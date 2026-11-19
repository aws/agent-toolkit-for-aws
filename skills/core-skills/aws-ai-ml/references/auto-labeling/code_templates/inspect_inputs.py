# Cell 0 [markdown]: Inspect the inputs
# # Inspect the inputs
#
# The corpus's and the seed's field names and sizes, the task type the spec and the seed
# suggest, and whether the label set is separable. Only the first row of the corpus is read;
# nothing is spent.
# Cell 1: Configuration
CORPUS = None                 # [CORPUS]: s3:// URI, DataSet ARN or local path of the corpus; None to skip it
SEED = None                   # [SEED]: s3:// URI, DataSet ARN or local path of the labeled seed; None to skip it
GUIDELINES = None             # [GUIDELINES]: the guidelines / spec file; its label set picks the label field
TEXT_FIELDS = None            # [TEXT_FIELDS]: comma-separated fields the spec passes to the labeler, else None
SPEC = None                   # [SPEC]: the one-page labeling spec (Cells 3 and 4)
TASK_SAMPLE = None            # [TASK_SAMPLE]: the labeled seed (or, on cold start, the corpus head file) Cell 3 reads
SAMPLE_SIZE = 200             # max rows Cell 3 reads from TASK_SAMPLE
DETECT_OUT = None             # [DETECT_OUT]: where Cell 3 writes its JSON, e.g. <proj>/task_detection.json; None = print only
LABELED = None                # [LABELED]: the labeled seed Cell 4 checks (optional)
GT_FIELD = "gt_label"         # [GT_FIELD]: the seed's gold field
TASK = "classification"       # [TASK]: the task the gate checks (the overlap check is skipped for ordinal)
GATE_OUT = None               # [GATE_OUT]: where Cell 4 writes its JSON, e.g. <proj>/taxonomy_gate.json; None = print only
REGION = "[REGION]"           # the inputs' region, e.g. us-west-2

import json
import sys

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators import (
    print_client_reads,
    report_client_read,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.inspect import (
    inputs as inspect_input,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.inspect import task as detect_task
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.inspect import (
    taxonomy as taxonomy_gate,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import register
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

print_client_reads()


def _write(path, text):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


def _resolve_arn(arn, region):  # a DataSet ARN -> its single .jsonl object URI
    return register.resolve_dataset_ref(arn, out_path=None, region=region, download=False)["resolved_s3_uri"]


# Cell 2: Inventory (Step 0) - one row of each input, the sizes, the proposed fields
if CORPUS or SEED:
    guidelines_text = None
    if GUIDELINES:
        with open(GUIDELINES, encoding="utf-8", errors="replace") as fh:
            guidelines_text = fh.read()
    fields = [f.strip() for f in (TEXT_FIELDS or "").split(",") if f.strip()] or None
    try:
        inventory = inspect_input.inspect(CORPUS, SEED, guidelines_text, REGION, text_fields=fields,
                                          resolve_arn=_resolve_arn)
    except (OSError, DataPreparerOperatorError) as e:
        sys.exit(f"inspect_input: {e}")
    print(json.dumps(inventory.to_json(), indent=2))

# Cell 3: Task type (Step 0.5) - from the spec and a seed sample; the decision is in the output
if SPEC or TASK_SAMPLE:
    spec_text = ""
    if SPEC:
        with open(SPEC, encoding="utf-8") as fh:
            spec_text = fh.read()
    sample = []
    if TASK_SAMPLE:
        with open(TASK_SAMPLE, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= SAMPLE_SIZE:
                    break
                if line.strip():
                    sample.append(json.loads(line))
        report_client_read("detect_task_type", len(sample))
    detection = detect_task.detect(spec_text, sample)
    _write(DETECT_OUT, json.dumps(detection.to_json(), indent=2))

# Cell 4: Taxonomy gate (Step 0.6) - any task with a Label Set (ordinal skips only the overlap
# check; a task with no Label Set gets a "skip" verdict); always a verdict, never a traceback
if SPEC:
    try:
        with open(SPEC, encoding="utf-8") as fh:
            spec_text = fh.read()
        labeled = []
        if LABELED:
            skipped = 0
            with open(LABELED, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        labeled.append(json.loads(line))
                    except json.JSONDecodeError:
                        skipped += 1  # a single bad seed line must not abort the gate
            if skipped:
                print(f"warning: skipped {skipped} malformed seed line(s)", file=sys.stderr)
            report_client_read("taxonomy_gate", len(labeled))
    except (OSError, UnicodeDecodeError) as e:
        # An unreadable or non-UTF-8 spec or seed is a review decision, not a traceback.
        verdict = {"verdict": "review", "decision": "review-before-spend", "task": TASK, "n_classes": 0,
                   "absence_classes": [], "coverage": {"checked": False}, "separability": {"checked": False},
                   "issues": [{"type": "input_error", "severity": "review", "classes": [],
                               "detail": f"could not read an input file: {e}",
                               "suggestion": "check the SPEC / LABELED paths"}]}
    else:
        verdict = taxonomy_gate.gate(spec_text, labeled, GT_FIELD, TASK).to_json()
    _write(GATE_OUT, json.dumps(verdict, indent=2))
