#!/usr/bin/env python3
"""Validate migration artifacts against the contracts the skills publish for them.

Why this exists
---------------
The migration skills (gcp-to-aws, heroku-to-aws, azure-to-aws) pass ~17 JSON artifacts
between phases: Discover writes an inventory, Clarify writes preferences, Design reads
both, and so on. Each artifact's contract is published as a `schema-*.md` document whose
"shape" is a JSON / JSONC example block, plus two real JSON Schemas under
`skills/shared/`. Those contracts are prose. Nothing checked that a producer actually
writes what the next phase reads, so a field could be renamed in one phase file, a new
key emitted without being documented, or a documented enum silently widened — and every
DSL `_assert` would still pass, because the model that writes the artifact is the model
that evaluates the assertion.

This tool turns the published shape blocks into a key-path contract and checks real
artifacts against it. It is deliberately conservative: it enforces only what the
documents actually say (known keys, example types, `a | b | c` enums, keys the document
marks REQUIRED) and reports the rest as what it is — a gap in the contract, not in the
artifact.

What it checks
--------------
For every artifact it finds in a run directory (or in the fixture goldens):

  UNKNOWN_KEY        a key the contract does not mention (off-contract emission — the
                     drift class that motivated this tool)
  MISSING_REQUIRED   a key the contract marks `(REQUIRED)` / `// REQUIRED` / `// ALWAYS
                     present` is absent
  TYPE_MISMATCH      the value's JSON type differs from the contract's example
  ENUM_VIOLATION     the value is outside an `a | b | c` set the contract spells out
  SCHEMA_VIOLATION   a real JSON Schema (draft-07 subset) rejected the value
  SCHEMA_PARSE       the contract document's own example block does not parse — the
                     contract is broken, independent of any artifact
  STALE_BASELINE     a baseline entry matched no finding — the gap it described is fixed
                     (remove the entry) or the entry is mistyped (it hides nothing today and
                     could hide a real finding tomorrow); fails the run either way
  NO_CONTRACT        an artifact was found that no contract covers (informational)

Keys beginning with `_` are treated as annotations (`_comment`, `_what_this_is`) and are
never reported as unknown. Placeholder values (`"<ISO 8601>"`, `"..."`) accept any
string; a placeholder *key* (`"<azure_id>"`, `"..."`) makes the object open.

Usage
-----
    python3 validate-artifacts.py --self-check
        Parse every contract document and report SCHEMA_PARSE findings. No artifacts.

    python3 validate-artifacts.py --fixtures
        Validate every golden artifact under fixtures/ against its skill's contracts,
        applying the shipped baseline file (known, explained findings that do not fail).

    python3 validate-artifacts.py --run-dir <path/.migration/<run>> --skill <name>
        Validate one real run. For users and for post-run checks in capability tests.
        No baseline is applied unless `--baseline` names one: the shipped baseline
        describes gaps in the fixture corpus (its globs are `fixtures/...`), so applying
        it to a run outside that corpus would only report every entry as stale.

    --json      machine-readable output
    --baseline  apply this baseline file (default: scripts/artifact-contracts-baseline.json
                for --fixtures; none for --run-dir). Every entry must match a finding.
    --manifest  override the contracts manifest (default: scripts/artifact-contracts.json)

Exit 0 when no non-baselined ERROR findings; 1 otherwise. Stdlib only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
DEFAULT_MANIFEST = HERE / "artifact-contracts.json"
DEFAULT_BASELINE = HERE / "artifact-contracts-baseline.json"

ERROR_CODES = {"UNKNOWN_KEY", "MISSING_REQUIRED", "TYPE_MISMATCH", "ENUM_VIOLATION",
               "SCHEMA_VIOLATION", "SCHEMA_PARSE", "STALE_BASELINE"}
INFO_CODES = {"NO_CONTRACT"}


# --------------------------------------------------------------------------- findings


@dataclass
class Finding:
    code: str
    artifact: str          # path of the artifact (relative to cwd when possible)
    path: str              # JSON path inside the artifact, e.g. "data.db_cutover"
    message: str
    contract: str = ""     # which contract document/section produced it
    baselined: bool = False
    baseline_reason: str = ""

    @property
    def severity(self) -> str:
        return "error" if self.code in ERROR_CODES else "info"

    def as_dict(self) -> Dict[str, Any]:
        d = {"code": self.code, "severity": self.severity, "artifact": self.artifact,
             "path": self.path, "message": self.message, "contract": self.contract}
        if self.baselined:
            d["baselined"] = True
            d["baseline_reason"] = self.baseline_reason
        return d


# --------------------------------------------------------------------------- JSONC → JSON


_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def strip_jsonc(text: str) -> Tuple[str, Dict[int, str], Dict[int, str]]:
    """Strip `//` comments outside strings and trailing commas.

    Returns (json_text, comment_by_line, key_by_line). Line numbers are 0-based into the
    block. `key_by_line` holds the JSON key that opens on that line, so a trailing comment
    can be attributed to the key it annotates.
    """
    out_lines: List[str] = []
    comments: Dict[int, str] = {}
    keys: Dict[int, str] = {}
    for i, line in enumerate(text.splitlines()):
        # find first `//` that is not inside a string
        idx = None
        in_str = False
        esc = False
        j = 0
        while j < len(line):
            ch = line[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "/" and j + 1 < len(line) and line[j + 1] == "/":
                    idx = j
                    break
            j += 1
        if idx is not None:
            comments[i] = line[idx + 2:].strip()
            line = line[:idx].rstrip()
        # The key a trailing comment annotates is the LAST `"key":` opened on the line
        # WHOSE OWN NESTING DEPTH MATCHES THE DEPTH AT THE END OF THE LINE — i.e. a key
        # that is still "current" by the time the comment is reached, not merely the
        # last key-like string that happens to appear earliest in the text. Two cases
        # must resolve differently and both are exercised by tests:
        #   - `"routing_provenance": "table", // REQUIRED` (depth stays open on this
        #     key's own value, never closed back out before the comment) → the comment
        #     belongs to `routing_provenance` itself, the last key opened, matching the
        #     original design for a key immediately followed by its own `// REQUIRED`.
        #   - `"call_sites": [{ "file": "app.py", "line": 1 }], // REQUIRED` (the inline
        #     array/object value is fully opened AND closed before the comment, so depth
        #     returns to the level `call_sites` itself was opened at) → the comment
        #     belongs to `call_sites`, the enclosing field, not to `line` (a key nested
        #     inside that value, whose own depth no longer matches the end-of-line depth).
        # Tracking bracket depth while re-scanning the comment-stripped line, and keeping
        # the LAST key seen at each depth, implements this without changing the plain
        # same-depth case (several flat `"a": 1, "b": 2 // REQUIRED` siblings still
        # resolve to the last one, `b`, because nothing nests and depth never changes).
        depth = 0
        last_key_at_depth: Dict[int, str] = {}
        k_in_str = False
        k_esc = False
        pos = 0
        key_start: Optional[int] = None
        string_open_pos = 0
        while pos < len(line):
            ch = line[pos]
            if k_in_str:
                if k_esc:
                    k_esc = False
                elif ch == "\\":
                    k_esc = True
                elif ch == '"':
                    k_in_str = False
                    key_start = pos  # candidate string just closed at `pos`
                pos += 1
                continue
            if ch == '"':
                k_in_str = True
                string_open_pos = pos
                pos += 1
                continue
            if ch in "{[":
                depth += 1
                pos += 1
                continue
            if ch in "}]":
                depth -= 1
                pos += 1
                continue
            if ch == ":" and key_start is not None:
                # the string that just closed, immediately followed by `:` (ignoring
                # whitespace), is a key opened at the CURRENT depth (before this colon's
                # value opens any further nesting of its own)
                between = line[key_start + 1:pos]
                if between.strip() == "":
                    last_key_at_depth[depth] = line[string_open_pos + 1:key_start]
            if ch not in '"':
                key_start = None
            pos += 1
        # A key's value can legitimately still be OPEN at end-of-line (e.g.
        # `"workloads": [ // REQUIRED` whose `]` closes on a later line) — that key was
        # recorded one level shallower than `depth` (the depth its own `[`/`{` pushed to).
        # Prefer an exact depth match (the fully-closed-on-this-line case); fall back to
        # `depth - 1` (the still-open-at-end-of-line case) only when no exact match exists.
        if depth in last_key_at_depth:
            keys[i] = last_key_at_depth[depth]
        elif (depth - 1) in last_key_at_depth:
            keys[i] = last_key_at_depth[depth - 1]
        out_lines.append(line)
    joined = "\n".join(out_lines)
    # bare `...` ellipses in arrays/objects (`["Q1", "Q2", ...]`) → a placeholder string
    joined = re.sub(r"(?<![\"\w.])\.\.\.(?![\"\w.])", '"..."', joined)
    # bare `true|false` alternation → a boolean example
    joined = re.sub(r"(?<![\"\w])(?:true|false)\|(?:true|false)(?![\"\w])", "true", joined)
    # trailing commas before } or ]
    joined = re.sub(r",(\s*[}\]])", r"\1", joined)
    return joined, comments, keys


# --------------------------------------------------------------------------- shape templates


@dataclass
class Node:
    kinds: Set[str] = field(default_factory=set)     # subset of object/array/string/number/boolean/null/any
    keys: Dict[str, "Node"] = field(default_factory=dict)
    required: Set[str] = field(default_factory=set)
    wildcard: bool = False                           # object accepts keys not listed
    any_key: Optional["Node"] = None                 # template every key under this object must satisfy
    item: Optional["Node"] = None
    enum: Optional[Set[str]] = None
    enum_join: Optional[str] = None                  # "+" when the contract allows a joined set of enum members
    examples: Set[str] = field(default_factory=set)  # concrete (non-enum, non-placeholder) string values shown
    source: str = ""

    def is_any(self) -> bool:
        return "any" in self.kinds or not self.kinds

    def _is_unspecified_any(self) -> bool:
        """An empty-array seed (`"services": []`) or a bare placeholder. It names no type,
        no keys, and no enum — unlike a null example, which is `{null, any}` on purpose."""
        return (
            self.kinds == {"any"}
            and not self.keys
            and self.item is None
            and self.any_key is None
            and self.enum is None
            and not self.examples
            and not self.wildcard
            and not self.required
        )

    def merge(self, other: "Node") -> "Node":
        """Union two templates for the same path (several documented variants).

        Children adopted from `other` are copied, never shared: a later refinement of a
        named child (`design_constraints.cpu_architecture`) must not mutate the generic
        template (`design_constraints.<key>`) it was seeded from.

        An unspecified `any` (the item of `"services": []`) is replaced when a concrete
        shape arrives. Unioning would keep `any` in the kinds and skip type checks for
        good. A later empty array does not put `any` back onto a shape already learned.
        """
        if self._is_unspecified_any() and not other._is_unspecified_any():
            concrete = copy.deepcopy(other)
            self.kinds = concrete.kinds
            self.wildcard = concrete.wildcard
            self.required = concrete.required
            self.keys = concrete.keys
            self.item = concrete.item
            self.any_key = concrete.any_key
            self.enum = concrete.enum
            self.enum_join = concrete.enum_join
            self.examples = concrete.examples
            self.source = concrete.source or self.source
            return self
        if other._is_unspecified_any() and not self._is_unspecified_any():
            return self
        self.kinds |= other.kinds
        self.wildcard = self.wildcard or other.wildcard
        self.required |= other.required
        for k, v in other.keys.items():
            if k in self.keys:
                self.keys[k].merge(v)
            else:
                self.keys[k] = copy.deepcopy(v)
        if other.item is not None:
            if self.item is None:
                self.item = copy.deepcopy(other.item)
            else:
                self.item.merge(other.item)
        if other.any_key is not None:
            if self.any_key is None:
                self.any_key = copy.deepcopy(other.any_key)
            else:
                self.any_key.merge(other.any_key)
        self.enum_join = self.enum_join or other.enum_join
        self.examples |= other.examples
        if self.enum is not None or other.enum is not None:
            # A declared enum survives a merge with a concrete example: `"confidence": "full"`
            # demonstrates one member of `full|reduced`, it does not widen the field to any
            # string. A concrete token the document shows that is not yet in the enum is
            # documented by that very example, so it joins the set. Only a free-text
            # example (not a token — spaces, punctuation) proves the field is not an enum.
            merged = (self.enum or set()) | (other.enum or set())
            if any(not _ENUM_TOKEN_RE.match(e) for e in self.examples):
                self.enum = None
            else:
                self.enum = merged | self.examples
        return self


_PLACEHOLDER_RE = re.compile(r"^<.*>$")
_ENUM_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:+\-/]+$")
_COMMENT_ENUM_RE = re.compile(r"(?:^|[—:\-]\s*)([A-Za-z0-9_.:+\-/]+(?:\s*\|\s*[A-Za-z0-9_.:+\-/]+)+)\s*(?:$|[—(\-])")
# `terraform | live | billing (or a "+"-joined set)` — members may be combined with "+"
_JOINED_SET_RE = re.compile(r"[\"'`]?\+[\"'`]?[\s-]*joined|joined\s+(?:by|with|on)\s+[\"'`]?\+", re.I)


def _enum_from_string(s: str) -> Optional[Set[str]]:
    if "|" not in s:
        return None
    toks = [t.strip() for t in s.split("|")]
    if len(toks) >= 2 and all(_ENUM_TOKEN_RE.match(t) for t in toks):
        return set(toks)
    return None


def _enum_from_comment(c: str) -> Optional[Set[str]]:
    m = _COMMENT_ENUM_RE.search(c)
    if not m:
        return None
    toks = [t.strip() for t in m.group(1).split("|")]
    if len(toks) >= 2 and all(_ENUM_TOKEN_RE.match(t) for t in toks):
        return set(toks)
    return None


def _is_required_comment(c: str) -> bool:
    c_up = c.upper()
    return ("REQUIRED" in c_up and "NOT REQUIRED" not in c_up and "REQUIRED WHEN" not in c_up
            and "REQUIRED IF" not in c_up and "REQUIRED ONLY" not in c_up and "REQUIRED ON" not in c_up
            and "REQUIRED WHENEVER" not in c_up) or "ALWAYS PRESENT" in c_up


def build_node(value: Any, key_comments: Dict[str, List[str]], source: str) -> Node:
    """Infer a template node from an example value."""
    n = Node(source=source)
    if isinstance(value, dict):
        n.kinds.add("object")
        for k, v in value.items():
            if k == "..." or _PLACEHOLDER_RE.match(k):
                n.wildcard = True
                if isinstance(v, (dict, list)) and v not in ({}, []) and not (isinstance(v, dict) and set(v) == {"..."}):
                    tmpl = build_node(v, key_comments, source)
                    n.any_key = tmpl if n.any_key is None else n.any_key.merge(tmpl)
                continue
            child = build_node(v, key_comments, source)
            for c in key_comments.get(k, []):
                if _is_required_comment(c):
                    n.required.add(k)
                e = _enum_from_comment(c)
                if e is not None and ("string" in child.kinds or "null" in child.kinds or child.is_any()):
                    # only trust a comment enum when the example value is consistent with it
                    if not isinstance(v, str) or v in e or _PLACEHOLDER_RE.match(v) or v == "...":
                        child.enum = e
                        child.kinds.add("string")
                        child.kinds.discard("any")
                        if _JOINED_SET_RE.search(c):
                            child.enum_join = "+"
                if "null" in c.lower() and "or null" in c.lower() or "nullable" in c.lower():
                    child.kinds.add("null")
            n.keys[k] = child
    elif isinstance(value, list):
        n.kinds.add("array")
        item: Optional[Node] = None
        for el in value:
            en = build_node(el, key_comments, source)
            item = en if item is None else item.merge(en)
        n.item = item if item is not None else Node(kinds={"any"}, source=source)
    elif isinstance(value, str):
        if value == "..." or _PLACEHOLDER_RE.match(value):
            # a placeholder like "<Q13 value>" says nothing about the JSON type
            n.kinds.add("any")
        else:
            e = _enum_from_string(value)
            n.kinds.add("string")
            if e is not None:
                n.enum = e
            else:
                n.examples.add(value)
    elif isinstance(value, bool):
        n.kinds.add("boolean")
    elif isinstance(value, (int, float)):
        n.kinds.add("number")
    elif value is None:
        n.kinds.add("null")
        n.kinds.add("any")  # a null example says nothing about the non-null type
    return n


# --------------------------------------------------------------------------- contract documents


@dataclass
class Block:
    heading: str
    lang: str
    text: str
    line: int          # 1-based line of the opening fence in the document


_FENCE_RE = re.compile(r"^```(\w+)?\s*$")


def extract_blocks(doc: Path) -> List[Block]:
    return _scan_doc(doc)[0]


def extract_headings(doc: Path) -> List[str]:
    """Every heading in document order, whether or not a JSON block follows it. A heading
    such as '### `metadata` (REQUIRED)' is a contract statement even when the section body
    is a table, so requiredness cannot be read from fenced blocks alone."""
    return _scan_doc(doc)[1]


def _scan_doc(doc: Path) -> Tuple[List[Block], List[str]]:
    blocks: List[Block] = []
    headings: List[str] = []
    heading = ""
    in_block = False
    lang = ""
    start = 0
    buf: List[str] = []
    for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
        if not in_block:
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
                headings.append(heading)
            m = _FENCE_RE.match(line)
            if m:
                in_block = True
                lang = (m.group(1) or "").lower()
                start = i
                buf = []
        else:
            if line.startswith("```"):
                in_block = False
                if lang in ("json", "jsonc"):
                    blocks.append(Block(heading=heading, lang=lang, text="\n".join(buf), line=start))
            else:
                buf.append(line)
    return blocks, headings


def _heading_matches(heading: str, wanted: str) -> bool:
    """Exact match, or a prefix match that ends on a word boundary — `graviton` matches
    '`graviton` block (added to …)' but not '`graviton_profile` (emitted by …)'."""
    h = heading.replace("`", "").strip().lower()
    w = wanted.replace("`", "").strip().lower()
    if h == w:
        return True
    if not h.startswith(w):
        return False
    nxt = h[len(w)]
    return not (nxt.isalnum() or nxt == "_")


def _heading_token(heading: str) -> Optional[str]:
    """The key path a sub-section heading documents, e.g. '## `services[]`' → 'services[]'."""
    m = re.search(r"`([^`]+)`", heading)
    tok = m.group(1) if m else heading.split(" ")[0]
    tok = tok.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.\[\]]*$", tok):
        return None
    return tok


def parse_block(block: Block, doc: Path, findings: List[Finding]) -> Optional[Tuple[Any, Dict[str, List[str]]]]:
    json_text, comments, keys = strip_jsonc(block.text)
    # a lone `...` line inside an object means "more keys like these"; inside an array it
    # means "more items". Try the object reading first, then the array reading, then the
    # fragment reading (`"key": {...}` with no outer braces).
    lone = re.compile(r'^(\s*)"\.\.\."\s*,?\s*$', re.M)
    candidates = [lone.sub(r'\1"...": "..."', json_text), json_text, "{" + json_text + "}",
                  "{" + lone.sub(r'\1"...": "..."', json_text) + "}"]
    value = None
    first_error: Optional[json.JSONDecodeError] = None
    for cand in candidates:
        try:
            value = json.loads(re.sub(r",(\s*[}\]])", r"\1", cand))
            break
        except json.JSONDecodeError as e:
            if first_error is None:
                first_error = e
    if value is None:
        e = first_error
        try:
            value = json.loads("{" + json_text + "}")
        except json.JSONDecodeError:
            findings.append(Finding(
                code="SCHEMA_PARSE", artifact=_rel(doc), path=f"L{block.line}",
                message=f"example block under '{block.heading}' is not valid JSON/JSONC: {e.msg} "
                        f"(block line {e.lineno})",
                contract=_rel(doc)))
            return None
    key_comments: Dict[str, List[str]] = {}
    for ln, c in comments.items():
        k = keys.get(ln)
        if k is not None:
            key_comments.setdefault(k, []).append(c)
    return value, key_comments


def _unwrap_to_path(value: Any, dotted: str) -> Any:
    """A block may show its key path as wrapper objects — `{"design_constraints":
    {"cpu_architecture": {...}}}` under a heading for `design_constraints.cpu_architecture`.
    Peel single-key wrappers while they match the path components, so the block's own
    keys land at the path and not one level below it."""
    comps = [c.rstrip("[]") for c in dotted.split(".") if c]
    for c in comps:
        if isinstance(value, dict) and len(value) == 1 and c in value:
            value = value[c]
        else:
            break
    # also peel when the wrapper is only the LAST component (common: {"metadata": {...}})
    if comps and isinstance(value, dict) and len(value) == 1 and comps[-1] in value \
            and isinstance(value[comps[-1]], (dict, list)):
        value = value[comps[-1]]
    return value


def _merge_example_at(root: Node, path: str, value: Any, key_comments: Dict[str, List[str]], source: str) -> None:
    """Merge an example block into the template at `path`, at the level the example
    actually shows. A path ending in `[]` names the array's ITEM; a block for it may be a
    bare item (`{"name": …}`, merged into the item) or the whole array (`[{…}, {…}]` after
    `{"workloads": [...]}` was unwrapped — merged into the array node, one level up).
    Merging an array example into the item node would nest a phantom item level whose
    object has no declared keys, so none of the item's field checks would ever run."""
    value = _unwrap_to_path(value, path)
    node = build_node(value, key_comments, source)
    if path.endswith("[]") and isinstance(value, list):
        target = _walk_path(root, path[:-2])
    else:
        target = _walk_path(root, path)
    if target is not None:
        target.merge(node)


