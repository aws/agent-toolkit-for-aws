from __future__ import annotations

import json
import math
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
        assert "Render" in entry["description"]
    # Cursor's marketplace entry schema allows only name/source/description/minClientVersions
    # (cursor/plugins#281); keywords live in .cursor-plugin/plugin.json, checked above.
    claude_entry = next(item for item in claude_marketplace["plugins"] if item["name"] == "aws-startup-advisor")
    assert {"render", "render-to-aws"} <= set(claude_entry["keywords"])
    cursor_entry = next(item for item in cursor_marketplace["plugins"] if item["name"] == "aws-startup-advisor")
    assert "keywords" not in cursor_entry

    codex = json.loads((PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text())
    assert "Migrate my Render services to AWS" in codex["interface"]["defaultPrompt"]
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Install all 16 skills together" in readme
    assert "| 7 | `render-to-aws` |" in readme
    assert "Render CLI 2.35.0" in readme
    assert "neither configures nor invokes a Render MCP server" in readme

    mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"aws-mcp"}
    assert not (SKILL_ROOT / "plan.json").exists()
CLARIFY_ROOT = PHASE_ROOT / "clarify"
NEW_CLARIFY_FRAGMENTS = ["identity", "database-migration", "cutover", "delivery", "governance"]
WORKFLOW_FRAGMENT = "workflow"
WORKFLOW_STRUCTURED_KEYS = (
    "task_order", "callbacks", "callback_timeout_seconds", "timeout_seconds", "timeout_minutes", "max_retries",
    "wait_duration_ms", "backoff_scaling", "fan_out.max_concurrency", "compensation_task", "history",
)
def clarify_question_rows(fragments: list[str] = NEW_CLARIFY_FRAGMENTS) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for fragment_id in fragments:
        header: list[str] = []
        for line in (CLARIFY_ROOT / f"clarify-{fragment_id}.md").read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if "`question_id`" in cells:
                header = [cell.strip("`") for cell in cells]
            elif header and not set(line) <= set("|- "):
                rows.append({**dict(zip(header, cells)), "fragment": fragment_id})
    return rows
def test_clarify_depth_fragments_are_registered_and_assembled() -> None:
    clarify = phase("clarify")
    registered = {fragment["_id"]: fragment for fragment in clarify["_fragments"]}
    assert set(NEW_CLARIFY_FRAGMENTS) | {WORKFLOW_FRAGMENT} <= set(registered)
    assert registered["database-migration"]["_trigger"] == {"_when": "the inventory contains PostgreSQL or Key Value"}
    for fragment_id in ("identity", "cutover", "delivery", "governance"):
        assert registered[fragment_id]["_trigger"] == {"_always": True}
    assembler = frontmatter(CLARIFY_ROOT / "clarify-assemble.md")
    assert assembler["_reads"] == list(registered)
def test_every_new_clarify_question_names_a_decision_and_a_consumer() -> None:
    rows = clarify_question_rows()
    ids = [row["question_id"].strip("`") for row in rows]
    assert len(ids) == len(set(ids))
    assert len(ids) == 15
    for row in rows:
        assert row["decision_changed"], row
        assert row["Consumer"], row
        assert row["Default and consequence"], row
    consumers = " ".join(
        (SKILL_ROOT / "references" / path).read_text(encoding="utf-8")
        for path in (
            "design-refs/data.md", "design-refs/networking.md", "design-refs/delivery.md",
            "phases/estimate/estimate-infra.md", "phases/generate/generate-artifacts-docs.md",
        )
    )
    for question_id in ids:
        assert question_id in consumers, f"{question_id} has no downstream reference"


def _read_ref(path: str) -> str:
    return (SKILL_ROOT / "references" / path).read_text(encoding="utf-8")


def _clarify_row(question_id: str) -> dict[str, str]:
    return next(row for row in clarify_question_rows() if row["question_id"].strip("`") == question_id)


