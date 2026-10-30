from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins/aws-startup-advisor"
SKILL_ROOT = PLUGIN_ROOT / "skills/render-to-aws"
SCHEMA = PLUGIN_ROOT / "scripts/contracts/ai-workload-profile.schema.json"
VENDORED = SKILL_ROOT / "references/contracts/ai-workload-profile.schema.json"
FIXTURES = sorted((PLUGIN_ROOT / "fixtures/ai-workload-profiles").glob("*/ai-workload-profile.json"))
SHARED_AI = PLUGIN_ROOT / "skills/shared/ai"
IDENTITY_KEYS = ("provider", "source_service", "product", "type", "model_family", "normalized_model", "family")


def _load_scanner():
    script = SKILL_ROOT / "scripts/scan-render-application.py"
    if str(script.parent) not in sys.path:
        sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location("scan_render_application_contract", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def render_profile() -> dict:
    return _load_scanner().scan(SKILL_ROOT / "fixtures/render-application")["ai_profile"]


def _identity_strings(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in IDENTITY_KEYS and isinstance(item, str):
                yield key, item
            yield from _identity_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _identity_strings(item)


def test_vendored_415_schema_is_byte_identical_to_canonical() -> None:
    assert VENDORED.read_bytes() == SCHEMA.read_bytes()


def test_shared_ai_has_no_competing_profile_schema() -> None:
    assert not list(SHARED_AI.glob("*workload-profile*"))
    assert not (SKILL_ROOT / "references/contracts/schema-ai-workload-profile.json").exists()


@pytest.mark.parametrize("fixture", FIXTURES, ids=[path.parent.name for path in FIXTURES])
def test_upstream_fixtures_validate(fixture: Path) -> None:
    assert len(FIXTURES) == 4
    jsonschema.Draft7Validator(schema()).validate(json.loads(fixture.read_text(encoding="utf-8")))


def test_render_profile_validates_is_deterministic_and_has_no_execution() -> None:
    first = render_profile()
    second = render_profile()
    assert canonical(first) == canonical(second)
    jsonschema.Draft7Validator(schema()).validate(first)
    assert "execution" not in first
    assert set(first) == {"schema_version", "ai_sources", "gateways"}


def test_render_never_emits_openrouter_both_or_unknown_as_identities() -> None:
    profile = render_profile()
    for key, value in _identity_strings(profile):
        assert value not in {"both", "unknown"}, (key, value)
        if value == "openrouter":
            assert key == "product"
    assert all(source["provider"] != "openrouter" for source in profile["ai_sources"])
    assert {source["provider"] for source in profile["ai_sources"]} <= {"anthropic", "openai", "google"}


def test_schema_rejects_openrouter_as_provider() -> None:
    candidate = deepcopy(render_profile())
    candidate["ai_sources"][0]["provider"] = "openrouter"
    assert list(jsonschema.Draft7Validator(schema()).iter_errors(candidate))


@pytest.mark.parametrize("identity", ["both", "unknown"])
def test_schema_rejects_both_and_unknown_identities(identity: str) -> None:
    validator = jsonschema.Draft7Validator(schema())
    for path in (("ai_sources", 0, "provider"), ("ai_sources", 0, "source_service"), ("gateways", 0, "product")):
        candidate = deepcopy(render_profile())
        target = candidate
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = identity
        assert list(validator.iter_errors(candidate)), path


def test_schema_rejects_additional_properties() -> None:
    validator = jsonschema.Draft7Validator(schema())
    candidate = deepcopy(render_profile())
    candidate["execution"] = {
        "status": "deferred_shared_ai_engine",
        "profile_path": "ai-workload-profile.json",
        "profile_digest": "sha256:" + "a" * 64,
        "reason": "provider-neutral AI Design, Estimate, and Generate execution is not available",
        "resume_from": "ai-workload-profile.json",
    }
    assert list(validator.iter_errors(candidate))
    candidate = deepcopy(render_profile())
    candidate["ai_sources"][0]["confidence"] = "deterministic"
    assert list(validator.iter_errors(candidate))


def test_discovery_doc_covers_every_identity_and_ordering() -> None:
    contract = (SKILL_ROOT / "references/shared/schema-render-ai-discovery.md").read_text(encoding="utf-8")
    for label in ("workload", "provider", "model", "gateway", "evidence", "call site", "relationship", "fingerprint"):
        assert label in contract
    assert "render-ai-discovery.json" in contract
    assert "Unicode NFC" in contract
    assert "SHA-256 lowercase hexadecimal" in contract
    assert "UTF-8 bytes of its ID" in contract
    assert "Reject duplicate normalized identity inputs" in contract
