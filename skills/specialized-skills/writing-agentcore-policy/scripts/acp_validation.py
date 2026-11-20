"""Local validation of one AgentCore policy statement (no AWS calls, no credentials).

Two dialects are told apart from the statement text:

* **Cedar** -- checked with ``cedarpy`` (syntax through the policy JSON AST, schema through
  ``validate_policies``). The claim and scope rules read the same JSON AST.
* **Dogwood** -- temporal blocks, guardrail providers and the output/redact effects. Checked with
  the pinned ``dogwood`` CLI when it is installed; otherwise the syntax and schema stages are
  ``unavailable`` and the result is ``incomplete``. The claim and guardrail rules fall back to
  scanning the comment- and string-masked source.

Nothing here proves service acceptance: every result lists what was not checked under
``coverage.not_checked``.

Environment variables read (by name only):
    AGENTCORE_POLICY_DOGWOOD  path or command name of the ``dogwood`` executable (else PATH)
    PATH                      only to locate ``dogwood`` and to pass through to it
Child processes get a cleared environment holding just ``PATH`` and a private ``HOME``.
Results never contain stderr, command lines or host paths.
"""

from __future__ import annotations

import difflib
import functools
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acp_common import SkillError, missing_dependency

NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
NAME_MAX = 48
STATEMENT_MIN = 35
STATEMENT_MAX = 10_000

#: The Dogwood CLI version whose JSON reports this module understands (crates.io `dogwood-cli`).
#: Only the latest patch release is accepted: 1.1.1 and 1.1.2 fix a stack overflow on deeply
#: nested policy text and exponential macro expansion. When upstream publishes a patch
#: release (https://github.com/dogwood-policy/dogwood/releases), raise this pin and the
#: install line in SKILL.md together, and run the tests against the new CLI (AGENTCORE_POLICY_DOGWOOD).
DOGWOOD_VERSIONS = ("dogwood 1.1.2",)
DOGWOOD_VERSION = DOGWOOD_VERSIONS[0]
DOGWOOD_SETUP = "cargo install dogwood-cli --version 1.1.2 --locked"
DOGWOOD_MISSING = (
    "Dogwood CLI is missing, so local validation of this Dogwood statement was skipped; the "
    "service validates it on submission. For local policy validation, install the Dogwood "
    f"command-line tools with `{DOGWOOD_SETUP}` (needs a Rust toolchain), or set "
    "AGENTCORE_POLICY_DOGWOOD to the `dogwood` executable."
)
DOGWOOD_TIMEOUT = 30.0
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

RESERVED_ACTIONS = (
    "Mcp",
    "Http",
    "CallTool",
    "UnknownTool",
    "InvokeAgent",
    "InvokeLLM",
)
PLACEHOLDER_NOTE = "Gateway resource (placeholder Gateway ARN; no Gateway selected)"


def uses_placeholder_gateway(context: dict | None, statement: str) -> bool:
    """True when the context was built with the placeholder Gateway ARN or the statement names it."""
    from acp_cedar_schema import PLACEHOLDER_GATEWAY_ARN

    if ((context or {}).get("cedar_schema") or {}).get("placeholder_gateway_arn"):
        return True
    return PLACEHOLDER_GATEWAY_ARN in statement


RESERVED_REF = re.compile(r'AgentCore::Action::"(' + "|".join(RESERVED_ACTIONS) + r')"')

#: Checks the service runs that a local result can never cover. Listed in every result.
SERVICE_ONLY_NOT_CHECKED = (
    "engine-wide schema merge and size limit (all Gateways on the engine)",
    "policy store selection and schema pruning by enforcement mode and effect",
    "live target validation with the caller's credentials at submission",
    "compile drift of other policies on the engine (deleted or inactive provider configurations)",
    "account entitlements (temporal dialect, streaming guardrail effects)",
)
GUARDRAIL_NOT_CHECKED = (
    "service-side semantic analysis: the service skips it under IGNORE_ALL_FINDINGS, which "
    "guardrail statements require, so no semantic analysis happens on either side"
)

#: Gap reasons that leave a whole tool listing unknown, so any action may merely be missing.
#: Matched by prefix: discovery appends details after a colon (``mcp_tools_list_failed: ...``).
LISTING_GAP_REASONS = (
    "mcp_discovery_failed",
    "mcp_tools_list_failed",
    "mcp_login_failed",
    "gateway_endpoint_missing",
    "gateway_endpoint_invalid",
    "target_unreadable",
)

SET_OPS = ("contains", "containsAny", "containsAll")
_LOCAL_FIRST = "local rule errors are reported first; fix them, then re-run"
SENSITIVE_AGGREGATIONS = (
    "count()",
    "categories()",
    "maxConfidenceScore()",
    "minConfidenceScore()",
)

_PER_PATH_ADVICE = (
    "Write one policy for each per-path action, each scoped with "
    '`action == AgentCore::Action::"<target>___<METHOD>:<path>"` (or `<target>___<tool>`), and '
    "keep the same condition in each (for guardrails, the JSONPaths that action's payload uses)."
)


# ---------------------------------------------------------------------------------------------
# API limits (control-plane constraints, read from the bedrock-agentcore-control model)
# ---------------------------------------------------------------------------------------------


def _suggest_name(name: str) -> str:
    fixed = re.sub(r"[^A-Za-z0-9_]", "_", name)
    fixed = re.sub(r"^[^A-Za-z]+", "", fixed) or "policy"
    return fixed[:NAME_MAX]


def check_name(name: str) -> None:
    """Raise ``SkillError("invalid_input")`` with a suggested fix unless ``name`` is a valid
    policy / policy engine name (``[A-Za-z][A-Za-z0-9_]*``, at most 48 characters)."""
    if not isinstance(name, str) or not name:
        raise SkillError("invalid_input", "name is required", input="name")
    if NAME_PATTERN.match(name) and len(name) <= NAME_MAX:
        return
    suggestion = _suggest_name(name)
    if not NAME_PATTERN.match(name):
        problem = (
            "must start with a letter and contain only letters, digits and underscores "
            "(no hyphens)"
        )
        if len(name) > NAME_MAX:
            problem += f", and be at most {NAME_MAX} characters (it has {len(name)})"
    else:
        problem = f"is {len(name)} characters; the limit is {NAME_MAX}"
    raise SkillError(
        "invalid_input",
        f"name {name!r} is invalid: it {problem}. Try {suggestion!r}.",
        input="name",
        suggestion=suggestion,
    )


def check_statement_limits(statement: str) -> None:
    """Raise ``SkillError("invalid_input")`` unless the statement is 35..10000 characters."""
    if not isinstance(statement, str) or not statement.strip():
        raise SkillError("invalid_input", "policy statement is empty", input="statement")
    length = len(statement)
    if length < STATEMENT_MIN:
        raise SkillError(
            "invalid_input",
            f"policy statement is {length} characters; the control plane requires at least "
            f"{STATEMENT_MIN}. Write it out in full, including the principal, action and "
            "resource clauses.",
            input="statement",
        )
    if length > STATEMENT_MAX:
        raise SkillError(
            "invalid_input",
            f"policy statement is {length} characters; the limit is {STATEMENT_MAX}. Split it "
            "into several policies on the same engine.",
            input="statement",
        )


def check_enforcement_mode(mode: str) -> str:
    """A per-policy enforcement mode. ``ENFORCE`` is a Gateway-link mode, not a policy mode."""
    if mode == "ENFORCE":
        raise SkillError(
            "invalid_input",
            "enforcement_mode on a policy must be ACTIVE or LOG_ONLY. ENFORCE is only valid for "
            "a Gateway's policy engine configuration, which is a separate setting this skill "
            "does not change -- use ACTIVE to make this policy enforce.",
            input="enforcement_mode",
        )
    if mode not in ("ACTIVE", "LOG_ONLY"):
        raise SkillError(
            "invalid_input",
            f"enforcement_mode must be ACTIVE or LOG_ONLY; got {mode!r}",
            input="enforcement_mode",
        )
    return mode


# ---------------------------------------------------------------------------------------------
# Source scanning (comments and string contents blanked, offsets preserved)
# ---------------------------------------------------------------------------------------------


def mask_noncode(src: str) -> str:
    """A same-length copy of ``src`` with comment bodies and string contents blanked, so code can
    be scanned by substring without matching inside a comment or a quoted literal. Quote
    characters are preserved. Only ``//`` line comments exist in Cedar and Dogwood; ``/* */``
    is code (a syntax error the parser reports), so it is never blanked."""
    n = len(src)
    out = [" "] * n
    i = 0
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src[i] == '"':
            out[i] = '"'
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                elif src[j] == '"':
                    break
                else:
                    j += 1
            if j < n:
                out[j] = '"'
            i = min(j + 1, n)
        else:
            out[i] = src[i]
            i += 1
    return "".join(out)


