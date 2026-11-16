#!/usr/bin/env python3
"""Generate and drift-check the prompt-library-for-startups entries from startups.aws.com.

Why
---
The skill carries a governance-approved subset of the AWS Startups prompt library
(`tools/prompt-library-approved.json`). Each entry must match its published page, except
for the security and plugin-fit changes recorded in
`skills/prompt-library-for-startups/references/prompt-library/local-changes.json`.
Hand-copying drifted silently, so the detail files are now generated from the published
pages and this script is the gate.

Modes
-----
--write   Fetch every approved page and rewrite the generated files.
--check   Fetch, regenerate in memory, and exit 1 if any file on disk differs (CI).
--report  Same comparison and exit codes as --check, but print a Markdown report to stdout
          (scheduled job: the status and the report come from one fetch).

--pages DIR reads `<slug>.html` files from DIR instead of the network (tests, offline).

Exit codes: 0 in sync, 1 drift or a local change that no longer applies, 2 fetch failure.

Published text is copied verbatim and wrapped in markdownlint-disable comments, because
reformatting it to satisfy the linter would itself be drift. Instruction blocks arrive as
Editor.js JSON and are converted to Markdown here; that conversion is the only formatting
this script applies.
"""

from __future__ import annotations

import argparse
import difflib
import html
import http.client
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = PLUGIN / "skills" / "prompt-library-for-startups"
ENTRIES = SKILL / "references" / "prompt-library"
APPROVED = PLUGIN / "tools" / "prompt-library-approved.json"
LOCAL_CHANGES = ENTRIES / "local-changes.json"
INDEX = SKILL / "references" / "prompt-library.md"
INDEX_START = "<!-- prompt-library-sync:start (generated; edit tools/prompt-library-sync.py) -->"
INDEX_END = "<!-- prompt-library-sync:end -->"
FULL_LIBRARY = "https://startups.aws.com/prompt-library"
BASE_URL = "https://startups.aws.com/prompt-library/"
USER_AGENT = "agent-toolkit-for-aws prompt-library-sync"
LINT_OFF = "<!-- markdownlint-disable -->"
LINT_ON = "<!-- markdownlint-enable -->"


class FetchError(Exception):
    pass


class LocalChangeError(Exception):
    pass


# --- Published page parsing -------------------------------------------------------------

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
_ROW = re.compile(rb"([0-9a-f]+):")
_REF = re.compile(r"\$([0-9a-f]+)")


def rsc_payload(page: str) -> str:
    """Join the React Server Components chunks a Next.js page streams into its HTML."""
    return "".join(json.loads('"' + chunk + '"') for chunk in _PUSH.findall(page))


def rsc_text_rows(payload: str) -> dict[str, str]:
    """Rows "<id>:T<hexlen>,<bytes>" carry long strings that other rows cite as "$<id>".

    Text rows have no terminator, so rows are walked in order using the byte length.
    """
    data = payload.encode("utf-8")
    rows: dict[str, str] = {}
    i = 0
    while i < len(data):
        m = _ROW.match(data, i)
        if not m:
            nl = data.find(b"\n", i)
            i = len(data) if nl < 0 else nl + 1
            continue
        start = m.end()
        if data[start : start + 1] == b"T":
            comma = data.index(b",", start)
            size = int(data[start + 1 : comma], 16)
            rows[m.group(1).decode()] = data[comma + 1 : comma + 1 + size].decode("utf-8", "replace")
            i = comma + 1 + size
        else:
            nl = data.find(b"\n", start)
            i = len(data) if nl < 0 else nl + 1
    return rows


def _enclosing_object(payload: str, key: str) -> dict | None:
    at = payload.find('"' + key + '"')
    while at >= 0:
        for start in range(at, -1, -1):
            if payload[start] != "{":
                continue
            depth, in_str, esc = 0, False, False
            for j in range(start, len(payload)):
                c = payload[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                elif c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(payload[start : j + 1])
                        except json.JSONDecodeError:
                            break
                        if key in obj:
                            return obj
                        break
        at = payload.find('"' + key + '"', at + 1)
    return None


def _resolve(value, rows: dict[str, str]):
    if isinstance(value, str):
        m = _REF.fullmatch(value)
        return rows.get(m.group(1), value) if m else value
    if isinstance(value, dict):
        return {k: _resolve(v, rows) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, rows) for v in value]
    return value


def parse_entry(page: str, slug: str) -> dict:
    payload = rsc_payload(page)
    obj = _enclosing_object(payload, "promptTextContent")
    if obj is None or obj.get("slug") != slug:
        raise FetchError(f"{slug}: page has no prompt-library entry for this slug")
    obj = _resolve(obj, rsc_text_rows(payload))
    text = obj.get("promptTextContent") or ""
    if _REF.fullmatch(text):
        raise FetchError(f"{slug}: prompt text reference {text} not found in page")
    return obj


