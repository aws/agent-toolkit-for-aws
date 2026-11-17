#!/usr/bin/env python3
"""Golden-row cleaning before the corpus run (references/label-review.md, Golden rows).

Only a person changes a golden (--eval) row: a row the person relabels leaves the
certificate's rows, a confirmed row stays, every other row is copied byte for byte.
route writes the routed rows as a blind review file and the manifest; apply folds the
person's export into golden_reviewed.jsonl; check_reviewed (the corpus run's
--golden-review) derives everything again and refuses any other change.

The checks are `sagemaker.ai_registry.data_preparer.auto_labeling.operators.review.golden`;
this script writes the files they return and the run-log entries of each golden-row read.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io_utils import (  # noqa: E402
    _run_log,
    record_entry,
    sdk_missing,
    warn_client_read,
    write_text_atomic,
)

try:
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.review import golden as _gr
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.review.golden import (  # noqa: F401
        MANIFEST_FILE,
        MANIFEST_VERSION,
        MARK_FIELD,
        PERSON_STATUSES,
        RESOLVED_KEYS,
        REVIEW_FILE,
        REVIEW_REASON,
        REVIEWED_FILE,
        RUN_LOG_STEP,
        GoldenReviewError,
        has_mark,
        manifest_text,
        read_manifest,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.review_export import (  # noqa: F401
        HUMAN_VERIFIED,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.split import (
        find_splits_dir,
        nearest_project,
    )
    from sagemaker.core import Attribution, set_attribution
except ImportError as e:
    sys.exit(sdk_missing(e))

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)


def _log_reads(events, eval_path, project_dir=None):
    """A golden-row read's run-log entries, in the project of the frozen split."""
    if not events:
        return
    root = project_dir or os.path.dirname(
        os.path.abspath(find_splits_dir(eval_path, nearest_project(eval_path)))
    )
    for ev in events:
        record_entry(root, **ev)


def route(
    eval_path,
    routed_path,
    out_dir,
    text_fields,
    label_field="gt_label",
    id_field="id",
    label_set=None,
    project_dir=None,
):
    """Write the review file and the manifest; returns the manifest."""
    res = _gr.route(
        eval_path,
        routed_path,
        out_dir,
        text_fields,
        label_field,
        id_field,
        label_set=label_set,
        project_dir=project_dir,
    )
    _log_reads(res.events, eval_path, project_dir)
    os.makedirs(out_dir, exist_ok=True)
    write_text_atomic(os.path.join(out_dir, REVIEW_FILE), res.review_text)
    write_text_atomic(os.path.join(out_dir, MANIFEST_FILE), manifest_text(res.manifest))
    return res.manifest


def apply(
    manifest_path, export_path, export_id_field=None, export_label_field="label", project_dir=None
):
    """Fold the person's export into golden_reviewed.jsonl beside the manifest."""
    res = _gr.apply(manifest_path, export_path, export_id_field, export_label_field, project_dir)
    _log_reads(res.events, res.manifest["eval"], project_dir)
    write_text_atomic(res.reviewed_path, res.reviewed_text)
    write_text_atomic(manifest_path, manifest_text(res.manifest))
    check_reviewed(manifest_path, res.reviewed_path, RUN_LOG_STEP, project_dir)
    return res.manifest


def check_reviewed(manifest_path, reviewed_path, step="certificate", project_dir=None):
    """Refuse a reviewed copy unless only a person decided it (the inputs, the manifest and
    every row are checked); returns {golden_rows, changed, confirmed, unresolved}."""
    eval_path = read_manifest(manifest_path)["eval"]
    try:
        res = _gr.check_reviewed(manifest_path, reviewed_path, step, project_dir)
    except (OSError, KeyError, ValueError) as e:
        _log_reads(getattr(e, "events", None), eval_path, project_dir)  # the read happened
        raise
    _log_reads(res.events, eval_path, project_dir)
    return res.to_json()


def _log(project_dir, kind, status, **fields):
    if not project_dir:
        return None
    return _run_log().write_entry(
        project_dir, kind=kind, step=RUN_LOG_STEP, iteration=0, status=status, **fields
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("route", help="write the flagged golden rows as a blind review file")
    r.add_argument("--eval", required=True, help="the corpus run's --eval file (golden rows)")
    r.add_argument("--routed", required=True, help="the review job's routed.jsonl (--scope golden)")
    r.add_argument("--text-fields", required=True, help="comma-separated input fields")
    r.add_argument("--label-field", default="gt_label")
    r.add_argument(
        "--label-set",
        default=None,
        help="JSON list of the labels a return may set (default: --eval's)",
    )
    r.add_argument("--out-dir", default=None, help="default <project-dir>/golden_review")
    r.add_argument("--project-dir", required=True)
    a_ = sub.add_parser("apply", help="fold the person's export into golden_reviewed.jsonl")
    a_.add_argument("--manifest", required=True)
    a_.add_argument("--export", required=True, help="the person's returned labels")
    a_.add_argument("--export-id-field", default=None, help="record_id for a local review")
    a_.add_argument(
        "--export-label-field", default="label", help="corrected_completion for a local review"
    )
    a_.add_argument("--project-dir", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "route":
            out_dir = a.out_dir or os.path.join(a.project_dir, "golden_review")
            fields = [f.strip() for f in a.text_fields.split(",") if f.strip()]
            m = route(
                a.eval,
                a.routed,
                out_dir,
                fields,
                a.label_field,
                project_dir=a.project_dir,
                label_set=json.loads(a.label_set) if a.label_set else None,
            )
            warn_client_read("golden_review route (golden rows)", m["golden_rows"])
            entry = _log(
                a.project_dir,
                "analysis",
                "routed",
                review=m["review"],
                manifest=os.path.abspath(os.path.join(out_dir, MANIFEST_FILE)),
            )
            out = _gr.route_summary(m, os.path.join(out_dir, MANIFEST_FILE), entry)
        else:
            m = apply(a.manifest, a.export, a.export_id_field, a.export_label_field, a.project_dir)
            entry = _log(
                a.project_dir,
                "artifact",
                "written",
                reviewed=m["reviewed"],
                manifest=os.path.abspath(a.manifest),
            )
            out = _gr.apply_summary(m, entry)
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"golden_review: {e}")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
