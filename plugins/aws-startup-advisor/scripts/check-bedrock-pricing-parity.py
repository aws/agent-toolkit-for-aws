#!/usr/bin/env python3
"""Prove the Bedrock pricing split preserves the pre-split data and behavior.

Run from anywhere:
    python3 plugins/aws-startup-advisor/scripts/check-bedrock-pricing-parity.py

The immutable pre-split comparison point was originally the stacked PR #387 head on
which this branch was created. It was bumped to upstream's 2026-10-05 pricing-cache
refresh commit (#408) so the "preserve pre-split behavior" check compares against
content that already includes both the Nova Canvas/Nova Reel EOL wording fix (#409)
and the Oct 5 refresh — the Sep 3 snapshot never had either, so comparing against it
would flag legitimate upstream data changes as regressions. The check uses only the
standard library and local git data.
"""
from __future__ import annotations

import __future__
import json
import re
import subprocess
import tempfile
import types
from pathlib import Path

BASE_SHA = "883270642209b06e1e76dcc4f944a1174abf0675"
PLUGIN = Path(__file__).resolve().parent.parent
REPO = PLUGIN.parents[1]
OLD_CACHE = "plugins/aws-startup-advisor/skills/gcp-to-aws/references/shared/pricing-cache.md"
OLD_SCRIPT = "plugins/aws-startup-advisor/skills/llm-to-bedrock/scripts/bedrock_pricing.py"
OLD_SKILL = "plugins/aws-startup-advisor/skills/gcp-to-aws/SKILL.md"
OLD_AZURE_CACHE = "plugins/aws-startup-advisor/skills/azure-to-aws/references/shared/pricing-cache.md"
CANONICAL = PLUGIN / "skills/shared/ai/bedrock-pricing-cache.md"
GCP_CACHE = PLUGIN / "skills/gcp-to-aws/references/shared/pricing-cache.md"
GCP_SKILL = PLUGIN / "skills/gcp-to-aws/SKILL.md"
GCP_ESTIMATE = PLUGIN / "skills/gcp-to-aws/references/phases/estimate/estimate.md"
GCP_ESTIMATE_AI = PLUGIN / "skills/gcp-to-aws/references/phases/estimate/estimate-ai.md"
AZURE_CACHE = PLUGIN / "skills/azure-to-aws/references/shared/pricing-cache.md"
AZURE_ESTIMATE = PLUGIN / "skills/azure-to-aws/references/phases/estimate/estimate.md"
AZURE_ESTIMATE_AI = PLUGIN / "skills/azure-to-aws/references/phases/estimate/estimate-ai.md"
AZURE_OPENAI = PLUGIN / "skills/azure-to-aws/references/shared/openai-on-bedrock.md"
VENDORED = (
    PLUGIN / "skills/gcp-to-aws/references/vendored/ai/bedrock-pricing-cache.md",
    PLUGIN / "skills/azure-to-aws/references/vendored/ai/bedrock-pricing-cache.md",
    PLUGIN / "skills/agent-advisor/references/vendored/ai/bedrock-pricing-cache.md",
)


