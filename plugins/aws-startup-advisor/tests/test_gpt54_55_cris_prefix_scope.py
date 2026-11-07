"""Guard: the `in.` CRIS prefix is a GPT-5.6 fact only.
The GPT-5.4 and GPT-5.5 model cards (read 2026-11-07) publish only `us.` and
`global.` inference-profile ids:
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-55.html
The catalog records that; this test makes sure no prose consumer of the catalog
(design/generate checklists, the code-rewriter agent, the shared schema) hands
those two models a grouped `us.`/`in.`/`global.` grant that would let an agent
record `in.openai.gpt-5.4` / `in.openai.gpt-5.5` as a runtime id.
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
def _sentences_granting_in_to_gpt54_55(text: str) -> list[str]:
    """Return sentence-ish windows that mention GPT-5.4/5.5 AND the grouped
    us./in./global. prefix WITHOUT also scoping `in.` to GPT-5.6 in that window."""
    hits: list[str] = []
    for m in _GROUPED_PREFIX.finditer(text):
        window = text[max(0, m.start() - 320) : m.end() + 320]
        if not _GPT_54_55.search(window):
            continue
        # Acceptable only when the same window explicitly scopes `in.` to GPT-5.6
        # and gives GPT-5.4/5.5 their own `us.`/`global.` grant.
        scoped = re.search(r"GPT-5\.6", window) and re.search(
            r"`?us\.`?\s*/\s*`?global\.`?\s*(only|for|;)", window
        )
        if not scoped:
            hits.append(" ".join(window.split()))
    return hits
def test_catalog_inference_profiles_for_gpt54_55_are_us_and_global_only() -> None:
    catalog = json.loads(CATALOG.read_text())
    for key in ("openai_gpt_5_4", "openai_gpt_5_5"):
        assert set(catalog["models"][key]["inference_profiles"]) == {"us", "global"}, key
def test_no_prose_consumer_grants_in_prefix_to_gpt54_55() -> None:
    offenders: dict[str, list[str]] = {}
    for path in CONSUMERS:
        assert path.exists(), path
        hits = _sentences_granting_in_to_gpt54_55(path.read_text())
        if hits:
            offenders[str(path.relative_to(PLUGIN_ROOT))] = hits
    assert not offenders, (
        "GPT-5.4 / GPT-5.5 are granted a us./in./global. CRIS id; their cards publish "
        "us. and global. only. Scope `in.` to GPT-5.6:\n"
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
