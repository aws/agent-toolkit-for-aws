import json
from pathlib import Path

AA = Path("skills/agent-advisor")
E = AA / "references/phases/estimate/estimate.md"
s = E.read_text(encoding="utf-8")

old_head = """Cached anchors (order-of-magnitude, us-east-1, verify; last updated 2026-11-13, from the AWS Price
List; each figure is also a `volatile_facts` entry with `as_of` and `source` in the runtime
profile named, so the two must agree):
"""
new_head = """Cached anchors (order-of-magnitude, us-east-1, verify; last updated 2026-11-13, from the AWS Price
List; each figure is also a `volatile_facts` entry with `as_of` and `source` in the runtime
profile named, so the two must agree). The pricing facts are dated cache references
(`verify_via_mcp: false`): Design does not look them up per run, so the freshness footer never
lists a price as verified, and `pricing_source` stays `cached` or `cached_stale` by the table's
date. To re-verify, update the fact and this table together.
"""
assert s.count(old_head) == 1
s = s.replace(old_head, new_head)

old_ac = """- AgentCore (microVMs compute type) — `agentcore.json` fact `microvms_pricing`: ~$0.0895/vCPU-hour
  (active CPU only), ~$0.00945/GB-hour for the original `Runtime:Consumption-based` SKUs. The price
  list also carries `-v2` runtime SKUs (consumption ~$0.1276/vCPU-hour, ~$0.0169/GB-hour;
  committed baseline ~$0.0997/vCPU-hour, ~$0.0132/GB-hour); use them only when the design states
  the unit runs on that runtime generation, and say which generation the band assumes.
"""
new_ac = """- AgentCore (microVMs compute type) — `agentcore.json` fact `microvms_pricing`. **Default: the
  next-generation runtime (`platformVersion` V2), consumption ~$0.1276/vCPU-hour, ~$0.0169/GB-hour**
  (active CPU only). Since 2026-11-12 a new runtime in us-east-1 and the other listed Regions is
  V2 unless created with `platformVersion: V1`, so price a new deployment at V2 and name the
  generation in the band. Use the V1 rate (~$0.0895/vCPU-hour, ~$0.00945/GB-hour, the original
  `Runtime:Consumption-based` SKUs) only when the design says the unit stays on an existing V1
  runtime. The V2 committed-baseline SKUs (~$0.0997/vCPU-hour, ~$0.0132/GB-hour) apply only when
  the user has a committed baseline; say so when used. V2 also reclaims idle memory, so a
  multi-turn agent's billed GB-hours can be well under its peak allocation; do not apply that
  discount in the band, name it as an assumption.
"""
assert s.count(old_ac) == 1
s = s.replace(old_ac, new_ac)

old_fg = """- Fargate — `ecs.json` fact `fargate_pricing`: x86_64 ~$0.04048/vCPU-hour, ~$0.004445/GB-hour;
  arm64 ~$0.03238/vCPU-hour, ~$0.00356/GB-hour.
"""
new_fg = """- Fargate — `ecs.json` fact `fargate_pricing`. **Default: x86_64** ~$0.04048/vCPU-hour,
  ~$0.004445/GB-hour; arm64 ~$0.03238/vCPU-hour, ~$0.00356/GB-hour only when the design says the
  task runs on Graviton. Name the architecture the band assumes.
"""
assert s.count(old_fg) == 1
s = s.replace(old_fg, new_fg)
E.write_text(s, encoding="utf-8")

# Facts: mark the default, turn off per-run MCP verification (they are dated cache references).
for name, key, default in (("agentcore", "microvms_pricing", "runtime_v2_consumption"),
                           ("lambda_microvms", "pricing", "arm64"), ("ecs", "fargate_pricing", "x86_64")):
    path = AA / f"references/runtimes/{name}.json"
    text = path.read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if f'"key": "{key}"' in l)
    fact = json.loads(line.rstrip().rstrip(","))
    assert fact["verify_via_mcp"] is True
    fact["verify_via_mcp"] = False
    fact["value"]["default"] = default
    if name == "agentcore":
        fact["value"]["default_note"] = ("New runtimes in us-east-1 and the other listed Regions default to platformVersion V2 since "
                                         "2026-11-12 (https://aws.amazon.com/about-aws/whats-new/2026/11/new-agentcore-runtime-default/); "
                                         "V1 applies only to an existing runtime that stays on V1.")
    fact["verification_note"] = "Dated cache reference, not verified per run: update as_of and estimate.md together."
    new_line = line[: len(line) - len(line.lstrip())] + json.dumps(fact, ensure_ascii=False) + ("," if line.rstrip().endswith(",") else "")
    assert text.count(line) == 1
    text = text.replace(line, new_line)
    json.loads(text)
    path.write_text(text, encoding="utf-8")

# estimate-assemble: state the same source order.
A = AA / "references/phases/estimate/estimate-assemble.md"
a = A.read_text(encoding="utf-8")
old = "  - design.json + cached rate anchors (combined inline in estimate.md)\n"
assert a.count(old) == 1
a = a.replace(old, "  - design.json + cached rate anchors (combined inline in estimate.md; the anchors are dated cache references mirrored by `verify_via_mcp: false` pricing facts in the runtime profiles, never a value Design verified this run)\n")
A.write_text(a, encoding="utf-8")
print("ok")
