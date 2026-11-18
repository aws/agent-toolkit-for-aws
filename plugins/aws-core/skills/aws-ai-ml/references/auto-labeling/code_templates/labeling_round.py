# Cell 0 [markdown]: Labeling round
# # Labeling round
#
# One labeling job on the input rows, scored against the gold rows. Cell 3 submits the job (or
# re-attaches to it under the same run id and stage) and prints its name and ARN; with
# `WAIT = False` the run stops there, and running it again once the job has ended reads the
# result and writes the labels and reports beside the output file.
# Cell 1: Configuration
# The command line's values, as given (comma-separated lists, JSON text): the run log's
# invocation records them so, for a replay.

SPEC = "[SPEC]"                      # the labeling spec (local Markdown file)
INPUT_DATA = "[INPUT_DATA]"                    # the rows to label: a local JSONL (a split), an s3:// URI, a corpus.ref.json pointer or a DataSet ARN
OUT = "[OUT]"                        # a refine round: <proj>/work/<stage>_pred_iter_<N>.jsonl; the corpus run: <proj>/labeled_dataset.json
PROJECT_DIR = "[PROJECT_DIR]"             # the project directory whose run-log.jsonl records this run
STAGE = "[STAGE]"                         # dev | val | corpus | another word for a working job (ceiling-dev, ab-val, ...)
DATASET_NAME = None                       # [DATASET_NAME]: the deliverable's DataSet name; None = autolabel-<task>
GENERATION_MODEL_ID = "[GENERATION_MODEL_ID]"  # the one model a refine round runs (and the first juror)
JURY_MODELS = None                        # [JURY_MODELS]: comma-separated jury of the corpus run (2-5; exactly 1 on ordinal / llm_judge), else None
TASK = None                               # [TASK]: classification | ner | qa | ordinal | llm_judge | summarization; None = detect from the spec and the gold rows
TEXT_FIELDS = "text"                      # [TEXT_FIELDS]: comma-separated input fields
LABEL_SET = None                          # [LABEL_SET]: JSON list of the classes, checked against the spec; else None
EVAL_DATA = None                          # [EVAL_DATA]: the gold rows the job scores against (a local split, an s3:// URI or a DataSet ARN); never the whole seed
GOLDEN_REVIEW = None                      # [GOLDEN_REVIEW]: corpus run only, the golden_review.py manifest of a reviewed EVAL_DATA
LABEL_FIELD = None                        # [LABEL_FIELD]: the gold field of EVAL_DATA and DEMOS; None = the task's
DEMOS = None                              # [DEMOS]: the dev split, for few-shot demos (never val or test)
DEMOS_PER_CLASS = 0                       # [DEMOS_PER_CLASS]: demos per class drawn from DEMOS (0 = zero-shot)
CONFIDENCE_METHOD = None                  # [CONFIDENCE_METHOD]: agreement | stated | verbalized (classification only), else None
CONFIDENCE_ESTIMATOR = None               # [CONFIDENCE_ESTIMATOR]: judge | panel, else None
JUDGE_MODELS = None                       # [JUDGE_MODELS]: comma-separated judge model ids (Confidence.Models), else None
CONFIDENCE_FLOOR_BYPASS = None            # True drops the 0.75 agreement floor (verbalized or a judge / panel estimator)
CONFIDENCE_RECALIBRATION = None           # [CONFIDENCE_RECALIBRATION]: platt (corpus run with verbalized), else None
RECALIBRATION_FIT = None                  # [RECALIBRATION_FIT]: the val split whose gold rows fit the map
OPTIMIZER = None                          # [OPTIMIZER]: refine round only, Config.Optimizer as JSON text, e.g. '{"Mode": "protegi", "Elicitation": "plain"}' (name plain: without Elicitation the request asks for confidence)
TARGET = None                             # [TARGET]: Scoring.Target 0.85-0.99, corpus run only; None = no accuracy promise
REVIEW_DATASET_NAME = None                # [REVIEW_DATASET_NAME]: Routing.ReviewDatasetName, which makes this the corpus run
GRADERS = None                            # [GRADERS]: summarization only, comma-separated grader model ids (1-3)
HUB_NAME = None                           # [HUB_NAME]: OutputDataConfig.HubName; None = AIRegistry
APPEND = False                            # corpus run: the user agreed to add a version to an existing DATASET_NAME / REVIEW_DATASET_NAME
CONFIRM_NO_SEED = False                   # the customer said yes to labels with no accuracy promise (references/cold-start.md, Opt-out)
S3_PREFIX = "[S3_PREFIX]"                 # writable S3 base, e.g. s3://bucket/autolabel/PROJECT/
REGION = "[REGION]"                       # the job's region, e.g. us-west-2
ROLE_ARN = "[ROLE_ARN]"                   # IAM role ARN that trusts sagemaker.amazonaws.com
RUN_ID = "[RUN_ID]"                       # names this run (letters, digits, hyphens; <= 40); the same id and STAGE re-attach instead of resubmitting
SUBMIT_MAX_WAIT = None                    # seconds CreateJob may back off on throttling (None = 3600; 0 = fail on the first)
WAIT = False                              # [WAIT]: False submits (or re-attaches) and stops while the job runs; True waits for it to end
KEEP_RUN_SCOPES = 10                      # keep the N most recent _sdg_work/<run-id> staging dirs
RUN_LOG_STEP = "auto-label"               # the run-log step this round records under
RUN_LOG_ITERATION = 0                     # [RUN_LOG_ITERATION]: the refinement iteration (iter_0 = the initial spec)
RUN_LOG_SCRIPTS = "[SKILL_ROOT]/references/directory-management/scripts"  # the shared run-log writer (run_log.py)

