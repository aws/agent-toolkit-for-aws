#!/usr/bin/env python3
"""Derive a model's monthly tokens from the shape of its calls, as references/genai-must-ask.md
asks for them, so two runs given the same answers size the same tokens.

Input (JSON on stdin): one entry per model.

  {"models": [{
     "model": "Claude Sonnet 4.6",
     "caching": true,
     "invocations": [{"count": 140000, "toolCalls": 4}, {"count": 125000, "toolCalls": 12}],
     "calls": 1700000,
     "coldStarts": 225000,
     "prefix": {"low": 3000, "mid": 5000, "high": 15000},
     "fresh": {"low": 50, "mid": 100, "high": 300},
     "step": {"low": 500, "mid": 2000, "high": 8000},
     "output": {"low": 250, "mid": 500, "high": 1500}}]}

  - invocations: each user request or job, and the tool calls it makes. An invocation with k
    tool calls makes k + 1 model calls. Leave it out when every call is its own invocation and
    give `calls` instead.
  - calls: the model calls a month the user stated. With `invocations` too, it is only checked.
  - coldStarts: how often the cache starts empty: one per session, or for a fixed template,
    templates x 12 refreshes an hour x active hours (the cache lasts 5 minutes).
  - prefix: the part every call repeats, such as the system prompt or template.
  - fresh: the new input of an invocation, such as the user's message or the job's content.
  - step: what each tool call adds to the context, the call and its result.
  - output: the tokens one call writes.

Each step's context is the prefix, the fresh input and every earlier step, so the call that
follows step j reads all of it. With caching on, a call reads the context already cached and
writes what it adds; a cold start writes the prefix. With caching off, every call is input.

Output (exit 0): {"models": [{"model", "calls", "warnings", "tokens": {"input", "cacheRead",
"cacheWrite", "output"}}]}, each token type a {"low", "mid", "high"} count of tokens. Convert to
the line's price-list unit, such as thousands of tokens, before writing the request.
On failure (exit 1): {"error": {"code": "ValidationException", "message": ...}} on stdout,
the same contract as the skill's other scripts (errors.py).

Usage:
  python scripts/derive_genai_tokens.py < genai-shape.json
"""

import json
import math
import sys

from errors import fail

BANDS = ("low", "mid", "high")
SIZES = ("prefix", "fresh", "step", "output")
# Stated calls that differ from the invocations' calls by more than this are a contradiction.
CALLS_TOLERANCE = 0.25


def is_count(value):
    """A non-negative, finite number, not a bool."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def band_values(model, name):
    value = model.get(name, 0)
    if is_count(value):
        return {b: float(value) for b in BANDS}
    if not isinstance(value, dict) or any(not is_count(value.get(b)) for b in BANDS):
        raise ValueError(
            f"{model.get('model')}: {name} needs a non-negative number or low, mid and high"
        )
    if not value["low"] <= value["mid"] <= value["high"]:
        raise ValueError(f"{model.get('model')}: {name} needs low <= mid <= high")
    return {b: float(value[b]) for b in BANDS}


def derive(model):
    groups = model.get("invocations")
    if not groups:
        if not is_count(model.get("calls")) or model["calls"] == 0:
            raise ValueError(f"{model.get('model')}: give invocations or calls")
        groups = [{"count": model["calls"], "toolCalls": 0}]
    if not isinstance(groups, list) or any(
        not isinstance(g, dict) or not is_count(g.get("count")) or not is_count(g.get("toolCalls"))
        for g in groups
    ):
        raise ValueError(
            f"{model.get('model')}: each invocations entry needs a non-negative count and toolCalls"
        )
    if not is_count(model.get("coldStarts", 0)):
        raise ValueError(f"{model.get('model')}: coldStarts must be a non-negative number")
    sizes = {name: band_values(model, name) for name in SIZES}
    cold = float(model.get("coldStarts", 0))
    caching = bool(model.get("caching"))
    calls = sum(g["count"] * (g["toolCalls"] + 1) for g in groups)
    tokens: dict[str, dict[str, float]] = {
        kind: {} for kind in ("input", "cacheRead", "cacheWrite", "output")
    }
    for b in BANDS:
        prefix, fresh, step, out = (sizes[name][b] for name in SIZES)
        context = written = 0.0
        for g in groups:
            n = g["toolCalls"] + 1
            # Call i (from 0) sees the prefix, the fresh input and the i steps before it.
            context += g["count"] * (n * (prefix + fresh) + step * n * (n - 1) / 2)
            written += g["count"] * (fresh + (n - 1) * step)
        if caching:
            new = sum(g["count"] for g in groups) * fresh
            tokens["input"][b] = new
            tokens["cacheWrite"][b] = cold * prefix + written - new
            tokens["cacheRead"][b] = max(context - new - tokens["cacheWrite"][b], 0.0)
        else:
            tokens["input"][b], tokens["cacheRead"][b], tokens["cacheWrite"][b] = context, 0.0, 0.0
        tokens["output"][b] = calls * out
    warnings = []
    if caching and "coldStarts" not in model:
        warnings.append(
            "caching is on but coldStarts is missing, so the prefix is never written to the "
            "cache; ask when the cache starts cold before pricing"
        )
    stated = model.get("calls")
    if model.get("invocations") and is_count(stated) and stated > 0:
        if abs(calls - stated) > CALLS_TOLERANCE * stated:
            warnings.append(
                f"the invocations make {calls:,.0f} calls, but the user stated {stated:,.0f}; ask "
                "which holds before pricing"
            )
    return {
        "model": model.get("model"),
        "calls": calls,
        "warnings": warnings,
        "tokens": {k: {b: round(v[b]) for b in BANDS} for k, v in tokens.items()},
    }


def main():
    try:
        request = json.load(sys.stdin)
        models = request.get("models") if isinstance(request, dict) else None
        if not isinstance(models, list) or not models:
            raise ValueError("the request must be an object with a non-empty models list")
        if any(not isinstance(m, dict) for m in models):
            raise ValueError("each entry in models must be an object")
        result = {"models": [derive(m) for m in models]}
    except (ValueError, KeyError, TypeError, OverflowError, json.JSONDecodeError) as exc:
        return fail("ValidationException", str(exc))
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
