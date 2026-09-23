#!/usr/bin/env python3
"""Static policy checks on generated Terraform (no provider init required).

Read-only VERDICT PRODUCER. This script never edits .tf files and never touches
run state (.phase-status.json). It parses HCL, evaluates policy, and emits a
structured verdict (stdout summary + optional --json report). Remediation and any
phase/state decisions belong to the CALLER (see tf-best-practices SKILL.md).

Enforces (each rule is fail-open on ambiguity — fires only on unambiguous,
in-block literal evidence, so a valid stack is never falsely blocked):
  - Internet-facing ALB TLS posture:
      * HTTPS listener on port 443 with certificate_arn and a forward action
      * HTTP listener on port 80 must redirect to HTTPS (never forward to targets)
  - rds_not_public: aws_db_instance / aws_rds_cluster must not set
    publicly_accessible = true (fail-open when variable-driven or absent).
  - db_sg_no_public_ingress: an inline aws_security_group ingress covering a
    database port (5432 / 3306) must not allow 0.0.0.0/0 (IPv4) or ::/0 (IPv6)
    (fail-open on separate aws_security_group_rule /
    aws_vpc_security_group_ingress_rule resources, which this static reader
    cannot correlate).
  - sg_no_public_admin_ingress: an inline ingress must not open a well-known
    admin/datastore port (SSH, RDP, Redis, Memcached, Mongo, Elasticsearch,
    Kibana) to 0.0.0.0/0 or ::/0. Scoped to a fixed never-public port list — web
    ports and app/game ports are not flagged. Same inline-only fail-open scope.
    Both SG rules read cidr_blocks and ipv6_cidr_blocks independently: an
    IPv6-only or dual-stack VPC is exposed by ::/0 exactly as IPv4 is by
    0.0.0.0/0.
  - no_wildcard_iam: a literal IAM policy document with Effect "Allow" must not
    use Action "*" or Resource "*", except an isolated
    elasticbeanstalk:CreateStorageLocation statement because AWS provides no
    resource-level permission for it (fail-open on aws_iam_policy_document data
    sources, whose statements are not visible as literal JSON here).
  - rds_encryption_at_rest: aws_db_instance / aws_rds_cluster must set
    storage_encrypted = true (RDS defaults to UNENCRYPTED). Fail-open when
    variable-driven. S3 is intentionally NOT checked: buckets have default
    SSE-S3 since Jan 2023, so a missing SSE block is not an unencrypted bucket.
  - elasticache_encryption_at_rest: aws_elasticache_replication_group must set
    at_rest_encryption_enabled = true; a standalone Redis aws_elasticache_cluster
    must set transit_encryption_enabled = true (at_rest_encryption_enabled is not
    a valid argument on that resource — at-rest requires a replication group).
    Fail-open when variable-driven.

Usage:
  python3 validate-terraform-policy.py /path/to/terraform [--json report.json]

Exit 0 on POLICY_OK, 1 on POLICY_FAIL, 2 on usage/IO error.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

RESOURCE_OPEN = re.compile(
    r'resource\s+"(?P<type>[a-zA-Z0-9_]+)"\s+"(?P<name>[^"]+)"\s*\{',
    re.MULTILINE,
)


@dataclass(frozen=True)
class Violation:
    check: str          # "policy"
    rule: str           # "alb_https_listener" | "alb_http_redirect" | "no_tf_files"
                        # | "rds_not_public" | "db_sg_no_public_ingress"
                        # | "no_wildcard_iam" | "rds_encryption_at_rest"
    file: str
    line: int           # 1-based; 0 if unknown
    severity: str       # "error" | "warning"
    summary: str
    fix_hint: str


@dataclass(frozen=True)
class ListenerSpec:
    file: str
    name: str
    line: int
    port: int | None
    protocol: str | None
    action_type: str | None
    has_certificate_arn: bool


def _read_tf_files(terraform_dir: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for path in sorted(terraform_dir.rglob("*.tf")):
        files.append((str(path.relative_to(terraform_dir)), path.read_text(encoding="utf-8")))
    return files


_HEREDOC_OPEN = re.compile(r"<<(-?)\s*([A-Za-z_][A-Za-z0-9_]*)")


def _lex_hcl(block: str) -> tuple[list[int], list[bool], list[bool]]:
    """Scan HCL once, returning per-index (brace depth, is-real-code, is-comment)
    arrays.

    Only braces that are actual block delimiters count toward depth. HCL permits
    `{` and `}` inside `#` / `//` line comments, `/* */` block comments, quoted
    strings, and heredoc bodies, and those are NOT delimiters — counting them
    would let unrelated text shift the apparent nesting of a real attribute.
    `is_code` additionally lets callers ignore an attribute that only appears
    commented out. `is_comment` marks exactly the comment spans (delimiters
    included, terminating newline excluded), distinguishing them from the other
    non-code states — a reader that must ignore comments but still read string
    contents (list entries are quoted strings) needs that distinction.

    Interpolations are treated as opaque string content: `{` and `}` inside a
    string are both ignored, so the running depth is unaffected either way. This
    requires tracking interpolation nesting, because `${...}` may contain its own
    quoted strings (`"${lookup(var.m, "a{b")}"`). Without that, the inner string's
    closing quote would end the OUTER string and everything after it would be
    scanned as code — putting textual braces back into the depth count, which is
    the failure mode this lexer exists to prevent.
    """
    n = len(block)
    depths = [0] * n
    codes = [False] * n
    comments = [False] * n
    depth = 0
    state = "code"
    tag = ""
    tag_indent_ok = False
    interp = 0          # open `${` levels inside the current string
    inner_str = False   # inside a quoted string nested in an interpolation
    i = 0
    while i < n:
        ch = block[i]
        nxt = block[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "#" or (ch == "/" and nxt == "/"):
                depths[i], codes[i], comments[i] = depth, False, True
                state = "line_comment"
                i += 1
                continue
            if ch == "/" and nxt == "*":
                depths[i], depths[i + 1] = depth, depth
                comments[i], comments[i + 1] = True, True
                state = "block_comment"
                i += 2
                continue
            if ch == '"':
                depths[i], codes[i] = depth, False
                state = "string"
                interp = 0
                inner_str = False
                i += 1
                continue
            if ch == "<" and nxt == "<":
                heredoc = _HEREDOC_OPEN.match(block, i)
                if heredoc:
                    for j in range(i, heredoc.end()):
                        depths[j] = depth
                    tag = heredoc.group(2)
                    # Only `<<-TAG` permits an indented terminator; plain `<<TAG`
                    # requires it at column 0, so an indented tag-looking line is
                    # ordinary body text.
                    tag_indent_ok = heredoc.group(1) == "-"
                    state = "heredoc"
                    i = heredoc.end()
                    continue
            depths[i], codes[i] = depth, True
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
            continue

        depths[i] = depth
        if state == "line_comment":
            if ch == "\n":
                state = "code"
            else:
                comments[i] = True
            i += 1
        elif state == "block_comment":
            comments[i] = True
            if ch == "*" and nxt == "/":
                depths[i + 1] = depth
                comments[i + 1] = True
                state = "code"
                i += 2
            else:
                i += 1
        elif state == "string":
            if ch == "\\" and i + 1 < n:
                depths[i + 1] = depth
                i += 2
            elif ch == "$" and nxt == "{" and not inner_str:
                depths[i + 1] = depth
                interp += 1
                i += 2
            elif interp > 0 and ch == '"':
                # A quote inside `${...}` opens/closes a NESTED string; it must not
                # be mistaken for the end of the interpolated string itself.
                inner_str = not inner_str
                i += 1
            elif interp > 0 and ch == "}" and not inner_str:
                interp -= 1
                i += 1
            else:
                if ch == '"' and interp == 0:
                    state = "code"
                i += 1
        else:  # heredoc — body is literal until a line holding only the tag
            end = block.find("\n", i)
            line_end = n if end == -1 else end + 1
            for j in range(i, line_end):
                depths[j] = depth
            line = block[i:line_end]
            terminator = line.strip() if tag_indent_ok else line.rstrip()
            if terminator == tag:
                state = "code"
            i = line_end
    return depths, codes, comments


def _extract_braced_block(
    content: str,
    open_brace: int,
    lexed: tuple[list[int], list[bool], list[bool]] | None = None,
) -> tuple[str, int]:
    """Return (block_text_including_braces, index_after_close).

    Uses _lex_hcl, not raw brace counting: a `}` inside a comment, string, or
    heredoc body is not a delimiter, and treating it as one truncates the block
    early. That silently drops every attribute after the stray brace — a resource
    body cut before `publicly_accessible = true` reports no violation at all. Pass
    `lexed` to reuse a scan already done for this exact `content`.
    """
    depths, codes, _ = lexed if lexed is not None else _lex_hcl(content)
    if open_brace >= len(codes) or not codes[open_brace]:
        return content[open_brace:], len(content)
    target = depths[open_brace] + 1
    for idx in range(open_brace + 1, len(content)):
        if codes[idx] and content[idx] == "}" and depths[idx] == target:
            return content[open_brace : idx + 1], idx + 1
    return content[open_brace:], len(content)


def _extract_blocks(content: str, resource_type: str) -> list[tuple[str, str, int]]:
    """Return (name, body, 1-based line) for each resource of resource_type.

    The file is lexed once and the scan is shared with every extraction, so
    extraction, attribute presence, and attribute values all agree on what counts
    as code. A resource declaration that is itself commented out is skipped.
    """
    lexed = _lex_hcl(content)
    _, codes, _ = lexed
    blocks: list[tuple[str, str, int]] = []
    for match in RESOURCE_OPEN.finditer(content):
        if match.group("type") != resource_type:
            continue
        if not codes[match.start()]:
            continue
        name = match.group("name")
        brace_start = match.end() - 1
        body, _ = _extract_braced_block(content, brace_start, lexed)
        line = content.count("\n", 0, match.start()) + 1
        blocks.append((name, body, line))
    return blocks


def _own_blocks(body: str, block_type: str) -> list[str]:
    """Bodies of `block_type { ... }` blocks declared directly in `body`.

    Shares the lexer so a commented-out `ingress {` is not treated as a real rule.
    """
    lexed = _lex_hcl(body)
    _, codes, _ = lexed
    found: list[str] = []
    for match in re.finditer(rf"{re.escape(block_type)}\s*\{{", body):
        if not codes[match.start()]:
            continue
        inner, _ = _extract_braced_block(body, match.end() - 1, lexed)
        found.append(inner)
    return found


def _has_own_attr(block: str, attr: str) -> bool:
    """True if `attr` is assigned among the block's OWN attributes.

    Presence must use the same lexical rules as value reading. A probe that counts
    a commented-out assignment while the reader correctly ignores it makes the two
    disagree, and the rules that branch on "attribute present but unreadable →
    variable-driven → fail open" then skip a resource whose attribute is genuinely
    absent.
    """
    return (
        _first_own_attr(block, rf"^\s*{re.escape(attr)}\s*=", re.MULTILINE) is not None
    )


def _first_own_attr(block: str, pattern: str, flags: int = 0) -> re.Match[str] | None:
    """First match of `pattern` that sits among the block's OWN attributes.

    `_extract_blocks` / `_extract_braced_block` return a resource body INCLUDING
    its nested blocks, and a plain `re.search` takes the first match anywhere —
    so an attribute of a nested block can be read as if it belonged to the
    resource. `aws_lb_listener` is the live example: `default_action { redirect {
    port = "443", protocol = "HTTPS" } }` carries both a `port` and a `protocol`,
    and HCL does not require the listener's own `port` to precede its
    `default_action` (`terraform fmt` will not reorder attributes relative to
    blocks). Read whole-body, such a listener reports port 443 / protocol HTTPS
    instead of 80 / HTTP.

    Candidates are therefore filtered by brace depth — only those at the body's
    own depth are eligible (1 for a braced body as returned by
    _extract_braced_block, 0 for a bare attribute fragment) — and a candidate that
    is merely commented out is skipped.

    Depth comes from _lex_hcl, NOT from raw `{`/`}` counting. Raw counting is
    unsafe here: a brace in an unrelated comment or string literal would shift the
    depth of a real top-level attribute and hide it, and for these rules a hidden
    attribute means a MISSED violation — `publicly_accessible = true` reported as
    compliant. That is the failure class this reader exists to prevent, so
    lexically-irrelevant braces must not participate.
    """
    base = 1 if block.lstrip().startswith("{") else 0
    depths, codes, _ = _lex_hcl(block)
    for match in re.finditer(pattern, block, flags):
        start = match.start()
        if start < len(codes) and codes[start] and depths[start] == base:
            return match
    return None


def _attr_string(block: str, attr: str) -> str | None:
    match = _first_own_attr(
        block, rf'^\s*{re.escape(attr)}\s*=\s*"([^"]*)"', re.MULTILINE
    )
    if match:
        return match.group(1)
    bool_match = _first_own_attr(
        block,
        rf"^\s*{re.escape(attr)}\s*=\s*(true|false)\b",
        re.MULTILINE | re.IGNORECASE,
    )
    return bool_match.group(1).lower() if bool_match else None


def _attr_int(block: str, attr: str) -> int | None:
    """Read an integer attribute, accepting BARE (443) and QUOTED ("443") forms.

    Terraform accepts a quoted integer for number-typed arguments (`port = "443"`
    is valid, idiomatic, `terraform fmt`-clean HCL and converts to 443), so a
    bare-only reader silently degrades every port-based rule: a correct HTTPS
    listener written as port = "443" was reported as a missing HTTPS listener
    (false positive), and — worse — an ingress with from_port = "5432" /
    cidr_blocks = ["0.0.0.0/0"] produced no covered ports, so the public-ingress
    rules never fired on a genuinely world-open database (fail-CLOSED miss).

    The quoted arm requires the value to be ENTIRELY digits (the closing quote is
    anchored against the digits), so "443x", "443-444" and "${var.port}" do NOT
    read as 443 — they return None and keep the existing fail-open behaviour for
    non-literal / non-integer values.

    Accepting the quoted form also makes a nested block's `port` a candidate where
    a bare-only pattern could never match one, so the search is scoped to the
    block's own attributes via _first_own_attr — see its docstring.
    """
    match = _first_own_attr(
        block,
        rf'^\s*{re.escape(attr)}\s*=\s*(?:(\d+)|"(\d+)")',
        re.MULTILINE,
    )
    if not match:
        return None
    bare, quoted = match.group(1), match.group(2)
    return int(bare if bare is not None else quoted)


def _default_action_type(block: str) -> str | None:
    """Extract default_action { ... type = "X" ... } via BRACE-DEPTH matching.

    NOTE: the naive r'default_action\\s*\\{[^}]*?type' approach breaks when the
    default_action contains a nested block (redirect {} / forward {}) placed
    BEFORE the type attribute — it stops at the first '}'. We isolate the full
    default_action body by brace matching, then read `type` from it.
    """
    m = re.search(r"default_action\s*\{", block)
    if not m:
        return None
    body, _ = _extract_braced_block(block, m.end() - 1)
    tmatch = re.search(r'^\s*type\s*=\s*"([^"]+)"', body, re.MULTILINE)
    return tmatch.group(1) if tmatch else None


def _has_internet_facing_alb(tf_files: list[tuple[str, str]]) -> bool:
    """True if any aws_lb is an internet-facing APPLICATION load balancer.

    The HTTPS-listener posture applies only to Application Load Balancers (L7).
    Network (L4 TCP/UDP) and Gateway (L3) load balancers legitimately have no
    HTTPS:443 listener, so an internet-facing NLB/GWLB must NOT be flagged.

    - load_balancer_type == "network" | "gateway" (literal) => skip (not an ALB).
    - load_balancer_type absent (Terraform default is "application"),
      "application", or variable-driven => treat as an ALB (fail-safe).
    - internal absent, "false", or variable-driven => internet-facing (fail-safe:
      demand HTTPS unless explicitly internal=true).
    """
    for _, content in tf_files:
        for _, body, _line in _extract_blocks(content, "aws_lb"):
            lb_type = _attr_string(body, "load_balancer_type")
            if lb_type in ("network", "gateway"):
                continue  # L4/L3 balancer — HTTPS-listener rule does not apply
            internal = _attr_string(body, "internal")
            if internal is None or internal == "false":
                return True
    return False


def _parse_listeners(tf_files: list[tuple[str, str]]) -> list[ListenerSpec]:
    listeners: list[ListenerSpec] = []
    for rel_path, content in tf_files:
        for name, body, line in _extract_blocks(content, "aws_lb_listener"):
            listeners.append(
                ListenerSpec(
                    file=rel_path,
                    name=name,
                    line=line,
                    port=_attr_int(body, "port"),
                    protocol=_attr_string(body, "protocol"),
                    action_type=_default_action_type(body),
                    has_certificate_arn="certificate_arn" in body,
                )
            )
    return listeners


def check_alb_https_policy(terraform_dir: Path) -> list[Violation]:
    tf_files = _read_tf_files(terraform_dir)
    if not tf_files:
        return [
            Violation(
                check="policy",
                rule="no_tf_files",
                file=".",
                line=0,
                severity="error",
                summary="No .tf files found in terraform directory",
                fix_hint="Ensure the generate step wrote terraform/ before validation",
            )
        ]

    if not _has_internet_facing_alb(tf_files):
        return []

    listeners = _parse_listeners(tf_files)
    violations: list[Violation] = []

    https_ok = [
        l
        for l in listeners
        if l.port == 443
        and (l.protocol or "").upper() == "HTTPS"
        and l.has_certificate_arn
        and l.action_type == "forward"
    ]

    if not https_ok:
        # Point at an aws_lb file when we can, else the first tf file.
        lb_file = next(
            (rel for rel, c in tf_files if _extract_blocks(c, "aws_lb")),
            tf_files[0][0],
        )
        violations.append(
            Violation(
                check="policy",
                rule="alb_https_listener",
                file=lb_file,
                line=0,
                severity="error",
                summary=(
                    "Internet-facing ALB requires an HTTPS listener on port 443 "
                    "with certificate_arn and a forward action"
                ),
                fix_hint=(
                    'Add an aws_lb_listener on port 443, protocol "HTTPS", with '
                    "ssl_policy, certificate_arn, and a forward default_action"
                ),
            )
        )

    for l in listeners:
        if l.port != 80 or (l.protocol or "").upper() != "HTTP":
            continue
        if l.action_type == "forward":
            violations.append(
                Violation(
                    check="policy",
                    rule="alb_http_redirect",
                    file=l.file,
                    line=l.line,
                    severity="error",
                    summary=(
                        f"ALB HTTP listener '{l.name}' on port 80 forwards to targets; "
                        "it must redirect to HTTPS"
                    ),
                    fix_hint=(
                        "Replace the forward default_action with a redirect block: "
                        'type = "redirect", redirect { port = "443", protocol = "HTTPS", '
                        'status_code = "HTTP_301" }'
                    ),
                )
            )

    return violations


_DB_PORTS = (5432, 3306)

# Well-known admin / datastore ports that should never be open to the whole
# internet in either address family (0.0.0.0/0 or ::/0).
# Deliberately EXCLUDES 5432/3306 (covered by db_sg_no_public_ingress, so no
# double-reporting) and web ports 80/443 (legitimately public). Kept tight to
# unambiguous "never public" ports so valid designs (e.g. game servers on high
# ports) are not falsely flagged.
_SENSITIVE_NONDB_PORTS = (
    22,     # SSH
    3389,   # RDP
    6379,   # Redis
    11211,  # Memcached
    27017,  # MongoDB
    9200,   # Elasticsearch HTTP
    9300,   # Elasticsearch transport
    5601,   # Kibana
)


def check_rds_not_public(tf_files: list[tuple[str, str]]) -> list[Violation]:
    """Flag RDS resources that explicitly set publicly_accessible = true.

    Fail-open: absent (RDS default is false) or variable-driven values do not
    fire — only a literal `true` is a violation.
    """
    violations: list[Violation] = []
    for rel_path, content in tf_files:
        for res_type in ("aws_db_instance", "aws_rds_cluster"):
            for name, body, line in _extract_blocks(content, res_type):
                if _attr_string(body, "publicly_accessible") == "true":
                    violations.append(
                        Violation(
                            check="policy",
                            rule="rds_not_public",
                            file=rel_path,
                            line=line,
                            severity="error",
                            summary=(
                                f"{res_type} '{name}' sets publicly_accessible = true — "
                                "the database is reachable from the internet"
                            ),
                            fix_hint=(
                                "Set publicly_accessible = false and place the database in "
                                "private subnets; reach it from application security groups only"
                            ),
                        )
                    )
    return violations


def _ingress_covered_ports(ingress_body: str, ports: tuple[int, ...]) -> list[int]:
    """Return the subset of `ports` whose value falls in this ingress rule's
    [from_port, to_port] range. Empty when the range is missing/non-literal."""
    from_p = _attr_int(ingress_body, "from_port")
    to_p = _attr_int(ingress_body, "to_port")
    if from_p is None or to_p is None:
        return []
    return [port for port in ports if from_p <= port <= to_p]


def _ingress_covers_db_port(ingress_body: str) -> bool:
    return bool(_ingress_covered_ports(ingress_body, _DB_PORTS))


def _strip_hcl_comments(text: str) -> str:
    """Blank out comment spans, using the lexer's classification of them.

    This must share _lex_hcl's single definition of "what counts as code" rather
    than keep a parallel comment regex: a regex cannot know that a `/*` inside a
    quoted string does not open a comment, and stripping from such a false opener
    swallows every real attribute up to the next `*/` — including a live
    `cidr_blocks = ["0.0.0.0/0"]`, which then reports POLICY_OK. Comment
    characters are replaced with spaces rather than deleted, so surviving tokens
    never fuse and line anchors keep working.
    """
    _, _, comments = _lex_hcl(text)
    return "".join(" " if comments[i] else ch for i, ch in enumerate(text))


def _attr_list_inner(block: str, attr: str) -> str | None:
    """Return the raw text inside a literal `attr = [ ... ]`, else None.

    The name must start a line OR directly follow a `{`. The line-start arm keeps
    `cidr_blocks` from matching the tail of `ipv6_cidr_blocks` (reading one list
    while believing it is the other silently inverts the verdict); the brace arm
    keeps an attribute that shares its block's opening line visible, e.g.
    `ingress { cidr_blocks = [...]`, which is valid HCL that a line-anchored
    pattern alone would miss.
    """
    m = re.search(
        rf"(?:^|\{{)\s*{re.escape(attr)}\s*=\s*\[(.*?)\]",
        block,
        re.DOTALL | re.MULTILINE,
    )
    return m.group(1) if m else None


def _is_entire_internet(cidr: str) -> bool:
    """True if `cidr` is a literal range covering the whole address space.

    Canonicalises through `ipaddress` instead of comparing text, because IPv6 has
    many legal spellings of the zero address (`::/0`, `::0/0`, `0:0:0:0:0:0:0:0/0`)
    and nothing in Terraform normalises them — `terraform fmt` treats a CIDR as an
    opaque string. Anything that is not a parseable literal (`var.x`, `${...}`,
    malformed text) returns False, preserving the module's fail-open posture.
    """
    try:
        return ipaddress.ip_network(cidr, strict=False).prefixlen == 0
    except ValueError:
        return False


def _ingress_public_cidrs(ingress_body: str) -> list[str]:
    """Return the "entire internet" CIDRs this ingress rule allows, both families.

    IPv4 `0.0.0.0/0` and IPv6 `::/0` are equally public: on a dual-stack or
    IPv6-only VPC, `::/0` on an admin port is a live exposure. Each family is read
    under its own attribute name so the two are never confused, comments are
    stripped first (by the shared lexer, so a comment marker inside a quoted
    string is not a comment), and only quoted string literals count as list
    entries — so a range mentioned in a comment inside the list is not an allowed
    range. Values are returned as spelled in the file, so the violation names
    what is written. Empty list => no unambiguous public exposure.
    """
    body = _strip_hcl_comments(ingress_body)
    found: list[str] = []
    for attr in ("cidr_blocks", "ipv6_cidr_blocks"):
        inner = _attr_list_inner(body, attr)
        if inner is None:
            continue
        for cidr in re.findall(r'"([^"]*)"', inner):
            if _is_entire_internet(cidr) and cidr not in found:
                found.append(cidr)
    return found


def check_db_sg_no_public_ingress(tf_files: list[tuple[str, str]]) -> list[Violation]:
    """Flag inline security-group ingress that opens a DB port to 0.0.0.0/0 or ::/0.

    Fail-open: only INLINE `ingress { ... }` blocks inside aws_security_group are
    inspected. Separate aws_security_group_rule / aws_vpc_security_group_ingress_rule
    resources are not correlated here (this static reader cannot resolve the
    referenced security_group_id), so they never trigger a false positive.
    """
    violations: list[Violation] = []
    for rel_path, content in tf_files:
        for name, body, line in _extract_blocks(content, "aws_security_group"):
            # Walk each inline ingress block via brace matching.
            for ingress_body in _own_blocks(body, "ingress"):
                public = _ingress_public_cidrs(ingress_body)
                if _ingress_covers_db_port(ingress_body) and public:
                    violations.append(
                        Violation(
                            check="policy",
                            rule="db_sg_no_public_ingress",
                            file=rel_path,
                            line=line,
                            severity="error",
                            summary=(
                                f"aws_security_group '{name}' has an ingress rule that opens a "
                                f"database port (5432/3306) to {' and '.join(public)}"
                            ),
                            fix_hint=(
                                "Restrict the ingress to the application security group "
                                "(security_groups = [aws_security_group.app.id]) or a private "
                                "CIDR — never 0.0.0.0/0 or ::/0 for a database port"
                            ),
                        )
                    )
    return violations


def check_sg_no_public_admin_ingress(tf_files: list[tuple[str, str]]) -> list[Violation]:
    """Flag inline security-group ingress that opens a well-known admin/datastore
    port (SSH, RDP, Redis, Memcached, Mongo, Elasticsearch, Kibana) to 0.0.0.0/0
    or ::/0.

    Deliberately scoped to a fixed list of ports that are ~never legitimately
    public — NOT "any public ingress" — so valid public workloads (web on
    80/443, game servers on high ports, etc.) are not falsely flagged. DB ports
    (5432/3306) are handled by db_sg_no_public_ingress and excluded here to avoid
    double-reporting.

    Fail-open (same scope as db_sg_no_public_ingress): only INLINE ingress blocks
    inside aws_security_group are inspected; separate rule resources are not
    correlated.
    """
    port_names = {
        22: "SSH", 3389: "RDP", 6379: "Redis", 11211: "Memcached",
        27017: "MongoDB", 9200: "Elasticsearch", 9300: "Elasticsearch",
        5601: "Kibana",
    }
    violations: list[Violation] = []
    for rel_path, content in tf_files:
        for name, body, line in _extract_blocks(content, "aws_security_group"):
            for ingress_body in _own_blocks(body, "ingress"):
                public = _ingress_public_cidrs(ingress_body)
                if not public:
                    continue
                hit = _ingress_covered_ports(ingress_body, _SENSITIVE_NONDB_PORTS)
                if not hit:
                    continue
                labels = ", ".join(f"{p} ({port_names[p]})" for p in sorted(set(hit)))
                violations.append(
                    Violation(
                        check="policy",
                        rule="sg_no_public_admin_ingress",
                        file=rel_path,
                        line=line,
                        severity="error",
                        summary=(
                            f"aws_security_group '{name}' opens sensitive port(s) {labels} "
                            f"to {' and '.join(public)}"
                        ),
                        fix_hint=(
                            "Restrict this ingress to a bastion/app security group or a private "
                            "CIDR; never expose admin or datastore ports to the internet"
                        ),
                    )
                )
    return violations


def _iam_key_is_wildcard(body: str, key: str) -> bool:
    """True if an IAM policy `key` (Action/Resource) is a sole "*" — string OR
    list form. Matches:
        "Action"   : "*"          (heredoc JSON, string)
        Action     = "*"          (jsonencode HCL, string)
        "Resource" : ["*"]        (heredoc JSON, single-element list)
        Resource   = ["*"]        (jsonencode HCL, single-element list)
    A list is only treated as wildcard when "*" is its ONLY element — a list that
    also contains scoped ARNs/actions is not a blanket wildcard.
    """
    # String form: key = "*"
    if re.search(rf'"?{key}"?\s*[:=]\s*"\*"', body):
        return True
    # List form: key = [ "*" ] with nothing else inside the brackets.
    m = re.search(rf'"?{key}"?\s*[:=]\s*\[(.*?)\]', body, re.DOTALL)
    if m:
        inner = m.group(1).strip()
        if inner == '"*"':
            return True
    return False


def _remove_allowed_resource_wildcard_statements(body: str) -> str:
    """Remove narrowly-approved IAM statements whose actions require Resource "*".

    Keep this allowlist statement-shaped rather than action-token-shaped so an
    approved action cannot hide a second, over-broad action in the same statement.
    """
    return re.sub(
        r"""
        \{\s*
        "?Effect"?\s*[:=]\s*"Allow"\s*,?\s*
        "?Action"?\s*[:=]\s*"elasticbeanstalk:CreateStorageLocation"\s*,?\s*
        "?Resource"?\s*[:=]\s*"\*"\s*,?\s*
        \}
        """,
        "",
        body,
        flags=re.DOTALL | re.VERBOSE,
    )


def check_no_wildcard_iam(tf_files: list[tuple[str, str]]) -> list[Violation]:
    """Flag literal IAM policy JSON with an unsafe Allow Action/Resource "*".

    Fail-open: only literal `policy = jsonencode({...})` / heredoc JSON inside
    aws_iam_policy, aws_iam_role_policy, or *_inline_policy blocks is scanned.
    aws_iam_policy_document DATA sources are not inspected (their statements are
    HCL blocks, not literal JSON here) — avoids false positives on the common,
    reviewable data-source pattern. Assume-role trust policies are excluded
    (a Service/AWS principal trust with Action sts:AssumeRole is not a wildcard).
    """
    violations: list[Violation] = []
    policy_res_types = ("aws_iam_policy", "aws_iam_role_policy", "aws_iam_group_policy",
                        "aws_iam_user_policy")
    for rel_path, content in tf_files:
        for res_type in policy_res_types:
            for name, body, line in _extract_blocks(content, res_type):
                # Accept both heredoc JSON ("Effect": "Allow") and HCL jsonencode
                # ({...}) (Effect = "Allow") forms — the separator is : or =.
                if not re.search(r'"?Effect"?\s*[:=]\s*"Allow"', body):
                    continue
                body_without_allowed = _remove_allowed_resource_wildcard_statements(body)
                if _iam_key_is_wildcard(body, "Action") or _iam_key_is_wildcard(
                    body_without_allowed, "Resource"
                ):
                    violations.append(
                        Violation(
                            check="policy",
                            rule="no_wildcard_iam",
                            file=rel_path,
                            line=line,
                            severity="error",
                            summary=(
                                f"{res_type} '{name}' grants Action \"*\" or Resource \"*\" "
                                "in an Allow statement — over-broad permissions"
                            ),
                            fix_hint=(
                                "Scope the policy to specific actions and resource ARNs; "
                                "isolate any documented action that requires Resource \"*\""
                            ),
                        )
                    )
    return violations


def check_rds_encryption_at_rest(tf_files: list[tuple[str, str]]) -> list[Violation]:
    """Flag RDS resources that do not enable storage_encrypted (RDS defaults to
    UNENCRYPTED).

    Fail-open: fires only when storage_encrypted is literally `false` OR the
    attribute is absent. A variable-driven value (storage_encrypted = var.x) is
    NOT flagged. S3 is intentionally excluded — buckets have default SSE-S3 since
    Jan 2023, so a missing SSE block is not an unencrypted bucket.
    """
    violations: list[Violation] = []
    for rel_path, content in tf_files:
        for res_type in ("aws_db_instance", "aws_rds_cluster"):
            for name, body, line in _extract_blocks(content, res_type):
                val = _attr_string(body, "storage_encrypted")
                # Variable-driven / non-literal → attribute present but not "true"/"false".
                has_attr = _has_own_attr(body, "storage_encrypted")
                if has_attr and val is None:
                    continue  # variable-driven — fail open
                if val == "true":
                    continue
                violations.append(
                    Violation(
                        check="policy",
                        rule="rds_encryption_at_rest",
                        file=rel_path,
                        line=line,
                        severity="error",
                        summary=(
                            f"{res_type} '{name}' does not set storage_encrypted = true — "
                            "RDS storage defaults to unencrypted"
                        ),
                        fix_hint="Set storage_encrypted = true (optionally with a kms_key_id)",
                    )
                )
    return violations


def check_elasticache_encryption_at_rest(tf_files: list[tuple[str, str]]) -> list[Violation]:
    """Flag ElastiCache replication groups without at-rest encryption enabled.

    Applies to aws_elasticache_replication_group (the resource that supports
    at_rest_encryption_enabled). Fires when the attribute is literally `false` or
    absent; a variable-driven value fails open. aws_elasticache_cluster is NOT
    checked — standalone Memcached clusters don't support this attribute and
    Redis-in-cluster is configured via the replication group.
    """
    violations: list[Violation] = []
    for rel_path, content in tf_files:
        for name, body, line in _extract_blocks(content, "aws_elasticache_replication_group"):
            val = _attr_string(body, "at_rest_encryption_enabled")
            has_attr = _has_own_attr(body, "at_rest_encryption_enabled")
            if has_attr and val is None:
                continue  # variable-driven — fail open
            if val == "true":
                continue
            violations.append(
                Violation(
                    check="policy",
                    rule="elasticache_encryption_at_rest",
                    file=rel_path,
                    line=line,
                    severity="error",
                    summary=(
                        f"aws_elasticache_replication_group '{name}' does not set "
                        "at_rest_encryption_enabled = true"
                    ),
                    fix_hint=(
                        "Set at_rest_encryption_enabled = true (and consider "
                        "transit_encryption_enabled = true for in-transit protection)"
                    ),
                )
            )
    return violations


def check_elasticache_cluster_encryption(tf_files: list[tuple[str, str]]) -> list[Violation]:
    """Flag single-node Redis aws_elasticache_cluster resources without encryption.

    aws_elasticache_cluster is the standalone (non-replication-group) cache form.
    Per the AWS provider schema, this resource exposes ONLY
    transit_encryption_enabled — at_rest_encryption_enabled is NOT a valid
    argument on aws_elasticache_cluster (it lives on
    aws_elasticache_replication_group). So for a Redis-engine cluster
    (engine = "redis") that is NOT a member of a replication group (no
    replication_group_id) we require transit_encryption_enabled = true, and the
    fix for at-rest is to move the cache into an encrypted
    aws_elasticache_replication_group — never to add a nonexistent cluster
    argument (which would produce Terraform that fails to apply).

    Exempt (fail open), matching the replication-group check's style:
    - engine == "memcached" (does not support these attributes),
    - a variable-driven engine or an absent engine (cannot evaluate literally),
    - a cluster that carries replication_group_id (encryption is enforced on the
      owning aws_elasticache_replication_group).
    A variable-driven encryption attribute also fails open.
    """
    violations: list[Violation] = []
    for rel_path, content in tf_files:
        for name, body, line in _extract_blocks(content, "aws_elasticache_cluster"):
            engine = _attr_string(body, "engine")
            if engine != "redis":
                continue  # memcached / variable-driven / absent engine → exempt
            if _has_own_attr(body, "replication_group_id"):
                continue  # node of a replication group — encryption enforced there
            # Only transit_encryption_enabled is a valid argument on this resource.
            val = _attr_string(body, "transit_encryption_enabled")
            has_attr = _has_own_attr(body, "transit_encryption_enabled")
            if has_attr and val is None:
                continue  # variable-driven — fail open
            if val == "true":
                continue
            violations.append(
                Violation(
                    check="policy",
                    rule="elasticache_encryption_at_rest",
                    file=rel_path,
                    line=line,
                    severity="error",
                    summary=(
                        f"aws_elasticache_cluster '{name}' (engine = redis) does "
                        "not set transit_encryption_enabled = true"
                    ),
                    fix_hint=(
                        "Set transit_encryption_enabled = true on the Redis "
                        "aws_elasticache_cluster. For at-rest encryption, move the "
                        "cache into an aws_elasticache_replication_group with "
                        "at_rest_encryption_enabled = true — at_rest_encryption_enabled "
                        "is not a valid argument on aws_elasticache_cluster."
                    ),
                )
            )
    return violations


def validate(terraform_dir: Path) -> tuple[bool, list[Violation]]:
    tf_files = _read_tf_files(terraform_dir)
    if not tf_files:
        # Preserve the existing no_tf_files verdict path.
        return False, check_alb_https_policy(terraform_dir)

    violations: list[Violation] = []
    violations.extend(check_alb_https_policy(terraform_dir))
    violations.extend(check_rds_not_public(tf_files))
    violations.extend(check_db_sg_no_public_ingress(tf_files))
    violations.extend(check_sg_no_public_admin_ingress(tf_files))
    violations.extend(check_no_wildcard_iam(tf_files))
    violations.extend(check_rds_encryption_at_rest(tf_files))
    violations.extend(check_elasticache_encryption_at_rest(tf_files))
    violations.extend(check_elasticache_cluster_encryption(tf_files))
    return len(violations) == 0, violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated Terraform policy rules")
    parser.add_argument("terraform_dir", type=Path, help="Path to terraform/ directory")
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional path to write a machine-readable JSON verdict",
    )
    args = parser.parse_args()

    terraform_dir = args.terraform_dir.resolve()
    if not terraform_dir.is_dir():
        print(f"POLICY_FAIL | path={terraform_dir} | reason=not_a_directory", file=sys.stderr)
        return 2

    ok, violations = validate(terraform_dir)

    if args.json is not None:
        report = {
            "check": "policy",
            "policy_status": "POLICY_OK" if ok else "POLICY_FAIL",
            "violations": [asdict(v) for v in violations],
        }
        try:
            args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"POLICY_FAIL | reason=json_write_failed | detail={exc}", file=sys.stderr)
            return 2

    checks = (
        "alb_https,rds_not_public,db_sg_no_public_ingress,sg_no_public_admin_ingress,"
        "no_wildcard_iam,rds_encryption,elasticache_encryption,"
        "elasticache_cluster_encryption"
    )

    if ok:
        print(f"POLICY_OK | checks={checks}")
        return 0

    print(f"POLICY_FAIL | checks={checks}", file=sys.stderr)
    for v in violations:
        print(
            f"POLICY_FAIL | file={v.file} | line={v.line} | rule={v.rule} | reason={v.summary}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