def canonical_statement(src: str) -> str:
    """``src`` with comments removed and each run of whitespace outside string literals reduced
    to one space, or to nothing next to a bracket, comma or semicolon. Two statements with the
    same canonical form parse the same (operators such as ``< =`` vs ``<=`` stay distinct), so a
    validation record keyed on it cannot be escaped by a layout-only edit."""
    out: list[str] = []
    pending_space = False
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            pending_space = True
        elif ch.isspace():
            pending_space = True
            i += 1
        else:
            if ch == '"':
                j = i + 1
                while j < n and src[j] != '"':
                    j += 2 if src[j] == "\\" else 1
                token, i = src[i : j + 1], j + 1
            else:
                token, i = ch, i + 1
            if (
                pending_space
                and out
                and out[-1][-1] not in _SEPARATORS
                and token[0] not in _SEPARATORS
            ):
                out.append(" ")
            out.append(token)
            pending_space = False
    return "".join(out)


_SEPARATORS = "()[]{},;"


def _close_paren(mask: str, open_at: int) -> int | None:
    """The index just past the balanced ``(``..``)`` that starts at ``open_at``."""
    depth = 0
    for offset in range(open_at, len(mask)):
        ch = mask[offset]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return offset + 1
    return None


CEDAR_OUTPUT_MESSAGE = (
    'the service rejects `context.output` in a plain Cedar policy ("Output context is not '
    "supported in Cedar policies\"), although the local schema accepts it. Read a tool's output "
    "only on a `::response` event in a temporal policy."
)
_SENSITIVE_CALL = re.compile(r"BedrockGuardrails::SensitiveInformation\s*\(")
SENSITIVE_JOIN_MESSAGE = (
    "removed whitespace between `SensitiveInformation(...)` and its aggregation method; the "
    'service rejects a space or line break there ("requires an aggregation method call")'
)


def join_sensitive_aggregation(statement: str) -> tuple[str, int]:
    """Remove the whitespace between the closing parenthesis of each
    ``BedrockGuardrails::SensitiveInformation(...)`` call and the ``.`` of the method that follows.

    Nothing else changes. String literals and comments are masked, so text inside them never
    matches; a comment between ``)`` and ``.`` is left alone. Returns (statement, joins)."""
    mask = mask_noncode(statement)
    cuts: list[tuple[int, int]] = []
    for match in _SENSITIVE_CALL.finditer(mask):
        close = _close_paren(mask, match.end() - 1)
        if close is None:
            continue
        end = close
        while end < len(statement) and statement[end] in " \t\r\n":
            end += 1
        if end > close and end < len(statement) and mask[end] == ".":
            cuts.append((close, end))
    for start, stop in reversed(cuts):
        statement = statement[:start] + statement[stop:]
    return statement, len(cuts)


def _scan_entity_refs(src: str, mask: str, entity: str) -> list[tuple[int, int, str]]:
    """``AgentCore::<entity>::"literal"`` outside comments and strings: (start, end, literal)."""
    pattern = re.compile(r"(?<![A-Za-z0-9_])AgentCore\s*::\s*" + re.escape(entity) + r'\s*::\s*"')
    refs = []
    for match in pattern.finditer(mask):
        quote = match.end() - 1
        end = mask.find('"', quote + 1)
        if end < 0:
            continue
        refs.append((match.start(), end + 1, src[quote : end + 1]))
    return refs


def _literal_value(literal: str) -> str | None:
    try:
        value = json.loads(literal)
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def qualify_policy(statement: str, gateway_arn: str) -> str:
    """Qualify literal ``AgentCore::Action::"raw"`` references with ``<gateway>___``, the way the
    service does before it validates."""
    mask = mask_noncode(statement)
    out: list[str] = []
    last = 0
    for start, end, literal in _scan_entity_refs(statement, mask, "Action"):
        raw = _literal_value(literal)
        if raw is None or raw in RESERVED_ACTIONS or raw.startswith(("arn:", f"{gateway_arn}___")):
            continue
        out.append(statement[last:start])
        out.append("AgentCore::Action::" + json.dumps(f"{gateway_arn}___{raw}"))
        last = end
    out.append(statement[last:])
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# Dialect, effects, submission requirements
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AdaptedEffect:
    authored: str
    parsed_as: str
    gated: bool  # enabled per account by the streaming-guardrails entitlement
    output_phase: bool  # evaluated on the response rather than the request


#: Effects the service accepts beyond permit/forbid. Public Dogwood parses only permit/forbid; the
#: service wrapper rewrites the leading keyword to its native one, padded to equal width.
ADAPTED_EFFECTS = (
    AdaptedEffect("interruptOutput", "forbid", True, True),
    AdaptedEffect("suppressOutput", "forbid", False, True),
    AdaptedEffect("redactOutput", "forbid", True, True),
    AdaptedEffect("redactInput", "permit", True, False),
)

# A `temporal { ... }` / `guardrails { ... }` block, tagged (`when temporal { ... }`) or nested
# inside a plain condition (`when { temporal { ... } || temporal { ... } }`).
_TEMPORAL_BLOCK = re.compile(r"(?<![A-Za-z0-9_.])temporal\s*\{")
_GUARDRAILS_BLOCK = re.compile(r"(?<![A-Za-z0-9_.])guardrails\s*\{")


def leading_effect(statement: str) -> AdaptedEffect | None:
    """The adapted effect the statement opens with: the keyword after leading whitespace, as a
    whole token (the service's rule)."""
    rest = statement.lstrip()
    for effect in ADAPTED_EFFECTS:
        if rest.startswith(effect.authored):
            tail = rest[len(effect.authored) :]
            if not tail or not (tail[0].isalnum() or tail[0] == "_"):
                return effect
    return None


def adapt_effect(statement: str) -> tuple[str, AdaptedEffect | None]:
    """The statement as public Dogwood should parse it, and the adapted effect if any."""
    effect = leading_effect(statement)
    if effect is None:
        return statement, None
    padded = effect.parsed_as.ljust(len(effect.authored))
    return statement.replace(effect.authored, padded, 1), effect


def is_guardrail_statement(statement: str) -> bool:
    """Whether the statement calls a Bedrock guardrail: a provider call, a ``when guardrails``
    block, or a leading output/redact effect."""
    mask = mask_noncode(statement)
    return (
        "BedrockGuardrails::" in mask
        or leading_effect(statement) is not None
        or _GUARDRAILS_BLOCK.search(mask) is not None
    )


def is_temporal_statement(statement: str) -> bool:
    return _TEMPORAL_BLOCK.search(mask_noncode(statement)) is not None


def detect_dialect(statement: str) -> str:
    """``"dogwood"`` for temporal blocks, providers/guardrails and the adapted effects; else
    ``"cedar"``."""
    if is_guardrail_statement(statement) or is_temporal_statement(statement):
        return "dogwood"
    return "cedar"


def required_validation_mode(statement: str) -> str:
    """The ``validationMode`` a statement must be submitted with. A guardrail statement yields
    findings that the default ``FAIL_ON_ANY_FINDINGS`` rejects even when the policy is correct;
    the setting suppresses findings only and authorizes nothing extra."""
    return "IGNORE_ALL_FINDINGS" if is_guardrail_statement(statement) else "FAIL_ON_ANY_FINDINGS"


def definition_for(statement: str) -> dict[str, Any]:
    """The ``definition`` union member for CreatePolicy/UpdatePolicy: ``cedar`` for plain Cedar,
    ``policy`` for the Dogwood dialect."""
    key = "policy" if detect_dialect(statement) == "dogwood" else "cedar"
    return {key: {"statement": statement}}


# ---------------------------------------------------------------------------------------------
# Claim access rules: messages shared by the AST (Cedar) and text (Dogwood) implementations
# ---------------------------------------------------------------------------------------------

GET_TAGS_MESSAGE = (
    "the tag accessor is `getTag`, singular; `getTags` is not a method on an AgentCore principal."
)


def _set_op_message(op: str) -> str:
    return (
        f"`.{op}` is applied to a tag value. The AgentCore schema declares the principal as "
        f"`tags String`, so a claim read with getTag is a String, not a Set, and `.{op}` is a Set "
        "operation -- a type error. An array-valued JWT claim is still delivered to policy as one "
        'String. Compare the confirmed value exactly with `== "<value>"`, or, only if the claim '
        "is confirmed to arrive as a JSON-array string, match a quoted element with "
        '`like "*\\"<value>\\"*"`.'
    )


def _unanchored_message(literal: str, inner: str, negated_exempt: bool) -> str:
    position = (
        " It is negated inside a `forbid`, so it selects who is exempt from the restriction "
        "rather than who is subject to it."
        if negated_exempt
        else ""
    )
    return (
        f'`like "{literal}"` matches any claim value containing `{inner}`, not only `{inner}` '
        f"itself.{position} Confirm that is intended for the claim values that can occur. If an "
        f'exact match is wanted, use `== "{inner}"`; if the claim arrives as a JSON-array string, '
        f'`like "*\\"{inner}\\"*"` matches a whole element.'
    )


_TAG_CALL = re.compile(r"\b(?:hasTag|getTag)\s*\(\s*\"")


