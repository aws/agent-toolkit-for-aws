#!/usr/bin/env bash

SCRIPT_CLIENT="db2-driver.sh"
SCRIPT_AIRGAP="db2client-airgap.sh"
SCRIPT_CONFIGURE="db2client-configure.sh"
FILE_FUNCTIONS="functions.sh"
FILE_README="README.txt"
INCLUDE_OTHER_TOOLS=${INCLUDE_OTHER_TOOLS:-TRUE}

# Db2 version selection — set DB2_VER before running:
#   DB2_VER=11.5  (default) → installs Db2 11.5.9 RT client
#   DB2_VER=12.1            → installs Db2 12.1.3 RT client
DB2_VER=${DB2_VER:-"11.5"}

case "$DB2_VER" in
  11.5)
    DRIVER_RT="v11.5.9_linuxx64_rtcl.tar"
    TOOLS_ZIP="db211.5-tools.zip"
    DB2_INSTALL_DIR="/opt/ibm/db2/V11.5"
    DB2_VERSION_LABEL="11.5.9"
    ;;
  12.1)
    DRIVER_RT="v12.1.4_linuxx64_rtcl.tar"
    TOOLS_ZIP="db212.1-tools.zip"
    DB2_INSTALL_DIR="/opt/ibm/db2/V12.1"
    DB2_VERSION_LABEL="12.1.4"
    ;;
  *)
    echo "ERROR: Unsupported DB2_VER='${DB2_VER}'. Valid values: 11.5, 12.1" >&2
    exit 1
    ;;
esac

# Public source (online mode)
SOURCE_URL="https://aws-blogs-artifacts-public.s3.amazonaws.com/artifacts/DBBLOG-4900"

# =============================================================================
# db2-driver.sh  —  Install RDS DB2 RT client
# =============================================================================
# Works in two modes — auto-detected based on whether BUCKET is set:
#
# ONLINE mode  (CloudShell / EC2 with internet access):
#   curl -sL https://bit.ly/getdb2driver | bash
#   — or —
#   REGION=us-east-1 ./${SCRIPT_CLIENT}
#
# AIRGAP mode  (private subnet, no internet — run ${SCRIPT_AIRGAP} first):
#   export BUCKET=db2client-artifacts-<account>-<region> REGION=<region>
#   ./${SCRIPT_CLIENT}
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

# --- Curl-pipe detection ---
# True when script is being piped via bash (not run as a saved file)
CURL_PIPE=false
if [ ! -f "${BASH_SOURCE[0]:-}" ]; then
  CURL_PIPE=true
fi



# --- Defaults ---
PROFILE=${PROFILE:-""}
REGION=${REGION:-""}
DB2USER_NAME=${DB2USER_NAME:-"db2inst1"}
BUCKET=${BUCKET:-""}
VERBOSE=${VERBOSE:-false}

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --region)  REGION="$2";  shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --bucket)  BUCKET="$2";  shift 2 ;;
    --verbose) VERBOSE=true; shift ;;
    -h|--help)
      echo "Usage: [BUCKET=<bucket>] [REGION=<region>] ./$SCRIPT_CLIENT [--region REGION] [--profile PROFILE]"
      echo "  No BUCKET = online mode  (downloads from public S3)"
      echo "  BUCKET set = airgap mode (downloads from private bucket)"
      exit 0 ;;
    *) log_error "Unknown option: $1"; exit 1 ;;
  esac
done

log_debug() { [[ "$VERBOSE" == "true" ]] && echo -e "${BLUE}[ DEBUG]${NC} $(date '+%H:%M:%S') - $1" >&2 || true; }

