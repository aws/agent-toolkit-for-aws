"""The cost-tier rule is plugin-wide and lives once, in the canonical decision core
(skills/shared/report/report-decision-core.md § Cost Comparison):

- Balanced = the right-sized figure the generated Terraform implements;
- Premium = Balanced plus the Multi-AZ / HA uplift on lines whose HA handling allows it;
- Optimized = Balanced with a mid-point commitment discount on the RI/SP-eligible subtotal only;
- Spot / S3-IA / storage-class assumptions are optimization_opportunities rows, never a tier;
- tiers are pricing scenarios for one design, never different builds.

Skill layers and estimate docs restate the tiers in their own tables and bullets, so
this file pins them to the canonical: the canonical states every definition, no tier
definition row in an owned estimate doc smuggles a consumption-model or storage-class
assumption back in, and no layer's ⟨tier_semantics⟩ row redefines a tier.

render-to-aws is in the layer check: its layer (merged from #790) declares Balanced as the
right-sized design, so every merged state keeps render consistent with the canonical.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = PLUGIN_ROOT / "skills" / "shared" / "report" / "report-decision-core.md"

TIER_DEFINITION_FILES = (
    "skills/shared/report/report-decision-core.md",
    "skills/gcp-to-aws/references/phases/estimate/estimate-infra.md",
    "skills/gcp-to-aws/references/shared/schema-estimate-infra.md",
    "skills/gcp-to-aws/references/phases/generate/generate-artifacts-docs.md",
    "skills/heroku-to-aws/references/phases/estimate/estimate-cost-engine.md",
    "skills/heroku-to-aws/references/phases/estimate/estimate-assemble.md",
    "skills/azure-to-aws/references/phases/estimate/estimate-infra.md",
)

LAYER_SKILLS = ("gcp-to-aws", "azure-to-aws", "heroku-to-aws", "render-to-aws")

# A tier definition row: a table row or a dash bullet whose first cell / token is the
# bold tier name (`| **Premium** |`, `| **\`premium\`** |`, `- **Premium** —`, `- Premium:`).
TIER_ROW_RE = re.compile(
    r"^\s*(?:\|\s*\*\*`?(?:Premium|Balanced|Optimized)`?\*\*\s*\||-\s*\*\*(?:Premium|Balanced|Optimized)\*\*\s*(?:—|=)|-\s*(?:Premium|Balanced|Optimized):)",
    re.IGNORECASE,
)
FORBIDDEN_IN_TIER_ROW_RE = re.compile(
    r"\bSpot\b|S3-IA|Infrequent Access|Intelligent-Tiering|latest[- ]gen|trade-offs assumed",
    re.IGNORECASE,
)
FORBIDDEN_IN_LAYER_RE = re.compile(
    r"capacity-preserving|\bbounds\b|\bSpot\b|trade-offs assumed|newer skew",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def _section(text: str, heading_prefix: str) -> str:
    start = text.index(heading_prefix)
    nxt = text.find("\n## ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def test_canonical_states_the_three_tier_definitions():
    cost = _section(_read(CANONICAL), "## Cost Comparison")
    for phrase in (
        "right-sized",
        "Multi-AZ / HA uplift",
        "RI/SP-eligible subtotal",
        "mid-point",
        "`optimization_opportunities[]`",
        "never different builds",
    ):
        assert phrase in cost, f"canonical § Cost Comparison no longer states: {phrase}"
    assert "a mapping, not a redefinition" in cost, (
        "⟨tier_semantics⟩ must be declared as a key mapping, not a redefinition"
    )


@pytest.mark.parametrize("rel", TIER_DEFINITION_FILES)
def test_tier_definition_rows_carry_no_consumption_or_storage_assumption(rel: str):
    text = _read(PLUGIN_ROOT / rel)
    rows = [(n, line) for n, line in enumerate(text.splitlines(), 1) if TIER_ROW_RE.match(line)]
    assert rows, f"{rel}: expected at least one Premium / Balanced / Optimized definition row"
    bad = [(n, line) for n, line in rows if FORBIDDEN_IN_TIER_ROW_RE.search(line)]
    assert not bad, f"{rel}: tier definition rows restate a non-tier assumption: {bad}"


@pytest.mark.parametrize("skill", LAYER_SKILLS)
def test_layer_tier_semantics_declares_keys_and_does_not_redefine(skill: str):
    layer = PLUGIN_ROOT / "skills" / skill / "references" / "shared" / "report-decision-core.md"
    rows = [line for line in _read(layer).splitlines() if "⟨tier_semantics⟩" in line]
    assert rows, f"{skill}: layer does not supply ⟨tier_semantics⟩"
    for row in rows:
        assert "aws_monthly_balanced" in row, f"{skill}: ⟨tier_semantics⟩ must name the Balanced key"
        hit = FORBIDDEN_IN_LAYER_RE.search(row)
        assert not hit, f"{skill}: ⟨tier_semantics⟩ redefines a tier ({hit.group(0)!r}): {row}"


SHARED_RATES = PLUGIN_ROOT / "skills" / "shared" / "estimate" / "commitment-discount-ranges.json"
VENDORED_RATES_SKILLS = ("gcp-to-aws", "azure-to-aws", "heroku-to-aws", "render-to-aws")
# Every estimate artifact this series re-derived, plus azure's (already on the rule).
TIERED_ESTIMATES = (
    "fixtures/estimation-infra-reference.json",
    "fixtures/gcp-decision-gate/after-decide-complete/estimation-infra.json",
    "fixtures/heroku-decision-gate/after-decide-complete/estimation-infra.json",
    "fixtures/heroku-decision-gate/retained-execution-pack/estimation-infra.json",
    "fixtures/azure-iac-terraform/after-estimate/estimation-infra.json",
    "skills/render-to-aws/fixtures/expected/estimation-infra.json",
    "fixtures/gcp-workshop/seed/estimation-infra.json",
    "fixtures/gcp-workshop/after-graviton-reprice/estimation-infra.json",
    "fixtures/heroku-workshop/seed/estimation-infra.json",
    "fixtures/heroku-workshop/after-arm64-reprice/estimation-infra.json",
)


def test_shared_commitment_rates_are_the_single_tier_source():
    """One shared file carries the Optimized tier rates; every skill vendors it and the
    canonical and the three estimate docs point at it rather than restating a number."""
    import json

    rates = json.loads(_read(SHARED_RATES))["rates"]
    assert rates["compute_savings_plan"]["rate"] == 0.30
    assert rates["database_savings_plan_provisioned"]["rate"] == 0.20
    for skill in VENDORED_RATES_SKILLS:
        vendored = PLUGIN_ROOT / "skills" / skill / "references" / "vendored" / "estimate" / "commitment-discount-ranges.json"
        assert vendored.is_file(), f"{skill} does not vendor commitment-discount-ranges.json"
        assert vendored.read_bytes() == SHARED_RATES.read_bytes(), f"{skill} vendored rates drifted"
    assert "commitment-discount-ranges.json" in _section(_read(CANONICAL), "## Cost Comparison")
    for rel in (
        "skills/gcp-to-aws/references/phases/estimate/estimate-infra.md",
        "skills/heroku-to-aws/references/phases/estimate/estimate-cost-engine.md",
        "skills/azure-to-aws/references/phases/estimate/estimate-infra.md",
    ):
        text = _read(PLUGIN_ROOT / rel)
        rows = [line for line in text.splitlines() if TIER_ROW_RE.match(line) and "Optimized" in line]
        assert rows and all("commitment-discount-ranges.json" in r for r in rows), (
            f"{rel}: the Optimized tier row must take its rate from the vendored shared file"
        )
    # No skill keeps a private copy of the tier rate.
    for skill in VENDORED_RATES_SKILLS:
        defaults = PLUGIN_ROOT / "skills" / skill / "knowledge" / "estimate" / "estimate-defaults.json"
        if defaults.is_file():
            assert "optimized_tier_discounts" not in defaults.read_text(encoding="utf-8"), (
                f"{skill}: tier rates belong in the shared file, not estimate-defaults.json"
            )


def test_canonical_requires_an_explanation_when_tier_figures_are_equal():
    cost = _section(_read(CANONICAL), "## Cost Comparison")
    for phrase in (
        "When two or three tier figures are equal, say why where the reader sees them",
        "Premium equals Balanced because every line that can take a resilience uplift is already multi-AZ",
        "Optimized equals Balanced because none of the priced lines is eligible for a commitment discount",
        "never pad a tier with an artificial delta",
    ):
        assert phrase in cost, f"canonical § Cost Comparison no longer states: {phrase}"


@pytest.mark.parametrize("rel", TIERED_ESTIMATES)
def test_tier_figures_are_ordered_and_explained(rel: str):
    """Premium ≥ Balanced ≥ Optimized always holds under the rule (uplift adds, discount
    subtracts). Each derived tier carries its `_basis` sentence, and an equal pair is
    explained there rather than left as a bare coincidence."""
    import json

    pc = json.loads(_read(PLUGIN_ROOT / rel))["projected_costs"]
    premium, balanced, optimized = (pc["aws_monthly_premium"], pc["aws_monthly_balanced"], pc["aws_monthly_optimized"])
    assert premium >= balanced >= optimized, f"{rel}: tiers out of order {premium}/{balanced}/{optimized}"
    assert pc.get("_premium_basis") and pc.get("_optimized_basis"), f"{rel}: derived tiers need a _basis sentence"
    if premium == balanced:
        assert re.search(r"uplift", pc["_premium_basis"], re.IGNORECASE), f"{rel}: Premium equals Balanced without saying why"
    if optimized == balanced:
        assert re.search(r"eligible", pc["_optimized_basis"], re.IGNORECASE), f"{rel}: Optimized equals Balanced without saying why"


def test_shared_rates_cap_services_below_their_product_rate():
    """AWS publishes a lower maximum for Lambda duration (Compute Savings Plan, 1-year No Upfront
    11.8% x86 / 12.2% arm64 per the price list; 17% is the All Upfront rate) and for
    DynamoDB / Keyspaces (Database Savings Plan, up to 18% on-demand and 12% provisioned)
    than the 0.30 / 0.20 product rates. The tier must apply min(rate, cap), so the caps are
    data in the shared file, each with a source."""
    import json

    data = json.loads(_read(SHARED_RATES))
    caps = data["service_caps"]
    products = {"compute_savings_plan": data["rates"]["compute_savings_plan"]["rate"],
                "database_savings_plan_provisioned": data["rates"]["database_savings_plan_provisioned"]["rate"]}
    expected = {"aws_lambda": 0.12, "dynamodb_and_keyspaces_on_demand_throughput": 0.18,
                "dynamodb_and_keyspaces_provisioned_capacity": 0.12}
    for key, cap in expected.items():
        entry = caps[key]
        assert entry["cap"] == cap, f"{key}: cap {entry['cap']} != published {cap}"
        assert entry["cap"] < products[entry["product"]], f"{key}: a cap at or above the product rate caps nothing"
        if key == "aws_lambda":
            assert "pricing.us-east-1.amazonaws.com/savingsPlan/v1.0/aws/AWSComputeSavingsPlan/20261124130343" in entry["source"]
            assert "2026-11-24" in entry["source"] and "$0.0000147" in entry["source"]
            assert "requests" in entry["applies_to_charge"].lower() and "no savings plan discount" in entry["applies_to_charge"].lower()
        else:
            assert "https://aws.amazon.com/blogs/aws/" in entry["source"], f"{key}: cap needs a primary-source URL"
    assert "min(product rate, service cap)" in data["midpoint_rule"]


@pytest.mark.parametrize("rel", TIERED_ESTIMATES)
def test_optimized_basis_does_not_cite_a_removed_rate_source(rel: str):
    """The per-skill `optimized_tier_discounts` block was removed in favour of the shared
    rate file; a fixture basis that still cites it points readers at a file that no longer
    holds the rate."""
    import json

    basis = json.loads(_read(PLUGIN_ROOT / rel))["projected_costs"]["_optimized_basis"]
    assert "optimized_tier_discounts" not in basis, f"{rel}: _optimized_basis cites a removed rate source"
    assert "estimate-defaults.json" not in basis, f"{rel}: _optimized_basis cites estimate-defaults.json for a tier rate"


# --- Database Savings Plan Generation 7+ gate -------------------------------------------
GATE_ROWS = {
    "skills/gcp-to-aws/references/phases/estimate/estimate-infra.md": "gcp",
    "skills/heroku-to-aws/references/phases/estimate/estimate-cost-engine.md": "heroku",
    "skills/azure-to-aws/references/phases/estimate/estimate-infra.md": "azure",
}
# Optimized per fixture, derived in code from the eligible subtotal under the gate:
# only Compute-SP lines are eligible today because every DB / cache class is pre-Generation-7.
EXPECTED_OPTIMIZED = {
    "fixtures/estimation-infra-reference.json": 105,
    "fixtures/gcp-decision-gate/after-decide-complete/estimation-infra.json": 140,
    "fixtures/heroku-decision-gate/after-decide-complete/estimation-infra.json": 182,
    "fixtures/heroku-decision-gate/retained-execution-pack/estimation-infra.json": 182,
    "fixtures/azure-iac-terraform/after-estimate/estimation-infra.json": 451.13,
}


def test_database_sp_generation_gate_is_stated_where_the_rule_lives():
    """AWS Database Savings Plans cover Generation 7 and newer instances only (Valkey only for
    ElastiCache; AWS Savings Plans FAQ, read 2026-11-27). The shared rate file, the eligibility
    matrix (and gcp's own copy), the canonical Optimized definition and every skill's Optimized
    row state it."""
    import json
    data = json.loads(_read(SHARED_RATES))
    gate = data["generation_gate"]
    assert gate["minimum_generation"] == 7
    assert "https://aws.amazon.com/savingsplans/faq/" in gate["source"] and "2026-11-27" in gate["source"]
    assert "Valkey" in gate["elasticache_engine"] and "INELIGIBLE" in gate["how_to_read_generation"]
    for rel in ("skills/shared/estimate/ri-sp-eligibility.md", "skills/gcp-to-aws/references/shared/ri-sp-eligibility.md"):
        text = _read(PLUGIN_ROOT / rel)
        assert "Generation 7 and newer" in text and "do not assert a specific" not in " ".join(text.split()), rel
    assert (PLUGIN_ROOT / "skills/shared/estimate/ri-sp-eligibility.md").read_bytes() == (
        PLUGIN_ROOT / "skills/gcp-to-aws/references/shared/ri-sp-eligibility.md"
    ).read_bytes()
    assert "Generation 7 or newer" in _section(_read(CANONICAL), "## Cost Comparison")
    for rel in GATE_ROWS:
        rows = [ln for ln in _read(PLUGIN_ROOT / rel).splitlines() if TIER_ROW_RE.match(ln) and "Optimized" in ln]
        assert rows and all("Generation 7" in r for r in rows), f"{rel}: Optimized row lacks the Generation 7+ gate"


@pytest.mark.parametrize("rel", sorted(EXPECTED_OPTIMIZED))
def test_tiered_fixtures_apply_the_generation_gate(rel: str):
    import json
    pc = json.loads(_read(PLUGIN_ROOT / rel))["projected_costs"]
    assert pc["aws_monthly_optimized"] == EXPECTED_OPTIMIZED[rel], f"{rel}: Optimized figure stale"
    basis = pc["_optimized_basis"]
    assert "Generation 7" in basis and re.search(r"ineligible", basis, re.IGNORECASE), f"{rel}: basis must say the DB/cache line is ineligible and why"
    assert "Database Savings Plan ~20% provisioned" not in basis
    if "aws_annual_optimized" in pc:
        assert round(pc["aws_annual_optimized"], 2) == round(pc["aws_monthly_optimized"] * 12, 2)
    for text in pc.get("scenario_deltas", {}).get("optimized", []):
        assert "on RDS at ~20% (-$3/mo)" not in text


def test_gcp_optimized_row_covers_every_eligible_target_gcp_designs():
    """gcp maps Memorystore to ElastiCache (Valkey) and Firestore/Datastore to DynamoDB, both
    Database-SP eligible, so the Optimized row names them, with DynamoDB's caps and the
    Generation 7+ gate, and excludes Redis OSS / Memcached."""
    text = _read(PLUGIN_ROOT / "skills/gcp-to-aws/references/phases/estimate/estimate-infra.md")
    row = next(ln for ln in text.splitlines() if TIER_ROW_RE.match(ln) and "Optimized" in ln)
    assert "ElastiCache **for Valkey**" in row and "Redis OSS and Memcached excluded" in row
    assert "DynamoDB (Firestore / Datastore targets)" in row and "service_caps" in row
    assert "0.18 on-demand throughput, 0.12 provisioned capacity" in row
    assert "Generation 7+ gate" in row and "Generation 7 or newer" in row
    deltas = next(ln for ln in text.splitlines() if ln.startswith("**Itemize the scenario deltas"))
    assert "ElastiCache for Valkey" in deltas and "DynamoDB" in deltas


def test_canonical_flags_estimates_without_a_tier_basis_and_generate_offers_a_rerun():
    """An estimation-infra.json from before the tier rule has no _premium_basis /
    _optimized_basis. Resumed straight into Generate, its report would describe the old
    figures with the new definitions, so the canonical tells the report to say they predate
    the rule, and each skill's Generate entry offers an Estimate re-run."""
    cost = _section(_read(CANONICAL), "## Cost Comparison")
    for phrase in (
        "Estimates written before this rule (no tier basis)",
        "`projected_costs._premium_basis` or `projected_costs._optimized_basis` is absent",
        "produced under the earlier tier definitions",
        "recommend re-running Estimate",
        "must NOT restate the derivations above as if they applied",
    ):
        assert phrase in cost, f"canonical no longer states: {phrase}"
    for rel in (
        "skills/gcp-to-aws/references/phases/generate/generate.md",
        "skills/heroku-to-aws/references/phases/generate/generate.md",
        "skills/azure-to-aws/references/phases/generate/generate.md",
    ):
        text = _read(PLUGIN_ROOT / rel)
        assert "_optimized_basis" in text and "earlier tier definitions" in text and "re-run" in text.lower(), rel
    # render writes both basis fields from its scenarios, so the rule never fires on a fresh
    # render report: the committed fixture carries them, and the estimate spec says Estimate
    # always writes them.
    render_estimate = json.loads(_read(PLUGIN_ROOT / "skills/render-to-aws/fixtures/expected/estimation-infra.json"))
    pc = render_estimate["projected_costs"]
    assert pc.get("_premium_basis") and pc.get("_optimized_basis"), "render fixture lacks the tier basis fields"
    render_spec = _read(PLUGIN_ROOT / "skills/render-to-aws/references/phases/estimate/estimate-infra.md")
    assert "`_premium_basis`" in render_spec and "`_optimized_basis`" in render_spec, "render Estimate does not write the tier basis"


def test_azure_generate_report_teaches_the_canonical_tier_meanings():
    html = _read(PLUGIN_ROOT / "fixtures/azure-iac-terraform/after-generate/migration-report.html")
    for phrase in (
        "Balanced plus the Multi-AZ / HA uplift",
        "Right-sized design at on-demand rates; compare Azure to this row first",
        "Balanced with a commitment discount on RI/SP-eligible lines",
        "is the right-sized design at on-demand rates",
        "is Balanced plus the Multi-AZ / HA uplift",
        "is Balanced with a commitment discount on the RI/SP-eligible lines only",
    ):
        assert phrase in " ".join(html.split()).replace("<strong>", "").replace("</strong>", ""), f"azure report lacks: {phrase}"
    for stale in ("Highest resilience / highest monthly estimate", "Default scenario", "Premium and Optimized are bounds"):
        assert stale not in html, f"azure report still teaches: {stale}"



def test_heroku_part6_database_savings_plan_rule_applies_the_generation_gate():
    """The Part 6 opportunity rule must use the same Generation 7+ gate as the Optimized tier row, so a
    real estimate for a pre-Generation-7 RDS class never lists a Database Savings Plan saving that the
    report then calls ineligible."""
    text = _read(PLUGIN_ROOT / "skills/heroku-to-aws/references/phases/estimate/estimate-cost-engine.md")
    start = text.index("### Database Savings Plans (when RDS/Aurora")
    section = text[start : text.index("\n### ", start + 1)]
    assert "Generation 7+ gate" in section
    assert "`savings_monthly: null`" in section
    assert "eligible when the instance class passes the Generation 7+ gate" in section
    assert "no target_services instance passes the Generation 7+ gate" in section


def test_fixtures_readme_heroku_generate_tiers_match_the_golden():
    import json

    pc = json.loads(_read(PLUGIN_ROOT / "fixtures/heroku-generate/after-generate/estimation-infra.json"))["projected_costs"]
    tiers = "/".join(str(int(pc[key])) for key in ("aws_monthly_premium", "aws_monthly_balanced", "aws_monthly_optimized"))
    assert f"tiers {tiers}" in _read(PLUGIN_ROOT / "fixtures/README.md")