def _tag_keys(source: str, mask: str) -> list[str]:
    """The string-literal keys of every hasTag/getTag call in code (not in strings or comments)."""
    keys: set[str] = set()
    for match in _TAG_CALL.finditer(mask):
        start = match.end()
        end = mask.find('"', start)
        if end >= start:
            keys.add(source[start:end])
    return sorted(keys)


def claim_key_findings(source: str, mask: str, context: dict | None) -> list[Issue]:
    """On a CUSTOM_JWT context, report tag reads whose key the developer has not confirmed."""
    principal = (context or {}).get("principal") or {}
    if not isinstance(principal, dict) or principal.get("entity_type") != "AgentCore::OAuthUser":
        return []
    keys = _tag_keys(source, mask)
    if not keys:
        return []
    confirmed = principal.get("confirmed_claims")
    if not isinstance(confirmed, list):
        return [
            (
                "claim_keys_not_confirmed",
                f"the statement reads token claims {', '.join(keys)}, but no claim names are "
                "confirmed for this Gateway. Ask the developer to give or confirm the exact claim "
                "names (names only, never a token), record them with `claims set --names ...`, "
                "and do not submit until they are confirmed. Never read them from the identity "
                "provider.",
            )
        ]
    return [
        (
            "claim_key_unconfirmed",
            f"claim `{key}` is not among the confirmed claim names ({', '.join(confirmed) or 'none'}); "
            "a key that the token does not carry never matches. Ask the developer before submitting.",
        )
        for key in keys
        if key not in confirmed
    ]


def _unguarded_message(key: str) -> str:
    return (
        f"getTag({key}) is used with no hasTag guard on the same key. Reading an absent tag is an "
        "evaluation error: a permit that errors grants nothing, but a forbid that errors fails to "
        f"forbid. Guard the read with `principal.hasTag({key}) && ...`."
    )


Issue = tuple[str, str]  # (rule, message)


def _pattern_text(pattern: list[Any]) -> str:
    chars = []
    for item in pattern:
        if item == "Wildcard":
            chars.append("*")
        elif isinstance(item, dict) and "Literal" in item:
            ch = item["Literal"]
            chars.append('\\"' if ch == '"' else "\\\\" if ch == "\\" else ch)
    return "".join(chars)


def _tag_key(node: Any) -> str | None:
    """The rendered key of a ``getTag``/``hasTag`` node's argument, or None if not such a node."""
    if not isinstance(node, dict):
        return None
    for op in ("getTag", "hasTag"):
        if op in node and isinstance(node[op], dict):
            right = node[op].get("right")
            if isinstance(right, dict) and isinstance(right.get("Value"), str):
                return json.dumps(right["Value"])
            return json.dumps(right, sort_keys=True)
    return None


def _is_get_tag(node: Any) -> bool:
    return isinstance(node, dict) and "getTag" in node


def _claim_issues_ast(policies: dict[str, Any]) -> tuple[list[Issue], list[Issue]]:
    """Errors and findings about how a Cedar statement reads identity claims."""
    errors: list[Issue] = []
    findings: list[Issue] = []
    seen: set[Issue] = set()

    def add(bucket: list[Issue], rule: str, message: str) -> None:
        if (rule, message) not in seen:
            seen.add((rule, message))
            bucket.append((rule, message))

    for policy in policies.values():
        forbid = policy.get("effect") == "forbid"
        guards: set[str] = set()
        reads: list[str] = []

        def visit(node: Any, negated: bool) -> None:
            if isinstance(node, list):
                for item in node:
                    visit(item, negated)
                return
            if not isinstance(node, dict):
                return
            for op, value in node.items():
                if op == "hasTag":
                    key = _tag_key(node)
                    if key is not None:
                        guards.add(key)
                elif op == "getTag":
                    key = _tag_key(node)
                    if key is not None:
                        reads.append(key)
                elif op in SET_OPS and isinstance(value, dict) and _is_get_tag(value.get("left")):
                    add(errors, "claim_set_operation", _set_op_message(op))
                elif op == "like" and isinstance(value, dict) and _is_get_tag(value.get("left")):
                    pattern = value.get("pattern") or []
                    if len(pattern) > 2 and pattern[0] == "Wildcard" and pattern[-1] == "Wildcard":
                        core = list(pattern)
                        while core and core[0] == "Wildcard":
                            core.pop(0)
                        while core and core[-1] == "Wildcard":
                            core.pop()
                        starts_with_quote = bool(core) and core[0] == {"Literal": '"'}
                        if core and not starts_with_quote:
                            add(
                                findings,
                                "claim_unanchored_like",
                                _unanchored_message(
                                    _pattern_text(pattern),
                                    _pattern_text(core),
                                    negated and forbid,
                                ),
                            )
                visit(
                    value["arg"] if op == "!" and isinstance(value, dict) else value,
                    (not negated) if op == "!" else negated,
                )

        for condition in policy.get("conditions", []):
            visit(condition.get("body"), condition.get("kind") == "unless")
        for key in dict.fromkeys(reads):
            if key not in guards:
                add(findings, "claim_unguarded_get_tag", _unguarded_message(key))
    return errors, findings


def _claim_issues_text(statement: str, mask: str) -> tuple[list[Issue], list[Issue]]:
    """The same checks on masked source, for statements the Cedar parser cannot read (Dogwood)."""
    errors: list[Issue] = []
    findings: list[Issue] = []
    guards = set()
    for match in re.finditer(r"hasTag\s*\(", mask):
        open_at = match.end() - 1
        close = _close_paren(mask, open_at)
        if close is not None:
            guards.add(re.sub(r"\s+", "", statement[open_at + 1 : close - 1]))
    reads = []
    from_at = 0
    while True:
        at = mask.find("getTag(", from_at)
        if at < 0:
            break
        open_at = at + len("getTag")
        close = _close_paren(mask, open_at)
        if close is None:
            break
        from_at = close
        reads.append(re.sub(r"\s+", "", statement[open_at + 1 : close - 1]))
        tail_at = close + (len(mask) - close - len(mask[close:].lstrip()))
        tail = mask[tail_at:]
        for op in SET_OPS:
            if tail.startswith("." + op) and not re.match(r"\w", tail[len(op) + 1 : len(op) + 2]):
                errors.append(("claim_set_operation", _set_op_message(op)))
                break
        if tail.startswith("like"):
            quote_at = tail_at + 4 + (len(tail) - 4 - len(tail[4:].lstrip()))
            end = mask.find('"', quote_at + 1) if mask[quote_at : quote_at + 1] == '"' else -1
            if end > 0:
                literal = statement[quote_at + 1 : end]
                inner = literal.strip("*")
                if (
                    literal.startswith("*")
                    and literal.endswith("*")
                    and inner
                    and not inner.startswith('\\"')
                ):
                    negated = "!" in mask[:quote_at] and mask.lstrip().startswith("forbid")
                    findings.append(
                        (
                            "claim_unanchored_like",
                            _unanchored_message(literal, inner, negated),
                        )
                    )
    for key in dict.fromkeys(reads):
        if key not in guards:
            findings.append(("claim_unguarded_get_tag", _unguarded_message(key)))
    return errors, findings


# ---------------------------------------------------------------------------------------------
# Guardrail rules (Dogwood dialect only: a guardrail never parses as plain Cedar)
# ---------------------------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def provider_categories() -> dict[str, list[str]]:
    """Accepted categories per guardrail provider: the output-record field names declared in the
    bundled ``providers.json``."""
    declared = json.loads((ASSETS_DIR / "providers.json").read_text(encoding="utf-8"))
    result = {}
    for name, provider in declared.get("availableProviders", {}).items():
        fields = ((provider.get("outputType") or {}).get("fields")) or {}
        if fields:
            result[name] = list(fields)
    return result


def _bracket_span(mask: str, start: int, stop: int) -> tuple[int, int] | None:
    open_at = mask.find("[", start, stop)
    if open_at < 0:
        return None
    depth = 0
    for i in range(open_at, stop):
        if mask[i] == "[":
            depth += 1
        elif mask[i] == "]":
            depth -= 1
            if depth == 0:
                return open_at, i
    return None


