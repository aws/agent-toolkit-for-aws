#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
set -euo pipefail

# psql-connect.sh - Connect to Aurora DSQL using psql with IAM auth
#
# Usage: ./psql-connect.sh [CLUSTER_ID|--cluster CLUSTER_ID] [--region REGION] [--user USER] [--admin] [--ai-model MODEL_ID] [--command "SQL" | --script PATH]
#
# Examples:
#   ./psql-connect.sh --cluster abc123def456 --ai-model claude-opus-4-6
#   ./psql-connect.sh abc123def456 --ai-model claude-opus-4-6 --region us-west-2
#   ./psql-connect.sh --cluster abc123def456 --admin
#   ./psql-connect.sh --cluster abc123def456 --command "SELECT * FROM entities LIMIT 5"
#   ./psql-connect.sh --cluster abc123def456 --script ./migration.sql   # multi-statement file

CLUSTER_ID="${CLUSTER:-}"
REGION="${REGION:-${AWS_REGION:-us-east-1}}"
# Note: avoid using bare `USER` here — bash sets it automatically to the login
# user, and overwriting it would clobber that for child processes.
DB_USER_NAME="${DB_USER:-admin}"
ADMIN=false
COMMAND=""
SCRIPT_FILE=""
AI_MODEL=""
SKIP_CERT_VERIFY=false

# require_value FLAG NEXT — validate that a value-taking flag has a non-empty,
# non-flag argument following it. Aborts with a clean error otherwise.
require_value() {
  local flag="$1"
  local next="${2:-}"
  if [[ -z "$next" ]]; then
    echo "Error: $flag requires a value." >&2
    exit 1
  fi
  if [[ "$next" == -* ]]; then
    echo "Error: $flag requires a value, got '$next' (looks like another flag)." >&2
    exit 1
  fi
}

# Track which source supplied CLUSTER_ID so positional+--cluster mismatch is
# caught instead of silently letting the last writer win.
CLUSTER_FROM_FLAG=""
CLUSTER_FROM_POSITIONAL=""

