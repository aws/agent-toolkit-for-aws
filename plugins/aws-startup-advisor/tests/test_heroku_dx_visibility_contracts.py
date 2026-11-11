"""Guards for the heroku-to-aws developer-workflow visibility change (PR #612 review).

The review found three places where the new guidance was described but not wired:
Q5c was marked always-active yet absent from the Batch 1 dispatch lists; the
Q12c scale check recommended Fargate yet option 1 still wrote an EB default; and
`recommendation.scale_note` was absent from the machine-enforced preference
shape, so the artifact validator rejected both `preferences.json` and the
workshop snapshot that carried it. These checks anchor on stable substrings and
on the real validator so a rewording that drops the wiring again fails here.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL = PLUGIN_ROOT / "skills" / "heroku-to-aws"
INTERVIEW = SKILL / "references" / "phases" / "clarify" / "clarify-interview.md"
ASSEMBLE = SKILL / "references" / "phases" / "clarify" / "clarify-assemble.md"
REPORT = SKILL / "references" / "phases" / "generate" / "generate-report.md"
DECISION_CORE = SKILL / "references" / "shared" / "report-decision-core.md"
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
SEED_PREFERENCES = PLUGIN_ROOT / "fixtures" / "heroku-workshop" / "after-arm64-reprice" / "preferences.json"


def _run_validator(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--run-dir", str(run_dir), "--skill", "heroku-to-aws", "--no-baseline"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
    )


def test_q5c_is_dispatched_in_batch_1_before_q12c() -> None:
    text = INTERVIEW.read_text(encoding="utf-8")
    batch_row = next(line for line in text.splitlines() if line.startswith("| **1** |"))
    assert "Q5c" in batch_row and batch_row.index("Q5c") < batch_row.index("Q12c"), (
        "Batch 1 membership row must list Q5c before Q12c (Q12c reads its answer)"
    )
    prompt = re.search(r"\[Present active questions Q1–Q3, Q5, ([^\]]*)\]", text)
    assert prompt is not None, "Step 3a Batch 1 presentation prompt not found"
    assert "Q5c" in prompt.group(1) and prompt.group(1).index("Q5c") < prompt.group(1).index("Q12c")


def test_q12c_option_1_writes_the_computed_fargate_default() -> None:
    text = INTERVIEW.read_text(encoding="utf-8")
    interpret = text[text.index("#### Q12c") :]
    interpret = interpret[: interpret.index("#### Q12d")]
    assert '"default": "ecs-fargate", "overrides": [], "chosen_by": "system_recommended"' in interpret, (
        "accepting the scale-aware recommendation must write compute_target.default ecs-fargate"
    )
    assert '"scale_note": "{N} formations"' in interpret
    # The explicit EB override stays available and keeps the system_forced worker overrides.
    assert 'user selected EB for all EB-compatible formations' in interpret
    defaults_row = next(line for line in text.splitlines() if line.startswith("| Q12c — Compute target     |"))
    assert "computed plan" in defaults_row and '"ecs-fargate"' in defaults_row


def test_scale_note_is_in_the_canonical_preference_shape_and_validates(tmp_path: Path) -> None:
    assert '"scale_note"' in ASSEMBLE.read_text(encoding="utf-8")

    seed = json.loads(SEED_PREFERENCES.read_text(encoding="utf-8"))
    assert "scale_note" not in seed["design_constraints"]["compute_target"]["recommendation"]

    # Old artifact without the note still validates.
    old_run = tmp_path / "old"
    old_run.mkdir()
    shutil.copy(SEED_PREFERENCES, old_run / "preferences.json")
    old = _run_validator(old_run)
    assert old.returncode == 0, old.stdout + old.stderr

    # New artifact (and its workshop snapshot twin) carrying the accepted Fargate plan validates.
    new = json.loads(json.dumps(seed))
    new["global"]["dx_priority"] = "critical"
    target = new["design_constraints"]["compute_target"]
    target["default"] = "ecs-fargate"
    target["overrides"] = []
    target["chosen_by"] = "system_recommended"
    target["recommendation"]["value"] = "ecs-fargate"
    target["recommendation"]["scale_note"] = "41 formations"
    new["design_constraints"].pop("eb_deploy_method", None)
    new_run = tmp_path / "new"
    (new_run / "scenarios").mkdir(parents=True)
    (new_run / "preferences.json").write_text(json.dumps(new, indent=2), encoding="utf-8")
    (new_run / "scenarios" / "scenario-001.preferences.json").write_text(json.dumps(new, indent=2), encoding="utf-8")
    result = _run_validator(new_run)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UNKNOWN_KEY" not in result.stdout


def test_developer_workflow_statuses_derive_from_target_and_deploy_method() -> None:
    text = REPORT.read_text(encoding="utf-8")
    section = text[text.index("### `developer-workflow`") :]
    assert "EB + `github_actions` or `codepipeline`" in section
    assert "EB + `manual`" in section
    assert "Fargate or EKS" in section
    assert "Dockerfile per buildpack app" in section
    assert "task definition carries no environment/secrets bindings" in section


def test_config_vars_row_gives_eks_its_own_kubernetes_rule() -> None:
    text = REPORT.read_text(encoding="utf-8")
    section = text[text.index("### `developer-workflow`") :]
    rules = section[: section.index("| Heroku today")]
    eks_rule = [line for line in rules.splitlines() if line.startswith("| Config vars") and "| EKS " in line]
    assert len(eks_rule) == 1, "EKS must have its own config-vars rule, not share Fargate's"
    assert "secretKeyRef" in eks_rule[0] and "DATABASE_URL" in eks_rule[0] and "REDIS_URL" in eks_rule[0]
    assert "Kubernetes Secret" in eks_rule[0]
    assert "Fargate config-var procedure does not apply" in eks_rule[0]
    fargate_rule = [line for line in rules.splitlines() if line.startswith("| Config vars") and "| Fargate " in line]
    assert len(fargate_rule) == 1 and "task definition" in fargate_rule[0]
    assert "| Fargate or EKS" not in "\n".join(eks_rule + fargate_rule)


def test_one_off_and_log_rows_follow_selected_target() -> None:
    text = REPORT.read_text(encoding="utf-8")
    section = text[text.index("### `developer-workflow`") :]
    rules = section[: section.index("| Heroku today")].splitlines()
    for row in ("One-off commands", "Log tailing"):
        eks = [line for line in rules if line.startswith(f"| {row}") and "| EKS " in line]
        ecs = [line for line in rules if line.startswith(f"| {row}") and "| EB / Fargate" in line]
        assert len(eks) == 1 and len(ecs) == 1, f"{row}: one EKS rule and one EB/Fargate rule"
        assert "kubectl" in eks[0]
        assert "kubectl" not in ecs[0]
    one_off = [line for line in rules if line.startswith("| One-off commands") and "| EKS " in line][0]
    assert "kubectl exec" in one_off and "Kubernetes Job" in one_off and "never give them ECS Exec" in one_off
    logs = [line for line in rules if line.startswith("| Log tailing") and "| EKS " in line][0]
    assert "kubectl logs -f" in logs and "Fluent Bit" in logs and "CloudWatch Observability" in logs
    assert "live tail is **Build**" in logs
    ecs_logs = [line for line in rules if line.startswith("| Log tailing") and "| EB / Fargate" in line][0]
    assert "CloudWatch Logs live tail" in ecs_logs and "Build" not in ecs_logs
    # Rendered rows follow the target in both all-EKS and mixed EB+EKS estates.
    rendered = section[section.index("| Heroku today") :]
    run_row = [line for line in rendered.splitlines() if line.startswith("| `heroku run`")][0]
    log_row = [line for line in rendered.splitlines() if line.startswith("| `heroku logs --tail`")][0]
    for row in (run_row, log_row):
        assert "Per the status rules above" in row and "EKS" in row and "Beanstalk/Fargate" in row
        assert "different command" not in row or "for the target" in row
    assert "kubectl exec" in run_row and "kubectl logs -f" in log_row and "CloudWatch tailing **Build**" in log_row
    core = DECISION_CORE.read_text(encoding="utf-8")
    assert "one-off-command and log-tailing rules" in core and "kubectl logs -f" in core


def test_scheduler_row_status_is_computed_from_mapped_vs_deferred() -> None:
    text = REPORT.read_text(encoding="utf-8")
    section = text[text.index("### `developer-workflow`") :]
    assert "never asserted" in section
    assert "**Covered** — mapped by this migration" not in section, "unconditional Scheduler status must be gone"
    assert "scheduler add-on(s) deferred — replacement selection pending" in section
    assert "{S_mapped} scheduler add-ons mapped, {S_deferred} deferred" in section
    core = DECISION_CORE.read_text(encoding="utf-8")
    assert "`services[]` vs `deferred[]`" in core and "never asserted" in core


def test_decision_report_renders_developer_workflow_pre_execution() -> None:
    text = DECISION_CORE.read_text(encoding="utf-8")
    assert "`exec-costs` →\n  `developer-workflow`" in text or "`exec-costs` → `developer-workflow`" in text, (
        "decision-mode body order must include developer-workflow"
    )
    assert "Will be generated" in text
    assert "Developer\n  workflow" in text or "Developer workflow" in text  # DECISION.md twin
