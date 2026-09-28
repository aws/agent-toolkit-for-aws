#!/bin/bash
set -euo pipefail

# AWS Marketplace SaaS Metering Integration - Deploy Script
#
# Usage:
#   ./deploy.sh events-only                              Deploy shared events stack only
#   ./deploy.sh <PRODUCT_CODE> <REGION>                  Deploy events + main stack
#   ./deploy.sh <PRODUCT_CODE> <REGION> <PREFIX>         Custom stack prefix
#
# Examples:
#   STAGE_NAME=v1 ./deploy.sh events-only
#   STAGE_NAME=v1 ./deploy.sh abc123def us-west-2
#   STAGE_NAME=beta METERING_MODE=dry-run TEST_ACCOUNT_ALLOWLIST=111122223333 ./deploy.sh abc123def us-west-2 myapp-abc123def-beta
#
# Stack names (stage-scoped; STAGE_NAME is mandatory):
#   Events stack (shared per stage): awsmp-events-<STAGE_NAME>-stack (us-east-1)
#   Main stack (per-product):        <PREFIX>-metering, default awsmp-<PRODUCT_CODE>-<STAGE_NAME>-metering (<REGION>)

# ─── Cleanup trap ────────────────────────────────────────────────────────────
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        echo "⚠️  Deployment failed (exit code: $exit_code)"
        echo "   Check the CloudFormation console for stack events."
        echo "   No automatic rollback — review and fix before retrying."
    fi
    # Clean up SAM build artifacts if they exist
    if [ -d ".aws-sam" ]; then
        rm -rf .aws-sam
    fi
    exit $exit_code
}
trap cleanup EXIT

# ─── Version checks ─────────────────────────────────────────────────────────
check_prerequisites() {
    local errors=0

    # AWS CLI v2 required
    if ! command -v aws &>/dev/null; then
        echo "ERROR: AWS CLI not found. Install from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        errors=$((errors + 1))
    else
        local aws_version
        aws_version=$(aws --version 2>&1 | sed -n 's/.*aws-cli\/\([0-9]*\).*/\1/p')
        if [ "${aws_version:-0}" -lt 2 ]; then
            echo "ERROR: AWS CLI v2 required (found v${aws_version}). Update: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
            errors=$((errors + 1))
        fi
    fi

    # SAM CLI required
    if ! command -v sam &>/dev/null; then
        echo "ERROR: SAM CLI not found. Install from https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html"
        errors=$((errors + 1))
    fi

    # Python 3.9+ required (for Lambda runtime compatibility)
    if ! command -v python3 &>/dev/null; then
        echo "ERROR: Python 3 not found."
        errors=$((errors + 1))
    else
        local py_version
        py_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        local py_minor
        py_minor=$(echo "$py_version" | cut -d. -f2)
        if [ "${py_minor:-0}" -lt 9 ]; then
            echo "WARNING: Python 3.9+ recommended (found $py_version). Lambda uses 3.12."
        fi
    fi

    if [ $errors -gt 0 ]; then
        echo ""
        echo "Fix the above errors before proceeding."
        exit 1
    fi
}

