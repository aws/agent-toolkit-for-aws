#!/usr/bin/env python3
"""The people's side of the labeling seed: fold what they returned, and check the fold.

The cold-start sample, the merge onto a local labeled file and the dataset-transformation
overlay are the SDK's (code_templates/seed_bootstrap.py); this script is the human-in-the-
loop fold (hil) and its check as commands, over the SDK's fold_human_labels, append_to_seed
and check_fold (operators.seed.bootstrap).


  hil   - HUMAN-IN-THE-LOOP fold. Merge the rows people reviewed (the cold-start
          sample, or the labeling job's review DataSet rows) with the labels they
          returned into a seed, score the spot-check, and count the confirmed and
          corrected rows per review reason.



  check - after every returned export, prove the fold happened, and with --labels that
          the overlay (or a merged local file) carries each reviewer label (full-loop
          Step 7b).

Provenance (the seed-row contract the labeling job's finalizer reads as human gold).
Every seed row carries `provenance`, one of:
  human_verified - a human assigned or confirmed the gold label: a routed row
                   (below the cutoff or failed) or a row of the cold-start sample
  spot_checked   - a human reviewed a row of the spot-check (the job's `split:
                   spot_check`, or `_review_reason` "calibration" / "audit")
  auto_approved  - the model's own label (a labeling job writes it on every model
                   label); such a row is never gold
plus the legacy `_bootstrap: hil` marker. In hil mode the provenance is set PER ROW
from the review row's `split` or routing tag
(io_utils.review_reason_of), read from the ORIGINAL review row, never from the export
(human-in-the-loop drops `split` from its output), so one mixed review file needs no
splitting. A hil row also records `source_export` (the --labels file) and `annotator`
when the export names a reviewer (annotator, annotator_id, reviewer, reviewer_id,
completed_by_profile or Label Studio's numeric completed_by, in that order). A routed
review row gets the model's answer back from the side file the job wrote beside the
review rows (`review_rows.model_output.jsonl`, or `review.model_output.jsonl` beside a
local review file). A return marked unsure or skipped (`verdict` or `status`:
unsure / skip / skipped) is NOT absorbed as gold; it is counted as
`sample_unresolved`. Ids join as strings. An id with several decided returns (a Label
Studio task with maximum_annotations above 1) is folded once when they agree; when
they disagree it is left out and listed under `conflicting_ids`.

Usage:
    # hil: fold the returned labels on the corpus run's review set. The job's side file
    # gives each row's id, split and model answer; no review rows are downloaded
    python fold_review.py hil --model-output review.model_output.jsonl \
        --labels hil_export.jsonl --job-summary labeling_summary.json \
        --out review_seed.jsonl --id-field id --export-id-field record_id \
        --label-field corrected_completion
    # hil on a local review file (the cold-start sample, or review rows downloaded for
    # a relabel pass): --sample gives the rows' text, so the fold can --append
    python fold_review.py hil --sample review.jsonl --labels hil_export.jsonl \
        --model-output review.model_output.jsonl --job-summary labeling_summary.json \
        --out hil_seed.jsonl --append seed.jsonl --id-field id

    # check: after every returned export, prove the fold happened and the overlay
    # carries the reviewer's labels
    python fold_review.py check --export hil_export.jsonl --seed seed.jsonl \
        --labels overlay.jsonl --id-field id --gt-field gt_label --pred-field label

check exits 1 when any decided row of the export (not unsure / skipped) is missing
from the seed as a human row, or, with --labels, when the overlay (or the merged local
file) does not carry the reviewer's label for it; when export rows name an id but none has a
--gt-field or --label-field column (pass --label-field); and when an id's annotations
disagree (`conflicting_ids`). With --sample (the cold-start sample) it also exits 1
unless every sample row has exactly one decided label in the export.

hil exits 2 (and writes no seed) when a non-empty export shares no id with the sample
(an id-space mismatch: pass --export-id-field, e.g. record_id for a local review) or
when nothing was kept and no export row has a --gt-field or --label-field column. Rows
that join but carry a null label are skipped as unlabeled. --append SEED also appends
the folded rows to SEED through a temp file and a rename; the same fold run again
appends nothing, and a fold whose ids are only partly in SEED exits 2.

The feedback row. The export carries the row id (`record_id` for a local
review, the review DataSet's `id` otherwise: --export-id-field), the corrected value
under the task's prediction field or `corrected_completion` (--label-field), and
`status` (`completed` / `skipped`). `split` is read from the original review row.

Spot-check verdict (hil). When the sample carries spot-check rows, hil counts their
errors: a row the reviewer corrected (the label does not confirm the model's answer:
--pred-field, else the side file's prediction field, else the first of label / score /
judge_score / entities / answer the row carries; scored by review_verdict, the rule
review_outcome uses), plus a row that came back unsure or skipped or did not come back
at all, plus a row whose reviewers disagree. At SPOT_CHECK_WITHDRAW_AT (7) errors or
more the spot-check fails: `spot_check_failed: true`, `spot_check_errors: "n of m"`,
stderr says so, and hil exits 3 after writing the seed. The report also carries
`spot_check.confirmed` and `spot_check.agreement_rate` (confirmed over the rows that
came back with a model answer): the spot-check agreement rate the hand-off reports
beside the certified bound. What a failure means is the basis (`spot_check.basis`):
"calibrated" when the model's answers carry `calib_accepted` (the labeling job writes
it on a certified run), so a failure withdraws the certificate
(`certificate_withdrawn: true`); "bar" when the rows were routed on the fixed 0.85 bar
(a run with no target, no gold, or a task without a promise), so a failure means the
auto-accepted rows do not meet the bar. When the answers carry neither, pass the job's
`labeling_summary.json` as --job-summary and the basis follows its `Status`: Certified
is "calibrated", anything else "bar"; without it the basis is "unknown" and the
verdict says so instead of guessing. A returned spot-check row with no model answer to
compare (no side file joined) counts as `no_model_answer`, neither an error nor a
confirmation, and leaves the verdict incomplete (`complete: false`).

hil and check read a Label Studio export as it is (flatten_export): each annotation is
one returned row, with the id from its task's `data`, the label from its answer to the
control named --gt-field or --label-field, and the reviewer from the annotation.

hil puts the model's answer back on every folded review row from the side file
(--model-output; by default io_utils.model_output_candidates(--sample), when one
exists; a --model-output that does not exist exits 2). Its report then adds
`model_output_joined` and `review_outcome`: per review reason, how many rows the
person's label confirmed and how many it corrected, scored by io_utils.task_correct
for the task the side file's prediction field names (review_verdict), at its defaults
unless --qa-match (qa) or --correct-tolerance (llm_judge) gives another rule;
`no_model_answer` counts the rows the model gave no answer for, and `not_scored` the
rows whose prediction field no task rule scores (a summary). A returned row whose
--label-field value is blank counts as unlabeled (`empty_labels`); a qa answer may be
blank, the unanswerable answer.

sample draws the first n positions of a random.Random(--seed) shuffle of the rows and
writes them in file order, so the same rows and seed always give the same sample and
a 200-row sample is part of the 400-row one. --input is the Split job's random sample
(a local JSONL or an s3:// URI; the file people will label), never the corpus itself,
which stays behind the API. A row with no `id`, or a null one, gets str(<i>), its position in the
corpus, which is the id the labeling job gives it; that position is known only when
--corpus-rows says the input is the whole corpus. It exits 2 and writes nothing when
the file is above the labeling job's row limit, two rows share an id, an id-less row
is in a sample of a larger corpus, a row lacks a non-default --id-field, a row is not a JSON object, the file has no rows, or no row
has any of --text-fields. The report adds `warning` when the target is above what the
sample can certify even with no errors; `whole_corpus` is true only when --corpus-rows
says the sample covers the corpus (people then label every row and nothing needs a
certificate).

merge moves each matched row's model answer under `_model_output`, sets the prediction
to the person's label, copies the seed row's `provenance` and routing tag, and marks
the row `_labeled_by: people` (io_utils.labeled_by_people). Only seed rows with a human
provenance and a gold value are merged. It exits 1 and writes nothing when such a seed
row has no labeled row with its id or that row's input fields differ from the seed
row's, and 2 when the seed has no row to merge or --labels has no --pred-field column.
"""