def git_show(path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{BASE_SHA}:{path}"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def section(text: str, heading: str) -> str:
    match = re.search(rf"(?m)^## {re.escape(heading)}.*$", text)
    assert match, f"missing section: {heading}"
    end = re.search(r"(?m)^## ", text[match.end() :])
    stop = match.end() + end.start() if end else len(text)
    return text[match.start() : stop]


def metadata(text: str) -> dict[str, str]:
    fields = {}
    for key in ("Last updated", "Region", "Currency", "Accuracy"):
        match = re.search(rf"(?m)^\*\*{re.escape(key)}:\*\*\s*(.+)$", text)
        assert match, f"missing metadata: {key}"
        fields[key] = match.group(1)
    return fields


def model_rows(text: str) -> dict[str, tuple[str, str]]:
    rows = {}
    bedrock_section = section(text, "Bedrock Models (On-Demand)")
    # Exclude the "### Embeddings — Bedrock" subsection: it is an input-only table (price,
    # Dimensions) rather than this scanner's assumed input/output price-pair shape, and
    # three of its five Dimensions values (single numbers like "1536") coincidentally pass
    # the same numeric fullmatch as a real output price, which would otherwise mix
    # embedding rows into the generative-model lookup-key comparison below.
    embed_match = re.search(r"(?m)^### Embeddings — Bedrock.*$", bedrock_section)
    if embed_match:
        embed_end = re.search(r"(?m)^### ", bedrock_section[embed_match.end() :])
        stop = embed_match.end() + embed_end.start() if embed_end else len(bedrock_section)
        bedrock_section = bedrock_section[: embed_match.start()] + bedrock_section[stop:]
    for line in bedrock_section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or "." not in cells[1]:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", cells[3]) and re.fullmatch(r"\d+(?:\.\d+)?", cells[4]):
            rows[cells[1]] = (cells[3], cells[4])
    return rows


def markdown_data_rows(text: str) -> list[str]:
    """Return table data rows while excluding separators and headers."""
    return [
        line
        for line in text.splitlines()
        if line.startswith("|")
        and not re.match(r"^\|[\s:-]+\|", line)
        and not line.startswith("| Model ")
    ]


def pricing_accuracy_bands(text: str) -> tuple[str, str]:
    line = next(
        (line for line in text.splitlines() if line.startswith("- Primary pricing source")),
        None,
    )
    assert line, "missing primary pricing source contract"
    bands = re.findall(r"±\d+-\d+%", line)
    assert len(bands) == 2, "expected infrastructure and AI pricing accuracy bands"
    return bands[0], bands[1]


def load_module(path: Path, name: str):
    module = types.ModuleType(name)
    code = compile(
        path.read_text(),
        str(path),
        "exec",
        flags=__future__.annotations.compiler_flag,
    )
    exec(code, module.__dict__)
    return module


def pricing_behavior(module) -> dict:
    fragment = {
        "terms": {"OnDemand": {"x": {"priceDimensions": {
            "input": {"pricePerUnit": {"USD": "0.003"}, "description": "Input tokens"},
            "output": {"pricePerUnit": {"USD": "0.015"}, "description": "Output tokens"},
            "cache": {"pricePerUnit": {"USD": "0.0003"}, "description": "Cache read input tokens"},
        }}}}}
    probes = sorted(module.STATIC_FALLBACK) + [
        "anthropic.claude-opus-4-8" + "-20250610-v1:0",
        "us.anthropic.claude-sonnet-4-6" + "-20250514-v1:0",
        "openai.gpt-5.6",
    ]
    return {
        "table": module.STATIC_FALLBACK,
        "parse": module.parse_price_dimensions(fragment),
        "unavailable": module.unavailable("parity probe"),
        "display": module.display_name_guess("us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        "mantle": [module.is_mantle_gpt(x) for x in ("openai.gpt-5.6-luna", "openai.gpt-oss-120b-1:0")],
        "fallbacks": {probe: module._static_fallback(probe) for probe in probes},
        "lookups": {probe: module.lookup("us-east-1", probe) for probe in probes if module._static_fallback(probe)},
    }


def main() -> int:
    old = git_show(OLD_CACHE)
    canonical = CANONICAL.read_text()
    remaining = GCP_CACHE.read_text()
    gcp_estimate = GCP_ESTIMATE.read_text()
    gcp_estimate_ai = GCP_ESTIMATE_AI.read_text()
    azure_old = git_show(OLD_AZURE_CACHE)
    azure_cache = AZURE_CACHE.read_text()
    azure_estimate = AZURE_ESTIMATE.read_text()
    azure_estimate_ai = AZURE_ESTIMATE_AI.read_text()
    azure_openai = AZURE_OPENAI.read_text()
    old_accuracy = pricing_accuracy_bands(git_show(OLD_SKILL))
    new_accuracy = pricing_accuracy_bands(GCP_SKILL.read_text())

    assert new_accuracy == old_accuracy, "estimate accuracy metadata changed"

    old_bedrock = section(old, "Bedrock Models (On-Demand)")
    new_bedrock = section(canonical, "Bedrock Models (On-Demand)")
    # The GCP-origin "## Bedrock Models (On-Demand)" section itself nests the
    # "### Embeddings — Bedrock" subsection reinstated below (it was previously only in
    # Azure's cache, under the same heading level, and was lost entirely during the
    # original split). Strip exactly that known, reviewed addition before the
    # byte-equality check, the same way the Claude Fable exception below is scoped to one
    # named, reviewed change rather than widened wholesale.
    new_bedrock_without_embeddings = re.sub(
        r"(?s)### Embeddings — Bedrock \(per 1M input tokens, US East\).*?(?=### Stability AI)",
        "",
        new_bedrock,
    )
    assert new_bedrock_without_embeddings.rstrip() == old_bedrock.rstrip(), "Bedrock section changed during extraction"
    old_metadata = metadata(old)
    canonical_metadata = metadata(canonical)
    for field in ("Last updated", "Region", "Currency"):
        assert canonical_metadata[field] == old_metadata[field], f"Bedrock {field} metadata changed"
    assert canonical_metadata["Accuracy"].startswith("±15-25% for AI/Bedrock")
    assert "±5-10%" not in canonical_metadata["Accuracy"]
    assert "other services in this file" not in canonical
    assert "infrastructure services" not in canonical_metadata["Accuracy"]

    for heading in (
        "Compute", "Database", "Storage", "Networking", "Supporting Services",
        "Analytics", "Source Provider Pricing (for Migration Comparison)", "Security Baseline",
    ):
        assert section(remaining, heading) == section(old, heading), f"non-Bedrock section changed: {heading}"
    assert "## Bedrock Models (On-Demand)" not in remaining
    assert "references/vendored/ai/bedrock-pricing-cache.md" in remaining
    assert metadata(remaining)["Accuracy"].startswith("±5-10%")
    assert "±15-25%" not in metadata(remaining)["Accuracy"]
    assert "Bedrock subsection" not in remaining
    assert "Amazon Nova" not in remaining[: remaining.index("## Compute")]
    assert "±5-25%" not in gcp_estimate
    assert "infrastructure/source-provider cache (updated [date], ±5-10%)" in gcp_estimate
    assert "Bedrock cache (updated [date], ±15-25%)" in gcp_estimate
    assert "a `references/vendored/ai/bedrock-pricing-cache.md` cell marked `_unverified_`" in gcp_estimate_ai

    assert "references/vendored/ai/bedrock-pricing-cache.md" in azure_estimate
    assert "references/vendored/ai/bedrock-pricing-cache.md` (primary for Bedrock)" in azure_estimate_ai
    assert "`shared/pricing-cache.md` (primary for source providers)" in azure_estimate_ai
    assert "## Bedrock Models (On-Demand)" not in azure_cache
    # Scoped to a reinstated Bedrock model row/recommendation sentence, not the whole
    # file: the Oct 5 refresh's "Last updated" provenance note (reproduced verbatim
    # from upstream per the metadata equality check below) legitimately names
    # "Claude Fable 5" while listing which models' rates it re-verified unchanged —
    # that is not the deleted Bedrock section leaking back in.
    assert "| Claude Fable" not in azure_cache
    assert "default to Claude Fable" not in azure_cache
    assert metadata(azure_cache)["Last updated"] == metadata(azure_old)["Last updated"]
    assert markdown_data_rows(section(azure_cache, "Source Provider Pricing (for Migration Comparison)")) == markdown_data_rows(section(azure_old, "Source Provider Pricing (for Migration Comparison)")), "Azure source-provider rate rows changed"
    assert "any Bedrock rate change into\n   `references/vendored/ai/bedrock-pricing-cache.md`" in azure_openai

    # The pre-split Azure cache's own "Embeddings — Bedrock" target table (Titan/Cohere) is
    # NOT part of GCP's "Bedrock Models (On-Demand)" section the checks above already cover,
    # so a prior split silently dropped it entirely instead of moving it to the canonical
    # cache. Prove every target row survived the move byte-for-byte and that each embedding
    # model ID is still reachable from the canonical cache's own quick-reference rows.
    def subsection(text: str, heading: str) -> str:
        """Like `section()` but for a `### ` subsection nested inside a `## ` section."""
        match = re.search(rf"(?m)^### {re.escape(heading)}.*$", text)
        assert match, f"missing subsection: {heading}"
        end = re.search(r"(?m)^#{2,3} ", text[match.end() :])
        stop = match.end() + end.start() if end else len(text)
        return text[match.start() : stop]

    azure_old_embed_rows = markdown_data_rows(subsection(azure_old, "Embeddings — Bedrock"))
    assert azure_old_embed_rows, "pre-split Azure cache's Embeddings — Bedrock table is missing; nothing to compare against"
    canonical_embed_rows = markdown_data_rows(subsection(canonical, "Embeddings — Bedrock"))
    assert canonical_embed_rows == azure_old_embed_rows, "Bedrock embedding target rows were not preserved during the split"
    for vendored_copy in VENDORED:
        assert markdown_data_rows(subsection(vendored_copy.read_text(), "Embeddings — Bedrock")) == azure_old_embed_rows, (
            f"Bedrock embedding target rows drifted in vendored copy: {vendored_copy}"
        )

    canonical_bytes = CANONICAL.read_bytes()
    for copy in VENDORED:
        assert copy.read_bytes() == canonical_bytes, f"vendored drift: {copy}"

    old_rows = model_rows(old)
    new_rows = model_rows(canonical)
    assert new_rows == old_rows and new_rows, "model lookup keys or quick-reference rates changed"
    volumes = (60, 40)
    representative = (
        "anthropic.claude-sonnet-5",
        "amazon.nova-pro-v1:0",
        "openai.gpt-5.6-luna",
    )
    old_estimates = {
        model: volumes[0] * float(old_rows[model][0]) + volumes[1] * float(old_rows[model][1])
        for model in representative
    }
    new_estimates = {
        model: volumes[0] * float(new_rows[model][0]) + volumes[1] * float(new_rows[model][1])
        for model in representative
    }
    assert new_estimates == old_estimates, "representative estimate outputs changed"

    current_script = PLUGIN / "skills/llm-to-bedrock/scripts/bedrock_pricing.py"
    with tempfile.TemporaryDirectory() as tmp:
        old_script = Path(tmp) / "bedrock_pricing_before.py"
        old_script.write_text(git_show(OLD_SCRIPT))
        before = load_module(old_script, "bedrock_pricing_before")
        after = load_module(current_script, "bedrock_pricing_after")
        assert pricing_behavior(after) == pricing_behavior(before), "pricing parser/lookup behavior changed"

    forbidden = "skills/gcp-to-aws/references/shared/pricing-cache.md"
    neutral_consumers = (
        PLUGIN / "skills/llm-to-bedrock/scripts/bedrock_pricing.py",
        PLUGIN / "skills/llm-to-bedrock/scripts/test_bedrock_pricing.py",
        PLUGIN / "skills/agent-advisor/references/phases/estimate/estimate.md",
        PLUGIN / "skills/agent-advisor/references/decision-refs/freshness.md",
    )
    for consumer in neutral_consumers:
        assert forbidden not in consumer.read_text(), f"neutral GCP pricing dependency remains: {consumer}"

    print(json.dumps({
        "status": "PASS",
        "bedrock_model_lookup_keys": len(new_rows),
        "static_fallback_keys": len(pricing_behavior(after)["table"]),
        "representative_monthly_estimates": new_estimates,
        "pricing_accuracy_bands": {
            "infrastructure": new_accuracy[0],
            "ai_models": new_accuracy[1],
        },
        "vendored_copies": len(VENDORED),
        "baseline": BASE_SHA,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
