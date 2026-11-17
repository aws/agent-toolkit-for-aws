#!/usr/bin/env python3
"""Fill the human-in-the-loop hand-off spec for a labeling job's review set
(full-loop Step 7a).

The labeling job writes the review DataSet (every row below the cutoff, `split:
low_confidence`, plus the pinned spot-check, `split: spot_check`), and this script
turns the job's result into the spec human-in-the-loop takes as its input: the review
DataSet ARN (or the review rows' S3 URI when Hub finalization registered none), the
labeled DataSet ARN, the row count, the prediction field to write, and the label set
with its one-line definitions copied from the labeling spec. Spec only, no script:
human-in-the-loop's input table takes exactly these.

    python scripts/hil_handoff.py --summary <proj>/labeling_summary.json \
        --spec <proj>/labeling_spec.md --dataset-name <name> --job-arn <job_arn> \
        [--review-dataset-arn <arn> | --review-rows-uri <s3://...> | --review-rows <proj>/review.jsonl] \
        [--labeled-dataset-arn <arn>] [--out <proj>/hil_handoff.json]

`Data.LowConfidence` is the review DataSet ARN by default. Pass the local review file
(`--review-rows`) when it differs from the job's review set: after `fold_review.py
overlay --review` dropped the cold-start rows people labeled already. The row count then
comes from that file, not from the summary's RowsRouted + SpotCheckRows.

Prints the spec as JSON:

    {"ProjectName": "<DatasetName>-review",
     "TaskDescription": "Auto-labeling job <job>: <RowsRouted + SpotCheckRows> rows to
                         label. Label each row from the text alone; the model's answer is
                         not shown. The rows include <SpotCheckRows> spot-check rows ...",
     "Recommendation": "Write <prediction field> for each row.",
     "QuestionContext": "<label set and one-line definitions, from the spec>",
     "Data": {"LowConfidence": "<review DataSet ARN or review rows URI>",
              "Dataset": "<labeled DataSet ARN>", "Format": "jsonl"},
     "Contract": {...}}

Human-in-the-loop shows the rows blind, exports the id and the label per row, and stops:
it does not apply the corrections for an auto-labeling review set. `Contract.fold`,
`Contract.overlay` and `Contract.check` are Step 7b in order: fold the export (by the
review DataSet ARN, from the job's side file alone into review_seed.jsonl; from a local
review file, with --sample and --append into the seed), write the people's labels as an
overlay onto the labeled DataSet (the corpus run's labels stay behind the API, so they
are never merged on the client), and check that the overlay carries every reviewer
label. `Contract.corrections` says how the overlay reaches the labels: one
dataset-transformation job over [a dt-view of the labeled DataSet, the overlay], whose
output the `hub_ops` `promote` action (`code_templates/hub_ops.py`) adds as the labeled DataSet's next version
(the overlay's .handoff.json).

`Contract` states what each side does (the hand-off requirements doc): the reviewer sees
the input fields only (io_utils.REVIEW_HIDDEN_FIELDS and the prediction field are
never shown), the export carries the row id unchanged (`record_id` or `id`), the corrected
value under the prediction field (or `corrected_completion`), `status` completed or
skipped, and no `split` (the skill reads it from the job: the side file's `routed`, or the
review row of a local review file); unreturned
or skipped rows count as wrong; a spot-check row whose value equals the prediction is a
confirmation; the spot-check withdraws the promise at `SpotCheckWithdrawAt` errors.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from io_utils import STATED_CONFIDENCE_FIELDS  # noqa: E402
from io_utils import (
    GT_FIELD_FOR_PRED,
    VERBALIZED_CONFIDENCE_FIELDS,
    model_output_path,
    read_jsonl,
    review_hidden_fields,
    sdk_missing,
)

try:
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job.request import (
        PREDICTION_FIELDS,
        task_of_type,
    )
    from sagemaker.core import Attribution, set_attribution
except ImportError as e:
    sys.exit(sdk_missing(e))

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

# The export columns fold_review.py hil joins on, per review tool
# (human-in-the-loop/references/local-review-guide.md; a Label Studio export keeps the
# record's `id` in each task's data).
LOCAL_REVIEW_ID_FIELD = "record_id"
LOCAL_REVIEW_VALUE_FIELD = "corrected_completion"
STATUS_FIELD = "status"
SPLIT_FIELD = "split"
SPLIT_VALUES = ("low_confidence", "spot_check")
# fold_review.py overlay's output, beside the review file.
OVERLAY_FILE = "overlay.jsonl"


def _spec_section(spec_text, heading):
    """The spec's `### <heading>` section through the next heading, trimmed, or ""."""
    if not spec_text:
        return ""
    m = re.search(
        r"^#{1,4}\s*" + heading + r"[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)",
        spec_text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def label_set_block(spec_text):
    """The spec's Label Set section (its `### Label Set` heading through the next
    heading), trimmed; empty when the spec has none (ner: entity types; a summarization
    or qa spec has no label set, and the question context is then the task's rule)."""
    return _spec_section(spec_text, "Label Set")


def score_levels_block(spec_text):
    """The spec's Score Levels section, which a numeric task (ordinal, llm_judge)
    writes instead of the Label Set (labeling-spec-template.md), or ""."""
    return _spec_section(spec_text, "Score Levels")


def question_context(spec_text, task):
    """The label set and its definitions for the reviewer (or, for a numeric task, the
    score levels), and nothing else from the spec (the rules would steer them toward
    the model's answer)."""
    block = label_set_block(spec_text) or score_levels_block(spec_text)
    if block:
        return block
    return {
        "ner": "Mark every entity span in the text with its type.",
        "qa": "Copy the answer from the passage, or leave it empty when the passage has none.",
        "summarization": "Write a faithful, complete one-paragraph summary of the text.",
        "ordinal": "Rate the text on the spec's scale.",
        "llm_judge": "Score the text on the spec's scale.",
    }.get(task, "")


def blind_fields(pred_field):
    """The fields a reviewer must never see (requirement A2): io_utils'
    REVIEW_HIDDEN_FIELDS (every model-output field, every field the job writes, and
    the review row's `split` and `_review_reason`) and the prediction field."""
    return review_hidden_fields(pred_field)


# The side-file fold's output beside the review files (no --append: it carries no text).
REVIEW_SEED_FILE = "review_seed.jsonl"


def review_seed_path(review_path):
    """The side-file fold's output, beside the review files."""
    return os.path.join(os.path.dirname(review_path), REVIEW_SEED_FILE)


def _gt_flag(pred_field):
    gt = GT_FIELD_FOR_PRED.get(pred_field) if pred_field != "label" else None
    return f" --gt-field {gt}" if gt else ""


def fold_commands(review_path, pred_field="label", model_out=None, labels_path="<overlay.jsonl>"):
    """{"fold", "check"}: the Step 7b commands for a local review file's export. The fold
    appends to the seed and writes hil_seed.jsonl beside the review file, reading the
    model's answers from `model_out` (default: its side file); the check verifies that
    `labels_path` carries each reviewer label. The <...> placeholders are the agent's
    to fill. A prediction field other than `label` adds the task's gold field to both
    and the prediction field to the check."""
    model_out = model_out or model_output_path(review_path)
    d = os.path.dirname(review_path) or "."
    hil_seed = os.path.join(d, "hil_seed.jsonl")
    pred_field = pred_field or "label"
    task = ""
    if pred_field != "label":
        gt = GT_FIELD_FOR_PRED.get(pred_field)
        task = f" --gt-field {gt}" if gt else ""
    label = " --label-field <export label column>"
    return {
        "fold": (
            f"python scripts/fold_review.py hil --sample {review_path} "
            f"--model-output {model_out} "
            f"--labels <hil_export.jsonl> --out {hil_seed} --append <seed.jsonl> "
            f"--id-field id{task}{label}"
        ),
        "check": (
            "python scripts/fold_review.py check --export <hil_export.jsonl> "
            f"--seed <seed.jsonl> --labels {labels_path} --id-field id{task}"
            f"{label}" + (f" --pred-field {pred_field}" if pred_field != "label" else "")
        ),
    }


def fold_command(review_path, pred_field, summary_path, spot_check_off=False, side_file_only=False):
    """Step 7b's fold for this review set, with the job summary (which settles the
    spot-check basis) and the prediction field the model answers carry.

    side_file_only (the review DataSet by ARN): `--model-output` alone, writing
    REVIEW_SEED_FILE without --append (those rows carry no text). Otherwise (a local
    review file): fold_commands' form, --sample <review file> --append <seed>."""
    tail = f" --job-summary {summary_path} --pred-field {pred_field}" + (
        " --spot-check-off" if spot_check_off else ""
    )
    if side_file_only:
        return (
            f"python scripts/fold_review.py hil --model-output "
            f"{model_output_path(review_path)} --labels <hil_export.jsonl> "
            f"--out {review_seed_path(review_path)} --id-field id"
            f"{_gt_flag(pred_field)} --label-field <export label column>{tail}"
        )
    return fold_commands(review_path, pred_field, model_output_path(review_path))["fold"] + tail


def overlay_command(review_path, pred_field, deliverable_path, side_file_only=False):
    """Step 7b's overlay for this review set: fold_review.py overlay over the seed
    (and, after a side-file fold, its REVIEW_SEED_FILE too), onto the corpus run's
    deliverable record, beside the review file."""
    d = os.path.dirname(review_path) or "."
    seeds = "--seed <seed.jsonl>" + (
        f" --seed {review_seed_path(review_path)}" if side_file_only else ""
    )
    return (
        f"python scripts/fold_review.py overlay {seeds} "
        f"--dataset {deliverable_path} --out {os.path.join(d, OVERLAY_FILE)} --id-field id"
        + _gt_flag(pred_field)
        + (f" --pred-field {pred_field}" if pred_field != "label" else "")
    )


def build_handoff(
    summary,
    spec_text,
    dataset_name,
    *,
    job_arn,
    review_dataset_arn=None,
    review_rows_uri=None,
    review_rows_path=None,
    review_rows=None,
    labeled_dataset_arn=None,
    text_fields=None,
    review_path="review.jsonl",
    summary_path="labeling_summary.json",
    deliverable_path="labeled_dataset.json",
    spot_check_off=False,
):
    """The human-in-the-loop spec from the job's labeling_summary.json and the spec.
    `review_rows_path` names a local review file as the data reference (with its rows
    in `review_rows`, counted and split-tallied in place of the summary's counts).
    `review_path` and `summary_path` are the local files the fold command names.
    `spot_check_off` (the plan's `review_high_confidence: false`) makes the fold give no
    spot-check verdict: the job still puts its spot-check rows in the review set."""
    task = task_of_type(summary.get("Type"))
    if task not in PREDICTION_FIELDS:
        raise ValueError(f"the summary names no labeling task (Type {summary.get('Type')!r})")
    pred_field = PREDICTION_FIELDS[task]
    # A job without Confidence.Method stated writes no stated-confidence field, so the
    # contract does not list them.
    hidden = [
        f
        for f in blind_fields(pred_field)
        if summary.get("ConfidenceMethod") == "stated" or f not in STATED_CONFIDENCE_FIELDS
    ]
    # A verbalized job also writes confidence_missing, model output the reviewer must not see.
    if summary.get("ConfidenceMethod") == "verbalized":
        hidden += [f for f in VERBALIZED_CONFIDENCE_FIELDS if f not in hidden]
    data_ref = review_dataset_arn or review_rows_uri or review_rows_path
    # Human-in-the-loop reads the review set by its ARN or URI, and the fold reads the
    # job's side file alone; a local review file (cold start, relabel) folds with
    # --sample and appends to the seed.
    side_file_only = review_rows_path is None
    check_dir = os.path.dirname(review_rows_path or review_path) or "."
    check_cmd = fold_commands(
        review_rows_path or review_path,
        pred_field,
        labels_path=os.path.join(check_dir, OVERLAY_FILE),
    )["check"]
    if side_file_only:
        check_cmd = check_cmd.replace(
            "--seed <seed.jsonl>", f"--seed {review_seed_path(review_path)}"
        )
    if not data_ref:
        raise ValueError(
            "pass --review-dataset-arn (the registered review DataSet), "
            "--review-rows-uri (the job's review/review_rows.jsonl) or "
            "--review-rows (the local review.jsonl)"
        )
    if review_rows is not None:
        rows: int | None = len(review_rows)
        spot = sum(
            1 for r in review_rows if isinstance(r, dict) and r.get(SPLIT_FIELD) == "spot_check"
        )
    else:
        # The job's review set is the routed rows plus the spot-check rows: RowsRouted
        # counts routed rows only, and a spot-check row is an accepted row.
        routed = summary.get("RowsRouted")
        spot = summary.get("SpotCheckRows") or 0
        rows = routed + spot if routed is not None else None
    if not job_arn:
        raise ValueError(
            "pass --job-arn (the corpus run's job_arn): the task description " "names the job"
        )
    job = job_arn
    n_text = f"{rows} rows" if rows is not None else "the review rows"
    desc = (
        f"Auto-labeling job {job}: {n_text} to label. Label each row from the text alone; "
        "the model's answer is not shown."
    )
    if spot:
        desc += (
            f" The {n_text} include {spot} spot-check rows the model labeled "
            "confidently; they look like every other row and are labeled the same way."
        )
    handoff = {
        "ProjectName": f"{dataset_name}-review",
        "TaskDescription": desc,
        "Recommendation": f"Write {pred_field} for each row.",
        "QuestionContext": question_context(spec_text, task),
        "Data": {"LowConfidence": data_ref, "Dataset": labeled_dataset_arn, "Format": "jsonl"},
        "Contract": {
            "task": task,
            "prediction_field": pred_field,
            "id_field": "id",
            "text_fields": list(text_fields or []),
            "split_field": SPLIT_FIELD,
            "split_values": list(SPLIT_VALUES),
            "hidden_fields": hidden,
            "export": {
                "id_field": f"id (a local review writes {LOCAL_REVIEW_ID_FIELD})",
                "value_field": f"{pred_field} (a local review writes {LOCAL_REVIEW_VALUE_FIELD})",
                "status_field": f"{STATUS_FIELD}: completed | skipped",
                "split": (
                    "not written by the reviewer; the skill reads it from the job (the "
                    "side file's routed, or the review row of a local review file)"
                ),
            },
            "scoring": {
                "unreturned_or_skipped": "counts as wrong",
                "spot_check_confirmation": "a spot_check row whose value equals the model's label",
                "spot_check_withdraw_at": (
                    None if spot_check_off else summary.get("SpotCheckWithdrawAt")
                ),
                "spot_check_reviewed": not spot_check_off,
                "spot_check_rows": spot or None,
                "status": summary.get("Status"),
                "status_reason": summary.get("StatusReason"),
            },
            # A local review export also needs --export-id-field record_id and
            # --label-field corrected_completion (Contract.export).
            "fold": fold_command(
                review_rows_path or review_path,
                pred_field,
                summary_path,
                spot_check_off,
                side_file_only=side_file_only,
            ),
            "overlay": overlay_command(
                review_rows_path or review_path,
                pred_field,
                deliverable_path,
                side_file_only=side_file_only,
            ),
            "check": check_cmd,
            "corrections": {
                "apply": (
                    "dataset-transformation overlay by id: one job over [a dt-view of "
                    "Data.Dataset, the overlay], whose output the hub_ops promote action adds as "
                    "the labeled DataSet's next version (the overlay's .handoff.json); "
                    "the labeled rows are never downloaded"
                ),
                "key_field": "id",
                "replace_fields": [pred_field, "provenance", "_labeled_by", "_review_reason"],
                "model_answer_to": "_model_output",
            },
        },
    }
    return handoff


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--summary", required=True, help="the job's labeling_summary.json")
    ap.add_argument("--spec", required=True, help="the labeling spec the job ran")
    ap.add_argument("--dataset-name", required=True, help="the labeled DataSet's name")
    ap.add_argument("--review-dataset-arn", default=None)
    ap.add_argument(
        "--review-rows-uri",
        default=None,
        help="the job's review/review_rows.jsonl S3 URI, when no review DataSet " "ARN is known",
    )
    ap.add_argument(
        "--review-rows",
        default=None,
        help="the local review.jsonl to hand off instead of the job's review "
        "set (after fold_review.py overlay --review dropped rows people "
        "labeled already); its rows set the counts",
    )
    ap.add_argument("--labeled-dataset-arn", default=None)
    ap.add_argument(
        "--job-arn",
        required=True,
        help="the corpus run's job ARN (code_templates/labeling_round.py prints job_arn)",
    )
    ap.add_argument("--text-fields", default=None, help="comma-separated input fields")
    ap.add_argument(
        "--spot-check-off",
        action="store_true",
        help="the plan turned the spot-check review off "
        "(review_high_confidence: false): the fold gives no spot-check "
        "verdict",
    )
    ap.add_argument("--out", default=None, help="write the spec here too")
    args = ap.parse_args(argv)
    try:
        with open(args.summary, encoding="utf-8") as fh:
            summary = json.load(fh)
        with open(args.spec, encoding="utf-8", errors="replace") as fh:
            spec_text = fh.read()
        review_rows = read_jsonl(args.review_rows) if args.review_rows else None
        handoff = build_handoff(
            summary,
            spec_text,
            args.dataset_name,
            review_dataset_arn=args.review_dataset_arn,
            review_rows_uri=args.review_rows_uri,
            review_rows_path=args.review_rows,
            review_rows=review_rows,
            labeled_dataset_arn=args.labeled_dataset_arn,
            job_arn=args.job_arn,
            text_fields=[f for f in (args.text_fields or "").split(",") if f.strip()],
            review_path=os.path.join(os.path.dirname(args.summary) or ".", "review.jsonl"),
            summary_path=args.summary,
            deliverable_path=os.path.join(
                os.path.dirname(args.summary) or ".", "labeled_dataset.json"
            ),
            spot_check_off=args.spot_check_off,
        )
    except (OSError, ValueError) as e:
        sys.exit(f"hil_handoff: {e}")
    text = json.dumps(handoff, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
