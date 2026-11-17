# Cell 0 [markdown]: The in-job search's pick
# # The in-job search's pick
#
# `adopt-job` copies the spec the in-job search picked into the project after your approval;
# `ship` checks that copy against the approval and writes it as the spec that ships. No job
# is submitted.
# Cell 1: Configuration
ACTION = "[ACTION]"            # adopt-job | ship
PROJECT_DIR = "[PROJECT_DIR]"  # the project directory
PICK = None                    # [PICK]: adopt-job: <out dir>/job/optimize/spec.md
APPROVAL = None                # [APPROVAL]: adopt-job: the approval entry's id in the run log
OUT = None                     # [OUT]: ship: <proj>/labeling_spec.md

import json
import sys

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators.spec import (
    adopt_job_pick,
    ship_adopted_spec,
)
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

# Cell 2: Run the action
try:
    if ACTION == "adopt-job":
        out = adopt_job_pick(PROJECT_DIR, PICK, APPROVAL)
        print(json.dumps({"decision_entry": out["decision_entry"], "spec": out["spec"]}, indent=2))
    elif ACTION == "ship":
        print(json.dumps(ship_adopted_spec(PROJECT_DIR, OUT)))
    else:
        sys.exit(f"ACTION must be adopt-job or ship; got {ACTION!r}")
except DataPreparerOperatorError as e:
    sys.exit(str(e))
