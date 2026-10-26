from __future__ import annotations

import copy
import hashlib
import json
import types
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "skills/bedrock-migration-assessment/scripts/bma-runtime.py"
runtime = types.ModuleType("bma_runtime")
exec(compile(PATH.read_text(encoding="utf-8"), str(PATH), "exec"), runtime.__dict__)
SCHEMA = ROOT / "skills/bedrock-migration-assessment/references/runtime/content-contribution.schema.json"


README_DOCUMENT = "<!-- bma-contributions:ai-notes -->\n"


def contribution(target: str = "README.md", kind: str = "subsection") -> dict:
    return {
        "id": "ai.valid", "bucket": 100, "source_order": 1,
        "target": target, "kind": kind, "section": "ai-notes",
        "content": {
            "text": "Valid traced contribution.",
            "links": [],
            "traceability": {
                "provider": "openai", "source_service": "openai_api", "model": "gpt-4o",
                "call_sites": [{"file": "src/app.py", "line": 7}],
            },
        },
    }


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def test_direct_and_delegated_route_ownership() -> None:
    direct = runtime.route("direct", True, True)
    delegated = runtime.route("delegated", True, True)
    below = runtime.route("delegated", False, True)
    assert direct == {"mode": "direct", "scan_neutral_source": True, "ai_route_active": True, "owning_skill": "BEDROCK_MIGRATION_ASSESSMENT", "telemetry_owner": None}
    assert delegated["owning_skill"] == "GCP_TO_AWS" and delegated["telemetry_owner"] == "gcp-to-aws"
    assert below["scan_neutral_source"] and not below["ai_route_active"]


def test_region_precedence_and_ambiguity() -> None:
    assert runtime.resolve_region(["fedramp"], ["us-west-2"], "latency-acceptable")["region"] == "us-gov-west-1"
    assert runtime.resolve_region(["none"], ["us-west-2"], "latency-acceptable")["region"] == "us-west-2"
    assert runtime.resolve_region(["none"], ["eu-west-1", "us-west-2"], "latency-acceptable")["source"] == "clarify_required"
    assert runtime.resolve_region(["none"], [], "latency-acceptable")["region"] == "us-east-1"
    assert runtime.resolve_region(["none"], [], "latency-acceptable", "us-west-2")["region"] == "us-west-2"


