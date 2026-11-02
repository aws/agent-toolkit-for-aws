# Generate Phase: Migration Script Generation

> Loaded by generate.md after generate-artifacts-infra.md completes (terraform files generated).

**Execute ALL steps in order. Do not skip or optimize.**

## Overview

Transform the migration plan (`generation-infra.json`) into numbered migration scripts for data, container, secrets, and validation tasks.

**Outputs:**

- `scripts/` directory — Numbered migration scripts for data and service migration

## Prerequisites

Read the following artifacts from `$MIGRATION_DIR/`:

- `aws-design.json` (REQUIRED) — AWS architecture design with cluster-level resource mappings
- `generation-infra.json` (REQUIRED) — Migration plan with timeline and service assignments
- `preferences.json` (REQUIRED) — User preferences including target region, sizing, compliance

If any REQUIRED file is missing: **STOP**. Output: "Missing required artifact: [filename]. Complete the prior phase that produces it."

## Step 1: Detect Resource Categories

Scan `aws-design.json` clusters[].resources[] to determine which resource categories exist.
Set boolean flags for downstream script generation:

- **has_databases**: true if ANY resource has `aws_service` containing "RDS", "Aurora", "DynamoDB",
  "ElastiCache", "Redshift" OR `gcp_type` starting with `google_sql_`, `google_firestore_`,
  `google_bigtable_`, `google_redis_` (NOT `google_bigquery_` — BigQuery is specialist-deferred
  and carries no automated data-migration steps; see `has_bigquery`)
- **has_bigquery**: true if ANY resource has `gcp_type` starting with `google_bigquery_`
  OR `aws_service` = "Deferred — specialist engagement"
- **has_storage**: true if ANY resource has `aws_service` = "S3" OR `gcp_type` = `google_storage_bucket`
- **has_containers**: true if ANY resource has `aws_service` containing "Fargate", "ECS", "EKS", or "Elastic Beanstalk"
  OR `gcp_type` starting with `google_cloud_run_`, `google_container_cluster`
- **has_secrets**: true if ANY resource has `aws_service` containing "Secrets Manager"
  OR `gcp_type` starting with `google_secret_manager_`
- **has_data_migration**: has_databases OR has_storage OR has_bigquery (used for script 02)

Report detected categories to user: "Resource categories detected: [list active flags]"

## Output Structure

Scripts 02-04 are generated **only** when the corresponding resource categories are detected:

```
$MIGRATION_DIR/
├── scripts/
│   ├── 01-validate-prerequisites.sh          # Always
│   ├── 02-migrate-data.sh                    # Only if has_data_migration
│   ├── 03-migrate-containers.sh              # Only if has_containers
│   ├── 04-migrate-secrets.sh                 # Only if has_secrets
│   └── 05-validate-migration.sh              # Always (adapts checks)
```

## Step 2: Generate Migration Scripts

### Script Rules

