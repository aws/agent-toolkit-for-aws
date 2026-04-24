#!/usr/bin/env python3
"""Validate manifests, skill frontmatter, and MCP configs.

Stdlib-only. Exit 0 on success, non-zero on failure.

Usage:
    python3 tools/validate.py              # validate everything
    python3 tools/validate.py --plugin X   # validate one plugin
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]+(-[a-z0-9]+)*$")

errors: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)
    print(f"  ERROR: {msg}", file=sys.stderr)


def validate_json(path: Path, required_keys: list[str]) -> dict | None:
    """Validate a JSON file exists, parses, and has required keys."""
    if not path.exists():
        error(f"Missing file: {path.relative_to(REPO_ROOT)}")
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        error(f"Invalid JSON in {path.relative_to(REPO_ROOT)}: {e}")
        return None
    for key in required_keys:
        if key not in data:
            error(f"Missing key '{key}' in {path.relative_to(REPO_ROOT)}")
    return data


def validate_skill_frontmatter(skill_md: Path) -> None:
    """Validate SKILL.md has valid YAML frontmatter with name and description."""
    text = skill_md.read_text()
    if not text.startswith("---\n"):
        error(f"Missing YAML frontmatter in {skill_md.relative_to(REPO_ROOT)}")
        return

    end = text.find("\n---\n", 4)
    if end == -1:
        error(f"Unterminated frontmatter in {skill_md.relative_to(REPO_ROOT)}")
        return

    frontmatter = text[4:end]
    # Simple key: value parsing (stdlib-only, no yaml import)
    # Handles multi-line YAML values (lines starting with spaces are continuations)
    fm = {}
    current_key = None
    for line in frontmatter.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            value = value.strip().strip('"').strip("'")
            # Handle YAML block scalar indicators (> or |)
            if value in (">", "|", ">-", "|-"):
                value = ""
            fm[key.strip()] = value
            current_key = key.strip()
        elif current_key and line.startswith("  "):
            # Continuation line — append to current key
            fm[current_key] = (fm[current_key] + " " + line.strip()).strip()

    name = fm.get("name")
    desc = fm.get("description")

    if not name:
        error(f"Missing 'name' in frontmatter: {skill_md.relative_to(REPO_ROOT)}")
    elif not KEBAB_RE.match(name):
        error(f"Name '{name}' is not kebab-case in {skill_md.relative_to(REPO_ROOT)}")
    elif len(name) > 64:
        error(f"Name exceeds 64 chars in {skill_md.relative_to(REPO_ROOT)}")
    else:
        expected_dir = skill_md.parent.name
        if name != expected_dir:
            error(f"Name '{name}' does not match directory '{expected_dir}' in {skill_md.relative_to(REPO_ROOT)}")

    if not desc:
        error(f"Missing 'description' in frontmatter: {skill_md.relative_to(REPO_ROOT)}")
    elif len(desc) < 20:
        error(f"Description too short (<20 chars) in {skill_md.relative_to(REPO_ROOT)}")


def validate_marketplace(path: Path, label: str) -> None:
    """Validate a marketplace manifest and check plugin source paths."""
    print(f"Validating {label} marketplace: {path.relative_to(REPO_ROOT)}")
    data = validate_json(path, ["name", "plugins"])
    if data is None:
        return
    for plugin in data.get("plugins", []):
        if "name" not in plugin:
            error(f"Plugin missing 'name' in {path.relative_to(REPO_ROOT)}")
            continue
        # Resolve source path (relative to repo root, not manifest location)
        if isinstance(plugin.get("source"), dict):
            source = plugin["source"].get("path", "")
        else:
            source = plugin.get("source", "")
        if source:
            resolved = (REPO_ROOT / source).resolve()
            if not resolved.is_dir():
                error(f"Plugin source '{source}' does not exist for '{plugin['name']}'")


def validate_plugin(plugin_dir: Path) -> None:
    """Validate a single plugin's manifests and skills."""
    name = plugin_dir.name
    print(f"Validating plugin: {name}")

    # Claude Code manifest
    validate_json(plugin_dir / ".claude-plugin" / "plugin.json", ["name"])

    # Codex manifest
    validate_json(
        plugin_dir / ".codex-plugin" / "plugin.json",
        ["name", "version", "description", "author", "interface"],
    )

    # MCP config
    mcp_path = plugin_dir / ".mcp.json"
    if mcp_path.exists():
        data = validate_json(mcp_path, ["mcpServers"])
        if data:
            for srv_name, srv in data.get("mcpServers", {}).items():
                srv_type = srv.get("type", "stdio")
                if srv_type == "stdio" and "command" not in srv:
                    error(f"MCP server '{srv_name}' is stdio but missing 'command'")
                elif srv_type == "http" and "url" not in srv:
                    error(f"MCP server '{srv_name}' is http but missing 'url'")

    # Skills in this plugin
    skills_dir = plugin_dir / "skills"
    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if skill_dir.is_dir() and skill_md.exists():
                validate_skill_frontmatter(skill_md)


def validate_top_level_skills() -> None:
    """Validate all skills in the top-level skills/ directory."""
    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.is_dir():
        return
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            print(f"Validating skill: {skill_dir.name}")
            validate_skill_frontmatter(skill_md)
        else:
            error(f"Skill directory missing SKILL.md: {skill_dir.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate repo manifests and skills")
    parser.add_argument("--plugin", help="Validate only this plugin")
    args = parser.parse_args()

    plugins_dir = REPO_ROOT / "plugins"

    if args.plugin:
        plugin_dir = plugins_dir / args.plugin
        if not plugin_dir.is_dir():
            print(f"Plugin not found: {args.plugin}", file=sys.stderr)
            sys.exit(1)
        validate_plugin(plugin_dir)
    else:
        # Marketplace manifests
        validate_marketplace(
            REPO_ROOT / ".claude-plugin" / "marketplace.json", "Claude Code"
        )
        validate_marketplace(
            REPO_ROOT / ".agents" / "plugins" / "marketplace.json", "Codex"
        )

        # All plugins
        if plugins_dir.is_dir():
            for plugin_dir in sorted(plugins_dir.iterdir()):
                if plugin_dir.is_dir():
                    validate_plugin(plugin_dir)

        # Top-level skills
        validate_top_level_skills()

    if errors:
        print(f"\nValidation failed with {len(errors)} error(s).", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll validations passed.")


if __name__ == "__main__":
    main()