def _walk_path(root: Node, dotted: str) -> Optional[Node]:
    """Find the node at 'a.b[].c'; create intermediate nodes as needed."""
    node = root
    if dotted == "":
        return root
    for part in dotted.split("."):
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part
        if key:
            if key not in node.keys:
                fresh = Node(kinds={"object"} if not is_array else {"array"}, source=root.source)
                if node.any_key is not None:
                    fresh.merge(node.any_key)
                node.keys[key] = fresh
            node = node.keys[key]
        if is_array:
            node.kinds.add("array")
            if node.item is None:
                node.item = Node(kinds={"object"}, source=root.source)
            node = node.item
    return node


@dataclass
class ShapeContract:
    doc: Path
    root: Node
    label: str


def build_shape_contract(spec: Dict[str, Any], findings: List[Finding]) -> Optional[ShapeContract]:
    doc = PLUGIN_ROOT / spec["shape"]
    if not doc.exists():
        findings.append(Finding("SCHEMA_PARSE", _rel(doc), "", "contract document not found", _rel(doc)))
        return None
    blocks, headings = _scan_doc(doc)
    root_heading = spec.get("root_heading")
    root_block: Optional[Block] = None
    for b in blocks:
        if root_heading is None or _heading_matches(b.heading, root_heading):
            root_block = b
            break
    if root_block is None:
        findings.append(Finding("SCHEMA_PARSE", _rel(doc), "",
                                f"no JSON block found under heading '{root_heading}'", _rel(doc)))
        return None
    parsed = parse_block(root_block, doc, findings)
    if parsed is None:
        return None
    value, kc = parsed
    root = build_node(value, kc, f"{_rel(doc)}:L{root_block.line}")
    if not isinstance(value, dict):
        findings.append(Finding("SCHEMA_PARSE", _rel(doc), f"L{root_block.line}",
                                "root example block is not a JSON object", _rel(doc)))
        return None

    # Sub-section blocks refine paths inside the root. Manifest `sections` wins; otherwise
    # the heading's backticked token is the path ("services[]", "metadata", "a.b").
    explicit: Dict[str, str] = spec.get("sections", {})            # heading → path
    rules: List[Dict[str, str]] = spec.get("section_rules", [])    # {heading_regex, path}
    ignore: List[str] = spec.get("ignore_headings", [])
    anchors = {k for k in explicit if k.startswith("@L")}
    seen_anchors: Set[str] = set()

    def section_path(heading: str) -> Optional[str]:
        """The key path a (non-anchored) section heading documents, or None to skip it."""
        if root_heading is not None and _heading_matches(heading, root_heading):
            # another example under the root heading (a per-item sample, a fragment) —
            # only a line anchor in the manifest can say what it documents
            return None
        if any(_heading_matches(heading, ig) for ig in ignore):
            return None
        for h, p in explicit.items():
            if not h.startswith("@L") and _heading_matches(heading, h):
                return p
        for r in rules:
            if re.search(r["heading_regex"], heading):
                return r["path"]
        return _heading_token(heading)

    for b in blocks:
        if b is root_block:
            continue
        anchor = f"@L{b.line}"
        if anchor in explicit:
            path: Optional[str] = explicit[anchor]
            seen_anchors.add(anchor)
        else:
            path = section_path(b.heading)
        if path is None:
            continue
        parsed = parse_block(b, doc, findings)
        if parsed is None:
            continue
        v, kc2 = parsed
        _merge_example_at(root, path, v, kc2, f"{_rel(doc)}:L{b.line}")
    # A heading marked `(REQUIRED)` is a contract statement on its own, whether the section
    # body is a JSON block or a table (`### \`metadata\` (REQUIRED)` in the Heroku inventory
    # contract is a table). Read requiredness from every heading, not only fenced ones.
    for heading in headings:
        if "(REQUIRED)" not in heading.upper():
            continue
        path = section_path(heading)
        if not path:
            continue
        parent_path = ".".join(path.split(".")[:-1])
        parent = _walk_path(root, parent_path) if parent_path else root
        if parent is not None:
            parent.required.add(path.split(".")[-1].rstrip("[]"))
    for a in anchors - seen_anchors:
        findings.append(Finding("SCHEMA_PARSE", _rel(doc), a,
                                f"manifest section anchor {a} does not point at a JSON block start in this document "
                                f"(the document moved; update artifact-contracts.json)", _rel(doc)))
    # Blocks in OTHER documents that add keys to this artifact (graviton, workshop, …)
    for extra in spec.get("extra_shapes", []):
        edoc = PLUGIN_ROOT / extra["shape"]
        if not edoc.exists():
            findings.append(Finding("SCHEMA_PARSE", _rel(edoc), "", "extra_shapes document not found", _rel(edoc)))
            continue
        hit = None
        for eb in extract_blocks(edoc):
            if _heading_matches(eb.heading, extra["heading"]):
                hit = eb
                break
        if hit is None:
            findings.append(Finding("SCHEMA_PARSE", _rel(edoc), "",
                                    f"no JSON block under heading '{extra['heading']}'", _rel(edoc)))
            continue
        parsed = parse_block(hit, edoc, findings)
        if parsed is None:
            continue
        ev, ekc = parsed
        _merge_example_at(root, extra["path"], ev, ekc, f"{_rel(edoc)}:L{hit.line}")
    for k in spec.get("required", []):
        root.required.add(k)
    for k in spec.get("open_paths", []):
        n = _walk_path(root, k)
        if n is not None:
            n.wildcard = True
    allowed = set(spec.get("allowed_anywhere", []))
    if allowed:
        _mark_allowed_anywhere(root, allowed)
    return ShapeContract(doc=doc, root=root, label=f"{_rel(doc)} § {root_block.heading}")


