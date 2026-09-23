#!/usr/bin/env python3
"""Resolve a plan-stated source model ID against the live provider catalog.

Usage:
  PLAN_MODEL_ID=<id> python resolve_source_model.py <path/to/.source-provider-env>

Prints one JSON object on stdout:
  {"status": "exact"|"prefix", "resolved_id": ..., "all_hits": [...]}
  {"status": "not_found", "candidates": [...], "ambiguous_prefix": true?}
  {"status": "no_key"}   (exit 2)

Hard rule — model line is sacred: auto-resolution may only pin the SAME model
line to a date (YYYY-MM-DD) or pure version suffix. Any alphabetic suffix
(mini, pro, turbo, latest, codex, ...) is a different line or a moving alias
and is surfaced to the user instead of picked. See
references/helpers/run-source-model-baseline/run-source-model-baseline.md.

Security: the key is read from the env file and sent ONLY as an auth header to
the provider's own official endpoint (api.openai.com / api.anthropic.com /
generativelanguage.googleapis.com) — never to any other host and never as a
URL query parameter. The key value is never printed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

SAFE_SUFFIX = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d[\d.]*$")


PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


def load_env_file(path: str) -> dict[str, str]:
    """Parse the env file and return ITS pairs. The file is authoritative for
    provider selection — an ambient OPENAI_API_KEY in the inherited process
    environment must not select OpenAI when the migration's file carries a
    GEMINI_API_KEY (the model ID would go to the wrong provider). Parsed pairs
    are also exported so downstream reads use the file's values."""
    pairs: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line:
                k, v = line.split("=", 1)
                pairs[k] = v
                os.environ[k] = v
    return pairs


PROVIDER_TO_KEY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def pick_provider(file_pairs: dict[str, str]) -> str | None:
    """Select the provider key name. SOURCE_PROVIDER (the helper's declared
    input) is authoritative when set — a file carrying several provider keys
    must not fall back to tuple-order guessing. Without it, fall back to the
    first recognized key IN THE FILE (never the ambient environment)."""
    stated = os.environ.get("SOURCE_PROVIDER", "").lower()
    if stated:
        key = PROVIDER_TO_KEY.get(stated)
        if key is None or key not in file_pairs:
            return None
        return key
    return next((k for k in PROVIDER_KEYS if k in file_pairs), None)


def _secret_variants(secrets) -> list:
    """Every textual form a secret can take in error text. A raw CR/LF inside
    a credential is rendered ESCAPED in exception messages (repr turns one
    control char into backslash-r text), so literal replacement alone misses
    it; the control-char-split fragments catch any remaining partial echo."""
    import re as _re
    out: list = []
    for s in secrets:
        if not s:
            continue
        out.append(s)
        esc = s.encode("unicode_escape").decode("ascii")
        if esc != s:
            out.append(esc)
        for frag in _re.split(r"[\x00-\x1f]+", s):
            if len(frag) >= 6 and frag not in out:
                out.append(frag)
    return sorted(out, key=len, reverse=True)


def redact(text: str, secrets) -> str:
    """Strip secret values from failure text. A raised exception can embed a
    header value verbatim (http.client rejects an invalid header with the full
    'Bearer <key>' in the ValueError message), and the docstring promise is
    that the key never reaches the output JSONL."""
    for s in _secret_variants(secrets):
        text = text.replace(s, "***")
    return text


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 — fixed https hosts
        return json.loads(r.read())


def list_openai() -> list[str]:
    # OpenAI's list endpoint returns the full catalog in one response (no cursor).
    data = _get_json(
        "https://api.openai.com/v1/models",
        {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
    )
    return [m["id"] for m in data["data"]]


def list_anthropic() -> list[str]:
    # Paginated: default page size is 20, so a valid model can sit past page 1
    # and must not be reported not_found. Cursor: has_more + last_id → after_id.
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
    }
    ids: list[str] = []
    url = "https://api.anthropic.com/v1/models?limit=1000"
    while True:
        data = _get_json(url, headers)
        ids += [m["id"] for m in data["data"]]
        if not data.get("has_more"):
            return ids
        url = f"https://api.anthropic.com/v1/models?limit=1000&after_id={data['last_id']}"


def list_gemini() -> list[str]:
    # Key travels as a header, not a query parameter — URLs end up in logs.
    # Paginated via nextPageToken.
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    ids: list[str] = []
    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
    while True:
        data = _get_json(url, headers)
        # Gemini returns names like "models/gemini-1.5-pro"; strip the prefix.
        ids += [m["name"].split("/", 1)[-1] for m in data.get("models", [])]
        token = data.get("nextPageToken")
        if not token:
            return ids
        url = ("https://generativelanguage.googleapis.com/v1beta/models"
               f"?pageSize=1000&pageToken={token}")


def safe_variant(catalog_id: str, plan_id: str) -> bool:
    if catalog_id == plan_id:
        return True
    suffix = catalog_id[len(plan_id) + 1:]  # strip "PLAN_ID-"
    return bool(SAFE_SUFFIX.match(suffix))


def _lcp(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def resolve(catalog: list[str], plan_id: str) -> dict:
    """Pure resolution decision — no network, unit-tested."""
    if plan_id in catalog:
        return {"status": "exact", "resolved_id": plan_id}

    prefix_hits = [m for m in catalog if m == plan_id or m.startswith(plan_id + "-")]

    # A bare prefix match is NOT enough to auto-resolve: "gpt-4o-mini",
    # "claude-3-5-sonnet-latest" start with a plausible plan ID but are
    # different model lines / non-deterministic aliases. Only a date or pure
    # version suffix is the same line.
    safe_hits = sorted((m for m in prefix_hits if safe_variant(m, plan_id)), key=len)
    if safe_hits:
        return {"status": "prefix", "resolved_id": safe_hits[0], "all_hits": safe_hits}

    if prefix_hits:
        return {"status": "not_found", "candidates": prefix_hits[:5], "ambiguous_prefix": True}

    ranked = sorted(catalog, key=lambda m: -_lcp(m, plan_id))[:5]
    return {"status": "not_found", "candidates": ranked}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: PLAN_MODEL_ID=<id> resolve_source_model.py <env-file>", file=sys.stderr)
        return 2
    file_pairs = load_env_file(sys.argv[1])
    plan_id = os.environ["PLAN_MODEL_ID"]

    provider = pick_provider(file_pairs)
    listers = {"OPENAI_API_KEY": list_openai, "ANTHROPIC_API_KEY": list_anthropic,
               "GEMINI_API_KEY": list_gemini}
    if provider not in listers:
        print(json.dumps({"status": "no_key"}))
        return 2

    secrets = [v for k, v in file_pairs.items() if k in PROVIDER_KEYS]
    try:
        catalog = listers[provider]()
    except Exception as e:  # noqa: BLE001 — an unhandled traceback would put the
        # exception text (which can embed the auth header) on stderr unredacted
        print(json.dumps({"status": "error",
                          "detail": redact(f"{type(e).__name__}: {e}", secrets)}))
        return 3

    print(json.dumps(resolve(catalog, plan_id)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
