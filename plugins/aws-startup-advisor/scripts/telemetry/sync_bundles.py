#!/usr/bin/env python3
"""Generate/check self-contained telemetry bundles without moving the hook code.

    python3 scripts/telemetry/sync_bundles.py --write
    python3 scripts/telemetry/sync_bundles.py --check

Only the listed runtime files are distributed. Tests, caches, and unrelated
scripts never enter a skill bundle. Also checks the existing DSL copies whose
telemetry boundary instructions are shared by Heroku and Azure.
"""

import argparse
import json
from pathlib import Path

TELEMETRY = Path(__file__).resolve().parent
PLUGIN = TELEMETRY.parents[1]
SKILLS = ("azure-to-aws", "gcp-to-aws", "heroku-to-aws", "llm-to-bedrock")
RUNTIME_FILES = (
    "cli.py",
    "PROTOCOL.md",
    "consent/record.py",
    "consent/notice.py",
    "consent/cli.py",
    "consent/accept.py",
    "consent/opt_out.py",
    "metric_emission/client.py",
    "metric_emission/migration.py",
    "metric_emission/migration_attributes.py",
)


def sync(plugin=PLUGIN, write=False):
    plugin = Path(plugin)
    telemetry = plugin / "scripts/telemetry"
    version = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))["version"]
    files = {name: (telemetry / name).read_bytes() for name in RUNTIME_FILES}
    files["version.json"] = (json.dumps({"version": version}, indent=2) + "\n").encode()
    expected = []
    for skill in SKILLS:
        target = plugin / "skills" / skill / "references/vendored/telemetry"
        expected.extend((target / name, content) for name, content in files.items())
    interpreter = (plugin / "skills/shared/dsl/INTERPRETER.md").read_bytes()
    for skill in ("agent-advisor", "azure-to-aws", "heroku-to-aws"):
        expected.append((plugin / "skills" / skill / "references/vendored/dsl/INTERPRETER.md", interpreter))
    problems = []
    for path, content in expected:
        if path.is_file() and path.read_bytes() == content:
            continue
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        else:
            problems.append(str(path.relative_to(plugin)))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    problems = sync(write=args.write)
    if problems:
        print("Telemetry bundles are missing or out of sync; run sync_bundles.py --write:")
        print("\n".join(problems))
        return 1
    print("Telemetry bundles and DSL copies: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