def _guardrail_issues(
    statement: str, mask: str, categories: dict[str, list[str]], output_phase: bool
) -> list[Issue]:
    issues: list[Issue] = []
    prefix = "BedrockGuardrails::"
    pos = 0
    while True:
        at = mask.find(prefix, pos)
        if at < 0:
            break
        after_ns = at + len(prefix)
        safeguard = re.match(r"[A-Za-z0-9]*", mask[after_ns:]).group(0)  # type: ignore[union-attr]
        open_at = mask.find("(", after_ns)
        if open_at < 0:
            break
        close = _close_paren(mask, open_at)
        if close is None:
            break
        pos = close
        allowed = categories.get(prefix + safeguard, [])
        cat_span = _bracket_span(mask, open_at + 1, close)

        i = open_at
        while i < close:
            if mask[i] != '"':
                i += 1
                continue
            end = mask.find('"', i + 1, close)
            if end < 0:
                break
            literal = statement[i + 1 : end]
            if cat_span is not None and cat_span[0] < i < cat_span[1]:
                if literal == "ACCOUNT_NUMBER":
                    issues.append(
                        (
                            "guardrail_category",
                            '"ACCOUNT_NUMBER" is not accepted; use "US_BANK_ACCOUNT_NUMBER" or '
                            '"INTERNATIONAL_BANK_ACCOUNT_NUMBER".',
                        )
                    )
                elif allowed and literal not in allowed:
                    issues.append(
                        (
                            "guardrail_category",
                            f'"{literal}" is not a {safeguard} category; the accepted values '
                            f"are {', '.join(allowed)}.",
                        )
                    )
            # Only `context` is unambiguous: `$.input` and `$.output` are real payload fields.
            elif literal.startswith(("$.context", "$['context'", '$["context"')):
                stripped = literal
                for lead in ("$.", "context.", "input.", "output."):
                    while stripped.startswith(lead):
                        stripped = stripped[len(lead) :]
                issues.append(
                    (
                        "guardrail_jsonpath_root",
                        f'the guardrail JSONPath "{literal}" is rooted at `context`. A '
                        "`$`-path addresses the raw payload, so it must start at the "
                        f'payload\'s own fields -- write "$.{stripped}". A path that matches '
                        "nothing contributes nothing: as written, the guardrail would pass "
                        "every local check and then screen empty text, so the rule would "
                        "never fire. Direction comes from the effect, not from the path.",
                    )
                )
            i = end + 1

        code = mask[open_at:close]
        if "[*]" in code or ".*" in code:
            issues.append(
                (
                    "guardrail_array_projection",
                    f"the {safeguard} content argument uses a Cedar array projection. Dogwood "
                    "has no projection operator and rejects this as a parse error -- but that "
                    "does not mean nested text is unreachable. Pass a `$`-prefixed JSONPath "
                    'string literal instead, for example ["$.messages[*].content"]. Several '
                    "candidate paths may be listed in one call; each match is concatenated and a "
                    "path matching nothing contributes nothing.",
                )
            )
        if safeguard == "SensitiveInformation" and mask[close:].lstrip().startswith("["):
            issues.append(
                (
                    "guardrail_sensitive_index",
                    "per-category indexing is not supported for SensitiveInformation, and the "
                    "service rejects it even though the local checker accepts it. Use an "
                    f"aggregation: {', '.join(SENSITIVE_AGGREGATIONS)}.",
                )
            )
        if not output_phase and "context.output" in code:
            issues.append(
                (
                    "guardrail_output_in_input_phase",
                    "a guardrail under `permit`, `forbid` or `redactInput` may read only the "
                    "inbound payload; `context.output` requires an output-phase effect "
                    "(`suppressOutput`, `interruptOutput`, `redactOutput`). To screen both "
                    "directions, write two policies.",
                )
            )
    return issues


_HAS_GUARD = re.compile(r"\bcontext\.((?:input|output)(?:\.\w+)*)\s+has\s+(\w+(?:\.\w+)*)")
_CONTEXT_PATH = re.compile(r"\bcontext\.((?:input|output)(?:\.\w+)+)")


def _optional_attrs(
    spec: Any, prefix: str, common: dict[str, Any], out: set[str], depth: int = 0
) -> None:
    for _ in range(8):  # a common type is named by `name` or, in generated schemas, by `type`
        if not isinstance(spec, dict) or spec.get("type") == "Record":
            break
        ref = spec.get("name") if spec.get("name") in common else spec.get("type")
        if ref not in common:
            break
        spec = common[ref]
    if depth > 8 or not isinstance(spec, dict) or spec.get("type") != "Record":
        return
    for attr, attr_spec in (spec.get("attributes") or {}).items():
        path = f"{prefix}{attr}"
        if isinstance(attr_spec, dict) and attr_spec.get("required") is False:
            out.add(path)
        _optional_attrs(attr_spec, path + ".", common, out, depth + 1)


def schema_optional_paths(schema_json: dict | None) -> set[str]:
    """Context paths (``input.a``, ``input.a.b``) that an action declares optional."""
    out: set[str] = set()
    if isinstance(schema_json, dict):
        for ns in schema_json.values():
            if not isinstance(ns, dict):
                continue
            common = ns.get("commonTypes") or {}
            for action in (ns.get("actions") or {}).values():
                ctx = ((action or {}).get("appliesTo") or {}).get("context")
                _optional_attrs(ctx, "", common, out)
    return {p for p in out if p.startswith(("input.", "output."))}


def _guarded_paths(mask: str) -> set[str]:
    guarded: set[str] = set()
    for m in _HAS_GUARD.finditer(mask):
        path = m.group(1)
        for attr in m.group(2).split("."):
            path = f"{path}.{attr}"
            guarded.add(path)
    return guarded


def _guardrail_guard_issues(mask: str, optional: set[str]) -> list[Issue]:
    """An optional field as a guardrail argument needs a `has` guard at every optional level:
    the service accepts it unguarded, and a call that omits it is then denied."""
    if not optional:
        return []
    guarded = _guarded_paths(mask)
    missing: list[str] = []
    prefix = "BedrockGuardrails::"
    pos = 0
    while True:
        at = mask.find(prefix, pos)
        if at < 0:
            break
        open_at = mask.find("(", at)
        close = _close_paren(mask, open_at) if open_at >= 0 else None
        if close is None:
            break
        pos = close
        for m in _CONTEXT_PATH.finditer(mask[open_at:close]):
            parts = m.group(1).split(".")
            for i in range(2, len(parts) + 1):
                level = ".".join(parts[:i])
                if level in optional and level not in guarded and level not in missing:
                    missing.append(level)
    issues: list[Issue] = []
    for level in missing:
        base, _, attr = level.rpartition(".")
        issues.append(
            (
                "guardrail_unguarded_optional",
                f"the guardrail reads `context.{level}`, which is optional in the schema, and "
                f"the statement has no `context.{base} has {attr}` guard. The service accepts "
                'this, but a call that omits the field is then denied ("request missing '
                'field(s) required for guardrail evaluation"). Guard every optional level '
                "before the check: in a `forbid`, `context.input has a && context.input.a has b "
                "&& <check>`; in a `permit`, `!(context.input has a && context.input.a has b) "
                "|| <check>`.",
            )
        )
    return issues


# ---------------------------------------------------------------------------------------------
# Scope rules
# ---------------------------------------------------------------------------------------------


def _scope_message(action_kind: str, guardrail: bool, uses: list[str]) -> Issue | None:
    """``action_kind``: ``"any"`` (unconstrained), ``"in"`` or ``"eq"``."""
    if action_kind == "any" and guardrail:
        return (
            "scope_guardrail_any_action",
            "a guardrail policy must name one action; an unconstrained `action` scope leaves the "
            "guardrail without configuration on real requests, which the service then denies. "
            + _PER_PATH_ADVICE,
        )
    if action_kind == "in" and uses:
        return (
            "scope_action_in",
            f"a policy scoped with `action in` cannot contain {', '.join(uses)}. "
            + _PER_PATH_ADVICE,
        )
    return None


def _scope_issues_text(statement: str, mask: str) -> list[Issue]:
    open_at = mask.find("(")
    if open_at < 0:
        return []
    close = _close_paren(mask, open_at)
    if close is None:
        return []
    head = mask[open_at + 1 : close]
    after_action = None
    for match in re.finditer(r"(?<![A-Za-z0-9_])action(?![A-Za-z0-9_])", head):
        after_action = head[match.end() :].lstrip()
        break
    if after_action is None:
        return []
    if re.match(r"in(?![A-Za-z0-9_])", after_action):
        kind = "in"
    elif after_action.startswith(",") or not after_action:
        kind = "any"
    else:
        kind = "eq"
    guardrail = is_guardrail_statement(statement)
    body = mask[close:]
    uses = []
    if guardrail:
        uses.append("guardrail calls")
    if "context.input" in body or "context.output" in body:
        uses.append("`context.input`/`context.output` reads")
    if re.search(r"(?<![A-Za-z0-9_])temporal(?![A-Za-z0-9_])", body):
        uses.append("temporal conditions")
    issue = _scope_message(kind, guardrail, uses)
    return [issue] if issue else []


_EVENT_PREDICATE = re.compile(
    r'(?<![A-Za-z0-9_])AgentCore\s*::\s*Action\s*::\s*"[^"]*"\s*::\s*'
    r"(?:request|response|error)(?![A-Za-z0-9_])"
)
_EVENT_RESOURCE_PIN = re.compile(r"(?<![A-Za-z0-9_.])eventResource\s*:\s*resource(?![A-Za-z0-9_])")


