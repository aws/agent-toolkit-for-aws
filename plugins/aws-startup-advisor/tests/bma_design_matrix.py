"""Loads fixtures/bma-design-model-matrix/matrix.json and builds the profile and preferences each row describes."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PLUGIN_ROOT / "fixtures"
MATRIX_PATH = FIXTURES / "bma-design-model-matrix" / "matrix.json"
PREFS_BASE = FIXTURES / "bma-design-openai-mantle-and-runtime" / "preferences.json"
CRIS_PREFIX = re.compile(r"^(us|us-gov|eu|apac|jp|au|ca|in|global)\.")
CAPABILITY_FLAGS = {"text_generation": "text_generation", "embedding": "embeddings", "image_generation": "image_generation",
                    "speech_to_text": "speech_to_text", "text_to_speech": "text_to_speech"}


def load() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def base_id(model_id: str) -> str:
    return CRIS_PREFIX.sub("", model_id)


def matches(allowed: list[str], target: str) -> bool:
    target = target if target.startswith("service:") else base_id(target)
    return any(target == a or (a.endswith("*") and target.startswith(a[:-1])) for a in allowed)


def build_profile(source: dict) -> dict:
    """A one-workload 1.1 profile cut from the source's fixture, with the model renamed when the source says so."""
    profile = json.loads((FIXTURES / source["fixture"] / "ai-workload-profile.json").read_text(encoding="utf-8"))
    workload = copy.deepcopy(next(w for w in profile["workloads"] if w["workload_id"] == source["workload_id"]))
    old, new = workload["model"], source["model"]
    workload.update(source.get("workload", {}))
    workload["model"] = new
    workload["workload_id"] = f"{workload['source_service']}.{new}.{workload['sdk_method']}.plain"
    src = copy.deepcopy(next(s for s in profile["ai_sources"]
                             if (s["provider"], s["source_service"]) == (workload["provider"], workload["source_service"])))
    observation = copy.deepcopy(next(o for o in src["model_observations"] if o["normalized_model"] == old))
    observation.update(normalized_model=new, raw_model=new)
    src.update(models=[new], model_observations=[observation])
    summary = {k: False for k in profile["integration"]["capabilities_summary"]}
    summary[CAPABILITY_FLAGS[workload["capability"]]] = True
    integration = dict(profile["integration"], capabilities_summary=summary)
    return {"schema_version": profile["schema_version"], "ai_sources": [src], "gateways": [], "integration": integration,
            "workloads": [workload], "mantle_signals": []}


def build_preferences(row: dict) -> dict:
    """The preferences.json a full Clarify would write for this row, with no Mantle-only requirement."""
    prefs = json.loads(PREFS_BASE.read_text(encoding="utf-8"))
    for key, value in row["preferences"].items():
        prefs["ai_constraints"][key].update(value=value, chosen_by="user", design_consequence=f"{value} shapes the model choice")
        prefs["ai_constraints"][key].pop("source", None)
    prefs["ai_constraints"]["mantle_requirements"]["value"] = [{"workload_id": "*", "selector": "none", "source": "user"}]
    return prefs
