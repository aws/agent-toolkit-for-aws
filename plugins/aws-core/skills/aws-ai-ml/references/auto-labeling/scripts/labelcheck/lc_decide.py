"""Apply the user's decisions (decisions.csv) to the next spec + seed iteration.

  guidelines_correct  relabel the item's conflicting members (proposed_changes)
  label_correct       keep the labels; add sop_wording (required) to the spec
  neither             if_neither: the right label for every member (wording goes in sop_wording)
Per-row overrides ("r12=a;r13=keep") win; two items that set one row differently cancel.

The decisions are `sagemaker.ai_registry.data_preparer.auto_labeling.operators.review.decisions`,
re-exported here; `review_inputs` and `logged_decisions` read the project's files and run log
for them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from io_utils import read_run_entries, sdk_missing  # noqa: E402

try:
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.review import decisions as _ld
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.review.decisions import (  # noqa: F401
        CLARIFY_HEADER,
        DECISION_COLS,
        DECISIONS,
        FORMULA_LEAD,
        RUN_LOG_STEP,
        OverrideOutsideItem,
        apply_decisions,
        canon,
        csv_cell,
        item_sha,
        next_spec_name,
        parse_overrides,
        read_decisions_csv,
        spec_iteration,
    )
    from sagemaker.core import Attribution, set_attribution
except ImportError as e:
    sys.exit(sdk_missing(e))

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)


def review_inputs(spec, seed, project_dir):
    """The sha256 of the spec, the --seed file and the frozen split's state (None without
    one): what a review read, and what applying its decisions needs unchanged."""
    from io_utils import split_state

    sdir = split_state.find_splits_dir(None, project_dir)
    return _ld.review_inputs(
        split_state.sha256_file(spec),
        split_state.sha256_file(seed),
        split_state.sha256_file(split_state.state_path(sdir)) if sdir else None,
    )


def logged_decisions(project_dir, items=None):
    """The decisions the project's run log records, by item_id (latest wins; the decision
    is the entry's `status`); with `items`, only those whose item still has the decided
    members and changes."""
    return _ld.logged_decisions(
        read_run_entries(project_dir, kind="decision", step=RUN_LOG_STEP), items
    )
