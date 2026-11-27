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

# render-to-aws joins this tuple when PR E2 (tier-semantics-render) lands.
LAYER_SKILLS = ("gcp-to-aws", "azure-to-aws", "heroku-to-aws")

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
