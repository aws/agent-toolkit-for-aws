"""Contract tests for the target-only ai-capability-catalog.json reference data file.

Pins the schema's self-validity, the canonical data file's structural and semantic
correctness (no duplicate provider/gateway identity, every gateway upstream_providers[]
entry exists in providers[]), the byte-identity of every vendored copy, and a set of
negative mutations the schema (or the semantic check) must reject. Target-only: this is
a static reference catalog, not a per-run produced artifact — implemented_adapter/route
are null/unknown everywhere and no adapter or route is claimed to exist.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CATALOG_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "ai-capability-catalog.schema.json"
CATALOG_DATA = PLUGIN_ROOT / "skills" / "shared" / "ai" / "ai-capability-catalog.json"
VALIDATOR_PATH = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"

VENDORED_COPIES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "vendored" / "ai" / "ai-capability-catalog.json",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "vendored" / "ai" / "ai-capability-catalog.json",
]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("ai_capability_catalog__validator", VALIDATOR_PATH)


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _catalog_schema() -> dict:
    return _load(CATALOG_SCHEMA)


def _catalog_findings(catalog: dict) -> list:
    findings = []
    VALIDATOR.validate_json_schema(_catalog_schema(), catalog, "", "catalog", str(CATALOG_SCHEMA), findings)
    return findings


def _assert_catalog_semantics(catalog: dict) -> None:
    """Duplicate-identity rejection and the gateway-upstream-points-at-a-real-provider
    cross-array check — a check the schema itself cannot express."""
    provider_identities = set()
    for provider in catalog["providers"]:
        identity = provider["identity"]
        assert identity not in provider_identities, f"duplicate provider identity: {identity}"
        provider_identities.add(identity)

    gateway_identities = set()
    for gateway in catalog["gateways"]:
        identity = gateway["identity"]
        assert identity not in gateway_identities, f"duplicate gateway identity: {identity}"
        gateway_identities.add(identity)

        for upstream in gateway["upstream_providers"]:
            assert upstream in provider_identities, (
                f"gateway {identity!r} names upstream_provider {upstream!r} not declared in providers[]"
            )


def _base_catalog() -> dict:
    return copy.deepcopy(_load(CATALOG_DATA))


# --------------------------------------------------------------------------- schema self-validity

def test_schema_has_no_unsupported_keywords() -> None:
    assert VALIDATOR.unsupported_keywords(_catalog_schema()) == []


def test_schema_is_valid_json_and_draft07_shaped() -> None:
    schema = _catalog_schema()
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"


# --------------------------------------------------------------------------- positive fixture

def test_canonical_catalog_validates_against_schema() -> None:
    assert _catalog_findings(_load(CATALOG_DATA)) == []


def test_canonical_catalog_satisfies_semantic_invariants() -> None:
    _assert_catalog_semantics(_load(CATALOG_DATA))


def test_canonical_catalog_never_claims_an_implemented_adapter_or_route() -> None:
    """Target-only invariant: implemented_adapter/route are null on every entry,
    regardless of a provider's or gateway's status."""
    catalog = _load(CATALOG_DATA)
    for provider in catalog["providers"]:
        assert provider["implemented_adapter"] is None
    for gateway in catalog["gateways"]:
        assert gateway["route"] is None


# --------------------------------------------------------------------------- vendored-copy byte-identity

@pytest.mark.parametrize("vendored_path", VENDORED_COPIES, ids=lambda p: str(p.relative_to(PLUGIN_ROOT)))
def test_vendored_copy_is_byte_identical_to_canonical(vendored_path: Path) -> None:
    assert vendored_path.read_bytes() == CATALOG_DATA.read_bytes(), (
        f"{vendored_path} has drifted from canonical {CATALOG_DATA} — "
        "run tools/sync-vendored.py"
    )


# --------------------------------------------------------------------------- negative mutations

def test_duplicate_provider_identity_is_rejected() -> None:
    catalog = _base_catalog()
    catalog["providers"].append(copy.deepcopy(catalog["providers"][0]))
    if not _catalog_findings(catalog):
        with pytest.raises(AssertionError):
            _assert_catalog_semantics(catalog)
    else:
        assert _catalog_findings(catalog)


def test_openrouter_as_a_direct_provider_identity_is_rejected() -> None:
    catalog = _base_catalog()
    catalog["providers"][0]["identity"] = "openrouter"
    assert _catalog_findings(catalog) != []


def test_invalid_status_enum_value_is_rejected() -> None:
    catalog = _base_catalog()
    catalog["providers"][0]["status"] = "maybe"
    assert _catalog_findings(catalog) != []


def test_non_null_malformed_implemented_adapter_is_rejected() -> None:
    catalog = _base_catalog()
    catalog["providers"][0]["implemented_adapter"] = "Not Valid!"
    assert _catalog_findings(catalog) != []


def test_missing_required_field_is_rejected() -> None:
    catalog = _base_catalog()
    del catalog["providers"][0]["source_services"]
    assert _catalog_findings(catalog) != []


def test_gateway_upstream_provider_absent_from_providers_is_rejected_semantically() -> None:
    """This is a cross-array check the schema cannot express (it has no way to compare
    one array's contents against another's) — document it as semantic, not schema-level,
    the same distinction test_ai_workload_profile_contracts.py draws."""
    catalog = _base_catalog()
    catalog["gateways"][0]["upstream_providers"].append("nonexistent_provider")
    assert _catalog_findings(catalog) == []
    with pytest.raises(AssertionError):
        _assert_catalog_semantics(catalog)
