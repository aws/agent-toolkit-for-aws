#!/usr/bin/env python3
"""Validate Agent Plugins v1.0.0 conformance for plugins/.

Checks:
  1. No symlinks anywhere under plugins/.
  2. Every plugin.json and mcp.json validates against the vendored canonical
     schemas. They are vendored because the spec forbids retrieving a schema
     while loading a plugin (§7.2.1), and CI should not need network access.
  3. Rules the schemas cannot express: path containment against the resolved
     plugin root (§4.1), placeholder restrictions (§9.2), and MCP url and
     header rules (§7.2.1).
  4. Every skill in plugins/*/skills/ passes the Agent Skills field, length,
     and naming rules.

Requires jsonschema and pyyaml.

Usage:
    python3 tools/validate_spec.py
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "tools" / "schemas" / "1.0.0"

AP_VERSION = "1.0.0"
PLUGIN_SCHEMA_ID = f"https://agent-plugins.org/schemas/{AP_VERSION}/plugin.schema.json"
MCP_SCHEMA_ID = f"https://agent-plugins.org/schemas/{AP_VERSION}/mcp.schema.json"

ALLOWED_SKILL_FIELDS = {
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
}
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500

errors: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)
    print(f"  ERROR: {msg}", file=sys.stderr)


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def validate_against_schema(doc: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        path = "/".join(str(x) for x in e.path) or "<root>"
        error(f"{label}: {e.message} (at {path})")


def iter_strings(node: object, prefix: str):
    """Yield every (label, string) leaf under a JSON value."""
    if isinstance(node, str):
        yield prefix, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from iter_strings(v, f"{prefix}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from iter_strings(v, f"{prefix}[{i}]")


def check_containment(rel_path: str, label: str, plugin_dir: Path) -> None:
    """Spec §4.1: a plugin-relative path is './'-prefixed and, once the
    filesystem resolves it, stays inside the resolved plugin root.

    Resolution matters: a lexical check passes a path that reaches outside
    the root through a symlink.
    """
    if "\\" in rel_path:
        error(f"{label}: path must use '/' separators (got {rel_path!r})")
        return
    if not rel_path.startswith("./"):
        error(f"{label}: plugin-relative path must begin with './' (got {rel_path!r})")
        return
    if ".." in Path(rel_path).parts:
        error(f"{label}: path escapes the plugin root ({rel_path!r})")
        return
    root = plugin_dir.resolve()
    target = (root / rel_path[2:]).resolve()
    if target != root and root not in target.parents:
        error(f"{label}: path resolves outside the plugin root ({rel_path!r} -> {target})")


def validate_plugin_dir(plugin_dir: Path, plugin_schema: dict, mcp_schema: dict) -> None:
    rel = plugin_dir.relative_to(REPO_ROOT)
    print(f"Validating plugin: {rel}")

    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        error(f"{rel}: missing required root plugin.json (spec §5.1)")
        return
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        error(f"{rel}/plugin.json: invalid JSON: {e}")
        return

    validate_against_schema(manifest, plugin_schema, f"{rel}/plugin.json")

    if manifest.get("$schema") != PLUGIN_SCHEMA_ID:
        error(f"{rel}/plugin.json: $schema must be {PLUGIN_SCHEMA_ID}")
    if manifest.get("name") != plugin_dir.name:
        error(f"{rel}/plugin.json: name {manifest.get('name')!r} != directory {plugin_dir.name!r}")

    # Extension namespaces must be reverse-domain and have a matching directory
    # when they declare file paths (spec §8.2).
    extensions = manifest.get("extensions")
    if extensions is not None and not isinstance(extensions, dict):
        error(f"{rel}/plugin.json: extensions must be an object (spec §8.1)")
        extensions = {}
    for ns, value in (extensions or {}).items():
        if "." not in ns:
            error(f"{rel}/plugin.json: extension namespace {ns!r} is not reverse-domain (spec §8)")
        # Every string leaf is a candidate path, at any nesting depth. Values
        # that merely look path-like are checked too: a namespace owner can
        # nest pointers arbitrarily, so type is the only reliable filter.
        for label, val in iter_strings(value, f"{rel}/plugin.json extensions.{ns}"):
            if not looks_like_path(val):
                continue
            check_containment(val, label, plugin_dir)
            if val.startswith("./") and not (plugin_dir / val[2:]).exists():
                error(f"{label}: points at missing {val}")

    mcp_path = plugin_dir / "mcp.json"
    if mcp_path.exists():
        try:
            mcp = json.loads(mcp_path.read_text())
        except json.JSONDecodeError as e:
            error(f"{rel}/mcp.json: invalid JSON: {e}")
        else:
            validate_against_schema(mcp, mcp_schema, f"{rel}/mcp.json")
            if mcp.get("$schema") != MCP_SCHEMA_ID:
                error(f"{rel}/mcp.json: $schema must be {MCP_SCHEMA_ID}")
            for srv_name, srv in (mcp.get("mcpServers") or {}).items():
                validate_server(srv_name, srv, f"{rel}/mcp.json", plugin_dir)

    skills_dir = plugin_dir / "skills"
    if skills_dir.exists() and not skills_dir.is_dir():
        error(f"{rel}: skills exists but is not a directory (spec §6.2)")


PLACEHOLDER_RE = re.compile(r"\$\{([^}]*)\}")
RESERVED = {"PLUGIN_ROOT", "PLUGIN_DATA"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def looks_like_path(val: str) -> bool:
    """Values a client could resolve against the plugin root."""
    return (
        val.startswith("./")
        or val.startswith("../")
        or val.startswith("/")
        or val.startswith("\\")
        or val.startswith("${PLUGIN_ROOT}")
        or val.startswith("${PLUGIN_DATA}")
        or "\\" in val
    )


def check_runtime_path(val: str, label: str, plugin_dir: Path) -> None:
    """Containment for MCP runtime values, which become a subprocess.

    A ${PLUGIN_ROOT} or ${PLUGIN_DATA} prefix stands in for the root, so
    strip it and check the remainder for traversal.
    """
    for placeholder in ("${PLUGIN_ROOT}", "${PLUGIN_DATA}"):
        if val.startswith(placeholder):
            remainder = val[len(placeholder) :].lstrip("/")
            check_containment(f"./{remainder}" if remainder else "./", label, plugin_dir)
            return
    check_containment(val, label, plugin_dir)


def validate_server(name: str, srv: dict, label: str, plugin_dir: Path) -> None:
    """Spec §7.2.1 and §9.2 rules the JSON Schema cannot express."""
    if not isinstance(srv, dict):
        error(f"{label}: server {name!r} must be an object")
        return
    stype = srv.get("type")
    if stype == "stdio":
        cmd = srv.get("command")
        if not isinstance(cmd, str):
            error(f"{label}: server {name!r} command must be a string")
            cmd = ""
        if PLACEHOLDER_RE.search(cmd):
            error(f"{label}: server {name!r} command must not use placeholders (spec §7.2.1)")
        if not (cmd.startswith("./") or "/" not in cmd):
            error(f"{label}: server {name!r} command must be a bare name or './' path")
        if cmd.startswith("./"):
            check_containment(cmd, f"{label} server {name!r} command", plugin_dir)
        env = srv.get("env")
        if env is not None and not isinstance(env, dict):
            error(f"{label}: server {name!r} env must be an object")
            env = {}
        for key in ("PLUGIN_ROOT", "PLUGIN_DATA"):
            if key in (env or {}):
                error(f"{label}: server {name!r} env must not set {key} (spec §9.2)")
        for field in ("args", "cwd"):
            values = srv.get(field)
            values = values if isinstance(values, list) else ([values] if values else [])
            for v in values:
                if not isinstance(v, str):
                    error(f"{label}: server {name!r} {field} entries must be strings")
                    continue
                for ph in PLACEHOLDER_RE.findall(v):
                    if ph not in RESERVED:
                        error(f"{label}: server {name!r} {field} uses unsupported placeholder ${{{ph}}} (spec §9.2)")
                # These values become a subprocess path, so containment is
                # enforced on anything resolvable against the plugin root.
                if looks_like_path(v):
                    check_runtime_path(v, f"{label} server {name!r} {field}", plugin_dir)
    elif stype in ("streamable-http", "sse"):
        url = srv.get("url")
        if not isinstance(url, str):
            error(f"{label}: server {name!r} url must be a string")
            return
        if PLACEHOLDER_RE.search(url):
            error(f"{label}: server {name!r} url must not use expansion (spec §7.2.1)")
        parsed = urlsplit(url)
        if parsed.fragment or parsed.username or parsed.password:
            error(f"{label}: server {name!r} url must not contain user info or a fragment (spec §7.2.1)")
        if parsed.scheme != "https" and parsed.hostname not in LOOPBACK_HOSTS:
            error(f"{label}: server {name!r} non-loopback url must use HTTPS (spec §7.2.1)")
        headers = srv.get("headers")
        if headers is not None and not isinstance(headers, dict):
            error(f"{label}: server {name!r} headers must be an object")
            headers = {}
        lowered = [h.lower() for h in (headers or {})]
        if len(lowered) != len(set(lowered)):
            error(f"{label}: server {name!r} has duplicate header names under different casing")
        for hname, hval in (headers or {}).items():
            if isinstance(hval, str) and PLACEHOLDER_RE.search(hval):
                error(f"{label}: server {name!r} header {hname!r} must not use expansion (spec §7.2.1)")
            if hname.lower() == "authorization":
                error(f"{label}: server {name!r} must not embed credentials in headers (spec §7.2.1)")


def parse_frontmatter(text: str) -> dict | None:
    """Parse frontmatter with a real YAML parser.

    A hand-rolled line scanner cannot see the failure that matters most here:
    a blank line inside a block scalar silently ends it and turns the next
    prose line into a bogus top-level key.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    raw = text[4:end]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return {"__yaml_error__": str(e).splitlines()[0]}
    return data if isinstance(data, dict) else {"__yaml_error__": "frontmatter is not a mapping"}


