---
_fragment: artifacts-scripts
_of_phase: generate
_contributes:
  - scripts/01-validate-prerequisites.sh
  - scripts/02-migrate-data.sh
  - scripts/03-migrate-containers.sh
  - scripts/04-migrate-secrets.sh
  - scripts/05-validate-migration.sh
---
# Generate — Migration Scripts
> **Fragment unit.** See `generate.md` for how it is composed into the phase.

Transform `aws-design.json` and `preferences.json` into numbered migration scripts for
prerequisites, data, container images, secrets and validation. **Generate writes these files
and nothing more: no script runs during Generate**, and none of them is run for the user. The
operator reads `MIGRATION_GUIDE.md`, previews each script in its default dry-run mode, and
decides when to pass `--execute`.

This fragment mirrors gcp-to-aws's `generate-artifacts-scripts.md` safety rails. Azure
sources differ (Azure Database for PostgreSQL/MySQL Flexible Server, Azure Container
Registry, Key Vault), so the blocks below are Azure-specific and are exercised by
`tests/test_azure_script_templates.py` with stubbed tools.

**Execute the steps in order.**

## Inputs
Read from `$MIGRATION_DIR/`: `aws-design.json` (`services[]` with `azure_type`,
`aws_service`) and `preferences.json`. If either is missing, **STOP** and report "Missing
required artifact: [filename]".

Read the confirmed cutover choice from `data.db_cutover.value` and the target region from
`design_constraints.target_region.value`. Never read `data.db_cutover.default`: that field
holds `dump_restore` even when the user chose `dms`. A `null` or absent `value` means the
choice is unconfirmed (`CUTOVER_UNCONFIRMED`).

## Step 1: Detect resource categories
Scan `aws-design.json` `services[]` (skip `deferred[]` entries, which carry no AWS target).
Source-side flags come from `azure_type`:

- **has_database**: any of `Microsoft.DBforPostgreSQL/flexibleServers`,
  `Microsoft.DBforMySQL/flexibleServers`, the retired Single Server types
  (`Microsoft.DBforPostgreSQL/servers`, `Microsoft.DBforMySQL/servers`), `Microsoft.Sql/*`,
  `Microsoft.DocumentDB/*`, `Microsoft.Cache/Redis`, or any other database type.
- **has_containers**: `Microsoft.ContainerRegistry/registries`.
- **has_secrets**: `Microsoft.KeyVault/vaults`.

Inventory-section flags for `05` come from `aws_service`: **ECS** ("Fargate" or "ECS"),
**EKS**, **Elastic Beanstalk**, **Lambda**, **RDS** ("RDS" or "Aurora"), **ECR**
(has_containers), **S3** (equals "S3"), **Secrets Manager**. A false flag omits its section.

Report: "Resource categories detected: [list active flags]".

## Output structure

```text
$MIGRATION_DIR/scripts/
├── 01-validate-prerequisites.sh   # Always
├── 02-migrate-data.sh             # Only if has_database
├── 03-migrate-containers.sh       # Only if has_containers
├── 04-migrate-secrets.sh          # Only if has_secrets
└── 05-validate-migration.sh       # Always (adapts checks)
```

## Step 2: Script rules

- Every script that changes anything defaults to **dry-run**. Only `--execute` may change
  anything. Dry-run makes no cloud call, reads no secret value, and creates no file or
  directory. `05-validate-migration.sh` only reads: it takes no argument, never writes, and
  exits **2** on any argument.
- For every other script, an unknown argument (an empty string included), or more than one
  argument, exits **2** before any work.
- Every script uses `set -euo pipefail`. Every script that handles a password or a secret
  (02, 03, 04) turns tracing off right after it with `set +x`, so a caller's
  `SHELLOPTS=xtrace` cannot print a password.
- Scripts 03 and 04 read space-separated lists (`IMAGE_LIST`, `SECRET_NAMES`) and turn
  globbing off with `set -f`, so a `*` in a list is never expanded to file names. Counters use `count=$((count + 1))`, never
  `((count++))`.
- Every `--execute` run logs its actions under `$MIGRATION_DIR/logs/`. Dry-run prints only.
- Resolve paths from the script's own directory; never rely on the caller's working
  directory.
- **List ALL missing inputs at `--execute`.** Each script checks every env var it needs in
  one pass at the top of the execute path and exits 1 listing all missing names at once,
  before any cloud call. Dry-run runs without them.
- Never print a secret. Preserve supplied env vars with `${NAME:-}`. Passwords never go on a
  command line, in a URI, or into a log. Database passwords reach the client tools only
  through a restricted credentials file (`mktemp`, directory `chmod 700`, file `chmod 600`,
  removed on exit).
- A copy is verified before cutover. An inventory listing is not a data-integrity check, and
  a failed or unavailable required check returns nonzero.
- Every script ends the execute path with a verification step that reports failure through
  its exit code.

