---
_assemble: assemble-model-recommend
_of_phase: model-recommend
_reads:
  - answers.json
  - scoring-result.json
  - context-signals.json when present
_produces:
  - model-recommendation-input.json
  - model-recommendation.json
_knowledge:
  - { file: references/models/anthropic-bedrock-2026-07-21.json }
---

# Model Recommend — Assemble the recommendation contract

The phase writes the normalized per-workload v2 input, then
`scripts/model_recommendation.py` creates `model-recommendation.json`. The script output is the
joint model/path contract; downstream phases consume it by workload id and do not rerank it.
`decision_required` entries must be resolved and rerun before completion. When the user approves
a live probe, `scripts/verify_model_path.py` separately writes `model-verification.json`;
recommendation acceptance never implies account invocability.
