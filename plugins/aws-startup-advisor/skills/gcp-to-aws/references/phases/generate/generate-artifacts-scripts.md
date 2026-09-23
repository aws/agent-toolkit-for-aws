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
- Every script includes a verification step after execution
- Scripts are numbered for execution order
- Scripts use `set -euo pipefail` for safety
- Scripts log all actions to `$MIGRATION_DIR/logs/`
- **Fail fast on unset fill-ins at `--execute`:** every script that reads user-supplied env vars (`SOURCE_HOST`, `TARGET_DB_PASSWORD`, `ALB_DNS`, …) checks them at the top of the execute path and exits listing ALL missing ones at once — never fails midway on the first empty var after work has started. Dry-run mode runs without them (printing which are unset). Pattern (adjust the `for v in …` list to match **this** script's required env vars — it is a template, not a universal constant):

  ```bash
  if [ "$DRY_RUN" = false ]; then
    missing=()
    # Adjust the list below to match this script's required env vars
    for v in SOURCE_HOST TARGET_HOST TARGET_DB_PASSWORD; do
      [ -z "${!v:-}" ] && missing+=("$v")
    done
    if [ ${#missing[@]} -gt 0 ]; then
      echo "Cannot execute — set these first (see MIGRATION_GUIDE.md fill-in checklist): ${missing[*]}"
      exit 1
    fi
  fi
  ```

### 01-validate-prerequisites.sh

Verify all prerequisites before migration:

- AWS CLI configured and authenticated
- Required IAM permissions present
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
[[ "${1:-}" == "--execute" ]] && DRY_RUN=false
echo "Mode: $([ "$DRY_RUN" = true ] && echo 'DRY RUN' || echo 'EXECUTE')"
```

**Cloud SQL to RDS/Aurora** — include only if `has_databases`:

Read `preferences.json` → `design_constraints.db_size.value` to select the migration tool:

**Inventory cross-check (before selecting the tool):** If `gcp-resource-inventory.json` has a `google_sql_database_instance` with a disk size (`config.disk_size_gb` or legacy variants), map it to the Q13b band and compare against `db_size.value`. Terraform disk size is **allocated capacity — an upper bound on actual data**, so the comparison is asymmetric:

- **`db_size.value` band is LARGER than the allocated band** — data cannot exceed its allocation, UNLESS the disk can autoresize. Branch on `config.disk_autoresize` (extracted by Discover only when explicitly set in HCL):
  - Explicitly `true` — the allocation is a starting point, not a cap; the disk may have grown since the Terraform was written. Keep the user's answer; no warning. Note it in the script header comment (`# db_size source: user answer [value]; terraform disk_size_gb=[N] is autoresize-enabled, not a cap`).
  - Explicitly `false`, or absent — treat the allocation as the effective bound. Warn and use the allocated band:

  > **Database size inconsistency:** Clarify recorded `db_size: [value]` but Terraform only allocates `disk_size_gb: [N]` ([band]). Using the allocated band for tool selection — say "use my answer instead" if the disk has grown since this Terraform was written (e.g. autoresize is enabled outside this Terraform).

- **`db_size.value` band is SMALLER than the allocated band** — plausible (actual data below allocation is the normal case). Keep the user's answer; no warning.

Record any override in the script header comment (`# db_size source: terraform disk_size_gb=[N] (allocated), overrode preferences value [value]`).

**Runtime size measurement (always emit, PostgreSQL path):** Because neither the Q13b answer nor the allocated disk measures actual data, the generated script must measure it before migrating. Emit this block in the shared preamble (after connection variables), tailoring the advisory to the tool the script was generated with:

```bash
# Allocated disk is an upper bound, not a measurement — check actual data size first.
if [ -n "$SOURCE_HOST" ] && [ -n "${SOURCE_DB_PASSWORD:-}" ]; then
  ACTUAL_GB=$(PGPASSWORD="$SOURCE_DB_PASSWORD" psql -h "$SOURCE_HOST" -U postgres -d "$DATABASE_NAME" -At \
    -c "SELECT ceil(pg_database_size(current_database()) / 1024.0^3)")
  echo "Actual database size: ${ACTUAL_GB} GB (this script was generated for the [band] band)"
else
  ACTUAL_GB=""
  echo "SKIP: actual-size check needs SOURCE_HOST and SOURCE_DB_PASSWORD set."
fi
```

Follow it with ONE tool-appropriate advisory branch:

- pgcopydb script: `if [ -n "$ACTUAL_GB" ] && [ "$ACTUAL_GB" -lt 10 ]; then echo "NOTE: actual data is under 10 GB — plain pg_dump/pg_restore would be simpler (no pgcopydb install, no wal_level change). Consider regenerating."; fi`
- pg_dump script: `if [ -n "$ACTUAL_GB" ] && [ "$ACTUAL_GB" -ge 10 ]; then echo "WARNING: actual data is ${ACTUAL_GB} GB — pg_dump may exceed your maintenance window above 10 GB. Regenerate with pgcopydb before proceeding."; exit 1; fi` (hard stop: undersized tooling is the dangerous direction; oversized is merely inconvenient. The guards run in both dry-run and execute mode; when connection variables are unset — typical first dry run — the check is skipped with a notice, and the operator must fill them in before `--execute` anyway)

- `"<10GB"` → use **pg_dump/pg_restore**
- `"10-100GB"` or `"100-500GB"` → use **pgcopydb** (parallel copy; requires `wal_level=logical` on Cloud SQL)
- `">500GB"` → use **AWS DMS** (continuous replication; generate DMS task config instead of a shell export script)
- `"unknown"` → default to **pgcopydb** with a TODO comment to verify size before running

Generate the script with conditional branches based on `db_size`:

```bash
# Cloud SQL → RDS data migration
# Tool selection based on database size (preferences.json design_constraints.db_size.value):
# <10GB: pg_dump/pg_restore
# 10-500GB: pgcopydb (parallel copy, 3-5x faster than pg_dump)
# >500GB: AWS DMS recommended — see README-DMS.md if generated
# unknown: pgcopydb (safer default at unknown scale)
# Note: band comes from Q13b / allocated disk (an upper bound) — the preamble below
# measures ACTUAL data size and warns (or stops) if this tool choice doesn't fit it.

echo "=== Database Migration: Cloud SQL → RDS ==="

SOURCE_HOST="" # TODO: Set Cloud SQL IP
TARGET_HOST="" # From terraform output database_endpoint
DATABASE_NAME="" # TODO: Set database name
```

Then emit ONE of the following tool-specific blocks based on `db_size`:

**If `db_size` is `"<10GB"`** — emit pg_dump block:

```bash
# Tool: pg_dump/pg_restore (database < 10GB)
if [ "$DRY_RUN" = true ]; then
  echo "[DRY RUN] Would export from Cloud SQL using pg_dump: $DATABASE_NAME"
  echo "[DRY RUN] Would import to RDS using pg_restore: $TARGET_HOST"
else
  echo "Exporting from Cloud SQL with pg_dump..."
  PGPASSWORD="$SOURCE_DB_PASSWORD" pg_dump \
    -h "$SOURCE_HOST" -U postgres -d "$DATABASE_NAME" \
    -Fc -f /tmp/migration_dump.pgc
  echo "Importing to RDS with pg_restore..."
  PGPASSWORD="$TARGET_DB_PASSWORD" pg_restore \
    -h "$TARGET_HOST" -U postgres -d "$DATABASE_NAME" \
    -Fc /tmp/migration_dump.pgc
  rm -f /tmp/migration_dump.pgc
fi
```

**If `db_size` is `"10-100GB"` or `"100-500GB"`** — emit pgcopydb block:

```bash
# Tool: pgcopydb (database 10GB–500GB — parallel copy, 3-5x faster than pg_dump)
# Requires: pgcopydb installed, wal_level=logical on Cloud SQL source
# See: https://pgcopydb.readthedocs.io/
if [ "$DRY_RUN" = true ]; then
  echo "[DRY RUN] Would copy database using pgcopydb: $DATABASE_NAME"
  echo "[DRY RUN] Source: $SOURCE_HOST → Target: $TARGET_HOST"
else
  echo "Copying database with pgcopydb (parallel)..."
  pgcopydb copy db \
    --source "postgresql://postgres:${SOURCE_DB_PASSWORD}@${SOURCE_HOST}/${DATABASE_NAME}" \
    --target "postgresql://postgres:${TARGET_DB_PASSWORD}@${TARGET_HOST}/${DATABASE_NAME}" \
    --table-jobs 4 \
    --index-jobs 4
fi
```

**If `db_size` is `">500GB"`** — emit DMS guidance block instead of a shell script:

```bash
# Tool: AWS DMS (database > 500GB — continuous replication recommended)
# Single-pass export/import at this scale is high-risk and likely to exceed any maintenance window.
# AWS DMS provides continuous replication with a minimal cutover window (minutes, not hours).
#
# Steps:
# 1. Create a DMS replication instance in the target VPC
# 2. Create source endpoint (Cloud SQL PostgreSQL) and target endpoint (Aurora PostgreSQL)
# 3. Create a full-load + CDC replication task
# 4. Run full load, then let CDC catch up to < 1 second lag
# 5. Cut over DNS during the minimal lag window
#
# TODO: Configure DMS endpoints and task — see AWS DMS documentation:
# https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Source.PostgreSQL.html
echo "Database size > 500GB: AWS DMS is strongly recommended."
echo "See README-DMS.md for setup instructions."
echo "This script does not perform the migration directly at this scale."
```

**If `db_size` is `"unknown"`** — emit pgcopydb block with prominent TODO:

```bash
# Tool: pgcopydb (database size unknown — safer default than pg_dump at unknown scale)
# TODO: Verify your database size before running. If > 500GB, use AWS DMS instead.
# Requires: pgcopydb installed, wal_level=logical on Cloud SQL source
if [ "$DRY_RUN" = true ]; then
  echo "[DRY RUN] Would copy database using pgcopydb: $DATABASE_NAME"
  echo "[DRY RUN] TODO: Verify database size before executing"
else
  echo "Copying database with pgcopydb..."
  pgcopydb copy db \
    --source "postgresql://postgres:${SOURCE_DB_PASSWORD}@${SOURCE_HOST}/${DATABASE_NAME}" \
    --target "postgresql://postgres:${TARGET_DB_PASSWORD}@${TARGET_HOST}/${DATABASE_NAME}" \
    --table-jobs 4 \
    --index-jobs 4
fi
```

```bash
# Verification
echo "=== Verification ==="
echo "TODO: Compare row counts between source and target"
```

**BigQuery — specialist-deferred (no automated AWS target)** — include only if `has_bigquery`:

Design marked every `google_bigquery_*` resource as **`Deferred — specialist engagement`** with
`no_automated_aws_target: true` (see `references/phases/design/design-infra.md` → BigQuery specialist gate).
Therefore **do not** generate BigQuery export, copy, or load steps, and **do not** name an AWS analytics or
warehouse target (no Athena, Redshift, Glue, EMR, Lake Formation, or a prescribed "data lake on S3").
Emit only the deferral notice below:

```bash
# BigQuery — AWS target deliberately NOT selected
# This plugin does not choose an AWS analytics or warehouse target for BigQuery
# (no Athena/Redshift/Glue/EMR recommendation, and no prescribed data lake on S3).
# Engage your AWS account team and/or a data analytics migration partner before
# data warehouse, lake, SQL analytics, or BI cutover planning — query patterns,
# data volumes, ETL/ELT, and downstream consumers must be assessed by specialists.
# No BigQuery migration steps are generated here by design.
echo "BigQuery: AWS target deferred — specialist engagement required."
echo "  Next step: engage your AWS account team and/or a data analytics migration partner."
echo "  No BigQuery export or load steps are generated by this skill."
```

**Firestore to DynamoDB** — include only if `has_databases`:

```bash
# Firestore → DynamoDB migration
# TODO: Use AWS DMS or custom export/import script
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
[[ "${1:-}" == "--execute" ]] && DRY_RUN=false

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="us-east-1"  # From preferences.json target_region
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
aws ecr describe-repositories --region "$AWS_REGION" --query 'repositories[].repositoryName' --output table 2>/dev/null || echo "No ECR repositories (expected if EB-only)"
# Include the next two lines only if the EB section was emitted:
echo "Listing Elastic Beanstalk environments..."
aws elasticbeanstalk describe-environments --region "$AWS_REGION" --query 'Environments[].{Env:EnvironmentName,Status:Status,Health:Health}' --output table 2>/dev/null || echo "No EB environments"
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
[[ "${1:-}" == "--execute" ]] && DRY_RUN=false

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
aws secretsmanager list-secrets --query 'SecretList[].Name' --output table
```

### 05-validate-migration.sh

Post-migration validation script. **Always generated**, but adapt checks based on which resource
categories were detected in Step 1. Only include validation sections for resources that exist.

```bash
#!/usr/bin/env bash
set -euo pipefail

# Post-migration validation
# Usage: ./05-validate-migration.sh

echo "=== Migration Validation ==="

# Check Terraform state (always included)
echo "--- Terraform Resources ---"
cd terraform/
terraform state list | wc -l
echo "resources in Terraform state"

# --- Include ONLY if Fargate/ECS/EKS present ---
# Check ECS services
echo "--- ECS Services ---"
aws ecs list-services --cluster "${PROJECT_NAME:-gcp-migration}" --query 'serviceArns' --output table 2>/dev/null || echo "No ECS cluster found"

# --- Include ONLY if Elastic Beanstalk present ---
echo "--- Elastic Beanstalk Environments ---"
aws elasticbeanstalk describe-environments --query 'Environments[].{Env:EnvironmentName,Status:Status,Health:Health}' --output table 2>/dev/null || echo "No EB environments found"

# --- Include ONLY if has_databases ---
# Check RDS instances
echo "--- RDS Instances ---"
aws rds describe-db-instances --query 'DBInstances[].{ID:DBInstanceIdentifier,Status:DBInstanceStatus,Endpoint:Endpoint.Address}' --output table 2>/dev/null || echo "No RDS instances found"

# --- Include ONLY if has_storage ---
# Check S3 buckets
echo "--- S3 Buckets ---"
aws s3 ls | grep "${PROJECT_NAME:-gcp-migration}" || echo "No matching S3 buckets found"

# --- Include ONLY if has_secrets ---
# Check secrets
echo "--- Secrets Manager ---"
aws secretsmanager list-secrets --query 'SecretList[].Name' --output table 2>/dev/null || echo "No secrets found"

echo "=== Validation Complete ==="
echo "Review the output above. All resources should show healthy status."
echo "TODO: Run application-level health checks"
echo "TODO: Compare performance metrics against GCP baseline"
```

## Step 3: Self-Check

After generating all scripts, verify the following quality rules:

### Script Quality Rules

1. All scripts use `set -euo pipefail`
2. All scripts default to dry-run mode
3. All scripts include verification steps
4. All scripts are numbered for execution order
5. All TODO markers are clearly marked with context
6. No script prescribes an AWS analytics or warehouse target for BigQuery (no Athena, Redshift, Glue,
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