# set_cluster SOURCE VALUE — record the cluster ID from a specific source and
# reject conflicting values from a different source.
set_cluster() {
  local src="$1"
  local val="$2"
  case "$src" in
    flag)
      if [[ -n "$CLUSTER_FROM_POSITIONAL" && "$CLUSTER_FROM_POSITIONAL" != "$val" ]]; then
        echo "Error: cluster id supplied by both --cluster ('$val') and positional ('$CLUSTER_FROM_POSITIONAL'); they disagree." >&2
        exit 1
      fi
      CLUSTER_FROM_FLAG="$val"
      ;;
    positional)
      if [[ -n "$CLUSTER_FROM_FLAG" && "$CLUSTER_FROM_FLAG" != "$val" ]]; then
        echo "Error: cluster id supplied by both positional ('$val') and --cluster ('$CLUSTER_FROM_FLAG'); they disagree." >&2
        exit 1
      fi
      CLUSTER_FROM_POSITIONAL="$val"
      ;;
  esac
  CLUSTER_ID="$val"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --region)
      require_value "$1" "${2:-}"
      REGION="$2"
      shift 2
      ;;
    --user)
      require_value "$1" "${2:-}"
      DB_USER_NAME="$2"
      shift 2
      ;;
    --admin)
      ADMIN=true
      shift
      ;;
    --command|-c)
      require_value "$1" "${2:-}"
      COMMAND="$2"
      shift 2
      ;;
    --script|-f)
      require_value "$1" "${2:-}"
      SCRIPT_FILE="$2"
      shift 2
      ;;
    --cluster)
      require_value "$1" "${2:-}"
      set_cluster flag "$2"
      shift 2
      ;;
    --ai-model)
      require_value "$1" "${2:-}"
      AI_MODEL="$2"
      shift 2
      ;;
    --skip-cert-verify)
      SKIP_CERT_VERIFY=true
      shift
      ;;
    --)
      # End-of-options sentinel — remaining args are positional.
      shift
      while [[ $# -gt 0 ]]; do
        set_cluster positional "$1"
        shift
      done
      break
      ;;
    -h|--help)
      echo "Usage: $0 [CLUSTER_ID|--cluster CLUSTER_ID] [--region REGION] [--user USER] [--admin] [--command SQL | --script PATH]"
      echo ""
      echo "Connect to Aurora DSQL using psql with IAM authentication."
      echo ""
      echo "Arguments:"
      echo "  CLUSTER_ID         Cluster identifier (positional, or via --cluster, or \$CLUSTER env var)"
      echo ""
      echo "Options:"
      echo "  --cluster ID       Cluster identifier (alternative to positional argument)"
      echo "  --region REGION    AWS region (default: \$REGION or \$AWS_REGION or us-east-1)"
      echo "  --user USER        Database user (default: \$DB_USER or 'admin')"
      echo "  --admin            Generate IAM admin auth token (uses generate-db-connect-admin-auth-token)"
      echo "  --command SQL, -c  Execute one SQL statement and exit (single-statement; chained semicolons rejected)"
      echo "  --script PATH, -f  Run a multi-statement SQL file via 'psql -f' (no semicolon guard)"
      echo "  --ai-model ID      AI model identifier appended to application_name (e.g. claude-opus-4-6)"
      echo "  --skip-cert-verify Downgrade TLS to sslmode=require (encrypt only; vulnerable to MITM)."
      echo "                     Do NOT use in production."
      echo "  -h, --help         Show this help message"
      echo ""
      echo "Environment Variables:"
      echo "  CLUSTER            Default cluster identifier"
      echo "  REGION             Default AWS region"
      echo "  DB_USER            Default database user"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      set_cluster positional "$1"
      shift
      ;;
  esac
done

# Validate cluster ID — trim surrounding whitespace and enforce DSQL's
# alphanumeric format. Catches `--cluster ""`, `--cluster "  "`, and accidental
# slashes/dots in the ID before they reach the AWS CLI or psql.
CLUSTER_ID="${CLUSTER_ID#"${CLUSTER_ID%%[![:space:]]*}"}"
CLUSTER_ID="${CLUSTER_ID%"${CLUSTER_ID##*[![:space:]]}"}"
if [[ -z "$CLUSTER_ID" ]]; then
  echo "Error: CLUSTER_ID is required. Set \$CLUSTER env var or pass as argument." >&2
  echo "" >&2
  echo "Usage: $0 [CLUSTER_ID|--cluster CLUSTER_ID] [options]" >&2
  echo "   or: export CLUSTER=abc123 && $0 [options]" >&2
  exit 1
fi
if [[ ! "$CLUSTER_ID" =~ ^[a-z0-9]+$ ]]; then
  echo "Error: CLUSTER_ID '$CLUSTER_ID' is invalid (DSQL cluster IDs are lowercase alphanumeric)." >&2
  exit 1
fi

# Build endpoint
ENDPOINT="${CLUSTER_ID}.dsql.${REGION}.on.aws"

# Generate auth token. Capture stderr alongside stdout so an aws CLI failure
# (expired creds, missing dsql:DbConnect, wrong region) surfaces a useful
# message — under `set -e` the bare command-substitution would otherwise abort
# the script before the empty-token guard below could fire.
echo "Generating IAM auth token for $ENDPOINT..." >&2

if [[ "$ADMIN" == "true" ]]; then
  TOKEN_CMD=(aws dsql generate-db-connect-admin-auth-token --hostname "$ENDPOINT" --region "$REGION")
else
  TOKEN_CMD=(aws dsql generate-db-connect-auth-token --hostname "$ENDPOINT" --region "$REGION")
fi

if ! TOKEN=$("${TOKEN_CMD[@]}" 2>&1); then
  echo "Error: Failed to generate auth token (aws CLI exited non-zero)." >&2
  echo "  Command: ${TOKEN_CMD[*]}" >&2
  echo "  Output:  $TOKEN" >&2
  exit 1
fi

# Check if token generation was successful
if [[ -z "$TOKEN" ]]; then
  echo "Error: Failed to generate auth token (empty result). Check your AWS credentials." >&2
  exit 1
fi

echo "Connecting to $ENDPOINT as $DB_USER_NAME..." >&2
echo "" >&2

# DSQL requires TLS and rejects non-TLS connections. Default to verify-full
# which validates the server certificate against DSQL's CA, preventing MITM
# attacks. Point sslrootcert at the OS trust store so users don't need a
# per-user ~/.postgresql/root.crt. Use --skip-cert-verify to downgrade to
# require (encrypt only).
# See https://docs.aws.amazon.com/aurora-dsql/latest/userguide/accessing-psql.html
if [[ "$SKIP_CERT_VERIFY" == "true" ]]; then
  echo "WARNING: Certificate verification disabled. Connection is vulnerable to MITM attacks. Do NOT use in production." >&2
  export PGSSLMODE=require
else
  export PGSSLMODE=verify-full
  # libpq defaults to ~/.postgresql/root.crt — fall back to the OS trust store
  # when the user has not provisioned a personal CA bundle. Honor any caller-
  # supplied PGSSLROOTCERT (e.g., a corporate bundle) by not overwriting it.
  : "${PGSSLROOTCERT:=system}"
  export PGSSLROOTCERT
fi

# Set application_name with AI model identifier if provided
PGAPPNAME="dsql-skill"
if [[ -n "$AI_MODEL" ]]; then
  # Validate: allow only alphanumeric, hyphens, underscores, and dots
  if [[ ! "$AI_MODEL" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    echo "Error: --ai-model must contain only alphanumeric characters, hyphens, underscores, and dots." >&2
    exit 1
  fi
  PGAPPNAME="dsql-skill/${AI_MODEL}"
fi
export PGAPPNAME

# Sanitize --command input: reject multi-statement chaining and comment injection.
# psql -c runs a single command; allow at most ONE trailing semicolon.
# This is a defense-in-depth measure — callers should also validate inputs.
# Limitations: does not handle escaped quotes (\' or ''), dollar-quoted strings
# ($$...$$), or all edge cases. For complex queries, use --script PATH instead
# to pipe a multi-statement file via stdin without the semicolon guard.
if [[ -n "$COMMAND" && -n "$SCRIPT_FILE" ]]; then
  echo "Error: --command and --script are mutually exclusive." >&2
  exit 1
fi

if [[ -n "$COMMAND" ]]; then
  # Reject whitespace-only --command early so the user gets a clear error
  # rather than psql's downstream syntax message.
  if [[ -z "${COMMAND//[[:space:]]/}" ]]; then
    echo "Error: --command is whitespace-only." >&2
    exit 1
  fi
  # Reject newlines — sed processes the strip-quotes pipeline line by line, so a
  # newline-spanning literal would defeat the multi-statement detector. Use
  # --script for SQL that needs to span multiple lines.
  if [[ "$COMMAND" == *$'\n'* ]]; then
    echo "Error: --command does not support newlines. Use --script PATH for multi-line SQL." >&2
    exit 1
  fi
  # Reject dollar-quoting which can interfere with single-quote stripping
  if echo "$COMMAND" | grep -qE '\$\$|\$[a-zA-Z_][a-zA-Z0-9_]*\$'; then
    echo "Error: Dollar-quoting is not supported in --command. Use --script PATH for SQL with dollar-quoted strings." >&2
    exit 1
  fi

  # Reject multi-statement chaining (semicolons outside string/identifier
  # literals, ignoring an optional trailing whitespace/semicolon at the end).
  # Strip in this order: (1) collapse SQL-standard doubled-quote escapes ('')
  # so the next pass treats them as empty literals; (2) strip single-quoted
  # string literals; (3) strip double-quoted identifiers; (4) trim a single
  # trailing semicolon. Any semicolon that survives is genuine statement
  # chaining.
  stripped=$(echo "$COMMAND" \
    | sed "s/''//g" \
    | sed "s/'[^']*'//g" \
    | sed 's/"[^"]*"//g' \
    | sed -E 's/[[:space:]]*;[[:space:]]*$//')
  if echo "$stripped" | grep -q ';'; then
    echo "Error: Multiple SQL statements are not allowed in --command. Use --script PATH for multi-statement input." >&2
    exit 1
  fi
  # Reject SQL comment sequences that could hide injected code
  if echo "$stripped" | grep -qE -- '--|/\*'; then
    echo "Error: SQL comments (-- or /*) are not allowed in --command. Use --script PATH if you need comments." >&2
    exit 1
  fi

  # Execute command and exit
  exec env PGPASSWORD="$TOKEN" psql \
    -h "$ENDPOINT" \
    -U "$DB_USER_NAME" \
    -d postgres \
    -c "$COMMAND"
elif [[ -n "$SCRIPT_FILE" ]]; then
  # Multi-statement file mode — no semicolon guard. Caller is responsible for
  # the contents of the file; build the SQL with safe_query.build() upstream
  # whenever values come from untrusted input.
  if [[ ! -f "$SCRIPT_FILE" ]]; then
    echo "Error: --script path '$SCRIPT_FILE' is not a regular file." >&2
    exit 1
  fi
  if [[ ! -r "$SCRIPT_FILE" ]]; then
    echo "Error: --script file '$SCRIPT_FILE' is not readable." >&2
    exit 1
  fi
  exec env PGPASSWORD="$TOKEN" psql \
    -P pager=off \
    -v ON_ERROR_STOP=1 \
    -h "$ENDPOINT" \
    -U "$DB_USER_NAME" \
    -d postgres \
    -f "$SCRIPT_FILE"
else
  # Interactive session
  exec env PGPASSWORD="$TOKEN" psql \
    -h "$ENDPOINT" \
    -U "$DB_USER_NAME" \
    -d postgres
fi
