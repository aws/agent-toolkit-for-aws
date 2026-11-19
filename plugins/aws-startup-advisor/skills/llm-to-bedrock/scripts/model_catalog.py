"""Model facts llm-to-bedrock's scripts read from the shared model catalogs.

The catalogs are rendered from skills/shared/ai/models/bedrock-model-registry.json and vendored
into this skill at references/vendored/ai/models/, so the skill runs standalone. Edit the
registry, run tools/build-model-catalogs.py and tools/sync-vendored.py; never restate these
facts in code.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "references" / "vendored" / "ai" / "models"
CATALOG_FILES = ("anthropic-bedrock.json", "openai-bedrock.json")

# Cross-Region inference profile prefixes used by Bedrock models the catalogs do not cover
# (for example Nova and older Claude models on `apac.` profiles). Kept so their ids are still
# recognised as inference profiles.
_EXTRA_PROFILE_PREFIXES = frozenset({"apac"})

OPUS_55_ID = "anthropic.claude-opus-5-5"


@lru_cache(maxsize=1)
def catalog_models() -> dict:
    """Every catalog model record, keyed by the catalog's model key."""
    models: dict = {}
    for name in CATALOG_FILES:
        models.update(json.loads((MODELS_DIR / name).read_text())["models"])
    return models


@lru_cache(maxsize=1)
def profile_prefixes() -> frozenset:
    """Every inference-profile prefix a catalog model publishes, plus the legacy extras."""
    prefixes = set(_EXTRA_PROFILE_PREFIXES)
    for model in catalog_models().values():
        prefixes.update(model.get("inference_profiles", {}))
    return frozenset(prefixes)


@lru_cache(maxsize=1)
def profile_prefix_regex() -> re.Pattern:
    """Matches a leading `<prefix>.` for any known inference-profile prefix."""
    alternatives = "|".join(sorted((re.escape(p) for p in profile_prefixes()), key=len, reverse=True))
    return re.compile(rf"^({alternatives})\.")


def _records_for(model_id: str) -> list:
    """Every catalog record for `model_id`. A model can appear in both catalogs (the OpenAI
    view carries the Claude cross-family targets); both are rendered from one registry record."""
    found = [m for m in catalog_models().values()
             if any(p.get("model_id") == model_id for p in m.get("paths", {}).values())]
    if not found:
        raise KeyError(model_id)
    return found


def _agreed(model_id: str, read):
    """`read(record)` for `model_id`, failing loudly if the catalogs disagree. A record whose
    view does not carry the field (`read` returns None) is skipped: each provider view keeps
    only the paths it uses."""
    values = {json.dumps(v, sort_keys=True) for v in (read(r) for r in _records_for(model_id)) if v is not None}
    if not values:
        raise KeyError(f"no catalog record for {model_id} carries this field")
    if len(values) != 1:
        raise ValueError(f"catalogs disagree on {model_id}: {sorted(values)}")
    return json.loads(values.pop())


def opus_55_mantle_regions() -> frozenset:
    """Regions where bare Opus 5.5 is served on bedrock-mantle (Messages)."""
    def read(record):
        path = record["paths"].get("mantle_messages")
        if path is None:
            return None
        return sorted(path.get("regions", [])) if path.get("available") else []
    return frozenset(_agreed(OPUS_55_ID, read))


def opus_55_runtime_in_region_regions() -> frozenset:
    """Regions where bare Opus 5.5 is a bedrock-runtime in-region target."""
    return frozenset(_agreed(OPUS_55_ID, lambda r: sorted(r["runtime_in_region_regions"]) if "runtime_in_region_regions" in r else None))


def opus_55_profile_regions() -> dict:
    """Opus 5.5's inference-profile prefixes mapped to their source Regions, in catalog order."""
    _agreed(OPUS_55_ID, lambda r: {k: sorted(v) for k, v in r["inference_profiles"].items()}
            if "inference_profiles" in r else None)
    record = next(r for r in _records_for(OPUS_55_ID) if "inference_profiles" in r)
    return {k: list(v) for k, v in record["inference_profiles"].items()}
