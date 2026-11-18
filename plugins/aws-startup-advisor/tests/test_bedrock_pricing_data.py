"""Tests for skills/shared/ai/bedrock-pricing.json, the single source of truth for Bedrock token rates.

The JSON is checked against its schema, against itself (every priced prefix has a long-context
rate when the model has that tier), and against bedrock-pricing-cache.md: every table row whose
model id the JSON prices must state the same rate, so the human-readable cache and the
machine-readable table cannot drift apart.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SHARED_AI = PLUGIN_ROOT / "skills" / "shared" / "ai"
PRICING_PATH = SHARED_AI / "bedrock-pricing.json"
CACHE_PATH = SHARED_AI / "bedrock-pricing-cache.md"
SCHEMA_PATH = PLUGIN_ROOT / "scripts" / "contracts" / "bedrock-pricing.schema.json"
VENDORED_COPY = PLUGIN_ROOT / "skills" / "llm-to-bedrock" / "references" / "vendored" / "ai" / "bedrock-pricing.json"
REGISTRY_PATH = SHARED_AI / "models" / "bedrock-model-registry.json"

PROFILE_PREFIXES = {"global", "us", "eu", "in", "au", "jp", "ca", "apac", "us-gov"}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("bedrock_pricing_data__validator", PLUGIN_ROOT / "scripts" / "validate-artifacts.py")


def _pricing() -> dict:
    return json.loads(PRICING_PATH.read_text())


def _schema_findings(value) -> list:
    out: list = []
    VALIDATOR.validate_json_schema(json.loads(SCHEMA_PATH.read_text()), value, "", "pricing",
                                   str(SCHEMA_PATH), out)
    return out


def _cache_rows():
    """(model id, input, output, is_long_context_row, status) for each quick-reference row."""
    for line in CACHE_PATH.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 8 or not re.match(r"^[a-z]+\.", cells[1]):
            continue
        try:
            rate_in, rate_out = float(cells[3]), float(cells[4])
        except ValueError:
            continue
        long_context = cells[5].startswith(">") or cells[5].endswith("+") or "Long Context" in cells[0]
        yield cells[1], rate_in, rate_out, long_context, cells[7]


def _split(model_id: str):
    prefix, _, rest = model_id.partition(".")
    return (prefix, rest) if prefix in PROFILE_PREFIXES else ("bare", model_id)


# ------------------------------------------------------------------ the checked-in file

def test_schema_uses_only_enforced_keywords_and_accepts_the_file():
    assert VALIDATOR.unsupported_keywords(json.loads(SCHEMA_PATH.read_text())) == []
    assert _schema_findings(_pricing()) == []


def test_llm_to_bedrock_reads_a_byte_identical_vendored_copy():
    assert VENDORED_COPY.read_bytes() == PRICING_PATH.read_bytes()


def test_long_context_tier_covers_every_priced_prefix():
    for bare, model in _pricing()["models"].items():
        lc = model.get("long_context")
        if lc:
            assert set(lc["rates"]) == set(model["rates"]), bare
            for prefix, rate in lc["rates"].items():
                base = model["rates"][prefix]
                assert rate["input"] > base["input"] and rate["output"] >= base["output"], (bare, prefix)


def test_registry_no_longer_carries_pricing():
    registry = json.loads(REGISTRY_PATH.read_text())
    assert not [k for k, m in registry["models"].items() if "pricing" in m]


# ------------------------------------------------------------------ cache agreement

def test_every_cache_row_for_a_priced_model_matches_the_json():
    models = _pricing()["models"]
    checked, errors = 0, []
    for model_id, rate_in, rate_out, long_context, _status in _cache_rows():
        prefix, bare = _split(model_id)
        if bare not in models:
            continue
        model = models[bare]
        if long_context and "long_context" in model:
            rates = model["long_context"]["rates"]
        else:
            # A long-context row for a model with no long-context tier states the base rate.
            rates = model["rates"]
        rate = rates.get(prefix)
        checked += 1
        if rate is None:
            errors.append(f"{model_id}: the cache lists a {prefix} rate the JSON does not price")
        elif (rate["input"], rate["output"]) != (rate_in, rate_out):
            errors.append(f"{model_id}: cache {rate_in}/{rate_out} != JSON {rate['input']}/{rate['output']}")
    assert not errors, errors
    assert checked >= 20, f"only {checked} cache rows matched a JSON model; the row parser may be broken"


def test_cache_check_catches_a_drifted_rate(monkeypatch, tmp_path):
    drifted = CACHE_PATH.read_text().replace(
        "| global.anthropic.claude-sonnet-5-5       | Anthropic | 2.00       | 10.00",
        "| global.anthropic.claude-sonnet-5-5       | Anthropic | 2.50       | 10.00")
    assert drifted != CACHE_PATH.read_text(), "fixture row not found; update the probe"
    fake = tmp_path / "cache.md"
    fake.write_text(drifted)
    monkeypatch.setattr(sys.modules[__name__], "CACHE_PATH", fake)
    with pytest.raises(AssertionError, match="global.anthropic.claude-sonnet-5-5"):
        test_every_cache_row_for_a_priced_model_matches_the_json()


def test_cache_points_readers_at_the_json_for_profile_rates():
    text = " ".join(CACHE_PATH.read_text().replace("\n> ", "\n").split())
    assert "The per-profile source of truth is `bedrock-pricing.json`" in text
    assert "STATIC_FALLBACK" not in text


def test_every_vendored_cache_has_the_json_it_points_to():
    # Review on #669: the cache says bedrock-pricing.json is "in this directory", so every
    # skill that vendors the cache must vendor the JSON beside it, byte-identical.
    caches = sorted((PLUGIN_ROOT / "skills").glob("*/references/vendored/ai/bedrock-pricing-cache.md"))
    assert len(caches) >= 4, caches
    canonical = PRICING_PATH.read_bytes()
    for cache in caches:
        sibling = cache.with_name("bedrock-pricing.json")
        assert sibling.is_file(), f"{cache.parent}: has the cache but not bedrock-pricing.json"
        assert sibling.read_bytes() == canonical, sibling
        manifest = (cache.parent.parent / "README.md").read_text()
        assert "| `ai/bedrock-pricing.json`" in manifest, cache.parent.parent
