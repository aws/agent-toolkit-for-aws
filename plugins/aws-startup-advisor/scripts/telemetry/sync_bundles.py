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
    problems = []
    for name in (".claude-plugin/plugin.json", ".cursor-plugin/plugin.json", ".codex-plugin/plugin.json"):
        manifest = plugin / name
        if manifest.is_file():
            host_version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
            if host_version != version:
                problems.append("%s: version %r does not match plugin.json version %r" % (name, host_version, version))
    if problems:
        return problems  # Refuse to generate bundles from conflicting version metadata.

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
    for skill in SKILLS:
        target = plugin / "skills" / skill / "references/vendored/telemetry"
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.relative_to(target).parts and path.suffix == ".pyc":
                continue
            if path.relative_to(target).as_posix() not in files:
                problems.append("Unexpected bundle file: %s" % path.relative_to(plugin))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    problems = sync(write=args.write)
    if problems:
        print("Telemetry manifests or bundles are out of sync:")
        print("\n".join(problems))
        print("Ensure manifest versions agree, then run sync_bundles.py --write.")
        print("Review and remove unexpected bundle files manually; --write does not delete them.")
        return 1
    print("Telemetry bundles and DSL copies: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