# =============================================================================
# Validation
# =============================================================================
validate() {
  # Auto-detect region if not set
  if [ -z "$REGION" ]; then
    if [ -n "${AWS_DEFAULT_REGION:-}" ]; then
      REGION="$AWS_DEFAULT_REGION"
      log_info "Detected region from environment: $REGION"
    elif curl -s --connect-timeout 1 http://169.254.169.254/latest/meta-data/ >/dev/null 2>&1; then
      local token
      token=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null)
      REGION=$(curl -s -H "X-aws-ec2-metadata-token: $token" \
        http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null)
      log_info "Detected region from EC2 metadata: $REGION"
    fi
  fi

  if [ -z "$REGION" ]; then
    log_error "REGION not set. Either: export REGION=us-east-1  or use --region us-east-1"
    exit 1
  fi

  if [ "$(uname -s)" != "Linux" ]; then
    log_error "This script only supports Linux. Detected: $(uname -s)"
    exit 1
  fi

  if ! sudo -n true 2>/dev/null; then
    log_error "This script requires sudo privileges."
    exit 1
  fi

  if ! command -v aws &>/dev/null; then
    log_error "aws CLI not found. Please install it first."
    exit 1
  fi

  # Set PROFILE_ARG early so ensure_jq can use it if needed.
  # Guard against an empty PROFILE: "--profile " (no name) is an invalid CLI
  # argument and would break the airgap jq download in ensure_jq, which runs
  # before set_credentials can resolve metadata creds.
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    PROFILE_ARG=""
  elif [ -n "$PROFILE" ]; then
    PROFILE_ARG="--profile $PROFILE"
  else
    PROFILE_ARG=""
  fi

  ensure_jq
  set_credentials  # sets CREDS_FROM_METADATA=true when sourced from CloudShell/EC2

  if [ "${CREDS_FROM_METADATA:-false}" = "false" ]; then
    if ! aws sts get-caller-identity $PROFILE_ARG --region "$REGION" >/dev/null 2>&1; then
      if [ -n "$PROFILE" ]; then
        log_error "Profile '$PROFILE' credentials are invalid or expired."
        log_error "Run: aws sts get-caller-identity --profile $PROFILE"
        log_error "Either refresh credentials for '$PROFILE' or unset PROFILE to use instance metadata."
      else
        log_error "AWS credentials invalid. Set AWS_ACCESS_KEY_ID/SECRET or export PROFILE=<name>."
      fi
      exit 1
    fi
  fi

  if [ -n "$BUCKET" ]; then
    log_success "Validation passed | Mode: AIRGAP | Region: $REGION | Bucket: $BUCKET"
  else
    log_success "Validation passed | Mode: ONLINE | Region: $REGION"
  fi
}

# =============================================================================
# Ensure jq is available — install from private bucket if missing
# =============================================================================
ensure_jq() {
  command -v jq &>/dev/null && return 0
  if [ -n "${BUCKET:-}" ]; then
    # Airgap mode — pull the static jq binary staged in the private bucket
    log_info "jq not found — downloading from s3://${BUCKET}/scripts/jq ..."
    local tmp_jq
    tmp_jq=$(mktemp)
    aws s3 cp "s3://${BUCKET}/scripts/jq" "$tmp_jq" \
      --region "$REGION" $PROFILE_ARG --quiet
    sudo mv -f "$tmp_jq" /usr/local/bin/jq
    sudo chmod +x /usr/local/bin/jq
    log_success "jq installed from private bucket"
  else
    # Online mode — BUCKET is empty, so install via the OS package manager
    log_info "jq not found — installing via package manager ..."
    sudo yum install -y jq &>/dev/null || sudo apt-get install -y jq &>/dev/null
    if ! command -v jq &>/dev/null; then
      log_error "Failed to install jq. Please install it manually and re-run."
      exit 1
    fi
    log_success "jq installed via package manager"
  fi
}

# =============================================================================
# Credentials — probe CloudShell, EC2 IMDSv2, then fall back to profile/env
# Precedence:
#   1. Exported AWS_ACCESS_KEY_ID/SECRET  → use immediately
#   2. PROFILE explicitly set             → validate with sts, exit if fails
#   3. No profile                         → probe CloudShell IMDS → EC2 IMDS → exit if neither works
#
# SECURITY: exported AWS_ACCESS_KEY_ID/SECRET are long-lived static keys —
# acceptable only for temporary CI/CD automation, NEVER for production. In
# production, obtain credentials exclusively through an EC2 instance profile /
# IAM role (CloudShell or EC2 IMDS below), never hard-coded or long-lived keys.
# =============================================================================
set_credentials() {
  local creds
  CREDS_FROM_METADATA=false

  # Priority 1: exported env var credentials
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    PROFILE_ARG=""
    return 0
  fi

  # Priority 2: explicit profile — skip IMDS, validate immediately
  if [ -n "$PROFILE" ]; then
    PROFILE_ARG="--profile $PROFILE"
    log_info "Using explicit profile: $PROFILE"
    return 0
  fi

  # Priority 3a: CloudShell IMDS
  if curl -s --connect-timeout 1 http://127.0.0.1:1338/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected AWS CloudShell environment"
    local token
    token=$(curl -sX PUT "http://127.0.0.1:1338/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    creds=$(curl -s -H "Authorization: $token" \
      "http://127.0.0.1:1338/latest/meta-data/container/security-credentials")
    export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .AccessKeyId)
    export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .SecretAccessKey)
    export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Token)
    PROFILE_ARG=""
    CREDS_FROM_METADATA=true
    return 0
  fi

  # Priority 3b: EC2 IMDSv2
  if curl -s --connect-timeout 1 http://169.254.169.254/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected EC2 environment"
    local token role
    token=$(curl -sX PUT "http://169.254.169.254/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    role=$(curl -s -H "X-aws-ec2-metadata-token: $token" \
      http://169.254.169.254/latest/meta-data/iam/security-credentials/)
    if [ -n "$role" ]; then
      creds=$(curl -s -H "X-aws-ec2-metadata-token: $token" \
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/$role")
      export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .AccessKeyId)
      export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .SecretAccessKey)
      export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Token)
      PROFILE_ARG=""
      CREDS_FROM_METADATA=true
      return 0
    fi
  fi

  log_error "No credentials found. Set AWS_ACCESS_KEY_ID/SECRET, export PROFILE=<name>, or run from CloudShell/EC2."
  exit 1
}