Use this preamble at the top of each script (set the log name and usage line per script):

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x # A caller's SHELLOPTS=xtrace must not print passwords or secrets.
# Script preamble (shared rules)
# Usage: ./NN-name.sh [--execute]
DRY_RUN=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
if [ "$#" -eq 1 ]; then # An empty string is an argument too: only --execute is accepted.
  [ "$1" = "--execute" ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
  DRY_RUN=false
fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MIGRATION_DIR=$(dirname "$SCRIPT_DIR")
LOG_FILE="$MIGRATION_DIR/logs/NN-name.log"
log() {
  printf '%s\n' "$*"
  if [ "$DRY_RUN" = false ]; then
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"
  fi
}
if [ "$DRY_RUN" = false ]; then
  mkdir -p "$MIGRATION_DIR/logs"
fi
echo "Mode: $([ "$DRY_RUN" = true ] && echo 'DRY RUN' || echo 'EXECUTE')"
```

The blocks below show the preamble once; each emitted script starts with it.

### 01-validate-prerequisites.sh (always)
With no argument, check only local tool availability and print the planned read-only cloud
checks. `--execute` authorizes those checks. This script freezes nothing and does not prove
every permission.

```bash
#!/usr/bin/env bash
set -euo pipefail
# Prerequisite checks: no cloud calls in the default preview.
DRY_RUN=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
if [ "$#" -eq 1 ]; then # An empty string is an argument too: only --execute is accepted.
  [ "$1" = "--execute" ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
  DRY_RUN=false
fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MIGRATION_DIR=$(dirname "$SCRIPT_DIR")
LOG_FILE="$MIGRATION_DIR/logs/01-validate-prerequisites.log"
if [ "$DRY_RUN" = false ]; then
  mkdir -p "$MIGRATION_DIR/logs"
fi
passed=0
failed=0
check() {
  if "$@" >/dev/null 2>&1; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    echo "FAILED prerequisite: $*" >&2
  fi
  return 0
}
# Keep the tool list to the tools the emitted scripts actually call.
for tool in aws terraform; do
  check command -v "$tool"
done
# Per-engine and per-script tools: emit only the lines for scripts that were generated.
# 02 PostgreSQL:  check command -v pg_dump;   check command -v pg_restore
# 02 MySQL:       check command -v mysqldump; check command -v mysql
# 03 containers:  check command -v docker
# 03 or 04:       check command -v az
if [ "$DRY_RUN" = false ]; then
  check aws sts get-caller-identity
  # 03 or 04:     check az account show
  # Add only read-only, target-specific access checks here.
else
  echo "DRY RUN: AWS identity, Azure sign-in and connectivity checks are not run."
fi
printf "Prerequisites: %s passed, %s failed\n" "$passed" "$failed"
if [ "$DRY_RUN" = false ]; then
  printf '%s prerequisites: %s passed, %s failed\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$passed" "$failed" >> "$LOG_FILE"
fi
[ "$failed" -eq 0 ] || exit 1
```

Uncomment only the per-engine lines for scripts that were generated, and delete the rest.
Uncomment the two `az` lines only when script 03 or 04 was generated. Do not add a tool that
no emitted script calls.

### 02-migrate-data.sh (only if has_database)
**There is no tested replication workflow in this plugin.** The script therefore supports
exactly one mechanism: an **offline copy** of Azure Database for PostgreSQL or MySQL Flexible
Server with all writers frozen. Everything else is a named HOLD.

Select the branch from `preferences.json` `data.db_cutover.value` (never `.default`) and the
engine of the database being migrated:

| `data.db_cutover.value` | Engine | Emit |
| ----------------- | ------ | ---- |
| any value, `null` and absent included | any other engine (Azure SQL, Cosmos DB, Redis, ...) | HOLD `ENGINE_NOT_SUPPORTED` |
| `dump_restore` | PostgreSQL Flexible Server | Offline copy, PostgreSQL blocks |
| `dump_restore` | MySQL Flexible Server | Offline copy, MySQL blocks |
| `dms` | PostgreSQL or MySQL Flexible Server | HOLD `DMS_NOT_IMPLEMENTED` |
| `null`, absent, or any other value | PostgreSQL or MySQL Flexible Server | HOLD `CUTOVER_UNCONFIRMED` |

An unsupported engine is a HOLD whatever `data.db_cutover.value` says, `null` included,
because the runbook's choice does not describe a tested path for it. Clarify marks
`data.db_cutover` N/A when the estate holds no relational database, so a Cosmos DB-only or
Redis-only design has a `null` value that no Decision gate row can clear: it gets
`ENGINE_NOT_SUPPORTED`, never `CUTOVER_UNCONFIRMED`. The script handles one database per run:
the operator sets the host, database and credentials per run. Report every unsupported
database to the assembler as a `warnings[]` entry `{ "code": "ENGINE_NOT_SUPPORTED",
"subject": "<azure_id>", "detail": "<engine> is not handled by scripts/02-migrate-data.sh" }`,
including the database a HOLD names and including an estate whose only databases are
unsupported. When the estate also holds a supported database, emit the supported branch.
Do not write `generation-warnings.json`: only the assembler creates it. Never apply the
PostgreSQL or MySQL blocks to another engine.

When the estate holds both a PostgreSQL and a MySQL Flexible Server, emit the data script for
the engine that appears first in `services[]` order and report the other as a `warnings[]`
entry with `code` `ENGINE_NOT_SUPPORTED`, `subject` its `azure_id` and `detail` "second
engine; run the data script once per database".

#### HOLD branches
Emit the preamble and exactly one of these blocks, and nothing that connects to a database.
Dry-run prints the HOLD and exits 0. `--execute` exits 1. In the unsupported-engine block,
replace the example value of `HOLD_ENGINE` with the real Azure resource type. The emitted
HOLD text must contain no angle-bracket placeholder.

```bash
# Data migration (Azure) — HOLD: dms
# data.db_cutover.value is dms. No tested AWS DMS replication workflow exists in this plugin.
HOLD_CODE="DMS_NOT_IMPLEMENTED"
HOLD_REASON="replication is run by the operator in AWS DMS following MIGRATION_GUIDE.md; this script does not start, monitor or verify it"
echo "HOLD[$HOLD_CODE]: $HOLD_REASON" >&2
[ "$DRY_RUN" = true ] || exit 1
```

```bash
# Data migration (Azure) — HOLD: unsupported engine
HOLD_ENGINE="Microsoft.Sql/servers" # Replace with the Azure resource type of the database.
HOLD_CODE="ENGINE_NOT_SUPPORTED"
HOLD_REASON="$HOLD_ENGINE has no tested migration path; a specialist must choose the method (see MIGRATION_GUIDE.md, Not covered by this runbook)"
echo "HOLD[$HOLD_CODE]: $HOLD_REASON" >&2
[ "$DRY_RUN" = true ] || exit 1
```

```bash
# Data migration (Azure) — HOLD: cutover unconfirmed
# data.db_cutover.value is null, absent or not one of dump_restore, dms.
HOLD_CODE="CUTOVER_UNCONFIRMED"
HOLD_REASON="data.db_cutover.value is not confirmed; return to the Decision gate"
echo "HOLD[$HOLD_CODE]: $HOLD_REASON" >&2
[ "$DRY_RUN" = true ] || exit 1
```

#### Offline copy (`dump_restore`, PostgreSQL or MySQL)
Emit, in order: the preamble, **one** inputs block (PostgreSQL or MySQL), the shared guard,
the engine's credentials block, the engine's copy block, and the verification gate.

PostgreSQL inputs:

```bash
# Data migration (Azure) — offline copy inputs (PostgreSQL)
DB_ENGINE="postgresql"
SOURCE_HOST="${SOURCE_HOST:-}"   # Flexible Server host name, no port, for example name.postgres.database.azure.com
TARGET_HOST="${TARGET_HOST:-}"   # RDS/Aurora address output, not an endpoint containing :port
SOURCE_PORT="${SOURCE_PORT:-5432}"
TARGET_PORT="${TARGET_PORT:-5432}"
SOURCE_DB_USER="${SOURCE_DB_USER:-}"
TARGET_DB_USER="${TARGET_DB_USER:-}"
DATABASE_NAME="${DATABASE_NAME:-}"   # Exact name; must already exist on the target
```

MySQL inputs:

```bash
# Data migration (Azure) — offline copy inputs (MySQL)
DB_ENGINE="mysql"
SOURCE_HOST="${SOURCE_HOST:-}"   # Flexible Server host name, no port, for example name.mysql.database.azure.com
TARGET_HOST="${TARGET_HOST:-}"   # RDS/Aurora address output, not an endpoint containing :port
SOURCE_PORT="${SOURCE_PORT:-3306}"
TARGET_PORT="${TARGET_PORT:-3306}"
SOURCE_DB_USER="${SOURCE_DB_USER:-}"
TARGET_DB_USER="${TARGET_DB_USER:-}"
DATABASE_NAME="${DATABASE_NAME:-}"   # Exact name; must already exist on the target
```

The shared guard runs before any database connection. It stops on missing inputs (listing
all of them), on missing write-freeze acknowledgements and on a missing verifier. A script
cannot infer that all writers are stopped: `SOURCE_WRITES_FROZEN=yes` and
`TARGET_WRITES_FROZEN=yes` refer to the write-freeze mechanism and evidence in the guide.
`DATA_VERIFIER` is operator-supplied (see the verification gate).

```bash
# Offline-copy guard (shared)
DB_AUTH_DIR=""
DUMP_DIR=""
cleanup() {
  [ -z "$DUMP_DIR" ] || rm -rf "$DUMP_DIR"
  [ -z "$DB_AUTH_DIR" ] || rm -rf "$DB_AUTH_DIR"
}
trap cleanup EXIT
DATA_VERIFIER="${DATA_VERIFIER:-}"
# Dump files can be as large as the database: point DUMP_DIR_BASE at a directory with enough
# free space (the guide says to check it against the database size).
DUMP_DIR_BASE="${DUMP_DIR_BASE:-${TMPDIR:-/tmp}}"
if [ "$DRY_RUN" = false ]; then
  missing=()
  for v in SOURCE_HOST TARGET_HOST SOURCE_DB_USER TARGET_DB_USER DATABASE_NAME SOURCE_DB_PASSWORD TARGET_DB_PASSWORD DATA_VERIFIER; do
    [ -n "${!v:-}" ] || missing+=("$v")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "Cannot execute — set these first (see MIGRATION_GUIDE.md): ${missing[*]}" >&2
    exit 1
  fi
  if [ "${SOURCE_WRITES_FROZEN:-}" != yes ] || [ "${TARGET_WRITES_FROZEN:-}" != yes ]; then
    echo "HOLD[WRITES_NOT_FROZEN]: freeze all source and target application writers; keep database reads." >&2
    exit 1
  fi
  if [ ! -f "$DATA_VERIFIER" ] || [ ! -x "$DATA_VERIFIER" ]; then
    echo "HOLD[VERIFIER_MISSING]: DATA_VERIFIER must name a reviewed executable data-integrity check." >&2
    exit 1
  fi
  if [ ! -d "$DUMP_DIR_BASE" ] || [ ! -w "$DUMP_DIR_BASE" ]; then
    echo "HOLD[BAD_INPUT]: DUMP_DIR_BASE must be a writable directory." >&2
    exit 1
  fi
  for name in SOURCE_HOST TARGET_HOST; do
    case "${!name}" in
      ""|*[!a-zA-Z0-9._-]*)
        echo "HOLD[BAD_INPUT]: $name must be a DNS name or IPv4 address without :port or a URI." >&2
        exit 1 ;;
    esac
  done
  for name in SOURCE_PORT TARGET_PORT; do
    value="${!name}"
    case "$value" in
      ""|*[!0-9]*) echo "HOLD[BAD_INPUT]: $name must be an integer TCP port." >&2; exit 1 ;;
    esac
    if [ "${#value}" -gt 5 ] || [ "$((10#$value))" -lt 1 ] || [ "$((10#$value))" -gt 65535 ]; then
      echo "HOLD[BAD_INPUT]: $name must be between 1 and 65535." >&2
      exit 1
    fi
    printf -v "$name" '%s' "$((10#$value))"
  done
  if [ "$SOURCE_HOST:$SOURCE_PORT" = "$TARGET_HOST:$TARGET_PORT" ]; then
    echo "HOLD[BAD_INPUT]: source and target must be different servers." >&2
    exit 1
  fi
  # Client tools can read a database name as a connection string or an option.
  case "$DATABASE_NAME" in
    -*|*=*|postgresql://*|postgres://*)
      echo "HOLD[BAD_INPUT]: this database name needs a reviewed explicit-connection variant." >&2
      exit 1 ;;
  esac
  # Credentials files are line-oriented. Reject newlines rather than corrupting them.
  for name in DATABASE_NAME SOURCE_DB_USER TARGET_DB_USER SOURCE_DB_PASSWORD TARGET_DB_PASSWORD; do
    case "${!name}" in
      *$'\n'*|*$'\r'*) echo "HOLD[BAD_INPUT]: multiline $name needs a separately reviewed authentication setup." >&2; exit 1 ;;
    esac
  done
  DB_AUTH_DIR=$(mktemp -d "${TMPDIR:-/tmp}/azure-migration-auth.XXXXXX")
  chmod 700 "$DB_AUTH_DIR"