- Every script defaults to **dry-run mode** — requires `--execute` flag to make changes
- Every script includes a verification step after execution. An inventory listing is not a data-integrity check; a failed or unavailable required check MUST return nonzero and keep cutover on hold.
- Scripts are numbered for execution order
- Scripts use `set -euo pipefail` for safety. Counter updates MUST use `count=$((count + 1))` or an explicit successful return. `((count++))` returns failure when the old count is zero and can abort the first prerequisite check.
- Scripts log all actions to `$MIGRATION_DIR/logs/`
- Preserve supplied environment variables with `${NAME:-}` instead of assigning empty strings over them. Do not print passwords or full database connection URIs.
- Resolve paths from the script's directory. Do not change the caller's working directory and then reuse a relative migration path.
- An ordinary `pg_dump`/`pg_restore` or `pgcopydb copy db` invocation is a single full copy, not CDC or a final delta sync. You MUST generate an offline-copy plan with source and target application writes frozen for the entire copy and verification window, or mark online migration/cutover **HOLD — replication workflow not implemented**. You MUST NOT emit `--final-sync`, invent a replication-lag gate, or promise a second full copy will apply only changes.
- A source write freeze must stop application writes while keeping database reads available. Do not use Cloud SQL `--activation-policy=NEVER` for a write freeze: it stops the instance and prevents the subsequent copy from connecting.
- **Fail fast on unset fill-ins at `--execute`:** every script that reads user-supplied env vars (`SOURCE_HOST`, `TARGET_DB_PASSWORD`, `ALB_DNS`, …) checks them at the top of the execute path and exits listing ALL missing ones at once — never fails midway on the first empty var after work has started. Dry-run mode runs without them (printing which are unset). Pattern (adjust the `for v in …` list to match **this** script's required env vars — it is a template, not a universal constant):

  ```bash
  if [ "$DRY_RUN" = false ]; then
    missing=()
    # Adjust the list below to match this script's required env vars
    for v in SOURCE_HOST TARGET_HOST SOURCE_DB_PASSWORD TARGET_DB_PASSWORD DATABASE_NAME; do
      [ -z "${!v:-}" ] && missing+=("$v")
    done
    if [ ${#missing[@]} -gt 0 ]; then
      echo "Cannot execute — set these first (see MIGRATION_GUIDE.md fill-in checklist): ${missing[*]}"
      exit 1
    fi
  fi
  ```

### 01-validate-prerequisites.sh

You MUST emit the following safe counter/argument structure and specialize the checks to the actual targets. With no argument, check only local tool availability and print the planned read-only cloud checks. `--execute` authorizes those checks; this prerequisite script does not freeze writes, modify infrastructure, or prove every IAM permission.

```bash
#!/usr/bin/env bash
set -euo pipefail
# Prerequisite checks: no cloud calls in the default preview.
DRY_RUN=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
case "${1:-}" in
  "") ;;
  --execute) DRY_RUN=false ;;
  *) echo "Usage: $0 [--execute]" >&2; exit 2 ;;
esac
passed=0
failed=0
check() {
  if "$@"; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    echo "FAILED prerequisite: $1" >&2
  fi
  return 0
}
for tool in aws gcloud terraform jq; do
  check command -v "$tool"
done
if [ "$DRY_RUN" = false ]; then
  check aws sts get-caller-identity
  # Add only read-only target-specific access/connectivity checks here.
else
  echo "DRY RUN: cloud identity, target access and connectivity checks are not run."
fi
printf "Prerequisites: %s passed, %s failed\n" "$passed" "$failed"
[ "$failed" -eq 0 ] || exit 1
```

Verify all prerequisites before migration:

- AWS CLI configured and authenticated
- Required IAM permissions: check the precise read operations used by this plan and list any mutation permissions that remain unverified
- Target VPC and subnets exist (Terraform applied)
- GCP connectivity established (for data transfer)
- Required tools installed (aws, gcloud, terraform, jq)

### 02-migrate-data.sh — IF has_data_migration

**Skip this script entirely if `has_data_migration` is false.**

Based on database and storage resources in `aws-design.json`:

**Script preamble** — emit FIRST, whenever this script is generated (any subsection below
active). The shebang, failure mode, and dry-run plumbing are not gated on any single resource
flag: a BigQuery-only project generates only the deferral notice below, and that script still
has to satisfy Script Quality Rule 1 (`set -euo pipefail`):

```bash
#!/usr/bin/env bash
set -euo pipefail
# Data migration
# Usage: ./02-migrate-data.sh [--execute]

DRY_RUN=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
case "${1:-}" in
  "") ;;
  --execute) DRY_RUN=false ;;
  *) echo "Usage: $0 [--execute]" >&2; exit 2 ;;
esac
echo "Mode: $([ "$DRY_RUN" = true ] && echo 'DRY RUN' || echo 'EXECUTE')"
```

**Cloud SQL PostgreSQL to PostgreSQL RDS/Aurora** — include only when both the source
and target engines are explicitly PostgreSQL. `has_databases` alone does not establish
engine compatibility. Unknown engines and other database mappings use the HOLD path below:

Read `preferences.json` → `design_constraints.db_size.value` to select the migration tool:

**Inventory cross-check (before selecting the tool):** If `gcp-resource-inventory.json` has a `google_sql_database_instance` with a disk size (`config.disk_size_gb` or legacy variants), map it to the Q13b band and compare against `db_size.value`. Terraform disk size is **allocated capacity — an upper bound on actual data**, so the comparison is asymmetric:

- **`db_size.value` band is LARGER than the allocated band** — data cannot exceed its allocation, UNLESS the disk can autoresize. Branch on `config.disk_autoresize` (extracted by Discover only when explicitly set in HCL):
  - Explicitly `true` — the allocation is a starting point, not a cap; the disk may have grown since the Terraform was written. Keep the user's answer; no warning. Note it in the script header comment (`# db_size source: user answer [value]; terraform disk_size_gb=[N] is autoresize-enabled, not a cap`).
  - Explicitly `false`, or absent — treat the allocation as the effective bound. Warn and use the allocated band:

  > **Database size inconsistency:** Clarify recorded `db_size: [value]` but Terraform only allocates `disk_size_gb: [N]` ([band]). Using the allocated band for tool selection — say "use my answer instead" if the disk has grown since this Terraform was written (e.g. autoresize is enabled outside this Terraform).

- **`db_size.value` band is SMALLER than the allocated band** — plausible (actual data below allocation is the normal case). Keep the user's answer; no warning.

Record any override in the script header comment (`# db_size source: terraform disk_size_gb=[N] (allocated), overrode preferences value [value]`).

**Runtime size measurement (emit for supported PostgreSQL copy paths only):** Because neither the Q13b answer nor the allocated disk measures actual data, the generated script must measure it before migrating. Emit this block in the shared preamble (after connection variables), tailoring the advisory to the tool the script was generated with:

```bash
# Allocated disk is an upper bound, not a measurement — check actual data size first.
if [ "$DRY_RUN" = false ] && [ -n "$SOURCE_HOST" ] && [ -n "${SOURCE_DB_PASSWORD:-}" ]; then
  ACTUAL_GB=$(PGPASSWORD="$SOURCE_DB_PASSWORD" psql -X --no-password -v ON_ERROR_STOP=1 -h "$SOURCE_HOST" -p "${SOURCE_PORT:-5432}" -U "${SOURCE_DB_USER:-postgres}" -d "$DATABASE_NAME" -At \
    -c "SELECT ceil(pg_database_size(current_database()) / 1024.0^3)")
  echo "Actual database size: ${ACTUAL_GB} GB (this script was generated for the [band] band)"
else
  ACTUAL_GB=""
  echo "SKIP: actual-size check runs in execute mode with source credentials."
fi
```

Follow it with ONE tool-appropriate advisory branch:

- pgcopydb script: `if [ -n "$ACTUAL_GB" ] && [ "$ACTUAL_GB" -lt 10 ]; then echo "NOTE: actual data is under 10 GB — plain pg_dump/pg_restore would be simpler (no pgcopydb install). Consider regenerating."; fi`
- pg_dump script: `if [ -n "$ACTUAL_GB" ] && [ "$ACTUAL_GB" -ge 10 ]; then echo "WARNING: actual data is ${ACTUAL_GB} GB — pg_dump may exceed your maintenance window above 10 GB. Regenerate with pgcopydb before proceeding."; exit 1; fi` (hard stop: undersized tooling is the dangerous direction; oversized is merely inconvenient. The query runs only in execute mode; the first dry run is offline. The operator must fill in the connection inputs before `--execute`)

- `"<10GB"` → use **pg_dump/pg_restore**
- `"10-100GB"` or `"100-500GB"` → use **pgcopydb** (parallel single copy; this template does not configure CDC)
- `">500GB"` → **HOLD** for a reviewed migration workflow (DMS full-load + CDC may be appropriate, but this template does not implement it)
- `"unknown"` → **HOLD** until actual data size and the permitted maintenance window are verified

Generate the script with conditional branches based on `db_size`:

```bash
# Cloud SQL → RDS data migration
# Tool selection based on database size (preferences.json design_constraints.db_size.value):
# <10GB: pg_dump/pg_restore
# 10-500GB: pgcopydb (parallel single copy; benchmark the maintenance window)
# >500GB: HOLD for a separately reviewed migration workflow
# unknown: HOLD until actual size and the permitted maintenance window are verified
# Note: band comes from Q13b / allocated disk (an upper bound) — the preamble below
# measures ACTUAL data size and warns (or stops) if this tool choice doesn't fit it.

echo "=== Database Migration: Cloud SQL → RDS ==="

SOURCE_HOST="${SOURCE_HOST:-}" # Cloud SQL DNS hostname or IPv4 address, WITHOUT a port
TARGET_HOST="${TARGET_HOST:-}" # Matching RDS address output (not endpoint containing :port)
SOURCE_PORT="${SOURCE_PORT:-5432}"
TARGET_PORT="${TARGET_PORT:-5432}"
SOURCE_DB_USER="${SOURCE_DB_USER:-postgres}"
TARGET_DB_USER="${TARGET_DB_USER:-postgres}"
DATABASE_NAME="${DATABASE_NAME:-}" # Exact database name; must exist on the target
```

You MUST emit this execution guard after the missing-input check and before any database
connection. It implements a bounded offline copy. Acknowledgements must refer to the
write-freeze mechanism and evidence in the guide; a script cannot infer that all writers
are stopped. Generate `verify-database-integrity.sh` only if the discovered schema permits
a complete, tested verifier. Otherwise require an operator-supplied `DATA_VERIFIER` and
leave execution/cutover on HOLD until it exists. The verifier MUST independently compare
source and target table inventories, exact row counts, deterministic content checksums,
and required sequence/application invariants; mismatch, missing coverage or query failure
MUST return nonzero. Equal row counts alone do not establish equal data.

**Generation readiness gate:** before presenting the scripts as executable, inspect the
actual verifier file, run it with mismatch and query-failure fixtures, and record the
covered tables, checksum strategy and invariant coverage. An executable bit, a zero exit
code from an echo/no-op, or an operator assertion is not verification. If this evidence is
unavailable, keep the `DATA_VERIFIER` requirement unresolved, explicitly label data
migration **unfinished / HOLD** in the guide, README, HTML report and generation plan,
and do not claim the stack is ready to migrate or cut over. Generating documentation or
passing an artifact inventory check does not satisfy this gate.

```bash
# Offline-copy guard and password-free connection arguments.
# Default verifier path resolves from this script, not the caller's directory.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DATA_VERIFIER="${DATA_VERIFIER:-$SCRIPT_DIR/verify-database-integrity.sh}"
if [ "$DRY_RUN" = false ]; then
  if [ "${SOURCE_WRITES_FROZEN:-}" != yes ] || [ "${TARGET_WRITES_FROZEN:-}" != yes ]; then
    echo "HOLD: freeze all source and target application writers; preserve database reads." >&2
    exit 1
  fi
  if [ ! -f "$DATA_VERIFIER" ] || [ ! -x "$DATA_VERIFIER" ]; then
    echo "HOLD: DATA_VERIFIER must name a reviewed executable data-integrity check." >&2
    exit 1
  fi
  for name in SOURCE_HOST TARGET_HOST; do
    value="${!name}"
    case "$value" in
      ""|*[!a-zA-Z0-9._-]*)
        echo "HOLD: $name must be a DNS hostname or IPv4 address without :port or a URI." >&2
        exit 1 ;;
    esac
  done
  for name in SOURCE_PORT TARGET_PORT; do
    value="${!name}"
    case "$value" in
      ""|*[!0-9]*) echo "HOLD: $name must be an integer TCP port." >&2; exit 1 ;;
    esac
    if [ "${#value}" -gt 5 ] || [ "$((10#$value))" -lt 1 ] || [ "$((10#$value))" -gt 65535 ]; then
      echo "HOLD: $name must be between 1 and 65535." >&2
      exit 1
    fi
    printf -v "$name" '%s' "$((10#$value))"
  done
  if [ "$SOURCE_HOST:$SOURCE_PORT:$DATABASE_NAME" = "$TARGET_HOST:$TARGET_PORT:$DATABASE_NAME" ]; then
    echo "HOLD: source and target must be different databases." >&2
    exit 1
  fi
  # psql/pg_dump treat a -d value containing '=' or a URI prefix as a connection string.
  case "$DATABASE_NAME" in
    *=*|postgresql://*|postgres://*)
      echo "HOLD: this database name needs a reviewed explicit-connection variant." >&2
      exit 1 ;;
  esac
  # libpq password files are line-oriented. Reject unsupported newlines rather than corrupting them.
  for name in DATABASE_NAME SOURCE_DB_USER TARGET_DB_USER SOURCE_DB_PASSWORD TARGET_DB_PASSWORD; do
    value="${!name}"
    case "$value" in
      *$'\n'*|*$'\r'*) echo "HOLD: multiline $name needs a separately reviewed authentication setup." >&2; exit 1 ;;
    esac
  done
  export PGSSLMODE="${PGSSLMODE:-require}"
  case "$PGSSLMODE" in
    require|verify-ca|verify-full) ;;
    *) echo "HOLD: PGSSLMODE must require TLS (require, verify-ca or verify-full)." >&2; exit 1 ;;
  esac
  unset PGPASSWORD # A caller's global password must not override the per-host password file.
  # Quote libpq keyword values; passwords never enter command-line arguments or logged URIs.
  conn_value() {
    local value="$1" char i
    printf "'"
    for ((i = 0; i < ${#value}; i = i + 1)); do
      char="${value:i:1}"
      case "$char" in
        "\\"|"'") printf '\\%s' "$char" ;;
        *) printf '%s' "$char" ;;
      esac
    done
    printf "'"
  }
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
  SOURCE_CONNINFO="host=$(conn_value "$SOURCE_HOST") port=$SOURCE_PORT user=$(conn_value "$SOURCE_DB_USER") dbname=$(conn_value "$DATABASE_NAME") sslmode=$(conn_value "$PGSSLMODE")"
  TARGET_CONNINFO="host=$(conn_value "$TARGET_HOST") port=$TARGET_PORT user=$(conn_value "$TARGET_DB_USER") dbname=$(conn_value "$DATABASE_NAME") sslmode=$(conn_value "$PGSSLMODE")"
  DB_AUTH_DIR=$(mktemp -d "${TMPDIR:-/tmp}/gcp-migration-auth.XXXXXX")
  chmod 700 "$DB_AUTH_DIR"
  export PGPASSFILE="$DB_AUTH_DIR/pgpass"
  trap 'rm -rf "$DB_AUTH_DIR"' EXIT
  (umask 077
    {
      printf '%s:%s:%s:%s:%s\n' "$(pass_field "$SOURCE_HOST")" "$SOURCE_PORT" "$(pass_field "$DATABASE_NAME")" "$(pass_field "$SOURCE_DB_USER")" "$(pass_field "$SOURCE_DB_PASSWORD")"
      printf '%s:%s:%s:%s:%s\n' "$(pass_field "$TARGET_HOST")" "$TARGET_PORT" "$(pass_field "$DATABASE_NAME")" "$(pass_field "$TARGET_DB_USER")" "$(pass_field "$TARGET_DB_PASSWORD")"
    } > "$PGPASSFILE"
  )
fi
```

This bounded template supports DNS/IPv4 inputs. For IPv6, different source/target database
names, database names interpreted by `psql -d` as connection strings, IAM database
authentication, or a required client-certificate setup, generate and
test the explicit connection variant before allowing execute. Do not guess by splitting
an endpoint string on `:`. Set per-connection CA verification when the environment supplies
it; do not weaken an existing TLS requirement to make the copy succeed.

Then emit ONE of the following tool-specific blocks based on `db_size`:

**If `db_size` is `"<10GB"`** — emit pg_dump block:

```bash
# Tool: pg_dump/pg_restore (database < 10GB)
if [ "$DRY_RUN" = true ]; then
  echo "[DRY RUN] Would export from Cloud SQL using pg_dump: $DATABASE_NAME"
  echo "[DRY RUN] Would import to RDS using pg_restore: $TARGET_HOST"
else
  echo "Exporting from Cloud SQL with pg_dump..."
  DUMP_FILE=$(mktemp "${TMPDIR:-/tmp}/gcp-migration.XXXXXX")
  chmod 600 "$DUMP_FILE"
  trap 'rm -f "${DUMP_FILE:-}"; if [ -n "${DB_AUTH_DIR:-}" ]; then rm -rf "$DB_AUTH_DIR"; fi' EXIT
  pg_dump --no-password \
    -h "$SOURCE_HOST" -p "${SOURCE_PORT:-5432}" -U "${SOURCE_DB_USER:-postgres}" -d "$DATABASE_NAME" \
    -Fc -f "$DUMP_FILE"
  echo "Importing to RDS with pg_restore..."
  pg_restore --no-password --exit-on-error \
    -h "$TARGET_HOST" -p "${TARGET_PORT:-5432}" -U "${TARGET_DB_USER:-postgres}" -d "$DATABASE_NAME" \
    -Fc "$DUMP_FILE"
  rm -f "$DUMP_FILE"
fi
```

**If `db_size` is `"10-100GB"` or `"100-500GB"`** — emit pgcopydb block:

```bash
# Tool: pgcopydb (database 10GB–500GB — parallel offline copy)
# Requires: pgcopydb installed; source/target writers frozen throughout copy and verification
# See: https://pgcopydb.readthedocs.io/
if [ "$DRY_RUN" = true ]; then
  echo "[DRY RUN] Would copy database using pgcopydb: $DATABASE_NAME"
  echo "[DRY RUN] Source: $SOURCE_HOST → Target: $TARGET_HOST"
else
  echo "Copying database with pgcopydb (parallel)..."
  pgcopydb copy db \
    --source "$SOURCE_CONNINFO" \
    --target "$TARGET_CONNINFO" \
    --table-jobs 4 \
    --index-jobs 4
fi
```

**If `db_size` is `">500GB"` or `"unknown"`** — emit a hold, not an
unimplemented replication workflow. Emit only the argument-parser preamble and the HOLD
block for these bands; do not emit connection setup, measurement or a copy block.
A specialist may produce a separate reviewed DMS
full-load + CDC plan with source privileges, replication configuration, readiness checks,
lag measurement, cutover and rollback. This template does not provide those operations.

```bash
# Large/unknown database: migration requires a separately reviewed workflow.
echo "HOLD: size and migration-window requirements need a reviewed data migration plan." >&2
[ "$DRY_RUN" = true ] || exit 1
```

For an implemented PostgreSQL copy, append the mandatory verification gate below. The
verifier receives password-free libpq connection strings and the temporary `PGPASSFILE`.
You MUST NOT replace it with an echo, TODO, inventory listing, or row-count-only success.

```bash
# Data-integrity gate: required before either side's writers or cutover are enabled.
if [ "$DRY_RUN" = true ]; then
  echo "DRY RUN: copy is offline; a complete data verifier is required before execution."
else
  if ! "$DATA_VERIFIER" --source "$SOURCE_CONNINFO" --target "$TARGET_CONNINFO"; then
    echo "HOLD: data verification failed. Keep writers frozen and do not cut over." >&2
    exit 1
  fi
  echo "Offline copy and data verification passed. Cutover still requires the guide's release gates."
fi
```

**BigQuery — specialist-deferred (no automated AWS target)** — include only if `has_bigquery`:

Design marked every `google_bigquery_*` resource as **`Deferred — specialist engagement`** with
`no_automated_aws_target: true` (see `references/phases/design/design-infra.md` → BigQuery specialist gate).
Therefore **do not** generate BigQuery export, copy, or load steps, and **do not** name an AWS analytics or
warehouse target (no Athena, Redshift, Glue, EMR, Lake Formation, or a prescribed "data lake on S3").
Emit only the deferral comment block below, followed by the `echo` lines in
`references/shared/bq-assess-next-step.md` → Migration script lines:

```bash
# BigQuery — AWS target deliberately NOT selected
# This plugin does not choose an AWS analytics or warehouse target for BigQuery
# (no Athena/Redshift/Glue/EMR recommendation, and no prescribed data lake on S3).
# Engage your AWS account team and/or a data analytics migration partner before
# data warehouse, lake, SQL analytics, or BI cutover planning — query patterns,
# data volumes, ETL/ELT, and downstream consumers must be assessed by specialists.
# No BigQuery migration steps are generated here by design.
```

**Other database targets (including Firestore → DynamoDB)** — include when detected,
and do not apply the PostgreSQL template to an incompatible source or target. No generic
data adapter is implemented by this fragment; preserve a migration hold:

```bash
# Non-PostgreSQL data migration is not implemented by this template.
echo "HOLD: generate and verify a source/target-specific data migration adapter." >&2
[ "$DRY_RUN" = true ] || exit 1
```

### 03-migrate-containers.sh — IF has_containers

**Skip this script entirely if `has_containers` is false.**

This script has two independent sections; emit each only if its services are present in `aws-design.json`:

- **Shared preamble** — **always emit** (shebang, `DRY_RUN`, account/region). Both sections depend on it, so it must not live inside either one.
- **ECR image migration** — emit if any resource maps to Fargate/ECS/EKS (container images move GCR/Artifact Registry → ECR).
- **Elastic Beanstalk source deploy** — emit if any resource maps to Elastic Beanstalk. **EB does not take a pre-built image from a registry:** for the Docker platform you ship a **source bundle containing the `Dockerfile`** (plus a `Dockerrun.aws.json` only for the pre-built-image case, which this skill does not use) and EB builds the image during deployment; for the language platforms (Python/Node/etc.) you ship the app source. So there is **no ECR push for EB** — do not create an ECR repo for an EB service. The EB section bundles the app source, uploads it to the EB-managed S3 bucket, creates an application version, and deploys it to the environment Terraform provisioned.

Shared preamble (always emitted):

```bash
#!/usr/bin/env bash
set -euo pipefail

# App migration: container images (→ ECR) and/or Elastic Beanstalk source deploy
# Usage: ./03-migrate-containers.sh [--execute]

DRY_RUN=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
case "${1:-}" in
  "") ;;
  --execute) DRY_RUN=false ;;
  *) echo "Usage: $0 [--execute]" >&2; exit 2 ;;
esac

AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
AWS_REGION="${AWS_REGION:-us-east-1}" # Default from preferences.json target_region
if [ -z "$AWS_ACCOUNT_ID" ]; then
  if [ "$DRY_RUN" = true ]; then
    AWS_ACCOUNT_ID="<AWS_ACCOUNT_ID>"
  else
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  fi
fi
```

ECR image migration — GCR/Artifact Registry → ECR (**include ONLY if Fargate/ECS/EKS present**):

```bash
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# TODO: List container images from aws-design.json compute resources
IMAGES=(
  "gcr.io/project/image1:latest"
  # Add more images from your GCP container registry
)

for IMAGE in "${IMAGES[@]}"; do
  IMAGE_NAME=$(echo "$IMAGE" | rev | cut -d'/' -f1 | rev | cut -d':' -f1)
  IMAGE_TAG=$(echo "$IMAGE" | rev | cut -d':' -f1 | rev)

  if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would migrate: $IMAGE → $ECR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
  else
    echo "Creating ECR repository: $IMAGE_NAME"
    aws ecr create-repository --repository-name "$IMAGE_NAME" --region "$AWS_REGION" 2>/dev/null || true

    echo "Pulling from GCR: $IMAGE"
    docker pull "$IMAGE"

    echo "Tagging for ECR: $ECR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
    docker tag "$IMAGE" "$ECR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"

    echo "Pushing to ECR..."
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"
    docker push "$ECR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
  fi
done
```

Elastic Beanstalk source deploy (**include ONLY if an EB environment is in `aws-design.json`**):

```bash
# EB builds the image from your Dockerfile at deploy time (Docker platform) or runs the app
# source directly (language platforms). No ECR push. One deploy per App Engine service → EB env.
# TODO: one entry per EB environment from aws-design.json (eb_application, eb_environment, source_service)
EB_APP="gcp-migration"            # aws_config.eb_application
EB_ENVS=(
  "default"                        # aws_config.eb_environment (one per source_service)
  # "worker"
)
EB_BUCKET="elasticbeanstalk-${AWS_REGION}-${AWS_ACCOUNT_ID}"

for EB_ENV in "${EB_ENVS[@]}"; do
  VERSION_LABEL="${EB_ENV}-$(date -u +%Y%m%d%H%M%S)"   # stamp at run time
  BUNDLE="/tmp/${EB_APP}-${EB_ENV}.zip"
  if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would bundle ./${EB_ENV} (incl. Dockerfile), upload to s3://${EB_BUCKET}, and deploy version ${VERSION_LABEL} to ${EB_APP}/${EB_ENV}"
  else
    echo "Bundling source for ${EB_ENV} (must include Dockerfile for the Docker platform)..."
    ( cd "./${EB_ENV}" && zip -r "$BUNDLE" . -x '*.git*' )
    aws s3 cp "$BUNDLE" "s3://${EB_BUCKET}/${VERSION_LABEL}.zip" --region "$AWS_REGION"
    aws elasticbeanstalk create-application-version --application-name "$EB_APP" \
      --version-label "$VERSION_LABEL" \
      --source-bundle "S3Bucket=${EB_BUCKET},S3Key=${VERSION_LABEL}.zip" --region "$AWS_REGION"
    aws elasticbeanstalk update-environment --application-name "$EB_APP" \
      --environment-name "$EB_ENV" --version-label "$VERSION_LABEL" --region "$AWS_REGION"
  fi
done
```

Verification (always emitted; each line only reports on the sections you included):

```bash
echo "=== Verification ==="
# Include the next two lines only if the ECR section was emitted:
echo "Listing ECR repositories (Fargate/ECS/EKS)..."
if [ "$DRY_RUN" = false ]; then
  aws ecr describe-repositories --region "$AWS_REGION" --query 'repositories[].repositoryName' --output table
fi
# Include the next two lines only if the EB section was emitted:
echo "Listing Elastic Beanstalk environments..."
if [ "$DRY_RUN" = false ]; then
  aws elasticbeanstalk describe-environments --region "$AWS_REGION" --query 'Environments[].{Env:EnvironmentName,Status:Status,Health:Health}' --output table
fi
```

### 04-migrate-secrets.sh — IF has_secrets

**Skip this script entirely if `has_secrets` is false.**

Migrate secrets from GCP Secret Manager to AWS Secrets Manager:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Secrets migration: GCP Secret Manager → AWS Secrets Manager
# Usage: ./04-migrate-secrets.sh [--execute]

DRY_RUN=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--execute]" >&2; exit 2; }
case "${1:-}" in
  "") ;;
  --execute) DRY_RUN=false ;;
  *) echo "Usage: $0 [--execute]" >&2; exit 2 ;;
