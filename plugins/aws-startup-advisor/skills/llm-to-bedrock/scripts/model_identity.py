"""Conservative same-model checks for Track 2 migration shortcuts.

The legacy same_model_family flag means unchanged model identity, not provider
membership. Resolve moving aliases and opaque profiles before using a shortcut.
"""

import argparse
import json
import re


def _identity(model_id: str | None, provider: str, target: bool = False) -> str | None:
    if not isinstance(model_id, str):
        return None
    value = model_id.strip().lower()
    if not value or value.startswith("arn:") or "latest" in value or "*" in value:
        return None
    value = re.sub(r"^(us|eu|au|jp|apac|in|global)\.", "", value)
    prefix = provider + "."
    if target and not value.startswith(prefix):
        return None
    value = value.removeprefix(prefix)
    # Bedrock transport revisions are not a different first-party checkpoint.
    # Keep release dates and model/tier suffixes: they may identify different models.
    if target:
        value = re.sub(r"-v\d+(?::\d+)?$", "", value)
    if provider == "anthropic" and not value.startswith("claude-"):
        return None
    if provider == "openai" and (not value.startswith("gpt-") or value.startswith("gpt-oss")):
        return None
    return value


def same_model(provider: str, source_model: str, target_model: str) -> bool:
    if provider not in {"anthropic", "openai"}:
        return False
    source = _identity(source_model, provider)
    target = _identity(target_model, provider, target=True)
    return source is not None and source == target


def same_model_family(provider: str, mappings: list[dict]) -> bool:
    return bool(mappings) and all(
        same_model(provider, item.get("source_model"), item.get("aws_model_id"))
        for item in mappings
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    print(json.dumps({"same_model": same_model(args.provider, args.source, args.target)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