def test_state_and_writer_selection() -> None:
    state = {"phases": {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed", "generate": "pending"}}
    assert runtime.next_phase(state) == "complete"
    assert runtime.next_phase(state, execute_requested=True) == "generate"
    assert runtime.writer("direct", "preferences.json") == "bedrock-migration-assessment"
    assert runtime.writer("delegated", "preferences.json") == "gcp-to-aws"
    assert runtime.writer("delegated", "ai-workload-profile.json") == "gcp-to-aws"
    assert runtime.writer("delegated", "openai-capture/manifest.json") == "bedrock-migration-assessment"
    assert runtime.writer("delegated", "estimation-ai.json") == "bedrock-migration-assessment"
    with pytest.raises(ValueError, match="writer_not_registered"):
        runtime.writer("delegated", "unexpected.json")


def test_clarify_result_and_contribution_validation() -> None:
    result = {"schema_version": 1, "kind": "BMA_AI_CLARIFY_RESULT", "constraints": {}, "workloads": [{"workload_id": "wl_1", "call_sites": [{"file": "app.py", "line": 1}]}], "question_metadata": {}}
    assert runtime.validate_clarify_result(result) is result
    first = contribution()
    second = contribution()
    first.update({"id": "ai.b", "bucket": 200, "source_order": 2})
    first["content"]["text"] = "b"
    second.update({"id": "ai.a", "bucket": 100, "source_order": 1})
    second["content"]["text"] = "a"
    values = [first, second]
    assert [value["id"] for value in runtime.order_contributions(values)] == ["ai.a", "ai.b"]
    with pytest.raises(ValueError):
        runtime.order_contributions(values + [dict(values[0])])


def test_content_contribution_schema_declares_closed_runtime_contract() -> None:
    schema = json.loads(SCHEMA.read_text())
    assert schema["additionalProperties"] is False
    assert schema["properties"]["target"]["enum"] == [
        "DECISION.md", "decision-report.html", "MIGRATION_GUIDE.md", "README.md",
        "migration-report.html",
    ]
    content = schema["properties"]["content"]
    assert content["additionalProperties"] is False
    assert content["required"] == ["text", "links", "traceability"]
    assert "section" in schema["required"]
    assert schema["properties"]["section"]["pattern"] == "^[a-z][a-z0-9-]*$"
    traceability = content["properties"]["traceability"]
    assert traceability["additionalProperties"] is False
    assert traceability["required"] == ["provider", "source_service", "model", "call_sites"]
    assert traceability["properties"]["call_sites"]["minItems"] == 1


PROHIBITED_CONTRIBUTIONS = {
    "script": lambda value: value["content"].update(text="<script>alert(1)</script>"),
    "style": lambda value: value["content"].update(text="<style>body{display:none}</style>"),
    "raw-html-wrapper": lambda value: value["content"].update(text="<section>wrapped</section>"),
    "markdown-heading": lambda value: value["content"].update(text="# Injected heading"),
    "markdown-setext-heading-hyphen": lambda value: value["content"].update(
        text="Injected heading\n---"
    ),
    "markdown-setext-heading-equals": lambda value: value["content"].update(
        text="Injected heading\n==="
    ),
    "html-anchor": lambda value: value["content"].update(text='<a href="https://example.com">injected</a>'),
    "markdown-link": lambda value: value["content"].update(text="[injected](javascript:alert(1))"),
    "disallowed-structured-link": lambda value: value["content"].update(
        links=[{"label": "Injected", "href": "https://example.com?query=1"}]
    ),
}
for field in ("provider", "source_service", "model", "call_sites"):
    PROHIBITED_CONTRIBUTIONS[f"missing-traceability-{field}"] = (
        lambda value, field=field: value["content"]["traceability"].pop(field)
    )


@pytest.mark.parametrize("case", sorted(PROHIBITED_CONTRIBUTIONS))
def test_content_contribution_schema_rejects_prohibited_content(case: str) -> None:
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    value = contribution()
    PROHIBITED_CONTRIBUTIONS[case](value)
    assert not validator.is_valid(value)


@pytest.mark.parametrize("href", [None, "https://docs.aws.amazon.com/bedrock/", "#migration-plan"])
def test_content_contribution_schema_accepts_allowed_forms(href: str | None) -> None:
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    value = contribution()
    value["content"]["text"] = "Paragraph text.\n\n- Ordered body item\n\n| Model | Target |"
    if href is not None:
        value["content"]["links"] = [{"label": "Bedrock details", "href": href}]
    Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize("mode", ["direct", "delegated"])
@pytest.mark.parametrize("case", sorted(PROHIBITED_CONTRIBUTIONS))
def test_contribution_rejection_precedes_staging_and_mutation(
    tmp_path: Path, mode: str, case: str,
) -> None:
    run = tmp_path / f"{mode}-{case}"
    run.mkdir()
    sentinel = run / ".phase-status.json"
    sentinel.write_text('{"stable":true}\n')
    before = tree_bytes(run)
    value = contribution()
    PROHIBITED_CONTRIBUTIONS[case](value)
    request = {
        "schema_version": 1, "mode": mode, "scenario": case, "run_dir": str(run),
        "state": {}, "consent": [], "writes": [],
        "assemblies": [{"phase": "generate", "target": "README.md", "contributions": [value], "document": README_DOCUMENT}],
    }
    with pytest.raises(ValueError, match="contribution_(?:content|link|traceability)_invalid"):
        runtime.execute_contract(request)
    assert tree_bytes(run) == before
    assert not list(run.glob(".bma-stage-*"))


@pytest.mark.parametrize("mode", ["direct", "delegated"])
@pytest.mark.parametrize("href", [None, "https://docs.aws.amazon.com/bedrock/", "#migration-plan"])
def test_allowed_content_links_and_traceability_assemble_in_both_modes(
    tmp_path: Path, mode: str, href: str | None,
) -> None:
    link_kind = "plain" if href is None else "https" if href.startswith("https:") else "fragment"
    run = tmp_path / f"{mode}-{link_kind}"
    run.mkdir()
    value = contribution()
    value["content"]["text"] = "Paragraph text.\n\n- Ordered body item\n\n| Model | Target |"
    if href is not None:
        value["content"]["links"] = [{"label": "Bedrock details", "href": href}]
    request = {
        "schema_version": 1, "mode": mode, "scenario": "positive", "run_dir": str(run),
        "state": {}, "consent": [], "writes": [],
        "assemblies": [{"phase": "generate", "target": "README.md", "contributions": [value], "document": README_DOCUMENT}],
    }
    result = runtime.execute_contract(request)
    rendered = (run / "README.md").read_text()
    assert "Paragraph text." in rendered
    if href is not None:
        assert f"[Bedrock details]({href})" in rendered
    assert result["operations"][0]["logical_owner"] == (
        "bedrock-migration-assessment" if mode == "direct" else "gcp-to-aws"
    )


def test_consent_decisions_preserve_request_retry_and_null_zero() -> None:
    assert runtime.consent_decision("declined") == {
        "status": "declined", "requests": 0, "profile_written": False,
        "retry_pending": False, "next": "continue", "cost": None,
    }
    assert runtime.consent_decision("all_failed", 3, True)["next"] == "retry"
    assert runtime.consent_decision("all_failed", 3)["cost"] is None
    assert runtime.consent_decision("succeeded", 1, False, 0)["cost"] == 0
    with pytest.raises(ValueError, match="consent_decline_invalid"):
        runtime.consent_decision("declined", 1)


def test_execute_contract_is_production_phase_boundary(tmp_path: Path) -> None:
    run = tmp_path / "execute"
    run.mkdir()
    request = {
        "schema_version": 1, "mode": "direct", "scenario": "direct",
        "run_dir": str(run), "state": {}, "execute_requested": False,
        "consent": [{"status": "declined", "requests": 0, "retry_pending": False, "cost": None}],
        "writes": [{"phase": "design", "path": "aws-design-ai.json", "payload": {"unknown": None, "zero": 0}, "logical_owner": "bedrock-migration-assessment"}],
        "assemblies": [],
    }
    result = runtime.execute_contract(request)
    assert result["state_decision"]["action"] == "reconstruct"
    assert result["consent"][0]["requests"] == 0
    assert result["operations"][0]["logical_owner"] == "bedrock-migration-assessment"
    assert (run / "aws-design-ai.json").is_file()
    with pytest.raises(ValueError, match="duplicate_final_write"):
        runtime.execute_contract(request)


def test_execute_prevalidates_late_failure_without_mutation(tmp_path: Path) -> None:
    run = tmp_path / "atomic"
    run.mkdir()
    state = run / ".phase-status.json"
    state.write_text('{"stable":true}\n')
    before = {path.relative_to(run).as_posix(): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    request = {
        "schema_version": 1, "mode": "direct", "scenario": "late-failure",
        "run_dir": str(run), "state": {}, "consent": [],
        "writes": [
            {"phase": "design", "path": "aws-design-ai.json", "payload": {}, "logical_owner": "bedrock-migration-assessment"},
            {"phase": "estimate", "path": "estimation-ai.json", "payload": {}, "logical_owner": "gcp-to-aws"},
        ],
        "assemblies": [],
    }
    with pytest.raises(ValueError, match="writer_owner_invalid"):
        runtime.execute_contract(request)
    after = {path.relative_to(run).as_posix(): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    assert after == before


def test_publish_failure_rolls_back_new_and_replaced_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = tmp_path / "rollback"
    run.mkdir()
    profile = run / "ai-workload-profile.json"
    profile.write_text('{"seed":"vertex"}\n')
    prior = hashlib.sha256(profile.read_bytes()).hexdigest()
    before = {path.relative_to(run).as_posix(): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    real_replace = runtime.os.replace
    calls = 0

    def fail_third_replace(source: object, target: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic publish failure")
        real_replace(source, target)

    monkeypatch.setattr(runtime.os, "replace", fail_third_replace)
    request = {
        "schema_version": 1, "mode": "direct", "scenario": "publish-rollback",
        "run_dir": str(run), "state": {}, "consent": [],
        "writes": [
            {"phase": "design", "path": "aws-design-ai.json", "payload": {}, "logical_owner": "bedrock-migration-assessment"},
            {"phase": "discover", "path": "ai-workload-profile.json", "payload": {"enriched": True}, "logical_owner": "bedrock-migration-assessment", "expected_sha256": prior},
        ],
        "assemblies": [],
    }
    with pytest.raises(OSError, match="synthetic publish failure"):
        runtime.execute_contract(request)
    after = {path.relative_to(run).as_posix(): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    assert after == before


def test_discovery_enrichment_requires_owner_and_prior_hash(tmp_path: Path) -> None:
    run = tmp_path / "enrichment"
    run.mkdir()
    profile = run / "ai-workload-profile.json"
    profile.write_text('{"metadata":{"profile_source":"iac_vertex"}}\n')
    prior = hashlib.sha256(profile.read_bytes()).hexdigest()
    base = {
        "schema_version": 1, "mode": "direct", "scenario": "vertex-enrichment",
        "run_dir": str(run), "state": {}, "consent": [], "assemblies": [],
    }
    with pytest.raises(ValueError, match="writer_owner_invalid"):
        runtime.execute_contract({**base, "writes": [{"phase": "discover", "path": "ai-workload-profile.json", "payload": {}, "logical_owner": "arbitrary-owner", "expected_sha256": prior}]})
    with pytest.raises(ValueError, match="expected_prior_hash_required"):
        runtime.execute_contract({**base, "writes": [{"phase": "discover", "path": "ai-workload-profile.json", "payload": {}, "logical_owner": "bedrock-migration-assessment"}]})
    result = runtime.execute_contract({**base, "writes": [{"phase": "discover", "path": "ai-workload-profile.json", "payload": {"metadata": {"profile_source": "iac_vertex", "enriched_by": "bma"}}, "logical_owner": "bedrock-migration-assessment", "expected_sha256": prior}]})
    assert result["operations"][0]["logical_owner"] == "bedrock-migration-assessment"
    assert "enriched_by" in profile.read_text()


@pytest.mark.parametrize(("mode", "route", "preferences_owner"), [
    ("direct", None, "bedrock-migration-assessment"),
    ("delegated", "ai_only", "bedrock-migration-assessment"),
    ("delegated", "combined", "gcp-to-aws"),
])
def test_delegated_route_selects_preferences_owner(tmp_path: Path, mode: str, route: str | None, preferences_owner: str) -> None:
    run = tmp_path / f"routes-{mode}-{route}"
    run.mkdir()
    state_owner = "gcp-to-aws" if mode == "delegated" else "bedrock-migration-assessment"
    base = {"schema_version": 1, "mode": mode, "scenario": "route", "run_dir": str(run), "state": {}, "consent": [], "assemblies": []}
    if route is not None:
        base["delegated_route"] = route
    prefs = {"metadata": {"migration_type": "ai-only"}}
    writes = [
        {"phase": "clarify", "path": "preferences-draft.json", "payload": prefs, "logical_owner": preferences_owner},
        {"phase": "clarify", "path": "preferences.json", "payload": prefs, "logical_owner": preferences_owner},
        {"phase": "clarify", "path": ".phase-status.json", "payload": {"phases": {}}, "logical_owner": state_owner},
        {"phase": "design", "path": "aws-design-ai.json", "payload": {}, "logical_owner": "bedrock-migration-assessment"},
    ]
    if mode == "delegated" and route is None:
        with pytest.raises(ValueError, match="delegated_route_required"):
            runtime.execute_contract({**base, "writes": writes})
        with pytest.raises(ValueError, match="delegated_route_invalid"):
            runtime.execute_contract({**base, "delegated_route": "unknown", "writes": writes})
        return
    with pytest.raises(ValueError, match="writer_owner_invalid"):
        runtime.execute_contract({**base, "writes": [{**writes[1], "logical_owner": "wrong-owner"}]})
    result = runtime.execute_contract({**base, "writes": writes})
    owners = {operation["path"]: operation["logical_owner"] for operation in result["operations"]}
    assert owners == {
        "preferences-draft.json": preferences_owner, "preferences.json": preferences_owner,
        ".phase-status.json": state_owner, "aws-design-ai.json": "bedrock-migration-assessment",
    }
    assert runtime.writer(mode, "preferences.json", route) == preferences_owner


def test_nested_write_rejects_symlink_parent_without_external_mutation(tmp_path: Path) -> None:
    run = tmp_path / "run"
    external = tmp_path / "external"
    run.mkdir(); external.mkdir()
    (run / "ai-migration").symlink_to(external, target_is_directory=True)
    before = list(external.iterdir())
    request = {
        "schema_version": 1, "mode": "direct", "scenario": "symlink-parent",
        "run_dir": str(run), "state": {}, "consent": [],
        "writes": [{"phase": "generate", "path": "ai-migration/provider-plan.txt", "payload": "blocked", "logical_owner": "bedrock-migration-assessment"}],
        "assemblies": [],
    }
    with pytest.raises(ValueError, match="write_path_invalid"):
        runtime.execute_contract(request)
    assert list(external.iterdir()) == before
    assert (run / "ai-migration").is_symlink()


def test_semantic_trace_rejects_unknown_source_model() -> None:
    request = {
        "schema_version": 2, "mode": "direct", "source_containing": True,
        "has_ai_profile": True, "iac_route_signal": False,
        "source_evidence": [{
            "provider": "openai", "source_service": "openai_api", "gateway": None,
            "models": ["different-model"], "call_sites": [{"file": "app.py", "line": 1}],
            "observed_monthly_cost": None, "monthly_input_tokens": 0,
            "monthly_output_tokens": 0,
        }],
        "state": {},
        "user_decisions": {"execute_requested": False, "generate": False,
                           "include_rollback": False, "report_scope": "none"},
        "capture_observations": [],
    }
    with pytest.raises(ValueError, match="trace_source_invalid"):
        runtime.semantic_trace(request)


def test_runtime_calls_production_closure_preflight() -> None:
    result = runtime.closure_preflight(ROOT / "skills/bedrock-migration-assessment")
    assert result["closure_entries"] == 66 and result["mutation_count"] == 0


def test_complete_state_resume_decisions() -> None:
    assert runtime.state_decision({}) == {"action": "reconstruct", "phase": "discover", "write_state": False}
    phases = {name: "completed" for name in runtime.PHASES}
    assert runtime.state_decision({"phases": phases})["action"] == "complete"
    pending = {**phases, "generate": "pending"}
    assert runtime.state_decision({"phases": pending, "run_mode": "decide"})["action"] == "offer_generate"
    assert runtime.state_decision({"phases": pending, "run_mode": "decide_and_execute"})["phase"] == "generate"
    assert runtime.state_decision({"phases": pending, "dirty_state": {"phase": "generate", "stage": "stage_1_planning"}})["action"] == "resume_dirty"
    assert runtime.state_decision({"phases": pending, "stale_downstream": True, "current_phase": "design"})["action"] == "confirm_reentry"
    workshop = {**pending, "workshop": "in_progress"}
    assert runtime.state_decision({"phases": workshop})["action"] == "resume_workshop"


def test_physical_write_audit_and_assembler_reject_duplicates(tmp_path: Path) -> None:
    direct = tmp_path / "direct"; direct.mkdir()
    audit = runtime.WriteAudit(direct, "direct", "direct-openai")
    first = contribution()
    second = contribution()
    first.update({"id": "ai.2", "bucket": 20, "source_order": 2})
    first["content"]["text"] = "second"
    second.update({"id": "ai.1", "bucket": 10, "source_order": 1})
    second["content"]["text"] = "first"
    values = [first, second]
    runtime.assemble_contributions(audit, "generate", "README.md", values, README_DOCUMENT)
    assert (direct / "README.md").read_text() == "first\nsecond\n"
    assert audit.operations == [{"scenario": "direct-openai", "phase": "generate", "logical_owner": "bedrock-migration-assessment", "path": "README.md", "operation": "write", "sha256": audit.operations[0]["sha256"]}]
    with pytest.raises(ValueError, match="duplicate_final_write"):
        runtime.assemble_contributions(audit, "generate", "README.md", values, README_DOCUMENT)

    delegated = tmp_path / "delegated"; delegated.mkdir()
    outer = runtime.WriteAudit(delegated, "delegated", "gcp-combined")
    runtime.assemble_contributions(outer, "generate", "README.md", values, README_DOCUMENT)
    assert outer.operations[0]["logical_owner"] == "gcp-to-aws"
    with pytest.raises(ValueError, match="writer_owner_invalid"):
        outer.write("generate", "estimation-ai.json", {}, "gcp-to-aws")
