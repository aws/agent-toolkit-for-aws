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
    assert "EB + `github_actions`, or EB + `codepipeline` for an app that does not resolve to CNB" in section
    assert "EB + `manual`" in section
    assert "Fargate or EKS" in section
    assert "Dockerfile per buildpack app" in section
    assert 'buildpack app with `app_containerization_method == "dockerfile"`' in section
    assert "needs no Dockerfile" in section and "never add the clause for it" in section
    assert "CodePipeline is unsupported for CNB apps" in section
    assert "EB + `codepipeline`, app resolves to CNB" in section
    assert "pipelines are detected, not generated" not in section
    promote = next(line for line in section.splitlines() if line.startswith("| Pipelines and promote"))
    assert "Per target" in promote and "**Generated** for EB apps" in promote and "**Build** for Fargate/EKS" in promote
    closing = section[section.index("**Closing paragraph (always):**") :]
    assert "a deploy pipeline with promote and release steps" not in closing
    assert "promote step for every" in closing
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


def test_report_adds_cfo_brief_timeline_and_security_meaning() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert "### `exec-share`" in text
    assert "Share with your CFO" in text
    assert "### `exec-timeline`" in text
    assert "planning band" in text
    assert "2–6 weeks" in text and "12–18 weeks" in text
    assert "What it does" in text and "Threat mitigated" in text
    banned = text[text.index("Do not emit") : text.index("Do not emit") + 220]
    assert "exec-timeline" not in banned
    assert "appendix-security-gap" in banned
    core = DECISION_CORE.read_text(encoding="utf-8")
    assert "`exec-share`" in core and "`exec-timeline`" in core


def test_decision_report_renders_developer_workflow_pre_execution() -> None:
    text = DECISION_CORE.read_text(encoding="utf-8")
    assert "`exec-costs` →\n  `developer-workflow`" in text or "`exec-costs` → `developer-workflow`" in text, (
        "decision-mode body order must include developer-workflow"
    )
    assert "Will be generated" in text
    assert "Developer\n  workflow" in text or "Developer workflow" in text  # DECISION.md twin


def test_q12c_explains_targets_in_heroku_terms_and_names_express_mode() -> None:
    """Q12c must give a Heroku user the management-model comparison before the option list,
    name ECS Express Mode in a Fargate web row (not only inside option 3), and recommend
    Fargate when every app already runs Heroku's container stack (step 4b)."""
    text = INTERVIEW.read_text(encoding="utf-8")
    section = text[text.index("#### Q12c") :]
    section = section[: section.index("#### Q12d")]
    options = section.index("> 1. Use this recommendation (default)")
    # Comparison table precedes the options and covers the three management models.
    table_header = "| | Elastic Beanstalk | ECS Fargate | Amazon EKS |"
    assert table_header in section and section.index(table_header) < options
    for row in ("| Closest to |", "| You deploy |", "| You operate |", "| Scaling and billing |"):
        assert row in section, f"comparison row {row!r} missing"
    assert section.index("| Scaling and billing |") < options
    # A Fargate web row is a standard ECS service; Express Mode is a condition, never the outcome,
    # and never mentioned for workers.
    assert "`web` → ECS Fargate: a standard ECS service behind" in section
    assert "`web` → ECS Fargate on ECS Express Mode" not in section
    assert "Worker rows never mention Express Mode" in section
    # Step 4b: the container signal flips the default to Fargate with no scale_note.
    step_4b = section[section.index("4b. **Container signal.**") : section.index("4a. **Scale check.**")]
    assert '`"containerized"`' in step_4b and "`ecs-fargate`" in step_4b
    assert "`\"buildpack_only\"`" in step_4b and "`\"partial\"`" in step_4b
    assert "step 4b fired and step 4a did not" in section
    assert '"reasons": [<container-signal reason from step 4b>' in section
    # The documented default row and option 1 both carry the 4b shape.
    defaults_row = next(line for line in text.splitlines() if line.startswith("| Q12c — Compute target     |"))
    assert "step 4b trigger" in defaults_row
    assert "when step 4a or 4b fired" in section


