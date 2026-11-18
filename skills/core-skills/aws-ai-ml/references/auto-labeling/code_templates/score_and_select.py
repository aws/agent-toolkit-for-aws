# Cell 0 [markdown]: Score and select
# # Score and select
#
# The score cell (Cell 2) re-scores a predictions file against its gold; Cell 3 decides which spec ships (the
# best val score, with a do-no-harm floor). No model call; the gold is the seed split.
# Cell 1: Configuration
PRED = None                    # [PRED]: the predictions file Cell 2 scores; None skips Cell 2
GT = None                      # [GT]: a seed split with the gold field (dev / val / test .jsonl); never the corpus
TASK = "[TASK]"                # classification | ner | qa | ordinal | llm_judge
GT_FIELD = None                # [GT_FIELD]: the gold field; None = the task's (gt_label, gt_entities, gt_answers, gt_score)
PRED_FIELD = None              # [PRED_FIELD]: the prediction field; None = the task's (label, entities, answer, score, judge_score)
ID_FIELD = "id"                # rows align by it when both files carry it, else by order
LABEL_MAP = None               # [LABEL_MAP]: ordinal / llm_judge, JSON text label -> rank, e.g. '{"very negative": 1}'
SPEC = None                    # [SPEC]: ordinal / llm_judge: ranks from the Label Set order; llm_judge: the tolerance from the score scale
TOLERANCE = None               # [TOLERANCE]: llm_judge: max |pred - gold| that counts as correct; overrides the scale rule
SCORE_OUT = None               # [SCORE_OUT]: where Cell 2 writes score.json; None = print only
PROJECT_DIR = "[PROJECT_DIR]"  # the project (its splits/ and run-log.jsonl)
SCORES = None                  # [SCORES]: the scores document Cell 3 reads, {"initial": {"spec", "val"}, "iters": [...]}; None skips Cell 3
MIN_GAIN = 0.02                # min val improvement to prefer refined over initial (finer gains are noise on a small val split)
PER_TYPE_TOL = None            # [PER_TYPE_TOL]: with breakdowns, reject a refined spec that regresses any passing type by more than this
DECISION_OUT = None            # [DECISION_OUT]: where Cell 3 writes decision.json; None = print only
RUN_LOG_SCRIPTS = "[SKILL_ROOT]/references/directory-management/scripts"  # the shared run-log writer (run_log.py)

import json
import sys

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators import (
    DEFAULT_CORRECT_TOLERANCE,
    GOLDEN_REVIEW_FIELD,
    job_tolerance,
    print_client_reads,
    read_jsonl,
    report_client_read,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.inspect import (
    taxonomy as taxonomy_gate,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import (
    request as labeling_request,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.score import scorers as scoring
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import split as split_state
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.spec.select import (
    select as select_spec,
)
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


def _write(path, text):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


# Cell 2: Score (Step 3) - PRED against GT under TASK's rule; score.json
if PRED:
    gt_rows = read_jsonl(GT)
    if len(gt_rows) > scoring.MAX_ROWS:
        sys.exit(f"GT has {len(gt_rows)} rows; this scores a seed-sized file (at most {scoring.MAX_ROWS}). "
                 "The corpus run's labels stay behind the API; read its metrics in labeling_summary.json.")
    if any(isinstance(r, dict) and GOLDEN_REVIEW_FIELD in r for r in gt_rows):
        sys.exit(f"GT {GT!r} is a golden_review.py reviewed copy, which only the corpus run's EVAL_DATA reads; "
                 "score against the original split")
    try:
        guard_project = _guard_project(GT)
        guard = split_state.guard_read(GT, "report", {"dev", "val", "test"}, project_dir=guard_project, rows=gt_rows)
    except (OSError, DataPreparerOperatorError) as e:
        sys.exit(f"split guard: {e}")
    for event in guard.events:  # a test read is a run-log entry
        run_log.write_entry(guard_project, **event)
    pred_rows = read_jsonl(PRED)
    if len(pred_rows) > scoring.MAX_ROWS:
        sys.exit(f"PRED has {len(pred_rows)} rows; this scores a seed-sized file (at most {scoring.MAX_ROWS})")
    report_client_read("scoring", len(pred_rows) + len(gt_rows))
    label_map = None
    if LABEL_MAP:
        try:
            label_map = scoring.parse_label_map(LABEL_MAP)
        except DataPreparerOperatorError as e:
            sys.exit(str(e))
    elif SPEC:
        with open(SPEC, encoding="utf-8") as fh:
            label_map = scoring.label_map_from_names([n for n, _ in taxonomy_gate.parse_label_set(fh.read())])
    tolerance = DEFAULT_CORRECT_TOLERANCE
    if TASK == "llm_judge":
        if TOLERANCE is not None:
            tolerance = TOLERANCE
        elif SPEC:
            with open(SPEC, encoding="utf-8") as fh:
                tolerance = job_tolerance(labeling_request.spec_score_scale(fh.read()))
        else:
            print(f"NOTE: no SPEC or TOLERANCE; scoring llm_judge rows correct within {tolerance} of the gold "
                  "(the job uses 5% of the spec's scale, at least 0.5).", file=sys.stderr)
    try:
        result = scoring.score(TASK, pred_rows, gt_rows, id_field=ID_FIELD, pred_field=PRED_FIELD,
                               gt_field=GT_FIELD, label_map=label_map, tolerance=tolerance)
    except DataPreparerOperatorError as e:
        sys.exit(f"scoring: {e}")
    _write(SCORE_OUT, json.dumps(result.to_json(), indent=2, ensure_ascii=False))

# Cell 3: Select (Steps 4 and 6) - which spec ships; decision.json
if SCORES:
    try:
        with open(SCORES, encoding="utf-8") as fh:
            data = json.loads(fh.read())
    except (OSError, ValueError) as e:
        sys.exit(f"select: cannot read SCORES {SCORES}: {e}")  # an unreadable scores file is not a no-iteration run
    try:
        decision = select_spec(data, MIN_GAIN, PER_TYPE_TOL)
    except DataPreparerOperatorError as e:
        sys.exit(f"select: invalid SCORES {SCORES}: {e}")  # exit with the expected shape rather than select on a misread
    for note in decision.warnings:
        print(note, file=sys.stderr)
    _write(DECISION_OUT, json.dumps(decision.to_json(), indent=2))