fi
```

PostgreSQL credentials (a libpq password file; passwords never reach arguments or logs):

```bash
# Offline copy credentials (PostgreSQL)
if [ "$DRY_RUN" = false ]; then
  export PGSSLMODE="${PGSSLMODE:-require}"
  case "$PGSSLMODE" in
    require|verify-ca|verify-full) ;;
    *) echo "HOLD[BAD_INPUT]: PGSSLMODE must require TLS (require, verify-ca or verify-full)." >&2; exit 1 ;;
  esac
  unset PGPASSWORD # A caller's global password must not override the password file.
  pass_field() {
    local value="$1" char i
    for ((i = 0; i < ${#value}; i = i + 1)); do
      char="${value:i:1}"
      case "$char" in
        "\\"|":") printf '\\%s' "$char" ;;
        *) printf '%s' "$char" ;;
      esac
    done
  }
  export PGPASSFILE="$DB_AUTH_DIR/pgpass"
  (umask 077
    {
      printf '%s:%s:%s:%s:%s\n' "$(pass_field "$SOURCE_HOST")" "$SOURCE_PORT" "$(pass_field "$DATABASE_NAME")" "$(pass_field "$SOURCE_DB_USER")" "$(pass_field "$SOURCE_DB_PASSWORD")"
      printf '%s:%s:%s:%s:%s\n' "$(pass_field "$TARGET_HOST")" "$TARGET_PORT" "$(pass_field "$DATABASE_NAME")" "$(pass_field "$TARGET_DB_USER")" "$(pass_field "$TARGET_DB_PASSWORD")"
    } > "$PGPASSFILE"
  )
fi
```

MySQL credentials (a client option file per side; values double-quoted and escaped):

```bash
# Offline copy credentials (MySQL)
if [ "$DRY_RUN" = false ]; then
  cnf_value() {
    local value="$1" char i
    printf '"'
    for ((i = 0; i < ${#value}; i = i + 1)); do
      char="${value:i:1}"
      case "$char" in
        "\\"|'"') printf '\\%s' "$char" ;;
        *) printf '%s' "$char" ;;
      esac
    done
    printf '"'
  }
  write_cnf() { # file host port user password
    (umask 077
      {
        printf '[client]\n'
        printf 'host=%s\n' "$(cnf_value "$2")"
        printf 'port=%s\n' "$3"
        printf 'user=%s\n' "$(cnf_value "$4")"
        printf 'password=%s\n' "$(cnf_value "$5")"
        printf 'ssl-mode=REQUIRED\n'
      } > "$1"
    )
  }
  SOURCE_CNF="$DB_AUTH_DIR/source.cnf"
  TARGET_CNF="$DB_AUTH_DIR/target.cnf"
  write_cnf "$SOURCE_CNF" "$SOURCE_HOST" "$SOURCE_PORT" "$SOURCE_DB_USER" "$SOURCE_DB_PASSWORD"
  write_cnf "$TARGET_CNF" "$TARGET_HOST" "$TARGET_PORT" "$TARGET_DB_USER" "$TARGET_DB_PASSWORD"
  export MYSQL_SOURCE_DEFAULTS_FILE="$SOURCE_CNF" MYSQL_TARGET_DEFAULTS_FILE="$TARGET_CNF"
fi
```

PostgreSQL copy:

```bash
# Offline copy (PostgreSQL): pg_dump, then pg_restore
if [ "$DRY_RUN" = true ]; then
  log "[DRY RUN] Would dump $DATABASE_NAME from the Azure server with pg_dump and restore it into the AWS target with pg_restore."
else
  DUMP_DIR=$(mktemp -d "$DUMP_DIR_BASE/azure-migration-dump.XXXXXX")
  chmod 700 "$DUMP_DIR"
  DUMP_FILE="$DUMP_DIR/database.dump"
  log "Dumping $DATABASE_NAME from $SOURCE_HOST"
  pg_dump --no-password -h "$SOURCE_HOST" -p "$SOURCE_PORT" -U "$SOURCE_DB_USER" -d "$DATABASE_NAME" --no-owner --no-acl -Fc -f "$DUMP_FILE"
  log "Restoring $DATABASE_NAME into $TARGET_HOST"
  pg_restore --no-password --exit-on-error --no-owner --no-acl -h "$TARGET_HOST" -p "$TARGET_PORT" -U "$TARGET_DB_USER" -d "$DATABASE_NAME" -Fc "$DUMP_FILE"
fi
```

MySQL copy:

```bash
# Offline copy (MySQL): mysqldump, then mysql
if [ "$DRY_RUN" = true ]; then
  log "[DRY RUN] Would dump $DATABASE_NAME from the Azure server with mysqldump and load it into the AWS target with mysql."
else
  DUMP_DIR=$(mktemp -d "$DUMP_DIR_BASE/azure-migration-dump.XXXXXX")
  chmod 700 "$DUMP_DIR"
  DUMP_FILE="$DUMP_DIR/database.sql"
  log "Dumping $DATABASE_NAME from $SOURCE_HOST"
  mysqldump --defaults-extra-file="$SOURCE_CNF" --single-transaction --routines --triggers --events "$DATABASE_NAME" > "$DUMP_FILE"
  log "Loading $DATABASE_NAME into $TARGET_HOST"
  mysql --defaults-extra-file="$TARGET_CNF" "$DATABASE_NAME" < "$DUMP_FILE"
fi
```

**Verification gate.** Emit after the copy. `DATA_VERIFIER` must compare source and target
table inventories, exact row counts, deterministic content checksums and the required
sequence or application invariants, and must return nonzero on a mismatch, missing coverage
or query failure. It receives `--engine`, `--source-host`, `--source-port`,
`--source-user`, `--target-host`, `--target-port`, `--target-user` and `--database`, and
finds credentials through `PGPASSFILE` (PostgreSQL) or `MYSQL_SOURCE_DEFAULTS_FILE` and
`MYSQL_TARGET_DEFAULTS_FILE` (MySQL). Never replace it with an echo, a TODO, an inventory
listing or a row-count-only check. Do not emit a verifier unless the schema permits a
complete one; otherwise label data migration **unfinished / HOLD: awaiting a reviewed
verifier** in the guide, README and report.

```bash
# Data-integrity gate: required before either side's writers or cutover are enabled.
if [ "$DRY_RUN" = true ]; then
  echo "DRY RUN: the copy is offline; a reviewed data verifier is required before execution."
else
  if ! "$DATA_VERIFIER" --engine "$DB_ENGINE" \
      --source-host "$SOURCE_HOST" --source-port "$SOURCE_PORT" --source-user "$SOURCE_DB_USER" \
      --target-host "$TARGET_HOST" --target-port "$TARGET_PORT" --target-user "$TARGET_DB_USER" \
      --database "$DATABASE_NAME"; then
    echo "HOLD[VERIFICATION_FAILED]: keep writers frozen and do not cut over." >&2
    exit 1
  fi
  log "Offline copy and data verification passed. Cutover still needs the guide's release gates."
fi
```

The copy dumps one database. It does not dump roles or grants (`--no-owner --no-acl`). The
PostgreSQL dump does include `CREATE EXTENSION` for each of the database's non-system
extensions (`pg_dump` without `-e` dumps them), and `pg_restore --exit-on-error` stops at one
the target engine version cannot create. The operator creates the roles the application needs
and confirms before the window that every extension in use is available on the target engine
version, removing or replacing one that is not (the guide says so).

A single full copy is not change data capture and not a delta sync. Never emit a
`--final-sync`-style flag, a lag gate or a claim that a second copy applies only changes.
Do not use `az postgres flexible-server stop` or `az mysql flexible-server stop` as a write
freeze: it stops reads too and prevents the copy from connecting.

### 03-migrate-containers.sh (only if has_containers)
Copies images from Azure Container Registry to Amazon ECR. The operator lists the images; a
script does not guess them.

```bash
# App migration: container images (ACR → ECR)
# Usage: ./03-migrate-containers.sh [--execute]
# Inputs: ACR_NAME, IMAGE_LIST (space-separated repository:tag), AWS_REGION, optional AWS_ACCOUNT_ID,
#         optional ACR_LOGIN_SERVER, optional IMAGE_PLATFORM (default linux/amd64)
set -f # A * in IMAGE_LIST must never expand to file names in the caller's directory.
AWS_REGION="${AWS_REGION:-us-east-1}" # Replace the default with design_constraints.target_region.value.
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"
ACR_NAME="${ACR_NAME:-}"
IMAGE_LIST="${IMAGE_LIST:-}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
if [ "$DRY_RUN" = false ]; then
  missing=()
  for v in ACR_NAME IMAGE_LIST; do
    [ -n "${!v:-}" ] || missing+=("$v")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "Cannot execute — set these first (see MIGRATION_GUIDE.md): ${missing[*]}" >&2
    exit 1
  fi
  case "$ACR_NAME" in
    *[!a-zA-Z0-9]*) echo "ACR_NAME must be the registry name only (letters and digits)." >&2; exit 1 ;;
  esac
  case "$AWS_REGION" in
    ""|*[!a-z0-9-]*) echo "AWS_REGION must look like us-east-1." >&2; exit 1 ;;
  esac
