"""Guard: the `in.` CRIS prefix belongs to GPT-5.6 Terra and Luna only.
Public model cards (read 2026-11-07):
  GPT-5.6 Terra / Luna  us. / in. / us-gov. / global.
  GPT-5.6 Sol           us. / global.
  GPT-5.4, GPT-5.5      us. / global.
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-sol.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-terra.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-55.html
This test makes sure no prose consumer of the catalog (design/generate
checklists, the code-rewriter agent, the shared schema, the catalog strength
text) hands GPT-5.4 / GPT-5.5 a grouped `us.`/`in.`/`global.` grant, and that
any `in.` grant to "GPT-5.6" names Terra/Luna rather than the whole family,
so an agent cannot record `in.openai.gpt-5.6-sol`, `in.openai.gpt-5.4` or
`in.openai.gpt-5.5` as a runtime id.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CATALOG = PLUGIN_ROOT / "skills" / "shared" / "ai" / "models" / "openai-bedrock.json"
# Every file that names GPT-5.4 / GPT-5.5 alongside a CRIS-prefix grant.
CONSUMERS = [
    PLUGIN_ROOT / "agents" / "llm2bedrock-code-rewriter.md",
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md",
    PLUGIN_ROOT / "skills" / "shared" / "ai" / "schema-design-aws-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "shared" / "schema-design-aws-ai.md",
    PLUGIN_ROOT / "skills" / "shared" / "ai" / "ai-migration-guardrails.md",
]
_GROUPED_PREFIX = re.compile(r"`?us\.`?\s*/\s*`?in\.`?\s*/\s*`?global\.`?")
_GPT_54_55 = re.compile(r"GPT-5\.[45]|gpt-5\.[45]", re.IGNORECASE)
_TERRA_LUNA_SCOPED = re.compile(r"GPT-5\.6\s+Terra\s*(and|/)\s*(GPT-5\.6\s+)?Luna", re.IGNORECASE)
_SOL_EXCLUDED = re.compile(r"`?us\.`?\s*/\s*`?global\.`?\s*(only\s+)?for[^.;)]*GPT-5\.6\s+Sol", re.IGNORECASE)
_US_GLOBAL_GRANT = re.compile(r"`?us\.`?\s*/\s*`?global\.`?\s*(only|for|;)")
def _bad_in_grants(text: str) -> list[str]:
    """Return windows around a grouped us./in./global. grant that either
    (a) cover GPT-5.4/5.5 without giving them their own us./global. grant, or
    (b) grant `in.` to "GPT-5.6" family-wide instead of to Terra/Luna with Sol
        explicitly in the us./global.-only set."""
    hits: list[str] = []
    for m in _GROUPED_PREFIX.finditer(text):
        window = text[max(0, m.start() - 360) : m.end() + 360]
        mentions_54_55 = bool(_GPT_54_55.search(window))
        mentions_56 = bool(re.search(r"GPT-5\.6", window))
        if not (mentions_54_55 or mentions_56):
            continue
        ok = True
        if mentions_54_55 and not _US_GLOBAL_GRANT.search(window):
            ok = False
        if mentions_56 and not (_TERRA_LUNA_SCOPED.search(window) and _SOL_EXCLUDED.search(window)):
            ok = False
        if not ok:
            hits.append(" ".join(window.split()))
    return hits
def test_catalog_inference_profiles_for_gpt54_55_are_us_and_global_only() -> None:
    catalog = json.loads(CATALOG.read_text())
    for key in ("openai_gpt_5_4", "openai_gpt_5_5"):
        assert set(catalog["models"][key]["inference_profiles"]) == {"us", "global"}, key
def test_no_prose_consumer_grants_in_prefix_to_gpt54_55_or_gpt56_sol() -> None:
    offenders: dict[str, list[str]] = {}
    # The catalog's runtime_converse path strength is prose an agent reads too.
    catalog = json.loads(CATALOG.read_text())
    strength_text = "\n".join(catalog["paths"]["runtime_converse"]["strengths"])
    hits = _bad_in_grants(strength_text)
    if hits:
        offenders["skills/shared/ai/models/openai-bedrock.json (runtime_converse.strengths)"] = hits
    for path in CONSUMERS:
        assert path.exists(), path
        hits = _bad_in_grants(path.read_text())
        if hits:
            offenders[str(path.relative_to(PLUGIN_ROOT))] = hits
    assert not offenders, (
        "A grouped us./in./global. CRIS grant covers GPT-5.4 / GPT-5.5 or the whole GPT-5.6 "
        "family. Cards (2026-11-07): in. exists for GPT-5.6 Terra/Luna only; GPT-5.6 Sol, "
        "GPT-5.4 and GPT-5.5 publish us./global. only:\n"
        + "\n".join(f"  {k}: {v[0][:200]}" for k, v in offenders.items())
    )
def test_vendored_copies_match_canonical_for_edited_files() -> None:
    pairs = [
        (
            PLUGIN_ROOT / "skills" / "shared" / "ai" / "schema-design-aws-ai.md",
            PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "vendored" / "ai" / "schema-design-aws-ai.md",
        ),
        (
            PLUGIN_ROOT / "skills" / "shared" / "ai" / "schema-design-aws-ai.md",
            PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "vendored" / "ai" / "schema-design-aws-ai.md",
        ),
        (
            CATALOG,
            PLUGIN_ROOT / "skills" / "agent-advisor" / "references" / "vendored" / "ai" / "models" / "openai-bedrock.json",
        ),
    ]
    for canonical, vendored in pairs:
        assert canonical.read_bytes() == vendored.read_bytes(), f"{vendored} drifted from {canonical}"