def validate_skill(skill_md: Path) -> None:
    rel = skill_md.relative_to(REPO_ROOT)
    try:
        raw = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        error(f"{rel}: cannot read as UTF-8: {e}")
        return
    fm = parse_frontmatter(raw)
    if fm is None:
        error(f"{rel}: missing or unterminated YAML frontmatter")
        return
    if "__yaml_error__" in fm:
        error(f"{rel}: invalid YAML frontmatter: {fm['__yaml_error__']}")
        return

    extra = set(fm) - ALLOWED_SKILL_FIELDS
    if extra:
        error(f"{rel}: non-spec frontmatter field(s): {', '.join(sorted(extra))}")

    name = str(fm.get("name", "") or "")
    if not name:
        error(f"{rel}: missing required 'name'")
    else:
        n = unicodedata.normalize("NFKC", name)
        if len(n) > MAX_NAME:
            error(f"{rel}: name exceeds {MAX_NAME} chars")
        if n != n.lower():
            error(f"{rel}: name must be lowercase")
        if n.startswith("-") or n.endswith("-"):
            error(f"{rel}: name must not start or end with a hyphen")
        if "--" in n:
            error(f"{rel}: name must not contain consecutive hyphens")
        if not all(c.isalnum() or c == "-" for c in n):
            error(f"{rel}: name has invalid characters")
        if n != unicodedata.normalize("NFKC", skill_md.parent.name):
            error(f"{rel}: name {name!r} != directory {skill_md.parent.name!r}")

    desc = str(fm.get("description", "") or "").strip()
    if not desc:
        error(f"{rel}: missing required 'description'")
    elif len(desc) > MAX_DESCRIPTION:
        error(f"{rel}: description is {len(desc)} chars, over the {MAX_DESCRIPTION} limit")

    compat = fm.get("compatibility")
    if compat and len(str(compat)) > MAX_COMPATIBILITY:
        error(f"{rel}: compatibility exceeds {MAX_COMPATIBILITY} chars")

    tools = fm.get("allowed-tools")
    if tools is not None and not isinstance(tools, str):
        error(f"{rel}: allowed-tools must be a space-separated string, not a sequence")



