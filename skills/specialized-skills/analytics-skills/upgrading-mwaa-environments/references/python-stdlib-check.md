# Python Standard-Library Check (Phase 3 step 1a)

Run this for every version jump flagged `python_change`. It finds DAG,
shared-utility and plugin code that uses a standard-library module, function
or method the new Python line removed (for example `import imp` on a 3.11 to
3.12 jump). Ruff AIR rules and the requirements re-check do not cover the
standard library, so this code passes every other pre-upgrade check and then
fails to parse on the live environment after the jump.

Do not keep or rely on a fixed list of removed names. Derive it each time
from the Python docs, so the check stays correct when MWAA adds a new Python
line.

## Procedure

1. **Derive the removed names.** For every Python line the jump enters (each
   `3.N` after `python_from`, up to and including `python_to`), fetch
   `https://docs.python.org/3/whatsnew/3.<N>.html` and read the section that
   lists removals. The heading varies by release ("Removed", "Removed Modules
   And APIs"); also read "Porting to Python `3.<N>`" when present. List the
   removed modules, and the removed functions, classes and methods.
2. **Grep the code.** Scan the DAG folder, shared utilities (such as
   `dags/common/`, `dags/utils/`) and the contents of `plugins.zip` (unzip to
   a scratch directory). Match removed modules as imports, and removed
   functions, classes and methods as attribute access:

   ```
   grep -rnE '^\s*(import|from)\s+(<mod1>|<mod2>)\b' <dags-dir> <unzipped-plugins-dir>
   grep -rnE '\.(<name1>|<name2>)\b' <dags-dir> <unzipped-plugins-dir>
   grep -rnE '^\s*from\s+\S+\s+import\s+.*\b(<name1>|<name2>)\b' <dags-dir> <unzipped-plugins-dir>
   ```

   For a 3.11 to 3.12 jump, the modules include `imp`, `distutils`,
   `asyncore` and `asynchat`, and the names include `SafeConfigParser`,
   `readfp` and `wrap_socket`. Treat these as examples only; the docs page is
   the source.
3. **Review each hit in context.** A name that also exists on a third-party
   class, or appears only in a comment or string, is not a finding.

The check reads code statically. It cannot see dynamic imports or failures
that only happen at runtime; Docker validation (Phase 6) covers those.

If the docs pages cannot be fetched, record the check as `INCOMPLETE` and
warn the user that removed-standard-library usage was not checked. Never
record a check that could not run as clean. An `INCOMPLETE` check blocks the
`python_change` jump until the user acknowledges it (see the pre-jump gate in
upgrade-engine.md).

## Record in the plan

Under the plan's `python-stdlib` findings, per `python_change` jump:

- the Python lines checked (`3.11 → 3.12`);
- the derived removed-name list, so a resumed session reuses it instead of
  reading the pages again (or `INCOMPLETE` with the reason);
- each hit as `file | line | usage` with status `PENDING`, set to `DONE` once
  fixed and re-checked (5-PY.1 / 5-PY.2).

## Common replacements

These replacements also run on the source Python, so they can be deployed
before the jump (Phase 5, 5-PY.1):

| Removed | Use instead |
|---|---|
| `imp` (`imp.load_source`, `imp.reload`) | `importlib.util.spec_from_file_location` + `module_from_spec`; `importlib.reload` |
| `distutils.version.LooseVersion` / `StrictVersion` | `packaging.version.Version` (`packaging` is installed with Airflow) |
| `distutils.util.strtobool` | a local helper that keeps its behavior: return `1` for `y/yes/t/true/on/1`, `0` for `n/no/f/false/off/0` (case-insensitive), and raise `ValueError` for anything else |
| other `distutils` helpers | `shutil`, `sysconfig`, or `setuptools` equivalents |
| `configparser.SafeConfigParser` | `configparser.ConfigParser` |
| `ConfigParser.readfp(f)` | `ConfigParser.read_file(f)` |
| `asyncore` / `asynchat` | `asyncio` |
| `ssl.wrap_socket(...)` | `ssl.create_default_context().wrap_socket(...)` (keep certificate verification on) |

For anything not in this table, use the replacement the "What's New" entry
names.