# Cell 2: Check the inputs and build the request (nothing is uploaded)
import json
import os
import sys
from pathlib import Path

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators import print_client_reads
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import round as run_round
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import run_context
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

if RUN_LOG_SCRIPTS not in sys.path:
    sys.path.insert(0, RUN_LOG_SCRIPTS)
import run_log  # the project's run-log writer (directory-management)

print_client_reads()  # every client-side read of customer rows prints a `client-read:` line


def _note(text):
    print(text, file=sys.stderr)


try:
    plan = run_round.prepare_round(
        spec=SPEC, input_data=INPUT_DATA, out=OUT, project_dir=PROJECT_DIR, stage=STAGE,
        generation_model_id=GENERATION_MODEL_ID, dataset_name=DATASET_NAME, jury_models=JURY_MODELS,
        task=TASK, text_fields=TEXT_FIELDS, label_set=LABEL_SET, eval_data=EVAL_DATA,
        golden_review=GOLDEN_REVIEW, label_field=LABEL_FIELD, demos=DEMOS,
        demos_per_class=DEMOS_PER_CLASS, confidence_method=CONFIDENCE_METHOD,
        confidence_estimator=CONFIDENCE_ESTIMATOR, judge_models=JUDGE_MODELS,
        confidence_floor_bypass=CONFIDENCE_FLOOR_BYPASS,
        confidence_recalibration=CONFIDENCE_RECALIBRATION, recalibration_fit=RECALIBRATION_FIT,
        optimizer=OPTIMIZER, target=TARGET, review_dataset_name=REVIEW_DATASET_NAME,
        graders=GRADERS, hub_name=HUB_NAME, append=APPEND, confirm_no_seed=CONFIRM_NO_SEED,
        s3_prefix=S3_PREFIX, region=REGION, role_arn=ROLE_ARN, run_id=RUN_ID,
        submit_max_wait=SUBMIT_MAX_WAIT)
except run_round.RoundRefused as e:  # a refusal after a split was read: the read is logged
    for note in e.warnings:
        _note(note)
    for event in e.events:
        run_log.write_entry(PROJECT_DIR, **event)
    sys.exit(str(e))
except DataPreparerOperatorError as e:
    sys.exit(str(e))
for note in plan.warnings:
    _note(note)
Path(plan.out).parent.mkdir(parents=True, exist_ok=True)
Path(plan.staging_dir).mkdir(parents=True, exist_ok=True)
run_context(plan.run_id).prune_old_scopes(Path(plan.out).parent, KEEP_RUN_SCOPES)
Path(plan.request_path).write_text(plan.request_text)
for event in plan.events:  # the split reads
    run_log.write_entry(PROJECT_DIR, **event)
print(json.dumps({"stage": plan.stage, "task": plan.task, "run_id": plan.run_id,
                  "dataset_name": plan.dataset_name, "request": plan.request_path}))

# Cell 3: Submit the job, or re-attach to it under the same RUN_ID and STAGE
# The job record is written before CreateJob, so a run stopped while the job runs (WAIT =
# False, or a timed-out wait) re-attaches under the same RUN_ID; a CreateJob refusal
# removes it (no job exists).
record = Path(plan.job_record_path)
try:
    submitted = run_round.submit_round(
        plan, on_submit=record.write_text, on_refused=lambda: record.unlink(missing_ok=True),
        endpoint=os.environ.get("AWS_ENDPOINT_URL_SAGEMAKER"), wait=WAIT)
except DataPreparerOperatorError as e:
    sys.exit(str(e))
job = submitted.job
print(json.dumps({"job_name": job.get("job_name"), "job_arn": job.get("job_arn"),
                  "job_status": job.get("job_status"), "reattached": job.get("reattached"),
                  "run_id": plan.run_id, "stage": plan.stage}))

# Cell 4: Read the result back once the job has ended
outputs = None
if submitted.running:
    print(f"Job {job.get('job_name')} is {job.get('job_status')}. Nothing is read yet: run this "
          f"template again with RUN_ID {plan.run_id!r} and STAGE {plan.stage!r} to collect it "
          "(it re-attaches and submits nothing).")
else:
    try:
        outputs = run_round.read_round(plan, job, run_log_step=RUN_LOG_STEP,
                                       run_log_iteration=RUN_LOG_ITERATION)
    except DataPreparerOperatorError as e:
        sys.exit(str(e))

# Cell 5: Write the round's files and its run-log record; print the summary
if outputs is not None:
    for path, text in outputs.texts.items():
        Path(path).write_text(text, encoding="utf-8")
    for dest, src in outputs.copies.items():
        Path(dest).write_bytes(Path(src).read_bytes())
    for path in outputs.removes:
        Path(path).unlink(missing_ok=True)
    entry = error = None
    if outputs.record is not None:
        try:
            job_ids = [run_log.write_entry(PROJECT_DIR, **event) for event in outputs.record.jobs]
            entry = run_log.write_entry(PROJECT_DIR, **outputs.record.artifact_entry(job_ids))
        except Exception as e:  # noqa: BLE001 - the labels are written; the record's failure is reported
            error = f"{type(e).__name__}: {e}"
    for note in outputs.warnings:
        _note(note)
    print(json.dumps(run_round.round_summary(outputs, run_log_entry=entry, run_log_error=error),
                     indent=2))
