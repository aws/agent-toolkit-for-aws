from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins/aws-startup-advisor"
SKILL_ROOT = PLUGIN_ROOT / "skills/render-to-aws"
SHARED_ROOT = PLUGIN_ROOT / "skills/shared"
PHASE_ROOT = SKILL_ROOT / "references/phases"

BACKBONE = ["discover", "clarify", "design", "estimate", "generate"]
SIDEBARS = ["workshop", "feedback"]
ALLOWED_PHASE_KEYS = {
    "_phase", "_title", "_kind", "_requires_phase", "_init", "_interactive",
    "_input", "_knowledge", "_trigger", "_fragments", "_assemble", "_produces",
    "_advances_to", "_gates", "_exec", "_re_entry_guard", "_preconditions",
    "_postconditions", "_forbids_files",
}


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    end = text.index("\n---\n", 4)
    parsed = yaml.safe_load(text[4:end])
    assert isinstance(parsed, dict), path
    return parsed


def phase_file(name: str) -> Path:
    return PHASE_ROOT / name / f"{name}.md"


def phase(name: str) -> dict:
    return frontmatter(phase_file(name))


def referenced_file(entry: object) -> str:
    return entry if isinstance(entry, str) else entry["file"]


def test_complete_interpreter_graph_and_strict_frontmatter() -> None:
    phases = {name: phase(name) for name in BACKBONE + SIDEBARS}
    assert set(phases) == set(BACKBONE + SIDEBARS)
    for name, data in phases.items():
        assert data["_phase"] == name
        assert not (set(data) - ALLOWED_PHASE_KEYS)
        assert data["_fragments"]
        assert data["_assemble"]
        assert data["_preconditions"]
        assert data["_postconditions"]

    assert phases["discover"]["_init"] is True
    assert "_requires_phase" not in phases["discover"]
    for previous, current in zip(BACKBONE, BACKBONE[1:]):
        assert phases[previous]["_advances_to"] == current
        assert phases[current]["_requires_phase"] == previous
    assert phases["generate"]["_advances_to"] == "complete"
    assert sum(data.get("_init") is True for data in phases.values()) == 1

    for current, downstream in zip(BACKBONE[:-1], BACKBONE[1:]):
        guard = phases[current]["_re_entry_guard"]
        assert guard == {
            "_stale_if_completed": downstream,
            "_stale_artifact": guard["_stale_artifact"],
            "_on_reentry": "stop_unless_confirmed",
            "_on_confirm": "reset_downstream_to_pending",
        }
    assert "_re_entry_guard" not in phases["generate"]


def test_dispatch_and_opt_in_contracts() -> None:
    phases = {name: phase(name) for name in BACKBONE + SIDEBARS}
    dispatched = {name for name, data in phases.items() if "_exec" in data}
    assert dispatched == {"discover", "generate"}
    for name in dispatched:
        assert phases[name]["_interactive"] is False
        assert phases[name]["_exec"] == {"_agent": "rw"}
    assert phases["clarify"]["_interactive"] is True
    assert phases["workshop"]["_kind"] == "sidebar"
    assert phases["workshop"]["_gates"] == "generate"
    assert "_advances_to" not in phases["workshop"]
    generate_asserts = [item.get("_assert", "") for item in phases["generate"]["_preconditions"]]
    assert any("decide_and_execute" in item and "not execution consent" in item for item in generate_asserts)
    assert any(item.get("_check_phase_completed") == "workshop" for item in phases["generate"]["_preconditions"])


def test_feedback_uses_exact_trigger_map_and_no_backbone_keys() -> None:
    feedback = phase("feedback")
    assert feedback["_trigger"] == {
        "_when": "the user opts in after the post-Estimate decision resolves"
    }
    assert "_advances_to" not in feedback
    assert "_gates" not in feedback
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    discover = phase_file("discover").read_text(encoding="utf-8")
    assert "Feedback decline is handled here" in skill
    assert "For a local-only Blueprint, application, or billing run" in discover
    assert "does not require the Render CLI, authentication, workspace enumeration" in discover
    assert "null `workspace_id`, `consent_digest`, and `ownership_index_digest`" in discover
    assert "Only when live capture is selected" in discover
    assert "without loading Feedback" in skill


def body_after_frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    return text[text.index("\n---\n", 4) + len("\n---\n"):]