def fetch_page(slug: str, pages_dir: Path | None) -> str:
    if pages_dir is not None:
        path = pages_dir / f"{slug}.html"
        if not path.exists():
            raise FetchError(f"{slug}: {path} not found")
        return path.read_text(encoding="utf-8")
    url = BASE_URL + slug
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        # OSError covers URLError, timeouts and connection resets; HTTPException covers
        # IncompleteRead. Both are transient fetch failures (exit 2), never drift (exit 1).
        except (OSError, http.client.HTTPException) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise FetchError(f"{slug}: could not fetch {url}: {last}")


# --- Editor.js instructions to Markdown -------------------------------------------------

_TAG = re.compile(r"<(/?)([a-zA-Z0-9]+)([^>]*)>")


def inline_md(text: str) -> str:
    def tag(m: re.Match) -> str:
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if name == "b" or name == "strong":
            return "**"
        if name == "i" or name == "em":
            return "*"
        if name == "code":
            return "`"
        if name == "br":
            return " "
        if name == "a":
            if closing:
                return "]" + "(" + _pending_href.pop() + ")" if _pending_href else ""
            href = re.search(r'href="([^"]*)"', attrs)
            _pending_href.append(html.unescape(href.group(1)) if href else "")
            return "["
        return ""

    _pending_href: list[str] = []
    out = _TAG.sub(tag, text)
    out = html.unescape(out).replace(" ", " ")
    out = re.sub(r"\*\*(\s*)\*\*", r"\1", out)
    return re.sub(r"[ \t]+", " ", out).strip()


def editorjs_md(blocks) -> str:
    if isinstance(blocks, str):
        blocks = json.loads(blocks)
    if isinstance(blocks, dict):
        blocks = blocks.get("blocks", [])
    parts: list[str] = []
    for block in blocks or []:
        kind, data = block.get("type"), block.get("data", {})
        if kind == "header":
            level = max(3, min(6, int(data.get("level", 3))))
            text = inline_md(data.get("text", ""))
            if text:
                parts.append("#" * level + " " + text)
        elif kind == "list":
            ordered = data.get("style") == "ordered"
            lines = []
            for n, item in enumerate(data.get("items", []), 1):
                text = inline_md(item if isinstance(item, str) else item.get("content", ""))
                if text:
                    lines.append(f"{n}. {text}" if ordered else f"- {text}")
            if lines:
                parts.append("\n".join(lines))
        else:
            text = inline_md(data.get("text", ""))
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def instructions_md(entry: dict) -> str:
    for key in ("promptInstructionsRichText", "agentInstructions"):
        if entry.get(key):
            return editorjs_md(entry[key])
    plain = (entry.get("promptInstructions") or "").strip()
    return plain


# --- Local changes ----------------------------------------------------------------------


def load_local_changes() -> dict[str, list[dict]]:
    if not LOCAL_CHANGES.exists():
        return {}
    by_slug: dict[str, list[dict]] = {}
    for change in json.loads(LOCAL_CHANGES.read_text(encoding="utf-8"))["changes"]:
        by_slug.setdefault(change["slug"], []).append(change)
    return by_slug


def _targeted(changes: list[dict], target: str) -> list[dict]:
    return [c for c in changes if c.get("target", "prompt") == target]


def apply_local_changes(slug: str, text: str, changes: list[dict]) -> str:
    """Each change replaces one exact passage of the published text.

    A passage that no longer appears exactly once means the published page changed under
    a recorded fix, which needs a human to re-review the fix, so it fails loudly.
    """
    for change in changes:
        count = text.count(change["find"])
        if count != 1:
            raise LocalChangeError(
                f"{slug}: local change '{change['id']}' expects its published passage once, found {count}"
            )
        text = text.replace(change["find"], change["replace"])
    return text


# --- Rendering --------------------------------------------------------------------------


def _frontmatter(fields: list[tuple[str, object]]) -> str:
    lines = ["---"]
    for key, value in fields:
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def _tags(entry: dict) -> list[str]:
    return [t.get("tagName") for t in entry.get("tags") or [] if t.get("tagName")]


def _verbatim(text: str) -> str:
    return f"{LINT_OFF}\n\n{text.strip()}\n\n{LINT_ON}"


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split on level-2 headings outside code fences; returns (heading, body) in order."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    fence = None
    for line in text.split("\n"):
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            if fence is None:
                fence = marker.group(1)[0] * len(marker.group(1))
            elif stripped.startswith(fence):
                fence = None
        if fence is None and line.startswith("## ") and not marker:
            sections.append((line[3:].strip(), [line]))
        else:
            sections[-1][1].append(line)
    return [(h, "\n".join(body)) for h, body in sections if h or "".join(body).strip()]


