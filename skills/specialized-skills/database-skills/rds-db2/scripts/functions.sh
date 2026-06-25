#!/bin/bash
# =============================================================================
# functions.sh  —  DB2 helper functions for RDS DB2 RT client
# =============================================================================
# Source this file as db2inst1 to get all helper functions:
#   source ~/functions.sh
#
# Quick start:
#   db2_use                 # select instance, fetch credentials
#   db2_connect             # connect using stored credentials
#   db2_test_connection     # diagnose connection problems
# =============================================================================

# Guard against double-loading
[ -n "${_DB2_FUNCTIONS_LOADED:-}" ] && return 0
_DB2_FUNCTIONS_LOADED=1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log_info()    { echo -e "${BLUE}[   INFO]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_error()   { echo -e "${RED}[  ERROR]${NC} $(date '+%H:%M:%S') - $1" >&2; }
log_debug()   { [[ "${VERBOSE:-}" == "true" ]] && echo -e "${CYAN}[ DEBUG]${NC} $(date '+%H:%M:%S') - $1" >&2 || true; }

DB2_ENV_FILE="${HOME}/.db2env"

# =============================================================================
# Credentials
# =============================================================================
set_credentials() {
  if curl -s --connect-timeout 1 http://127.0.0.1:1338/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected AWS CloudShell environment"
    local token creds
    token=$(curl -sX PUT "http://127.0.0.1:1338/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    creds=$(curl -s -H "Authorization: $token" "http://127.0.0.1:1338/latest/meta-data/container/security-credentials")
    export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .AccessKeyId)
    export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .SecretAccessKey)
    export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Token)
    return
  fi
  if curl -s --connect-timeout 1 http://169.254.169.254/latest/meta-data/ >/dev/null 2>&1; then
    log_info "Detected EC2 environment"
    local token role creds
    token=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    role=$(curl -s -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/iam/security-credentials/)
    creds=$(curl -s -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/iam/security-credentials/$role")
    export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .AccessKeyId)
    export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .SecretAccessKey)
    export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Token)
    return
  fi
}

# =============================================================================
# Region detection
# =============================================================================
detect_region() {
  [ -n "${REGION:-}" ] && return 0
  [ -n "${AWS_DEFAULT_REGION:-}" ] && export REGION="$AWS_DEFAULT_REGION" && return 0
  if curl -s --connect-timeout 1 http://169.254.169.254/latest/meta-data/ >/dev/null 2>&1; then
    local token
    token=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    REGION=$(curl -s -H "X-aws-ec2-metadata-token: $token" \
      http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null)
    [ -n "$REGION" ] && export REGION && return 0
  fi
  REGION=$(aws configure get region 2>/dev/null)
  [ -n "$REGION" ] && export REGION && return 0
  log_error "Cannot detect region. Set: export REGION=us-east-1"
  return 1
}

# =============================================================================
# Persistent env file — ~/.db2env
# =============================================================================

# Save current instance credentials to ~/.db2env
# WARNING: ~/.db2env contains the master password. It is written `chmod 600`
# (owner-only), but it MUST NEVER be (1) committed to version control,
# (2) shared with others, (3) backed up to unencrypted storage, or (4) used in
# production AWS environments. For production, obtain credentials from Secrets
# Manager via an IAM role (provision with --manage-master-user-password).
# Uses printf %q to safely escape special characters in the password
# (e.g. $, >, &, !) that would be re-expanded or misinterpreted by the
# shell when the file is sourced later.
db2_save_env() {
  {
    echo "export REGION=$(printf '%q' "${REGION:-}")"
    echo "export DB_INSTANCE_ID=$(printf '%q' "${DB_INSTANCE_ID:-}")"
    echo "export DB_DSN=$(printf '%q' "${DB_DSN:-}")"
    echo "export MASTER_USER_NAME=$(printf '%q' "${MASTER_USER_NAME:-}")"
    echo "export MASTER_USER_PASSWORD=$(printf '%q' "${MASTER_USER_PASSWORD:-}")"
  } > "$DB2_ENV_FILE"
  chmod 600 "$DB2_ENV_FILE"
  log_success "Credentials saved to $DB2_ENV_FILE"
}

