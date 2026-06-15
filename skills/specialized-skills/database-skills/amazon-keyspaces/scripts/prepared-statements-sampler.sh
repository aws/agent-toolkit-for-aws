#!/bin/bash
shopt -s expand_aliases
# The following script exports the cluster's prepared statements as
#   newline-delimited JSON (NDJSON) for Amazon Keyspaces compatibility
#   analysis.
#
# It reads `system.prepared_statements` (which every coordinator maintains
#   in-memory for every CQL statement clients have prepared) and emits one
#   JSON object per statement on stdout.
#
# The prepared statements are used by the Keyspaces calculator skill to
#   detect Cassandra features that are not supported by Amazon Keyspaces:
#     - Lightweight transactions inside `BEGIN UNLOGGED BATCH`
#     - Aggregations (COUNT / MIN / MAX / SUM / AVG)
#     - User-defined function calls (when a schema is also supplied)
#     - Per-table `USING TTL` usage (informational — used to set has_ttl
#       when no default TTL is declared on the table)
#
# The script takes the same parameters as cqlsh to connect to cassandra.
#
# For Amazon Keyspaces, prefer SigV4 authentication (no password needed):
#   ./scripts/prepared-statements-sampler.sh cassandra.us-east-1.amazonaws.com 9142 --ssl
#   (requires the SigV4 auth plugin configured in cqlshrc or the cqlsh-expansion tool)
#
# For source Cassandra clusters with username/password auth, use a cqlshrc credentials file:
#   1. Create ~/.cassandra/cqlshrc with [authentication] section (username + password)
#   2. chmod 600 ~/.cassandra/cqlshrc
#   3. ./scripts/prepared-statements-sampler.sh <host> <port> --ssl > prepared_statements.ndjson
#
# Alternatively, set CQLSH_PASSWORD environment variable (less secure than cqlshrc but avoids CLI args):
#   export CQLSH_PASSWORD="$PASSWORD"
#   ./scripts/prepared-statements-sampler.sh <host> <port> -u "serviceuser" --ssl > prepared_statements.ndjson
#
# NEVER pass passwords via -p on the command line — they are visible in process listings.

# check if the cqlsh-expansion is installed, then if cqlsh installed, then check local file
if [ -x "$(command -v cqlsh-expansion)" ]; then
  echo 'using installed cqlsh-expansion' 1>&2
  alias kqlsh='cqlsh-expansion'
elif [ -x "$(command -v cqlsh)" ]; then
  echo 'using installed cqlsh' 1>&2
  alias kqlsh='cqlsh'
elif [ -e cqlsh ]; then
  echo 'using local cqlsh' 1>&2
  alias kqlsh='./cqlsh'
else
  echo 'cqlsh not found' 1>&2
  exit 1
fi

echo 'starting...' 1>&2

# Filter statements that reference only system keyspaces (driver/cqlsh chatter).
SYSTEMKEYSPACEFILTER='system\.\|system_schema\.\|system_traces\.\|system_auth\.\|system_distributed\.\|dse_\|OpsCenter\.'

# cqlsh prints a header line, a divider of dashes, the rows, a blank line, and
# "(N rows)". We keep only lines that look like a JSON object.
kqlsh "$@" -e "CONSISTENCY LOCAL_ONE; PAGING OFF; SELECT JSON * FROM system.prepared_statements;" \
  | awk '/^[[:space:]]*\{.*\}[[:space:]]*$/' \
  | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' \
  | grep -v "$SYSTEMKEYSPACEFILTER"

echo 'fin!' 1>&2
