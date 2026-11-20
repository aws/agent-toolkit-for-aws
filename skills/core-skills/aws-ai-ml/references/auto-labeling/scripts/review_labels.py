#!/usr/bin/env python3
"""Label review through the labeling job: submit a review-only CreateJob (Config.Review),
wait for it (or, with --no-wait, return while it runs), and download its review/ files
(references/label-review.md).

    python scripts/review_labels.py --seed <review_seed.jsonl> --spec <work/labeling_spec_iter_N.md> \
        --text-fields <fields> --generation-model-id <id> --project-dir <proj> \
        --s3-prefix <s3://bucket/autolabel/PROJECT/> --role-arn <role> [--run-id <id>] \
        [--scope seed|golden] [--label-field gt_label] [--preds <file> ...] [--rules <json>] \
        [--judge-model-id <id> [--estimate-only] [--judge-scope candidates|all] [--max-judge-rows N]] \
        [--no-wait]

The job labels nothing; its review/ files land in --out-dir (default <proj>/audit, or
<proj>/audit/golden) only after every check passes, with decisions.csv for the seed scope.
A judged job needs the run log's --estimate-only entry for the same scope, judge settings and
inputs, and an unused approval naming it (used at submit). The submitted job's record is its
run-log `submitting` entry; a rerun under the same --run-id re-attaches from it only with
unchanged inputs (else it stops; --resubmit), never resubmitting a judged job.
With --no-wait (which needs --run-id) it prints the job's name, ARN and status and exits 0 while
the job runs; the same command again collects it.

The checks, the request, the approval rule and the read-back are
`sagemaker.ai_registry.data_preparer.auto_labeling.operators.review.request`; this script reads
the files, guards the split reads, uploads, submits, downloads and writes the run log.
"""

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io_utils import sdk_missing  # noqa: E402
from io_utils import (
    download_file,
    read_jsonl,
    read_run_entries,
    record_entry,
    upload_file,
    warn_client_read,
    write_text_atomic,
)
from labelcheck.lc_decide import (  # noqa: E402
    RUN_LOG_STEP,
    logged_decisions,
    review_inputs,
    spec_iteration,
)