# Load credentials from ~/.db2env
db2_load_env() {
  if [ ! -f "$DB2_ENV_FILE" ]; then
    log_warning "$DB2_ENV_FILE not found — run db2_use first"
    return 1
  fi
  source "$DB2_ENV_FILE"
  log_success "Loaded: instance=$DB_INSTANCE_ID dsn=$DB_DSN user=$MASTER_USER_NAME"
}

# Show current active instance/credentials
db2_show_env() {
  echo "  REGION             : ${REGION:-<not set>}"
  echo "  DB_INSTANCE_ID     : ${DB_INSTANCE_ID:-<not set>}"
  echo "  DB_DSN             : ${DB_DSN:-<not set>}"
  echo "  DB_SSL_DSN         : ${DB_SSL_DSN:-<not set>}"
  echo "  MASTER_USER_NAME   : ${MASTER_USER_NAME:-<not set>}"
  echo "  MASTER_USER_PASSWORD: ${MASTER_USER_PASSWORD:+<set>}${MASTER_USER_PASSWORD:-<not set>}"
}
# Switch active instance — fetches fresh password, rewrites ~/.db2env
# Usage: db2_use [instance-id]
db2_use() {
  local registry="$HOME/.db2instances"
  if [ ! -f "$registry" ]; then
    log_error "No instance registry found. Run db2client-configure.sh first."
    return 1
  fi

  # List available instances from registry
  local instances
  mapfile -t instances < <(cut -d'|' -f1 "$registry")
  if [ ${#instances[@]} -eq 0 ]; then
    log_error "No instances in registry. Run db2client-configure.sh first."
    return 1
  fi

  local selected
  if [ -n "${1:-}" ]; then
    # Validate provided instance exists in registry
    if ! grep -q "^${1}|" "$registry"; then
      log_error "Instance '$1' not found in registry. Available:"
      cut -d'|' -f1 "$registry" | while read -r i; do echo "  $i" >&2; done
      return 1
    fi
    selected="$1"
  elif [ ${#instances[@]} -eq 1 ]; then
    selected="${instances[0]}"
    log_info "Auto-selected: $selected"
  else
    echo "Available DB2 instances:" >&2
    for i in "${!instances[@]}"; do
      local marker=""; [ "${instances[$i]}" = "${DB_INSTANCE_ID:-}" ] && marker=" (active)"
      echo "  $((i+1)). ${instances[$i]}${marker}" >&2
    done
    local choice
    while true; do
      read -p "Select instance (1-${#instances[@]}): " choice
      [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#instances[@]} )) && break
      log_warning "Invalid choice"
    done
    selected="${instances[$((choice-1))]}"
  fi

  # Parse registry entry: instance|master_user|tcp_dsn|ssl_dsn|krb_dsn|region
  # (db2client-configure.sh writes 6 pipe-delimited fields; read all 6 so the
  #  trailing `region` is not corrupted by the krb_dsn field.)
  local entry master_user tcp_dsn ssl_dsn krb_dsn region
  entry=$(grep "^${selected}|" "$registry")
  IFS='|' read -r _ master_user tcp_dsn ssl_dsn krb_dsn region <<< "$entry"

  detect_region || true
  [ -n "$region" ] && export REGION="$region"
  set_credentials

  # Fetch password — Secrets Manager → ~/.need_password → prompt
  local secret_arn secret_json password
  secret_arn=$(aws rds describe-db-instances \
    --db-instance-identifier "$selected" \
    --region "$REGION" \
    --query "DBInstances[0].MasterUserSecret.SecretArn" \
    --output text 2>/dev/null)

  if [ -n "$secret_arn" ] && [ "$secret_arn" != "None" ]; then
    secret_json=$(aws secretsmanager get-secret-value \
      --secret-id "$secret_arn" --region "$REGION" \
      --query "SecretString" --output text 2>/dev/null)
    password=$(jq -r '.password' <<< "$secret_json")
    [ -n "$password" ] && log_success "Password fetched from Secrets Manager"
  fi

  if [ -z "${password:-}" ]; then
    # ~/.need_password is a DEVELOPMENT/TEST-ONLY fallback for instances not
    # using Secrets Manager. It MUST be kept private (`chmod 600`), MUST NEVER be
    # committed to version control, and MUST NEVER be shared or deployed to
    # production. For production, provision with --manage-master-user-password so
    # RDS stores and rotates the credential in Secrets Manager, and do not keep
    # plaintext passwords on disk.
    local file_password
    file_password=$(grep "^${selected} " "$HOME/.need_password" 2>/dev/null | cut -d' ' -f2-)
    if [ -n "$file_password" ] && [ "$file_password" != "replace this with the master user password" ]; then
      password="$file_password"
      log_warning "Password loaded from ~/.need_password (dev/test only — use --manage-master-user-password in production)"
    fi
  fi

  if [ -z "${password:-}" ]; then
    read -rsp "Password for ${master_user}@${selected}: " password; echo
  fi

  export DB_INSTANCE_ID="$selected"
  export MASTER_USER_NAME="$master_user"
  export MASTER_USER_PASSWORD="$password"
  export DB_DSN="$tcp_dsn"
  export DB_SSL_DSN="$ssl_dsn"

  # Write ~/.db2env with printf %q so special chars ($, >, &, !) in the
  # password are shell-escaped and survive being sourced later.
  {
    echo "export REGION=$(printf '%q' "$REGION")"
    echo "export DB_INSTANCE_ID=$(printf '%q' "$selected")"
    echo "export DB_DSN=$(printf '%q' "$tcp_dsn")"
    echo "export DB_SSL_DSN=$(printf '%q' "$ssl_dsn")"
    echo "export MASTER_USER_NAME=$(printf '%q' "$master_user")"
    echo "export MASTER_USER_PASSWORD=$(printf '%q' "$password")"
  } > "$DB2_ENV_FILE"
  chmod 600 "$DB2_ENV_FILE"
  log_success "Active instance: $selected | TCP: $tcp_dsn | SSL: $ssl_dsn"
  log_info    "Connect: db2 \"connect to $tcp_dsn user $master_user using '\$MASTER_USER_PASSWORD'\""
  [ -n "$ssl_dsn" ] && \
  log_info    "SSL:     db2 \"connect to $ssl_dsn user $master_user using '\$MASTER_USER_PASSWORD'\""
}



# Connect to a DSN — uses stored credentials, optional DSN override
# Usage: db2_connect [DSN]
db2_connect() {
  local dsn="${1:-${DB_DSN:-${DB_SSL_DSN:-RDSADMIN}}}"

  if [ -z "${MASTER_USER_NAME:-}" ] || [ -z "${MASTER_USER_PASSWORD:-}" ]; then
    if [ -f "$DB2_ENV_FILE" ]; then
      source "$DB2_ENV_FILE"
    else
      log_error "No credentials loaded. Run db2_use first."
      return 1
    fi
  fi

  # Escape single quotes in password for Db2 CLP: Db2 uses '' inside a
  # single-quoted string to represent a literal single quote.
  local _db2pw="${MASTER_USER_PASSWORD//\'/\'\'}" 
  log_info "Connecting to $dsn as $MASTER_USER_NAME ..."
  db2 "connect to $dsn user $MASTER_USER_NAME using '$_db2pw'"
}

# Disconnect
db2_disconnect() {
  db2 connect reset
  db2 terminate
}

# =============================================================================
# Connection diagnostics
# =============================================================================
db2_test_connection() {
  local dsn="${1:-${DB_DSN:-${DB_SSL_DSN:-RDSADMIN}}}"

  if [ -z "${MASTER_USER_NAME:-}" ] || [ -z "${MASTER_USER_PASSWORD:-}" ]; then
    [ -f "$DB2_ENV_FILE" ] && source "$DB2_ENV_FILE"
  fi

  echo "============================================================================"
  echo "  DB2 Connection Diagnostics"
  echo "  DSN             : $dsn"
  echo "  User            : ${MASTER_USER_NAME:-<not set>}"
  echo "  Password        : ${MASTER_USER_PASSWORD:+<set>}${MASTER_USER_PASSWORD:-<not set>}"
  echo "  DB_INSTANCE_ID  : ${DB_INSTANCE_ID:-<not set>}"
  echo "============================================================================"

  # 1. Check DSN exists in db2dsdriver.cfg
  if db2cli validate -dsn "$dsn" 2>&1 | grep -q "not found\|invalid"; then
    log_error "DSN '$dsn' not found in db2dsdriver.cfg"
    log_info  "Run: db2cli writecfg list  — to see configured DSNs"
    log_info  "Run: BUCKET=... REGION=... source ~/db2client-configure.sh  — to reconfigure"
    return 1
  fi
  log_success "DSN '$dsn' found in db2dsdriver.cfg"

  # 2. Extract host/port from DSN and test TCP reachability
  local host port
  host=$(db2cli validate -dsn "$dsn" 2>/dev/null | grep -i "hostname" | awk '{print $NF}')
  port=$(db2cli validate -dsn "$dsn" 2>/dev/null | grep -i "port"     | awk '{print $NF}')
  if [ -n "$host" ] && [ -n "$port" ]; then
    log_info "Testing TCP connectivity to $host:$port ..."
    if timeout 5 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
      log_success "TCP connection to $host:$port OK"
    else
      log_error "Cannot reach $host:$port — check security group / VPC routing"
      return 1
    fi
  fi

  # 3. Attempt DB2 connect and capture error
  log_info "Attempting db2 connect to $dsn ..."
  local out rc _db2pw
  _db2pw="${MASTER_USER_PASSWORD//\'/\'\'}" 
  out=$(db2 "connect to $dsn user $MASTER_USER_NAME using '$_db2pw'" 2>&1)
  rc=$?

  if [ $rc -eq 0 ]; then
    log_success "Connection successful"
    db2 connect reset >/dev/null 2>&1
    return 0
  fi

  # Diagnose common error codes
  log_error "Connection failed (rc=$rc)"
  echo "$out" >&2

  if echo "$out" | grep -q "SQL30082N"; then
    log_error "Authentication failed — wrong username or password"
    log_info  "Check: MASTER_USER_NAME=$MASTER_USER_NAME"
    log_info  "Run db2_use to refresh credentials"
  elif echo "$out" | grep -q "SQL08001N\|SQL30061N"; then
    log_error "Database not found — DSN may point to wrong database name"
    log_info  "Run: BUCKET=... REGION=... source ~/db2client-configure.sh  — to reconfigure DSNs"
  elif echo "$out" | grep -q "SQL01013N\|TCP"; then
    log_error "Network error — cannot reach DB2 server"
    log_info  "Check security group allows port $port from this host"
  elif echo "$out" | grep -q "GSKit\|SSL\|certificate"; then
    log_error "SSL certificate error"
    log_info  "Check: ls -la ~/$REGION-bundle.pem"
    log_info  "Run: BUCKET=... REGION=... source ~/db2client-configure.sh  — to re-download cert"
  fi
  return 1
}

# List all configured DSNs
db2_list_dsns() {
  log_info "Configured DSNs in db2dsdriver.cfg:"
  db2cli validate -dsn 2>/dev/null | grep -i "data source\|dsn" || \
    cat "$HOME/sqllib/cfg/db2dsdriver.cfg" 2>/dev/null || \
    log_warning "No DSNs found"
}

# =============================================================================
# RDS task monitoring (uses stored credentials)
# =============================================================================
get_task_status() {
  db2_connect RDSADMIN || return 1
  db2 "SELECT VARCHAR(task_type,25) AS task_type,
            VARCHAR(lifecycle,15)   AS lifecycle,
            created_at,
            completed_work_bytes
       FROM TABLE(rdsadmin.get_task_status(null,null,null)) AS r
       ORDER BY created_at DESC"
  db2_disconnect
}

get_task_elapsed() {
  db2_connect RDSADMIN || return 1
  db2 "SELECT task_id,
            VARCHAR(task_type,25)  AS task_type,
            VARCHAR(lifecycle,15)  AS lifecycle,
            NVL(TIMESTAMPDIFF(2, (last_updated_at - created_at)),-1) AS elapsed_seconds
       FROM TABLE(rdsadmin.get_task_status(null,null,null)) AS r
       ORDER BY created_at DESC"
  db2_disconnect
}

get_task_output() {
  db2_connect RDSADMIN || return 1
  db2 "SELECT VARCHAR(r.task_type,25)                       AS task_type,
            VARCHAR(r.lifecycle,15)                         AS lifecycle,
            r.created_at,
            r.completed_work_bytes,
            VARCHAR(bson_to_json(task_input_params),256)    AS input_params,
            VARCHAR(r.task_output,1024)                     AS task_output
       FROM TABLE(rdsadmin.get_task_status(null,null,null)) AS r
       ORDER BY created_at DESC
       LIMIT 1"
  db2_disconnect
}

# =============================================================================
# RDS instance monitoring
# =============================================================================
monitor_db_instance_creation() {
  [ -z "${DB_INSTANCE_ID:-}" ] && log_error "DB_INSTANCE_ID not set. Run db2_use first." && return 1
  detect_region || return 1
  log_info "Monitoring RDS instance '$DB_INSTANCE_ID' ..."
  local status=""
  while [ "$status" != "available" ]; do
    status=$(aws rds describe-db-instances \
      --db-instance-identifier "$DB_INSTANCE_ID" \
      --region "$REGION" \
      --query "DBInstances[0].DBInstanceStatus" \
      --output text 2>/dev/null)
    if [ "$status" = "available" ]; then
      log_success "Instance '$DB_INSTANCE_ID' is available"
    else
      log_info "$(date '+%H:%M:%S') status: $status — waiting 30s ..."
      sleep 30
    fi
  done
}

# =============================================================================
# Help
# =============================================================================
db2_help() {
  echo
  echo "  DB2 Helper Functions (source ~/functions.sh to load)"
  echo "  ======================================================"
  echo
  echo "  Setup"
  echo "    db2_use [instance-id]     Switch active instance — fetches fresh password, rewrites ~/.db2env"
  echo "    db2_load_env              Load saved credentials from ~/.db2env"
  echo "    db2_save_env              Save current credentials to ~/.db2env"
  echo "    db2_show_env              Show current instance/credentials in use"
  echo
  echo "  Connection"
  echo "    db2_connect [DSN]         Connect using stored credentials (default DSN: RDSADMIN)"
  echo "    db2_disconnect            Reset and terminate current connection"
  echo "    db2_list_dsns             List all configured DSNs from db2dsdriver.cfg"
  echo
  echo "  Diagnostics"
  echo "    db2_test_connection [DSN] Test connectivity — checks DSN, TCP, auth, SSL"
  echo
  echo "  RDS Tasks"
  echo "    get_task_status           Show RDS task status (connects to RDSADMIN)"
  echo "    get_task_elapsed          Show RDS task elapsed time"
  echo "    get_task_output           Show latest task output, input params, and lifecycle"
  echo "    monitor_db_instance_creation  Poll instance status until available"
  echo
  echo "  Quick start"
  echo "    db2_use                   # select instance and fetch credentials"
  echo "    db2_connect               # connect using saved credentials"
  echo "    db2_test_connection       # if connection fails, run this to diagnose"
  echo
}

# =============================================================================
# Auto-load ~/.db2env if it exists (silent)
# =============================================================================
[ -f "$DB2_ENV_FILE" ] && source "$DB2_ENV_FILE" 2>/dev/null || true
