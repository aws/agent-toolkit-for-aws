# Cell 0 [markdown]: The frozen split
# # The frozen split
#
# `freeze` records each split's ids and file hash once; `check` verifies the files against
# it; `rehash` accepts edited dev and val files. The test split never changes.
# Cell 1: Configuration
ACTION = "[ACTION]"             # freeze | check | rehash
SPLITS_DIR = "[SPLITS_DIR]"     # <proj>/splits
TEXT_FIELDS = None              # [TEXT_FIELDS]: freeze: comma-separated input fields (the ones the labeling runs get)
LABEL_FIELD = "gt_label"        # [LABEL_FIELD]: freeze: the seed's gold field
MOVE_NEAR_DUPLICATES = False    # freeze: move the val or test member of each near-duplicate pair into dev first
REASON = None                   # [REASON]: rehash: why dev or val changed
ALLOW_VAL_REMOVAL = False       # rehash: the user removed val rows on purpose

import json
import sys

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import split_state
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

# Cell 2: Run the action
try:
    if ACTION == "freeze":
        fields = [x.strip() for x in (TEXT_FIELDS or "").split(",") if x.strip()]
        if not fields:
            sys.exit("split_state: freeze needs TEXT_FIELDS")
        res = split_state.freeze_split(SPLITS_DIR, fields, label_field=LABEL_FIELD,
                                       move_near_duplicates=MOVE_NEAR_DUPLICATES)
        out = {"rows": res["rows"], "moved_near_duplicates": len(res["moved_near_duplicates"]),
               "state": res["state"]}
    elif ACTION == "check":
        out = split_state.verify_splits(SPLITS_DIR)
    elif ACTION == "rehash":
        if not REASON:
            sys.exit("split_state: rehash needs REASON")
        out = split_state.rehash_split(SPLITS_DIR, REASON, ALLOW_VAL_REMOVAL)
    else:
        sys.exit(f"ACTION must be freeze, check or rehash; got {ACTION!r}")
except (OSError, ValueError, DataPreparerOperatorError) as e:
    sys.exit(f"split_state: {e}")
print(json.dumps(out, ensure_ascii=False))