# =============================================================================
# Download artifacts — online (curl from public S3) or airgap (aws s3 cp)
# =============================================================================
curl_download() {
  local url="$1" dest="$2"
  curl -fsSL "$url" -o "$dest"
}

s3_download() {
  local key="$1" dest="$2"
  aws s3 cp "s3://${BUCKET}/${key}" "$dest" \
    --region "$REGION" $PROFILE_ARG --quiet
}

download_artifacts() {
  local work_dir="$1"

  if [ -n "$BUCKET" ]; then
    # --- Airgap mode: pull from private bucket ---
    for f in "$FILE_FUNCTIONS" "$FILE_README"; do
      s3_download "scripts/${f}" "${work_dir}/${f}"
    done
    if [ "$INCLUDE_OTHER_TOOLS" = "TRUE" ]; then
      s3_download "scripts/${TOOLS_ZIP}" "${work_dir}/${TOOLS_ZIP}"
    fi
    s3_download "ssl/${REGION}-bundle.pem"    "${work_dir}/${REGION}-bundle.pem"
    s3_download "drivers/${DRIVER_RT}"        "${work_dir}/${DRIVER_RT}"
    s3_download "scripts/${SCRIPT_CONFIGURE}" "${work_dir}/${SCRIPT_CONFIGURE}"
  else
    # --- Online mode: pull from public S3 via curl ---
    for f in "$FILE_FUNCTIONS" "$FILE_README"; do
      curl_download "${SOURCE_URL}/${f}" "${work_dir}/${f}"
    done
    if [ "$INCLUDE_OTHER_TOOLS" = "TRUE" ]; then
      curl_download "${SOURCE_URL}/${TOOLS_ZIP}" "${work_dir}/${TOOLS_ZIP}"
    fi
    curl_download \
      "https://truststore.pki.rds.amazonaws.com/${REGION}/${REGION}-bundle.pem" \
      "${work_dir}/${REGION}-bundle.pem"
    curl_download "${SOURCE_URL}/${DRIVER_RT}"        "${work_dir}/${DRIVER_RT}"
    curl_download "${SOURCE_URL}/${SCRIPT_CONFIGURE}" "${work_dir}/${SCRIPT_CONFIGURE}"
  fi

  echo "${DRIVER_RT}"
}

# =============================================================================
# User creation
# =============================================================================
create_db2_user() {
  local username="$DB2USER_NAME"
  local start_id=1001

  while getent group "$start_id" >/dev/null; do start_id=$((start_id + 1)); done
  local gid=$start_id
  while getent passwd "$start_id" >/dev/null; do start_id=$((start_id + 1)); done
  local uid=$start_id

  log_info "Creating group $username (GID $gid) and user (UID $uid)"
  sudo groupadd -g "$gid" "$username"
  sudo useradd -u "$uid" -g "$gid" -d "/home/$username" -m -s /bin/bash "$username"
  log_success "User $username created"
}