def test_q12c_promises_express_mode_only_when_design_can_use_it() -> None:
    """design-mapping.md 2A uses Express only when dns_strategy != route53, the task fits
    4096/8192, the app is not CNB and not in a Private Space. Q10 defaults to route53 and the
    fast path always applies that default, so Q12c must not promise Express on the fast path,
    for performance-l+ dynos, or for CNB (buildpack) web apps; the persisted 4b reason must not
    promise it at all."""
    text = INTERVIEW.read_text(encoding="utf-8")
    section = text[text.index("#### Q12c") :]
    section = section[: section.index("#### Q12d")]
    step_4b = section[section.index("4b. **Container signal.**") : section.index("4a. **Scale check.**")]
    assert "Express Mode" not in step_4b.split("The reason names no ECS shape")[0], (
        "the persisted step 4b recommendation reason must not promise ECS Express Mode"
    )
    row = section[section.index("**Row wording for Fargate web formations.**") : section.index("**Comparison facts")]
    assert "**Fast path:** never mention Express Mode" in row
    assert '`dns_strategy: "route53"` after' in row and "rules it out for every web dyno" in row
    assert "`fargate_cpu <= 4096` and `fargate_memory <= 8192`" in row
    assert "`performance-l` and larger map to 16 GiB or more and are out" in row
    assert "not in a Private Space" in row
    assert "resolves to CNB and does **not** qualify" in row
    assert "if you keep your current DNS provider (Q10)" in row
    # Batch references match the batch table: Q10 is Batch 2, Q12e is Batch 3, both after Q12c.
    assert "Q10 (DNS, Batch 2) and Q12e (Batch 3) are both asked **after**" in row
    assert "asked in Batch 2, after this question" not in section
    batch_2 = next(line for line in text.splitlines() if line.startswith("| **2** |"))
    batch_3 = next(line for line in text.splitlines() if line.startswith("| **3** |"))
    assert "Q10" in batch_2 and "Q12e" not in batch_2
    assert "Q12b" in batch_3
    batch_3_body = text[text.index("### Batch 3: Operational / Conditional") :]
    assert "#### Q12e" in batch_3_body and "#### Q12e" not in text[: text.index("### Batch 3: Operational / Conditional")]
    # The comparison table header no longer folds Express into the Fargate column.
    assert "| | Elastic Beanstalk | ECS Fargate | Amazon EKS |" in section
    assert "ECS Fargate (web dynos on ECS Express Mode)" not in section
    # Option 3 states every 2A condition rather than "land on".
    assert "web dynos land on ECS Express Mode" not in section
    option_3 = next(line for line in section.splitlines() if line.startswith("> 3. Use ECS Fargate"))
    assert "they move to ECS Express Mode" in option_3 and "(Q10, default is Route 53)" in option_3
    for condition in ("4 vCPU / 8 GiB", "own Dockerfile", "not in a Private Space", "canary (Q12e)"):
        assert condition in option_3, condition
    # The comparison table cell is shown on the fast path too, so it must carry the same conditions.
    operate_cell = next(line for line in section.splitlines() if line.startswith("> | You operate |"))
    assert "can use ECS Express Mode" in operate_cell and "when you keep your current DNS provider (Q10)" in operate_cell
    for condition in ("4 vCPU / 8 GiB", "own Dockerfile", "no Private Space"):
        assert condition in operate_cell, condition
    assert "Express Mode provisions them for you when" not in operate_cell


def test_q12c_step_4b_trigger_is_stated_once_and_reused() -> None:
    """Step 4b, Interpret option 1, the Default paragraph and the Defaults Table row must all
    key off the same source-neutral trigger (status resolved to containerized before Q12c by
    extraction on either path or on the sheet), so the fast path and the full flow give the
    same inventory the same default."""
    text = INTERVIEW.read_text(encoding="utf-8")
    section = text[text.index("#### Q12c") :]
    section = section[: section.index("#### Q12d")]
    step_4b = section[section.index("4b. **Container signal.**") : section.index("4a. **Scale check.**")]
    assert "The **4b trigger** is:" in step_4b
    assert "applied directly on the fast" in step_4b and "takes 4b exactly like the full flow" in step_4b
    interpret = section[section.index("**Interpret:**") :]
    assert "the 4b trigger does not hold" in interpret
    assert 'not `"containerized"` on the sheet' not in interpret
    assert "the 4b trigger holds on the fast path" in section
    defaults_row = next(line for line in text.splitlines() if line.startswith("| Q12c — Compute target     |"))
    assert "the step 4b trigger, by extraction on either path or on the sheet" in defaults_row
    assert "when the sheet did not resolve" not in defaults_row
    # Combined 4a + 4b: the 4a shape carries the container-signal reason too.
    shape_4a = interpret[interpret.index("step 4a **fired** (41 or more") :]
    shape_4a = shape_4a[: shape_4a.index("Never write")]
    assert "<container-signal reason from step 4b when 4b also fired>" in shape_4a
    assert "or both when both fired" in section
