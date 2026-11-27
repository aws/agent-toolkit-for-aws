"""The render-to-aws Generate golden (fixtures/expected/generated/migration-report.html) stays
green under BOTH report validators, and each validator still bites on its own contract.

The shared validator (scripts/validate-migration-report.py) owns structure, readability,
accessibility, and the shared cost anchors; the render-local validator
(skills/render-to-aws/scripts/validate-render-migration-report.py) owns the render-only
checks (mapping rows, accounting, ledger, required phrases). This test runs both on the
golden, proves the negative paths each one is responsible for, and pins the render fixture
facts later steps rely on (stable appendix lettering, the accounting split, and the four
shared anchors inside exec-costs).
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PLUGIN_ROOT / "skills" / "render-to-aws"
EXPECTED = SKILL_ROOT / "fixtures" / "expected"
GOLDEN = EXPECTED / "generated"
REPORT = GOLDEN / "migration-report.html"
SHARED_VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
LOCAL_VALIDATOR = SKILL_ROOT / "scripts" / "validate-render-migration-report.py"
ESTIMATE = EXPECTED / "estimation-infra.json"
DESIGN = EXPECTED / "aws-design.json"

GOLDEN_OPTIMIZED = '<td data-cost-key="aws_monthly_optimized">$278</td>'
GOLDEN_CURRENT = '<td data-cost-key="current_monthly">$123</td>'
RR_WEB_ROW_RE = re.compile(r'<tr data-source-resource-id="rr-web" [^>]*>.*?</tr>\s*', re.DOTALL)
APPENDIX_LABELS = (
    "Appendix A —",
    "Appendix A.1 —",
    "Appendix B —",
    "Appendix B.1 —",
    "Appendix C —",
    "Appendix E —",
    "Appendix F —",
    "Appendix G —",
    "Appendix H —",
    "Appendix I —",
    "Appendix J —",
)
# Executive add-ons rendered after exec-costs (decision core § Cost Optimization, § What-if,
# and the render-declared security teaser). Each is present exactly once and TOC-linked.
EXEC_SECTIONS = ("exec-optimization", "what-if-scenarios", "exec-security-teaser")
ACCOUNTING_SPLIT = "15 design rows · 13 generated · 2 consumed topology · 0 deferred · 0 unsupported"
SHARED_ANCHORS = ("current_monthly", "aws_monthly_premium", "aws_monthly_balanced", "aws_monthly_optimized")
BASELINE_TF = GOLDEN / "terraform" / "baseline.tf"
WORKSHOP_INDEX = EXPECTED / "scenarios" / "index.json"
BASELINE_RESOURCE_RE = re.compile(r'resource "([a-z0-9_]+)" "([a-z0-9_]+)"')
# Appendix F's questions table header; the shared validator reads the FIRST <thead> of
# appendix-config, so this exact string is what the "Source" negative mutates.
CONFIG_THEAD = (
    '<thead><tr><th scope="col">Question / assumption</th><th scope="col">Your choice</th>'
    '<th scope="col">Source</th><th scope="col">Design consequence</th></tr></thead>'
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — list args, no shell, committed script paths only
        [sys.executable, *args], capture_output=True, text=True, check=False
    )


def _shared(report: Path, migration_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        str(SHARED_VALIDATOR), str(report),
        "--estimation-infra", str(ESTIMATE), "--aws-design", str(DESIGN), "--migration-dir", str(migration_dir),
    )


def _local(report: Path, migration_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(str(LOCAL_VALIDATOR), str(report), "--migration-dir", str(migration_dir))


def _copy_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Copy fixtures/expected (artifacts, scenarios/index.json and generated/) to tmp."""
    root = tmp_path / "expected"
    shutil.copytree(EXPECTED, root, ignore=shutil.ignore_patterns("generated-variants", "workflow-contracts", ".terraform*"))
    return root, root / "generated" / "migration-report.html"


def _altered_copy(tmp_path: Path, old: str, new: str) -> tuple[Path, Path]:
    """Copy fixtures/expected to tmp and replace `old` (exactly one occurrence) in the report."""
    root, report = _copy_fixture(tmp_path)
    html = report.read_text(encoding="utf-8")
    assert html.count(old) == 1, f"fixture no longer carries exactly one {old!r}"
    report.write_text(html.replace(old, new), encoding="utf-8")
    return root, report


