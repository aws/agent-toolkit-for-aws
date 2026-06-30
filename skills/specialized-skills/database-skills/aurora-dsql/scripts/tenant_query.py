"""Fetch all rows from `entities` for a given tenant.

req.tenant is untrusted input — it MUST be validated before interpolation.
The execution path here builds a raw SQL string (for cases where a driver's
native parameter binding cannot be used — e.g., dynamic identifiers, shell
pipelines). safe_query.build() is the injection defense.

Authorization note: format validation (regex) confirms the value looks like a
valid tenant slug. It does NOT prove the caller is authorized to read that
tenant's data. Authorize the caller against req.tenant before calling this
function.
"""

from safe_query import build, regex, ident, TENANT_SLUG


def select_by_tenant(cursor, req) -> list[tuple]:
    """Return all rows from `entities` where tenant_id matches req.tenant.

    Uses cursor-based execution so the same shape works across psycopg2,
    psycopg3, and pgx-style cursors (psycopg2's `cursor.execute` returns None,
    so the caller must use `cursor.fetchall()` separately rather than chain).

    Args:
        cursor: A driver cursor that exposes `.execute(sql)` and `.fetchall()`.
            For psycopg3 you can also pass `connection.cursor()` or use
            `connection.execute(sql).fetchall()` directly inline.
        req: An object with a `.tenant` attribute (untrusted string).

    Returns:
        A list of row tuples (or row dicts, depending on the cursor's
        configured row factory).

    Raises:
        UnsafeSQLError: If req.tenant fails TENANT_SLUG validation.
        ValueError: If req.tenant is missing or not a string.
    """
    tenant = getattr(req, "tenant", None)
    if not isinstance(tenant, str):
        raise ValueError(f"req.tenant must be a str, got {type(tenant).__name__}")

    sql = build(
        "SELECT * FROM {t} WHERE tenant_id = {tid}",
        t=ident("entities"),
        tid=regex(tenant, TENANT_SLUG, label="req.tenant"),
    )

    cursor.execute(sql)
    return cursor.fetchall()
