"""The public Azure discovery summary must match the sources Discover actually reads.

PR #458 made a customer-supplied RDfA report a real Discover producer and stated
that Azure Cost Management billing-export discovery is not implemented. The
skill description and the plugin README still described the old set (Terraform,
live `az`, app code, and billing exports) and never named RDfA.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL = PLUGIN_ROOT / "skills" / "azure-to-aws" / "SKILL.md"
README = PLUGIN_ROOT / "README.md"


def test_skill_summary_names_rdfa_and_not_billing_exports() -> None:
    text = SKILL.read_text(encoding="utf-8")
    description = text.split("---", 2)[1]
    defaults = text[text.index("## Defaults"):text.index("## Scope Notes")]

    assert "RDfA" in description
    assert "app code, and billing exports" not in description
    assert "billing-export discovery is not implemented" in description
    assert "RDfA archive parsing" in defaults
    assert "billing exports as a fallback" not in defaults
    assert "billing exports are not implemented" in defaults


def test_plugin_readme_names_rdfa_for_azure_only() -> None:
    text = README.read_text(encoding="utf-8")
    azure_row = next(
        line for line in text.splitlines() if line.startswith("| 4 | `azure-to-aws` |")
    )
    discover = text[text.index("- **Discover** —"):text.index("- **Clarify** —")]
    azure_clause = discover.split("`gcp-to-aws`", 1)[0]

    assert "RDfA" in azure_row
    assert "and billing exports" not in azure_row
    assert "not Bicep, ARM templates, or Azure billing exports" in azure_row
    assert "RDfA" in azure_clause
    assert "billing exports" not in azure_clause.replace("Azure billing exports", "")
    # GCP still reads billing exports. Only the Azure clause changed.
    assert "`gcp-to-aws` reads Terraform, application code, and billing exports" in discover
