# Ad-Hoc Recovery and Control Template
#
# Cells in this file are NOT part of the primary workflow and are NOT written
# to the user's initial notebook. The agent inserts a cell from here into the
# user's running notebook only when the triggering event occurs (kernel loss,
# user request to stop a running job).

# Cell 0 [markdown]: Ad-Hoc Recovery and Control

# Cell 1: Kernel Restart Recovery  [AD-HOC — insert when kernel/connection is lost]
# Re-attach to a running synthetic dataset generation job after a kernel restart.
# [JOB_ARN]: the ARN printed at submission time (e.g. "arn:aws:sagemaker:us-west-2:123456789012:job/SyntheticDataGeneration/my-job-20261030-180000-abc").
# [DATASET_VAR]: the variable name expected by downstream cells —
#   sample_dataset   for a Cell 5 sample run,
#   refined_dataset  for a Cell 6 refinement run,
#   full_dataset     for a Cell 7 full run.
from sagemaker.ai_registry import DataPreparer
from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

[DATASET_VAR] = DataPreparer.attach("[JOB_ARN]")

# Cell 2: Stop Running Job  [AD-HOC — insert when the user asks to stop a running job]
# Stop a running synthetic dataset generation job gracefully.
# [JOB_HANDLE_OR_ARN]: the ARN string printed at submission time (as emitted by Cell 7).
# If a live Job handle from a wait=False submission is in scope, pass that variable name
# directly (without quotes) instead of the ARN string.
from sagemaker.ai_registry import DataPreparer
from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

DataPreparer.stop("[JOB_HANDLE_OR_ARN]")
