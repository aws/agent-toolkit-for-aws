# Input Validation for DSQL Queries

Part of the [Aurora DSQL Skill](../SKILL.md).

When constructing SQL strings (for `psql -c "..."`, ad-hoc shell pipelines, or any code path
that does not use the driver's native parameter binding), build every query with the
[`safe_query`](../scripts/safe_query.py) helper. Do not interpolate values into SQL with
f-strings, `%`, `.format()`, or concatenation.

When using a Postgres driver in application code (psycopg, pgx, sqlx, JDBC, etc.), prefer the
driver's native parameter binding (`%s` for psycopg, `$1` for pgx, `?` for JDBC). `safe_query`
is the canonical fallback whenever you must build a raw SQL string.

---

## Required Pattern

```python
from safe_query import build, allow, regex, ident, keyword, integer, literal, UnsafeSQLError
from safe_query import TENANT_SLUG, UUID, ISO_DATE

sql = build(
    "SELECT * FROM {tbl} WHERE tenant_id = {tid} AND entity_id = {eid}",
    tbl=ident("entities"),
    tid=regex(tenant_id, TENANT_SLUG),
    eid=regex(entity_id, UUID),
)
# Pass `sql` to your driver: cur.execute(sql), conn.Query(ctx, sql), psql -c "$sql", etc.
```

`build()` raises `UnsafeSQLError` when a placeholder receives a raw string, so
`build("... {x} ...", x=user_input)` fails loudly at the call site.

## Validator Selection

| Value kind                         | Validator              | Emits                |
|------------------------------------|------------------------|----------------------|
| Known set (tenant ID, status enum) | `allow(v, SET)`        | `'value'`            |
| Known set used as SQL keyword      | `keyword(v, SET)`      | `value` (unquoted)   |
| Strict format (UUID, slug)         | `regex(v, PATTERN)`    | `'value'`            |
| Table or column name               | `ident(name)`          | `"value"`            |
| Integer                            | `integer(v)`           | `value`              |
| Free text (description, comment)   | `literal(v)`           | `$dq_xxx$value$dq_xxx$` |

Built-in patterns in `safe_query.py`: `TENANT_SLUG` (`[a-z0-9-]{1,64}`),
`UUID`, `INT`, `ISO_DATE` (structurally validated `YYYY-MM-DD` — month 01–12, day
01–31; does NOT check month-day combinations such as Feb 30. The database will
reject impossible calendar dates at execute time).

## Authorization Is Separate

Format validation proves the value is shaped correctly. It does not prove the
caller is allowed to act on it. Authorize the caller against the tenant or
resource **before** validating format or calling `build()`:

```python
assert_caller_has_tenant_access(caller, tenant_id)   # authorization
sql = build("... WHERE tenant_id = {tid}", tid=regex(tenant_id, TENANT_SLUG))
```

## Why the Helper Exists

- `psql -c "..."` and many shell-driven pipelines accept only SQL strings — there is no
  parameter-binding facility at that layer.
- A Postgres driver's native parameter binding handles validation when the value reaches it as a
  bound parameter, but the moment you build a raw SQL string anywhere along the way (string
  interpolation, dynamic ORDER BY, dynamic table name, etc.), you are back to constructing a SQL
  text. `safe_query.build()` is the canonical way to do that without opening an injection vector.
- Identifier interpolation (table name, column name) cannot be parameter-bound by any standard
  Postgres driver — it MUST be validated and emitted as a quoted identifier. `ident()` is the
  only safe way.

## Rules

- **MUST** build every dynamically-constructed SQL string with `safe_query.build()`.
- **MUST** authorize the caller before validating format.
- **MUST NOT** fall back to f-strings, `%`, `.format()`, or concatenation when
  a validator rejects a value — fix the caller or widen the validator.
- **MUST NOT** catch `UnsafeSQLError` to recover silently. Re-raise or return
  an error to the caller.
- **SHOULD** add new patterns to `safe_query.py` rather than inlining regex at
  call sites, so reviewers can audit them in one place.

## Bash Deliverables

Bash deliverables (CI/CD steps, cron jobs, bastion runbooks) apply the same
rule. **ALWAYS** compose the SQL in a `python3` subshell so `safe_query.py`
actually executes. MUST NOT rely on native reference alone. **MUST** invoke to defend against injection.

```bash
SQL=$(python3 - "$USER_ID" <<'PY'
import sys
from safe_query import build, regex, literal, TENANT_SLUG
print(build(
    "INSERT INTO audit_log (action, user_id) VALUES ({a}, {u})",
    a=literal("psql-write-smoke"),
    u=regex(sys.argv[1], TENANT_SLUG),  # raises on malformed input
))
PY
)
PGPASSWORD=$(aws dsql generate-db-connect-admin-auth-token --hostname "$HOST" --region "$REGION") \
  psql -P pager=off "host=$HOST port=5432 user=admin dbname=postgres sslmode=verify-full sslrootcert=system" <<<"$SQL"
```

`regex()` raises before `psql` runs; `literal()` escapes the validated
value into the final SQL text.

**ALWAYS** explicitly set SSL mode — DSQL rejects non-TLS connections
and psql's default `PGSSLMODE=prefer` will attempt plaintext first.
Two equivalent forms, both valid per the
[AWS DSQL psql guide](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/accessing-psql.html):

- **Env-var form (canonical per AWS docs):** `export PGSSLMODE=verify-full PGSSLROOTCERT=system`
  before the psql invocation, with flag-form arguments
  (`psql --username admin --dbname postgres --host $HOST`).
- **Connection-string form:** embed `sslmode=verify-full sslrootcert=system` in a libpq URI
  (`psql "host=$HOST port=5432 user=admin dbname=postgres sslmode=verify-full sslrootcert=system"`).

Use `sslmode=verify-full sslrootcert=system` (matches `psql-connect.sh`'s default and what the
Java/Rust/Python connectors enforce). Drop to `sslmode=require` only when the client genuinely
cannot reach a trusted CA bundle — and document the downgrade in the runbook.
