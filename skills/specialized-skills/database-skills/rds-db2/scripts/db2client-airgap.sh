#!/usr/bin/env bash

SCRIPT_CLIENT="db2-driver.sh"
SCRIPT_AIRGAP="db2client-airgap.sh"
SCRIPT_CONFIGURE="db2client-configure.sh"
FILE_FUNCTIONS="functions.sh"
FILE_README="README.txt"
INCLUDE_LICENSED_TOOLS=${INCLUDE_LICENSED_TOOLS:-FALSE}
JQ_BINARY="jq-linux-amd64"
JQ_VERSION="jq-1.7.1"

# Db2 version selection — set DB2_VER before running:
#   DB2_VER=11.5  (default) → downloads Db2 11.5.9 RT client + db211.5.9-tools.zip
#   DB2_VER=12.1            → downloads Db2 12.1.3 RT client + db212.1-tools.zip
DB2_VER=${DB2_VER:-"11.5"}

case "$DB2_VER" in
  11.5)
    DRIVER_RT="v11.5.9_linuxx64_rtcl.tar"
    TOOLS_ZIP="db211.5.9-tools.zip"
    ;;
  12.1)
    DRIVER_RT="v12.1.4_linuxx64_rtcl.tar"
    TOOLS_ZIP="db212.1-tools.zip"
    ;;
  *)
    echo "ERROR: Unsupported DB2_VER='${DB2_VER}'. Valid values: 11.5, 12.1" >&2
    exit 1
    ;;
esac

# =============================================================================
# db2client-airgap.sh  —  Populate private bucket for air-gapped deployments
# =============================================================================
# MODE: download  — download all artifacts to ./db2client-artifacts/ (needs internet)
# MODE: upload    — create bucket and upload from ./db2client-artifacts/ (needs AWS)
# MODE: both      — download then upload in one shot (default)
#
# Usage:
#   ./$SCRIPT_AIRGAP --mode download --region us-east-1   # step 1: laptop with internet
#   ./$SCRIPT_AIRGAP --mode upload   --region us-east-1   # step 2: machine with AWS access
#   ./$SCRIPT_AIRGAP --mode both     --region us-east-1   # download + upload in one shot
#
# NOTE: --region is required for all modes. It determines the RDS SSL certificate
#       filename (e.g. us-east-1-bundle.pem).
# =============================================================================

if [ -z "$BASH_VERSION" ]; then exec bash "$0" "$@"; fi
set -eo pipefail
export AWS_PAGER=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}[   INFO]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_error()   { echo -e "${RED}[  ERROR]${NC} $(date '+%H:%M:%S') - $1" >&2; }

SOURCE_BUCKET="aws-blogs-artifacts-public"
SOURCE_PREFIX="artifacts/DBBLOG-4900"
SOURCE_URL="https://${SOURCE_BUCKET}.s3.amazonaws.com/${SOURCE_PREFIX}"
ARTIFACTS_DIR="./db2client-artifacts"
MODE=${MODE:-"both"}

# --- Curl-pipe detection ---
CURL_PIPE=false
detect_curl_pipe() {
  local src="${BASH_SOURCE[0]:-}"
  if [[ -z "$src" || "$src" == "/dev/fd/"* || "$src" == "/dev/stdin" || ! -f "$src" ]]; then
    CURL_PIPE=true
  fi
}