def test_discover_executable_helpers_run_only_in_main_window() -> None:
    # PR #489 review finding 1 (P1): `_exec: {_agent: rw}` selects a worker
    # with Read/Grep/Glob/Write/Edit only, so every Python helper must run in
    # the main window before dispatch and the dispatched units stay file-only.
    executes_helper = re.compile(r"Invoke `|uv run|--frozen python|\.py` through")
    discover = phase("discover")
    assert discover["_exec"] == {"_agent": "rw"}
    assert discover["_interactive"] is False
    gate = [row.get("_assert", "") for row in discover["_preconditions"]]
    assert any("normalize-result.json" in row and "main window" in row for row in gate)

    discover_body = body_after_frontmatter(phase_file("discover"))
    assert "## Pre-dispatch main-window actions" in discover_body
    assert "WORKER_DONE" in discover_body
    pre_dispatch = discover_body[discover_body.index("## Pre-dispatch main-window actions"):]
    # Negative control: the helpers are still documented, in the main-window section.
    assert executes_helper.search(pre_dispatch)
    for helper in ("parse-render-blueprint.py", "scan-render-application.py", "parse-render-billing.py", "normalize-render-capture.py"):
        assert f"`{helper}`" in pre_dispatch, helper
    for flag in ("--output-inventory", "--output-clusters", "--output-ai-profile", "--output-ai-discovery"):
        assert flag in pre_dispatch, flag

    dispatched_units = [fragment["_file"] for fragment in discover["_fragments"]] + [discover["_assemble"]["_file"]]
    assert len(dispatched_units) == 5
    for unit in dispatched_units:
        body = body_after_frontmatter(SKILL_ROOT / "references" / unit)
        assert not executes_helper.search(body), unit
        assert re.search(r"file-only|reads only|read only", body), unit

    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "never invokes `uv`, Python, or any shell command" in skill
    abi = (SKILL_ROOT / "references/shared/script-abis.md").read_text(encoding="utf-8")
    assert abi.count("Caller: main window") == 7


def test_every_phase_reference_resolves_and_unit_identity_matches() -> None:
    for name in BACKBONE + SIDEBARS:
        data = phase(name)
        for fragment in data["_fragments"]:
            path = SKILL_ROOT / "references" / fragment["_file"]
            assert path.is_file(), path
            unit = frontmatter(path)
            assert unit["_fragment"] == fragment["_id"]
            assert unit["_of_phase"] == name
        assembler_path = SKILL_ROOT / "references" / data["_assemble"]["_file"]
        assert assembler_path.is_file(), assembler_path
        assembler = frontmatter(assembler_path)
        assert assembler["_of_phase"] == name
        assert assembler["_assemble"]
        for entry in data.get("_knowledge", []):
            path = SKILL_ROOT / referenced_file(entry)
            assert path.is_file(), path


