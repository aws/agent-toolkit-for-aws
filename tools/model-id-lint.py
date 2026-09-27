#!/usr/bin/env python3
"""Model-ID drift lint (CI).

Fails when a known-bad Bedrock model ID appears in the aws-startup-advisor
plugin outside the files whose JOB is to catalog it. Two classes today:

1. EOL-as-target: models that are past EOL or inside the 90-day exclusion
   zone per ai-model-lifecycle.md — Claude Sonnet 4, Claude 3 Haiku, Nova
   Premier v1, Nova Sonic v1. Each may appear in the model catalog / pricing
   rate card (that's what a lifecycle table is for), but nowhere else: an
   example or script carrying one becomes a rewrite target.

2. Fabricated hybrids: `claude-sonnet-4-6-<date>` / `claude-opus-4-8-<date>`
   — Sonnet 4.6 and Opus 4.8 IDs are UNDATED; the dated forms graft a newer
   model name onto an older model's date stamp and have never existed. One
   allowlisted exception: the resolve-bedrock-model-id helper, whose input
   example is intentionally invalid (repairing broken IDs is its purpose).

Grep-once hygiene doesn't stick; this makes the sweep permanent. Extend
BAD_PATTERNS when a model is EOL'd. Stdlib only. Exit 0 = clean.

This is the model-reference half of the model-registry gate: model-staleness.py
keeps the registry itself fresh and in sync; this keeps the rest of the plugin
from naming a model the registry has already retired.
"""

import re
import sys
from pathlib import Path

# This repo nests the plugin under plugins/; the sibling repo rooted at the
# plugin dir directly. Everything below keys off PLUGIN, so this is the only
# path that changes between the two homes.
PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "aws-startup-advisor"
EXTS = {".md", ".py", ".json", ".ts", ".tf", ".sh", ".template"}

BAD_PATTERNS = [
    (
        re.compile(r"claude-sonnet-4-20250514"),
        "Claude Sonnet 4 (EOL 2026-10-14, excluded) used outside the model catalog",
        {  # allowlist: catalog files whose job is recording the model + its EOL status
            "skills/gcp-to-aws/references/shared/pricing-cache.md",
            "skills/shared/ai/ai-model-lifecycle.md",
        },
    ),
    (
        re.compile(r"anthropic\.claude-3-haiku-20240307-v1:0"),
        "Claude 3 Haiku (EOL 2026-09-10, past EOL) used outside the model catalog",
        {
            "skills/shared/ai/ai-model-lifecycle.md",
        },
    ),
    (
        re.compile(r"amazon\.nova-premier-v1:0"),
        "Nova Premier v1 (EOL 2026-09-14, past EOL) used outside the model catalog",
        {
            "skills/gcp-to-aws/references/shared/pricing-cache.md",
            "skills/shared/ai/ai-model-lifecycle.md",
        },
    ),
    (
        re.compile(r"amazon\.nova-sonic-v1:0"),
        "Nova Sonic v1 (EOL 2026-09-14, past EOL) used outside the model catalog",
        {
            "skills/gcp-to-aws/references/shared/pricing-cache.md",
            "skills/shared/ai/ai-model-lifecycle.md",
        },
    ),
    (
        re.compile(r"claude-(?:sonnet-4-6|opus-4-8)-\d{8}"),
        "fabricated dated ID — Sonnet 4.6 / Opus 4.8 Bedrock IDs are undated; this form never existed",
        {  # allowlist: the broken-ID-repair helper's intentionally-invalid example
            "skills/llm-to-bedrock/references/helpers/resolve-bedrock-model-id/resolve-bedrock-model-id.md",
        },
    ),
]

SELF = Path(__file__).resolve()

# A vendored copy under `skills/<skill>/references/vendored/<rel>` is a byte-identical
# mirror of the canonical `skills/shared/<rel>` (enforced by model-staleness.py), so it
# inherits the canonical file's allowlist entry. Collapsing the path here keeps the
# allowlist a set of CANONICAL paths — otherwise every new skill that vendors a
# catalog file would silently start failing this lint until someone remembered to
# add its mirror, which is exactly the per-copy manifest the vendoring model exists
# to avoid.
_VENDORED = re.compile(r"^skills/[^/]+/references/vendored/")


def canonicalize(rel: str) -> str:
    return _VENDORED.sub("skills/shared/", rel)


def main() -> int:
    failures = []
    for path in sorted(PLUGIN.rglob("*")):
        if not path.is_file() or path.suffix not in EXTS or path.resolve() == SELF:
            continue
        rel = str(path.relative_to(PLUGIN))
        if "node_modules" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        canonical = canonicalize(rel)
        for pattern, why, allow in BAD_PATTERNS:
            if rel in allow or canonical in allow:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    failures.append(f"{rel}:{i}: {why}")
    if failures:
        print(f"model-id lint: {len(failures)} problem(s)", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("model-id lint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
