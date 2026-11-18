# Cell 0 [markdown]: The run report
# # The run report
#
# `report.html` and `report.md` from the project's artifacts: the labeled DataSet, the job's
# certificate and held-out report, the review fold and the run log. No labeled row is read.
# Cell 1: Configuration
PROJECT_DIR = "[PROJECT_DIR]"  # the project directory holding the run outputs
DATASET = ""                   # [DATASET]: the dataset name shown in the title
FORMAT = "both"                # html | md | both
OUT = None                     # [OUT]: the output path for a single format; ignored for both
CALIBRATION = None             # [CALIBRATION]: the job's labeling_summary.json; None = <proj>/labeling_summary.json, else the corpus run's run-log entry
PRED_FIELD = "label"           # [PRED_FIELD]: a local labels.jsonl's prediction field (`entities` for ner)
GT = None                      # [GT]: a gold file: checked by the split guard (the test read is logged), never joined to rows

import sys

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators.report import write_report
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import split_state
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

# Cell 2: Build both documents, then write them
try:
    touched = GT and split_state.guard_split_read_or_raise(GT, "report", {"dev", "val", "test"},
                                                           project_dir=PROJECT_DIR, log=False)
    written = write_report(PROJECT_DIR, dataset=DATASET, fmt=FORMAT, out=OUT, calibration=CALIBRATION,
                           pred_field=PRED_FIELD, gt=GT)
    if touched and touched.get("test"):  # the completion gate passed: the test read is logged
        split_state.log_test_read(PROJECT_DIR, GT, "report", touched["test"])
except (OSError, ValueError, DataPreparerOperatorError) as e:
    sys.exit(f"report: {e}")
print("wrote " + ", ".join(written["wrote"]))
