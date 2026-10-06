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


def test_empty_array_item_is_replaced_when_a_concrete_shape_arrives():
    """Review finding on #387: `"services": []` seeded an `any` item, and merging the
    later object kept `any`, so a scalar or nested list passed."""
    seed = _node('{"services": [], "warnings": []}')
    seed.merge(_node('{"services": [{"routing_provenance": "table", // REQUIRED\n "n": 1}]}'))
    item = seed.keys["services"].item
    assert not item.is_any() and "object" in item.kinds
    assert "routing_provenance" in item.required
    seed.merge(_node('{"services": []}'))
    assert not seed.keys["services"].item.is_any()
    ex = '{"services": [{"routing_provenance": "table", // REQUIRED\n "n": 1}]}'
    root = _node('{"services": []}')
    root.merge(_node(ex))

    def check(value):
        out = []
        va.validate_shape(root, value, "", "a", "c", out)
        return {(f.code, f.path) for f in out}

    assert check({"services": []}) == set()
    assert check({"services": [{"routing_provenance": "table", "n": 1}]}) == set()
    assert check({"services": [None]}) == set()
    assert ("TYPE_MISMATCH", "services[0]") in check({"services": ["not-an-object"]})
    assert ("TYPE_MISMATCH", "services[0]") in check({"services": [17]})
    assert ("TYPE_MISMATCH", "services[0]") in check({"services": [False]})
    assert ("TYPE_MISMATCH", "services[0]") in check({"services": [[]]})
    assert ("MISSING_REQUIRED", "services[0].routing_provenance") in check({"services": [{}]})
    ph = _node('{"ids": ["<azure_id>"]}')
    assert ph.keys["ids"].item.is_any()
    out = []
    va.validate_shape(ph, {"ids": [1, "x", False]}, "", "a", "c", out)
    assert out == []


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


# --------------------------------------------------------------------------- template merging


def test_merge_keeps_declared_enum_when_a_concrete_example_shows_one_member():
    """Review finding on #385: merging `"confidence": "full"` (a Complete Example) into
    `"confidence": "full|reduced"` cleared the enum, so any string passed."""
    declared = _node('{"confidence": "full|reduced"}')
    declared.merge(_node('{"confidence": "full"}'))
    assert declared.keys["confidence"].enum == {"full", "reduced"}
    # the other direction too (the example is seen before the declaration)
    example = _node('{"confidence": "full"}')
    example.merge(_node('{"confidence": "full|reduced"}'))
    assert example.keys["confidence"].enum == {"full", "reduced"}
    # a concrete token the document shows that the enum omitted is documented by that example
    declared.merge(_node('{"confidence": "partial"}'))
    assert declared.keys["confidence"].enum == {"full", "reduced", "partial"}
    # only a free-text example (not a token) proves the field is not an enum
    declared.merge(_node('{"confidence": "Using cached prices from 2026-03-04 (±5%)"}'))
    assert declared.keys["confidence"].enum is None


def test_merge_copies_adopted_children_so_a_named_refinement_does_not_leak_into_the_generic_template():
    """Review finding on #385/#387: `design_constraints.cpu_architecture` was seeded from the
    `<key>` template by reference, so refining it widened `chosen_by` on every row."""
    root = _node('{"design_constraints": {"<key>": {"value": "<v>", "chosen_by": "user|default|extracted"}}}')
    target = va._walk_path(root, "design_constraints.cpu_architecture")
    target.merge(_node('{"value": "graviton", "chosen_by": "default"}'))
    generic = root.keys["design_constraints"].any_key.keys["chosen_by"]
    assert generic.enum == {"user", "default", "extracted"}
    assert target.keys["chosen_by"].enum == {"user", "default", "extracted"}
    out = []
    va.validate_shape(root, {"design_constraints": {"target_region": {"value": "us-east-1", "chosen_by": "invalid-origin"},
                                                    "cpu_architecture": {"value": "graviton", "chosen_by": "bogus"}}},
                      "", "a", "c", out)
    assert {(f.code, f.path) for f in out} == {("ENUM_VIOLATION", "design_constraints.target_region.chosen_by"),
                                               ("ENUM_VIOLATION", "design_constraints.cpu_architecture.chosen_by")}