def _part_name(n: int, heading: str) -> str:
    if n == 0:
        return "00-overview.md"
    words = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-").split("-")
    name = ""
    for word in words:
        if len(name) + len(word) + 1 > 40:
            break
        name = f"{name}-{word}" if name else word
    return f"{n:02d}-{name}.md"


def shared_parts(sections: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Split the part files into the rules every phase depends on and the report appendices.

    Derived from the headings rather than listed by hand, so a shared section added on the
    published page lands in the load set (and the SKILL.md contract test) automatically.
    """
    shared, appendices = [], []
    for n, (heading, _) in enumerate(sections):
        name = _part_name(n, heading or "overview")
        upper = heading.upper()
        if upper.startswith("APPENDIX"):
            appendices.append(name)
        elif not upper.startswith("PHASE"):
            shared.append(name)
    return shared, appendices


def render(slug: str, kind: str, entry: dict, changes: list[dict], split: bool) -> dict[Path, str]:
    title = (entry.get("title") or slug).strip()
    url = BASE_URL + slug
    description = "\n".join(line.rstrip() for line in (entry.get("description") or "").strip().split("\n"))
    text = apply_local_changes(slug, entry.get("promptTextContent") or "", _targeted(changes, "prompt"))
    how = apply_local_changes(slug, instructions_md(entry), _targeted(changes, "instructions"))
    fields: list[tuple[str, object]] = [("source_url", url), ("title", title), ("kind", kind)]
    if kind == "agent":
        fields.append(("install_source", entry.get("ctaLink") or ""))
    fields.append(("tags", _tags(entry)))
    head = [_frontmatter(fields), "", f"## {title}", "", description]
    files: dict[Path, str] = {}

    if kind == "agent":
        body = head + ["", "## About this agent", "", _verbatim(text)]
        if how:
            body += ["", "## How to use?", "", _verbatim(how)]
        body += [
            "",
            "## Install",
            "",
            f"Install source: <{entry.get('ctaLink') or ''}>",
            "",
            "This agent installs separately from this skill, into the user's AI coding agent.",
        ]
        files[ENTRIES / f"{slug}.md"] = "\n".join(body) + "\n"
        return files

    if not split:
        body = head + ["", "## System Prompt", "", _verbatim(text)]
        if how:
            body += ["", "## How to use?", "", _verbatim(how)]
        files[ENTRIES / f"{slug}.md"] = "\n".join(body) + "\n"
        return files

    sections = split_sections(text)
    part_dir = ENTRIES / slug
    rows = []
    for n, (heading, section) in enumerate(sections):
        name = _part_name(n, heading or "overview")
        rows.append(f"| [{name}]({slug}/{name}) | {heading or 'Overview'} |")
        files[part_dir / name] = (
            f"{LINT_OFF}\n\n{section.strip()}\n\n{LINT_ON}\n"
        )
    shared, appendices = shared_parts(sections)
    body = head + [
        "",
        "## System Prompt",
        "",
        "This prompt is long, so it is split into one file per section below. Read the parts in",
        "order to reproduce the full System Prompt. To run or adapt one phase, load every shared",
        f"part ({', '.join(f'`{n}`' for n in shared)}), then only that phase's file.",
        f"For the report phase, also load the appendices ({', '.join(f'`{n}`' for n in appendices)}).",
        "",
        "| Part | Section |",
        "| ---- | ------- |",
        *rows,
    ]
    if how:
        body += ["", "## How to use?", "", _verbatim(how)]
    files[ENTRIES / f"{slug}.md"] = "\n".join(body) + "\n"
    return files


def _cell(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("|", "\\|").strip()


def render_index(current: str, meta: list[dict]) -> str:
    """Regenerate the prompt and agent tables between the markers; the rest stays hand-written."""
    if INDEX_START not in current or INDEX_END not in current:
        raise LocalChangeError(f"{INDEX.name}: missing the prompt-library-sync markers")
    prompts = [m for m in meta if m["kind"] == "prompt"]
    agents = [m for m in meta if m["kind"] == "agent"]
    block = [
        INDEX_START,
        "",
        "## Prompts — searchable index",
        "",
        f"This plugin carries the {len(prompts)} prompts and {len(agents)} downloadable agents approved for it. "
        f"The full AWS Startups prompt library is at <{FULL_LIBRARY}>; point the user there for anything not listed below.",
        "",
        "| Prompt | Summary | Keywords |",
        "| ------ | ------- | -------- |",
    ]
    for m in sorted(prompts, key=lambda m: m["title"].lower()):
        block.append(
            f"| [{_cell(m['title'])}](prompt-library/{m['slug']}.md) | {_cell(m['description'])} | {_cell(', '.join(m['tags']))} |"
        )
    block += [
        "",
        "## Downloadable agents",
        "",
        "These are installable agents, not copy-paste prompts. Each installs separately from this skill, into the "
        "user's AI coding agent, from the install source in its detail file.",
        "",
        "| Agent | Summary | Keywords |",
        "| ----- | ------- | -------- |",
    ]
    for m in sorted(agents, key=lambda m: m["title"].lower()):
        block.append(
            f"| [{_cell(m['title'])}](prompt-library/{m['slug']}.md) | {_cell(m['description'])} | {_cell(', '.join(m['tags']))} |"
        )
    block += ["", INDEX_END]
    before, rest = current.split(INDEX_START, 1)
    after = rest.split(INDEX_END, 1)[1]
    return before + "\n".join(block) + after


def reassemble(parts: list[str]) -> str:
    """Inverse of the split, for tests: strip the lint markers and join the sections."""
    out = []
    for part in parts:
        inner = part.strip()
        inner = inner[len(LINT_OFF) :] if inner.startswith(LINT_OFF) else inner
        inner = inner[: -len(LINT_ON)] if inner.endswith(LINT_ON) else inner
        out.append(inner.strip())
    return "\n".join(out)


# --- Driver -----------------------------------------------------------------------------


def build(pages_dir: Path | None) -> tuple[dict[Path, str], list[str]]:
    approved = json.loads(APPROVED.read_text(encoding="utf-8"))
    local = load_local_changes()
    known = {e["slug"] for e in approved["entries"]}
    errors = [f"local change for unapproved slug {s}" for s in local if s not in known]
    files: dict[Path, str] = {}
    meta: list[dict] = []
    for item in approved["entries"]:
        slug = item["slug"]
        try:
            entry = parse_entry(fetch_page(slug, pages_dir), slug)
            if entry.get("type") != item["kind"]:
                errors.append(f"{slug}: published as {entry.get('type')}, approved as {item['kind']}")
                continue
            files.update(render(slug, item["kind"], entry, local.get(slug, []), item.get("split", False)))
            meta.append(
                {
                    "slug": slug,
                    "kind": item["kind"],
                    "title": (entry.get("title") or slug).strip(),
                    "description": (entry.get("description") or "").strip(),
                    "tags": _tags(entry),
                }
            )
        except LocalChangeError as exc:
            errors.append(str(exc))
    if not errors:
        try:
            files[INDEX] = render_index(INDEX.read_text(encoding="utf-8"), meta)
        except LocalChangeError as exc:
            errors.append(str(exc))
    return files, errors


def compare(expected: dict[Path, str]) -> list[str]:
    on_disk = {p for p in ENTRIES.rglob("*.md")}
    problems = []
    for path in sorted(set(expected) | on_disk):
        rel = path.relative_to(PLUGIN)
        if path not in expected:
            problems.append(f"{rel}: not an approved entry (remove it, or add it to {APPROVED.name})")
        elif not path.exists():
            problems.append(f"{rel}: missing")
        else:
            current = path.read_text(encoding="utf-8")
            if current != expected[path]:
                diff = list(
                    difflib.unified_diff(
                        current.splitlines(), expected[path].splitlines(), "on disk", "published", n=0, lineterm=""
                    )
                )
                changed = sum(1 for d in diff if d[:1] in "+-" and d[:3] not in ("+++", "---"))
                problems.append(f"{rel}: differs from the published page ({changed} lines)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--report", action="store_true")
    parser.add_argument("--pages", type=Path, help="read <slug>.html from this directory")
    args = parser.parse_args(argv)

    try:
        files, errors = build(args.pages)
    except FetchError as exc:
        print(f"prompt-library-sync: {exc}", file=sys.stderr)
        return 2

    if args.write:
        if errors:
            for e in errors:
                print(f"ERROR {e}", file=sys.stderr)
            return 1
        for path in ENTRIES.rglob("*.md"):
            if path not in files:
                path.unlink()
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for d in sorted((p for p in ENTRIES.rglob("*") if p.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        print(f"prompt-library-sync: wrote {len(files)} files")
        return 1 if errors else 0

    problems = errors + compare(files)
    if args.report:
        print("## Prompt library drift report\n")
        print(f"Compared {len(files)} generated files against {BASE_URL}.\n")
        if not problems:
            print("No drift: every approved entry matches its published page.")
        else:
            print("Run `python3 tools/prompt-library-sync.py --write` and review the diff:\n")
            print("\n".join(f"- {p}" for p in problems))
        return 1 if problems else 0
    for p in problems:
        print(f"DRIFT {p}", file=sys.stderr)
    if problems:
        print(
            "prompt-library-sync: run `python3 tools/prompt-library-sync.py --write` from "
            "plugins/aws-startup-advisor and review the diff",
            file=sys.stderr,
        )
        return 1
    print(f"prompt-library-sync: {len(files)} files match the published pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