def _drop_toc_link(text: str, section_id: str) -> str:
    pattern = re.compile(rf'<li><a href="#{re.escape(section_id)}">[^<]*</a></li>\s*')
    assert len(pattern.findall(text)) == 1, section_id
    return pattern.sub("", text, count=1)


def _drop_section(text: str, section_id: str) -> str:
    """Remove a whole <section id=…> and its TOC link (same shape as the render-local tests)."""
    pattern = re.compile(rf'<section id="{re.escape(section_id)}">.*?</section>\s*', re.DOTALL)
    assert len(pattern.findall(text)) == 1, section_id
    return _drop_toc_link(pattern.sub("", text, count=1), section_id)


def _dropped_section_copy(tmp_path: Path, section_id: str) -> tuple[Path, Path]:
    root, report = _copy_fixture(tmp_path)
    report.write_text(_drop_section(report.read_text(encoding="utf-8"), section_id), encoding="utf-8")
    return root, report


def _section(html: str, section_id: str) -> str:
    match = re.search(rf'<section id="{re.escape(section_id)}">(.*?)</section>', html, re.DOTALL)
    assert match is not None, section_id
    return match.group(1)


def _tbody_rows(fragment: str) -> list[str]:
    tbody = re.search(r"<tbody>(.*?)</tbody>", fragment, re.DOTALL)
    assert tbody is not None
    return re.findall(r"<tr\b[^>]*>.*?</tr>", tbody.group(1), re.DOTALL)


def _first_cell_text(row: str) -> str:
    cell = re.search(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.DOTALL)
    assert cell is not None
    return re.sub(r"<[^>]+>", "", cell.group(1)).strip()


def test_generate_golden_passes_shared_validator() -> None:
    result = _shared(REPORT, EXPECTED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("REPORT_OK"), result.stdout
    for section_id in EXEC_SECTIONS + ("appendix-optimization", "appendix-config", "appendix-security", "appendix-security-gap"):
        assert section_id in result.stdout, f"{section_id} not reported in the validator's optional= list"


def test_generate_golden_passes_local_validator() -> None:
    result = _local(REPORT, EXPECTED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "REPORT_OK\n", result.stdout


def test_altered_optimized_figure_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_OPTIMIZED, GOLDEN_OPTIMIZED.replace("$278", "$230"))
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="aws_monthly_optimized"' in result.stderr, result.stderr
    assert "projected_costs.aws_monthly_optimized = $278" in result.stderr, result.stderr


def test_altered_current_spend_figure_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_CURRENT, GOLDEN_CURRENT.replace("$123", "$120"))
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="current_monthly"' in result.stderr, result.stderr
    assert "current_costs.render_monthly = $123" in result.stderr, result.stderr


def test_numeric_baseline_rendered_as_unavailable_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_CURRENT, GOLDEN_CURRENT.replace("$123", "unavailable"))
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "renders no dollar amount" in result.stderr, result.stderr


def test_deleted_target_row_fails_local_validator(tmp_path: Path) -> None:
    root = tmp_path / "expected"
    shutil.copytree(EXPECTED, root, ignore=shutil.ignore_patterns("generated-variants", "workflow-contracts", ".terraform*"))
    report = root / "generated" / "migration-report.html"
    html = report.read_text(encoding="utf-8")
    assert len(RR_WEB_ROW_RE.findall(html)) == 1
    report.write_text(RR_WEB_ROW_RE.sub("", html, count=1), encoding="utf-8")
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TARGET_MAPPING_MISMATCH" in result.stdout + result.stderr