handle_curl_pipe_download() {
  log_info "Downloading ${SCRIPT_AIRGAP} ..."
  curl -fsSL "${SOURCE_URL}/${SCRIPT_AIRGAP}" -o "./${SCRIPT_AIRGAP}" && chmod +x "./${SCRIPT_AIRGAP}"
  log_success "Saved: ./${SCRIPT_AIRGAP}"

  log_info "Downloading ${SCRIPT_CLIENT} ..."
  curl -fsSL "${SOURCE_URL}/${SCRIPT_CLIENT}" -o "./${SCRIPT_CLIENT}" && chmod +x "./${SCRIPT_CLIENT}"
  log_success "Saved: ./${SCRIPT_CLIENT}"

  echo
  echo "============================================================="
  echo "  Downloaded. Steps for air-gapped deployment:"
  echo "============================================================="
  echo
  echo "STEP 1a — Download all artifacts on this machine (needs internet):"
  echo "   ./$SCRIPT_AIRGAP --mode download --region <your-region>"
  echo
  echo "STEP 1b — Copy $SCRIPT_AIRGAP, $SCRIPT_CLIENT and db2client-artifacts/"
  echo "   to a machine with AWS access (private subnet). Then upload:"
  echo "   ./$SCRIPT_AIRGAP --mode upload --region <your-region>"
  echo
  echo "   Or if this machine also has AWS access, run both in one shot:"
  echo "   ./$SCRIPT_AIRGAP --mode both --region <your-region>"
  echo
  echo "STEP 2 — On the target Linux machine, pull the install script and run it:"
  echo "   aws s3 cp s3://db2client-artifacts-<account>-<region>/$SCRIPT_CLIENT . && chmod +x $SCRIPT_CLIENT"
  echo "   BUCKET=db2client-artifacts-<account>-<region> ./$SCRIPT_CLIENT --region <your-region>"
  echo "============================================================="
}

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --mode)    MODE="$2";    shift 2 ;;
    --region)  REGION="$2";  shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $SCRIPT_AIRGAP --mode download|upload|both --region REGION [--profile PROFILE]"
      echo "       --region is required: determines the RDS SSL certificate filename."
      exit 0 ;;
    *) log_error "Unknown option: $1"; exit 1 ;;
  esac
done

# --- Curl-pipe detection (must precede the mandatory --region check, since
#     a curl|bash bootstrap has no args and only needs handle_curl_pipe_download) ---
detect_curl_pipe
if $CURL_PIPE; then
  handle_curl_pipe_download
  exit 0
fi

# --- Enforce mandatory --region ---
if [ -z "${REGION:-}" ]; then
  log_error "--region is required. Example: $SCRIPT_AIRGAP --mode download --region us-east-1"
  exit 1
fi

# --- AWS setup (required for upload/both) ---
set_credentials_airgap() {
  # If creds already exported in environment, use them as-is
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    log_info "Using AWS credentials from environment variables"
    CREDS_FROM_METADATA=false
    return
  fi

  if curl -s --connect-timeout 1 http://127.0.0.1:1338/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected AWS CloudShell environment"
    local token creds
    token=$(curl -sX PUT "http://127.0.0.1:1338/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    creds=$(curl -s -H "Authorization: $token" "http://127.0.0.1:1338/latest/meta-data/container/security-credentials")
    export AWS_ACCESS_KEY_ID=$(echo "$creds"     | python3 -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])")
    export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | python3 -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])")
    export AWS_SESSION_TOKEN=$(echo "$creds"     | python3 -c "import sys,json; print(json.load(sys.stdin)['Token'])")
    CREDS_FROM_METADATA=true
    return
  fi
  if curl -s --connect-timeout 1 http://169.254.169.254/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected EC2 environment"
    local token role creds
    token=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    role=$(curl -s -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/iam/security-credentials/)
    creds=$(curl -s -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/iam/security-credentials/$role")
    export AWS_ACCESS_KEY_ID=$(echo "$creds"     | python3 -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])")
    export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | python3 -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])")
    export AWS_SESSION_TOKEN=$(echo "$creds"     | python3 -c "import sys,json; print(json.load(sys.stdin)['Token'])")
    CREDS_FROM_METADATA=true
    return
  fi
  CREDS_FROM_METADATA=false
}

setup_aws() {
  PROFILE=${PROFILE:-"default"}
  CREDS_FROM_METADATA=false
  set_credentials_airgap

  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    PROFILE_ARG=""
  else
    PROFILE_ARG="--profile $PROFILE"
  fi

  if [ "$CREDS_FROM_METADATA" = "false" ]; then
    if ! aws sts get-caller-identity $PROFILE_ARG --region "$REGION" >/dev/null 2>&1; then
      log_error "AWS credentials invalid. Run 'aws configure' or set AWS_ACCESS_KEY_ID/SECRET."
      exit 1
    fi
  fi
  ACCOUNT_ID=$(aws sts get-caller-identity $PROFILE_ARG --region "$REGION" --query Account --output text 2>/dev/null)
  if [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "None" ]; then
    log_error "Could not determine AWS Account ID. Check credentials."
    exit 1
  fi
  TARGET_BUCKET="db2client-artifacts-${ACCOUNT_ID}-${REGION}"
  log_success "AWS ready | Account: $ACCOUNT_ID | Region: $REGION"
}