def test_joined_set_qualifier_allows_plus_joined_members_but_not_unknown_ones():
    """Review finding on #386/#387: `terraform | live | billing (or a "+"-joined set)` was read
    as a closed enum, so the documented `live+terraform` provenance failed."""
    ex = ('{"source": "terraform", // terraform | bicep | arm | live | rdfa | billing (or a "+"-joined set)\n'
          ' "prov": "table", // table | rubric\n}')
    n = _node(ex)
    assert n.keys["source"].enum_join == "+" and n.keys["prov"].enum_join is None
    assert _validate(ex, {"source": "live+terraform", "prov": "table"}) == set()
    assert _validate(ex, {"source": "terraform", "prov": "table"}) == set()
    assert _validate(ex, {"source": "terraform+bogus", "prov": "table"}) == {("ENUM_VIOLATION", "source")}
    assert _validate(ex, {"source": "live", "prov": "table+rubric"}) == {("ENUM_VIOLATION", "prov")}


def test_wrapped_array_example_merges_at_the_array_level(tmp_path: Path):
    """Review finding on #385: `{"workloads": [...]}` under a `workloads[]` heading was merged
    into the ITEM node, nesting a phantom level whose object had no keys — so no workload
    field was ever checked."""
    root = _node('{"metadata": {"a": 1}}')
    text, comments, keys = va.strip_jsonc('{"workloads": [{"workload_id": "wl_1", "structured_output": false, "call_sites": [{"file": "a", "line": 1}]}]}')
    va._merge_example_at(root, "workloads[]", json.loads(text), {}, "t")
    item = root.keys["workloads"].item
    assert set(item.keys) == {"workload_id", "structured_output", "call_sites"}
    # a bare per-item example still lands on the item
    va._merge_example_at(root, "workloads[]", {"model_id": "m"}, {}, "t")
    assert "model_id" in root.keys["workloads"].item.keys
    out = []
    va.validate_shape(root, {"metadata": {"a": 1}, "workloads": [{"workload_id": "x", "model_name": "m", "structured_output": "yes", "call_sites": "a.ts"}]},
                      "", "a", "c", out)
    assert {(f.code, f.path) for f in out} == {("UNKNOWN_KEY", "workloads[0].model_name"),
                                               ("TYPE_MISMATCH", "workloads[0].structured_output"),
                                               ("TYPE_MISMATCH", "workloads[0].call_sites")}
    ok = []
    va.validate_shape(root, {"metadata": {"a": 1}, "workloads": []}, "", "a", "c", ok)
    assert ok == []


def test_heading_match_is_exact_or_word_boundary_prefix():
    """Review finding on #385: `graviton` selected '`graviton_profile` (emitted by …)' by prefix."""
    assert va._heading_matches("`graviton` block (added to each compute service in `aws-design.json`)", "graviton")
    assert not va._heading_matches("`graviton_profile` (emitted by Discover, one entry per compute service)", "graviton")
    assert va._heading_matches("`graviton_profile` (emitted by Discover)", "graviton_profile")
    assert va._heading_matches("Shape", "Shape") and not va._heading_matches("Shapes", "Shape")
    assert va._heading_matches("Cost tiers (`projected_costs` / `cost_comparison`)", "Cost tiers")


def test_required_heading_with_a_table_body_is_enforced(tmp_path: Path):
    """Review finding on #385: requiredness was read only from headings that had a JSON block,
    so '### `apps[]` (REQUIRED)' followed by a table never reached `root.required`."""
    doc = tmp_path / "schema.md"
    doc.write_text("# Contract\n\n## thing.json\n\n```json\n{\"metadata\": {\"x\": 1}, \"apps\": [], \"opt\": {}}\n```\n\n"
                   "### `metadata` (REQUIRED)\n\n| Field | Type |\n|---|---|\n| `x` | number |\n\n"
                   "### `apps[]` (REQUIRED)\n\n| Field | Type |\n|---|---|\n\n"
                   "### `opt` (OPTIONAL — present when available)\n\n| Field | Type |\n|---|---|\n")
    old_root = va.PLUGIN_ROOT
    va.PLUGIN_ROOT = tmp_path
    try:
        findings = []
        c = va.build_shape_contract({"shape": "schema.md", "root_heading": "thing.json"}, findings)
    finally:
        va.PLUGIN_ROOT = old_root
    assert findings == [] and c is not None
    assert c.root.required == {"metadata", "apps"}


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


