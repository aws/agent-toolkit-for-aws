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

render-to-aws is excluded from the layer check until PR E2 (tier-semantics-render)
converts its layer, which today defines Balanced as the capacity-preserving scenario.
Add "render-to-aws" to LAYER_SKILLS when E2 lands.
"""
from __future__ import annotations

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