# =============================================================================
# STEP 1 — Download all artifacts to ARTIFACTS_DIR (internet-connected laptop)
# =============================================================================
do_download() {
  mkdir -p "${ARTIFACTS_DIR}/scripts" "${ARTIFACTS_DIR}/drivers" "${ARTIFACTS_DIR}/ssl"

  log_info "Downloading jq static binary ..."
  curl -fsSL "https://github.com/jqlang/jq/releases/download/${JQ_VERSION}/${JQ_BINARY}" \
    -o "${ARTIFACTS_DIR}/scripts/jq"
  log_success "Downloaded: scripts/jq"

  log_info "Downloading DB2 client scripts from s3://${SOURCE_BUCKET}/${SOURCE_PREFIX}/ ..."
  for f in "$FILE_FUNCTIONS" "$FILE_README"; do
    curl -fsSL "https://${SOURCE_BUCKET}.s3.amazonaws.com/${SOURCE_PREFIX}/${f}" \
      -o "${ARTIFACTS_DIR}/scripts/${f}"
    log_success "Downloaded: scripts/${f}"
  done
  if [ "$INCLUDE_LICENSED_TOOLS" = "TRUE" ]; then
    curl -fsSL "https://${SOURCE_BUCKET}.s3.amazonaws.com/${SOURCE_PREFIX}/${TOOLS_ZIP}" \
      -o "${ARTIFACTS_DIR}/scripts/${TOOLS_ZIP}"
    log_success "Downloaded: scripts/${TOOLS_ZIP}"
  else
    log_info "Skipping tools zip (${TOOLS_ZIP}) — set INCLUDE_LICENSED_TOOLS=TRUE to enable"
  fi

  log_info "Downloading ${SCRIPT_CONFIGURE} ..."
  curl -fsSL "${SOURCE_URL}/${SCRIPT_CONFIGURE}" \
    -o "${ARTIFACTS_DIR}/scripts/${SCRIPT_CONFIGURE}"
  chmod +x "${ARTIFACTS_DIR}/scripts/${SCRIPT_CONFIGURE}"
  log_success "Copied: scripts/${SCRIPT_CONFIGURE}"

  log_info "Downloading DB2 driver packages (large files, this may take a while) ..."
  curl -fsSL "https://${SOURCE_BUCKET}.s3.amazonaws.com/${SOURCE_PREFIX}/${DRIVER_RT}" \
    -o "${ARTIFACTS_DIR}/drivers/${DRIVER_RT}"
  log_success "Downloaded: drivers/${DRIVER_RT}"

  log_info "Downloading RDS SSL certificate for region: $REGION ..."
  local pem_file="${REGION}-bundle.pem"
  if ! curl -fsSL "https://truststore.pki.rds.amazonaws.com/${REGION}/${pem_file}" \
       -o "${ARTIFACTS_DIR}/ssl/${pem_file}"; then
    log_error "Failed to download SSL certificate for region $REGION."
    return 1
  fi
  log_success "Downloaded: ssl/${pem_file}"

  echo
  log_success "All artifacts saved to: ${ARTIFACTS_DIR}/"
  echo
  echo "  Next: copy ${SCRIPT_CLIENT}, ${SCRIPT_AIRGAP} and"
  echo "    directory ${ARTIFACTS_DIR}/ to your system (private subnets) that has aws configured. Run:"
  echo "    ./$SCRIPT_AIRGAP --mode upload --region $REGION"
  echo
}