GOLDEN_PREMIUM = '<td data-cost-key="aws_monthly_premium">$314</td>'
def test_removed_optimized_anchor_fails_local_validator(tmp_path: Path) -> None:
    # The shared pass treats optimized as optional; the render pass requires it (at base: COST_RIGHT_SIZED_MISSING).
    root, report = _altered_copy(tmp_path, GOLDEN_OPTIMIZED, "<td>$999</td>")
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "COST_AWS_MONTHLY_OPTIMIZED_MISSING" in result.stdout + result.stderr
def test_removed_premium_anchor_fails_local_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_PREMIUM, "<td>$888</td>")
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "COST_AWS_MONTHLY_PREMIUM_MISSING" in result.stdout + result.stderr
def test_projected_costs_that_disagree_with_scenarios_fail_local_validator(tmp_path: Path) -> None:
    root = tmp_path / "expected"
    shutil.copytree(EXPECTED, root, ignore=shutil.ignore_patterns("generated-variants", "workflow-contracts", ".terraform*"))
    estimate_path = root / "estimation-infra.json"
    estimate = json.loads(estimate_path.read_text(encoding="utf-8"))
    estimate["projected_costs"]["aws_monthly_balanced"] = 410
    estimate["projected_costs"]["aws_monthly_optimized"] = 330
    estimate_path.write_text(json.dumps(estimate), encoding="utf-8")
    result = _local(root / "generated" / "migration-report.html", root)
    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "COST_AWS_MONTHLY_BALANCED_SCENARIO_MISMATCH" in output
    assert "COST_AWS_MONTHLY_OPTIMIZED_SCENARIO_MISMATCH" in output
def test_golden_pins_lettering_accounting_and_anchor_placement() -> None:
    html = REPORT.read_text(encoding="utf-8")
    headings = re.findall(r"<h2>([^<]*)", html)
    toc = re.search(r'<nav class="toc"[^>]*>(.*?)</nav>', html, re.DOTALL)
    assert toc is not None
    for label in APPENDIX_LABELS:
        assert any(heading.startswith(label) for heading in headings), label
        assert label in toc.group(1), label
    assert html.count('data-accounted-count="15"') == 1
    assert ACCOUNTING_SPLIT in html
    exec_costs = re.search(r'<section id="exec-costs">(.*?)</section>', html, re.DOTALL)
    assert exec_costs is not None
    for key in SHARED_ANCHORS:
        anchor = f'data-cost-key="{key}"'
        assert html.count(anchor) == 1, key
        assert anchor in exec_costs.group(1), key
    assert "0611-0606" not in html
    for section_id in EXEC_SECTIONS:
        assert html.count(f'<section id="{section_id}">') == 1, section_id
        assert f'href="#{section_id}"' in toc.group(1), section_id
    # Executive order: exec-costs → exec-optimization → what-if-scenarios → exec-security-teaser → exec-timeline.
    order = ["exec-costs", *EXEC_SECTIONS, "exec-timeline"]
    positions = [html.index(f'<section id="{section_id}">') for section_id in order]
    assert positions == sorted(positions), order


def test_golden_pins_new_section_content() -> None:
    html = REPORT.read_text(encoding="utf-8")

    # Appendix B.1: exactly the two commitment rows the estimate emits, and the Optimized caveat.
    optimization = _section(html, "appendix-optimization")
    assert "not additive" in optimization
    assert [_first_cell_text(row) for row in _tbody_rows(optimization)] == ["Compute Savings Plans", "Database Savings Plans"]
    assert "not additive" in _section(html, "exec-optimization")

    # Appendix G: every resource address of the generated baseline.tf appears in the section.
    addresses = {f"{kind}.{name}" for kind, name in BASELINE_RESOURCE_RE.findall(BASELINE_TF.read_text(encoding="utf-8"))}
    assert len(addresses) == 22, sorted(addresses)
    security = _section(html, "appendix-security")
    missing = sorted(address for address in addresses if address not in security)
    assert not missing, missing

    # Appendix H: the skeleton's six minimum rows plus render's extra rows, with the four columns.
    gap = _section(html, "appendix-security-gap")
    gap_thead = re.search(r"<thead>(.*?)</thead>", gap, re.DOTALL)
    assert gap_thead is not None
    for column in ("Capability", "Render (detected)", "AWS (generated)", "Gap / action"):
        assert column in gap_thead.group(1), column
    assert len(_tbody_rows(gap)) >= 6

    # What-if: one row per scenario in scenarios/index.json, exactly one of them active.
    index = json.loads(WORKSHOP_INDEX.read_text(encoding="utf-8"))
    what_if_rows = _tbody_rows(_section(html, "what-if-scenarios"))
    assert len(what_if_rows) == len(index["scenarios"]) == 2
    assert sum('class="active-scenario"' in row for row in what_if_rows) == 1

    # Appendix I: the pricing-confidence table replaces the prose paragraph.
    assumptions = _section(html, "appendix-assumptions")
    pricing = re.search(r"<table>\s*<caption>Pricing confidence.*?</table>", assumptions, re.DOTALL)
    assert pricing is not None
    assert len(_tbody_rows(pricing.group(0))) >= 3

    # Appendix F: validator columns, one row per preferences.json question, defaulted rows flagged.
    config = _section(html, "appendix-config")
    assert CONFIG_THEAD in config
    questions = json.loads((EXPECTED / "preferences.json").read_text(encoding="utf-8"))["questions"]
    config_rows = _tbody_rows(config)
    assert len(config_rows) == len(questions) >= 30
    defaulted = sum(1 for question in questions if question["disposition"] == "defaulted")
    assert sum('class="assumption"' in row for row in config_rows) == defaulted


