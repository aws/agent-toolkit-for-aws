"""Build SQL for Aurora DSQL when raw-SQL construction is unavoidable.

Used by ad-hoc shell pipelines (`psql -c "..."`) and any code path that does not
use the driver's native parameter binding. Every interpolated value MUST pass
through a validator, and `build()` rejects raw strings by construction.

Usage:
    from safe_query import build, allow, regex, ident, keyword, integer, literal
    from safe_query import TENANT_SLUG, UUID

    sql = build(
        "SELECT * FROM {tbl} WHERE tenant_id = {tid} AND entity_id = {eid}",
        tbl=ident("entities"),
        tid=regex(user_tenant, TENANT_SLUG),
        eid=regex(user_eid, UUID),
    )
    # Pass `sql` to your driver: cur.execute(sql), conn.Query(ctx, sql), etc.
    # Or `psql -c "$sql"` after composing in a python3 subshell — see the
    # bash-deliverables block in references/input-validation.md.

    sql = build(
        "INSERT INTO entities (entity_id, tenant_id, name) "
        "VALUES ({eid}, {tid}, {name})",
        eid=regex(new_id, UUID),
        tid=regex(tenant, TENANT_SLUG),
        name=literal(user_supplied_name),   # free text — dollar-quoted
    )

Design rules:
    - Raw strings passed to build() raise UnsafeSQLError. That is the point.
    - Format validation does NOT prove authorization; authorize separately.
    - When using a Postgres driver in application code, prefer the driver's
      native parameter binding. Reach for safe_query whenever you must build
      a raw SQL string (dynamic identifiers, shell-driven pipelines, etc.).
"""

import re
import secrets
import string
from typing import AbstractSet, Any, Callable, Dict, Pattern