# =============================================================================
# STEP 2 — Create bucket and upload from ARTIFACTS_DIR (AWS-connected machine)
# =============================================================================
do_upload() {
  setup_aws

  if [ ! -d "$ARTIFACTS_DIR" ]; then
    log_error "Artifacts directory not found: $ARTIFACTS_DIR"
    log_error "Run './$SCRIPT_AIRGAP --mode download' first, then copy the directory here."
    exit 1
  fi

  # --- Create target bucket if needed ---
  if ! aws s3api head-bucket --bucket "$TARGET_BUCKET" --region "$REGION" $PROFILE_ARG 2>/dev/null; then
    log_info "Creating bucket: $TARGET_BUCKET"
    if [ "$REGION" = "us-east-1" ]; then
      aws s3api create-bucket --bucket "$TARGET_BUCKET" --region "$REGION" $PROFILE_ARG >/dev/null
    else
      aws s3api create-bucket --bucket "$TARGET_BUCKET" --region "$REGION" $PROFILE_ARG \
        --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
    fi
    aws s3api put-bucket-versioning --bucket "$TARGET_BUCKET" \
      --versioning-configuration Status=Enabled --region "$REGION" $PROFILE_ARG >/dev/null
    log_success "Bucket created: $TARGET_BUCKET"
  else
    log_info "Bucket already exists: $TARGET_BUCKET"
  fi

  # --- Upload all artifacts ---
  log_info "Uploading artifacts to s3://${TARGET_BUCKET}/ ..."
  aws s3 sync "${ARTIFACTS_DIR}/" "s3://${TARGET_BUCKET}/" \
    --region "$REGION" $PROFILE_ARG --quiet
  log_success "Upload complete"

  # --- Copy scripts to bucket so private subnet machines can pull via S3 GW ---
  log_info "Copying scripts to s3://${TARGET_BUCKET}/ ..."
  local script_dir
  script_dir="$(dirname "$(realpath "$0")")"
  aws s3 cp "${script_dir}/${SCRIPT_AIRGAP}" "s3://${TARGET_BUCKET}/${SCRIPT_AIRGAP}" \
    --region "$REGION" $PROFILE_ARG --quiet
  aws s3 cp "${script_dir}/${SCRIPT_CLIENT}" "s3://${TARGET_BUCKET}/${SCRIPT_CLIENT}" \
    --region "$REGION" $PROFILE_ARG --quiet
  aws s3 cp "${ARTIFACTS_DIR}/scripts/${SCRIPT_CONFIGURE}" "s3://${TARGET_BUCKET}/scripts/${SCRIPT_CONFIGURE}" \
    --region "$REGION" $PROFILE_ARG --quiet
  log_success "Scripts uploaded to s3://${TARGET_BUCKET}/"

  # --- Verify ---
  log_info "Verifying uploads..."
  local missing=false
  for key in \
    scripts/jq \
    "scripts/${FILE_FUNCTIONS}" \
    "scripts/${FILE_README}" \
    "scripts/${SCRIPT_CONFIGURE}" \
    "drivers/${DRIVER_RT}" \
    "ssl/${REGION}-bundle.pem"; do
    if aws s3api head-object --bucket "$TARGET_BUCKET" --key "$key" \
       --region "$REGION" $PROFILE_ARG &>/dev/null; then
      log_success "OK: s3://${TARGET_BUCKET}/${key}"
    else
      log_warning "Missing: s3://${TARGET_BUCKET}/${key}"
      missing=true
    fi
  done
  [ "$missing" = "true" ] && log_warning "Some artifacts missing — check errors above."

  echo
  echo "============================================================="
  echo "  Bucket ready : s3://${TARGET_BUCKET}"
  echo "  SSL cert     : s3://${TARGET_BUCKET}/ssl/${REGION}-bundle.pem"
  echo
  echo "  STEP 1b (continued) — On the private subnet machine, download the install script:"
  echo "    aws s3 cp s3://${TARGET_BUCKET}/${SCRIPT_CLIENT} . && chmod +x ${SCRIPT_CLIENT}"
  echo
  echo "  STEP 2 — Install the DB2 client:"
  echo "    export BUCKET=${TARGET_BUCKET} REGION=${REGION}"
  echo "    ./$SCRIPT_CLIENT"
  echo "============================================================="
}

# =============================================================================
# Main
# =============================================================================
case "$MODE" in
  download) do_download ;;
  upload)   do_upload ;;
  both)     do_download; do_upload ;;
  *) log_error "Unknown mode: $MODE. Use download, upload, or both."; exit 1 ;;
esac