def reject_symlinks() -> None:
    """A plugin tree of Markdown and JSON has no use for symlinks, and one
    pointing outside the repository would make the checks below read files
    that are not part of the package. Refuse them outright."""
    plugins_dir = REPO_ROOT / "plugins"
    if not plugins_dir.is_dir():
        return
    for path in sorted(plugins_dir.rglob("*")):
        if path.is_symlink():
            error(f"{path.relative_to(REPO_ROOT)}: symlinks are not allowed under plugins/")


def main() -> None:
    plugin_schema = load_schema("plugin.schema.json")
    mcp_schema = load_schema("mcp.schema.json")

    reject_symlinks()

    plugins_dir = REPO_ROOT / "plugins"
    for plugin_dir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
        # One malformed plugin must not stop the others from being checked.
        try:
            validate_plugin_dir(plugin_dir, plugin_schema, mcp_schema)
        except Exception as e:  # noqa: BLE001 - report and keep going
            error(f"{plugin_dir.relative_to(REPO_ROOT)}: validator raised {type(e).__name__}: {e}")

    print("Validating skills")
    for skill_md in sorted(REPO_ROOT.glob("plugins/*/skills/*/SKILL.md")):
        try:
            validate_skill(skill_md)
        except Exception as e:  # noqa: BLE001 - report and keep going
            error(f"{skill_md.relative_to(REPO_ROOT)}: validator raised {type(e).__name__}: {e}")

    if errors:
        print(f"\nSpec validation failed with {len(errors)} error(s).", file=sys.stderr)
        sys.exit(1)
    print("\nAll Agent Plugins v1.0.0 checks passed.")


if __name__ == "__main__":
    main()