def test_sub_hour_downtime_and_data_bearing_key_value_never_default_to_data_loss_or_dump_restore() -> None:
    privilege = _clarify_row("database.replication_privilege")["Default and consequence"]
    assert privilege.startswith("none"), privilege
    assert "falls back to dump/restore" not in privilege
    strategy = _clarify_row("key_value.migration_strategy")["Default and consequence"]
    assert strategy.startswith("none"), strategy
    data = _read_ref("design-refs/data.md")
    assert "never fall back to dump/restore through a default" in data
    assert "`replication_privilege` when the tolerance is below one hour" in data


def test_cutover_precedence_table_covers_every_downtime_and_ttl_combination() -> None:
    text = _read_ref("phases/clarify/clarify-cutover.md")
    for window in ("short_window", "staged_shift"):
        for ttl in ("ttl_lowered_24h_ahead", "cannot_lower"):
            assert f"- `{window}` with `{ttl}`:" in text, (window, ttl)
    docs = _read_ref("phases/generate/generate-artifacts-docs.md")
    assert "`staged_shift`" in docs and "`short_window`" in docs
    assert "stage traffic, observe, then move fully; otherwise" not in docs


def test_regulated_data_control_is_designed_and_generated_for_every_covered_store() -> None:
    row = _clarify_row("data.regulated_data")
    assert "PostgreSQL, Key Value, persistent disk" in row["Resource"]
    assert "customer-managed KMS" in _read_ref("design-refs/data.md")
    assert "customer-managed KMS" in _read_ref("design-refs/storage.md")
    infra = _read_ref("phases/generate/generate-artifacts-infra.md")
    for service in ("Amazon RDS for PostgreSQL", "ElastiCache for Valkey", "Amazon EFS"):
        line = next(item for item in infra.splitlines() if item.startswith(f"| {service} |"))
        assert "data.regulated_data" in line and "aws_kms_key" in line, service


def test_estate_wide_estimate_costs_attach_to_design_mappings() -> None:
    text = _read_ref("phases/estimate/estimate-infra.md")
    assert "Do not emit separate estate-wide lines." in text
    estimate = json.loads((SKILL_ROOT / "fixtures/expected/estimation-infra.json").read_text(encoding="utf-8"))
    for scenario in estimate["scenarios"].values():
        env = next(line for line in scenario["lines"] if line["source_resource_id"] == "rr-env")
        assert "CloudWatch Logs, Metrics, and Alarms (30-day retention)" in env["aws_service"]
        assert env["monthly_amount"] and env["monthly_amount"] > 0


def test_baseline_fragment_registered_and_gated() -> None:
    generate_dir = PHASE_ROOT / "generate"
    generate = frontmatter(generate_dir / "generate.md")
    entry = next(item for item in generate["_fragments"] if item["_id"] == "artifacts-baseline")
    assert entry["_trigger"] == {"_always": True}
    fragment = PLUGIN_ROOT / "skills/render-to-aws/references" / entry["_file"]
    assert fragment.is_file()
    assert frontmatter(fragment)["_fragment"] == "artifacts-baseline"
    assert "artifacts-baseline" in frontmatter(generate_dir / "generate-assemble.md")["_reads"]
    infra = (generate_dir / "generate-artifacts-infra.md").read_text(encoding="utf-8")
    assert infra.count("artifacts-baseline") == 1
    text = fragment.read_text(encoding="utf-8")
    for phrase in (
        "desired_count", "global.compliance", "soc2", "pci", "hipaa", "fedramp", "Remote State",
        "monitoring.tf", "kms.tf", "backup.tf", "Amazon EFS", "exempt", "no new warning code",
        "CacheClusterId", "cloudwatch.amazonaws.com", "aws:SourceAccount", "cloudtrail_retention_days", "End Account Baseline",
    ):
        assert phrase in text, phrase
    assert "{{" not in text


def test_warning_code_enum_keeps_existing_order_for_append_only_merges() -> None:
    schema = json.loads((SKILL_ROOT / "references/shared/schema-generation-warnings.json").read_text(encoding="utf-8"))
    codes = schema["$defs"]["warning"]["properties"]["code"]["enum"]
    assert codes[:3] == ["deferred_shared_ai_engine", "conditional_workflow_generation_unsupported", "unpriced_cost_floor"]


