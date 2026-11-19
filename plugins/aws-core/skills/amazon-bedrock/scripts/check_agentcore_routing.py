#!/usr/bin/env python3
"""Offline checks for the AgentCore task-to-component routing table.

The table lives in references/agentcore-runtime.md under the heading
"Task-to-Component Routing". These checks keep it honest as rows, components
and reference files change:

1. Structure: the table exists, has the three expected columns, and no two
   rows share the same task text.
2. Components: every component named in the table is listed in the
   "AgentCore Services" table in SKILL.md, so a new component is added to
   both places or neither.
3. Links: every relative link in the table resolves to a file in this skill,
   and every absolute link points at AWS documentation or aws.amazon.com.
4. Routing: a fixture of user prompts (the words users actually type) each
   route to exactly one expected component. Routing is a plain word-overlap
   score between the prompt and each row's task text, so a row only wins when
   its wording carries the terms users use for that job.

Stdlib only. Run from any directory:

    python3 skills/core-skills/amazon-bedrock/scripts/check_agentcore_routing.py

Exit code is 0 when every check passes and 1 otherwise. Pass --verbose to
print the routing score for each fixture.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
RUNTIME_REF = SKILL_DIR / "references" / "agentcore-runtime.md"
SKILL_MD = SKILL_DIR / "SKILL.md"

ROUTING_HEADING = "## Task-to-Component Routing"
SERVICES_HEADING = "## AgentCore Services"
EXPECTED_COLUMNS = ["Task the user describes", "Component", "Read first"]
ALLOWED_URL_PREFIXES = (
    "https://docs.aws.amazon.com/bedrock-agentcore/",
    "https://aws.amazon.com/bedrock/agentcore/",
)

# Prompts in the users' own words, each with the one component it should
# route to. Add a fixture whenever a row is added or reworded.
ROUTING_FIXTURES: list[tuple[str, str]] = [
    ("get this agent hosted with the least infrastructure for us to own - no cluster, no queue, no fleet to patch", "Runtime"),
    ("this agent works on my laptop - deploy it for real users, you pick the platform", "Runtime"),
    ("some agent tasks run for hours and the current host kills them at the request timeout - fix the execution model", "Runtime"),
    ("the agent runs on a vm someone set up by hand - move it to a real deployment target with zero-downtime releases", "Runtime"),
    ("keep the browser chat streaming in real time after we move the agent off the laptop", "Runtime"),
    ("process, container, or microvm isolation for agent sessions - what does each protect against", "Runtime"),
    ("the agent sits idle waiting on model calls most of the time - stop paying for an always-on fleet", "Runtime"),
    ("this agent's loop is custom code nobody wants to own anymore - move it onto a managed loop and keep our tools and prompts", "Harness"),
    ("we need thirty internal agents for different teams this quarter - pick an approach where each one is a declaration, not a codebase", "Harness"),
    ("run Claude Code as a hosted service for the team with its own filesystem and shell", "Harness"),
    ("the agent forgets everything between sessions - add memory so it remembers user preferences and facts", "Memory"),
    ("migrate our homegrown memory tables for conversations and preferences to a managed store", "Memory"),
    ("expose our existing REST APIs and Lambda functions as tools the agent can call without rewriting the services", "Gateway"),
    ("the agent needs to read a user's Google calendar on their behalf - handle the OAuth tokens, refresh and revoke per user", "Identity"),
    ("the agent writes Python for data analysis and we run it in-process - run generated code safely in a sandbox", "Code Interpreter"),
    ("the agent has to log in to a vendor portal, fill the form and download the invoice", "Browser"),
    ("we have no idea what the agent does in production - add tracing so we can see every step and tool call", "Observability"),
    ("block the release when the agent's answers regress - score quality with an LLM judge in CI", "Evaluations"),
    ("only allow the agent to call refund tools under certain conditions and deny everything else with rules outside the model", "Policy"),
    ("teams keep building duplicate agents and MCP servers - catalog them so people can discover and approve what exists", "Registry"),
    ("let the agent pay for x402-protected APIs with a spending limit", "Payments"),
]

STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "can", "do", "each",
    "for", "from", "has", "have", "how", "if", "in", "into", "is", "it", "its",
    "no", "not", "of", "on", "one", "or", "our", "out", "so", "that", "the",
    "their", "them", "then", "they", "this", "to", "us", "we", "what", "when",
    "which", "with", "you", "your", "agent", "agents", "the", "use", "using",
}

errors: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)
    print(f"  ERROR: {msg}", file=sys.stderr)


def section(text: str, heading: str) -> str:
    """Return the text of one '## ' section, up to the next '## ' heading."""
    start = text.find(heading)
    if start == -1:
        return ""
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def parse_table(block: str) -> tuple[list[str], list[list[str]]]:
    """Parse the first pipe table in a markdown block into header + rows."""
    lines = [ln.strip() for ln in block.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for ln in lines[2:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) != len(header):
            error(f"Row has {len(cells)} cells, expected {len(header)}: {ln[:80]}")
            continue
        rows.append(cells)
    return header, rows


def strip_markup(cell: str) -> str:
    """Remove bold/italic markers and link targets, keeping link text."""
    cell = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell)
    return cell.replace("**", "").replace("*", "").replace("`", "").strip()


def words(text: str) -> set[str]:
    """Lowercase word set with stopwords dropped and simple plurals folded."""
    out = set()
    for w in re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower()):
        w = w.strip("'-")
        if len(w) < 3 or w in STOPWORDS:
            continue
        if w.endswith("ies"):
            w = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def check_structure(header: list[str], rows: list[list[str]]) -> None:
    if header != EXPECTED_COLUMNS:
        error(f"Routing table columns are {header}, expected {EXPECTED_COLUMNS}")
    seen: dict[str, int] = {}
    for i, row in enumerate(rows, start=1):
        task = strip_markup(row[0])
        if not task:
            error(f"Row {i} has an empty task cell")
        if task in seen:
            error(f"Row {i} repeats the task text of row {seen[task]}")
        seen[task] = i
        if not strip_markup(row[1]):
            error(f"Row {i} has an empty component cell")
        if not row[2]:
            error(f"Row {i} has an empty 'Read first' cell")


def skill_components() -> set[str]:
    """Component names from the AgentCore Services table in SKILL.md."""
    block = section(SKILL_MD.read_text(encoding="utf-8"), SERVICES_HEADING)
    _, rows = parse_table(block)
    names = set()
    for row in rows:
        name = strip_markup(row[0])
        if name.lower().startswith("not sure"):
            continue  # the pointer row back to this table
        names.add(name)
    return names


def check_components(rows: list[list[str]]) -> None:
    known = skill_components()
    if not known:
        error(f"Could not read the '{SERVICES_HEADING}' table in SKILL.md")
        return
    for i, row in enumerate(rows, start=1):
        component = strip_markup(row[1])
        if component not in known:
            error(
                f"Row {i} routes to '{component}', which is not listed in the "
                f"SKILL.md AgentCore Services table ({sorted(known)})"
            )


def check_links(rows: list[list[str]]) -> None:
    link_re = re.compile(r"\]\(([^)]+)\)")
    for i, row in enumerate(rows, start=1):
        for target in link_re.findall(row[2]):
            if target.startswith(("http://", "https://")):
                if not target.startswith(ALLOWED_URL_PREFIXES):
                    error(f"Row {i} links outside AWS documentation: {target}")
                continue
            path = (RUNTIME_REF.parent / target.split("#", 1)[0]).resolve()
            if not path.is_file():
                error(f"Row {i} links to a missing file: {target}")


def check_pointer_row() -> None:
    """SKILL.md must point at this table with a link that resolves."""
    block = section(SKILL_MD.read_text(encoding="utf-8"), SERVICES_HEADING)
    anchor = "references/agentcore-runtime.md#task-to-component-routing"
    if anchor not in block:
        error(f"SKILL.md AgentCore Services table has no pointer row linking to {anchor}")
    heading_anchor = ROUTING_HEADING[3:].lower().replace(" ", "-")
    if heading_anchor != anchor.split("#", 1)[1]:
        error(f"Routing heading anchor '{heading_anchor}' does not match the SKILL.md link")


def route(prompt: str, rows: list[list[str]]) -> list[tuple[int, str]]:
    """Score every row against the prompt; return (score, component) sorted high to low."""
    pw = words(prompt)
    scored = []
    for row in rows:
        task_words = words(strip_markup(row[0]))
        scored.append((len(pw & task_words), strip_markup(row[1])))
    scored.sort(key=lambda s: -s[0])
    return scored


def check_routing(rows: list[list[str]], verbose: bool) -> None:
    for prompt, expected in ROUTING_FIXTURES:
        scored = route(prompt, rows)
        top_score, top_component = scored[0]
        runners = [c for s, c in scored[1:] if s == top_score and c != top_component]
        if verbose:
            print(f"  {top_score:>2} {top_component:<17} <- {prompt[:70]}")
        if top_score == 0:
            error(f"No row shares any words with the prompt: {prompt!r}")
        elif top_component != expected:
            error(f"Prompt routed to '{top_component}', expected '{expected}': {prompt!r}")
        elif runners:
            error(f"Prompt ties between '{expected}' and {runners}: {prompt!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verbose", action="store_true", help="print routing scores")
    args = parser.parse_args()

    if not RUNTIME_REF.is_file():
        error(f"Missing {RUNTIME_REF}")
        return 1
    block = section(RUNTIME_REF.read_text(encoding="utf-8"), ROUTING_HEADING)
    if not block:
        error(f"'{ROUTING_HEADING}' section not found in {RUNTIME_REF.name}")
        return 1
    header, rows = parse_table(block)
    if not rows:
        error("Routing table has no rows")
        return 1

    print(f"Checking routing table in {RUNTIME_REF.relative_to(SKILL_DIR)} ({len(rows)} rows)")
    check_structure(header, rows)
    check_components(rows)
    check_links(rows)
    check_pointer_row()
    check_routing(rows, args.verbose)

    if errors:
        print(f"\n{len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"OK: {len(rows)} rows, {len(ROUTING_FIXTURES)} prompts routed as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