TENANT_SLUG: Pattern[str] = re.compile(r"[a-z0-9-]{1,64}")
UUID: Pattern[str] = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
INT: Pattern[str] = re.compile(r"-?[0-9]{1,19}")
ISO_DATE: Pattern[str] = re.compile(r"\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
_IDENT: Pattern[str] = re.compile(r"[a-z_][a-z0-9_]{0,62}", re.IGNORECASE)


class UnsafeSQLError(ValueError):
    """A value failed validation. Never catch and fall back — fix the caller."""


class Safe:
    """A value that has passed validation and is safe to interpolate.

    `build()` accepts only Safe instances. This is how the module prevents
    `build("... {x} ...", x=user_input)` from ever working.
    """

    __slots__ = ("_sql",)

    def __init__(self, sql: str) -> None:
        self._sql = sql

    def __str__(self) -> str:
        return self._sql


def allow(value: Any, allowed: AbstractSet[str], *, label: str = "value") -> Safe:
    """Allowlist-validate and emit as a single-quoted string literal."""
    if value not in allowed:
        raise UnsafeSQLError(f"{label} not in allowlist: {value!r}")
    # Allowlisted values originate from developer-controlled sets; the escape
    # is belt-and-braces in case someone puts a quote in the set.
    return Safe("'" + str(value).replace("'", "''") + "'")


def keyword(value: str, allowed: AbstractSet[str], *, label: str = "keyword") -> Safe:
    """Allowlist-validate a SQL keyword and emit it unquoted.

    Use for ASC/DESC, AND/OR, or other places where a string literal would be
    syntactically wrong.
    """
    if value not in allowed:
        raise UnsafeSQLError(f"{label} not in allowlist: {value!r}")
    return Safe(value)


def regex(value: Any, pattern: Pattern[str], *, label: str = "value") -> Safe:
    """Regex-validate with re.fullmatch and emit as a single-quoted literal.

    Rejects values containing a single quote or backslash. `regex()` is for
    strict-format values (UUIDs, slugs, dates) that never legitimately need
    embedded quotes or backslashes; free text belongs in `literal()`, which
    dollar-quotes and sidesteps escaping entirely.
    """
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise UnsafeSQLError(f"{label} failed pattern {pattern.pattern!r}: {value!r}")
    if "'" in value:
        raise UnsafeSQLError(
            f"{label} contains a single quote; use literal() for free text: {value!r}"
        )
    if "\\" in value:
        raise UnsafeSQLError(
            f"{label} contains a backslash; use literal() for values "
            f"needing special characters: {value!r}"
        )
    return Safe("'" + value + "'")


def ident(name: str) -> Safe:
    """Validate a SQL identifier (table or column) and emit it double-quoted."""
    if not isinstance(name, str) or not _IDENT.fullmatch(name):
        raise UnsafeSQLError(f"invalid identifier: {name!r}")
    return Safe('"' + name + '"')


def integer(value: Any) -> Safe:
    """Validate an integer. Accepts int or numeric string; rejects bool."""
    if isinstance(value, bool):
        raise UnsafeSQLError(f"expected int, got bool: {value!r}")
    if isinstance(value, int):
        return Safe(str(value))
    if isinstance(value, str) and INT.fullmatch(value):
        return Safe(value)
    raise UnsafeSQLError(f"invalid integer: {value!r}")


def literal(value: str) -> Safe:
    """Emit free text as a PostgreSQL dollar-quoted literal.

    Picks a random tag until it does not appear inside `value`, which sidesteps
    quote-escaping entirely. Use for descriptions, names, comments — values
    without a strict format.
    """
    if not isinstance(value, str):
        raise UnsafeSQLError(f"expected str, got {type(value).__name__}")
    for _ in range(8):
        tag = "dq_" + secrets.token_hex(4)
        boundary = f"${tag}$"
        if boundary not in value:
            return Safe(f"{boundary}{value}{boundary}")
    # Eight 32-bit-random tag collisions implies adversarial input.
    raise UnsafeSQLError("could not generate a unique dollar-quote tag")


def build(template: str, **parts: Safe) -> str:
    """Substitute validated parts into a SQL template.

    Template uses `{name}` placeholders (str.format syntax). Every placeholder
    MUST map to a Safe value; raw strings raise UnsafeSQLError so the
    `build("... {t} ...", t=user_input)` anti-pattern fails loudly.

    Also rejects template/kwargs mismatch: a missing key would otherwise raise
    `KeyError` (invisible to callers catching `UnsafeSQLError`), and an extra
    key would be silently ignored — dropping, for example, a tenant filter
    from the query.
    """
    for key, value in parts.items():
        if not isinstance(value, Safe):
            raise UnsafeSQLError(
                f"{key!r} must be a Safe value from allow/regex/ident/"
                f"keyword/integer/literal; got {type(value).__name__}"
            )
    expected: set[str] = set()
    for _, fname, fspec, conv in string.Formatter().parse(template):
        if fname is None:
            continue
        if fname == "" or fname.isdigit():
            raise UnsafeSQLError(
                f"template contains a positional placeholder {{{fname or ''}}}; "
                f"use named placeholders like {{name}}"
            )
        if conv:
            raise UnsafeSQLError(
                f"placeholder {{{fname}!{conv}}} uses a conversion flag; "
                f"Safe values must be interpolated without conversion"
            )
        if fspec:
            raise UnsafeSQLError(
                f"placeholder {{{fname}:{fspec}}} uses a format spec; "
                f"Safe values must be interpolated without formatting"
            )
        expected.add(fname)
    provided = set(parts.keys())
    if expected != provided:
        missing = expected - provided
        extra = provided - expected
        raise UnsafeSQLError(
            f"template/kwargs mismatch: missing {sorted(missing)}, " f"extra {sorted(extra)}"
        )
    try:
        return template.format(**{k: str(v) for k, v in parts.items()})
    except (KeyError, IndexError) as exc:
        raise UnsafeSQLError(
            f"template references a key not in kwargs " f"(possibly in a format spec): {exc}"
        ) from exc


def _selftest() -> None:
    """Smoke-test every validator and build()."""

    def _check(condition: bool, msg: str) -> None:
        if not condition:
            raise RuntimeError(msg)

    def _expect_unsafe(fn: str, *args: Any, **kwargs: Any) -> None:
        """Call a validator/build by name and verify it raises UnsafeSQLError."""
        registry: Dict[str, Callable[..., Any]] = {
            "allow": allow,
            "keyword": keyword,
            "regex": regex,
            "ident": ident,
            "integer": integer,
            "literal": literal,
            "build": build,
        }
        target = registry[fn]
        try:
            target(*args, **kwargs)
            raise RuntimeError(f"expected UnsafeSQLError from {fn}")
        except UnsafeSQLError:
            pass

    # Happy paths
    _check(str(allow("tenant-1", {"tenant-1"})) == "'tenant-1'", "allow")
    _check(str(keyword("ASC", {"ASC", "DESC"})) == "ASC", "keyword")
    _check(str(regex("a-1", TENANT_SLUG)) == "'a-1'", "regex")
    _check(str(ident("entities")) == '"entities"', "ident")
    _check(str(integer(42)) == "42", "integer")
    _check(str(integer("-7")) == "-7", "integer neg")
    lit = str(literal("o'reilly"))
    _check(lit.startswith("$dq_") and "o'reilly" in lit, "literal")

    sql = build(
        "SELECT * FROM {t} WHERE tenant_id = {tid}",
        t=ident("entities"),
        tid=regex("acme", TENANT_SLUG),
    )
    _check(sql == "SELECT * FROM \"entities\" WHERE tenant_id = 'acme'", "build")
    _check(str(regex("abc", TENANT_SLUG, label="tenant")) == "'abc'", "regex label")

    # Rejections
    _permissive = re.compile(r".+")
    _expect_unsafe("allow", "evil", {"tenant-1"})
    _expect_unsafe("keyword", "DROP", {"ASC", "DESC"})
    _expect_unsafe("regex", "'; DROP TABLE t; --", TENANT_SLUG)
    _expect_unsafe("ident", 'x" OR 1=1 --')
    _expect_unsafe("integer", "1; DROP")
    _expect_unsafe("integer", True)
    _expect_unsafe("literal", 123)
    _expect_unsafe("build", "SELECT {x}", x="raw string")
    _expect_unsafe("regex", "x' OR 1=1 --", _permissive)
    _expect_unsafe("regex", "it's", _permissive)
    _expect_unsafe("regex", "'", _permissive)
    _expect_unsafe("regex", "abc\\", _permissive)
    _expect_unsafe("build", "SELECT {x}", x=ident("col"), y=ident("extra"))
    _expect_unsafe("build", "SELECT {x} FROM {y}", x=ident("col"))
    _expect_unsafe("build", "SELECT {x!r}", x=ident("col"))
    _expect_unsafe("build", "SELECT {x:>30}", x=ident("col"))
    _expect_unsafe("build", "SELECT {}", x=ident("col"))
    _expect_unsafe("build", "SELECT {0}", x=ident("col"))

    print("safe_query self-test passed")


if __name__ == "__main__":
    _selftest()
