# Cell 0 [markdown]: The cold-start seed
# # The cold-start seed
#
# `sample` draws the rows people label from the Split job's random part; `merge` puts their
# labels on a local labeled file; `overlay` writes their labels as the corrections applied to
# the labeled DataSet.
# Cell 1: Configuration
ACTION = "[ACTION]"           # sample | merge | overlay
OUT = "[OUT]"                 # sample: <proj>/sample.jsonl; merge: <proj>/labels.jsonl; overlay: <proj>/overlay.jsonl
ID_FIELD = "id"               # [ID_FIELD]: the id field
# sample
INPUT = None                  # [INPUT]: the Split job's sample part (s3:// URI or local JSONL), never the corpus
TEXT_FIELDS = None            # [TEXT_FIELDS]: comma-separated input fields to keep
TARGET = 0.90                 # [TARGET]: the accuracy target, which sets the size
TASK = None                   # [TASK]: the detected task, else None
SAMPLE_SEED = "0"             # the draw's seed
CORPUS_ROWS = None            # [CORPUS_ROWS]: the corpus row count the Split job sampled from, when known
# merge
LABELS = None                 # [LABELS]: the labeled file (the corpus itself on a whole-corpus merge)
SEED = None                   # [SEED]: merge: the seed people labeled; overlay: comma-separated seeds, in order
GT_FIELD = None               # [GT_FIELD]: the seed's gold field (merge default gt_label; overlay: the task's)
PRED_FIELD = None             # [PRED_FIELD]: the labeled file's label field (merge default label; score for ordinal, entities for ner)
REVIEW = None                 # [REVIEW]: the corpus job's review.jsonl (or its side file review.model_output.jsonl)
# overlay
DATASET = None                # [DATASET]: overlay: <proj>/labeled_dataset.json

import json
import logging
import sys

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators import print_client_reads
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import bootstrap
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

print_client_reads()  # every client-side read of customer rows prints a `client-read:` line
_h = logging.StreamHandler(sys.stderr)
_h.setFormatter(logging.Formatter("WARNING: %(message)s"))
for _name in ("sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.bootstrap",
              "sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed.labels"):
    logging.getLogger(_name).addHandler(_h)

# Cell 2: Run the action
try:
    if ACTION == "sample":
        report = bootstrap.write_sample(INPUT, OUT, TEXT_FIELDS, target=TARGET, task=TASK,
                                        seed=SAMPLE_SEED, id_field=ID_FIELD, corpus_rows=CORPUS_ROWS)
    elif ACTION == "merge":
        report = bootstrap.write_merged_labels(LABELS, SEED, OUT, id_field=ID_FIELD,
                                               gt_field=GT_FIELD or "gt_label",
                                               pred_field=PRED_FIELD, review_path=REVIEW)
    elif ACTION == "overlay":
        seeds = [s.strip() for s in (SEED or "").split(",") if s.strip()]
        report = bootstrap.write_overlay(seeds, DATASET, OUT, id_field=ID_FIELD, gt_field=GT_FIELD,
                                         pred_field=PRED_FIELD or "label", review_path=REVIEW)
    else:
        sys.exit(f"ACTION must be sample, merge or overlay; got {ACTION!r}")
except bootstrap.SeedMergeRefused as e:
    sys.exit(f"ERROR: {e}. Nothing written.")
except DataPreparerOperatorError as e:
    sys.exit(f"ERROR: {e}. Nothing written.")
print(json.dumps(report, indent=2, ensure_ascii=False))