try:
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import (
        check_run_id,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import client as job_client
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import (
        request as job_request,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import (
        run_context,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job.round import (
        default_run_id as _default_run_id,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.review import request as _lr
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.review.request import (  # noqa: F401
        CSV_FIELDS,
        MAX_JUDGE_ROWS,
        MAX_PREDICTIONS,
        MAX_PREDICTIONS_BYTES,
        MAX_ROWS,
        MAX_ROWS_PER_TEXT,
        MAX_RULES_BYTES,
        OUTPUT_FILES,
        REVIEW_CONTRACT_VERSION,
        REVIEW_SUBDIR,
        SDG_OUTPUT_SUBDIR,
        csv_cell,
        review_folder,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.split import (
        SplitGuardError,
        find_splits_dir,
        load_state,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.split import (
        read_rows as _split_rows,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.split_state import (
        guard_split_read,
    )
    from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError
    from sagemaker.core import Attribution, set_attribution
    from sagemaker.core.helper.session_helper import Session
except ImportError as e:
    sys.exit(sdk_missing(e))


def _session_region():
    """The region of the SageMaker SDK's default session (the AWS config), or None."""
    try:
        return Session().boto_region_name
    except Exception:  # noqa: BLE001 - no region configured: the caller asks for one
        return None


def _check_file(path, cap, what):
    """Exit before any upload when a file is not local, empty or over its byte cap."""
    local = not path.startswith("s3://") and os.path.isfile(path)
    try:
        _lr.check_file_size(
            path,
            os.path.getsize(path) if local else None,
            Path(path).read_text(encoding="utf-8", errors="replace") if local else "",
            cap,
            what,
        )
    except DataPreparerOperatorError as e:
        sys.exit(str(e))


def rows_to_send(args, rows, fields):
    """(rows the job reviews, test ids left out): `label_review.review_rows` over the frozen
    split's state and gold, with the read guarded as its step."""
    sdir = find_splits_dir(None, args.project_dir)
    st = load_state(sdir) if sdir else None
    allowed = {"test"} if args.scope == "golden" else {"dev", "val"}
    gold = (
        {
            str(r.get(st["id_field"])): r.get(st["label_field"])
            for s in allowed
            for r in _split_rows(os.path.join(sdir, f"{s}.jsonl"))
        }
        if st
        else {}
    )
    try:
        keep, test, step, allowed = _lr.review_rows(
            rows,
            scope=args.scope,
            label_field=args.label_field,
            fields=fields,
            seed_name=args.seed,
            state=st,
            split_gold=gold,
        )
    except DataPreparerOperatorError as e:
        sys.exit(str(e))
    guard_split_read(args.seed, step, allowed, project_dir=args.project_dir, rows=keep)
    return keep, test


def write_decision_files(out_dir, project_dir):
    """decisions.csv: a row for the same item version (item_sha256) is kept as it is, blank or
    not, else the run log's decision for an unchanged item fills it; any other filled row is
    added to decisions.prev.csv. Cells a spreadsheet would run as a formula are escaped."""
    items = read_jsonl(os.path.join(out_dir, "contradictions.jsonl"))
    dpath, ppath = os.path.join(out_dir, "decisions.csv"), os.path.join(
        out_dir, "decisions.prev.csv"
    )

    def read(path):
        with open(path if os.path.exists(path) else os.devnull, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    rows, prev, undecided, apart = _lr.decision_csv(
        items, logged_decisions(project_dir, items), read(dpath), read(ppath)
    )
    if prev is not None:  # appended to the earlier kept-apart rows
        write_text_atomic(ppath, _lr.csv_text(prev))
    write_text_atomic(dpath, _lr.csv_text(rows))
    return len(items), undecided, apart


def submitted_review_job(entries, review_run):
    """The run-log entry of the review job `review_run` (``<run id>-<scope>-<mode>``) last
    submitted, or None: the newest ``submitting`` entry naming it, unless the entry right after
    it is the service's ``refused`` (CreateJob made no job). It carries what a re-attach needs
    (`job_name`, `request_sha256`, `s3_run`, `approval`), so the run log is the only record of
    a submitted review job."""
    found, previous = None, None
    for e in entries:
        if e.get("kind") != "analysis" or e.get("record") != review_run:
            continue
        if e.get("status") == "submitting" and e.get("request_sha256"):
            found = e
        elif e.get("status") == "refused" and previous is found:
            found = None
        previous = e
    return found


def _read_job(args, job, document, out_dir, rows, dropped, fail):
    """The job's review/ files, moved into out_dir only after every check passes; the summary."""
    ended = _lr.job_ended_message(job)
    if ended:
        fail(ended, job["job_status"].lower(), job_name=job["job_name"])
    folder = review_folder(
        document["OutputDataConfig"]["OutputS3Uri"], job["job_name"], args.region
    )
    tmp = tempfile.mkdtemp(dir=out_dir, prefix=".incoming-")
    try:
        for name in OUTPUT_FILES[args.scope]:
            download_file(folder + name, os.path.join(tmp, name), args.region)
        summary = json.loads(Path(tmp, "summary.json").read_text(encoding="utf-8"))
        routed = read_jsonl(os.path.join(tmp, "routed.jsonl")) if args.scope == "golden" else None
        try:
            _lr.check_summary(
                summary,
                scope=args.scope,
                judge_model_id=args.judge_model_id,
                estimate_only=args.estimate_only,
                routed_rows=len(routed) if routed is not None else None,
            )
        except DataPreparerOperatorError as e:
            fail(str(e))
        for name in OUTPUT_FILES[args.scope]:
            os.replace(os.path.join(tmp, name), os.path.join(out_dir, name))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    decisions = None
    if args.scope != "golden":
        items, undecided, apart = write_decision_files(out_dir, args.project_dir)
        decisions = {"items": items, "undecided_items": undecided, "decisions_kept_apart": apart}
    return _lr.review_result(
        job_name=job["job_name"],
        scope=args.scope,
        rows_sent=len(rows),
        test_rows_left_out=dropped,
        summary=summary,
        out_dir=out_dir,
        routed_rows=len(routed) if routed is not None else None,
        decisions=decisions,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--seed",
        required=True,
        help="the labeled rows (local JSONL with ids); with a frozen split, its dev and val rows",
    )
    ap.add_argument("--spec", required=True)
    ap.add_argument("--text-fields", required=True, help="comma-separated input fields")
    ap.add_argument(
        "--generation-model-id",
        required=True,
        help="the trial run's model; CreateJob needs one model config (no row is labeled)",
    )
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--scope", default="seed", choices=("seed", "golden"))
    ap.add_argument("--label-field", default="gt_label")
    ap.add_argument(
        "--preds", action="append", default=[], help="a local dev or val prediction file; up to 4"
    )
    ap.add_argument(
        "--rules", default=None, help="a local keyword_rules.json drafted from the spec"
    )
    ap.add_argument(
        "--judge-model-id", default=None, help="runs the guideline judge (one call per row)"
    )
    ap.add_argument("--judge-scope", default=None, choices=("candidates", "all"))
    ap.add_argument("--max-judge-rows", type=int, default=None)
    ap.add_argument(
        "--estimate-only", action="store_true", help="no model call: the judge's cost estimate"
    )
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--s3-prefix", default=os.environ.get("AUTOLABEL_S3_PREFIX"))
    ap.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        help="the trial run's region; default: the session's",
    )
    ap.add_argument("--role-arn", default=os.environ.get("AUTOLABEL_ROLE_ARN"))
    ap.add_argument("--run-id", default=os.environ.get("RUN_ID"))
    ap.add_argument(
        "--resubmit",
        action="store_true",
        help="submit a new job even though this --run-id already names one with other content",
    )
    ap.add_argument(
        "--no-wait",
        action="store_true",
        help="submit (or re-attach to) the job and return while it runs; rerun the same command "
        "with the same --run-id to collect it",
    )
    args = ap.parse_args(argv)
    set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
    if args.no_wait and not args.run_id:
        ap.error("--no-wait needs --run-id: the rerun that collects the job re-attaches by it")
    if not args.region:  # the session's region (the AWS config), never a fixed one
        args.region = _session_region()
        if not args.region:
            ap.error("no AWS region: pass --region (the trial run's region) or set AWS_REGION")
    fields = [f.strip() for f in args.text_fields.split(",") if f.strip()]
    try:  # client checks, before anything is read or uploaded
        _lr.check_review_arguments(
            s3_prefix=args.s3_prefix,
            preds=args.preds,
            scope=args.scope,
            judge_model_id=args.judge_model_id,
            estimate_only=args.estimate_only,
            max_judge_rows=args.max_judge_rows,
            judge_scope=args.judge_scope,
            label_field=args.label_field,
            fields=fields,
        )
    except DataPreparerOperatorError as e:
        sys.exit(str(e))
    args.judge_scope = args.judge_scope or "candidates"
    try:
        all_rows = read_jsonl(args.seed)
        rows, test = rows_to_send(args, all_rows, fields)
        spec_text = Path(args.spec).read_text(encoding="utf-8")
        if args.judge_model_id and not spec_text.strip():
            raise ValueError("the judge reads the spec, and --spec is blank")
    except (OSError, ValueError, SplitGuardError) as e:
        sys.exit(f"cannot read --seed or --spec: {e}. Nothing was uploaded.")
    for p in args.preds:
        _check_file(p, MAX_PREDICTIONS_BYTES, "--preds")
        try:
            guard_split_read(p, RUN_LOG_STEP, {"dev", "val"}, project_dir=args.project_dir)
            hit = _lr.test_predictions(read_jsonl(p), test) if args.scope == "seed" else []
            if hit:
                raise SplitGuardError(f"it predicts {len(hit)} test row(s) (e.g. {hit[:3]})")
        except (OSError, ValueError, SplitGuardError) as e:
            sys.exit(f"split guard: --preds {p!r}: {e}. Nothing was uploaded.")
    if args.rules:
        _check_file(args.rules, MAX_RULES_BYTES, "--rules")
    warn_client_read("review_labels", len(rows))
    seed_text = _lr.seed_text(rows, args.label_field, fields)  # the job reads nothing else
    _, content_sha = _lr.content_digest(
        spec_text,
        seed_text,
        [Path(p).read_bytes() for p in args.preds],
        Path(args.rules).read_bytes() if args.rules else None,
    )
    inputs = review_inputs(
        args.spec, args.seed, args.project_dir
    )  # what apply_label_decisions.py checks
    step = _lr.step_for(args.scope)
    run_id = args.run_id or _default_run_id()
    try:
        run_slug = check_run_id(run_id)
    except ValueError as e:
        sys.exit(str(e))
    # One sub-prefix per scope and kind of job, so an estimate and a judged job never
    # share an output folder; the submitted job's record is its run-log entry, keyed by run id.
    mode = "estimate" if args.estimate_only else ("judge" if args.judge_model_id else "checks")
    out_dir = args.out_dir or os.path.join(
        args.project_dir, "audit", *(["golden"] if args.scope == "golden" else [])
    )
    os.makedirs(out_dir, exist_ok=True)
    record = f"{run_slug}-{args.scope}-{mode}"  # the review run the run-log entries name
    entries = read_run_entries(args.project_dir)
    resume = submitted_review_job(entries, record) if args.run_id and not args.resubmit else None
    nonce = f"-{uuid.uuid4().hex[:12]}" if args.resubmit else ""  # its own sub-prefix
    s3_run = (resume or {}).get("s3_run") or run_context(run_id).s3_prefix(args.s3_prefix).rstrip(
        "/"
    ) + f"/review-{args.scope}-{mode}{nonce}/"
    pred_uris = [s3_run + f"review/predictions_{i}.jsonl" for i in range(len(args.preds))]
    rules_uri = args.rules and s3_run + "review/keyword_rules.json"
    try:
        document = job_request.build_labeling_request(
            task="classification",
            text_fields=fields,
            spec_s3_uri=s3_run + "labeling/spec.md",
            model_ids=[args.generation_model_id],
            dataset_name=job_request.scratch_dataset_name(
                "autolabel", f"review-{args.scope}", run_slug
            ),
            output_s3_uri=s3_run + "output/",
            input_s3_uri=s3_run + "input/seed.jsonl",
        )
    except job_request.LabelingRequestError as e:
        sys.exit(f"review request refused before anything was uploaded: {e}")
    document["GenerationConfig"]["DatasetOptions"]["Config"]["Review"] = _lr.review_config(
        label_field=args.label_field,
        scope=args.scope,
        pred_uris=pred_uris,
        rules_uri=rules_uri,
        judge_model_id=args.judge_model_id,
        judge_scope=args.judge_model_id and args.judge_scope,
        max_judge_rows=args.judge_model_id and args.max_judge_rows,
        estimate_only=args.estimate_only,
    )
    # A re-run with the same --run-id re-attaches to its job only when the request and
    # every file it uploads are unchanged; checked before any upload.
    req_sha = _lr.request_digest(document, content_sha)
    try:
        _lr.check_resume(resume, req_sha, run_id=run_id, mode=mode, record=record)
    except DataPreparerOperatorError as e:
        sys.exit(str(e))
    approval = resume.get("approval") if resume else None  # a re-attach needs no new approval
    if mode == "judge" and not resume:
        approval = _lr.unused_approval(
            entries,
            step,
            content_sha,
            judge_model_id=args.judge_model_id,
            judge_scope=args.judge_scope,
            max_judge_rows=args.max_judge_rows,
        )
        if not approval:
            sys.exit(_lr.judge_needs_approval_message(args.scope))
    iteration = spec_iteration(args.spec)

    def _job_entry(status, **fields):
        return record_entry(
            args.project_dir, **_lr.job_event(step, iteration, status, record, approval, **fields)
        )

    def _fail(msg, status="failed", rerun=None, **fields):
        _job_entry(status, reason=str(msg)[:500], **fields)
        sys.exit(f"{msg}\n{_lr.rerun_hint(mode) if rerun is None else rerun}")

    try:  # a pure re-attach uploads nothing: the job's files are in place
        uploads = (
            []
            if resume
            else [
                (spec_text, s3_run + "labeling/spec.md", "DatasetSpecification.SpecS3Uri"),
                (seed_text, s3_run + "input/seed.jsonl", "InputDataS3Uri"),
            ]
        )
        for text, uri, field in uploads:
            job_client.upload_text(
                text,
                uri,
                args.region,
                field=field,
                max_bytes=job_request.MAX_SPEC_BYTES if field.startswith("Dataset") else None,
            )
        for path, uri in (
            [] if resume else zip(args.preds + [args.rules], pred_uris + [rules_uri])
        ):
            if path:
                upload_file(path, uri, args.region)
    except job_request.LabelingRequestError as e:
        _fail(e, "refused")

    def _on_submit(
        rec,
    ):  # before CreateJob, so a timeout re-attaches and the yes is used; a refusal supersedes it
        if resume and mode == "judge":
            _fail(
                f"judged review job {resume.get('job_name')} ended Failed or Stopped, or is gone, and its yes is "
                "used: a new judged job needs --resubmit and a new yes."
            )
        _job_entry(
            "submitting",
            job_name=rec["job_name"],
            job_arn=rec.get("job_arn"),
            request_sha256=req_sha,
            s3_run=s3_run,
            submitted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    try:
        job = job_client.submit_labeling_job(
            document,
            region=args.region,
            role_arn=args.role_arn,
            base_job_name="autolabel-review",
            on_submit=_on_submit,
            resume_job=resume or None,
            option_fields=["Review"],
            wait=not args.no_wait,
        )
    except (job_client.CreateJobRefused, job_client.LabelingBackendUnavailable) as e:
        # CreateJob made no job: the `refused` entry below supersedes the `submitting` one
        if isinstance(
            e, job_client.LabelingBackendUnavailable
        ):  # the account cannot run labeling jobs: no other review path
            _fail(
                f"CreateJob refused the review request: {e}",
                "refused",
                rerun="This account cannot run labeling jobs: fix the account's access or use another account.",
            )
        if isinstance(e, job_client.OptionRefused):
            e = f"the deployed service refused Config.Review; the service says: {e}"
        _fail(
            f"CreateJob refused the review request: {e}",
            "refused",
            rerun="No job was created: fix what the service names, then rerun with the same --run-id.",
        )
    except RuntimeError as e:
        # The job may still be running (a wait timeout): its `submitting` entry stays, so the same --run-id
        # re-attaches with no upload and no new yes; --resubmit would start, and bill, a second job.
        _fail(
            f"the review job did not complete: {e}",
            rerun="Rerun the same command with the same --run-id to re-attach (nothing is uploaded and "
            "no new yes is needed); --resubmit starts a second, billed job.",
        )
    _job_entry("reattached" if job.get("reattached") else "submitted", job_name=job.get("job_name"))
    if job.get("job_status") not in (
        "Completed",
        "Failed",
        "Stopped",
    ):  # --no-wait: the job runs on
        print(
            json.dumps(
                {
                    "job_name": job.get("job_name"),
                    "job_arn": job.get("job_arn"),
                    "job_status": job.get("job_status"),
                    "run_id": run_id,
                    "collect": "rerun this command with the same --run-id; it re-attaches, uploads "
                    "nothing and needs no new yes",
                }
            )
        )
        return 0
    try:
        out = _read_job(
            args,
            job,
            document,
            out_dir,
            rows,
            len(all_rows) - len(rows) if args.scope == "seed" else 0,
            _fail,
        )
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - any read-back failure is a run-log entry, then raised
        _job_entry("failed", job_name=job.get("job_name"), reason=f"{type(e).__name__}: {e}"[:500])
        raise
    out["run_log_entry"] = record_entry(
        args.project_dir,
        **_lr.review_event(
            step,
            iteration,
            estimate_only=args.estimate_only,
            job_name=job["job_name"],
            run_id=run_slug,
            judge_model_id=args.judge_model_id,
            judge_scope=args.judge_scope,
            max_judge_rows=args.max_judge_rows,
            content_sha=content_sha,
            inputs=inputs,
            estimate=out["estimate"],
            summary_path=os.path.abspath(os.path.join(out_dir, "summary.json")),
        ),
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
