"""Tests for scripts/validate-artifacts.py — the artifact-contract validator.

Two layers: unit tests on the shape-template builder / validator (so a contract-document
convention that stops parsing is caught here, not in CI noise), and CLI tests against the
real repository (self-check passes, fixtures pass with the baseline, and an injected
off-contract key FAILS — the regression this tool exists to catch).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_artifacts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_artifacts"] = mod
    spec.loader.exec_module(mod)
    return mod


va = _load()


# --------------------------------------------------------------------------- JSONC stripping


def test_strip_jsonc_removes_comments_outside_strings_only():
    text = '{\n  "url": "https://x/y", // keep the url\n  "n": 1, // REQUIRED\n}'
    out, comments, keys = va.strip_jsonc(text)
    v = json.loads(out)
    assert v == {"url": "https://x/y", "n": 1}
    assert comments[1] == "keep the url" and keys[1] == "url"
    assert comments[2] == "REQUIRED" and keys[2] == "n"


def test_strip_jsonc_handles_ellipsis_and_bool_alternation():
    out, _, _ = va.strip_jsonc('{"a": ["Q1", ...], "b": true|false}')
    assert json.loads(out) == {"a": ["Q1", "..."], "b": True}


# --------------------------------------------------------------------------- template inference


def _node(example: str):
    text, comments, keys = va.strip_jsonc(example)
    kc = {}
    for ln, c in comments.items():
        k = keys.get(ln)
        if k:
            kc.setdefault(k, []).append(c)
    return va.build_node(json.loads(text), kc, "test")


def test_enum_from_pipe_string_and_from_comment():
    n = _node('{"status": "full|reduced", "tier": "compute", // network | data | compute\n}')
    assert n.keys["status"].enum == {"full", "reduced"}
    assert n.keys["tier"].enum == {"network", "data", "compute"}


def test_required_from_comment_and_placeholder_is_any_type():
    n = _node('{"id": "<uuid>", // REQUIRED\n "n": "<Q13 value>"}')
    assert "id" in n.required
    assert n.keys["n"].is_any()  # a placeholder says nothing about the JSON type


def test_placeholder_key_makes_object_open_and_sets_any_key_template():
    n = _node('{"<key>": {"value": 1, "chosen_by": "user|default"}}')
    assert n.wildcard and n.any_key is not None
    assert set(n.any_key.keys) == {"value", "chosen_by"}


# --------------------------------------------------------------------------- shape validation


def _validate(example: str, instance, allowed_anywhere=()):
    n = _node(example)
    if allowed_anywhere:
        va._mark_allowed_anywhere(n, set(allowed_anywhere))
    out = []
    va.validate_shape(n, instance, "", "art.json", "contract", out)
    return {(f.code, f.path) for f in out}


def test_unknown_key_is_reported_but_underscore_keys_are_not():
    found = _validate('{"a": 1, "b": "x"}', {"a": 1, "b": "x", "c": 2, "_comment": "ok"})
    assert found == {("UNKNOWN_KEY", "c")}


def test_missing_required_type_mismatch_enum_violation():
    ex = '{"a": 1, // REQUIRED\n "s": "full|reduced", "arr": [{"k": true}]}'
    found = _validate(ex, {"s": "partial", "arr": [{"k": "no"}]})
    assert ("MISSING_REQUIRED", "a") in found
    assert ("ENUM_VIOLATION", "s") in found
    assert ("TYPE_MISMATCH", "arr[0].k") in found


def test_null_is_tolerated_and_open_objects_accept_anything():
    found = _validate('{"a": 1, "cfg": {"...": "..."}}', {"a": None, "cfg": {"anything": [1, 2]}})
    assert found == set()


def test_any_key_template_applies_to_named_children():
    ex = '{"rows": {"<key>": {"value": "x", "chosen_by": "user|default"}}}'
    found = _validate(ex, {"rows": {"q1": {"value": "y", "chosen_by": "user", "extra": 1}}})
    assert found == {("UNKNOWN_KEY", "rows.q1.extra")}


def test_allowed_anywhere_vocabulary():
    ex = '{"g": {"r": {"value": 1}}}'
    assert _validate(ex, {"g": {"r": {"value": 1, "source": "live"}}}) == {("UNKNOWN_KEY", "g.r.source")}
    assert _validate(ex, {"g": {"r": {"value": 1, "source": "live"}}}, allowed_anywhere=["source"]) == set()


# --------------------------------------------------------------------------- JSON Schema subset


def test_json_schema_subset():
    schema = {
        "type": "object",
        "required": ["phase"],
        "additionalProperties": False,
        "properties": {
            "phase": {"const": "estimate"},
            "tier": {"type": "string", "enum": ["small", "medium"]},
            "items": {"type": "array", "items": {"type": "integer", "minimum": 0}},
            "id": {"type": "string", "pattern": "^[a-z]+$"},
        },
    }
    out = []
    va.validate_json_schema(schema, {"phase": "design", "tier": "huge", "items": [-1, "x"], "id": "A1", "zzz": 1},
                            "", "a.json", "s", out)
    codes = {(f.path, f.message.split(",")[0]) for f in out}
    assert ("phase", "'design' != const 'estimate'") in codes
    assert any(p == "tier" for p, _ in codes)
    assert any(p == "items[0]" for p, _ in codes) and any(p == "items[1]" for p, _ in codes)
    assert any(p == "id" for p, _ in codes)
    assert ("zzz", "additionalProperties is false") in codes
    ok = []
    va.validate_json_schema(schema, {"phase": "estimate", "tier": "small", "items": [1], "id": "ab"}, "", "a", "s", ok)
    assert ok == []


# --------------------------------------------------------------------------- baseline


def test_baseline_marks_matches_and_reports_stale_entries():
    f1 = va.Finding("UNKNOWN_KEY", "fixtures/x/a.json", "resources[3].id", "m")
    f2 = va.Finding("UNKNOWN_KEY", "fixtures/x/a.json", "other", "m")
    stale = va.apply_baseline([f1, f2], {"entries": [
        {"code": "UNKNOWN_KEY", "artifact": "fixtures/x/*", "path": "resources[[]*[]].id", "reason": "r"},
        {"code": "UNKNOWN_KEY", "artifact": "fixtures/x/*", "path": "never.matches", "reason": "r"},
    ]})
    assert f1.baselined and f1.baseline_reason == "r"
    assert not f2.baselined
    assert len(stale) == 1 and stale[0]["path"] == "never.matches"


# --------------------------------------------------------------------------- CLI against the real repo


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=PLUGIN_ROOT)


def test_self_check_passes_every_contract_document_parses():
    r = _run("--self-check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_fixtures_pass_with_baseline_and_no_stale_entries():
    r = _run("--fixtures", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["checked_artifacts"] > 0
    assert report["errors"] == []
    assert report["stale_baseline_entries"] == [], "remove baseline entries that no longer match anything"


def test_injected_off_contract_key_fails(tmp_path: Path):
    """The regression this tool exists for: a producer emits a key its contract never
    documented. Copy a golden run, plant the key, expect exit 1 naming the path."""
    src = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-discover"
    run = tmp_path / "run"
    shutil.copytree(src, run)
    inv = run / "azure-resource-inventory.json"
    data = json.loads(inv.read_text())
    data["resources"][0]["invented_by_a_phase_file"] = True
    inv.write_text(json.dumps(data))
    r = _run("--run-dir", str(run), "--skill", "azure-to-aws", "--no-baseline", "--json")
    assert r.returncode == 1
    report = json.loads(r.stdout)
    assert any(e["code"] == "UNKNOWN_KEY" and e["path"] == "resources[0].invented_by_a_phase_file"
               for e in report["errors"]), report["errors"]


def test_empty_phases_fails_min_properties(tmp_path: Path):
    """Review finding on #385: phase-status.schema.json has `minProperties: 1` on `phases`
    and the subset silently skipped it, so `phases: {}` passed."""
    run = tmp_path / "run"
    run.mkdir()
    (run / ".phase-status.json").write_text(json.dumps(
        {"migration_id": "x", "last_updated": "2026-01-01T00:00:00Z", "phases": {}}))
    r = _run("--run-dir", str(run), "--skill", "gcp-to-aws", "--no-baseline", "--json")
    assert r.returncode == 1
    errs = json.loads(r.stdout)["errors"]
    assert any(e["code"] == "SCHEMA_VIOLATION" and e["path"] == "phases" and "minProperties" in e["message"]
               for e in errs), errs


def test_schema_keyword_the_subset_does_not_implement_is_rejected_at_load():
    """The class behind the minProperties hole: a keyword the subset does not know must
    surface as SCHEMA_PARSE, never be skipped."""
    schema = {"type": "object", "properties": {"a": {"type": "string", "contentEncoding": "base64"}},
              "dependencies": {"a": ["b"]}}
    found = va.unsupported_keywords(schema)
    assert ("#/properties/a", "contentEncoding") in found
    assert ("#", "dependencies") in found
    # every keyword the two real schemas use is either enforced or an annotation
    for p in (PLUGIN_ROOT / "skills/shared/state/phase-status.schema.json",
              PLUGIN_ROOT / "skills/shared/estimate/estimation-infra.schema.json"):
        assert va.unsupported_keywords(json.loads(p.read_text())) == [], p.name


def test_stale_baseline_entry_fails_the_gate(tmp_path: Path):
    """Review finding on #385: a baseline entry matching nothing printed a warning and
    exited 0, so the burn-down list could only shrink if someone read the log."""
    src = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-discover"
    run = tmp_path / "run"
    shutil.copytree(src, run)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"entries": [
        {"code": "UNKNOWN_KEY", "artifact": "*", "path": "never.matches.anything", "reason": "stale"}]}))
    r = _run("--run-dir", str(run), "--skill", "azure-to-aws", "--baseline", str(baseline), "--json")
    assert r.returncode == 1
    report = json.loads(r.stdout)
    assert any(e["code"] == "STALE_BASELINE" for e in report["errors"]), report["errors"]
    assert report["stale_baseline_entries"][0]["path"] == "never.matches.anything"


def test_real_json_schema_violation_fails(tmp_path: Path):
    src = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-estimate"
    run = tmp_path / "run"
    shutil.copytree(src, run)
    p = run / "estimation-infra.json"
    data = json.loads(p.read_text())
    data["complexity_tier"] = "enormous"
    p.write_text(json.dumps(data))
    r = _run("--run-dir", str(run), "--skill", "azure-to-aws", "--no-baseline", "--json")
    assert r.returncode == 1
    assert any(e["code"] == "SCHEMA_VIOLATION" and e["path"] == "complexity_tier" for e in json.loads(r.stdout)["errors"])
