#!/usr/bin/env bash
# =============================================================================
# db2client-configure.sh  —  Configure db2dsdriver.cfg for RDS DB2 RT client
# =============================================================================
# Run as db2inst1 after db2-driver.sh has installed the RT client:
#
#   sudo su - db2inst1
#   REGION=<region> source db2client-configure.sh                                    # online
#   BUCKET=db2client-artifacts-<account>-<region> REGION=<region> source db2client-configure.sh  # airgap
#
# Optional env vars:
#   DB_INSTANCE_ID=<id>   target a specific RDS instance
#   PROFILE=<profile>     AWS CLI profile (default: default)
# =============================================================================

if [ -z "$BASH_VERSION" ]; then exec bash "$0" "$@"; fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}[   INFO]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_error()   { echo -e "${RED}[  ERROR]${NC} $(date '+%H:%M:%S') - $1" >&2; }

# RDS cert bundle URL — partition-aware (commercial / GovCloud / China)
rds_truststore_url() {
  local region="$1"
  case "$region" in
    us-gov-*) echo "https://truststore.pki.${region}.rds.amazonaws.com/${region}/${region}-bundle.pem" ;;
    cn-*)     echo "https://truststore.pki.${region}.rds.amazonaws.com.cn/${region}/${region}-bundle.pem" ;;
    *)        echo "https://truststore.pki.rds.amazonaws.com/${region}/${region}-bundle.pem" ;;
  esac
}

# =============================================================================
# Kerberos / domain-join detection
# =============================================================================
# Sets IS_DOMAIN_JOINED=true and KRB_REALM=<realm> when the host is confirmed
# to be a member of an Active Directory / Kerberos realm.
#
# Detection order (first match wins):
#   1. 'realm list' shows "configured: kerberos-member"  (realmd + sssd — most common)
#   2. /etc/krb5.conf contains a default_realm           (any kerberos setup)
#
# When domain-joined, also validates that a TGT exists in the Kerberos cache.
# RDS for Db2 does not support local user authentication when Kerberos is
# enabled — a valid TGT is required for ALL connections (including the
# internal bootstrap query). The script exits if no ticket is found.
#
IS_DOMAIN_JOINED=false
KRB_REALM=""

detect_domain_join() {
  # Method 1: realm list (realmd)
  if command -v realm &>/dev/null; then
    local realm_out
    realm_out=$(realm list 2>/dev/null)
    if echo "$realm_out" | grep -q "configured: kerberos-member"; then
      KRB_REALM=$(echo "$realm_out" | awk '/^[^ ]/ {realm=$1} /configured: kerberos-member/ {print realm; exit}')
      log_info "Domain join detected via 'realm list' — realm: $KRB_REALM"
      # Only treat the host as domain-joined if a valid TGT is present. Otherwise
      # the Kerberos DSNs would be written but fail at connect time.
      if _require_tgt; then
        IS_DOMAIN_JOINED=true
      else
        log_warning "Domain join detected but no valid TGT — Kerberos DSNs will NOT be created"
        IS_DOMAIN_JOINED=false
      fi
      return
    fi
  fi

  # Method 2: /etc/krb5.conf default_realm
  if [ -f /etc/krb5.conf ]; then
    local realm_line
    realm_line=$(grep -i '^\s*default_realm\s*=' /etc/krb5.conf 2>/dev/null | head -1)
    if [ -n "$realm_line" ]; then
      KRB_REALM=$(echo "$realm_line" | awk -F'=' '{gsub(/[[:space:]]/,"",$2); print $2}')
      log_info "Domain join detected via /etc/krb5.conf — realm: $KRB_REALM"
      # Only treat the host as domain-joined if a valid TGT is present. Otherwise
      # the Kerberos DSNs would be written but fail at connect time.
      if _require_tgt; then
        IS_DOMAIN_JOINED=true
      else
        log_warning "Domain join detected but no valid TGT — Kerberos DSNs will NOT be created"
        IS_DOMAIN_JOINED=false
      fi
      return
    fi
  fi

  log_info "No domain join detected — Kerberos DSN parameters will not be added"
}

# Gate: verify a valid TGT exists. Called only when IS_DOMAIN_JOINED=true.
# Both local auth and Kerberos SSL DSNs will be written on domain-joined hosts.
# A valid TGT is required for the Kerberos DSNs and for the bootstrap connect
# when db2comm=SSL (since local auth over SSL also needs a working SSL path
# that the Kerberos ticket provides for discovery).
_require_tgt() {
  if ! command -v klist &>/dev/null; then
    log_error "klist not found — cannot verify Kerberos ticket."
    log_error "Install krb5-workstation (AL2/AL2023) and obtain a ticket:"
    log_error "  sudo dnf install -y krb5-workstation"
    log_error "  kinit $(whoami)@${KRB_REALM}"
    return 1
  fi

  if ! klist -s 2>/dev/null; then
    log_error "============================================================="
    log_error "This host is domain-joined (realm: $KRB_REALM)."
    log_error "RDS for Db2 does not support local user authentication"
    log_error "when Kerberos is enabled — a valid TGT is required."
    log_error ""
    log_error "No Kerberos ticket found in the cache. Obtain one first:"
    log_error "  kinit $(whoami)@${KRB_REALM}"
    log_error "  klist                   # confirm ticket is present"
    log_error "  REGION=$REGION source db2client-configure.sh"
    log_error "============================================================="
    return 1
  fi

  # Ticket exists — show the principal so the user can confirm it's the right one
  local principal
  principal=$(klist 2>/dev/null | awk '/^Default principal:/ {print $3}')
  log_success "Kerberos TGT found — principal: ${principal:-<unknown>}"
}

