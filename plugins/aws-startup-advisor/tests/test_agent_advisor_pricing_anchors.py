"""agent-advisor Estimate pricing anchors carry a current date and agree with the runtime facts.

`estimate.md` marks `pricing_source: cached_stale` when its cached rate table is more than 90 days
old. The table said "last updated 2025-07-14", so every estimate had been stale by the skill's own
rule since October 2025. Each anchor now also lives as a `volatile_facts` entry with `as_of` and
`source` in the runtime profile, and the inline figures must match those facts. The Lambda MicroVMs
anchor was the arm64 rate without saying so; x86_64 is about 18% higher.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
AA = PLUGIN_ROOT / "skills" / "agent-advisor"
ESTIMATE = AA / "references" / "phases" / "estimate" / "estimate.md"
RUNTIMES = AA / "references" / "runtimes"


def _fact(profile: str, key: str) -> dict:
    facts = json.loads((RUNTIMES / f"{profile}.json").read_text(encoding="utf-8"))["volatile_facts"]
    matches = [f for f in facts if f["key"] == key]
    assert len(matches) == 1, (profile, key)
    return matches[0]


def _anchor_block() -> str:
    text = ESTIMATE.read_text(encoding="utf-8")
    start = text.index("Cached anchors (order-of-magnitude")
    return text[start:text.index("- Bedrock model token rates", start)]


def _last_updated() -> date:
    match = re.search(r"last updated (\d{4}-\d{2}-\d{2})", _anchor_block())
    assert match, "the anchor table must carry a last-updated date"
    return date.fromisoformat(match.group(1))


def test_pricing_facts_exist_with_date_and_source() -> None:
    for profile, key in (("agentcore", "microvms_pricing"), ("lambda_microvms", "pricing"), ("ecs", "fargate_pricing")):
        fact = _fact(profile, key)
        assert fact["verification_key"] == f"{profile}.{key}"
        assert fact["verify_via_mcp"] is True
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact["as_of"]), fact["as_of"]
        assert fact["source"].startswith("https://aws.amazon.com/"), fact["source"]
        assert fact["value"]["region"] == "us-east-1"


def test_anchor_date_matches_the_facts_and_is_not_the_2025_date() -> None:
    updated = _last_updated()
    assert updated > date(2025, 7, 14)
    for profile, key in (("agentcore", "microvms_pricing"), ("lambda_microvms", "pricing"), ("ecs", "fargate_pricing")):
        assert date.fromisoformat(_fact(profile, key)["as_of"]) == updated, (profile, key)


def _rates(text: str, label: str) -> tuple[float, float]:
    """Return (vcpu_hour, gb_hour) from '... ~$X/vCPU-hour ... ~$Y/GB-hour' after `label`."""
    start = text.index(label)
    chunk = text[start:start + 160]
    match = re.search(r"~\$([0-9.]+)/vCPU-hour[^~]*~\$([0-9.]+)/GB-hour", chunk)
    assert match, (label, chunk)
    return float(match.group(1)), float(match.group(2))


def test_inline_anchors_agree_with_the_facts() -> None:
    block = " ".join(_anchor_block().split())
    agentcore = _fact("agentcore", "microvms_pricing")["value"]
    assert _rates(block, "`microvms_pricing`:") == (agentcore["runtime_v1"]["vcpu_hour"], agentcore["runtime_v1"]["gb_hour"])
    v2 = agentcore["runtime_v2_consumption"]
    assert _rates(block, "consumption ") == (v2["vcpu_hour"], v2["gb_hour"])
    v2c = agentcore["runtime_v2_committed_baseline"]
    assert _rates(block, "committed baseline ") == (v2c["vcpu_hour"], v2c["gb_hour"])
    lam = _fact("lambda_microvms", "pricing")["value"]
    assert _rates(block, "`pricing`: arm64 ") == (lam["arm64"]["vcpu_hour"], lam["arm64"]["gb_hour"])
    assert _rates(block, "x86_64 ~$0.1176") == (lam["x86_64"]["vcpu_hour"], lam["x86_64"]["gb_hour"])
    fargate = _fact("ecs", "fargate_pricing")["value"]
    assert _rates(block, "`fargate_pricing`: x86_64 ") == (fargate["x86_64"]["vcpu_hour"], fargate["x86_64"]["gb_hour"])
    assert _rates(block, "arm64 ~$0.03238") == (fargate["arm64"]["vcpu_hour"], fargate["arm64"]["gb_hour"])


def test_lambda_anchor_names_the_architecture() -> None:
    block = " ".join(_anchor_block().split())
    lambda_line = block[block.index("- Lambda MicroVMs"):block.index("- Fargate")]
    assert "arm64" in lambda_line and "x86_64" in lambda_line
    assert "Name the architecture the band assumes" in lambda_line
    lam = _fact("lambda_microvms", "pricing")["value"]
    assert lam["x86_64"]["vcpu_hour"] > lam["arm64"]["vcpu_hour"]