PREFIX = 'uv run --project "$SKILL_BASE/scripts" --frozen python'


def _render_md() -> list[Path]:
    return sorted(SKILL_ROOT.rglob("*.md"))


def test_runtime_prefix_and_preflight_are_declared() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    assert PREFIX in skill
    assert "python -c 'import yaml,jsonschema'" in skill
    for rel in (
        "references/shared/script-abis.md",
        "references/phases/discover/discover.md",
        "references/phases/generate/generate-artifacts-report.md",
    ):
        text = (SKILL_ROOT / rel).read_text()
        assert PREFIX in text
        for line in text.splitlines():
            if "uv run" in line:
                assert PREFIX in line, (rel, line)


def test_no_ambient_python_fallback_is_preserved() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    assert "Do not fall back to an ambient Python environment" in skill
    bad = re.compile(r'python3?\s+"?\$SKILL_BASE|python3?\s+\S*(parse|normalize)-render')
    for path in _render_md():
        assert not bad.search(path.read_text()), path


def test_missing_uv_degradation_is_declared() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    assert "https://docs.astral.sh/uv/getting-started/installation/" in skill
    assert "`uv --version`" in skill
    assert "rerun the same request" in skill
    assert "Discover Steps 1 to 3" in skill
    assert "Generate stage 7" in skill
    assert "Clarify, Design, Estimate, Workshop, Feedback" in skill
    assert "do not" in skill.split("Steps that need `uv`:")[1].split("\n")[0]


def test_discover_uv_gate_precedes_consent_and_capture() -> None:
    text = (PHASE_ROOT / "discover/discover.md").read_text()
    body = text.split("### Step 0 ", 1)[1]
    gate = body.index("### Step 0b")
    assert gate < body.index("### Step 1")
    gate_text = body[gate : body.index("### Step 1")]
    assert "mint no attempt ID" in gate_text
    assert "no consent prompt" in gate_text
    assert "no capture" in gate_text
    assert "whether or not" in gate_text
    assert "leaves Discover `in_progress`" in gate_text
    assert "stays pending" not in gate_text
    skill = (SKILL_ROOT / "SKILL.md").read_text().split("Steps that need `uv`:")[1].split("\n")[0]
    assert "`blueprint_validate`" in skill
    assert "leaves Discover `in_progress`" in skill
    assert "stays pending" not in skill


def test_script_free_phases_do_not_invoke_scripts() -> None:
    pattern = re.compile(r"uv run|--frozen python|\.py\b")
    for phase in ("clarify", "design", "estimate", "workshop", "feedback"):
        for path in (PHASE_ROOT / phase).rglob("*"):
            if path.is_file():
                assert not pattern.search(path.read_text()), path


def test_generate_report_stage_blocks_without_uv_and_has_no_skip() -> None:
    for name in ("generate-assemble.md", "generate-artifacts-report.md"):
        text = (PHASE_ROOT / "generate" / name).read_text()
        assert "stage 7 is recorded as `failed`" in text
        assert "stage 7 is `not_run`" not in text
        assert "There is no validation skip" in text
    assemble = (PHASE_ROOT / "generate/generate-assemble.md").read_text()
    assert "No `not_run`" in assemble


def test_no_uv_validation_report_shape_is_schema_valid() -> None:
    validator = jsonschema.Draft202012Validator(
        json.loads((SKILL_ROOT / "references/shared/schema-validation-report.json").read_text())
    )
    report = json.loads((SKILL_ROOT / "fixtures/expected/generated/validation-report.json").read_text())
    report["status"] = "failed"
    report["checks"]["report"] = {
        "status": "failed",
        "command": "uv run --project SKILL_BASE/scripts --frozen python validate-render-migration-report.py",
        "evidence": "uv or the frozen environment is unavailable; report validation did not run.",
    }
    validator.validate(report)
    report["checks"]["report"]["status"] = "not_run"
    assert list(validator.iter_errors(report))


def test_readme_uv_prerequisite_wording() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text()
    line = next(l for l in readme.splitlines() if "docs.astral.sh/uv" in l)
    assert "render-to-aws" in line
    assert "unfinished Render Discover" in line
    assert "report validation" in line
    assert "Blueprint semantic revalidation" in line