esac

# TODO: List secrets to migrate
SECRETS=(
  "database-password"
  "api-key"
  # Add more secrets from your GCP project
)

for SECRET_NAME in "${SECRETS[@]}"; do
  if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would migrate secret: $SECRET_NAME"
  else
    echo "Reading secret from GCP: $SECRET_NAME"
    # Write to a restricted temp file — avoids secret values appearing in shell
    # variables, process lists (ps aux), or shell history. Cleaned up on exit.
    TMPFILE=$(mktemp)
    chmod 600 "$TMPFILE"
    trap 'rm -f "$TMPFILE"' EXIT

    gcloud secrets versions access latest --secret="$SECRET_NAME" > "$TMPFILE"

    echo "Creating/updating secret in AWS: $SECRET_NAME"
    aws secretsmanager create-secret \
      --name "$SECRET_NAME" \
      --secret-string "file://$TMPFILE" \
      --tags Key=MigrationSource,Value=gcp-secret-manager 2>/dev/null || \
    aws secretsmanager put-secret-value \
      --secret-id "$SECRET_NAME" \
      --secret-string "file://$TMPFILE"

    rm -f "$TMPFILE"
    trap - EXIT
  fi
done

# Verification
echo "=== Verification ==="
if [ "$DRY_RUN" = false ]; then
  aws secretsmanager list-secrets --query 'SecretList[].Name' --output table