else
  AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-<AWS_ACCOUNT_ID>}"
  ACR_NAME="${ACR_NAME:-<ACR_NAME>}"
  IMAGE_LIST="${IMAGE_LIST:-example/app:latest}" # preview value only
fi
# Validate the whole list before any login or copy, so a bad entry leaves nothing half copied.
failures=0
for IMAGE in $IMAGE_LIST; do
  case "$IMAGE" in
    *@*) echo "FAILED: $IMAGE uses a digest; use repository:tag." >&2; failures=$((failures + 1)) ;;
    *:*) ;;
    *) echo "FAILED: $IMAGE needs an explicit repository:tag." >&2; failures=$((failures + 1)) ;;
  esac
done
if [ "$failures" -gt 0 ]; then
  echo "Image list errors: $failures. Fix IMAGE_LIST and rerun." >&2
  exit 1
fi
if [ "$DRY_RUN" = false ] && [ -z "$AWS_ACCOUNT_ID" ]; then
  AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
fi
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-$ACR_NAME.azurecr.io}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
if [ "$DRY_RUN" = false ]; then
  case "$AWS_ACCOUNT_ID" in
    ""|*[!0-9]*) echo "AWS_ACCOUNT_ID must be the 12-digit account ID." >&2; exit 1 ;;
  esac
  [ "${#AWS_ACCOUNT_ID}" -eq 12 ] || { echo "AWS_ACCOUNT_ID must be the 12-digit account ID." >&2; exit 1; }
  case "$ACR_LOGIN_SERVER" in
    ""|-*|*[!a-zA-Z0-9.-]*) echo "ACR_LOGIN_SERVER must be a registry host name such as myregistry.azurecr.io." >&2; exit 1 ;;
  esac
  case "$ACR_LOGIN_SERVER" in
    "$ACR_NAME".*) ;;
    *) echo "ACR_LOGIN_SERVER must start with $ACR_NAME. (the registry that az acr login signs in to)." >&2; exit 1 ;;
  esac
  case "$IMAGE_PLATFORM" in
    ""|-*|*[!a-z0-9/._-]*) echo "IMAGE_PLATFORM must look like linux/amd64." >&2; exit 1 ;;
  esac