# --- Defaults ---
PROFILE=${PROFILE:-"default"}
DB2USER_NAME=${DB2USER_NAME:-"db2inst1"}
DB_NAMES_INPUT=${DB_NAMES:-""}   # optional: comma-separated list, e.g. DB_NAMES=DB2DB,MYDB
E_URL=${E_URL:-""}               # optional: custom RDS endpoint, e.g.
                                 #   E_URL="--endpoint-url https://rds-siteb.us-east-1.amazonaws.com --no-verify-ssl"
SSL_CERT_FILE=""                 # set by download_pem_file() — do not set manually
declare -a HELP_COMMANDS=()
declare -a DB_INSTANCES=()
declare -a MASTER_USER_NAMES=()
declare -a MASTER_USER_PASSWORDS=()
declare -a DB_NAMES=()

# Wrapper for all 'aws rds' calls — injects E_URL when set.
# Usage:  aws_rds describe-db-instances --region ... --query ... --output text
aws_rds() {
  # shellcheck disable=SC2086
  aws rds "$@" ${E_URL}
}

# =============================================================================
# Validation
# =============================================================================
validate() {
  if [ -z "$REGION" ]; then
    log_error "REGION is required. Example: BUCKET=... REGION=us-east-1 source db2client-configure.sh"
    return 1
  fi
  # BUCKET is optional — only needed for airgap SSL cert download
  if [ "$(whoami)" != "$DB2USER_NAME" ]; then
    log_error "This script must be run as $DB2USER_NAME. Run: sudo su - $DB2USER_NAME"
    return 1
  fi
  if [ ! -d "$HOME/sqllib" ]; then
    log_error "RT client not installed — $HOME/sqllib not found. Run db2-driver.sh as root first."
    return 1
  fi
}

# =============================================================================
# Credentials
# =============================================================================
set_credentials() {
  # CloudShell
  if curl -s --connect-timeout 1 http://127.0.0.1:1338/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected AWS CloudShell environment"
    local token creds
    token=$(curl -sX PUT "http://127.0.0.1:1338/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    creds=$(curl -s -H "Authorization: $token" "http://127.0.0.1:1338/latest/meta-data/container/security-credentials")
    export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .AccessKeyId)
    export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .SecretAccessKey)
    export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Token)
    log_success "AWS credentials set from CloudShell"
    return
  fi
  # EC2 IMDSv2
  if curl -s --connect-timeout 1 http://169.254.169.254/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected EC2 environment"
    local token role creds
    token=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    role=$(curl -s -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/iam/security-credentials/)
    creds=$(curl -s -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/iam/security-credentials/$role")
    export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .AccessKeyId)
    export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .SecretAccessKey)
    export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Token)
    log_success "AWS credentials set from EC2 instance role"
    return
  fi
  # Fall back to configured profile
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    # SECURITY: AWS_ACCESS_KEY_ID/SECRET are long-lived static keys — acceptable
    # only for temporary CI/CD automation, NEVER for production. Production
    # workflows MUST obtain credentials through a CloudShell/EC2 IAM role (handled
    # above) or a configured profile, never hard-coded or long-lived keys.
    log_info "Using AWS credentials from environment variables"
  else
    log_info "Using AWS CLI profile: $PROFILE"
    export AWS_PROFILE="$PROFILE"
  fi
}