fi
```

### 05-validate-migration.sh

Post-migration validation script. **Always generated**, but adapt checks based on which resource
categories were detected in Step 1. Only include validation sections for resources that exist.
Keep ECS/Fargate and EKS checks separate. For each EKS cluster, populate its
`EKS_CLUSTER_NAME` default from the matching design entry when the name is known.
If Terraform computes the name, require that name as an input from the generated
output; do not assume that the project name is the EKS cluster name.
You MUST set the generated `AWS_REGION` default from
`preferences.json` → `design_constraints.target_region.value` and pass it
explicitly to each regional AWS inventory command. The caller's default region
may differ from the migration's target region.

```bash
#!/usr/bin/env bash
set -euo pipefail

# Post-migration validation
# Usage: ./05-validate-migration.sh

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MIGRATION_DIR=$(dirname "$SCRIPT_DIR")
AWS_REGION="${AWS_REGION:-us-east-1}" # Replace the default with the selected target region.
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

# Check Terraform state (always included)
echo "--- Terraform Resources ---"
check terraform -chdir="$MIGRATION_DIR/terraform" state list

# --- Include ONLY if Fargate/ECS present ---
# Check ECS services
echo "--- ECS Services ---"
check aws ecs list-services --region "$AWS_REGION" --cluster "${PROJECT_NAME:-gcp-migration}" --query 'serviceArns' --output table