fi
LOGGED_IN=false
cleanup() {
  if [ "$LOGGED_IN" = true ]; then
    docker logout "$ACR_LOGIN_SERVER" >/dev/null 2>&1 || true
    docker logout "$ECR_REGISTRY" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
if [ "$DRY_RUN" = false ]; then
  LOGGED_IN=true
  az acr login --name "$ACR_NAME"
  aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"
fi
for IMAGE in $IMAGE_LIST; do
  REPO="${IMAGE%:*}"
  TAG="${IMAGE##*:}"
  if [ "$DRY_RUN" = true ]; then
    log "[DRY RUN] Would copy $ACR_LOGIN_SERVER/$IMAGE to $ECR_REGISTRY/$REPO:$TAG"
  else
    if ! aws ecr describe-repositories --region "$AWS_REGION" --repository-names "$REPO" >/dev/null 2>&1; then
      aws ecr create-repository --region "$AWS_REGION" --repository-name "$REPO" \
        --image-scanning-configuration scanOnPush=true >/dev/null
    fi
    log "Copying $IMAGE"
    docker pull --platform "$IMAGE_PLATFORM" "$ACR_LOGIN_SERVER/$IMAGE"
    docker tag "$ACR_LOGIN_SERVER/$IMAGE" "$ECR_REGISTRY/$REPO:$TAG"
    docker push "$ECR_REGISTRY/$REPO:$TAG"
  fi
done
echo "=== Verification ==="
if [ "$DRY_RUN" = false ]; then
  for IMAGE in $IMAGE_LIST; do
    aws ecr describe-images --region "$AWS_REGION" --repository-name "${IMAGE%:*}" --image-ids "imageTag=${IMAGE##*:}" >/dev/null
  done
  log "All listed image tags are present in ECR (presence only; digests were not compared)."
fi
```

The script copies one platform of each image (`IMAGE_PLATFORM`, default `linux/amd64`, the
x86_64 default of this skill). It does not copy a multi-architecture manifest list: for that
the operator chooses a registry-to-registry copy tool that preserves the manifest list (for
example `skopeo copy --all` or `docker buildx imagetools create`; confirm the options in the
tool's current documentation). The script does not rewrite image references in the
application or in Terraform. Say all of this in the guide.

**Ordering with Terraform.** Run `terraform apply` first, then `03`. The script creates a
repository only when Terraform did not already create it. It signs out of both registries
when it exits.

### 04-migrate-secrets.sh (only if has_secrets)
Copies named Key Vault secrets into AWS Secrets Manager. Dry-run must not read any secret
value or call `az`. At `--execute`, each value goes through a restricted file and never into
a shell variable, an argument, the log or the screen.

```bash
# Secrets migration: Azure Key Vault → AWS Secrets Manager
# Usage: ./04-migrate-secrets.sh [--execute]
# Inputs: KEY_VAULT_NAME, SECRET_NAMES (space-separated), AWS_REGION
# Run terraform apply first. Each SECRET_NAMES entry is both the Key Vault secret name and the
# AWS secret name: the infra fragment names each Secrets Manager secret exactly as its Key
# Vault secret (see the secret_names terraform output).
set -f # A * in SECRET_NAMES must never expand to file names in the caller's directory.
AWS_REGION="${AWS_REGION:-us-east-1}" # Replace the default with design_constraints.target_region.value.
KEY_VAULT_NAME="${KEY_VAULT_NAME:-}"
SECRET_NAMES="${SECRET_NAMES:-}"
SECRET_DIR=""
cleanup() { [ -z "$SECRET_DIR" ] || rm -rf "$SECRET_DIR"; }
trap cleanup EXIT
if [ "$DRY_RUN" = false ]; then
  missing=()
  for v in KEY_VAULT_NAME SECRET_NAMES; do
    [ -n "${!v:-}" ] || missing+=("$v")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "Cannot execute — set these first (see MIGRATION_GUIDE.md): ${missing[*]}" >&2
    exit 1
  fi
  case "$AWS_REGION" in
    ""|*[!a-z0-9-]*) echo "AWS_REGION must look like us-east-1." >&2; exit 1 ;;
  esac
  for SECRET_NAME in $SECRET_NAMES; do
    case "$SECRET_NAME" in
      ""|-*|*[!a-zA-Z0-9/_+=.@-]*) echo "Unsupported secret name: $SECRET_NAME" >&2; exit 1 ;;
    esac
    # Secrets Manager adds a hyphen and six random characters to the ARN of a secret.
    case "$SECRET_NAME" in
      *-??????) echo "WARNING: $SECRET_NAME ends with a hyphen and six characters; searching for it by partial ARN can match the wrong secret." >&2 ;;
    esac
  done
