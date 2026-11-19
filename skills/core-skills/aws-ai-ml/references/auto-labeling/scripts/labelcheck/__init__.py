"""The person's side of label review: the apply step (lc_decide). The checks, the judge,
the ranking and contradictions.csv come from the labeling job (Config.Review,
scripts/review_labels.py). The decisions are the V3 SDK's
operators.auto_labeling.label_decisions; lc_decide re-exports them.
"""