def _mark_allowed_anywhere(node: Node, allowed: Set[str]) -> None:
    """Keys a document defines as a vocabulary usable on any row (e.g. azure preferences'
    `source` / `reason` / `context`) are accepted at every object level without being
    listed in each example row."""
    if "object" in node.kinds and node.keys:
        for k in allowed:
            node.keys.setdefault(k, Node(kinds={"any"}, source=node.source))
        for child in list(node.keys.values()):
            _mark_allowed_anywhere(child, allowed)
    if node.item is not None:
        _mark_allowed_anywhere(node.item, allowed)


# --------------------------------------------------------------------------- shape validation


_KIND_OF = {dict: "object", list: "array", str: "string", bool: "boolean", int: "number",
            float: "number", type(None): "null"}


def validate_shape(node: Node, value: Any, path: str, artifact: str, contract: str, out: List[Finding]) -> None:
    kind = _KIND_OF.get(type(value), "any")
    if not node.is_any() and kind not in node.kinds:
        # tolerate null where the example never said — too many contracts write null for "absent"
        if kind == "null":
            return
        out.append(Finding("TYPE_MISMATCH", artifact, path or "$",
                           f"is {kind}, contract example is {'/'.join(sorted(node.kinds))}", contract))
        return
    if node.enum is not None and isinstance(value, str):
        # a joined set (`terraform+live`) is valid when every member is; an unknown member
        # is still a violation
        members = value.split(node.enum_join) if node.enum_join else [value]
        if not members or any(m not in node.enum for m in members):
            allowed = ", ".join(sorted(node.enum))
            joined = f" (or a '{node.enum_join}'-joined set of them)" if node.enum_join else ""
            out.append(Finding("ENUM_VIOLATION", artifact, path or "$",
                               f"'{value}' not in {{{allowed}}}{joined}", contract))
    if isinstance(value, dict) and "object" in node.kinds:
        for k in node.required:
            if k not in value:
                out.append(Finding("MISSING_REQUIRED", artifact, _join(path, k),
                                   "contract marks this key REQUIRED / ALWAYS present", contract))
        for k, v in value.items():
            if k.startswith("_"):
                continue
            child = node.keys.get(k)
            if child is None:
                if node.any_key is not None:
                    validate_shape(node.any_key, v, _join(path, k), artifact, contract, out)
                elif not node.wildcard and node.keys:
                    out.append(Finding("UNKNOWN_KEY", artifact, _join(path, k),
                                       "key is not in the contract's example shape", contract))
                continue
            validate_shape(child, v, _join(path, k), artifact, contract, out)
    elif isinstance(value, list) and "array" in node.kinds and node.item is not None:
        for i, el in enumerate(value):
            validate_shape(node.item, el, f"{path}[{i}]", artifact, contract, out)


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