def _temporal_pin_issues(statement: str, mask: str) -> list[Issue]:
    """Event predicates without ``eventResource: resource``. Dogwood accepts them, but the
    service rejects a temporal policy whose events are not tied to the request's resource."""
    missing = []
    for match in _EVENT_PREDICATE.finditer(mask):
        open_at = match.end()
        while open_at < len(mask) and mask[open_at].isspace():
            open_at += 1
        args = ""
        if open_at < len(mask) and mask[open_at] == "{":
            depth, end = 0, len(mask)
            for offset in range(open_at, len(mask)):
                if mask[offset] == "{":
                    depth += 1
                elif mask[offset] == "}":
                    depth -= 1
                    if depth == 0:
                        end = offset
                        break
            args = mask[open_at + 1 : end]
        if not _EVENT_RESOURCE_PIN.search(args):
            missing.append(re.sub(r"\s+", "", statement[match.start() : match.end()]))
    if not missing:
        return []
    return [
        (
            "temporal_event_resource",
            "every temporal event predicate needs `eventResource: resource` (for example "
            '`AgentCore::Action::"<Target>___<tool>"::request{ eventResource: resource }`); the '
            "service rejects the policy without it. Missing on: " + ", ".join(missing) + ".",
        )
    ]


def _context_path(node: Any) -> str | None:
    """``input.amount`` for the AST of ``context.input.amount``; None if not a context chain."""
    attrs = []
    while isinstance(node, dict) and "." in node and isinstance(node["."], dict):
        attrs.append(node["."].get("attr"))
        node = node["."].get("left")
    if isinstance(node, dict) and node.get("Var") == "context" and attrs:
        return ".".join(a for a in reversed(attrs) if isinstance(a, str))
    return None


def _walk_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_nodes(value)