# ─── Input validation ─────────────────────────────────────────────
# Validate caller-supplied values against a strict allowlist charset BEFORE use, so a
# value containing spaces/shell metacharacters cannot inject extra CloudFormation
# parameter overrides or arguments. Product code / prefix: alphanumeric, dash, underscore.
# Region: AWS region format.
validate_inputs() {
    local product_code="$1"
    local region="$2"
    local prefix="$3"

    if ! [[ "$product_code" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo "ERROR: invalid PRODUCT_CODE '$product_code' (allowed: A-Z a-z 0-9 _ -)."
        exit 1
    fi
    if ! [[ "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]]; then
        echo "ERROR: invalid REGION '$region' (expected e.g. us-east-1)."
        exit 1
    fi
    if ! [[ "$prefix" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo "ERROR: invalid PREFIX '$prefix' (allowed: A-Z a-z 0-9 _ -)."
        exit 1
    fi
}

# ─── SAM artifact bucket (no --resolve-s3) ──────────────────────────
# The least-privilege deployer policy scopes cloudformation:* to stack/awsmp-*, so
# `sam deploy --resolve-s3` (which bootstraps the non-awsmp aws-sam-cli-managed-default
# CFN stack) is DENIED. Provision the artifact bucket DIRECTLY instead — the policy's
# S3DeploymentArtifacts grant already allows this on aws-sam-cli-managed-default-*.
# Echoes the bucket name for use with `sam deploy --s3-bucket`.
ensure_sam_bucket() {
    local region="$1"
    local bucket="aws-sam-cli-managed-default-${ACCOUNT_ID}-${region}"
    if ! aws s3api head-bucket --bucket "$bucket" --region "$region" >/dev/null 2>&1; then
        if [ "$region" = "us-east-1" ]; then
            aws s3api create-bucket --bucket "$bucket" --region "$region" >/dev/null
        else
            aws s3api create-bucket --bucket "$bucket" --region "$region" \
                --create-bucket-configuration "LocationConstraint=${region}" >/dev/null
        fi
        aws s3api put-bucket-encryption --bucket "$bucket" \
            --server-side-encryption-configuration \
            '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
        aws s3api put-bucket-versioning --bucket "$bucket" \
            --versioning-configuration Status=Enabled >/dev/null
    fi
    echo "$bucket"
}

# ─── Per-region API Gateway CloudWatch Logs account role ────────────
# A logging-enabled API stage (AccessLogSetting) requires a per-region,
# account-level CloudWatch Logs role set via `apigateway update-account`. Granting the
# permission is not enough — the role/account setting must actually be provisioned per
# region, or the first region "just works" and every additional region fails with
# "CloudWatch Logs role ARN must be set in account settings to enable logging".
# Idempotent: creates the (region-agnostic) role once, then sets the account setting for
# THIS region if not already set.
ensure_apigw_cw_role() {
    local region="$1"
    local role_name="awsmp-apigw-cloudwatch-logs"
    local role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${role_name}"

    if ! aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
        aws iam create-role --role-name "$role_name" \
            --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"apigateway.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
            >/dev/null
        aws iam attach-role-policy --role-name "$role_name" \
            --policy-arn arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs \
            >/dev/null
        # IAM role propagation to API Gateway can lag a few seconds.
        sleep 10
    fi

    local current
    current=$(aws apigateway get-account --region "$region" \
        --query cloudwatchRoleArn --output text 2>/dev/null || echo "None")
    if [ "$current" = "None" ] || [ -z "$current" ]; then
        echo "Setting API Gateway account CloudWatch Logs role for ${region} (account-global for that region)..."
        aws apigateway update-account --region "$region" \
            --patch-operations "op=replace,path=/cloudwatchRoleArn,value=${role_arn}" >/dev/null
    fi
}

# ─── Failed-deploy recovery preflight (detect-and-guide only) ────────
# After a failed deploy/rollback, DeletionPolicy: Retain resources (usage/subscribers
# tables, subscription role, /aws/lambda/awsmp-* log groups) and an orphaned baseline
# WebACL can survive and collide on retry (ResourceExistenceCheck / WebACL AlreadyExists).
# This is READ-ONLY: it DETECTS likely collisions and prints guidance, then continues.
# It NEVER auto-deletes; the seller removes reviewed resources with their own credentials
# (a data-bearing table requires explicit confirmation).
warn_retained_resources() {
    local prefix="$1"
    local region="$2"
    local found=0
    # Log groups are the easy-to-miss case (not shown in the rollback resource summary).
    local lg
    lg=$(aws logs describe-log-groups --region "$region" \
        --log-group-name-prefix "/aws/lambda/${prefix}-" \
        --query 'logGroups[].logGroupName' --output text 2>/dev/null || true)
    if [ -n "$lg" ] && [ "$lg" != "None" ]; then
        echo "NOTE: pre-existing log group(s) may collide on re-create: $lg"
        found=1
    fi
    if aws dynamodb describe-table --table-name "${prefix}-usage" --region "$region" >/dev/null 2>&1; then
        echo "NOTE: usage table '${prefix}-usage' already exists (retained). If this is a"
        echo "      re-deploy after a FAILED first deploy the table is empty and can be removed;"
        echo "      if it holds billable usage do NOT delete it. Deleting requires your explicit"
        echo "      action with your own credentials — this script will not delete it."
        found=1
    fi
    if [ $found -eq 1 ]; then
        echo "      Review and remove the reviewed leftover resource(s), then retry."
    fi
}

# ─── Materialize-then-deploy parity preflight ────────────────────────────────
# This script deploys the on-disk SAM template(s) the skill materialized into the
# workspace (`sam build --template-file <name>` below), so the deployed stack always
# matches the source the seller can see and further develop. Fail fast (READ-ONLY, no
# mutation) if the template we are about to build is missing or renamed — that would
# mean a drift between "what was generated" and "what gets deployed". We do NOT recreate
# or relocate it; the seller/skill regenerates it in place.
require_template() {
    local tmpl="$1"
    if [ ! -f "$tmpl" ]; then
        echo "ERROR: expected on-disk template '$tmpl' not found in $(pwd)." >&2
        echo "       deploy.sh deploys the materialized template so the stack matches your" >&2
        echo "       source. Generate/restore '$tmpl' (and its Lambda handlers) here," >&2
        echo "       then re-run — do not deploy a template that is not left in the workspace." >&2
        exit 1
    fi
}

# ─── Deploy events stack (shared, us-east-1) ─────────────────────────────────
# ─── Permissions-boundary preflight ──────────────────────────────────────────
# SAM auto-generates the Lambda execution roles; the deployer role only allows
# iam:CreateRole when a matching permissions boundary is attached. Fail fast with a
# clear message (instead of an opaque AccessDenied mid-deploy) if the boundary policy
# named by BOUNDARY_NAME does not exist in the target account.
BOUNDARY_NAME="${BOUNDARY_NAME:-awsmp-metering-boundary}"

verify_boundary_exists() {
    local acct boundary_arn err
    # Validate the account id before building the ARN — an empty/None value would produce a
    # malformed ARN and a misleading "not found" message. `|| true` so a failing STS call
    # falls through to the guard below instead of aborting the script under `set -e`.
    acct=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)
    if [ -z "$acct" ] || [ "$acct" = "None" ]; then
        echo "ERROR: unable to resolve AWS account id (check credentials/region)."
        exit 1
    fi
    boundary_arn="arn:aws:iam::${acct}:policy/${BOUNDARY_NAME}"

    # Capture stderr so we can distinguish a genuinely-missing policy (NoSuchEntity) from
    # a permissions gap (AccessDenied). Collapsing every failure into "not found" would
    # block deploys when the deployer merely lacks iam:GetPolicy — the opaque failure this
    # preflight is meant to prevent.
    if err=$(aws iam get-policy --policy-arn "$boundary_arn" 2>&1 >/dev/null); then
        echo "Permissions boundary: ${boundary_arn}"
        return 0
    fi
    case "$err" in
        *NoSuchEntity*)
            echo "ERROR: permissions boundary '${BOUNDARY_NAME}' not found (${boundary_arn})."
            echo "       Create it before deploying (see references/iam-credentials.md):"
            echo "         aws iam create-policy --policy-name ${BOUNDARY_NAME} --policy-document file://boundary.json"
            echo "       The deployer role's iam:CreateRole is gated on this exact boundary, so"
            echo "       SAM role creation would otherwise fail with AccessDenied."
            exit 1
            ;;
        *AccessDenied*|*not\ authorized*)
            echo "WARN: cannot verify boundary '${boundary_arn}' (iam:GetPolicy denied); continuing."
            echo "      Grant iam:GetPolicy on the boundary ARN to enable this preflight, or"
            echo "      ensure the boundary policy exists before deploying."
            return 0
            ;;
        *)
            echo "ERROR: failed to verify boundary '${boundary_arn}': ${err}"
            exit 1
            ;;
    esac
}

# ─── Deploy events stack (shared, us-east-1) ─────────────────────────────────
deploy_events_stack() {
    echo ""
    # The (stage-scoped) events stack is always deployed here. `sam deploy` is idempotent
    # (`--no-fail-on-empty-changeset` makes an unchanged stack a no-op change set), and a
    # requested MeteringMode / TestAccountAllowlist / EventSource change MUST be applied — so
    # there is deliberately NO existence-skip / SKIP_EVENTS flag (an existence-skip would
    # silently suppress those updates). The deploy role needs cloudformation:GetTemplateSummary
    # for the re-deploy of an existing stack.
    echo "=== Deploying events stack ${EVENTS_STACK_NAME} to us-east-1 (shared across all products for this stage) ==="
    verify_boundary_exists
    local ev_bucket
    ev_bucket=$(ensure_sam_bucket us-east-1)
    require_template template-events.yaml
    sam build --template-file template-events.yaml --region us-east-1
    sam deploy \
        --template-file .aws-sam/build/template.yaml \
        --stack-name "$EVENTS_STACK_NAME" \
        --region us-east-1 \
        --capabilities CAPABILITY_NAMED_IAM \
        --s3-bucket "$ev_bucket" \
        --no-confirm-changeset \
        --no-fail-on-empty-changeset \
        --parameter-overrides "StackPrefix=$EVENTS_PREFIX" "PermissionsBoundaryName=${BOUNDARY_NAME}" "CreateDashboard=${CREATE_DASHBOARD:-true}" "MeteringMode=$METERING_MODE" "TestAccountAllowlist=$TEST_ACCOUNT_ALLOWLIST" "EventSource=$EVENT_SOURCE"
    # NOTE: ProductCode is deliberately NOT passed to the SHARED events stack — the dry-run test
    # publisher takes productCode PER INVOCATION (payload), so a second product's deploy cannot
    # overwrite a shared per-product value (the events-stack ProductCode param stays empty).

    echo "✅ Events stack deployed"
}

# ─── Deploy main stack (per-product, seller's region) ─────────────────────────
deploy_main_stack() {
    local product_code="$1"
    local region="$2"
    local prefix="$3"

    # Get subscribers table name from events stack
    local subscribers_table
    subscribers_table=$(aws cloudformation describe-stacks \
        --stack-name "$EVENTS_STACK_NAME" \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`SubscribersTableName`].OutputValue' \
        --output text)

    if [ -z "$subscribers_table" ] || [ "$subscribers_table" = "None" ]; then
        echo "ERROR: Could not get SubscribersTableName from events stack."
        echo "       Deploy the events stack first: ./deploy.sh events-only"
        exit 1
    fi
    echo "Subscribers table: $subscribers_table"

    echo ""
    echo "=== Deploying main stack to $region ==="
    verify_boundary_exists
    # read-only recovery preflight — detect retained/orphaned resources that
    # would collide on retry and print guidance (never auto-deletes).
    warn_retained_resources "$prefix" "$region"
    # ensure the per-region API Gateway CloudWatch Logs account role/setting
    # exists before deploying the logging-enabled stage (multi-region correctness).
    ensure_apigw_cw_role "$region"
    local main_bucket
    main_bucket=$(ensure_sam_bucket "$region")
    require_template template.yaml
    sam build --template-file template.yaml --region "$region"
    # Pass overrides as discrete, individually-quoted Key=Value tokens (array form) so a
    # value containing spaces cannot inject additional overrides. Values are
    # already validated by validate_inputs().
    local overrides=(
        "ProductCode=$product_code"
        "StackPrefix=$prefix"
        "SubscribersTableName=$subscribers_table"
        "PermissionsBoundaryName=$BOUNDARY_NAME"
        "StageName=$STAGE_NAME"
        "MeteringLockHours=$METERING_LOCK_HOURS"
        "UsageTableTtlDays=$USAGE_TABLE_TTL_DAYS"
        "AggregatedUsageTableTtlDays=$AGGREGATED_USAGE_TTL_DAYS"
        "CreateDashboard=$CREATE_DASHBOARD"
        "DeploymentMode=$DEPLOYMENT_MODE"
        "MeteringMode=$METERING_MODE"
        "TestAccountAllowlist=$TEST_ACCOUNT_ALLOWLIST"
)
    sam deploy \
        --stack-name "${prefix}-metering" \
        --region "$region" \
        --capabilities CAPABILITY_NAMED_IAM \
        --s3-bucket "$main_bucket" \
        --no-confirm-changeset \
        --no-fail-on-empty-changeset \
        --parameter-overrides "${overrides[@]}"

    echo "✅ Main stack deployed"
    echo ""
    echo "Stack outputs:"
    aws cloudformation describe-stacks \
        --stack-name "${prefix}-metering" \
        --region "$region" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
}

# ─── Main ────────────────────────────────────────────────────────────────────
check_prerequisites

echo "=== Verifying AWS credentials ==="
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
    echo "ERROR: AWS credentials not configured. Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or run 'aws configure'."
    exit 1
}
echo "Account: $ACCOUNT_ID"

# CreateDashboard: whether to create the CloudWatch health dashboards (default true). Set
# CREATE_DASHBOARD=false to skip; sellers can also delete/customize post-deploy. Sourced
# before the events-only branch so both stacks honor it.
CREATE_DASHBOARD="${CREATE_DASHBOARD:-true}"
if [ "$CREATE_DASHBOARD" != "true" ] && [ "$CREATE_DASHBOARD" != "false" ]; then
    echo "ERROR: invalid CREATE_DASHBOARD '$CREATE_DASHBOARD' (must be 'true' or 'false')."
    exit 1
fi

# DEPLOYMENT_MODE selects full (raw pipeline: discoverer/aggregator/cleanup) or direct-submit
# (seller writes finalized records straight to aggregated_usage; only submitter + submission-
# expiry are created). Direct-submit records MUST be final before insert (any record may be
# submitted on the next 5-min run; a re-write returns DuplicateRecord).
DEPLOYMENT_MODE="${DEPLOYMENT_MODE:-full}"
if [ "$DEPLOYMENT_MODE" != "full" ] && [ "$DEPLOYMENT_MODE" != "direct-submit" ]; then
    echo "ERROR: invalid DEPLOYMENT_MODE '$DEPLOYMENT_MODE' (must be 'full' or 'direct-submit')."
    exit 1
fi

# Handle events-only mode
if [ "${1:-}" = "events-only" ]; then
    # Events stack is stage-scoped too — require STAGE_NAME here as well.
    STAGE_NAME="${STAGE_NAME:-}"
    if [ -z "$STAGE_NAME" ] || ! [[ "$STAGE_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo "ERROR: STAGE_NAME is required for events-only (e.g. STAGE_NAME=v1 ./deploy.sh events-only)."
        exit 1
    fi
    EVENTS_PREFIX="awsmp-events-${STAGE_NAME}"
    EVENTS_STACK_NAME="awsmp-events-${STAGE_NAME}-stack"
    METERING_MODE="${METERING_MODE:-live}"
    if [ "$METERING_MODE" != "live" ] && [ "$METERING_MODE" != "dry-run" ]; then
        echo "ERROR: invalid METERING_MODE '$METERING_MODE' (allowed: live | dry-run)."; exit 1
    fi
    TEST_ACCOUNT_ALLOWLIST="${TEST_ACCOUNT_ALLOWLIST:-}"
    if [ "$METERING_MODE" = "dry-run" ]; then
        if [ -z "$TEST_ACCOUNT_ALLOWLIST" ]; then
            echo "ERROR: METERING_MODE=dry-run requires TEST_ACCOUNT_ALLOWLIST (test buyer account ids)."; exit 1
        fi
        if ! [[ "$TEST_ACCOUNT_ALLOWLIST" =~ ^[0-9]{12}(,[0-9]{12})*$ ]]; then
            echo "ERROR: TEST_ACCOUNT_ALLOWLIST must be comma-separated 12-digit AWS account ids."; exit 1
        fi
    fi
    if [ "$METERING_MODE" = "live" ] && [ -n "$TEST_ACCOUNT_ALLOWLIST" ]; then
        echo "ERROR: TEST_ACCOUNT_ALLOWLIST must be EMPTY for METERING_MODE=live."; exit 1
    fi
    if [ "$METERING_MODE" = "dry-run" ]; then
        EVENT_SOURCE="${STAGE_NAME}.agreement-marketplace"
        case "$EVENT_SOURCE" in
            aws.*) echo "ERROR: dry-run EVENT_SOURCE must not start with 'aws.' (STAGE_NAME='$STAGE_NAME' collides with the reserved production source)."; exit 1 ;;
        esac
    else
        EVENT_SOURCE="aws.agreement-marketplace"
    fi
    PRODUCT_CODE="${PRODUCT_CODE:-}"
    deploy_events_stack
    echo ""
    echo "Next: Deploy main stack per-product:"
    echo "  STAGE_NAME=$STAGE_NAME ./deploy.sh <PRODUCT_CODE> <REGION>"
    exit 0
fi

# Full deployment mode
PRODUCT_CODE="${1:?Usage: ./deploy.sh events-only | ./deploy.sh <PRODUCT_CODE> <REGION> [PREFIX]}"
REGION="${2:?Usage: ./deploy.sh <PRODUCT_CODE> <REGION> [PREFIX]}"

# StageName is a MANDATORY seller-supplied answer — there is no default and no fallback
# to `prod`. Supply it via the STAGE_NAME environment variable. Deployment fails fast if
# it is empty so we never create an API with an empty/placeholder stage.
STAGE_NAME="${STAGE_NAME:-}"
if [ -z "$STAGE_NAME" ]; then
    echo "ERROR: STAGE_NAME is required and has no default."
    echo "       Set the API Gateway stage name you want (your choice — e.g. v1, live, or prod)."
    echo "       Example: STAGE_NAME=v1 ./deploy.sh $PRODUCT_CODE $REGION"
    exit 1
fi
if ! [[ "$STAGE_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "ERROR: invalid STAGE_NAME '$STAGE_NAME' (allowed: A-Z a-z 0-9 _ -)."
    exit 1
fi

# Stage-scoped names: the stage folds into BOTH stacks so multiple stages coexist without
# collision. Main stack: awsmp-<productCode>-<stage>-metering (prefix awsmp-<productCode>-<stage>).
# Events stack: awsmp-events-<stage>-stack (prefix awsmp-events-<stage>).
PREFIX="${3:-awsmp-${PRODUCT_CODE}-${STAGE_NAME}}"
EVENTS_PREFIX="awsmp-events-${STAGE_NAME}"
EVENTS_STACK_NAME="awsmp-events-${STAGE_NAME}-stack"

# MeteringMode decides prod (live) vs non-prod (dry-run). live = real BatchMeterUsage;
# dry-run = full pipeline but NO real submit (a sandbox). Prod vs non-prod is THIS switch,
# not the free-form STAGE_NAME.
METERING_MODE="${METERING_MODE:-live}"
if [ "$METERING_MODE" != "live" ] && [ "$METERING_MODE" != "dry-run" ]; then
    echo "ERROR: invalid METERING_MODE '$METERING_MODE' (allowed: live | dry-run)."
    exit 1
fi
# For a non-prod (dry-run) stage a TestAccountAllowlist is REQUIRED and must be test accounts
# ONLY; a live stage must NOT set it. TEST_ACCOUNT_ALLOWLIST is comma-separated 12-digit ids.
TEST_ACCOUNT_ALLOWLIST="${TEST_ACCOUNT_ALLOWLIST:-}"
if [ "$METERING_MODE" = "dry-run" ]; then
    if [ -z "$TEST_ACCOUNT_ALLOWLIST" ]; then
        echo "ERROR: METERING_MODE=dry-run requires TEST_ACCOUNT_ALLOWLIST (comma-separated TEST"
        echo "       buyer account ids). A non-prod stage must use test accounts ONLY."
        exit 1
    fi
    if ! [[ "$TEST_ACCOUNT_ALLOWLIST" =~ ^[0-9]{12}(,[0-9]{12})*$ ]]; then
        echo "ERROR: TEST_ACCOUNT_ALLOWLIST must be comma-separated 12-digit AWS account ids."
        exit 1
    fi
    echo "NOTE: dry-run (non-prod) stage — the submitter will NOT call BatchMeterUsage (no real"
    echo "      billing); use TEST accounts ONLY: $TEST_ACCOUNT_ALLOWLIST"
else
    if [ -n "$TEST_ACCOUNT_ALLOWLIST" ]; then
        echo "ERROR: TEST_ACCOUNT_ALLOWLIST must be EMPTY for METERING_MODE=live (production)."
        exit 1
    fi
fi
# EventSource the events rule matches. dry-run uses a STAGE-SCOPED source (never the reserved
# aws.* prefix) so the test publisher's events are delivered AND are disjoint from real prod
# events (no same-account cross-match). live uses the real aws.agreement-marketplace.
if [ "$METERING_MODE" = "dry-run" ]; then
    EVENT_SOURCE="${STAGE_NAME}.agreement-marketplace"
    case "$EVENT_SOURCE" in
        aws.*)
            echo "ERROR: dry-run EVENT_SOURCE must not start with 'aws.' (STAGE_NAME='$STAGE_NAME'"
            echo "       collides with the reserved production source aws.agreement-marketplace)."
            exit 1 ;;
    esac
else
    EVENT_SOURCE="aws.agreement-marketplace"
fi

# MeteringLockHours: how many hours a metering hour stays open for late usage
# before it is aggregated/submitted. Seller-configured via the METERING_LOCK_HOURS env var;
# default 1 (submit a fully-complete hour). Validated 1..20 so an hour is first submitted
# with >=4h of margin inside the 24h billable window (>=3 retries + rejection re-drive).
METERING_LOCK_HOURS="${METERING_LOCK_HOURS:-1}"
if ! [[ "$METERING_LOCK_HOURS" =~ ^[0-9]+$ ]] || [ "$METERING_LOCK_HOURS" -lt 1 ] || [ "$METERING_LOCK_HOURS" -gt 20 ]; then
    echo "ERROR: invalid METERING_LOCK_HOURS '$METERING_LOCK_HOURS' (must be an integer 1..20)."
    echo "       This is how many hours an hour stays open for late usage before submission."
    exit 1
fi

# TTL retention (days) for the RAW usage table (high-volume; RECOMMENDED on to control
# cost). 0 disables. Floor of 2 days so a row can never expire before it is metered
# (must exceed MeteringLockHours + the 24h billable window). The seller's WRITER sets the
# `ttl` attribute; enabling it here only makes DynamoDB honor it.
USAGE_TABLE_TTL_DAYS="${USAGE_TABLE_TTL_DAYS:-365}"
if ! [[ "$USAGE_TABLE_TTL_DAYS" =~ ^[0-9]+$ ]] || { [ "$USAGE_TABLE_TTL_DAYS" -ne 0 ] && [ "$USAGE_TABLE_TTL_DAYS" -lt 2 ]; } || [ "$USAGE_TABLE_TTL_DAYS" -gt 3650 ]; then
    echo "ERROR: invalid USAGE_TABLE_TTL_DAYS '$USAGE_TABLE_TTL_DAYS' (0 to disable, else an integer 2..3650)."
    exit 1
fi

# TTL retention (days) for the AGGREGATED usage table (small billing audit trail).
# DEFAULTS 0 (disabled = retain), which is recommended. When >0 the submitter sets `ttl`
# on finalized Success rows only.
AGGREGATED_USAGE_TTL_DAYS="${AGGREGATED_USAGE_TTL_DAYS:-0}"
if ! [[ "$AGGREGATED_USAGE_TTL_DAYS" =~ ^[0-9]+$ ]] || [ "$AGGREGATED_USAGE_TTL_DAYS" -gt 3650 ]; then
    echo "ERROR: invalid AGGREGATED_USAGE_TTL_DAYS '$AGGREGATED_USAGE_TTL_DAYS' (0 to disable, else an integer 1..3650)."
    exit 1
fi

# Validate all caller-supplied inputs before any AWS call.
validate_inputs "$PRODUCT_CODE" "$REGION" "$PREFIX"

echo "Product code: $PRODUCT_CODE"
echo "Region: $REGION"
echo "Stack prefix: $PREFIX"
echo "Stage name: $STAGE_NAME"

deploy_events_stack
deploy_main_stack "$PRODUCT_CODE" "$REGION" "$PREFIX"

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Next steps:"
echo "1. Copy the RegistrationUrl from stack outputs above"
echo "2. Set it as the fulfillment URL in AWS Marketplace Management Portal"
echo "3. Subscribe to the product and click 'Set up your account' to test"
