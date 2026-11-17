# Cell 0 [markdown]: Induce a spec
# # Induce a spec from the labeled seed
#
# One model call reads the dev split's examples per label and drafts the spec's decision
# rules (or an anchored rubric for a numeric gold field). The seed is the only data read.
# Cell 1: Configuration
SEED = "[SEED]"           # the labeled INDUCE-pool JSONL (the dev split); disjoint from val and test
OUT = "[OUT]"             # where the induced spec Markdown is written, e.g. <proj>/work/labeling_spec_induced.md
PROJECT_DIR = "[PROJECT_DIR]"  # the project (its splits/ and run-log.jsonl)
TASK = "classification"        # [TASK]: classification | ner | llm_judge | ordinal
LABEL_SET = None               # [LABEL_SET]: JSON list, e.g. '["TP","FP"]'; required for classification and ner
TASK_HINT = ""                 # [TASK_HINT]: one-line task description to steer induction
TEXT_FIELDS = "text"           # [TEXT_FIELDS]: comma-separated input field(s)
GT_FIELD = "gt_label"          # [GT_FIELD]: classification: label field; ner: entity-list field; llm_judge / ordinal: the score field
SCORE_MIN = None               # [SCORE_MIN]: llm_judge / ordinal: low end of the score scale (required there)
SCORE_MAX = None               # [SCORE_MAX]: llm_judge / ordinal: high end of the score scale (required there)
ANCHORS_PER_LEVEL = 2          # llm_judge / ordinal: dev rows quoted per score level (1 or 2)
MAX_PER_CLASS = 12             # cap on examples / spans shown per class / type in the prompt
MIN_TYPE_SUPPORT = 3           # ner: warn when a type has fewer seed spans than this
ANNOTATION_SCOPE = "exhaustive"  # ner: exhaustive | notable
MODEL = "[MODEL]"              # the reflection model that writes the rules: an inference profile id (references/spec-induction.md)
REPLY_KEYS_LINE = False        # classification: end the Output Schema with the keys the job appends (references/offer-options.md)
REGION = "[REGION]"            # the model's region, e.g. us-west-2
SEED_NUM = 0                   # RNG seed (example ordering)
RUN_LOG_SCRIPTS = "[SKILL_ROOT]/references/directory-management/scripts"  # the shared run-log writer (run_log.py)

import json
import sys

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators import (
    print_client_reads,
    read_jsonl,
    report_client_read,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import split as split_state
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.spec import induce as induce_spec
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

if RUN_LOG_SCRIPTS not in sys.path:
    sys.path.insert(0, RUN_LOG_SCRIPTS)
import run_log  # the project's run-log writer (directory-management)


def _guard_project(path):
    """PROJECT_DIR when it (or `path`'s own folder) has a frozen split, else the nearest project
    above `path` that has one: a wrong PROJECT_DIR must not leave the read unchecked."""
    if split_state.find_splits_dir(path, project_dir=PROJECT_DIR):
        return PROJECT_DIR
    return split_state.nearest_project(path) or PROJECT_DIR


print_client_reads()

# Cell 2: Induce - the arguments are checked before the seed is read
if not MODEL or MODEL.startswith("["):
    sys.exit("induce_spec: set MODEL to an inference profile id "
             "(aws bedrock list-inference-profiles --region <region>).")
if TASK in induce_spec.RUBRIC_TASKS:
    if SCORE_MIN is None or SCORE_MAX is None:
        sys.exit(f"induce_spec: TASK {TASK} needs SCORE_MIN and SCORE_MAX (the anchored rubric has one level per score).")
elif not LABEL_SET:
    sys.exit(f"induce_spec: LABEL_SET is required for TASK {TASK}")
labels = json.loads(LABEL_SET) if LABEL_SET else []
text_fields = [f.strip() for f in TEXT_FIELDS.split(",") if f.strip()]
rows = read_jsonl(SEED)
guard_project = _guard_project(SEED)
try:
    guard = split_state.guard_read(SEED, "induce", {"dev"}, project_dir=guard_project, rows=rows)
except (OSError, DataPreparerOperatorError) as e:
    sys.exit(f"split guard: {e}")
for event in guard.events:
    run_log.write_entry(guard_project, **event)
report_client_read("induce_spec", len(rows))
try:
    induced = induce_spec.induce_spec(
        rows, task=TASK, labels=labels, task_hint=TASK_HINT, text_fields=text_fields, gt_field=GT_FIELD,
        score_min=SCORE_MIN, score_max=SCORE_MAX, anchors_per_level=ANCHORS_PER_LEVEL,
        max_per_class=MAX_PER_CLASS, min_type_support=MIN_TYPE_SUPPORT, annotation_scope=ANNOTATION_SCOPE,
        reply_keys_line=REPLY_KEYS_LINE, seed_num=SEED_NUM, model_id=MODEL, region=REGION)
except DataPreparerOperatorError as e:
    sys.exit(str(e))
for note in induced.warnings:
    print(note, file=sys.stderr)
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(induced.spec + "\n")
print(json.dumps({"out": OUT, **induced.summary}, indent=2))
