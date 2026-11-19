#!/usr/bin/env bash
# check_odb_connectivity.sh — End-to-end ODB@AWS connectivity check
# Usage: bash check_odb_connectivity.sh <scan-hostname> <port>
#
# Checks: DNS resolution, TCP reachability, TCPS handshake (if port 2484)

set -euo pipefail

SCAN_HOST="${1:?Usage: check_odb_connectivity.sh <scan-hostname> <port>}"
PORT="${2:-1521}"

echo "=== ODB@AWS Connectivity Check ==="
echo "Target: ${SCAN_HOST}:${PORT}"
echo ""

# Step 1: DNS Resolution
echo "--- Step 1: DNS Resolution ---"
DNS_RESULT=$(dig +short "$SCAN_HOST" 2>/dev/null || true)
if [ -z "$DNS_RESULT" ]; then
    echo "❌ DNS FAILED: Cannot resolve $SCAN_HOST"
    echo ""
    echo "Likely cause: Route 53 Resolver forwarding rule not set up for oraclevcn.com"
    echo "Fix: Set up outbound endpoint + forwarding rule targeting ODB DNS listener IPs"
    exit 1
else
    IP_COUNT=$(echo "$DNS_RESULT" | wc -l | tr -d ' ')
    echo "✅ DNS OK: Resolved to $IP_COUNT IP(s)"
    echo "$DNS_RESULT" | while read -r ip; do echo "   $ip"; done
fi
echo ""

# Step 2: TCP Reachability
echo "--- Step 2: TCP Reachability (port $PORT) ---"
if command -v nc &>/dev/null; then
    if nc -zv -w 5 "$SCAN_HOST" "$PORT" 2>&1 | grep -q "succeeded\|open\|Connected"; then
        echo "✅ TCP OK: Port $PORT is reachable"
    else
        echo "❌ TCP FAILED: Cannot reach $SCAN_HOST:$PORT"
        echo ""
        echo "Likely causes:"
        echo "  1. Missing route in VPC route table to ODB client subnet CIDR"
        echo "  2. Security group blocking outbound TCP $PORT"
        echo "  3. NACL blocking traffic"
        echo "  4. ODB peering not in AVAILABLE state"
        exit 1
    fi
elif command -v timeout &>/dev/null; then
    if timeout 5 bash -c "echo >/dev/tcp/$SCAN_HOST/$PORT" 2>/dev/null; then
        echo "✅ TCP OK: Port $PORT is reachable"
    else
        echo "❌ TCP FAILED: Cannot reach $SCAN_HOST:$PORT"
        exit 1
    fi
else
    echo "⚠️  Cannot test TCP (nc/timeout not available). Install netcat."
fi
echo ""

# Step 3: TCPS Handshake (only for port 2484 or if explicitly TCPS)
if [ "$PORT" = "2484" ]; then
    echo "--- Step 3: TCPS Handshake ---"
    if command -v openssl &>/dev/null; then
        TLS_RESULT=$(echo | openssl s_client -connect "$SCAN_HOST:$PORT" -servername "$SCAN_HOST" 2>/dev/null | head -5 || true)
        if echo "$TLS_RESULT" | grep -q "CONNECTED"; then
            echo "✅ TCPS OK: TLS handshake succeeded"
            # Show certificate info
            CERT_INFO=$(echo | openssl s_client -connect "$SCAN_HOST:$PORT" -servername "$SCAN_HOST" 2>/dev/null | openssl x509 -noout -subject -dates 2>/dev/null || true)
            if [ -n "$CERT_INFO" ]; then
                echo "   Certificate:"
                echo "$CERT_INFO" | sed 's/^/   /'
            fi
        else
            echo "❌ TCPS FAILED: TLS handshake failed"
            echo ""
            echo "Likely causes:"
            echo "  1. Wrong port (Autonomous DB may use custom TCPS port)"
            echo "  2. Certificate issue"
            exit 1
        fi
    else
        echo "⚠️  Cannot test TCPS (openssl not available)"
    fi
    echo ""
fi

echo "=== All checks passed ✅ ==="
echo "Next: Test application-level connection with your driver"