def test_workflow_clarify_rows_cover_the_structured_keys_the_workflow_rubric_reads() -> None:
    rows = clarify_question_rows([WORKFLOW_FRAGMENT])
    ids = [row["question_id"].strip("`") for row in rows]
    assert len(ids) == len(set(ids))
    assert {row["fragment"] for row in rows} == {WORKFLOW_FRAGMENT}
    for row in rows:
        assert row["decision_changed"] and row["Default and consequence"] and row["Consumer"], row
    structured = [row for row in rows if "generate-infra-workflow.md" in row["Consumer"]]
    assert {row["question_id"].strip("`") for row in structured} == {
        "workflow.task_order", "workflow.callback_wait", "workflow.timeout", "workflow.task_retry",
        "workflow.fan_out_concurrency", "workflow.compensation", "workflow.history",
    }
    for row in structured:
        assert row["Default and consequence"].startswith("none."), row
    text = " ".join(row["Default and consequence"] + " " + row["decision_changed"] for row in structured)
    for key in WORKFLOW_STRUCTURED_KEYS:
        assert f"`{key}`" in text, f"{key} has no Clarify row"


def test_golden_preferences_use_only_question_ids_a_clarify_fragment_defines() -> None:
    defined = {row["question_id"].strip("`") for row in clarify_question_rows([*NEW_CLARIFY_FRAGMENTS, WORKFLOW_FRAGMENT])}
    for fragment in ("global", "compute", "data", "storage", "network"):
        for line in (CLARIFY_ROOT / f"clarify-{fragment}.md").read_text(encoding="utf-8").splitlines():
            defined.update(re.findall(r"`([a-z_]+\.[a-z_]+)`", line))
    preferences = json.loads((SKILL_ROOT / "fixtures/expected/preferences.json").read_text(encoding="utf-8"))
    for row in preferences["questions"]:
        if row["topic"] == "workflow":
            assert row["question_id"] in defined, row["question_id"]


def test_customer_managed_key_field_is_one_name_across_design_estimate_and_kms_gate() -> None:
    field = "customer_managed_key: true"
    for path in ("design-refs/data.md", "design-refs/storage.md", "phases/generate/generate-artifacts-infra.md"):
        assert field in _read_ref(path), path
    assert "customer_managed_key: true" in _read_ref("phases/generate/generate-artifacts-baseline.md")
    assert field in _read_ref("phases/estimate/estimate-infra.md")
    assert "aws_kms_key.stack" in _read_ref("phases/estimate/estimate-infra.md")
    infra = _read_ref("phases/generate/generate-artifacts-infra.md")
    assert "customer-managed `aws_kms_key`" not in infra
    assert "aws_kms_key.stack" in infra


def test_log_retention_lists_generate_consumers() -> None:
    row = _clarify_row("observability.log_retention")
    for name in ("generate-infra-compute.md", "generate-infra-workflow.md", "generate-infra-data.md"):
        assert name in row["Consumer"], name


def test_budget_uses_stated_guardrail_else_documented_default() -> None:
    baseline = _read_ref("phases/generate/generate-artifacts-baseline.md")
    assert "`cost.budget_guardrail`" in baseline and "is a number" in baseline
    assert "max(50, ceil(aws_monthly_balanced * 1.2))" in baseline
    governance = _clarify_row("cost.budget_guardrail")["Default and consequence"]
    assert "1.2" in governance and "no AWS Budgets alert" not in governance
    estimation = json.loads((SKILL_ROOT / "fixtures/expected/estimation-infra.json").read_text(encoding="utf-8"))
    limit = max(50, math.ceil(estimation["projected_costs"]["aws_monthly_balanced"] * 1.2))
    golden = (SKILL_ROOT / "fixtures/expected/generated/terraform/baseline.tf").read_text(encoding="utf-8")
    assert f'limit_amount = "{limit}"' in golden
    assert f"ceil({estimation['projected_costs']['aws_monthly_balanced']} * 1.2)" in golden