# =============================================================================
# Instance discovery
# =============================================================================
list_db_instances() {
  local query='DBInstances[?starts_with(Engine, `db2`)].DBInstanceIdentifier'
  local aws_output
  aws_output=$(aws_rds describe-db-instances \
    --region "$REGION" \
    --query "$query" \
    --output text 2>/dev/null)

  local existing_instances=($aws_output)
  if [ ${#existing_instances[@]} -eq 0 ]; then
    log_error "No DB2 instances found in region $REGION"
    return 1
  fi

  if [ -n "${DB_INSTANCE_ID:-}" ]; then
    if [ "$DB_INSTANCE_ID" = "ALL" ]; then
      DB_INSTANCES=("${existing_instances[@]}")
      log_info "Processing ALL DB2 instances: ${DB_INSTANCES[*]}"
      return 0
    fi
    DB_INSTANCES=("$DB_INSTANCE_ID")
    log_info "Using specified instance: $DB_INSTANCE_ID"
    return 0
  fi

  if [ ${#existing_instances[@]} -eq 1 ]; then
    DB_INSTANCES=("${existing_instances[0]}")
    log_info "Auto-selected only available instance: ${existing_instances[0]}"
    return 0
  fi

  # Interactive selection — one instance only
  local choice=-1
  while [ "$choice" -lt 1 ] || [ "$choice" -gt ${#existing_instances[@]} ]; do
    echo "Available DB2 instances:" >&2
    for i in "${!existing_instances[@]}"; do
      echo "$((i+1)). ${existing_instances[$i]}" >&2
    done
    read -p "Select instance (1-${#existing_instances[@]}): " choice
    if [ "$choice" -ge 1 ] && [ "$choice" -le ${#existing_instances[@]} ]; then
      DB_INSTANCES=("${existing_instances[$((choice-1))]}")
    else
      log_warning "Invalid choice"
      choice=-1
    fi
  done
}

# =============================================================================
# Master user names and passwords
# =============================================================================
get_all_master_user_names() {
  MASTER_USER_NAMES=()
  for db_instance in "${DB_INSTANCES[@]}"; do
    local name
    name=$(aws_rds describe-db-instances \
      --db-instance-identifier "$db_instance" \
      --region "$REGION" \
      --query "DBInstances[0].MasterUsername" \
      --output text 2>/dev/null)
    [ "$name" = "None" ] && name=""
    MASTER_USER_NAMES+=("$name")
    log_info "Master user for $db_instance: ${name:-<not found>}"
  done
}

get_all_master_passwords() {
  MASTER_USER_PASSWORDS=()
  local password_file="$HOME/.need_password"

  for db_instance in "${DB_INSTANCES[@]}"; do
    local secret_arn
    secret_arn=$(aws_rds describe-db-instances \
      --db-instance-identifier "$db_instance" \
      --region "$REGION" \
      --query "DBInstances[0].MasterUserSecret.SecretArn" \
      --output text 2>/dev/null)

    if [ -n "$secret_arn" ] && [ "$secret_arn" != "None" ]; then
      local secret_json password
      secret_json=$(aws secretsmanager get-secret-value \
        --secret-id "$secret_arn" \
        --region "$REGION" \
        --query "SecretString" \
        --output text 2>/dev/null)
      password=$(jq -r '.password' <<< "$secret_json")
      if [ -n "$password" ]; then
        log_info "Retrieved password from Secrets Manager for $db_instance"
        MASTER_USER_PASSWORDS+=("$password")
        continue
      fi
    fi

    # Fall back to .need_password file. This is a DEVELOPMENT/TEST-ONLY path for
    # instances not using Secrets Manager. The file MUST be created with
    # `chmod 600 ~/.need_password` (owner read/write only) and MUST NEVER be
    # committed to version control or shared. For production, provision with
    # --manage-master-user-password so RDS stores and rotates the master
    # credential in Secrets Manager instead of keeping plaintext on disk.
    local file_password=""
    if [ -f "$password_file" ]; then
      file_password=$(grep "^$db_instance " "$password_file" 2>/dev/null | cut -d' ' -f2-)
    fi

    if [ -n "$file_password" ] && [ "$file_password" != "replace this with the master user password" ]; then
      log_warning "Using password from $password_file for $db_instance (dev/test only — use --manage-master-user-password in production)"
      MASTER_USER_PASSWORDS+=("$file_password")
    else
      log_warning "No password found for $db_instance — prompting"
      read -rsp "Password for $db_instance: " entered_password; echo
      MASTER_USER_PASSWORDS+=("${entered_password:-}")
    fi
  done
}

# =============================================================================
# Database name discovery
# =============================================================================
#
# Resolution order:
#   1. DB_NAMES env var  — comma-separated list, e.g. DB_NAMES=DB2DB,MYDB
#                          (useful for automation or when RDSADMIN is inaccessible)
#   2. DBName field on the RDS instance  (single-database, most common case)
#   3. Bootstrap connect to RDSADMIN + rdsadmin.list_databases()
#      — requires the connecting user to have CONNECT on RDSADMIN
#      — when domain-joined, this uses the Kerberos TGT (no master user/password)
#      — when Kerberos is active but the AD user lacks RDSADMIN access, this
#        step fails and the script falls through to the interactive prompt
#   4. Interactive prompt  — user enters names manually; skipped when stdin
#                            is not a terminal (non-interactive mode)
#
get_all_database_names() {
  local db_instance_id="$1" master_user="$2" master_password="$3" temp_dsn="${4:-RDSADMIN}"
  DB_NAMES=()

  # --- Resolution 1: DB_NAMES env var ---
  if [ -n "${DB_NAMES_INPUT:-}" ]; then
    IFS=',' read -ra DB_NAMES <<< "$DB_NAMES_INPUT"
    # Trim whitespace from each entry
    DB_NAMES=("${DB_NAMES[@]// /}")
    log_info "Using database list from DB_NAMES env var: ${DB_NAMES[*]}"
    return 0
  fi

  # --- Resolution 2: DBName field on the RDS instance ---
  local default_dbname
  default_dbname=$(aws_rds describe-db-instances \
    --db-instance-identifier "$db_instance_id" \
    --region "$REGION" \
    --query "DBInstances[0].DBName" \
    --output text 2>/dev/null)
  [ "$default_dbname" = "None" ] && default_dbname=""

  if [ -n "$default_dbname" ]; then
    log_info "Default database from RDS metadata: $default_dbname"
    DB_NAMES=("$default_dbname")
    return 0
  fi

  # --- Resolution 3: Bootstrap connect to RDSADMIN ---
  log_info "No default database set — attempting RDSADMIN bootstrap query"
  local connect_out connect_rc
  if [ "${IS_DOMAIN_JOINED:-false}" = "true" ]; then
    connect_out=$(db2 "connect to $temp_dsn" 2>&1)
    connect_rc=$?
  else
    connect_out=$(db2 "connect to $temp_dsn user $master_user using '$master_password'" 2>&1)
    connect_rc=$?
  fi

  if [ $connect_rc -eq 0 ]; then
    local db_names_raw
    mapfile -t db_names_raw < <(
      db2 -x "SELECT database_name FROM TABLE(rdsadmin.list_databases()) WHERE UPPER(database_name) <> 'RDSADMIN'" 2>/dev/null
    )
    db2 connect reset >/dev/null 2>&1 || true

    local db_names_clean=()
    for dbname in "${db_names_raw[@]}"; do
      dbname="$(echo "$dbname" | xargs)"
      [[ -n "$dbname" && ! "$dbname" =~ ^SQL ]] && db_names_clean+=("$dbname")
    done

    if [ ${#db_names_clean[@]} -gt 0 ]; then
      DB_NAMES=("${db_names_clean[@]}")
      log_info "Found ${#DB_NAMES[@]} database(s) via RDSADMIN: ${DB_NAMES[*]}"
      return 0
    fi
    log_warning "RDSADMIN connect succeeded but no user databases found"
  else
    db2 connect reset >/dev/null 2>&1 || true
    log_warning "RDSADMIN bootstrap connect failed (rc=$connect_rc)"
    if [ "${IS_DOMAIN_JOINED:-false}" = "true" ]; then
      local principal
      principal=$(klist 2>/dev/null | awk '/^Default principal:/ {print $3}')
      log_warning "Kerberos principal '${principal}' may not have CONNECT privilege on RDSADMIN."
      log_warning "This is expected — RDSADMIN is protected and AD users are not granted access by default."
    fi
  fi

  # --- Resolution 4: Interactive prompt ---
  log_info "------------------------------------------------------------"
  log_info "Cannot discover databases automatically for $db_instance_id."
  log_info "To skip this prompt next time, set before running:"
  log_info "  DB_NAMES=DB2DB,MYDB REGION=$REGION source db2client-configure.sh"
  log_info "------------------------------------------------------------"

  if [ -t 0 ]; then
    local input
    read -rp "Enter database name(s) for $db_instance_id (comma-separated, or Enter to skip): " input
    if [ -n "$input" ]; then
      IFS=',' read -ra DB_NAMES <<< "$input"
      DB_NAMES=("${DB_NAMES[@]// /}")
      log_info "Registering databases: ${DB_NAMES[*]}"
      return 0
    fi
    log_warning "No databases entered — only the RDSDBSSL admin DSN will be created for $db_instance_id"
  else
    log_warning "Non-interactive mode and no DB_NAMES set — only the admin DSN will be created"
    log_warning "Re-run with: DB_NAMES=<name1,name2> REGION=$REGION source db2client-configure.sh"
  fi

  return 0  # not fatal — admin DSN is still useful
}

# =============================================================================
# DSN helpers
# =============================================================================
#
# Naming convention (all aliases must be ≤ 8 characters):
#
#   Admin database (RDSADMIN):
#     RDSAT    — TCP,  local auth (SERVER_ENCRYPT)
#     RDSAS    — SSL,  local auth
#     RDSAKS   — SSL,  Kerberos
#
#   User databases (<DB>, truncated to fit):
#     <DB>T    — TCP,  local auth
#     <DB>S    — SSL,  local auth
#     <DB>SK   — SSL,  Kerberos
#
#   Multi-instance: numeric index appended before the type suffix,
#   e.g. RDSAT0 / RDSAT1, DB2DB0T / DB2DB0S / DB2DB0SK
#
# generate_db_alias NAME SUFFIX [INSTANCE_SUFFIX]
#   Builds a user-DB alias that fits in 8 chars including BOTH the type suffix
#   and the optional multi-instance index, e.g. generate_db_alias DB2DB SK 0 -> DB2DB0SK.
#   The instance index is placed before the type suffix (matching the documented
#   DB2DB0SK convention) and is counted against the 8-char budget so callers must
#   NOT append ${SUFFIX} themselves.
#   SUFFIX = T | S | SK  (1-2 chars);  INSTANCE_SUFFIX = "" | 0 | 1 | ...
generate_db_alias() {
  local raw="${1^^}" suffix="${2}" instance_suffix="${3:-}"
  local maxbase=$(( 8 - ${#suffix} - ${#instance_suffix} ))
  (( maxbase < 0 )) && maxbase=0
  local base="${raw:0:$maxbase}"
  echo "${base}${instance_suffix}${suffix}"
}

writecfg_tcp() {
  local dsn=$1 dbname=$2 host=$3 port=$4
  db2cli writecfg add -dsn "$dsn" -database "$dbname" -host "$host" -port "$port" \
    -parameter "Authentication=SERVER_ENCRYPT"
}

# SSL + local auth (SERVER_ENCRYPT)
writecfg_ssl_local() {
  local dsn=$1 dbname=$2 host=$3 port=$4
  local cert_file="${SSL_CERT_FILE:-$HOME/$REGION-bundle.pem}"
  db2cli writecfg add -dsn "$dsn" -database "$dbname" -host "$host" -port "$port" \
    -parameter "SSLServerCertificate=${cert_file};SecurityTransportMode=SSL;TLSVersion=TLSV12"
}

# SSL + Kerberos
writecfg_ssl_krb() {
  local dsn=$1 dbname=$2 host=$3 port=$4
  local cert_file="${SSL_CERT_FILE:-$HOME/$REGION-bundle.pem}"
  db2cli writecfg add -dsn "$dsn" -database "$dbname" -host "$host" -port "$port" \
    -parameter "Authentication=KERBEROS;KRBPlugin=IBMkrb5;SSLServerCertificate=${cert_file};SecurityTransportMode=SSL;TLSVersion=TLSV12"
}

# =============================================================================
# Read parameter group values for a given instance
# Returns the ParameterValue or "" if not found / None
# =============================================================================
get_param_group_name() {
  # Sets global PARAM_GROUP for the current DB_INSTANCE_IDENTIFIER
  PARAM_GROUP=$(aws_rds describe-db-instances \
    --db-instance-identifier "$DB_INSTANCE_IDENTIFIER" \
    --region "$REGION" \
    --query "DBInstances[0].DBParameterGroups[0].DBParameterGroupName" \
    --output text 2>/dev/null)
  [ "$PARAM_GROUP" = "None" ] && PARAM_GROUP=""
}

get_param_value() {
  local param_name="$1"
  [ -z "${PARAM_GROUP:-}" ] && echo "" && return
  local val
  val=$(aws_rds describe-db-parameters \
    --db-parameter-group-name "$PARAM_GROUP" \
    --region "$REGION" \
    --query "Parameters[?ParameterName=='${param_name}'].ParameterValue" \
    --output text 2>/dev/null)
  [ "$val" = "None" ] && val=""
  echo "$val"
}

get_ssl_port() {
  get_param_value "ssl_svcename"
}

# Returns the db2comm value from the parameter group (e.g. "SSL", "TCPIP", "TCPIP,SSL")
get_db2comm() {
  local raw
  raw=$(get_param_value "db2comm")
  # Normalise: upper-case, strip spaces
  echo "${raw^^}" | tr -d ' '
}

# True when db2comm contains TCPIP (and so TCP connections are allowed)
db2comm_has_tcpip() {
  local comm="$1"
  [[ "$comm" == *"TCPIP"* ]]
}

# True when db2comm is set to SSL-only (no TCPIP)
db2comm_ssl_only() {
  local comm="$1"
  [[ "$comm" == "SSL" ]]
}

download_pem_file() {
  # Sets global SSL_CERT_FILE to the path of the cert Db2 should trust.
  #
  # Standard endpoint  (E_URL not set):
  #   Downloads <region>-bundle.pem from the public RDS truststore.
  #   The bundle is reordered so RSA2048 is first (Db2 CLP requirement).
  #
  # Custom endpoint  (E_URL set — PrivateLink, siteb, internal domain):
  #   The server presents a cert signed by an internal/Preprod CA that is
  #   NOT in the public RDS bundle. Instead, the root CA is extracted live
  #   from the server's TLS chain and saved as <region>-siteb-root-ca.pem.
  #   Only the root is needed — GSKit walks the chain from root to leaf.

  if [ -n "${E_URL:-}" ]; then
    _download_pem_custom_endpoint "$@"
  else
    _download_pem_standard "$@"
  fi
}

_download_pem_standard() {
  local pem_file="$HOME/$REGION-bundle.pem"
  SSL_CERT_FILE="$pem_file"

  if [ -f "$pem_file" ]; then
    log_info "SSL certificate already present: $pem_file"
    return 0
  fi

  if [ -n "${BUCKET:-}" ]; then
    log_info "Downloading SSL certificate from s3://$BUCKET/ssl/$REGION-bundle.pem ..."
    aws s3 cp "s3://$BUCKET/ssl/$REGION-bundle.pem" "$pem_file" \
      --region "$REGION" --quiet
  else
    local url
    url=$(rds_truststore_url "$REGION")
    log_info "Downloading SSL certificate from $url ..."
    curl -sL "$url" -o "$pem_file"
  fi
  if [ $? -ne 0 ]; then
    log_error "Failed to download SSL certificate"
    return 1
  fi

  # Reorder certificates so RSA2048 is first.
  # Db2 CLP picks the first cert in the bundle for the TLS handshake.
  # RDS for Db2 only has RSA2048 — if RSA4096 is first (e.g. us-west-1)
  # the CLP connection fails. Python/JCC drivers iterate all certs so
  # they are unaffected. This reorder is a no-op for regions where
  # RSA2048 is already first (e.g. us-east-1).
  if command -v openssl &>/dev/null; then
    local tmp_pem; tmp_pem=$(mktemp)
    awk '
      /-----BEGIN CERTIFICATE-----/ { cert=""; in_cert=1 }
      in_cert { cert = cert $0 "\n" }
      /-----END CERTIFICATE-----/ { certs[++n] = cert; in_cert=0 }
      END {
        first=""; rest=""
        for (i=1; i<=n; i++) {
          cmd = "echo \"" certs[i] "\" | openssl x509 -noout -subject 2>/dev/null"
          cmd | getline subj; close(cmd)
          if (subj ~ /RSA2048/) { first = certs[i] }
          else { rest = rest certs[i] }
        }
        printf "%s%s", first, rest
      }
    ' "$pem_file" > "$tmp_pem"
    if [ -s "$tmp_pem" ]; then
      mv -f "$tmp_pem" "$pem_file"
      log_info "SSL cert reordered: RSA2048 first (Db2 CLP compatibility)"
    else
      rm -f "$tmp_pem"
      log_warning "SSL cert reorder skipped — openssl subject parse returned empty"
    fi
  else
    log_warning "openssl not found — skipping cert reorder (Db2 CLP may fail on regions where RSA2048 is not first)"
  fi

  log_success "SSL certificate saved to $pem_file"
}

_download_pem_custom_endpoint() {
  # For custom/internal endpoints the server presents a cert signed by an
  # internal CA (e.g. Amazon RDS Preprod Root CA) that is not in the public
  # RDS bundle. Extract the root CA directly from the live TLS chain.
  #
  # The DB_ADDRESS global must be set before this is called (set in configure_dsn).

  local root_ca_file="$HOME/$REGION-siteb-root-ca.pem"
  SSL_CERT_FILE="$root_ca_file"

  if [ -f "$root_ca_file" ]; then
    log_info "Custom endpoint root CA already present: $root_ca_file"
    return 0
  fi

  if [ -z "${DB_ADDRESS:-}" ]; then
    log_error "DB_ADDRESS not set — cannot extract root CA from custom endpoint"
    return 1
  fi

  if ! command -v openssl &>/dev/null; then
    log_error "openssl not found — required to extract root CA from custom endpoint"
    return 1
  fi

  log_info "Custom endpoint detected (E_URL set) — extracting root CA from TLS chain ..."
  log_info "Connecting to $DB_ADDRESS:${SSL_PORT:-50443} ..."

  # Pull full chain, skip the leaf (cert #1), save intermediate + root
  local full_chain
  full_chain=$(openssl s_client \
    -connect "${DB_ADDRESS}:${SSL_PORT:-50443}" \
    -showcerts \
    2>/dev/null </dev/null)

  if [ -z "$full_chain" ]; then
    log_error "Could not retrieve TLS chain from $DB_ADDRESS:${SSL_PORT:-50443}"
    return 1
  fi

  # Extract root CA — the last self-signed cert in the chain
  # (issuer == subject). Works for chains of any depth.
  echo "$full_chain" | awk '
    /-----BEGIN CERTIFICATE-----/ { n++; cert="" }
    { cert = cert $0 "\n" }
    /-----END CERTIFICATE-----/ { certs[n] = cert }
    END { print certs[n] }
  ' > "$root_ca_file"

  if [ ! -s "$root_ca_file" ]; then
    log_error "Failed to extract root CA from TLS chain"
    rm -f "$root_ca_file"
    return 1
  fi

  # Verify it's actually self-signed (root CA)
  local issuer subject
  issuer=$(openssl x509 -noout -issuer  -in "$root_ca_file" 2>/dev/null | sed 's/issuer=//')
  subject=$(openssl x509 -noout -subject -in "$root_ca_file" 2>/dev/null | sed 's/subject=//')
  if [ "$issuer" != "$subject" ]; then
    log_warning "Extracted cert may not be a root CA (issuer != subject)"
    log_warning "issuer:  $issuer"
    log_warning "subject: $subject"
  fi

  log_success "Root CA extracted: $root_ca_file"
  log_info "  Subject: $subject"
}

build_connect_help_rt() {
  local alias_name=$1 db_name=$2 use_kerberos=${3:-false}
  if [ "$use_kerberos" = "true" ]; then
    HELP_COMMANDS+=("db2 \"connect to ${alias_name}\"  # ${db_name}")
  else
    HELP_COMMANDS+=("db2 \"connect to ${alias_name} user ${MASTER_USER_NAME} using '\$MASTER_USER_PASSWORD'\"  # ${db_name}")
  fi
}

print_all_help() {
  [ ${#HELP_COMMANDS[@]} -eq 0 ] && return
  echo ""
  echo "  ========================="
  echo "  db2 terminate"
  for c in "${HELP_COMMANDS[@]}"; do echo "  $c"; done
  echo "  ========================="
  echo ""
}

# =============================================================================
# Main DSN configuration
# =============================================================================
configure_dsn() {
  log_info "============================================================================"
  log_info "Creating DB2 RT DSN entries for RDS DB2 instance(s)"
  log_info "Region: $REGION"
  log_info "============================================================================"

  detect_domain_join
  list_db_instances || return 1
  get_all_master_user_names
  get_all_master_passwords

  # Clean slate before writing any DSN entries
  rm -f "$HOME/sqllib/cfg/db2dsdriver.cfg"

  for i in "${!DB_INSTANCES[@]}"; do
    local DB_INSTANCE_IDENTIFIER="${DB_INSTANCES[$i]}"
    local MASTER_USER_NAME="${MASTER_USER_NAMES[$i]}"
    local MASTER_USER_PASSWORD="${MASTER_USER_PASSWORDS[$i]}"
    local SUFFIX; [ ${#DB_INSTANCES[@]} -eq 1 ] && SUFFIX="" || SUFFIX="$i"

    log_info "============================================================================"
    log_info "Processing: $DB_INSTANCE_IDENTIFIER"

    [ -z "$MASTER_USER_NAME" ]     && log_error "No master user for $DB_INSTANCE_IDENTIFIER — skipping" && continue
    [ -z "$MASTER_USER_PASSWORD" ] && log_warning "No password for $DB_INSTANCE_IDENTIFIER — skipping"  && continue

    local DB_ADDRESS DB_TCP_IP_PORT
    DB_ADDRESS=$(aws_rds describe-db-instances \
      --db-instance-identifier "$DB_INSTANCE_IDENTIFIER" \
      --region "$REGION" \
      --query "DBInstances[0].Endpoint.Address" \
      --output text 2>/dev/null)
    DB_TCP_IP_PORT=$(aws_rds describe-db-instances \
      --db-instance-identifier "$DB_INSTANCE_IDENTIFIER" \
      --region "$REGION" \
      --query "DBInstances[0].Endpoint.Port" \
      --output text 2>/dev/null)

    [ -z "$DB_ADDRESS" ] && log_error "No endpoint for $DB_INSTANCE_IDENTIFIER — skipping" && continue

    # -----------------------------------------------------------------------
    # Read parameter group values for this instance
    # -----------------------------------------------------------------------
    get_param_group_name   # sets $PARAM_GROUP

    local DB2COMM SSL_PORT
    DB2COMM=$(get_db2comm)
    SSL_PORT=$(get_ssl_port)

    # Default to TCPIP if db2comm is not set in the parameter group
    [ -z "$DB2COMM" ] && DB2COMM="TCPIP"

    log_info "db2comm : ${DB2COMM} | ssl_svcename : ${SSL_PORT:-<not set>}"

    local WANT_TCP=false WANT_SSL=false
    db2comm_has_tcpip "$DB2COMM" && WANT_TCP=true
    [ -n "$SSL_PORT" ]           && WANT_SSL=true

    if [ "$WANT_SSL" = "false" ] && [ "$WANT_TCP" = "false" ]; then
      log_warning "Neither TCPIP port nor ssl_svcename configured for $DB_INSTANCE_IDENTIFIER — skipping"
      continue
    fi

    # -----------------------------------------------------------------------
    # Bootstrap: write a temporary DSN to discover database names.
    # Use SSL (local auth) when db2comm is SSL-only; otherwise use TCP.
    # -----------------------------------------------------------------------
    local TEMP_DSN="RDSTMP${SUFFIX}"
    if [ "$WANT_TCP" = "true" ]; then
      writecfg_tcp "$TEMP_DSN" "RDSADMIN" "$DB_ADDRESS" "$DB_TCP_IP_PORT" >/dev/null 2>&1
    else
      # SSL-only — download cert first (sets SSL_CERT_FILE)
      if ! download_pem_file; then
        log_error "Cannot download SSL cert for $DB_INSTANCE_IDENTIFIER — skipping"
        continue
      fi
      # Bootstrap always uses local auth — Kerberos DSNs are written after discovery
      writecfg_ssl_local "$TEMP_DSN" "RDSADMIN" "$DB_ADDRESS" "$SSL_PORT" >/dev/null 2>&1
    fi

    # Fetch database names using the temporary DSN
    get_all_database_names "$DB_INSTANCE_IDENTIFIER" "$MASTER_USER_NAME" "$MASTER_USER_PASSWORD" "$TEMP_DSN" || true
    log_info "Databases to register: ${DB_NAMES[*]:-<none found>}"

    # Remove temp DSN — final entries written below
    db2cli writecfg remove -dsn "$TEMP_DSN" >/dev/null 2>&1 || true

    # -----------------------------------------------------------------------
    # Write TCP DSN entries  (RDSAT / <DB>T)
    # -----------------------------------------------------------------------
    if [ "$WANT_TCP" = "true" ]; then
      local tcp_admin_dsn="RDSAT${SUFFIX}"
      log_info "Creating TCP DSN: $tcp_admin_dsn  (local auth)"
      writecfg_tcp "$tcp_admin_dsn" "RDSADMIN" "$DB_ADDRESS" "$DB_TCP_IP_PORT"
      build_connect_help_rt "$tcp_admin_dsn" "RDSADMIN TCP"
      for dbname in "${DB_NAMES[@]}"; do
        local alias_t; alias_t="$(generate_db_alias "$dbname" "T" "$SUFFIX")"
        log_info "Registering $dbname as $alias_t (TCP local)"
        writecfg_tcp "$alias_t" "$dbname" "$DB_ADDRESS" "$DB_TCP_IP_PORT"
        build_connect_help_rt "$alias_t" "$dbname TCP"
      done
    fi

    # -----------------------------------------------------------------------
    # Write SSL DSN entries  (RDSAS / <DB>S  and, when domain-joined, RDSAKS / <DB>SK)
    # -----------------------------------------------------------------------
    if [ "$WANT_SSL" = "true" ]; then
      # Cert may already be downloaded in the bootstrap block above; idempotent
      if ! download_pem_file; then
        log_warning "SSL cert unavailable — skipping SSL entries for $DB_INSTANCE_IDENTIFIER"
      else
        log_info "SSL port: $SSL_PORT"

        # --- SSL + local auth ---
        local ssl_local_admin="RDSAS${SUFFIX}"
        log_info "Creating SSL DSN: $ssl_local_admin  (local auth)"
        writecfg_ssl_local "$ssl_local_admin" "RDSADMIN" "$DB_ADDRESS" "$SSL_PORT"
        build_connect_help_rt "$ssl_local_admin" "RDSADMIN SSL"

        for dbname in "${DB_NAMES[@]}"; do
          local alias_s; alias_s="$(generate_db_alias "$dbname" "S" "$SUFFIX")"
          log_info "Registering $dbname as $alias_s (SSL local)"
          writecfg_ssl_local "$alias_s" "$dbname" "$DB_ADDRESS" "$SSL_PORT"
          build_connect_help_rt "$alias_s" "$dbname SSL"
        done

        # --- SSL + Kerberos (domain-joined only) ---
        if [ "${IS_DOMAIN_JOINED:-false}" = "true" ]; then
          log_info "Domain-joined host — also creating Kerberos SSL DSN entries"

          local ssl_krb_admin="RDSAKS${SUFFIX}"
          log_info "Creating SSL+Kerberos DSN: $ssl_krb_admin"
          writecfg_ssl_krb "$ssl_krb_admin" "RDSADMIN" "$DB_ADDRESS" "$SSL_PORT"
          build_connect_help_rt "$ssl_krb_admin" "RDSADMIN SSL+Kerberos" "true"

          for dbname in "${DB_NAMES[@]}"; do
            local alias_sk; alias_sk="$(generate_db_alias "$dbname" "SK" "$SUFFIX")"
            log_info "Registering $dbname as $alias_sk (SSL Kerberos)"
            writecfg_ssl_krb "$alias_sk" "$dbname" "$DB_ADDRESS" "$SSL_PORT"
            build_connect_help_rt "$alias_sk" "$dbname SSL+Kerberos" "true"
          done
        fi
      fi
    fi
  done
}

# =============================================================================
# Entry point
# =============================================================================
main() {
  validate || return 1
  set_credentials
  configure_dsn || return 1
  unset DB_INSTANCE_ID   # clean up the user-supplied env var only AFTER configure_dsn has consumed it
  print_all_help | tee "$HOME/CONN_HELP_README.txt" >&2
  log_info "Run 'db2 terminate' then use the commands above (also saved to ~/CONN_HELP_README.txt)"

  # Write instance registry (instance→DSN mapping, no passwords)
  local registry="$HOME/.db2instances"
  # Append or create entry for each instance
  touch "$registry"
  for i in "${!DB_INSTANCES[@]}"; do
    local suffix; [ ${#DB_INSTANCES[@]} -eq 1 ] && suffix="" || suffix="$i"
    # Determine which DSN names were written based on db2comm
    DB_INSTANCE_IDENTIFIER="${DB_INSTANCES[$i]}"
    get_param_group_name
    local comm; comm=$(get_db2comm)
    [ -z "$comm" ] && comm="TCPIP"
    local tcp_dsn="" ssl_dsn="" krb_dsn=""
    local ssl_port_val; ssl_port_val=$(get_ssl_port)
    db2comm_has_tcpip "$comm"  && tcp_dsn="RDSAT${suffix}"
    [ -n "$ssl_port_val" ]   && ssl_dsn="RDSAS${suffix}"
    [ -n "$ssl_port_val" ] && [ "${IS_DOMAIN_JOINED:-false}" = "true" ] && krb_dsn="RDSAKS${suffix}"
    # Remove existing entry for this instance then re-add
    sed -i '' "/^${DB_INSTANCES[$i]}|/d" "$registry" 2>/dev/null || \
    sed -i    "/^${DB_INSTANCES[$i]}|/d" "$registry" 2>/dev/null || true
    echo "${DB_INSTANCES[$i]}|${MASTER_USER_NAMES[$i]}|${tcp_dsn}|${ssl_dsn}|${krb_dsn}|${REGION}" >> "$registry"
  done
  chmod 600 "$registry"
  log_success "Instance registry saved to $registry"

  # Persist credentials for the last processed instance to ~/.db2env
  # Uses printf %q to safely escape special characters in the password.
  local last=$((${#DB_INSTANCES[@]} - 1))
  export MASTER_USER_NAME="${MASTER_USER_NAMES[$last]}"
  export MASTER_USER_PASSWORD="${MASTER_USER_PASSWORDS[$last]}"
  # Default DSN priority: Kerberos SSL > local SSL > TCP
  DB_INSTANCE_IDENTIFIER="${DB_INSTANCES[$last]}"
  get_param_group_name
  local last_comm; last_comm=$(get_db2comm)
  [ -z "$last_comm" ] && last_comm="TCPIP"
  local last_suffix; [ ${#DB_INSTANCES[@]} -eq 1 ] && last_suffix="" || last_suffix="$last"
  local last_ssl_port; last_ssl_port=$(get_ssl_port)
  if [ -n "$last_ssl_port" ] && [ "${IS_DOMAIN_JOINED:-false}" = "true" ]; then
    export DB_DSN="RDSAKS${last_suffix}"
  elif [ -n "$last_ssl_port" ]; then
    export DB_DSN="RDSAS${last_suffix}"
  else
    export DB_DSN="RDSAT${last_suffix}"
  fi
  {
    echo "export REGION=$(printf '%q' "$REGION")"
    echo "export DB_INSTANCE_ID=$(printf '%q' "${DB_INSTANCES[$last]}")"
    echo "export DB_DSN=$(printf '%q' "$DB_DSN")"
    echo "export MASTER_USER_NAME=$(printf '%q' "${MASTER_USER_NAMES[$last]}")"
    echo "export MASTER_USER_PASSWORD=$(printf '%q' "${MASTER_USER_PASSWORDS[$last]}")"
  } > "$HOME/.db2env"
  chmod 600 "$HOME/.db2env"
  log_success "Credentials saved to ~/.db2env — auto-loaded by functions.sh"
  log_success "DSN configuration complete. Connection help saved to ~/CONN_HELP_README.txt"
  # Add source functions.sh to shell profile files if not already there
  local source_line='source ~/functions.sh'
  local comment='# DB2 helper functions'
  for profile in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    [ -f "$profile" ] || continue
    if ! grep -q 'source ~/functions.sh' "$profile" 2>/dev/null; then
      echo '' >> "$profile"
      echo "$comment" >> "$profile"
      echo "$source_line" >> "$profile"
      log_success "Added 'source ~/functions.sh' to $profile"
    fi
  done
  log_info "Run 'source ~/.bashrc' or log out and back in to activate. Then run 'db2_help' to see available helper functions."
  echo "" >&2
  echo "  ============================" >&2
  echo "  source ~/.bashrc"            >&2
  echo "  db2_help"                    >&2
  echo "  ============================" >&2
  echo "" >&2
}

main