# --------------------------------------------------------------------------- JSON Schema subset


# Keywords the subset validator ENFORCES. Anything else that is a validation keyword is
# reported by `unsupported_keywords` so a schema cannot silently lose a constraint.
_ENFORCED_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "enum", "const", "items",
    "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minItems",
    "maxItems", "uniqueItems", "minProperties", "maxProperties", "minLength", "maxLength",
    "allOf", "anyOf", "oneOf", "not", "$ref",
}
# Annotations / structure that carry no constraint of their own.
_ANNOTATION_KEYWORDS = {
    "$schema", "$id", "$comment", "title", "description", "default", "examples",
    "definitions", "$defs", "format",  # format is intentionally not enforced (annotation-level)
}


def unsupported_keywords(schema: Any, ptr: str = "#") -> List[Tuple[str, str]]:
    """Walk a JSON Schema and return (json-pointer, keyword) pairs for every keyword the
    subset neither enforces nor recognises as an annotation. Called once per schema load."""
    found: List[Tuple[str, str]] = []
    if isinstance(schema, dict):
        for k, v in schema.items():
            if k in ("properties", "definitions", "$defs", "patternProperties"):
                if isinstance(v, dict):
                    for name, sub in v.items():
                        found.extend(unsupported_keywords(sub, f"{ptr}/{k}/{name}"))
                if k == "patternProperties":
                    found.append((ptr, k))
                continue
            if k in ("items", "additionalProperties", "not"):
                found.extend(unsupported_keywords(v, f"{ptr}/{k}"))
            elif k in ("allOf", "anyOf", "oneOf") and isinstance(v, list):
                for i, sub in enumerate(v):
                    found.extend(unsupported_keywords(sub, f"{ptr}/{k}/{i}"))
            if k not in _ENFORCED_KEYWORDS and k not in _ANNOTATION_KEYWORDS:
                found.append((ptr, k))
    return found