fi
for SECRET_NAME in ${SECRET_NAMES:-<secret-name>}; do
  if [ "$DRY_RUN" = true ]; then
    log "[DRY RUN] Would copy Key Vault secret $SECRET_NAME to AWS Secrets Manager (value not read)."
  else
    SECRET_DIR=$(mktemp -d "${TMPDIR:-/tmp}/azure-migration-secret.XXXXXX")
    chmod 700 "$SECRET_DIR"
    SECRET_FILE="$SECRET_DIR/value"
    az keyvault secret download --vault-name "$KEY_VAULT_NAME" --name "$SECRET_NAME" --file "$SECRET_FILE" --encoding utf-8 >/dev/null
    chmod 600 "$SECRET_FILE"
    if aws secretsmanager describe-secret --region "$AWS_REGION" --secret-id "$SECRET_NAME" >/dev/null 2>&1; then
      aws secretsmanager put-secret-value --region "$AWS_REGION" --secret-id "$SECRET_NAME" \
        --secret-string "file://$SECRET_FILE" >/dev/null
    else
      aws secretsmanager create-secret --region "$AWS_REGION" --name "$SECRET_NAME" \
        --secret-string "file://$SECRET_FILE" \
        --tags Key=MigrationSource,Value=azure-key-vault >/dev/null
    fi
    rm -rf "$SECRET_DIR"
    SECRET_DIR=""
    log "Copied secret $SECRET_NAME"
  fi