def test_neutral_matrix_shared_artifacts_extend_the_mapped_fixture_count():
    manifest = va.load_manifest(PLUGIN_ROOT / "scripts" / "artifact-contracts.json")
    fixtures_root = PLUGIN_ROOT / "fixtures"
    matrix = fixtures_root / "ai-migration-matrix"
    shared_artifacts = [p for p in va.find_artifacts(matrix) if p.name in manifest["shared"]]
    assert sum(p.name == ".phase-status.json" for p in shared_artifacts) == 14
    assert sum(p.name == "integration-validation.json" for p in shared_artifacts) == 7
    assert not any(p.name.startswith("expected-") for p in va.find_artifacts(matrix))

    matrix_findings = []
    matrix_checked = va.validate_run_dir(matrix, None, manifest, matrix_findings)
    assert matrix_checked == len(shared_artifacts)
    assert matrix_findings == []

    mapped_checked = 0
    mapped_findings = []
    for fixture_dir in sorted(p for p in fixtures_root.iterdir() if p.is_dir()):
        skill = va.skill_for_fixture(fixture_dir.name, manifest)
        if skill is not None:
            mapped_checked += va.validate_run_dir(fixture_dir, skill, manifest, mapped_findings)

    r = _run("--fixtures", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["checked_artifacts"] - mapped_checked == len(shared_artifacts)


def test_invalid_neutral_shared_artifacts_fail_their_schemas(tmp_path: Path):
    matrix = PLUGIN_ROOT / "fixtures" / "ai-migration-matrix"
    manifest = va.load_manifest(PLUGIN_ROOT / "scripts" / "artifact-contracts.json")
    mutations = {
        ".phase-status.json": lambda value: value.pop("migration_id"),
        "integration-validation.json": lambda value: value.pop("run_id"),
    }
    for name, mutate in mutations.items():
        source = next(matrix.rglob(name))
        value = json.loads(source.read_text())
        mutate(value)
        neutral = tmp_path / name.lstrip(".")
        neutral.mkdir()
        (neutral / name).write_text(json.dumps(value))
        findings = []
        assert va.validate_run_dir(neutral, None, manifest, findings) == 1
        assert any(f.code == "SCHEMA_VIOLATION" for f in findings), findings


def test_neutral_fixture_skips_provider_artifacts_and_expected_snapshots(tmp_path: Path):
    manifest = va.load_manifest(PLUGIN_ROOT / "scripts" / "artifact-contracts.json")
    (tmp_path / "gcp-resource-inventory.json").write_text("{}")
    (tmp_path / "expected-artifacts.json").write_text("not json")
    findings = []
    assert va.validate_run_dir(tmp_path, None, manifest, findings) == 0
    assert findings == []
    assert [p.name for p in va.find_artifacts(tmp_path)] == ["gcp-resource-inventory.json"]


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


# --------------------------------------------------------------------------- review findings (#385 round 2) against the real contracts


def _errors(r: subprocess.CompletedProcess):
    assert r.stdout, r.stderr
    return {(e["code"], e["path"]) for e in json.loads(r.stdout)["errors"]}


def _write_run(tmp_path: Path, name: str, artifact: str, data) -> Path:
    run = tmp_path / name
    (run / Path(artifact).parent).mkdir(parents=True, exist_ok=True)
    (run / artifact).write_text(json.dumps(data))
    return run


def _doc_example(doc: Path, heading: str):
    """The first JSON block under `heading`, with `a|b` alternations resolved to `a`."""
    block = next(b for b in va.extract_blocks(doc) if va._heading_matches(b.heading, heading))
    findings = []
    value, _ = va.parse_block(block, doc, findings)   # also reads `"key": {...}` fragments
    assert findings == []

    def pick(o):
        if isinstance(o, dict):
            return {k: pick(v) for k, v in o.items()}
        if isinstance(o, list):
            return [pick(x) for x in o]
        if isinstance(o, str) and "|" in o and va._enum_from_string(o):
            return o.split("|")[0]
        return o
    return pick(value)


def test_documented_default_run_dir_command_passes_for_a_valid_run(tmp_path: Path):
    """Review finding on #385: `--run-dir <run> --skill gcp-to-aws` applied the shipped
    fixture baseline, so a valid real run failed with 21 STALE_BASELINE errors."""
    status = json.loads((PLUGIN_ROOT / "fixtures/gcp-decision-gate/after-decide-complete/.phase-status.json").read_text())
    run = _write_run(tmp_path, "run", ".phase-status.json", status)
    r = _run("--run-dir", str(run), "--skill", "gcp-to-aws", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["errors"] == [] and report["stale_baseline_entries"] == []
    # the real fixture run passes the same way when validated as a run directory
    r = _run("--run-dir", str(PLUGIN_ROOT / "fixtures/azure-iac-terraform/after-discover"), "--skill", "azure-to-aws", "--json")
    assert r.returncode == 0, r.stdout
    # the shipped baseline still applies to --fixtures (and every entry must match there):
    # test_fixtures_pass_with_baseline_and_no_stale_entries. An explicit --baseline on a run
    # is still audited for stale entries: test_stale_baseline_entry_fails_the_gate.


def test_heroku_complete_example_enums_are_enforced_after_merge(tmp_path: Path):
    """Review finding on #385: merging the Heroku Complete Example cleared the declared enums
    on confidence / heroku_generation / discovery_status / dyno_type."""
    doc = PLUGIN_ROOT / "skills/heroku-to-aws/references/shared/schema-discover-heroku.md"
    good = _doc_example(doc, "Complete Example")
    r = _run("--run-dir", str(_write_run(tmp_path, "ok", "heroku-resource-inventory.json", good)),
             "--skill", "heroku-to-aws", "--no-baseline", "--json")
    assert r.returncode == 0, r.stdout
    formation = next(i for i, x in enumerate(good["resources"]) if x["resource_type"] == "formation")
    mutants = {
        "metadata.confidence": lambda d: d["metadata"].__setitem__("confidence", "bogus"),
        "apps[0].heroku_generation": lambda d: d["apps"][0].__setitem__("heroku_generation", "mars"),
        "apps[0].discovery_status": lambda d: d["apps"][0].__setitem__("discovery_status", "whatever"),
        f"resources[{formation}].config.dyno_type": lambda d: d["resources"][formation]["config"].__setitem__("dyno_type", "giga-9000"),
    }
    for path, mutate in mutants.items():
        bad = json.loads(json.dumps(good))
        mutate(bad)
        r = _run("--run-dir", str(_write_run(tmp_path, path, "heroku-resource-inventory.json", bad)),
                 "--skill", "heroku-to-aws", "--no-baseline", "--json")
        assert r.returncode == 1 and ("ENUM_VIOLATION", path) in _errors(r), (path, r.stdout)


def test_heroku_required_table_sections_are_enforced(tmp_path: Path):
    """Review finding on #385: `metadata`, `apps[]`, `resources[]` are headed `(REQUIRED)` but
    documented as tables, so `{}` passed as heroku-resource-inventory.json."""
    doc = PLUGIN_ROOT / "skills/heroku-to-aws/references/shared/schema-discover-heroku.md"
    good = _doc_example(doc, "Complete Example")
    for key in ("metadata", "apps", "resources"):
        bad = json.loads(json.dumps(good))
        bad.pop(key)
        r = _run("--run-dir", str(_write_run(tmp_path, "no-" + key, "heroku-resource-inventory.json", bad)),
                 "--skill", "heroku-to-aws", "--no-baseline", "--json")
        assert r.returncode == 1 and _errors(r) == {("MISSING_REQUIRED", key)}, (key, r.stdout)
    for key in ("billing_profile", "terraform_metadata"):   # OPTIONAL sections stay optional
        ok = json.loads(json.dumps(good))
        ok.pop(key)
        r = _run("--run-dir", str(_write_run(tmp_path, "opt-" + key, "heroku-resource-inventory.json", ok)),
                 "--skill", "heroku-to-aws", "--no-baseline", "--json")
        assert r.returncode == 0, (key, r.stdout)
    r = _run("--run-dir", str(_write_run(tmp_path, "empty", "heroku-resource-inventory.json", {})),
             "--skill", "heroku-to-aws", "--no-baseline", "--json")
    assert _errors(r) == {("MISSING_REQUIRED", "metadata"), ("MISSING_REQUIRED", "apps"), ("MISSING_REQUIRED", "resources")}


def test_gcp_estimate_extensions_bind_to_their_object_keys(tmp_path: Path):
    """Review finding on #385: scenario_deltas and the observability / security_baseline /
    security_baseline_compliance breakdown members were bound to a `breakdown[]` item (the
    schema types breakdown as an object), so a complete estimate failed with UNKNOWN_KEY."""
    doc = PLUGIN_ROOT / "skills/gcp-to-aws/references/shared/schema-estimate-infra.md"
    est = json.loads((PLUGIN_ROOT / "fixtures/gcp-decision-gate/after-decide-complete/estimation-infra.json").read_text())
    sec_blocks = [b for b in va.extract_blocks(doc) if va._heading_matches(b.heading, "Security Baseline Entries in")]
    assert len(sec_blocks) == 2, "manifest anchors @L373/@L390 expect two Security Baseline blocks"
    est["projected_costs"]["scenario_deltas"] = _doc_example(doc, "Cost tiers")["scenario_deltas"]
    est["projected_costs"]["breakdown"] = {
        "compute": {"service": "Fargate", "monthly": 71},
        "observability": _doc_example(doc, "Observability Entry in"),
        "security_baseline": json.loads(va.strip_jsonc(sec_blocks[0].text)[0]),
        "security_baseline_compliance": json.loads(va.strip_jsonc(sec_blocks[1].text)[0]),
    }
    r = _run("--run-dir", str(_write_run(tmp_path, "ok", "estimation-infra.json", est)), "--skill", "gcp-to-aws", "--json")
    assert r.returncode == 0, r.stdout
    bad = json.loads(json.dumps(est))
    bad["projected_costs"]["breakdown"]["observability"]["components"]["bogus"] = 1
    bad["projected_costs"]["breakdown"]["security_baseline"]["invented"] = 1
    bad["projected_costs"]["scenario_deltas"]["weird"] = []
    bad["projected_costs"]["unrelated"] = 1
    r = _run("--run-dir", str(_write_run(tmp_path, "bad", "estimation-infra.json", bad)), "--skill", "gcp-to-aws", "--json")
    assert r.returncode == 1
    assert _errors(r) == {("UNKNOWN_KEY", "projected_costs.breakdown.observability.components.bogus"),
                          ("UNKNOWN_KEY", "projected_costs.breakdown.security_baseline.invented"),
                          ("UNKNOWN_KEY", "projected_costs.scenario_deltas.weird"),
                          ("UNKNOWN_KEY", "projected_costs.unrelated")}


def test_azure_design_graviton_block_is_the_design_section_not_the_discovery_profile(tmp_path: Path):
    """Review finding on #385: the `graviton` heading matched `graviton_profile` by prefix, so
    services[].graviton rejected the documented `compatibility` field."""
    src = PLUGIN_ROOT / "fixtures/azure-iac-terraform/after-design"
    control = _errors(_run("--run-dir", str(src), "--skill", "azure-to-aws", "--no-baseline", "--json"))
    design = json.loads((src / "aws-design.json").read_text())
    design["services"][0]["graviton"] = {"compatibility": "ready", "target_architecture": "arm64", "caveats": []}
    r = _run("--run-dir", str(_write_run(tmp_path, "grav", "aws-design.json", design)), "--skill", "azure-to-aws", "--no-baseline", "--json")
    assert _errors(r) - control == set(), r.stdout
    design["services"][0]["graviton"] = {"compatibility": "ready", "tier": "ready", "service_name": "x"}   # discovery-profile fields
    r = _run("--run-dir", str(_write_run(tmp_path, "mixed", "aws-design.json", design)), "--skill", "azure-to-aws", "--no-baseline", "--json")
    assert _errors(r) - control == {("UNKNOWN_KEY", "services[0].graviton.tier"), ("UNKNOWN_KEY", "services[0].graviton.service_name")}
    # the discovery profile is still selected for the inventory
    inv = json.loads((PLUGIN_ROOT / "fixtures/azure-iac-terraform/after-discover/azure-resource-inventory.json").read_text())
    inv["graviton_profile"] = [{"service_name": "api", "tier": "ready", "target_architecture": "arm64", "signals": [], "caveats": [], "source": "app_code"}]
    r = _run("--run-dir", str(_write_run(tmp_path, "inv", "azure-resource-inventory.json", inv)), "--skill", "azure-to-aws", "--no-baseline", "--json")
    assert not any(p.startswith("graviton_profile") for _, p in _errors(r)), r.stdout


def test_gcp_ai_workloads_fields_are_checked(tmp_path: Path):
    """Review finding on #385: the wrapped `{"workloads": [...]}` example merged one level too
    deep, so key and type drift inside a workload never fired."""
    doc = PLUGIN_ROOT / "skills/gcp-to-aws/references/shared/schema-discover-ai.md"
    profile = _doc_example(doc, "ai-workload-profile.json")
    profile["workloads"] = _doc_example(doc, "workloads[]")["workloads"]
    r = _run("--run-dir", str(_write_run(tmp_path, "ok", "ai-workload-profile.json", profile)), "--skill", "gcp-to-aws", "--json")
    assert r.returncode == 0, r.stdout
    empty = dict(profile, workloads=[])
    r = _run("--run-dir", str(_write_run(tmp_path, "empty", "ai-workload-profile.json", empty)), "--skill", "gcp-to-aws", "--json")
    assert r.returncode == 0, r.stdout
    bad = json.loads(json.dumps(profile))
    w = bad["workloads"][0]
    w["model_name"] = w.pop("model_id")
    w["structured_output"] = "yes"
    w["call_sites"] = "lib/gemini.ts"
    r = _run("--run-dir", str(_write_run(tmp_path, "bad", "ai-workload-profile.json", bad)), "--skill", "gcp-to-aws", "--json")
    assert r.returncode == 1
    assert _errors(r) == {("UNKNOWN_KEY", "workloads[0].model_name"),
                          ("TYPE_MISMATCH", "workloads[0].structured_output"),
                          ("TYPE_MISMATCH", "workloads[0].call_sites")}


def test_heroku_workshop_preferences_subset_is_an_open_knob_map(tmp_path: Path):
    """Review finding on #385: `preferences_subset` was closed to the two knobs in the example,
    so a cost-optimization or availability delta failed with UNKNOWN_KEY."""
    sc = json.loads((PLUGIN_ROOT / "fixtures/heroku-workshop/after-arm64-reprice/scenarios/scenario-002.json").read_text())
    sc["preferences_subset"].update({"operational.cost_optimization": "aggressive", "availability.multi_az": True,
                                     "database.ha": "multi_az", "compute.target": "fargate"})
    r = _run("--run-dir", str(_write_run(tmp_path, "ok", "scenarios/scenario-002.json", sc)), "--skill", "heroku-to-aws", "--json")
    assert r.returncode == 0, r.stdout
    sc["invented_root_key"] = 1   # the manifest itself is still closed
    r = _run("--run-dir", str(_write_run(tmp_path, "bad", "scenarios/scenario-002.json", sc)), "--skill", "heroku-to-aws", "--json")
    assert _errors(r) == {("UNKNOWN_KEY", "invented_root_key")}


def test_azure_inventory_source_accepts_the_documented_joined_set(tmp_path: Path):
    """Review finding on #386/#387: `source` is documented as `terraform | bicep | arm | live |
    rdfa | billing (or a "+"-joined set)` and discover-live.md emits `live+terraform`."""
    inv = json.loads((PLUGIN_ROOT / "fixtures/azure-iac-terraform/after-discover/azure-resource-inventory.json").read_text())
    for val, expect in (("live+terraform", set()), ("terraform+live", set()), ("terraform", set()),
                        ("terraform+bogus", {("ENUM_VIOLATION", "resources[0].source")}),
                        ("bogus", {("ENUM_VIOLATION", "resources[0].source")})):
        inv["resources"][0]["source"] = val
        r = _run("--run-dir", str(_write_run(tmp_path, val, "azure-resource-inventory.json", inv)), "--skill", "azure-to-aws", "--json")
        assert _errors(r) == expect, (val, r.stdout)
    inv["resources"][0]["source"] = "terraform"
    inv["resources"][0]["azure_type_provenance"] = "terraform+live"   # a genuinely closed enum stays closed
    r = _run("--run-dir", str(_write_run(tmp_path, "prov", "azure-resource-inventory.json", inv)), "--skill", "azure-to-aws", "--json")
    assert _errors(r) == {("ENUM_VIOLATION", "resources[0].azure_type_provenance")}, r.stdout


def test_gcp_preferences_chosen_by_enum_is_enforced_including_derived(tmp_path: Path):
    """Review finding on #385/#387: the Graviton refinement cleared `chosen_by` for every row;
    restoring the enum must keep the AI-only route's `derived` (schema-preferences.md § Wrapper)."""
    pref = json.loads((PLUGIN_ROOT / "fixtures/gcp-workshop/after-graviton-reprice/preferences.json").read_text())
    for val, expect in (("derived", set()), ("default", set()),
                        ("invalid-origin", {("ENUM_VIOLATION", "design_constraints.target_region.chosen_by")})):
        pref["design_constraints"]["target_region"]["chosen_by"] = val
        r = _run("--run-dir", str(_write_run(tmp_path, val, "preferences.json", pref)), "--skill", "gcp-to-aws", "--json")
        assert _errors(r) == expect, (val, r.stdout)
    pref["design_constraints"]["target_region"]["chosen_by"] = "user"
    pref["design_constraints"]["cpu_architecture"] = {"value": "graviton", "chosen_by": "bogus"}
    r = _run("--run-dir", str(_write_run(tmp_path, "cpu", "preferences.json", pref)), "--skill", "gcp-to-aws", "--json")
    assert _errors(r) == {("ENUM_VIOLATION", "design_constraints.cpu_architecture.chosen_by")}, r.stdout


def test_azure_design_arrays_reject_a_scalar_after_the_empty_seed(tmp_path: Path):
    """Review finding on #387: services, clusters, deferred, and pending_rubric are seeded
    `[]` and refined by a later object section. A scalar, string, boolean, or nested list
    must fail. An empty array and an object stay valid as types. An array whose example
    never names an item type stays open."""
    src = PLUGIN_ROOT / "fixtures/azure-iac-terraform/after-design/aws-design.json"
    design = json.loads(src.read_text())
    control = _errors(_run("--run-dir", str(src.parent), "--skill", "azure-to-aws", "--no-baseline", "--json"))

    def run(name, data):
        return _errors(_run("--run-dir", str(_write_run(tmp_path, name, "aws-design.json", data)),
                            "--skill", "azure-to-aws", "--no-baseline", "--json"))

    for key in ("services", "clusters", "deferred", "pending_rubric"):
        for label, member in (("str", "not-an-object"), ("num", 17), ("bool", False), ("list", [])):
            bad = json.loads(json.dumps(design))
            bad[key] = [member]
            assert ("TYPE_MISMATCH", f"{key}[0]") in run(f"{key}-{label}", bad) - control
        empty = json.loads(json.dumps(design))
        empty[key] = []
        assert ("TYPE_MISMATCH", f"{key}[0]") not in run(key + "-empty", empty)
        blank = json.loads(json.dumps(design))
        blank[key] = [{}]
        assert ("TYPE_MISMATCH", f"{key}[0]") not in run(key + "-obj", blank)
    blank = json.loads(json.dumps(design))
    blank["services"] = [{}]
    assert ("MISSING_REQUIRED", "services[0].routing_provenance") in run("svc-obj", blank)


def test_azure_preferences_follow_the_producer_route(tmp_path: Path):
    """Review finding on #387: the infra shape was the only preferences contract, so an
    AI-only file failed clarify_status and the mixed flow's AI rows were unknown keys."""
    infra = json.loads((PLUGIN_ROOT / "fixtures/azure-iac-terraform/after-clarify/preferences.json").read_text())
    rows = _doc_example(PLUGIN_ROOT / "skills/azure-to-aws/references/phases/clarify/clarify-ai.md",
                        "Step 3: Rows returned")
    mixed = json.loads(json.dumps(infra))
    mixed.update(rows)

    def run(name, data):
        return _errors(_run("--run-dir", str(_write_run(tmp_path, name, "preferences.json", data)),
                            "--skill", "azure-to-aws", "--no-baseline", "--json"))

    assert ("MISSING_REQUIRED", "clarify_status") not in run("infra", infra)
    assert run("mixed", mixed) - run("infra", infra) == set()
    bad = json.loads(json.dumps(mixed))
    bad["not_a_preference"] = 1
    assert ("UNKNOWN_KEY", "not_a_preference") in run("mixed-bad", bad)
    bad = json.loads(json.dumps(mixed))
    bad["workloads"] = [42]
    assert ("TYPE_MISMATCH", "workloads[0]") in run("mixed-scalar", bad)

    ai = _doc_example(PLUGIN_ROOT / "skills/azure-to-aws/references/phases/clarify/clarify-ai-only.md",
                      "preferences.json (AI-only)")
    assert run("ai", ai) == set(), run("ai", ai)
    omitted = json.loads(json.dumps(ai))
    del omitted["workloads"]
    assert ("MISSING_REQUIRED", "workloads") in run("ai-omit", omitted)
    dropped = json.loads(json.dumps(ai))
    del dropped["ai_constraints"]["ai_framework"]
    assert ("MISSING_REQUIRED", "ai_constraints.ai_framework") in run("ai-framework", dropped)
    invented = json.loads(json.dumps(ai))
    invented["metadata"]["invented"] = 1
    assert ("UNKNOWN_KEY", "metadata.invented") in run("ai-invented", invented)
    # the infra verdict stays required on the infra route
    no_status = json.loads(json.dumps(infra))
    no_status.pop("clarify_status", None)
    assert ("MISSING_REQUIRED", "clarify_status") in run("infra-status", no_status)


def test_gcp_drift_values_keep_their_json_types(tmp_path: Path):
    """Review finding on #387: the live-discovery example typed drift values as strings,
    so a numeric or boolean config change failed."""
    inv = json.loads((PLUGIN_ROOT / "fixtures/gcp-workshop/seed/gcp-resource-inventory.json").read_text())
    inv["live_metadata"] = {
        "found": True,
        "drift": {"config_conflicts": [{
            "address": "google_compute_disk.d",
            "field": "size_gb",
            "terraform_value": 10,
            "live_value": 20,
        }]},
    }

    def run(name, data):
        return _errors(_run("--run-dir", str(_write_run(tmp_path, name, "gcp-resource-inventory.json", data)),
                            "--skill", "gcp-to-aws", "--json"))

    assert ("TYPE_MISMATCH", "live_metadata.drift.config_conflicts[0].terraform_value") not in run("num", inv)
    inv["live_metadata"]["drift"]["config_conflicts"][0]["terraform_value"] = False
    inv["live_metadata"]["drift"]["config_conflicts"][0]["live_value"] = True
    assert ("TYPE_MISMATCH", "live_metadata.drift.config_conflicts[0].live_value") not in run("bool", inv)
    inv["live_metadata"]["drift"]["config_conflicts"][0]["terraform_value"] = "db-f1-micro"
    assert ("TYPE_MISMATCH", "live_metadata.drift.config_conflicts[0].terraform_value") not in run("str", inv)
    inv["live_metadata"]["drift"]["config_conflicts"][0]["address"] = 10
    assert ("TYPE_MISMATCH", "live_metadata.drift.config_conflicts[0].address") in run("address", inv)


def test_azure_workshop_index_records_capture_state(tmp_path: Path):
    """Review finding on #387: the index example omitted the fields workshop-refresh writes."""
    doc = PLUGIN_ROOT / "skills/azure-to-aws/references/shared/schema-workshop-scenarios.md"
    index = _doc_example(doc, "scenarios/index.json")

    def run(name, data):
        return _errors(_run("--run-dir", str(_write_run(tmp_path, name, "scenarios/index.json", data)),
                            "--skill", "azure-to-aws", "--no-baseline", "--json"))

    assert run("baseline", index) == set(), index
    active = json.loads(json.dumps(index))
    active["active_scenario_id"] = "scenario-002"
    assert run("active", active) == set()
    bad = json.loads(json.dumps(index))
    bad["invented"] = 1
    assert ("UNKNOWN_KEY", "invented") in run("bad", bad)
