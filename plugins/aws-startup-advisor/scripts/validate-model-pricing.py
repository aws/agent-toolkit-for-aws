#!/usr/bin/env python3
"""Require a numeric Active cache row for every default Anthropic candidate."""

import json
import math
import re
import sys
from pathlib import Path


def validate_model_pricing(plugin_root: Path) -> list[str]:
    skills = plugin_root / "skills"
    selector = (skills / "agent-advisor/scripts/model_recommendation.py").read_text()
    match = re.search(r'^DEFAULT_CATALOG = MODELS_DIR / "([^"]+)"', selector, re.MULTILINE)
    if not match:
        raise ValueError("Cannot locate the default Anthropic catalog.")
    catalog = json.loads((skills / "agent-advisor/references/models" / match[1]).read_text())
    errors = []
    for cloud in ("gcp-to-aws", "azure-to-aws"):
        cache = skills / cloud / "references/shared/pricing-cache.md"
        priced = set()
        for line in cache.read_text().splitlines():
            if not line.startswith("|"):
                continue
            row = [cell.strip() for cell in line.split("|")[1:-1]]
            if len(row) < 8 or not re.match(r"active\b", row[7], re.IGNORECASE):
                continue
            try:
                rates = [float(row[3]), float(row[4])]
            except ValueError:
                continue
            if all(math.isfinite(rate) and rate > 0 for rate in rates):
                priced.add(re.sub(r"^(us|eu|au|jp|global)\.", "", row[1]))
        for model in catalog["models"].values():
            model_id = model["paths"]["runtime_converse"]["model_id"]
            if model_id not in priced:
                errors.append(f"{cloud}: candidate {model_id} has no numeric Active price row.")
    return errors


def main() -> int:
    try:
        errors = validate_model_pricing(Path(__file__).resolve().parent.parent)
    except (OSError, ValueError, KeyError) as exc:
        errors = [str(exc)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Model pricing coverage: all Anthropic candidates have numeric Active cache rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