done
echo "=== Verification ==="
if [ "$DRY_RUN" = false ]; then
  for SECRET_NAME in $SECRET_NAMES; do
    aws secretsmanager describe-secret --region "$AWS_REGION" --secret-id "$SECRET_NAME" >/dev/null
  done
  log "All listed secrets exist in Secrets Manager. Values were not compared."
fi
```

The operator must still check that each application reads the new secret by name. Key Vault
keys and certificates are not copied by this script; list them in the guide as manual work.

**Ordering with Terraform.** Run `terraform apply` first. Set each `SECRET_NAMES` entry to the
secret name from `terraform output secret_names`. The infra fragment names each Secrets
Manager secret exactly as its Key Vault secret, so one name serves both sides, and the script
writes a new version of that existing secret. The infra fragment's `aws_secretsmanager_secret_version` carries
`lifecycle { ignore_changes = [secret_string] }`, so the next `terraform apply` does not
restore the placeholder. Say so in the guide.

A secret name uses letters, digits and `/_+=.@-` (up to 512 characters), cannot start with
`-`, and should not end with a hyphen followed by six characters (for example `db-secret`):
Secrets Manager appends a hyphen and six random characters to a secret's ARN, so a name that
ends that way is confusing to find by partial ARN. The script rejects a leading `-` and warns
about the hyphen-and-six ending without stopping.

### 05-validate-migration.sh (always)
Inventory checks only. Include only the sections whose Step 1 flag is true; omit the rest
(do not comment them out). Set the `AWS_REGION` default from `design_constraints.target_region.value`
and pass `--region "$AWS_REGION"` to every regional command, because the caller's default
region may differ. Names that Terraform computes (ECS cluster, EKS cluster, S3 bucket) are
required inputs read from `terraform output`; never guess them from the project name. When the
name is known from `aws_config` at generation time, set it as the variable's default.

```bash
#!/usr/bin/env bash
set -euo pipefail
# Post-migration validation
# Usage: ./05-validate-migration.sh   (reads only; takes no argument)
[ "$#" -eq 0 ] || { echo "Usage: $0" >&2; exit 2; }
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MIGRATION_DIR=$(dirname "$SCRIPT_DIR")
AWS_REGION="${AWS_REGION:-us-east-1}" # Replace the default with design_constraints.target_region.value.
failures=0
check() {
  if "$@"; then
    return 0
  else
    echo "FAILED: $1 $2" >&2
    failures=$((failures + 1))
  fi
}
echo "=== Migration Inventory Checks ==="
echo "--- Terraform Resources ---"
check terraform -chdir="$MIGRATION_DIR/terraform" state list