def test_removed_appendix_optimization_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _dropped_section_copy(tmp_path, "appendix-optimization")
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'optimization_opportunities exist but no <section id="appendix-optimization">' in result.stdout + result.stderr


def test_removed_exec_optimization_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _dropped_section_copy(tmp_path, "exec-optimization")
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'no <section id="exec-optimization">' in result.stdout + result.stderr


def test_removed_what_if_table_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _dropped_section_copy(tmp_path, "what-if-scenarios")
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'scenarios/index.json has ≥2 scenarios but no <section id="what-if-scenarios">' in result.stdout + result.stderr


def test_appendix_config_without_source_column_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, CONFIG_THEAD, CONFIG_THEAD.replace('<th scope="col">Source</th>', '<th scope="col">Origin</th>'))
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'appendix-config table must include a "Source" column' in result.stdout + result.stderr

def test_decision_core_and_abis_name_the_render_local_cost_checks() -> None:
    # The canonical report contract must match what stage 7 enforces: premium is required, not optional,
    # and the ownership lists name the anchor-presence and projected/scenario checks.
    shared = SKILL_ROOT / "references" / "shared"
    core = (shared / "report-decision-core.md").read_text(encoding="utf-8")
    abis = (shared / "script-abis.md").read_text(encoding="utf-8")
    assert "optional `data-cost-key=\"aws_monthly_premium\"`" not in core
    for text in (core, abis):
        assert "COST_AWS_MONTHLY_PREMIUM_MISSING" in text or "aws_monthly_premium" in text
    for code in (
        "COST_AWS_MONTHLY_OPTIMIZED_MISSING", "COST_AWS_MONTHLY_PREMIUM_MISSING",
        "COST_AWS_MONTHLY_BALANCED_SCENARIO_MISMATCH", "COST_AWS_MONTHLY_OPTIMIZED_SCENARIO_MISMATCH",
    ):
        assert code in core, code
    assert "projected/scenario" in abis