def validate_json_schema(schema: Dict[str, Any], value: Any, path: str, artifact: str, contract: str,
                         out: List[Finding], root_schema: Optional[Dict[str, Any]] = None) -> None:
    """Draft-07 subset — exactly the keywords in `_ENFORCED_KEYWORDS`. A schema using any
    other validation keyword is rejected at load time (see `unsupported_keywords`), so a
    constraint can never be skipped silently."""
    root_schema = root_schema or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/"):
            target: Any = root_schema
            for part in ref[2:].split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            validate_json_schema(target, value, path, artifact, contract, out, root_schema)
        return
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        kind = _KIND_OF.get(type(value), "any")
        ok = kind in types or (kind == "number" and "integer" in types and isinstance(value, int) and not isinstance(value, bool))
        if not ok:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                               f"is {kind}, schema type is {t}", contract))
            return
    if "enum" in schema and value not in schema["enum"]:
        out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                           f"{value!r} not in enum {schema['enum']}", contract))
    if "const" in schema and value != schema["const"]:
        out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                           f"{value!r} != const {schema['const']!r}", contract))
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                           f"'{value}' does not match pattern {schema['pattern']}", contract))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", f"length {len(value)} < minLength {schema['minLength']}", contract))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", f"length {len(value)} > maxLength {schema['maxLength']}", contract))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", f"{value} < minimum {schema['minimum']}", contract))
        if "maximum" in schema and value > schema["maximum"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", f"{value} > maximum {schema['maximum']}", contract))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", f"{value} <= exclusiveMinimum {schema['exclusiveMinimum']}", contract))
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", f"{value} >= exclusiveMaximum {schema['exclusiveMaximum']}", contract))
    if isinstance(value, dict):
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                               f"{len(value)} properties < minProperties {schema['minProperties']}", contract))
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                               f"{len(value)} properties > maxProperties {schema['maxProperties']}", contract))
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                out.append(Finding("SCHEMA_VIOLATION", artifact, _join(path, k), "required by schema", contract))
        addl = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                validate_json_schema(props[k], v, _join(path, k), artifact, contract, out, root_schema)
            elif addl is False:
                out.append(Finding("SCHEMA_VIOLATION", artifact, _join(path, k),
                                   "additionalProperties is false", contract))
            elif isinstance(addl, dict):
                validate_json_schema(addl, v, _join(path, k), artifact, contract, out, root_schema)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                               f"{len(value)} items < minItems {schema['minItems']}", contract))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                               f"{len(value)} items > maxItems {schema['maxItems']}", contract))
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", "items are not unique (uniqueItems)", contract))
        items = schema.get("items")
        if isinstance(items, dict):
            for i, el in enumerate(value):
                validate_json_schema(items, el, f"{path}[{i}]", artifact, contract, out, root_schema)
    for combinator in ("allOf",):
        for sub in schema.get(combinator, []):
            validate_json_schema(sub, value, path, artifact, contract, out, root_schema)
    if isinstance(schema.get("not"), dict):
        trial_not: List[Finding] = []
        validate_json_schema(schema["not"], value, path, artifact, contract, trial_not, root_schema)
        if not trial_not:
            out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$", "matches a `not` schema", contract))
    for combinator in ("oneOf", "anyOf"):
        subs = schema.get(combinator)
        if subs:
            passes = 0
            for sub in subs:
                trial: List[Finding] = []
                validate_json_schema(sub, value, path, artifact, contract, trial, root_schema)
                if not trial:
                    passes += 1
            if passes == 0 or (combinator == "oneOf" and passes > 1):
                out.append(Finding("SCHEMA_VIOLATION", artifact, path or "$",
                                   f"matches {passes} of {len(subs)} {combinator} branches", contract))


