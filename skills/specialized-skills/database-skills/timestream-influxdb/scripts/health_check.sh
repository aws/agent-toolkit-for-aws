#!/usr/bin/env bash
# Health check for Timestream for InfluxDB instances/clusters.
# Usage: ./health_check.sh <endpoint> <port> [token] [database] [--insecure]
#
# TLS verification is enabled by default. Use --insecure only for local
# port-forwarding scenarios where the certificate doesn't match localhost.
set -euo pipefail

# Separate the --insecure flag from positional args before assignment, so a
# trailing --insecure is never mistaken for the token/database positional.
INSECURE=false
POSITIONAL=()
for arg in "$@"; do
  if [ "$arg" = "--insecure" ]; then
    INSECURE=true
  else
    POSITIONAL+=("$arg")
  fi
done

ENDPOINT="${POSITIONAL[0]:?Usage: health_check.sh <endpoint> <port> [token] [database] [--insecure]}"
PORT="${POSITIONAL[1]:?Usage: health_check.sh <endpoint> <port> [token] [database] [--insecure]}"

# Validate inputs before building the URL
if ! echo "$ENDPOINT" | grep -qE '^[a-zA-Z0-9.-]+$'; then
  echo "ERROR: Invalid endpoint format (expected a hostname: letters, digits, '.', '-')" >&2
  exit 1
fi
if ! [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "ERROR: Invalid port (must be 1-65535)" >&2
  exit 1
fi

# Token: prefer env var or file over positional arg (avoids exposure in ps/history)
TOKEN="${POSITIONAL[2]:-${INFLUXDB_TOKEN:-}}"
if [ -z "$TOKEN" ] && [ -f "${HOME}/.influxdb_token" ]; then
  TOKEN=$(cat "${HOME}/.influxdb_token")
fi
DB="${POSITIONAL[3]:-}"

CURL_TLS_OPTS=""
if $INSECURE; then
  CURL_TLS_OPTS="-k"
  echo "WARNING: TLS certificate verification disabled (--insecure). Do not use in production."
fi

BASE="https://${ENDPOINT}:${PORT}"

echo "Checking ${BASE}..."

# Ping (no auth required)
echo -n "  /ping: "
HTTP_CODE=$(curl -s $CURL_TLS_OPTS -o /dev/null -w "%{http_code}" "${BASE}/ping" 2>/dev/null) || HTTP_CODE="FAIL"
if [ "$HTTP_CODE" = "204" ] || [ "$HTTP_CODE" = "200" ]; then
  echo "OK ($HTTP_CODE)"
else
  echo "FAILED ($HTTP_CODE)"
fi

# Health (no auth required on most versions)
echo -n "  /health: "
RESP=$(curl -s $CURL_TLS_OPTS -w "\n%{http_code}" "${BASE}/health" 2>/dev/null) || RESP="FAIL"
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
if [ "$HTTP_CODE" = "200" ]; then
  echo "OK — $BODY"
else
  echo "FAILED ($HTTP_CODE)"
fi

# Authenticated query test (if token provided)
if [ -n "$TOKEN" ]; then
  echo -n "  Auth test: "
  if [ "$PORT" = "8086" ]; then
    # V2 — check /api/v2/buckets
    HTTP_CODE=$(curl -s $CURL_TLS_OPTS -o /dev/null -w "%{http_code}" -H "Authorization: Token ${TOKEN}" "${BASE}/api/v2/buckets?limit=1" 2>/dev/null) || HTTP_CODE="FAIL"
  elif [ -n "$DB" ]; then
    # V3 — check /api/v3/query_sql with a real database
    HTTP_CODE=$(curl -s $CURL_TLS_OPTS -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d "{\"db\":\"${DB}\",\"q\":\"SELECT 1\"}" "${BASE}/api/v3/query_sql" 2>/dev/null) || HTTP_CODE="FAIL"
  else
    echo "SKIPPED — provide a database name as 4th arg for V3 auth test"
    HTTP_CODE=""
  fi
  if [ -n "$HTTP_CODE" ]; then
    if [ "$HTTP_CODE" = "200" ]; then
      echo "OK — authenticated"
    else
      echo "FAILED ($HTTP_CODE) — check token"
    fi
  fi
fi

echo "Done."