def test_backbone_and_sidebar_state_tuples_validate() -> None:
    schema = json.loads((SHARED_ROOT / "state/phase-status.schema.json").read_text())
    statuses = {
        "initial": ("discover", {"discover": "in_progress"}),
        "clarify": ("clarify", {"discover": "completed", "clarify": "in_progress"}),
        "workshop_offer": (
            "estimate",
            {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed", "generate": "pending", "workshop": "pending", "feedback": "pending"},
        ),
        "decide_complete": (
            "complete",
            {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed", "generate": "pending", "workshop": "completed", "feedback": "completed"},
        ),
        "execute": (
            "generate",
            {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed", "generate": "in_progress", "workshop": "completed", "feedback": "completed"},
        ),
    }
    for label, (current, phases) in statuses.items():
        state = {
            "migration_id": "1021-1200",
            "last_updated": "2026-10-21T12:00:00Z",
            "current_phase": current,
            "phases": phases,
        }
        if label == "decide_complete":
            state["run_mode"] = "decide"
        if label == "execute":
            state["run_mode"] = "decide_and_execute"
        jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker()).validate(state)

    assert statuses["workshop_offer"][1]["workshop"] == "pending"
    assert statuses["decide_complete"][1]["generate"] == "pending"
    assert statuses["execute"][1]["workshop"] == "completed"


def test_vendored_shared_contracts_are_byte_identical() -> None:
    pairs = [
        (SHARED_ROOT / "dsl/INTERPRETER.md", SKILL_ROOT / "references/vendored/dsl/INTERPRETER.md"),
        (SHARED_ROOT / "state/phase-status.schema.json", SKILL_ROOT / "references/vendored/state/phase-status.schema.json"),
        (SHARED_ROOT / "pricing/aws-infra-pricing.json", SKILL_ROOT / "references/vendored/pricing/aws-infra-pricing.json"),
        (SHARED_ROOT / "workshop/workshop-invariants.md", SKILL_ROOT / "references/vendored/workshop/workshop-invariants.md"),
    ]
    pairs.extend((path, SKILL_ROOT / "references/vendored/clarify" / path.name) for path in (SHARED_ROOT / "clarify").iterdir())
    pairs.extend((path, SKILL_ROOT / "references/vendored/estimate" / path.name) for path in (SHARED_ROOT / "estimate").iterdir())
    pairs.append((PLUGIN_ROOT / "scripts/contracts/ai-workload-profile.schema.json", SKILL_ROOT / "references/contracts/ai-workload-profile.schema.json"))
    for canonical, vendored in pairs:
        assert vendored.read_bytes() == canonical.read_bytes(), vendored


def test_generate_semantic_validation_is_main_window_digest_bound() -> None:
    generate = (SKILL_ROOT / "references/phases/generate/generate.md").read_text(encoding="utf-8")
    assert "run_mode: \"decide_and_execute\"" in generate
    assert "source SHA-256" in generate
    assert "renewed consent" in generate
    assert "The dispatched worker never invokes Render" in generate
    assert "There is no skip-and-complete path" in generate
    assert "If `render_blueprint` is absent" in generate
    preconditions = phase("generate")["_preconditions"]
    assertions = [row.get("_assert", "") for row in preconditions]
    semantic_gate = next(value for value in assertions if "current source SHA-256" in value)
    assert "if inventory discovery_sources contains render_blueprint" in semantic_gate
    assert "otherwise the Blueprint semantic gate is not applicable" in semantic_gate


def test_feedback_accept_decline_failure_and_offer_once_contract() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    feedback = (PHASE_ROOT / "feedback/feedback.md").read_text(encoding="utf-8")
    collect = (PHASE_ROOT / "feedback/feedback-collect.md").read_text(encoding="utf-8")
    assemble = (PHASE_ROOT / "feedback/feedback-assemble.md").read_text(encoding="utf-8")
    assert "Offer Feedback exactly once" in skill
    assert "never offer it again after Generate" in skill
    assert "create no feedback or trace file" in feedback
    assert 'phases.feedback: "in_progress"' in feedback
    assert "collection or persistence failure is recoverable" in feedback
    assert collect.count("prefer_not_to_answer") == 5
    for forbidden in ("workspace", "repository", "email", "source-resource", "configuration"):
        assert forbidden in collect.lower()
    for unchanged in ("current_phase", "run_mode", "recommendations", "generated artifacts"):
        assert unchanged in assemble


def test_all_seven_script_abis_and_locked_runtime_are_declared() -> None:
    abi = (SKILL_ROOT / "references/shared/script-abis.md").read_text(encoding="utf-8")
    scripts = {
        "parse-render-blueprint.py", "capture-render-cli.py", "capture-render-api.py",
        "scan-render-application.py", "normalize-render-capture.py",
        "parse-render-billing.py", "validate-render-migration-report.py",
    }
    assert {name for name in scripts if f"`{name}`" in abi} == scripts
    for token in ("BLUEPRINT_OK", "CLI_CAPTURE_OK", "API_CAPTURE_OK", "APP_SCAN_OK", "NORMALIZE_OK", "BILLING_OK", "REPORT_OK"):
        assert token in abi
    assert "atomic" in abi and "exit 1" in abi and "exit 2" in abi

    project = (SKILL_ROOT / "scripts/pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = "==3.12.*"' in project
    assert '"PyYAML==6.0.2"' in project
    assert '"jsonschema==4.23.0"' in project
    assert '"pytest==9.0.3"' in project
    lock = (SKILL_ROOT / "scripts/uv.lock").read_text(encoding="utf-8")
    assert re.search(r'name = "pyyaml"\nversion = "6\.0\.2"', lock)
    assert re.search(r'name = "jsonschema"\nversion = "4\.23\.0"', lock)


def test_render_is_registered_without_mcp_or_plan_handoff_drift() -> None:
    manifests = [
        PLUGIN_ROOT / "plugin.json",
        PLUGIN_ROOT / ".claude-plugin/plugin.json",
        PLUGIN_ROOT / ".codex-plugin/plugin.json",
        PLUGIN_ROOT / ".cursor-plugin/plugin.json",
    ]
    for path in manifests:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert {"render", "render-to-aws"} <= set(document["keywords"]), path
        assert "Render" in document["description"], path

    claude_marketplace = json.loads((REPO_ROOT / ".claude-plugin/marketplace.json").read_text())
    cursor_marketplace = json.loads((REPO_ROOT / ".cursor-plugin/marketplace.json").read_text())
    for marketplace in (claude_marketplace, cursor_marketplace):
        entry = next(item for item in marketplace["plugins"] if item["name"] == "aws-startup-advisor")
        assert {"render", "render-to-aws"} <= set(entry["keywords"])
        assert "Render" in entry["description"]

    codex = json.loads((PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text())
    assert "Migrate my Render services to AWS" in codex["interface"]["defaultPrompt"]
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Install all 13 skills together" in readme
    assert "| 7 | `render-to-aws` |" in readme
    assert "Render CLI 2.30.0" in readme
    assert "neither configures nor invokes a Render MCP server" in readme

    mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"aws-mcp"}
    assert not (SKILL_ROOT / "plan.json").exists()