def _scope_issues_ast(policies: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    for policy in policies.values():
        op = (policy.get("action") or {}).get("op")
        kind = {"All": "any", "in": "in"}.get(op or "", "eq")
        uses = []
        for node in _walk_nodes(policy.get("conditions", [])):
            if (
                isinstance(node.get("."), dict)
                and (node["."].get("left") or {}).get("Var") == "context"
                and node["."].get("attr") in ("input", "output")
            ):
                uses.append("`context.input`/`context.output` reads")
                break
        issue = _scope_message(kind, False, uses)
        if issue and issue not in issues:
            issues.append(issue)
    return issues


# ---------------------------------------------------------------------------------------------
# Target (action group) equality, Gateway resource, numeric types
# ---------------------------------------------------------------------------------------------


def _unqualified(action_id: str, gateway: str | None) -> str:
    if gateway and action_id.startswith(f"{gateway}___"):
        return action_id[len(gateway) + 3 :]
    return action_id


def _group_message(shown: str) -> str:
    return (
        f"`{shown}` is a Gateway target (an action group) and cannot be compared with `==` or "
        f'`!=`. Use `action in AgentCore::Action::"{shown}"` for a plain condition, or, for '
        "guardrail, input/output or temporal policies, one policy per path with "
        f'`action == AgentCore::Action::"{shown}___<METHOD>:<path>"` (or `{shown}___<tool>`).'
    )


def action_groups(context: dict | None, schema_json: dict | None, gateway: str | None) -> set[str]:
    """Unqualified ids of target-level action groups: the context's target names plus every
    non-reserved action some schema action names in ``memberOf``."""
    groups = set((context or {}).get("targets") or {})
    if isinstance(schema_json, dict):
        for ns in schema_json.values():
            actions = ns.get("actions") if isinstance(ns, dict) else None
            for action in (actions or {}).values():
                for parent in action.get("memberOf") or []:
                    pid = parent.get("id") if isinstance(parent, dict) else None
                    if isinstance(pid, str) and pid not in RESERVED_ACTIONS:
                        groups.add(_unqualified(pid, gateway))
    return groups


def _group_equality_text(
    statement: str, mask: str, groups: set[str], gateway: str | None
) -> list[Issue]:
    issues = []
    for start, _end, literal in _scan_entity_refs(statement, mask, "Action"):
        action_id = _literal_value(literal)
        if action_id is None:
            continue
        shown = _unqualified(action_id, gateway)
        if shown in groups:
            before = mask[:start].rstrip()
            if before.endswith(("==", "!=")):
                issues.append(("target_group_equality", _group_message(shown)))
    return issues


def _entity_ids(node: Any) -> list[str]:
    ids = []
    for sub in _walk_nodes(node):
        entity = sub.get("__entity")
        if isinstance(entity, dict) and entity.get("type") == "AgentCore::Action":
            ids.append(entity.get("id"))
    return [i for i in ids if isinstance(i, str)]


def _group_equality_ast(
    policies: dict[str, Any], groups: set[str], gateway: str | None
) -> list[Issue]:
    issues: list[Issue] = []

    def report(action_id: str) -> None:
        shown = _unqualified(action_id, gateway)
        issue = ("target_group_equality", _group_message(shown))
        if shown in groups and issue not in issues:
            issues.append(issue)

    for policy in policies.values():
        action = policy.get("action") or {}
        entity = action.get("entity")
        if action.get("op") == "==" and isinstance(entity, dict) and "id" in entity:
            report(entity["id"])
        for node in _walk_nodes(policy.get("conditions", [])):
            for op in ("==", "!="):
                sides = node.get(op)
                if isinstance(sides, dict) and (
                    (sides.get("left") or {}).get("Var") == "action"
                    or (sides.get("right") or {}).get("Var") == "action"
                ):
                    for action_id in _entity_ids(sides):
                        report(action_id)
    return issues


def _gateway_mismatch(statement: str, mask: str, gateway: str) -> bool:
    return any(
        (value := _literal_value(lit)) is not None and value != gateway
        for _s, _e, lit in _scan_entity_refs(statement, mask, "Gateway")
    )


def _resolve_type(spec: Any, common: dict[str, Any], depth: int = 0) -> Any:
    while (
        depth < 8
        and isinstance(spec, dict)
        and spec.get("type") != "Record"
        and isinstance(spec.get("name"), str)
        and spec["name"] in common
    ):
        spec = common[spec["name"]]
        depth += 1
    return spec


def _flatten_record(
    spec: Any,
    prefix: str,
    common: dict[str, Any],
    out: dict[str, str],
    conflicts: set[str],
) -> None:
    spec = _resolve_type(spec, common)
    if not isinstance(spec, dict) or spec.get("type") != "Record":
        return
    for attr, attr_spec in (spec.get("attributes") or {}).items():
        path = f"{prefix}{attr}"
        resolved = _resolve_type(attr_spec, common)
        if not isinstance(resolved, dict):
            continue
        if resolved.get("type") == "Record":
            _flatten_record(resolved, path + ".", common, out, conflicts)
            continue
        name = str(resolved.get("name", "")).split("::")[-1].lower()
        kind = str(resolved.get("type", ""))
        is_decimal = "decimal" in (name, kind.lower())
        leaf = "decimal" if is_decimal else "Long" if kind == "Long" else None
        if leaf is None:
            continue
        if out.get(path, leaf) != leaf:
            conflicts.add(path)
        out[path] = leaf


def schema_context_types(schema_json: dict | None) -> dict[str, str]:
    """``input.amount`` -> ``decimal``/``Long`` for context fields under ``input``/``output``,
    merged across actions. A path typed differently by two actions is dropped."""
    out: dict[str, str] = {}
    conflicts: set[str] = set()
    if isinstance(schema_json, dict):
        for ns in schema_json.values():
            if not isinstance(ns, dict):
                continue
            common = ns.get("commonTypes") or {}
            for action in (ns.get("actions") or {}).values():
                ctx = (action.get("appliesTo") or {}).get("context")
                _flatten_record(ctx, "", common, out, conflicts)
    keep = ("input.", "output.")
    return {p: t for p, t in out.items() if p not in conflicts and p.startswith(keep)}


def _numeric_issues_ast(policies: dict[str, Any], types: dict[str, str]) -> list[Issue]:
    issues: list[Issue] = []
    if not types:
        return issues
    for policy in policies.values():
        for node in _walk_nodes(policy.get("conditions", [])):
            for op in ("<", "<=", ">", ">="):
                sides = node.get(op)
                if not isinstance(sides, dict):
                    continue
                for side in (sides.get("left"), sides.get("right")):
                    path = _context_path(side)
                    if path and types.get(path) == "decimal":
                        issues.append(
                            (
                                "numeric_type",
                                f"`context.{path}` lowers to Cedar `decimal`, not `Long`, so a "
                                "bare comparison operator is a type error. Write "
                                f'`context.{path}.greaterThan(decimal("1000.0"))` -- a decimal '
                                "method with a quoted decimal string. An MCP tool `number` "
                                "lowers to decimal while an MCP `integer` lowers to Long, and "
                                "the Http/inference overlay maps both to Long, so read the "
                                "context types from `describe` rather than inferring them from "
                                "the JSON Schema type.",
                            )
                        )
            for op in (
                "greaterThan",
                "greaterThanOrEqual",
                "lessThan",
                "lessThanOrEqual",
            ):
                args = node.get(op)
                if isinstance(args, list) and args:
                    path = _context_path(args[0])
                    if path and types.get(path) == "Long":
                        issues.append(
                            (
                                "numeric_type",
                                f"`context.{path}` lowers to Cedar `Long`, so the decimal "
                                "methods are a type error. Compare it with the ordinary "
                                f"operators and an unquoted number, for example "
                                f"`context.{path} > 1000`.",
                            )
                        )
    unique = []
    for issue in issues:
        if issue not in unique:
            unique.append(issue)
    return unique


# ---------------------------------------------------------------------------------------------
# Schema-stage status: rejected vs incomplete (coverage gaps)
# ---------------------------------------------------------------------------------------------

_UNRECOGNIZED = re.compile(r'unrecognized action `AgentCore::Action::"((?:[^"\\]|\\.)*)"`')
_NOT_IN_SCHEMA = re.compile(r"action `([^`]+)` not found in schema")


def _unknown_action(message: str, gateway: str | None) -> str | None:
    """The unqualified id of the action a Cedar/Dogwood message calls unknown, or None."""
    found = _UNRECOGNIZED.search(message)
    if found:
        return _unqualified(json.loads(f'"{found.group(1)}"'), gateway)
    found = _NOT_IN_SCHEMA.search(message)
    return _unqualified(found.group(1), gateway) if found else None


def _gap_covers_action(gap: dict, action: str) -> bool:
    if str(gap.get("reason") or "").startswith(LISTING_GAP_REASONS):
        return True
    if gap.get("field"):
        return False
    target, _, rest = action.partition("___")
    gap_target = gap.get("target")
    gap_action = gap.get("action")
    if not gap_target and not gap_action:
        return True
    if gap_target != target and gap_action != action:
        return False
    return gap_action is None or gap_action in (rest, action)


def _gap_covers_field(gap: dict, message: str, statement: str) -> bool:
    field = gap.get("field")
    action = gap.get("action")
    if not field or not action:
        return False
    leaf = str(field).replace("[]", "").split(".")[-1].lower()
    lowered = message.lower()
    target = gap.get("target")
    full = f"{target}___{action}" if target else action
    return "not found" in lowered and f"`{leaf}`" in lowered and full in statement


def classify_schema_errors(
    messages: list[str], gaps: list[dict], gateway: str | None, statement: str
) -> str:
    """``"rejected"`` unless every error is an unknown action or a missing field that a coverage
    gap could explain, in which case ``"incomplete"``. A typo on a fully discovered target stays
    rejected."""
    if not messages or not gaps:
        return "rejected"
    unknown = explained = 0
    for message in messages:
        action = _unknown_action(message, gateway)
        if action is not None:
            unknown += 1
            if any(_gap_covers_action(g, action) for g in gaps):
                explained += 1
    actions_uncertain = unknown > 0 and explained == unknown
    for message in messages:
        if (
            _unknown_action(message, gateway) is not None
            or "unable to find an applicable action" in message
        ):
            if not actions_uncertain:
                return "rejected"
        elif not any(_gap_covers_field(g, message, statement) for g in gaps):
            return "rejected"
    return "incomplete"


def _known_actions(context: dict | None) -> list[str]:
    known = []
    for target, info in ((context or {}).get("targets") or {}).items():
        known.append(target)
        known.extend(f"{target}___{a}" for a in (info.get("actions") or {}))
    return known


def _readable(message: str, gateway: str | None, known: list[str]) -> dict[str, Any]:
    """A diagnostic dict from a Cedar/Dogwood message: policy prefix and Gateway qualification
    removed, with a nearest-action hint for an unknown action."""
    text = message
    text = re.sub(r"^for policy `[^`]*`, ", "", text)
    if gateway:
        text = text.replace(f"{gateway}___", "")
    diagnostic: dict[str, Any] = {"severity": "error", "message": text}
    wanted = _unknown_action(message, gateway)
    if wanted is not None and known:
        close = difflib.get_close_matches(wanted, known, n=3, cutoff=0.5)
        if close:
            diagnostic["hint"] = "closest known actions: " + ", ".join(close)
        else:
            diagnostic["hint"] = "this context declares no similarly named action"
    return diagnostic


# ---------------------------------------------------------------------------------------------
# Cedar checker
# ---------------------------------------------------------------------------------------------


def _import_cedarpy():
    try:
        import cedarpy
    except ImportError as exc:
        raise missing_dependency(
            "cedarpy",
            "pip install cedarpy==4.12.2",
            "to validate Cedar statements locally",
        ) from exc
    return cedarpy


def _cedarpy_version() -> str | None:
    from importlib import metadata

    try:
        return metadata.version("cedarpy")
    except metadata.PackageNotFoundError:
        return None


# ---------------------------------------------------------------------------------------------
# Dogwood checker
# ---------------------------------------------------------------------------------------------


def resolve_dogwood() -> str | None:
    """``AGENTCORE_POLICY_DOGWOOD`` (a path, or a name looked up on PATH), else ``dogwood`` on
    PATH. None when not found or not executable."""
    configured = os.environ.get("AGENTCORE_POLICY_DOGWOOD")
    if configured:
        # A path, not a name, when it has a separator; Windows also accepts "/" (os.altsep).
        if os.sep in configured or (os.altsep and os.altsep in configured):
            path = Path(configured).expanduser()
            return str(path) if path.is_file() and os.access(path, os.X_OK) else None
        return shutil.which(configured)
    return shutil.which("dogwood")


class _CliFailure(Exception):
    """The CLI could not be run or returned something unusable. ``reason`` is safe to show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Windows cannot start most programs without SystemRoot, and uses TEMP/TMP and USERPROFILE where
# POSIX uses HOME. These are passed on Windows only; elsewhere the child sees just PATH and HOME.
_WINDOWS_ENV = ("SystemRoot", "SYSTEMROOT", "windir", "TEMP", "TMP")


def _child_env(home: str, *, windows: bool | None = None) -> dict[str, str]:
    """The Dogwood CLI's environment: PATH and a private HOME, plus what Windows needs to run."""
    env = {"HOME": home}
    if "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    if os.name == "nt" if windows is None else windows:
        env.update({k: os.environ[k] for k in _WINDOWS_ENV if k in os.environ})
        env["USERPROFILE"] = home
    return env


def _run_cli(binary: str, args: list[str], stdin: str, home: str) -> tuple[int, str]:
    env = _child_env(home)
    try:
        proc = subprocess.run(
            [binary, *args],
            input=stdin.encode("utf-8"),
            capture_output=True,
            timeout=DOGWOOD_TIMEOUT,
            env=env,
            cwd=home,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _CliFailure(f"Dogwood did not finish within {int(DOGWOOD_TIMEOUT)} s") from exc
    except OSError as exc:
        raise _CliFailure("Dogwood could not be started") from exc
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def dogwood_version(binary: str) -> str | None:
    """``dogwood --version`` through the same hardened call as validation (cleared environment,
    private HOME and working directory), or None when it fails to run or exits non-zero."""
    with tempfile.TemporaryDirectory(prefix="agentcore-policy-dw-") as home:
        try:
            code, out = _run_cli(binary, ["--version"], "", home)
        except _CliFailure:
            return None
    return out.strip() if code == 0 else None


def _run_json(binary: str, args: list[str], stdin: str, home: str) -> tuple[str, dict]:
    """Run a Dogwood command expecting a JSON report: exit 0 -> passed, 2 -> rejected."""
    code, out = _run_cli(binary, args, stdin, home)
    try:
        report = json.loads(out.strip())
    except ValueError as exc:
        raise _CliFailure("Dogwood returned non-JSON output") from exc
    if not isinstance(report, dict):
        raise _CliFailure("Dogwood returned an unexpected report shape")
    if code not in (0, 2):
        raise _CliFailure("Dogwood reported a usage or I/O failure")
    if code == 2 and not isinstance(report.get("errors"), list):
        message = report.get("message")
        asset = re.search(r"providers?\.json|dwschema|event[- ]schema", str(message), re.IGNORECASE)
        if not isinstance(message, str) or asset:
            raise _CliFailure("Dogwood reported an asset or schema error")
    return ("passed" if code == 0 else "rejected"), report


def _line_of(source: str, offset: int) -> int:
    return source.encode("utf-8")[:offset].count(b"\n") + 1


def _dogwood_diagnostics(report: dict, source: str, gateway: str | None) -> list[dict[str, Any]]:
    def strip(text: str) -> str:
        return text.replace(f"{gateway}___", "") if gateway else text

    items = []
    if isinstance(report.get("errors"), list):
        items = list(report["errors"]) + list(report.get("warnings") or [])
    elif "message" in report:
        items = [report]
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("message"), str):
            continue
        diagnostic: dict[str, Any] = {
            "severity": item.get("severity", "error"),
            "message": strip(item["message"]),
        }
        labels = item.get("labels")
        if isinstance(labels, list) and labels and isinstance(labels[0].get("start"), int):
            diagnostic["line"] = _line_of(source, labels[0]["start"])
        if isinstance(item.get("help"), str):
            diagnostic["help"] = strip(item["help"])
        out.append(diagnostic)
    return out


def _unavailable(reason: str, *, setup: bool = False) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {"severity": "error", "message": reason}
    if setup:
        diagnostic["setup"] = DOGWOOD_SETUP
    return {"status": "unavailable", "diagnostics": [diagnostic]}


def _skipped(reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "diagnostics": [{"severity": "info", "message": reason}],
    }


def _dogwood_stages(
    parse_source: str,
    schema_text: str | None,
    gateway: str | None,
    gaps: list[dict],
    known: list[str],
) -> tuple[dict, dict, str | None, list[str]]:
    """(syntax stage, schema stage, dogwood version or None, extra not_checked entries)."""
    binary = resolve_dogwood()
    if binary is None:
        missing = {
            "status": "skipped",
            "diagnostics": [
                {"severity": "info", "message": DOGWOOD_MISSING, "setup": DOGWOOD_SETUP}
            ],
        }
        return (
            missing,
            dict(missing),
            None,
            ["syntax and schema validation (Dogwood CLI not installed; skipped)"],
        )
    with tempfile.TemporaryDirectory(prefix="agentcore-policy-dw-") as home:
        try:
            code, out = _run_cli(binary, ["--version"], "", home)
        except _CliFailure as exc:
            stage = _unavailable(f"Dogwood version check failed: {exc.reason}", setup=True)
            return (
                stage,
                dict(stage),
                None,
                ["syntax and schema validation (Dogwood unavailable)"],
            )
        version = out.strip()
        if code != 0 or version not in DOGWOOD_VERSIONS:
            shown = version[:40] if code == 0 else "unknown"
            stage = _unavailable(
                f"unsupported Dogwood version {shown!r}; this skill supports "
                f"{', '.join(repr(v) for v in DOGWOOD_VERSIONS)}. Install with: {DOGWOOD_SETUP}",
                setup=True,
            )
            return (
                stage,
                dict(stage),
                None,
                ["syntax and schema validation (Dogwood unavailable)"],
            )

        common = [
            "--format",
            "json",
            "--providers",
            str(ASSETS_DIR / "providers.json"),
            "--event-schema",
            str(ASSETS_DIR / "agentcore.dwschema"),
        ]
        try:
            status, report = _run_json(binary, ["check-parse", "-", *common], parse_source, home)
        except _CliFailure as exc:
            stage = _unavailable(exc.reason)
            return (
                stage,
                _skipped("syntax check did not complete"),
                version,
                ["syntax and schema validation (Dogwood check failed)"],
            )
        syntax = {
            "status": status,
            "diagnostics": _dogwood_diagnostics(report, parse_source, gateway),
        }
        undeclared = sorted(
            {
                name
                for policy in report.get("policies") or []
                for name in (policy.get("undeclared_providers") or [])
            }
        )
        if status == "passed" and undeclared:
            syntax = _unavailable(
                "provider has no local interface declaration: " + ", ".join(undeclared)
            )
        if syntax["status"] != "passed":
            return (
                syntax,
                _skipped("syntax check did not pass"),
                version,
                ["schema validation (syntax check did not pass)"],
            )
        if schema_text is None:
            return (
                syntax,
                _skipped("no Cedar schema text supplied"),
                version,
                ["schema validation (no Cedar schema text supplied)"],
            )

        schema_path = Path(home) / "schema.cedarschema"
        schema_path.write_text(schema_text, encoding="utf-8")
        try:
            pre, _ = _run_json(
                binary,
                ["schema", "action", str(schema_path), "--format", "json"],
                "",
                home,
            )
            if pre != "passed":
                raise _CliFailure("the generated Cedar schema was rejected by Dogwood")
            status, report = _run_json(
                binary,
                ["validate", "-", *common, "--policy-schema", str(schema_path)],
                parse_source,
                home,
            )
        except _CliFailure as exc:
            return (
                syntax,
                _unavailable(exc.reason),
                version,
                ["schema validation (Dogwood schema check failed)"],
            )
        diagnostics = _dogwood_diagnostics(report, parse_source, gateway)
        stage_status = status
        if status == "rejected":
            entries = report["errors"] if isinstance(report.get("errors"), list) else [report]
            raw = [
                e["message"]
                for e in entries
                if isinstance(e, dict) and isinstance(e.get("message"), str)
            ]
            stage_status = classify_schema_errors(raw, gaps, gateway, parse_source)
            for diagnostic in diagnostics:
                if diagnostic["severity"] == "error":
                    hint = _readable(diagnostic["message"], None, known).get("hint")
                    if hint:
                        diagnostic["hint"] = hint
        return syntax, {"status": stage_status, "diagnostics": diagnostics}, version, []


# ---------------------------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------------------------


def _schema_inputs(
    schema_text: str | None, schema_json: dict | None, context: dict | None
) -> tuple[str | None, str | None]:
    """(gateway ARN used to qualify actions, gateway ARN to match the resource against).

    The first comes from the schema itself (the actions are ``<gateway>___...``), else the
    context; the second is only set for a real, selected Gateway (never a placeholder)."""
    ctx = context or {}
    placeholder = bool((ctx.get("cedar_schema") or {}).get("placeholder_gateway_arn"))
    candidates: set[str] = set()
    if isinstance(schema_json, dict):
        for ns in schema_json.values():
            for name in (((ns or {}).get("actions") or {}) if isinstance(ns, dict) else ()):
                if "___" in name and name.startswith("arn:"):
                    candidates.add(name.split("___", 1)[0])
    if not candidates and schema_text:
        candidates = set(re.findall(r'"(arn:[^"\s]+?)___', schema_text))
    context_arn = ctx.get("gateway_arn") if isinstance(ctx.get("gateway_arn"), str) else None
    qualify = next(iter(candidates)) if len(candidates) == 1 else context_arn
    match_against = None if placeholder else context_arn or qualify
    return qualify, match_against


def _api_limits_stage(statement: str, name: str | None, qualified: str) -> dict[str, Any]:
    diagnostics = []
    if name is not None:
        try:
            check_name(name)
        except SkillError as exc:
            diagnostics.append({"severity": "error", "message": exc.message})
    try:
        check_statement_limits(statement)
    except SkillError as exc:
        diagnostics.append({"severity": "error", "message": exc.message})
    else:
        if len(qualified) > STATEMENT_MAX or len(qualified.encode("utf-8")) > STATEMENT_MAX:
            diagnostics.append(
                {
                    "severity": "error",
                    "message": f"statement exceeds {STATEMENT_MAX} characters or UTF-8 bytes once "
                    "actions are Gateway-qualified",
                }
            )
    return {
        "status": "rejected" if diagnostics else "passed",
        "diagnostics": diagnostics,
    }


def _cedar_syntax(cedarpy: Any, qualified: str) -> tuple[dict, dict | None]:
    """(syntax stage, ``staticPolicies`` JSON AST or None when the syntax did not pass)."""
    try:
        policies = json.loads(cedarpy.policies_to_json_str(qualified))
    except ValueError as exc:
        message = str(exc).strip() or "the statement does not parse as Cedar"
        diagnostic = {"severity": "error", "message": message}
        return {"status": "rejected", "diagnostics": [diagnostic]}, None
    static = policies.get("staticPolicies") or {}
    if policies.get("templates") or not static:
        message = "the statement must hold at least one static policy and no templates"
        diagnostic = {"severity": "error", "message": message}
        return {"status": "rejected", "diagnostics": [diagnostic]}, None
    return {"status": "passed", "diagnostics": []}, static


def _cedar_schema_stage(
    cedarpy: Any,
    qualified: str,
    schema_arg: Any,
    gateway: str | None,
    gaps: list[dict],
    known: list[str],
) -> dict[str, Any]:
    """Validate against the schema. A schema Cedar cannot load is ``unavailable`` (not the
    statement's fault); statement errors are ``rejected``, or ``incomplete`` when a coverage gap
    could explain them."""
    try:
        result = cedarpy.validate_policies(qualified, schema_arg)
    except Exception as exc:  # noqa: BLE001 - pyo3 raises several types for a bad schema
        text = str(exc).strip()
        reason = text.splitlines()[0][:300] if text else "unknown error"
        return _unavailable(f"the Cedar schema could not be loaded: {reason}")
    if result.validation_passed:
        return {"status": "passed", "diagnostics": []}
    schema_errors = [
        e.error for e in result.errors if not e.policy_id and e.error.startswith("Schema")
    ]
    if schema_errors:
        return _unavailable(f"the Cedar schema could not be loaded: {schema_errors[0][:300]}")
    raw = [e.error for e in result.errors]
    return {
        "status": classify_schema_errors(raw, gaps, gateway, qualified),
        "diagnostics": [_readable(m, gateway, known) for m in raw],
    }


def validate(
    statement: str,
    *,
    schema_text: str | None,
    schema_json: dict | None,
    context: dict | None,
    name: str | None = None,
) -> dict[str, Any]:
    """Validate one statement locally. See the module docstring and the skill contract for the
    result shape; ``status`` is ``passed`` only when every stage passed and no effect adapter was
    needed."""
    statement = statement if isinstance(statement, str) else ""
    context = context if isinstance(context, dict) else None
    dialect = detect_dialect(statement)
    parse_source, adapted = adapt_effect(statement)
    gaps = [g for g in (context or {}).get("gaps") or [] if isinstance(g, dict)]
    known = _known_actions(context)
    qualify_gw, match_gw = _schema_inputs(schema_text, schema_json, context)
    qualified = qualify_policy(parse_source, qualify_gw) if qualify_gw else parse_source

    checked = ["statement length bounds", "policy name"] if name else ["statement length bounds"]
    not_checked = ["service-side validation parity (not verified)"]
    if qualify_gw:
        checked.append("raw action qualification with the Gateway ARN")
    else:
        not_checked.append("raw action qualification (Gateway ARN unknown; no schema supplied)")
    placeholder_used = uses_placeholder_gateway(context, statement)
    if placeholder_used:
        not_checked.append(PLACEHOLDER_NOTE)

    stages: dict[str, dict] = {
        "api_limits": _api_limits_stage(statement, name, qualified),
    }
    local_errors: list[Issue] = []
    claim_findings: list[Issue] = []
    mask = mask_noncode(parse_source)
    checker: dict[str, str | None] = {"cedarpy": None, "dogwood": None}

    def finish_rules(claims: tuple[list[Issue], list[Issue]], extra: list[Issue]) -> None:
        local_errors.extend(claims[0])
        claim_findings.extend(claims[1])
        local_errors.extend(extra)

    statement_ok = bool(statement.strip())
    claim_findings.extend(claim_key_findings(parse_source, mask, context))
    if "getTags(" in mask:
        local_errors.append(("claim_get_tags", GET_TAGS_MESSAGE))
    reserved = sorted(
        {
            m.group(1)
            for m in RESERVED_REF.finditer(statement)
            if mask[m.start()] == statement[m.start()]
        }
    )
    if reserved:
        local_errors.append(
            (
                "reserved_action_group",
                f"`{'`, `'.join(reserved)}`: reserved service action "
                f"group{'s' if len(reserved) > 1 else ''}, not valid in a policy. Scope the policy with "
                'the per-target group (`action in AgentCore::Action::"<target>"`) or list '
                'the leaf actions (`action in [AgentCore::Action::"<target>___<action>", ...]`) '
                "taken from `prepare`/`describe`.",
            )
        )

    groups = action_groups(context, schema_json, qualify_gw)
    types = schema_context_types(schema_json)
    if match_gw:
        checked.append("Gateway resource matches the selected Gateway")
        if _gateway_mismatch(parse_source, mask, match_gw):
            local_errors.append(
                (
                    "gateway_resource_mismatch",
                    "statement Gateway resource differs from the selected Gateway",
                )
            )

    schema_arg: Any = schema_text if schema_text else (schema_json if schema_json else None)

    if not statement_ok:
        stages["syntax"] = {
            "status": "rejected",
            "diagnostics": [{"severity": "error", "message": "statement is required"}],
        }
        stages["schema"] = _skipped("syntax check did not pass")
    elif dialect == "cedar":
        cedarpy = _import_cedarpy()
        checker["cedarpy"] = _cedarpy_version()
        syntax, static = _cedar_syntax(cedarpy, qualified)
        stages["syntax"] = syntax
        checked.append("Cedar syntax (cedarpy)")
        if static is not None and syntax["status"] == "passed":
            checked.append("identity claim access (tag accessor, Set-vs-String, guard)")
            checked.append("scope: input/output conditions need a single-action scope")
            extra = _scope_issues_ast(static)
            checked.append("no `context.output` in a plain Cedar policy")
            if "context.output" in mask:
                extra.append(("cedar_output_context", CEDAR_OUTPUT_MESSAGE))
            if groups:
                checked.append("no `==`/`!=` against a Gateway target (action group)")
                extra += _group_equality_ast(static, groups, qualify_gw)
            if types:
                checked.append("numeric comparison syntax against the generated Cedar type")
                extra += _numeric_issues_ast(static, types)
            finish_rules(_claim_issues_ast(static), extra)
        if syntax["status"] != "passed":
            stages["schema"] = _skipped("syntax check did not pass")
            not_checked.append("schema validation (syntax check did not pass)")
        elif local_errors:
            stages["schema"] = _skipped(_LOCAL_FIRST)
            not_checked.append("schema validation (skipped while local errors are open)")
        elif schema_arg is None:
            stages["schema"] = _skipped("no schema supplied")
            not_checked.append("schema validation (no schema supplied)")
        else:
            stages["schema"] = _cedar_schema_stage(
                cedarpy, qualified, schema_arg, qualify_gw, gaps, known
            )
            if stages["schema"]["status"] == "unavailable":
                not_checked.append("schema validation (schema could not be loaded)")
            else:
                checked.append("Cedar validation against the schema (cedarpy)")
    else:
        text_claims = _claim_issues_text(parse_source, mask)
        checked.append("identity claim access (tag accessor, Set-vs-String, guard)")
        extra = []
        categories = ((context or {}).get("guardrail_providers") or {}).get(
            "categories"
        ) or provider_categories()
        if is_guardrail_statement(statement):
            checked.append("guardrail content paths, categories and effect/direction")
            extra += _guardrail_issues(
                statement, mask, categories, bool(adapted and adapted.output_phase)
            )
            optional = schema_optional_paths(schema_json)
            if optional:
                checked.append("guardrail arguments on optional fields have `has` guards")
                extra += _guardrail_guard_issues(mask, optional)
        checked.append("scope: guardrail, input/output and temporal need a single-action scope")
        extra += _scope_issues_text(parse_source, mask)
        if is_temporal_statement(statement):
            checked.append("temporal: `eventResource: resource` on every event predicate")
            extra += _temporal_pin_issues(parse_source, mask)
        if groups:
            checked.append("no `==`/`!=` against a Gateway target (action group)")
            extra += _group_equality_text(parse_source, mask, groups, qualify_gw)
        finish_rules(text_claims, extra)
        if local_errors:
            stages["syntax"] = _skipped(_LOCAL_FIRST)
            stages["schema"] = _skipped(_LOCAL_FIRST)
            not_checked.append("syntax and schema validation (skipped while local errors are open)")
        else:
            syntax, schema_stage, version, missing = _dogwood_stages(
                qualified,
                schema_text,
                qualify_gw,
                gaps,
                known,
            )
            stages["syntax"], stages["schema"] = syntax, schema_stage
            checker["dogwood"] = version
            not_checked.extend(missing)
            if syntax["status"] == "passed":
                checked.append("Dogwood check-parse (syntax, macros, provider declarations)")
            if schema_stage["status"] in ("passed", "rejected", "incomplete"):
                checked.append("Dogwood validate against the Cedar schema and event-schema assets")
        if is_temporal_statement(statement):
            not_checked.append(
                "temporal rules: at most 3 temporal operators per policy, and the "
                "`x-amzn-bedrock-agentcore-policy-session-id` header requirement"
            )
        not_checked.append("runtime temporal/provider evaluation")

    if gaps:
        not_checked.append(
            "actions and fields of targets with discovery gaps (unknown ones are reported as "
            "incomplete)"
        )

    not_checked.extend(SERVICE_ONLY_NOT_CHECKED)
    not_checked.append("semantic analysis (vacuity, allow-all and overlap analysis) was not run")
    if is_guardrail_statement(statement):
        not_checked.append(GUARDRAIL_NOT_CHECKED)

    effect_adapter = None
    if adapted:
        effect_adapter = {
            "authored_effect": adapted.authored,
            "parsed_as": adapted.parsed_as,
        }
        if adapted.output_phase:
            not_checked.append(
                f"`{adapted.authored}` output-phase rules: at least one guardrail call, no "
                "temporal clause, guardrail-only conditions"
            )
            not_checked.append(
                f"`{adapted.authored}` direction semantics (the `context.isOutput` guard applied "
                "by the service)"
            )
        else:
            not_checked.append(f"`{adapted.authored}` input-phase rules and direction semantics")
        if adapted.gated:
            not_checked.append(
                f"`{adapted.authored}` account enablement (streaming guardrails entitlement)"
            )

    if local_errors or any(s["status"] == "rejected" for s in stages.values()):
        status = "rejected"
    elif adapted or placeholder_used or any(s["status"] != "passed" for s in stages.values()):
        status = "incomplete"
    else:
        status = "passed"

    return {
        "status": status,
        "dialect": dialect,
        "stages": {k: stages[k] for k in ("syntax", "schema", "api_limits")},
        "local_errors": [{"rule": r, "message": m} for r, m in local_errors],
        "claim_findings": [{"rule": r, "message": m} for r, m in claim_findings],
        "effect_adapter": effect_adapter,
        "submission": {
            "definition_key": "policy" if dialect == "dogwood" else "cedar",
            "validation_mode": required_validation_mode(statement),
        },
        "coverage": {
            "checked": checked,
            "not_checked": list(dict.fromkeys(not_checked)),
        },
        "checker": checker,
    }