def _whole(value: object) -> int:
    """Whole dollars, half-to-even (the figure the report anchors carry)."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
def test_golden_figures_derive_from_the_estimate_and_baseline() -> None:
    """Every dollar figure this PR added is re-derived from estimation-infra.json and baseline.tf,
    never typed: tier anchors, B.1, the budget formula and limit, the teaser and the what-if baseline row."""
    html = REPORT.read_text(encoding="utf-8")
    estimate = json.loads(ESTIMATE.read_text(encoding="utf-8"))
    scenarios = estimate["scenarios"]
    balanced = _whole(scenarios["balanced"]["known_cost_monthly_usd"])
    optimized = _whole(scenarios["optimized"]["known_cost_monthly_usd"])
    like = _whole(scenarios["like_for_like"]["known_cost_monthly_usd"])
    delta = _whole(estimate["rightsizing_delta"]["monthly"])
    commitment = scenarios["optimized"]["commitment"]
    compute = commitment["compute_savings_plans"]
    discount = _whole(compute["discount_monthly_usd"])
    assert commitment["database_savings_plans"]["discount_monthly_usd"] == 0.0
    # Optimized = Balanced minus the sum of per-line whole-dollar discounts, so the exact difference is shown.
    assert Decimal(str(scenarios["balanced"]["known_cost_monthly_usd"])) - Decimal(str(scenarios["optimized"]["known_cost_monthly_usd"])) == Decimal(str(compute["discount_monthly_usd"]))
    exec_costs = _section(html, "exec-costs")
    for key, value in (("aws_monthly_balanced", balanced), ("aws_monthly_optimized", optimized), ("like_for_like_monthly", like), ("delta", delta)):
        assert re.search(rf'data-cost-key="{key}">\+?\$?{value}</td>', exec_costs), (key, value)
    assert f'<td class="savings">-${discount}</td>' in exec_costs
    optimization = _section(html, "exec-optimization")
    assert f"<td>${balanced}</td>" in optimization and f"<td>${optimized}</td>" in optimization and f"-${discount}" in optimization
    assert f"${_whole(compute['eligible_subtotal_monthly_usd'])} of Fargate and Lambda" in optimization
    appendix_b = _section(html, "appendix-costs")
    assert f"annual ${_whole(estimate['projected_costs']['aws_annual_optimized']):,}" in appendix_b
    assert f"${balanced}</td><td>${optimized}</td>" in appendix_b
    limit = max(50, math.ceil(Decimal(str(scenarios["balanced"]["known_cost_monthly_usd"])) * Decimal("1.2")))
    baseline = BASELINE_TF.read_text(encoding="utf-8")
    assert re.search(rf'limit_amount\s*=\s*"{limit}"', baseline), limit
    security = _section(html, "appendix-security")
    assert f"max(50, ceil({scenarios['balanced']['known_cost_monthly_usd']} × 1.2)) = {limit}" in security
    assert f"<strong>${limit}</strong>" in security and f"<td>${limit} monthly cost budget;" in security
    assert f"${limit} monthly limit" in _section(html, "exec-security-teaser")
    assert f"${limit} monthly budget" in html
    index = json.loads(WORKSHOP_INDEX.read_text(encoding="utf-8"))
    summary = index["scenarios"][0]["estimation_summary"]
    baseline_row = _tbody_rows(_section(html, "what-if-scenarios"))[0]
    assert f"<td>${_whole(summary['premium_known_cost_monthly_usd'])}</td><td>${balanced}</td><td>${optimized}</td>" in baseline_row
    assert summary["balanced_known_cost_monthly_usd"] == scenarios["balanced"]["known_cost_monthly_usd"]
    assert summary["optimized_known_cost_monthly_usd"] == scenarios["optimized"]["known_cost_monthly_usd"]
    # The Graviton row is re-priced under the same rules, never a stale snapshot (workshop-compare.md).
    assert "not re-priced" not in _section(html, "what-if-scenarios")
def test_golden_database_savings_plan_rows_claim_no_saving() -> None:
    """No pre-Generation-7 line gets a Database Savings Plan saving or a purchase recommendation in the report."""
    html = REPORT.read_text(encoding="utf-8")
    for section_id in ("exec-optimization", "appendix-optimization"):
        section = _section(html, section_id)
        rows = [row for row in _tbody_rows(section) if "Database Savings Plan" in row]
        assert len(rows) == 1, section_id
        for needle in ("Generation 4", "Generation 6", "Generation 7+", "db.m7g", "cache.m7g"):
            assert needle in rows[0], (section_id, needle)
        assert "$" not in rows[0], rows[0]
        assert "no saving claimed" in rows[0].lower() or "No saving claimed" in rows[0], rows[0]
    fits = _section(html, "exec-optimization")
    bullet = re.search(r"<li><strong>Database Savings Plan</strong>(.*?)</li>", fits, re.DOTALL)
    assert bullet is not None and "$" not in bullet.group(1) and "not available" in bullet.group(1)
def test_golden_credits_caveat_appears_once_below_the_b1_table() -> None:
    html = REPORT.read_text(encoding="utf-8")
    caveat = (
        "Promotional or AWS Activate credits do not cover the upfront cost of Reserved Instances or Savings Plans "
        "(Partial or All Upfront) and apply only to the ongoing discounted rate."
    )
    assert html.count(caveat) == 1
    section = _section(html, "appendix-optimization")
    assert section.index("</table>") < section.index(caveat)
    assert "credits claim" not in html
def test_golden_audit_log_and_budget_rows_match_render_docs() -> None:
    """Render docs (https://render.com/docs/audit-logs, read 2026-11-27): Pro plans and higher export
    workspace audit logs of team actions, at least 90 days retained. The budget row makes no claim about spend alerts."""
    html = REPORT.read_text(encoding="utf-8")
    security = _section(html, "appendix-security")
    trail = next(row for row in _tbody_rows(security) if _first_cell_text(row) == "CloudTrail with its log bucket")
    audit = next(row for row in _tbody_rows(_section(html, "appendix-security-gap")) if _first_cell_text(row) == "Audit logging")
    for row in (trail, audit):
        assert "No customer-visible API audit log" not in row and "no customer-visible API audit log" not in row
        assert "Pro plans and higher" in row and "90" in row and "not a trail of every API call" in row
    assert "CloudTrail adds a per-API-call trail of the AWS account" in audit
    budget = next(row for row in _tbody_rows(security) if _first_cell_text(row) == "Monthly budget")
    assert "Render billing page" in budget and "no threshold alert" not in budget
    spec = (SKILL_ROOT / "references/phases/generate/generate-artifacts-report.md").read_text(encoding="utf-8")
    assert "without a customer-visible API audit log" not in spec
    assert "Pro plans and higher" in spec and "https://render.com/docs/audit-logs" in spec
    assert "Promotional or AWS Activate credits do not cover the upfront cost" in re.sub(r"\s+", " ", spec).replace("promotional or AWS Activate", "Promotional or AWS Activate")




def _graviton_from_baseline(estimate: dict) -> dict[str, Decimal]:
    """Re-price the baseline's Balanced and like-for-like lines on the cached arm64 rates and apply
    the tier rules: Premium = Balanced (no uplift on this estate), Optimized = Balanced minus the
    Compute Savings Plan on eligible lines (Lambda at its cap), each line's discount rounded to whole
    dollars half-even; no Database Savings Plan because the database classes do not change."""
    pricing = json.loads((SKILL_ROOT / "references/vendored/pricing/aws-infra-pricing.json").read_text(encoding="utf-8"))
    rates = json.loads((SKILL_ROOT / "references/vendored/estimate/commitment-discount-ranges.json").read_text(encoding="utf-8"))
    eligibility = json.loads((SKILL_ROOT / "knowledge/estimate/estimate-defaults.json").read_text(encoding="utf-8"))["commitment_eligibility"]
    cents = Decimal("0.01")
    fargate = (Decimal(str(pricing["fargate"]["per_vcpu_hour_arm64"])) / Decimal(str(pricing["fargate"]["per_vcpu_hour"]))).quantize(cents, ROUND_HALF_EVEN)
    lam = (Decimal(str(pricing["lambda"]["per_gb_second_arm64_first_6b"])) / Decimal(str(pricing["lambda"]["per_gb_second_x86_first_6b"]))).quantize(cents, ROUND_HALF_EVEN)

    def ratio(service: str) -> Decimal:
        if service == "AWS Lambda":
            return lam
        return fargate if "Fargate" in service else Decimal(1)

    def reprice(lines: list[dict]) -> list[tuple[str, Decimal]]:
        return [
            (row["aws_service"], (Decimal(str(row["monthly_amount"])) * ratio(row["aws_service"])).quantize(cents, ROUND_HALF_EVEN))
            for row in lines
            if row["monthly_amount"] is not None
        ]

    balanced_lines = reprice(estimate["scenarios"]["balanced"]["lines"])
    balanced = sum(amount for _, amount in balanced_lines)
    like = sum(amount for _, amount in reprice(estimate["scenarios"]["like_for_like"]["lines"]))
    compute = set(eligibility["compute_savings_plans"]["aws_services"])
    plan = Decimal(str(rates["rates"]["compute_savings_plan"]["rate"]))
    cap = Decimal(str(rates["service_caps"]["aws_lambda"]["cap"]))
    discount = sum(
        (amount * (min(plan, cap) if service == "AWS Lambda" else plan)).quantize(Decimal(1), ROUND_HALF_EVEN)
        for service, amount in balanced_lines
        if service in compute and amount
    )
    return {"balanced": balanced, "premium": balanced, "optimized": balanced - discount, "like_for_like": like, "delta": like - balanced}


def test_graviton_what_if_scenario_is_re_derived_under_the_tier_rules() -> None:
    """scenario-002 changes only the CPU architecture, so its summary must equal the baseline re-priced
    on arm64 rates under the same tier rules; a stale snapshot (for example one that still carries a
    Database Savings Plan discount) fails, and the report row shows the same figures."""
    estimate = json.loads((EXPECTED / "estimation-infra.json").read_text(encoding="utf-8"))
    expected = _graviton_from_baseline(estimate)
    for path in (WORKSHOP_INDEX, EXPECTED / "workshop-scenarios.json"):
        rows = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
        summary = next(row for row in rows if row["scenario_id"] == "scenario-002")["estimation_summary"]
        assert Decimal(str(summary["balanced_known_cost_monthly_usd"])) == expected["balanced"], path.name
        assert Decimal(str(summary["premium_known_cost_monthly_usd"])) == expected["premium"], path.name
        assert Decimal(str(summary["optimized_known_cost_monthly_usd"])) == expected["optimized"], path.name
        assert Decimal(str(summary["like_for_like_known_cost_monthly_usd"])) == expected["like_for_like"], path.name
        assert Decimal(str(summary["rightsizing_delta_monthly_usd"])) == expected["delta"], path.name
    html = REPORT.read_text(encoding="utf-8")
    graviton = next(row for row in _tbody_rows(_section(html, "what-if-scenarios")) if "Graviton" in row)
    figures = [_whole(expected[key]) for key in ("premium", "balanced", "optimized")]
    assert "<td>${}</td><td>${}</td><td>${}</td>".format(*figures) in graviton, graviton


def test_render_layer_cost_optimization_bullet_matches_step_2_5() -> None:
    """The render layer is loaded for every full-mode report, so its Cost Optimization add-on must give
    the same rules as generate-artifacts-report.md Step 2.5: one row per commitment bucket, a no-saving
    Database Savings Plan row for pre-Generation-7 classes, and the credits caveat once below B.1."""
    layer = (SKILL_ROOT / "references/shared/report-decision-core.md").read_text(encoding="utf-8")
    spec = (SKILL_ROOT / "references/phases/generate/generate-artifacts-report.md").read_text(encoding="utf-8")
    bullet = next(line for line in layer.splitlines() if line.startswith("- **Cost Optimization (`exec-optimization`"))
    step = spec[spec.index("## Step 2.5"):]
    caveat = (
        "promotional or AWS Activate credits do not cover the upfront cost of Reserved Instances or Savings "
        "Plans (Partial or All Upfront) and apply only to the ongoing discounted rate"
    )
    assert caveat in bullet
    assert " ".join(caveat.split()) in " ".join(step.split())
    assert "directly below the B.1 table" in bullet and "directly below the B.1 opportunities table" in " ".join(step.split())
    assert "Generation 7+ gate" in bullet and "Generation 7+ gate" in step
    for stale in ("with eligible lines, per", "carries its discount in dollars", "no credits claim is made", "is replaced by"):
        assert stale not in bullet, stale


def test_missing_appendix_assumptions_section_fails_local_validator(tmp_path: Path) -> None:
    # The render spec requires Appendix I; the shared default `full` set treats it as optional,
    # so only the render-local pass can enforce it.
    root, report = _altered_copy(tmp_path, '<section id="appendix-assumptions">', '<section id="appendix-assumptions-renamed">')
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SECTION_APPENDIX_ASSUMPTIONS_MISSING" in result.stdout + result.stderr
def test_appendix_assumptions_without_toc_link_fails_local_validator(tmp_path: Path) -> None:
    link = '<li><a href="#appendix-assumptions">Appendix I — Assumptions, Exclusions, and Validation</a></li>'
    root, report = _altered_copy(tmp_path, link, "")
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TOC_RENDER_SECTION_MISSING" in result.stdout + result.stderr