# --- Include ONLY if EKS present ---
# Set the default to this cluster's aws_config.cluster_name when known.
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

# --- Include ONLY if has_databases ---
# Check RDS instances
echo "--- RDS Instances ---"
check aws rds describe-db-instances --region "$AWS_REGION" --query 'DBInstances[].{ID:DBInstanceIdentifier,Status:DBInstanceStatus,Endpoint:Endpoint.Address}' --output table

# --- Include ONLY if has_storage ---
# Check S3 buckets
echo "--- S3 Buckets ---"
if [ -n "${S3_BUCKET:-}" ]; then
  check aws s3api head-bucket --region "$AWS_REGION" --bucket "$S3_BUCKET"
else
  echo "FAILED: set S3_BUCKET to the generated bucket name." >&2
  failures=$((failures + 1))
fi

# --- Include ONLY if has_secrets ---
# Check secrets
echo "--- Secrets Manager ---"
check aws secretsmanager list-secrets --region "$AWS_REGION" --query 'SecretList[].Name' --output table

if [ "$failures" -gt 0 ]; then
  echo "Inventory checks failed: $failures. Do not proceed to cutover." >&2
  exit 1
fi
echo "Inventory commands succeeded. This does not establish application health or data integrity."
echo "Before cutover, run application-level health checks and compare source/target data."
```

## Step 3: Self-Check

After generating all scripts, verify the following quality rules:

### Script Quality Rules

1. All scripts use `set -euo pipefail`
2. All scripts default to dry-run mode
3. All scripts include verification steps
4. All scripts are numbered for execution order
5. All TODO markers are clearly marked with context
6. PostgreSQL scripts reject unsupported extra arguments (including `--final-sync`), require documented writer freezes and a complete data verifier, and fail closed on missing evidence. `05` inventory output alone never authorizes database cutover.
7. No script prescribes an AWS analytics or warehouse target for BigQuery (no Athena, Redshift, Glue,
   EMR, Lake Formation, or "data lake on S3", and no `bq extract` / export steps) — BigQuery resources
   carry only the specialist-engagement deferral notice, consistent with `no_automated_aws_target: true`

## Phase Completion

Report the list of generated script files to the parent orchestrator. **Do NOT update `.phase-status.json`** — the parent `generate.md` handles phase completion.

Only list scripts that were actually generated (based on Step 1 resource detection flags):

```
Resource categories detected: [list active flags from Step 1]

Generated migration scripts:
- scripts/01-validate-prerequisites.sh
- scripts/02-migrate-data.sh                    # only if has_data_migration
- scripts/03-migrate-containers.sh              # only if has_containers
- scripts/04-migrate-secrets.sh                 # only if has_secrets
- scripts/05-validate-migration.sh

Total: [N] migration scripts
TODO markers: [N] items requiring manual configuration
Skipped scripts: [list any scripts not generated, with reason]
```