# =============================================================================
# Install RT Client (runtime client)  — mirrors install_rt_client() in db2-driver.sh
# =============================================================================
install_rt_client() {
  local work_dir="$1"
  local driver_pkg="$2"

  log_info "============================================================================"
  log_info "Deploying Db2 ${DB2_VERSION_LABEL} Runtime client"
  log_debug "Extracting ${driver_pkg} from ${work_dir}"
  if ! tar -xf "${work_dir}/${driver_pkg}" -C "$work_dir" 2>/tmp/tar_err; then
    log_error "tar extraction failed: $(cat /tmp/tar_err)"
    return 1
  fi

  if id "$DB2USER_NAME" &>/dev/null; then
    log_info "User $DB2USER_NAME already exists. Skipping user creation."
  else
    create_db2_user
  fi

  # db2_install only if not already done for this version
  if [ ! -d "${DB2_INSTALL_DIR}" ]; then
    log_info "Installing Db2 ${DB2_VERSION_LABEL} runtime client"
    # AL2023 ships without libcrypt.so.1 — db2iure requires it
    if ! ldconfig -p | grep -q libcrypt.so.1; then
      log_info "Installing libxcrypt-compat for AL2023 compatibility"
      sudo yum install -y libxcrypt-compat &>/dev/null
    fi
    (cd "${work_dir}/rtcl" && sudo TMPDIR=/var/tmp ./db2_install -f sysreq -y -b /opt/ibm/db2 2>/tmp/db2install_err) || true
    if [ ! -d "/opt/ibm/db2" ]; then
      log_error "db2_install failed — /opt/ibm/db2 not found."
      return 1
    fi
  else
    log_info "Db2 software already installed at ${DB2_INSTALL_DIR} — skipping db2_install"
  fi
  rm -rf "${work_dir}/rtcl"

  # Always remove sqllib before db2icrt so it can recreate it cleanly
  sudo rm -rf "/home/$DB2USER_NAME/sqllib" &>/dev/null || true
  local tmp_free
  tmp_free=$(df /tmp --output=avail | tail -1)
  if [ "$tmp_free" -lt 524288 ]; then
    log_info "/tmp has insufficient space (${tmp_free}KB) — bind-mounting /var/tmp over /tmp"
    sudo mount --bind /var/tmp /tmp
    trap "sudo umount /tmp 2>/dev/null; rm -rf $work_dir" EXIT
  fi

  local icrt_out
  icrt_out=$(sudo env -i TMPDIR=/var/tmp PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    /opt/ibm/db2/instance/db2icrt -s client "$DB2USER_NAME" 2>&1) || true

  if [ ! -d "/home/$DB2USER_NAME/sqllib" ]; then
    log_error "db2icrt failed — /home/$DB2USER_NAME/sqllib not found."
    log_error "db2icrt output: $icrt_out"
    return 1
  fi

  # Place functions.sh and README.txt
  sudo mv -f "${work_dir}/${FILE_FUNCTIONS}" "/home/$DB2USER_NAME/"
  sudo chown "$DB2USER_NAME:$DB2USER_NAME" "/home/$DB2USER_NAME/${FILE_FUNCTIONS}"
  sudo mv -f "${work_dir}/${FILE_README}" "/home/$DB2USER_NAME/"
  sudo chown "$DB2USER_NAME:$DB2USER_NAME" "/home/$DB2USER_NAME/${FILE_README}"

  if [ "$INCLUDE_OTHER_TOOLS" = "TRUE" ] && [ -f "${work_dir}/${TOOLS_ZIP}" ]; then
    log_info "Installing tools from ${TOOLS_ZIP}..."
    # Extract tools zip — expected contents: db2exfmt, db2advis, db2advisbind.zip
    local tools_dir="${work_dir}/tools"
    mkdir -p "$tools_dir"
    unzip -o "${work_dir}/${TOOLS_ZIP}" -d "$tools_dir" &>/dev/null

    # Place db2advisbind.zip into sqllib/bnd and unzip
    if [ -f "${tools_dir}/db2advisbind.zip" ]; then
      sudo mv -f "${tools_dir}/db2advisbind.zip" "/home/$DB2USER_NAME/sqllib/bnd/"
      sudo bash -c "
        cd /home/$DB2USER_NAME/sqllib/bnd
        rm -f db2adv*.bnd
        unzip -o db2advisbind.zip &>/dev/null
        chown -R bin:bin db2adv*.bnd
        rm -f db2advisbind.zip
      "
    fi

    # Place db2exfmt and db2advis into /opt/ibm/db2/bin
    for bin in db2exfmt db2advis; do
      if [ -f "${tools_dir}/${bin}" ]; then
        sudo mv -f "${tools_dir}/${bin}" /opt/ibm/db2/bin/
        sudo chown bin:bin "/opt/ibm/db2/bin/${bin}"
        sudo chmod +x "/opt/ibm/db2/bin/${bin}"
      fi
    done
    rm -rf "$tools_dir"
  else
    log_info "Skipping additional tools — set INCLUDE_OTHER_TOOLS=TRUE to enable"
  fi

  # Grant db2inst1 passwordless sudo ONLY for the Db2 binaries/instance tools it
  # needs post-install (least privilege) — not blanket NOPASSWD:ALL. db2client-configure.sh
  # and the Db2 admin commands run out of these paths.
  cat <<SUDOERS | sudo tee "/etc/sudoers.d/$DB2USER_NAME" >/dev/null
$DB2USER_NAME ALL=(ALL) NOPASSWD: /opt/ibm/db2/bin/*, /opt/ibm/db2/V*/bin/*, /opt/ibm/db2/V*/instance/*, /opt/ibm/db2/V*/adm/*
SUDOERS
  sudo chmod 440 "/etc/sudoers.d/$DB2USER_NAME"

  sudo mv -f "${work_dir}/${SCRIPT_CONFIGURE}" "/home/$DB2USER_NAME/${SCRIPT_CONFIGURE}"
  sudo chown "$DB2USER_NAME:$DB2USER_NAME" "/home/$DB2USER_NAME/${SCRIPT_CONFIGURE}"
  sudo chmod +x "/home/$DB2USER_NAME/${SCRIPT_CONFIGURE}"

  log_success "Db2 ${DB2_VERSION_LABEL} Runtime client installed successfully for user $DB2USER_NAME"
  log_info "============================================================================"
}

# =============================================================================
# Curl-pipe handler — download script then exit so user can run it directly
# =============================================================================
handle_curl_pipe() {
  log_info "Curl-pipe detected — downloading $SCRIPT_CLIENT and $SCRIPT_AIRGAP for direct use"
  local dest_client="./$SCRIPT_CLIENT"
  local dest_airgap="./$SCRIPT_AIRGAP"
  curl -fsSL "${SOURCE_URL}/${SCRIPT_CLIENT}" -o "$dest_client" && chmod +x "$dest_client"
  log_success "Saved: $dest_client"
  curl -fsSL "${SOURCE_URL}/${SCRIPT_AIRGAP}" -o "$dest_airgap" && chmod +x "$dest_airgap"
  log_success "Saved: $dest_airgap"
  curl -fsSL "${SOURCE_URL}/${FILE_README}" -o "./$FILE_README"
  log_success "Saved: ./$FILE_README"
  echo
  echo "============================================================="
  echo "  ONLINE mode (EC2 / CloudShell with internet):"
  echo "    REGION=<region> ./$SCRIPT_CLIENT"
  echo "    DB2_VER=12.1 REGION=<region> ./$SCRIPT_CLIENT   # install Db2 12.1"
  echo "    DB2_VER=11.5 REGION=<region> ./$SCRIPT_CLIENT   # install Db2 11.5 (default)"
  echo
  echo "  AIRGAP mode (no internet — private subnet):"
  echo "    Step 1: On any machine WITH internet, download all artifacts:"
  echo "      DB2_VER=12.1 ./$SCRIPT_AIRGAP --mode download --region <region>"
  echo "                       # saves to ./db2client-artifacts/"
  echo
  echo "    Step 2: On a machine WITH AWS configured, upload to S3:"
  echo "      ./$SCRIPT_AIRGAP --mode upload --region <region>"
  echo "                       # creates bucket + uploads artifacts"
  echo
  echo "    Step 3: Follow steps given after completion of step 2:"
  echo "============================================================="
}

# =============================================================================
# Main
# =============================================================================
main() {
  if [ "$CURL_PIPE" = "true" ]; then
    handle_curl_pipe
    return
  fi

  validate

  local work_dir
  work_dir=$(mktemp -d -p /var/tmp)
  trap "rm -rf $work_dir" EXIT

  log_info "Downloading artifacts ..."
  local driver_pkg
  driver_pkg=$(download_artifacts "$work_dir")
  log_success "Downloading artifacts ... Done."

  install_rt_client "$work_dir" "$driver_pkg"

  log_success "============================================================="
  log_success "DB2 RT client installed successfully"
  log_info "To configure DSN entries, switch to the DB2 user and run:"
  log_info "  1. sudo su - $DB2USER_NAME"
  if [ -n "$BUCKET" ]; then
    log_info "  2. BUCKET=$BUCKET REGION=$REGION source $SCRIPT_CONFIGURE"
  else
    log_info "  2. REGION=$REGION source $SCRIPT_CONFIGURE"
  fi
  log_success "============================================================="
}

main "$@"
