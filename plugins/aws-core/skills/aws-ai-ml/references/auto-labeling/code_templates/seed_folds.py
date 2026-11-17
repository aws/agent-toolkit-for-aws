# Cell 0 [markdown]: Seed folds and demos
# # Seed folds and demos
#
# The folds cell (Cell 2) builds K stratified folds of the dev split for val rotation across refinement
# iterations; Cell 3 previews the few-shot demos a labeling round would draw.
# Cell 1: Configuration
LABELED = "[LABELED]"        # the frozen dev split, <proj>/splits/dev.jsonl
PROJECT_DIR = "[PROJECT_DIR]"  # the project (its splits/ and run-log.jsonl)
GT_FIELD = "gt_label"          # [GT_FIELD]: classification: single-label field; ner: entity-list field
TASK = "classification"        # [TASK]: classification | ner (ner stratifies folds by each row's rarest entity type)
FOLDS_OUT_DIR = None           # [FOLDS_OUT_DIR]: where Cell 2 writes fold_{0..K-1}.jsonl and manifest.json; None skips Cell 2
K = 4                          # folds
FOLD_SEED = 0                  # the folds' RNG seed
EXCLUDE = None                 # [EXCLUDE]: a seed with no frozen split only: its reserved test JSONL, whose rows are dropped from the folds (under a frozen split leave it None: the guard already refuses test rows)
DEMOS_OUT = None               # [DEMOS_OUT]: where Cell 3 writes the demo preview; None skips Cell 3
DEMOS_MODE = "fixed"           # none | fixed (K per class)
DEMOS_PER_CLASS = 2            # demos per class (ner: rows per entity type)
RUN_LOG_SCRIPTS = "[SKILL_ROOT]/references/directory-management/scripts"  # the shared run-log writer (run_log.py)

import json
import sys
from pathlib import Path

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators import (
    print_client_reads,
    read_jsonl,
    report_client_read,
)
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import demos
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import folds as kfold
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import split as split_state
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


def _guarded_rows(path, step, primitive, allowed):
    """The rows, once the split guard has checked the read; a test read is a run-log entry."""
    guard_project = _guard_project(path)
    try:  # the guard reads the file as written: under a frozen split a row with no id is refused
        guard = split_state.guard_read(path, step, allowed, project_dir=guard_project)
    except (OSError, DataPreparerOperatorError) as e:
        sys.exit(f"split guard: {e}")
    for event in guard.events:
        run_log.write_entry(guard_project, **event)
    rows = read_jsonl(path, add_id=True)  # folds and demos align by id
    report_client_read(primitive, len(rows))
    return rows


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# Cell 2: Folds (Step 1) - fold_{0..K-1}.jsonl and manifest.json under FOLDS_OUT_DIR
if FOLDS_OUT_DIR:
    rows = _guarded_rows(LABELED, "kfold", "kfold_rotate", {"dev", "val"})
    frozen = bool(EXCLUDE) and bool(split_state.test_ids(project_dir=PROJECT_DIR))
    exclude = None if not EXCLUDE else [] if frozen else _guarded_rows(EXCLUDE, "kfold", "kfold_rotate", {"dev", "val"})
    out = Path(FOLDS_OUT_DIR)
    try:
        folds = kfold.build_kfold(rows, out_dir="" if str(out) == "." else str(out), gt_field=GT_FIELD, k=K,
                                  seed=FOLD_SEED, task=TASK, exclude=exclude, frozen_split=frozen)
    except DataPreparerOperatorError as e:
        sys.exit(str(e))
    if folds.dropped:
        print(f"kfold_rotate: dropped {folds.dropped} row(s) present in EXCLUDE ({EXCLUDE}) so the reserved "
              "test partition does not leak into the dev/val folds.", file=sys.stderr)
    out.mkdir(parents=True, exist_ok=True)
    for name, fold_rows in folds.files.items():
        _write_jsonl(out / name, fold_rows)
    (out / "manifest.json").write_text(json.dumps(folds.manifest, indent=2) + "\n")
    print(json.dumps({"k": K, "n_rows": folds.n_rows, "fold_sizes": folds.fold_sizes}, indent=2))

# Cell 3: Demo preview (references/demo-modes.md) - the rows a labeling round draws as demos
if DEMOS_OUT:
    rows = _guarded_rows(LABELED, "demos", "select_demos", {"dev"})
    try:
        drawn = demos.select_demos(rows, mode=DEMOS_MODE, k=DEMOS_PER_CLASS, task=TASK, gt_field=GT_FIELD)
    except DataPreparerOperatorError as e:
        sys.exit(str(e))
    _write_jsonl(DEMOS_OUT, drawn.demos)
    print(json.dumps(drawn.summary))
