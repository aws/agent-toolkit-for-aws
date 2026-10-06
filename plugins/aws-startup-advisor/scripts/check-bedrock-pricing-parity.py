#!/usr/bin/env python3
"""Prove the Bedrock pricing split preserves the pre-split data and behavior.

Run from anywhere:
    python3 plugins/aws-startup-advisor/scripts/check-bedrock-pricing-parity.py

The immutable pre-split comparison point is the stacked PR #387 head on which this
branch was created. The check uses only the standard library and local git data.
"""
from __future__ import annotations

import __future__
import json
import re
import subprocess
import tempfile
import types
from pathlib import Path

BASE_SHA = "9e60fce74ff65ef4752dd2c4a1ae0a0bca6007a8"
PLUGIN = Path(__file__).resolve().parent.parent
REPO = PLUGIN.parents[1]
OLD_CACHE = "plugins/aws-startup-advisor/skills/gcp-to-aws/references/shared/pricing-cache.md"
OLD_SCRIPT = "plugins/aws-startup-advisor/skills/llm-to-bedrock/scripts/bedrock_pricing.py"
OLD_SKILL = "plugins/aws-startup-advisor/skills/gcp-to-aws/SKILL.md"
CANONICAL = PLUGIN / "skills/shared/ai/bedrock-pricing-cache.md"
GCP_CACHE = PLUGIN / "skills/gcp-to-aws/references/shared/pricing-cache.md"
GCP_SKILL = PLUGIN / "skills/gcp-to-aws/SKILL.md"
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
    for line in section(text, "Bedrock Models (On-Demand)").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or "." not in cells[1]:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", cells[3]) and re.fullmatch(r"\d+(?:\.\d+)?", cells[4]):
            rows[cells[1]] = (cells[3], cells[4])
    return rows


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
    old_accuracy = pricing_accuracy_bands(git_show(OLD_SKILL))
    new_accuracy = pricing_accuracy_bands(GCP_SKILL.read_text())

    assert new_accuracy == old_accuracy, "estimate accuracy metadata changed"

    old_bedrock = section(old, "Bedrock Models (On-Demand)")
    new_bedrock = section(canonical, "Bedrock Models (On-Demand)")
    assert new_bedrock.rstrip() == old_bedrock.rstrip(), "Bedrock section changed during extraction"
    assert metadata(canonical) == metadata(old), "freshness/source metadata changed"

    for heading in (
        "Compute", "Database", "Storage", "Networking", "Supporting Services",
        "Analytics", "Source Provider Pricing (for Migration Comparison)", "Security Baseline",
    ):
        assert section(remaining, heading) == section(old, heading), f"non-Bedrock section changed: {heading}"
    assert "## Bedrock Models (On-Demand)" not in remaining
    assert "references/vendored/ai/bedrock-pricing-cache.md" in remaining

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
