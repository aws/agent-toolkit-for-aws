#!/usr/bin/env bash
# Retrieve InfluxDB auth token from AWS Secrets Manager.
# After provisioning, the admin token is stored in the secret referenced by influxAuthParametersSecretArn.
# Usage: ./get_token.sh <secret-arn-or-name> <region>
#
# WARNING: The token is a sensitive credential. This script writes it to a
# restricted file (~/.influxdb_token) rather than printing it to stdout to
# avoid exposure in shell history, terminal logs, or CI/CD output.
set -euo pipefail

SECRET="${1:?Usage: get_token.sh <secret-arn-or-name> <region>}"
REGION="${2:?Usage: get_token.sh <secret-arn-or-name> <region>}"
TOKEN_FILE="${3:-${HOME}/.influxdb_token}"

echo "Retrieving token from Secrets Manager..."

SECRET_VALUE=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text 2>/dev/null) || { echo "ERROR: Failed to retrieve secret. Check ARN and permissions."; exit 1; }

# Parse the token from the JSON secret
TOKEN=$(echo "$SECRET_VALUE" | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
try:
    data = json.loads(raw)
    for key in ['token', 'influxdb_token', 'admin_token', 'api_token']:
        if key in data:
            print(data[key])
            sys.exit(0)
    print('Available keys: ' + ', '.join(data.keys()), file=sys.stderr)
    sys.exit(1)
except json.JSONDecodeError:
    print(raw)
") || { echo "ERROR: Could not parse token from secret. Check secret format — any 'Available keys' line above shows what was found."; exit 1; }

# Write token to a restricted file (umask ensures 600 from creation, no race window)
(umask 077; echo "$TOKEN" > "$TOKEN_FILE")
chmod 600 "$TOKEN_FILE"  # defense-in-depth

echo "Token retrieved successfully and written to: $TOKEN_FILE (mode 600)"
echo ""
echo "To use:"
echo "  export INFLUXDB_TOKEN=\$(cat $TOKEN_FILE)"
echo ""
echo "WARNING: The token is a secret. Do not log, commit, or share this value."