import argparse
import json
import logging
import os
import sys

from io_utils import sdk_missing  # noqa: E402
from io_utils import (  # noqa: F401 (BLIND_FIELD_SET, NO_PROMISE_TASKS re-exported); noqa: E402
    BLIND_FIELD_SET,
    NO_PROMISE_TASKS,
    fold_report_path,
    job_summary_sha256,
    model_output_candidates,
)
from io_utils import read_jsonl as _read_jsonl  # noqa: F401 (shared JSONL reader)
from io_utils import (  # noqa: F401 (BLIND_FIELD_SET, NO_PROMISE_TASKS re-exported); noqa: E402
    record_entry,
    split_state,
)
from io_utils import write_jsonl as _write_jsonl  # noqa: F401 (shared JSONL writer)
from io_utils import (  # noqa: F401 (BLIND_FIELD_SET, NO_PROMISE_TASKS re-exported); noqa: E402
    write_text_atomic,
)

# The fold, its check and the seed's labels are the SDK's (operators.seed); the names the
# tests reach through this module are re-exported with them.
try:
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import (  # noqa: F401
        MIN_CALIBRATION_TARGET,
        calibration_sample_size,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.bootstrap import (
        append_to_seed,
        check_fold,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.bootstrap import (  # noqa: F401
        fold_human_labels as assemble_hil_seed,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.bootstrap import (
        review_path_of,
        review_rows_from_side_file,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.bootstrap import (
        spot_check_message as _spot_check_message,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.cold_start import (  # noqa: F401
        certificate_warning,
        cold_start_sample_size,
        draw_sample,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels import (
        _WARNED_UNSCORED_FIELDS,
        NO_MODEL_ANSWER,
        SeedAppendRefused,
        build_overlay,
        drop_people_rows_from_review,
        known_spot_check_path,
        merge_seed_labels,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels import (  # noqa: F401
        model_source as _model_source,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels import (
        overlay_handoff,
        review_verdict,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels import (
        seed_input_fields as _seed_input_fields,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels import (
        seed_review_tag as _seed_review_tag,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels import (
        seed_rows_for_overlay,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.review_export import (
        HUMAN_PROVENANCE,
        HUMAN_VERIFIED,
        SPOT_CHECKED,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.review_export import (  # noqa: F401
        conflict_hint as _conflict_hint,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.review_export import (
        flatten_export,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.review_export import (
        id_key as _id_key,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.review_export import (
        provenance_for_review,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.review_export import (
        span_fields as _span_fields,
    )
    from sagemaker.core import Attribution, set_attribution
except ImportError as e:
    sys.exit(sdk_missing(e))

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)


class _StderrNow(logging.StreamHandler):
    """Writes to whatever sys.stderr is when the record is emitted (a redirected stderr sees it)."""

    stream = property(lambda self: sys.stderr, lambda self, v: None)


# The fold's notes (a prediction field no task rule scores) are the SDK seed module's
# warnings; the command line prints them as the fold always did.
_seed_log = logging.getLogger(
    "sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels"
)
if not any(isinstance(h, _StderrNow) for h in _seed_log.handlers):
    _handler = _StderrNow()
    _handler.setFormatter(logging.Formatter("fold_review: %(message)s"))
    _seed_log.addHandler(_handler)
    _seed_log.setLevel(logging.WARNING)
    _seed_log.propagate = False


def spot_check_message(report):
    """The stderr line for a report's spot-check verdict: the SDK's, under this script's
    name, with the flag or the full-loop step that acts on it."""
    sc = report["spot_check"]
    hints = [
        h
        for cond, h in (
            (sc.get("no_model_answer"), "Pass the side file as --model-output."),
            (sc.get("basis") == "unknown", "Pass it as --job-summary."),
            (report.get("spot_check_failed"), "Next: full-loop Step 7b."),
        )
        if cond
    ]
    msg = _spot_check_message(report).rstrip("\n")
    return "fold_review: " + " ".join([msg] + hints) + "\n"


def write_jsonl_atomic(path, rows):
    """Write rows as JSONL with io_utils.write_text_atomic: an interrupted write leaves the
    old file whole, and the file keeps its old permission bits (or the umask's)."""
    write_text_atomic(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# Record-id names a flat human-in-the-loop export may carry. An annotation tool's own
# task number (Label Studio's task_id) never names a sample row, so it is not one.
_HIL_ID_FIELDS = ("id", "record_id")


def _require_id_join(sample_rows, human_labels, id_field, export_id_field=None):
    """Exit 2 when a non-empty export shares no id with the sample (`id_field` against
    `export_id_field`): an id-space mismatch, such as an export keyed by the tool's own
    task number, that an empty seed would hide."""
    export_id_field = export_id_field or id_field
    if not sample_rows or not human_labels:
        return
    sample_ids = {_id_key(r.get(id_field)) for r in sample_rows if isinstance(r, dict)}
    export_ids = {_id_key(h.get(export_id_field)) for h in human_labels if isinstance(h, dict)}
    sample_ids.discard(None)
    export_ids.discard(None)
    if sample_ids & export_ids:
        return
    present = sorted(
        {k for h in human_labels if isinstance(h, dict) for k in _HIL_ID_FIELDS if k in h}
    )
    hint = (
        f" The export carries {', '.join(present)}; pass --export-id-field with the "
        f"one that holds the sample's {id_field!r} values, or re-export with that id "
        f"carried through unchanged."
        if present
        else " The export carries neither id nor record_id: re-export "
        "with the sample's id carried through unchanged (a Label Studio task keeps "
        "it in its data)."
    )
    if any(isinstance(h, dict) and "task_id" in h for h in human_labels):
        hint += " task_id is the annotation tool's own task number, not the sample's id."
    sys.stderr.write(
        f"ERROR: the human-in-the-loop export joins zero rows of the sample on --id-field "
        f"{id_field!r} / --export-id-field {export_id_field!r} ({len(human_labels)} "
        f"export rows, {len(sample_rows)} sample rows).{hint} No seed written.\n"
    )
    sys.exit(2)


def _label_field_hint(gt_field, label_field):
    return (
        f"no export row carries a label under --gt-field {gt_field!r} or "
        f"--label-field {label_field!r}; pass --label-field <export label column>"
    )


def _require_some_label(human_labels, report, gt_field, label_field):
    """Exit 2 (no seed written) when the export is non-empty, nothing was kept or
    marked unsure, and no export row has a `gt_field` or `label_field` column: the
    export's label column has another name. (A row whose label is present but null is
    an unlabeled row, skipped as before.)"""
    has_column = any(
        isinstance(h, dict) and (gt_field in h or label_field in h) for h in human_labels
    )
    if (
        human_labels
        and not has_column
        and report.get("kept") == 0
        and not report.get("sample_unresolved")
    ):
        sys.stderr.write(
            f"ERROR: {_label_field_hint(gt_field, label_field)}. " "No seed written.\n"
        )
        sys.exit(2)


def _project_of(args, *paths):
    """The project whose run log records this fold: --project-dir, else the nearest frozen-split
    project above the first of `paths` that has one, else None (then nothing is recorded)."""
    if args.project_dir:
        return args.project_dir
    for path in paths:
        if path:
            found = split_state.nearest_project(path)
            if found:
                return found
    return None


def _record(project, kind, step, status, **fields):
    """One run-log entry through the shared writer; a missing project records nothing."""
    if not project:
        return None
    return record_entry(project, kind=kind, step=step, iteration=0, status=status, **fields)


def _read_known_spot_check(sample_path):
    """`overlay --review`'s (or `merge --review`'s) known spot-check verdicts beside the review file, or None."""
    path = known_spot_check_path(sample_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"ERROR: cannot read {path}: {e}. No seed written.\n")
        sys.exit(2)
    return doc if isinstance(doc, dict) else None


def _read_job_summary(summary_path):
    """A labeling job's labeling_summary.json as a dict, or None without one."""
    if not summary_path:
        return None
    try:
        with open(summary_path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        sys.stderr.write(
            f"ERROR: cannot read --job-summary {summary_path}: {e}. " "No seed written.\n"
        )
        sys.exit(2)
    return doc if isinstance(doc, dict) else None


def _job_status(summary_path):
    """The `Status` of a labeling job's labeling_summary.json, or None without one."""
    doc = _read_job_summary(summary_path)
    return doc.get("Status") if doc else None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="mode", required=True)

    h = sub.add_parser("hil", help="merge sampled rows with returned human labels")
    h.add_argument(
        "--sample",
        default=None,
        help="the rows people labeled: the cold-start sample or a review file. "
        "For a corpus run's review set, leave it out and pass "
        "--model-output: the fold takes each row's id and split from the "
        "job's side file, so review.jsonl is not needed",
    )
    h.add_argument("--labels", required=True, help="human labels (id + label per row)")
    h.add_argument("--out", required=True)
    h.add_argument("--id-field", default="id")
    h.add_argument(
        "--model-output",
        default=None,
        help="the side file for --sample (the job's review.model_output.jsonl), with the model's "
        "answer per routed row (default: the side file "
        "io_utils.model_output_path names for --sample, when it exists)",
    )
    h.add_argument(
        "--export-id-field",
        default=None,
        help="the export's id column when it differs from --id-field "
        "(a local review writes record_id); default: --id-field",
    )
    h.add_argument("--gt-field", default="gt_label")
    h.add_argument(
        "--label-field", default="label", help="export label field when --gt-field is absent"
    )
    h.add_argument(
        "--append",
        default=None,
        metavar="SEED",
        help="also append the folded rows to this seed in one atomic step "
        "(temp file + rename); a repeat of the same fold appends nothing, "
        "and a fold whose ids are partly in the seed already is refused "
        "(exit 2, nothing written)",
    )
    h.add_argument(
        "--pred-field",
        default=None,
        help="the model's answer field on the spot-check rows (default: the "
        "first of label, score, judge_score, entities, answer present)",
    )
    h.add_argument(
        "--qa-match",
        default=None,
        help="qa: the correctness rule the confirmed / corrected counts and the "
        "spot-check verdict use (exact, contains or f1>=X; default "
        "exact, the rule the labeling job certifies on)",
    )
    h.add_argument(
        "--project-dir",
        default=None,
        help="the project whose run log records the fold (default: the frozen-split "
        "project above --out, when there is one)",
    )
    h.add_argument(
        "--job-summary",
        default=None,
        help="the labeling job's labeling_summary.json: when the review rows' "
        "model answers carry no calib_accepted, the spot-check verdict's "
        "basis follows its Status (Certified: a failure withdraws the "
        "certificate; otherwise the auto-accepted rows missed the bar)",
    )
    h.add_argument(
        "--spot-check-off",
        action="store_true",
        help="the plan turned the spot-check review off (review_high_confidence: "
        "false): the job's split: spot_check rows give no verdict and an "
        "unreturned one is not a miss (no exit 3); returned ones fold as "
        "usual. The labels then carry no accuracy promise",
    )
    h.add_argument(
        "--correct-tolerance",
        type=float,
        default=None,
        help="llm_judge: max |pred - gold| that counts as confirmed "
        "(default 0.5; the job uses 5%% of the scale on a wider scale)",
    )

    c = sub.add_parser(
        "check",
        help="verify a returned export was folded into the seed "
        "and merged onto the labels (exit 1 if not)",
    )
    c.add_argument("--export", required=True, help="the human-in-the-loop export (id + label)")
    c.add_argument("--seed", required=True, help="the seed the hil rows were appended to")
    c.add_argument(
        "--labels",
        default=None,
        help="the overlay rows (overlay.jsonl, the corpus run) or a merged local "
        "labeled file (optional: also check it carries each reviewer label)",
    )
    c.add_argument(
        "--sample",
        default=None,
        help="the cold-start sample (optional): also check that every sample "
        "row has exactly one decided label in the export",
    )
    c.add_argument("--id-field", default="id")
    c.add_argument(
        "--export-id-field",
        default=None,
        help="the export's id column when it differs from --id-field; " "default: --id-field",
    )
    c.add_argument("--gt-field", default="gt_label")
    c.add_argument(
        "--label-field", default="label", help="export label field when --gt-field is absent"
    )
    c.add_argument(
        "--pred-field",
        default="label",
        help="the label field of --labels (score for ordinal, entities for ner)",
    )
    c.add_argument(
        "--project-dir",
        default=None,
        help="the project whose run log records the check (default: the frozen-split "
        "project above --seed, when there is one)",
    )

    args = ap.parse_args()

    if args.mode == "check":
        report = check_fold(
            _read_jsonl(args.export),
            _read_jsonl(args.seed),
            _read_jsonl(args.labels) if args.labels else None,
            id_field=args.id_field,
            gt_field=args.gt_field,
            label_field=args.label_field,
            pred_field=args.pred_field,
            export_id_field=args.export_id_field,
            sample_rows=_read_jsonl(args.sample) if args.sample else None,
        )
        print(json.dumps(report, indent=2))
        _record(
            _project_of(args, args.seed, args.export),
            "analysis",
            "seed-fold",
            "verified" if report.get("ok") else "failed",
            export=args.export,
            seed=args.seed,
            **({"labels": args.labels} if args.labels else {}),
            **{
                k: len(v) if isinstance(v, list) else v
                for k, v in report.items()
                if k
                in (
                    "folded",
                    "merged",
                    "not_merged",
                    "missing_from_seed",
                    "no_label_ids",
                    "conflicting_ids",
                    "sample_missing",
                    "sample_unsure",
                    "sample_conflicting",
                )
            },
        )
        if report.get("no_label_ids"):
            sys.stderr.write(
                f"fold_review check: {len(report['no_label_ids'])} export row(s) name "
                f"an id but {_label_field_hint(args.gt_field, args.label_field)}.\n"
            )
            sys.exit(1)
        if report.get("conflicting_ids"):
            sys.stderr.write(
                f"fold_review check: " f"{_conflict_hint(report['conflicting_ids'])}.\n"
            )
        gaps = [
            (k, what)
            for k, what in (
                ("sample_missing", "have no label in the export"),
                ("sample_unsure", "are marked unsure or skipped"),
                ("sample_conflicting", "have two different labels"),
            )
            if report.get(k)
        ]
        if gaps:
            sys.stderr.write(
                "fold_review check: people must label every sample row once: "
                + "; ".join(
                    f"{len(report[k])} sample row(s) {what} ("
                    + ", ".join(repr(i) for i in report[k][:5])
                    + (", ..." if len(report[k]) > 5 else "")
                    + ")"
                    for k, what in gaps
                )
                + ". Get one label for each, put it in the export in place of the "
                "row's earlier rows, then fold and check again.\n"
            )
        if report["missing_from_seed"] or report.get("not_merged"):
            sys.stderr.write(
                "fold_review check: the export is not fully folded "
                f"({len(report['missing_from_seed'])} decided row(s) missing from the seed"
                + (
                    f", {len(report['not_merged'])} not merged onto the labels"
                    if "not_merged" in report
                    else ""
                )
                + "). Run the fold (and the merge) before the report.\n"
            )
        if not report["ok"]:
            sys.exit(1)
        return

    if args.qa_match is not None:
        from io_utils import parse_qa_match

        try:
            args.qa_match = parse_qa_match(args.qa_match)
        except ValueError as e:
            sys.stderr.write(f"ERROR: {e}. No seed written.\n")
            sys.exit(2)
    if args.sample is None and not args.model_output:
        sys.stderr.write(
            "ERROR: pass --sample (the rows people labeled) or --model-output "
            "(the job's review.model_output.jsonl). No seed written.\n"
        )
        sys.exit(2)
    if args.sample is None and args.append:
        sys.stderr.write(
            "ERROR: --append needs --sample: a fold from the side file alone carries no "
            "input text, and a seed row needs it for the next refinement. Leave --append "
            "out and pass both seeds to the overlay (--seed <seed.jsonl> --seed <--out>); "
            "for a relabel pass, download the review rows by the review DataSet ARN and "
            "fold with --sample. No seed written.\n"
        )
        sys.exit(2)
    if args.sample is None:
        try:
            sample = review_rows_from_side_file(_read_jsonl(args.model_output), args.id_field)
        except ValueError as e:
            sys.stderr.write(f"ERROR: {args.model_output}: {e}. No seed written.\n")
            sys.exit(2)
    else:
        sample = _read_jsonl(args.sample)
        # The review rows key the fold, the side file and the overlay: a null or
        # repeated id would join one person's label to two rows (hand-off requirements
        # A5, checked here too since the review set is small).
        seen, bad = set(), []
        for r in sample:
            key = _id_key(r.get(args.id_field)) if isinstance(r, dict) else None
            if key is None or key in seen:
                bad.append(key)
            seen.add(key)
        if bad:
            sys.stderr.write(
                f"ERROR: {args.sample} has {len(bad)} row(s) with a null or "
                f"repeated {args.id_field!r} (first: {bad[0]!r}); the fold "
                "joins on it. No seed written.\n"
            )
            sys.exit(2)
    human = flatten_export(
        _read_jsonl(args.labels),
        args.export_id_field or args.id_field,
        _span_fields(args.gt_field, args.label_field),
    )
    _require_id_join(sample, human, args.id_field, args.export_id_field)
    candidates = model_output_candidates(args.sample) if args.sample else [args.model_output]
    side_path = args.model_output or next(
        (c for c in candidates if os.path.exists(c)), candidates[0]
    )
    model_outputs = None
    if os.path.exists(side_path):
        model_outputs = {
            _id_key(rec.get("id")): rec
            for rec in _read_jsonl(side_path)
            if isinstance(rec, dict) and rec.get("id") is not None
        }
    elif args.model_output:
        sys.stderr.write(
            f"ERROR: --model-output {args.model_output} does not exist. " "No seed written.\n"
        )
        sys.exit(2)
    else:
        sys.stderr.write(
            f"fold_review hil: no side file at {' or '.join(candidates)}, so no "
            "model answer was "
            "joined. That is expected for the cold-start sample. A review file's side "
            "file (review.model_output.jsonl) goes with it: without it the folded "
            "rows carry no confidence, and calibration skips them.\n"
        )
    seed, report = assemble_hil_seed(
        sample,
        human,
        id_field=args.id_field,
        gt_field=args.gt_field,
        label_field=args.label_field,
        source_export=os.path.basename(args.labels),
        export_id_field=args.export_id_field,
        pred_field=args.pred_field,
        model_outputs=model_outputs,
        qa_match=args.qa_match,
        correct_tolerance=args.correct_tolerance,
        job_status=_job_status(args.job_summary),
        spot_check_reviewed=not args.spot_check_off,
        known_spot_check=_read_known_spot_check(args.sample or review_path_of(args.model_output)),
    )
    _require_some_label(human, report, args.gt_field, args.label_field)
    report.setdefault("model_output_joined", 0)
    if args.append:
        try:
            appended, already = append_to_seed(args.append, seed, args.id_field, args.gt_field)
        except SeedAppendRefused as e:
            sys.stderr.write(f"ERROR: {e}. No seed written.\n")
            sys.exit(2)
        report["appended_to_seed"] = appended
        if already:
            report["already_in_seed"] = len(already)
            sys.stderr.write(
                f"fold_review: all {len(already)} folded row(s) are already in "
                f"{args.append} (this fold ran before); nothing was appended.\n"
            )

    _write_jsonl(args.out, seed)
    if report.get("sample_unresolved"):
        sys.stderr.write(
            f"fold_review: {report['sample_unresolved']} returned row(s) were marked "
            "unsure or skipped; they were not added to the seed.\n"
        )
    if report.get("conflicting_ids"):
        sys.stderr.write(f"fold_review: {_conflict_hint(report['conflicting_ids'])}.\n")
    if report.get("empty_labels"):
        sys.stderr.write(
            f"fold_review: {report['empty_labels']} returned row(s) have an empty "
            "label; they count as unlabeled, since a blind reviewer gives the label "
            "itself.\n"
        )
    print(json.dumps(report, indent=2))
    # Persisted beside the seed so report.py shows the verdict and the agreement rate
    # next to the certified bound (the human-in-the-loop hand-off requirements, A3).
    with open(fold_report_path(args.out), "w", encoding="utf-8") as fh:
        # The job this fold belongs to, so report.py shows it only beside that job's
        # summary, not beside a re-run's (io_utils.job_summary_sha256).
        job_doc = _read_job_summary(args.job_summary)
        json.dump(
            dict(
                report,
                export=os.path.basename(args.labels),
                job_summary_sha256=job_summary_sha256(job_doc),
                spec_sha256=(job_doc or {}).get("SpecSha256"),
            ),
            fh,
            indent=2,
        )
        fh.write("\n")
    project = _project_of(args, args.out, args.append)
    fold_entry = _record(
        project,
        "artifact",
        "seed-fold",
        "folded",
        file=args.out,
        report=fold_report_path(args.out),
        export=args.labels,
        **{
            k: (len(v) if isinstance(v, list) else v)
            for k, v in report.items()
            if k
            in (
                "rows",
                "kept",
                "confirmed",
                "corrected",
                "not_returned",
                "sample_unresolved",
                "sample_unlabeled",
                "conflicting_ids",
                "empty_labels",
                "review_outcome",
            )
        },
    )
    if "spot_check_errors" in report:
        sc = report.get("spot_check") or {}
        _record(
            project,
            "analysis",
            "spot-check",
            (
                "failed"
                if report["spot_check_failed"]
                else ("incomplete" if sc.get("complete") is False else "passed")
            ),
            report=fold_report_path(args.out),
            errors=report["spot_check_errors"],
            agreement_rate=sc.get("agreement_rate"),
            basis=sc.get("basis"),
            fold=fold_entry,
        )
        sys.stderr.write(spot_check_message(report))
        if report["spot_check_failed"]:
            sys.exit(3)


if __name__ == "__main__":
    main()
