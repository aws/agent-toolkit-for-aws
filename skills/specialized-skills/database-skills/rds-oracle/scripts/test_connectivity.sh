#!/bin/bash
# Test network connectivity to an RDS Oracle endpoint
# Usage: bash test_connectivity.sh <rds-endpoint> [port]
#
# Checks: DNS resolution, TCP connectivity, port reachability

set -euo pipefail

ENDPOINT="${1:?Usage: $0 <rds-endpoint> [port]}"
PORT="${2:-1521}"

echo "=== RDS Oracle Connectivity Test ==="
echo "Endpoint: ${ENDPOINT}"
echo "Port:     ${PORT}"
echo "Time:     $(date)"
echo ""

# 1. DNS Resolution
echo "--- DNS Resolution ---"
if nslookup "${ENDPOINT}" > /dev/null 2>&1; then
    IP=$(nslookup "${ENDPOINT}" 2>/dev/null | grep -A1 "Name:" | grep "Address:" | head -1 | awk '{print $2}')
    if [ -z "$IP" ]; then
        IP=$(dig +short "${ENDPOINT}" 2>/dev/null | head -1)
    fi
    echo "PASS: ${ENDPOINT} resolves to ${IP:-unknown}"
else
    echo "FAIL: Cannot resolve ${ENDPOINT}"
    echo "  Check: VPC DNS resolution enabled, DNS hostnames enabled"
    exit 1
fi
echo ""

# 2. TCP Connectivity
echo "--- TCP Connectivity (port ${PORT}) ---"
if nc -zw5 "${ENDPOINT}" "${PORT}" 2>/dev/null; then
    echo "PASS: TCP connection to ${ENDPOINT}:${PORT} succeeded"
elif bash -c "echo > /dev/tcp/${ENDPOINT}/${PORT}" 2>/dev/null; then
    echo "PASS: TCP connection to ${ENDPOINT}:${PORT} succeeded (via /dev/tcp)"
else
    echo "FAIL: Cannot connect to ${ENDPOINT}:${PORT}"
    echo "  Check:"
    echo "  - Security group inbound rules allow TCP ${PORT} from your source"
    echo "  - RDS instance is in 'available' state"
    echo "  - Network ACLs allow traffic on port ${PORT}"
    echo "  - If cross-VPC: VPC peering/TGW routes are configured"
    exit 1
fi
echo ""

# 3. Check if this looks like an RDS endpoint
echo "--- Endpoint Validation ---"
if echo "${ENDPOINT}" | grep -q "rds.amazonaws.com"; then
    echo "PASS: Endpoint matches RDS format (*.rds.amazonaws.com)"
    REGION=$(echo "${ENDPOINT}" | sed -n 's/.*\.\([a-z0-9-]*\)\.rds\.amazonaws\.com/\1/p')
    echo "  Region: ${REGION}"
else
    echo "WARN: Endpoint does not match standard RDS format"
    echo "  Expected: <instance>.xxxxxxxxxxxx.<region>.rds.amazonaws.com"
    echo "  This may be a Route 53 CNAME or CMAN endpoint — that's OK"
fi
echo ""

echo "=== All connectivity checks passed ==="
