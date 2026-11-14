"""Tests for tools/prompt-library-sync.py and the approved prompt-library contract."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("prompt_library_sync", PLUGIN / "tools" / "prompt-library-sync.py")
pls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pls)

REMOVED = [
    "ai-support-ticket-triage-and-routing-assistant",
    "aws-security-baseline-terraform-deployment-kit",
    "bedrock-quota-manager",
    "container-orchestration",
    "cost-anomaly-detection",
    "deploy-github-repo",
    "kiro-project-init",
    "mvsp",
    "well-architecture-review",
    "aws-db-advisor",
]


def _page(entry: dict, text_rows: dict[str, str]) -> str:
    """Build a minimal Next.js page that streams `entry` the way startups.aws.com does."""
    payload = ""
    for rid, text in text_rows.items():
        payload += f"{rid}:T{len(text.encode('utf-8')):x},{text}"
    payload += "9:" + json.dumps(["$", "div", None, {"entry": entry}]) + "\n"
    chunk = json.dumps(payload)[1:-1]
    return f'<html><script>self.__next_f.push([1,"{chunk}"])</script></html>'


def test_parse_entry_resolves_text_rows_without_terminators():
    long_text = "# Title\n\nYou are an AWS architect.\n\n## Step\n\nDo the thing."
    other = "unrelated row text that ends without a newline"
    entry = {"slug": "demo", "type": "prompt", "title": "Demo", "promptTextContent": "$1f", "description": "d"}
    page = _page(entry, {"1e": other, "1f": long_text})
    parsed = pls.parse_entry(page, "demo")
    assert parsed["promptTextContent"] == long_text


def test_parse_entry_rejects_wrong_slug_and_unresolved_reference():
    entry = {"slug": "demo", "type": "prompt", "promptTextContent": "$2a"}
    with pytest.raises(pls.FetchError):
        pls.parse_entry(_page(entry, {}), "other")
    with pytest.raises(pls.FetchError, match="not found"):
        pls.parse_entry(_page(entry, {}), "demo")


def test_editorjs_to_markdown():
    blocks = [
        {"type": "header", "data": {"text": "Setup", "level": 2}},
        {"type": "paragraph", "data": {"text": "<b>Prerequisites</b>&nbsp;see <a href=\"https://x.test/a?b=1&amp;c=2\">docs</a>"}},
        {"type": "list", "data": {"style": "ordered", "items": ["Run <code>aws sts get-caller-identity</code>", "Done"]}},
        {"type": "list", "data": {"style": "unordered", "items": [{"content": "nested <i>item</i>"}]}},
    ]
    assert pls.editorjs_md(blocks) == (
        "### Setup\n\n"
        "**Prerequisites** see [docs](https://x.test/a?b=1&c=2)\n\n"
        "1. Run `aws sts get-caller-identity`\n2. Done\n\n"
        "- nested *item*"
    )


def test_local_change_applies_once_and_fails_loudly_otherwise():
    change = {"id": "c1", "find": "username and password", "replace": "IAM credentials"}
    assert pls.apply_local_changes("s", "ask for the username and password.", [change]) == "ask for the IAM credentials."
    with pytest.raises(pls.LocalChangeError, match="found 0"):
        pls.apply_local_changes("s", "the page was edited upstream", [change])
    with pytest.raises(pls.LocalChangeError, match="found 2"):
        pls.apply_local_changes("s", "username and password, username and password", [change])


def test_split_ignores_headings_inside_code_fences_and_round_trips():
    text = "## Overview\n\nIntro.\n\n## Phase 1\n\n```bash\n## not a heading\necho hi\n```\n\n## Phase 2\n\nEnd."
    sections = pls.split_sections(text)
    assert [h for h, _ in sections] == ["Overview", "Phase 1", "Phase 2"]
    parts = [f"{pls.LINT_OFF}\n\n{body.strip()}\n\n{pls.LINT_ON}\n" for _, body in sections]
    assert re.sub(r"\n+", "\n", pls.reassemble(parts)) == re.sub(r"\n+", "\n", text)


# --- Repository contract: what is on disk matches the approved list ---------------------


def _approved() -> dict:
    return json.loads(pls.APPROVED.read_text(encoding="utf-8"))


def test_approved_list_is_the_governance_subset():
    approved = _approved()
    kinds = [e["kind"] for e in approved["entries"]]
    assert len(kinds) == 27 and kinds.count("prompt") == 22 and kinds.count("agent") == 5
    assert not set(REMOVED) & {e["slug"] for e in approved["entries"]}


def test_every_approved_entry_has_a_detail_file_and_nothing_else_is_bundled():
    approved = {e["slug"]: e for e in _approved()["entries"]}
    files = {p.stem for p in pls.ENTRIES.glob("*.md")}
    assert files == set(approved)
    for slug, item in approved.items():
        text = (pls.ENTRIES / f"{slug}.md").read_text(encoding="utf-8")
        assert f'source_url: "{pls.BASE_URL}{slug}"' in text
        assert f'kind: "{item["kind"]}"' in text
        if item["kind"] == "agent":
            assert re.search(r'install_source: "https://github\.com/[^"]+"', text)
        if item.get("split"):
            parts = sorted((pls.ENTRIES / slug).glob("*.md"))
            assert parts and all(f"]({slug}/{p.name})" in text for p in parts)


def test_local_changes_target_approved_entries_and_record_why():
    approved = {e["slug"] for e in _approved()["entries"]}
    changes = json.loads(pls.LOCAL_CHANGES.read_text(encoding="utf-8"))["changes"]
    assert len({c["id"] for c in changes}) == len(changes)
    for c in changes:
        assert c["slug"] in approved
        assert c.get("target", "prompt") in ("prompt", "instructions")
        assert c["reason"] and c["origin"] and c["find"] and c["find"] != c["replace"]


def test_removed_entries_are_not_mentioned_where_the_skill_routes():
    skill = (pls.SKILL / "SKILL.md").read_text(encoding="utf-8")
    index = pls.INDEX.read_text(encoding="utf-8")
    for slug in REMOVED:
        assert slug not in skill and slug not in index
    assert "DB Advisor" not in skill and "DB Advisor" not in index
    assert pls.FULL_LIBRARY in skill and pls.FULL_LIBRARY in index


def test_index_links_resolve():
    index = pls.INDEX.read_text(encoding="utf-8")
    for target in re.findall(r"\]\((prompt-library/[^)]+\.md)\)", index):
        assert (pls.INDEX.parent / target).exists(), target