# --- Include ONLY if ECS present ---
ECS_CLUSTER_NAME="${ECS_CLUSTER_NAME:-}"
echo "--- ECS Services ---"
if [ -n "$ECS_CLUSTER_NAME" ]; then
  check aws ecs list-services --region "$AWS_REGION" --cluster "$ECS_CLUSTER_NAME" --query 'serviceArns' --output table
else
  echo "FAILED: set ECS_CLUSTER_NAME to the generated cluster name." >&2
  failures=$((failures + 1))
fi

# --- Include ONLY if EKS present ---
EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:-}"
echo "--- EKS Cluster ---"
if [ -n "$EKS_CLUSTER_NAME" ]; then
  check aws eks describe-cluster --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME" --query 'cluster.{Name:name,Status:status}' --output table
else
  echo "FAILED: set EKS_CLUSTER_NAME to the generated cluster name." >&2
  failures=$((failures + 1))
fi

# --- Include ONLY if Elastic Beanstalk present ---
echo "--- Elastic Beanstalk Environments ---"
check aws elasticbeanstalk describe-environments --region "$AWS_REGION" --query 'Environments[].{Env:EnvironmentName,Status:Status,Health:Health}' --output table

# --- Include ONLY if Lambda present ---
echo "--- Lambda Functions ---"
check aws lambda list-functions --region "$AWS_REGION" --query 'Functions[].{Name:FunctionName,State:State}' --output table

# --- Include ONLY if RDS present ---
echo "--- RDS Instances ---"
check aws rds describe-db-instances --region "$AWS_REGION" --query 'DBInstances[].{ID:DBInstanceIdentifier,Status:DBInstanceStatus,Endpoint:Endpoint.Address}' --output table

# --- Include ONLY if ECR present ---
echo "--- ECR Repositories ---"
check aws ecr describe-repositories --region "$AWS_REGION" --query 'repositories[].repositoryName' --output table

# --- Include ONLY if S3 present ---
echo "--- S3 Buckets ---"
if [ -n "${S3_BUCKET:-}" ]; then
  check aws s3api head-bucket --region "$AWS_REGION" --bucket "$S3_BUCKET"
else
  echo "FAILED: set S3_BUCKET to the generated bucket name." >&2
  failures=$((failures + 1))
fi

# --- Include ONLY if Secrets Manager present ---
echo "--- Secrets Manager ---"
check aws secretsmanager list-secrets --region "$AWS_REGION" --query 'SecretList[].Name' --output table

if [ "$failures" -gt 0 ]; then
  echo "Inventory checks failed: $failures. Do not proceed to cutover." >&2
  exit 1
fi
echo "Inventory commands succeeded. This does not establish application health or data integrity."
echo "Before cutover, run application-level health checks and compare source/target data."
```

## Step 3: Self-check

1. Every script uses `set -euo pipefail`. Every script except 05 defaults to dry-run and
   exits 2 on an unknown argument; 05 exits 2 on any argument. Every script that takes
   inputs lists all missing inputs at `--execute`.
2. No script prints a secret or a connection URI with a password, and dry-run reads no
   secret value.
3. The data script emits one offline-copy path for PostgreSQL or MySQL, or a named HOLD
   (`DMS_NOT_IMPLEMENTED`, `ENGINE_NOT_SUPPORTED`, `CUTOVER_UNCONFIRMED`). It never claims
   replication, a lag gate or a delta sync.
4. No script was run. Generate writes the files and stops.

## Phase completion
Report the files generated, using only categories detected in Step 1:

```text
Resource categories detected: [list]
Generated migration scripts:
- scripts/01-validate-prerequisites.sh
- scripts/02-migrate-data.sh            # only if has_database (state the branch or HOLD code)
- scripts/03-migrate-containers.sh      # only if has_containers
- scripts/04-migrate-secrets.sh         # only if has_secrets
- scripts/05-validate-migration.sh
```

Do not update `.phase-status.json`; `generate.md` owns phase completion.

## Status — implemented (build step: Generate)
Implemented, mirroring gcp-to-aws's `generate-artifacts-scripts.md`. The data script has an
offline copy for PostgreSQL and MySQL Flexible Server and named HOLDs for `dms`, unsupported
engines and an unconfirmed cutover. **No replication workflow is implemented or tested.**