# --------------------------------------------------------------------------- manifest + resolution


@dataclass
class Contract:
    artifact_glob: str
    shape: Optional[ShapeContract] = None
    json_schema: Optional[Dict[str, Any]] = None
    json_schema_path: str = ""
    # (json path, expected value, shape). The first match replaces the default shape,
    # so requiredness follows the producer route that wrote the file.
    routes: List[Tuple[str, Any, ShapeContract]] = field(default_factory=list)


def load_manifest(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_contracts(manifest: Dict[str, Any], skill: Optional[str], findings: List[Finding]) -> List[Contract]:
    specs: Dict[str, Any] = {}
    specs.update(manifest.get("shared", {}))
    if skill is not None:
        specs.update(manifest.get("skills", {}).get(skill, {}))
    contracts: List[Contract] = []
    for glob_, spec in specs.items():
        c = Contract(artifact_glob=glob_)
        if "json_schema" in spec:
            p = PLUGIN_ROOT / spec["json_schema"]
            try:
                c.json_schema = json.loads(p.read_text(encoding="utf-8"))
                c.json_schema_path = _rel(p)
            except (OSError, json.JSONDecodeError) as e:
                findings.append(Finding("SCHEMA_PARSE", _rel(p), "", f"cannot load JSON Schema: {e}", _rel(p)))
            else:
                for ptr, kw in unsupported_keywords(c.json_schema):
                    findings.append(Finding(
                        "SCHEMA_PARSE", _rel(p), ptr,
                        f"JSON Schema keyword '{kw}' is not implemented by this validator's subset — "
                        f"it would be skipped silently. Add it to _ENFORCED_KEYWORDS (with a check) or "
                        f"_ANNOTATION_KEYWORDS (if it carries no constraint).", _rel(p)))
        if "shape" in spec:
            c.shape = build_shape_contract(spec, findings)
        for route in spec.get("route_shapes", []):
            built = build_shape_contract(route, findings)
            if built is not None:
                c.routes.append((route["when_path"], route.get("when_value"), built))
        contracts.append(c)
    return contracts


def _value_at(value: Any, dotted: str) -> Any:
    cur = value
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def artifact_name(p: Path) -> str:
    """Normalise 'scenarios/scenario-001.preferences.json' → 'scenarios/scenario-NNN.preferences.json'."""
    name = p.name
    name = re.sub(r"scenario-\d+\.", "scenario-NNN.", name)
    if p.parent.name == "scenarios":
        return "scenarios/" + name
    return name


def find_artifacts(run_dir: Path) -> List[Path]:
    out: List[Path] = []
    for p in sorted(run_dir.rglob("*.json")):
        rel = p.relative_to(run_dir)
        parts = rel.parts
        if any(part in ("live-capture", "workspace-terraform", ".terraform", "node_modules") for part in parts):
            continue
        if p.name.startswith("expected-") or p.name.startswith("clarify-answers"):
            continue
        out.append(p)
    return out


def validate_run_dir(run_dir: Path, skill: Optional[str], manifest: Dict[str, Any], findings: List[Finding]) -> int:
    contracts = build_contracts(manifest, skill, findings)
    checked = 0
    for p in find_artifacts(run_dir):
        name = artifact_name(p)
        matched = [c for c in contracts if fnmatch.fnmatch(name, c.artifact_glob)]
        rel = _rel(p)
        if not matched:
            if skill is not None:
                findings.append(Finding("NO_CONTRACT", rel, "", f"no contract covers '{name}' for skill {skill}", ""))
            continue
        try:
            value = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            findings.append(Finding("TYPE_MISMATCH", rel, "$", f"artifact is not valid JSON: {e.msg}", ""))
            continue
        checked += 1
        for c in matched:
            if c.json_schema is not None:
                validate_json_schema(c.json_schema, value, "", rel, c.json_schema_path, findings)
            shape = c.shape
            for path, expect, route in c.routes:
                if _value_at(value, path) == expect:
                    shape = route
                    break
            if shape is not None:
                validate_shape(shape.root, value, "", rel, shape.label, findings)
    return checked


# --------------------------------------------------------------------------- baseline


def apply_baseline(findings: List[Finding], baseline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Mark findings matched by a baseline entry. Returns entries that matched nothing."""
    entries = baseline.get("entries", [])
    used = [False] * len(entries)
    for f in findings:
        for i, e in enumerate(entries):
            if e.get("code") != f.code:
                continue
            if not fnmatch.fnmatch(f.artifact, e.get("artifact", "*")):
                continue
            if not fnmatch.fnmatch(f.path, e.get("path", "*")):
                continue
            f.baselined = True
            f.baseline_reason = e.get("reason", "")
            used[i] = True
            break
    return [e for e, u in zip(entries, used) if not u]


# --------------------------------------------------------------------------- CLI


def _rel(p: Path) -> str:
    """Paths in findings are relative to the plugin root (stable across cwd, so the
    baseline's artifact globs match whether the tool runs from the repo root or the
    plugin directory); paths outside the plugin fall back to absolute."""
    try:
        return str(p.resolve().relative_to(PLUGIN_ROOT))
    except ValueError:
        return str(p.resolve())


def skill_for_fixture(dirname: str, manifest: Dict[str, Any]) -> Optional[str]:
    for prefix, skill in manifest.get("fixture_prefixes", {}).items():
        if dirname.startswith(prefix):
            return skill
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true", help="parse every contract document only")
    mode.add_argument("--fixtures", action="store_true", help="validate the fixture goldens")
    mode.add_argument("--run-dir", type=Path, help="a .migration/<run> directory to validate")
    ap.add_argument("--skill", choices=["gcp-to-aws", "heroku-to-aws", "azure-to-aws"],
                    help="required with --run-dir")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--baseline", type=Path, default=None,
                    help="baseline file to apply; defaults to the shipped fixture baseline for --fixtures "
                         "and to none for --run-dir (the shipped entries describe the fixture corpus)")
    ap.add_argument("--no-baseline", action="store_true", help="ignore the baseline file")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    manifest = load_manifest(args.manifest)
    findings: List[Finding] = []
    checked = 0

    if args.self_check:
        for skill in manifest.get("skills", {}):
            build_contracts(manifest, skill, findings)
    elif args.fixtures:
        fixtures_root = PLUGIN_ROOT / "fixtures"
        for d in sorted(p for p in fixtures_root.iterdir() if p.is_dir()):
            skill = skill_for_fixture(d.name, manifest)
            checked += validate_run_dir(d, skill, manifest, findings)
    else:
        if not args.skill:
            ap.error("--run-dir requires --skill")
        if not args.run_dir.is_dir():
            ap.error(f"{args.run_dir} is not a directory")
        checked += validate_run_dir(args.run_dir, args.skill, manifest, findings)

    # The shipped baseline is the fixture corpus' burn-down list (every entry's artifact
    # glob is `fixtures/...`), so it applies by default only to --fixtures. A real run gets
    # a baseline only when the caller names one — and then every entry must match.
    baseline_path: Optional[Path] = args.baseline
    if baseline_path is None and args.fixtures:
        baseline_path = DEFAULT_BASELINE
    stale: List[Dict[str, Any]] = []
    if not args.no_baseline and baseline_path is not None and baseline_path.exists() and not args.self_check:
        stale = apply_baseline(findings, json.loads(baseline_path.read_text(encoding="utf-8")))
        for e in stale:
            # a baseline entry that matches nothing is either fixed (remove it) or mistyped
            # (it is hiding nothing and would hide a future finding by accident) — fail either way
            findings.append(Finding("STALE_BASELINE", _rel(baseline_path), e.get("path", "*"),
                                    f"entry matched no finding — remove it, or fix its code/artifact/path: {json.dumps(e)}",
                                    ""))

    # de-duplicate identical findings (several contracts can cover one artifact)
    seen: Set[Tuple[str, str, str, str]] = set()
    unique: List[Finding] = []
    for f in findings:
        key = (f.code, f.artifact, f.path, f.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    findings = unique

    errors = [f for f in findings if f.severity == "error" and not f.baselined]
    baselined = [f for f in findings if f.baselined]
    infos = [f for f in findings if f.severity == "info"]

    if args.json:
        print(json.dumps({"checked_artifacts": checked, "errors": [f.as_dict() for f in errors],
                          "baselined": [f.as_dict() for f in baselined], "info": [f.as_dict() for f in infos],
                          "stale_baseline_entries": stale}, indent=2))
    else:
        for f in errors:
            print(f"ERROR  {f.code:<17} {f.artifact} :: {f.path}\n       {f.message}" +
                  (f"\n       contract: {f.contract}" if f.contract else ""))
        for f in infos:
            print(f"info   {f.code:<17} {f.artifact} :: {f.message}")
        if baselined:
            by_code: Dict[str, int] = {}
            for f in baselined:
                by_code[f.code] = by_code.get(f.code, 0) + 1
            print(f"baselined (known, explained, not failing): " +
                  ", ".join(f"{k}={v}" for k, v in sorted(by_code.items())))
        print(f"\n{'FAIL' if errors else 'PASS'} — {checked} artifact(s) checked, "
              f"{len(errors)} error(s), {len(baselined)} baselined, {len(infos)} info")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
