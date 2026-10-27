"""Drift guard between the two Gemini → Bedrock mapping guides that both live in gcp-to-aws.

PR #469 promoted `google` to `supported` by adding a source-cloud-neutral shared guide
at `skills/shared/ai/ai-gemini-to-bedrock.md` (vendored into gcp-to-aws and azure-to-aws),
while gcp-to-aws KEPT its older adapter-local guide at
`skills/gcp-to-aws/references/design-refs/ai-gemini-to-bedrock.md` — which is still the
file `design-ai.md` actually loads at runtime. Repointing that runtime routing onto the
shared guide is deferred to the extraction stages (issue #389 stages 3a-3e).

Until then, the two guides carry the SAME pricing tables and model-mapping rows under two
paths with no gate between them: the vendored-parity check only compares the vendored copy
against the shared canonical, never against the adapter-local original. A one-sided pricing
edit would let them silently disagree.

This test closes that gap WITHOUT moving runtime routing: it pins the substantive BODY of
both guides (everything from the first `## ` section heading onward) byte-for-byte. The two
files intentionally differ only in their lead-in (the shared guide carries the canonical
"vendored / edit HERE" banner and a source-neutral `Applies to:` line; the adapter-local
guide keeps its Vertex-specific framing), so the header is excluded and the priced body is
not. When the extraction stage folds the adapter-local guide into the shared one, delete
this test with that change.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SHARED_GUIDE = PLUGIN_ROOT / "skills" / "shared" / "ai" / "ai-gemini-to-bedrock.md"
ADAPTER_LOCAL_GUIDE = (
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "design-refs" / "ai-gemini-to-bedrock.md"
)

# First `## ` heading in both files; everything from here down is the priced, source-neutral
# body (tables, decision paths, feature notes). The lead-in above it is the only part the two
# guides are allowed to differ on.
BODY_ANCHOR = "## Competitive Reality"


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    idx = text.find(BODY_ANCHOR)
    assert idx != -1, f"{path} is missing the body anchor {BODY_ANCHOR!r} — the guide's shape changed; update this test's anchor"
    return text[idx:]


def test_both_gemini_guides_exist() -> None:
    assert SHARED_GUIDE.is_file(), f"missing shared Gemini guide: {SHARED_GUIDE}"
    assert ADAPTER_LOCAL_GUIDE.is_file(), f"missing adapter-local Gemini guide: {ADAPTER_LOCAL_GUIDE}"


def test_gemini_guide_bodies_are_byte_identical() -> None:
    """The priced body (from the first `## ` heading down) must match exactly across both
    Gemini guides. If this fails, a pricing/model-mapping row was edited in one guide and not
    the other — sync them (edit the shared canonical, then copy the body into the adapter-local
    guide), or, if this is the #389 3a-3e extraction, delete this test with that change."""
    shared_body = _body(SHARED_GUIDE)
    adapter_body = _body(ADAPTER_LOCAL_GUIDE)
    assert shared_body == adapter_body, (
        "Gemini mapping-guide bodies have drifted between\n"
        f"  {ADAPTER_LOCAL_GUIDE.relative_to(PLUGIN_ROOT)} (runtime-loaded by design-ai.md)\n"
        f"  {SHARED_GUIDE.relative_to(PLUGIN_ROOT)} (shared canonical, vendored)\n"
        "A pricing or model-mapping row was changed in one but not the other. Edit the shared "
        "canonical and copy its body into the adapter-local guide, or delete this test as part "
        "of the issue #389 3a-3e extraction that folds the two into one."
    )
