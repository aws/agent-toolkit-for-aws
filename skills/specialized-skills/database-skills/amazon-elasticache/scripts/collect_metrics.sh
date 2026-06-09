#!/usr/bin/env bash
# ============================================================
# ElastiCache Metrics Collection Script
#
# Run this on a machine that can connect to your ElastiCache
# cluster endpoints. It collects the data needed for the
# serverless cost estimator.
#
# Usage:
#   ./collect_metrics.sh <endpoint> [port] [output_prefix]
#
# Example:
#   ./collect_metrics.sh my-cluster.abc123.use1.cache.amazonaws.com 6379 my-cluster
#
# NOTE: For Redis OSS (cluster mode enabled) clusters, the INFO command only
# returns data for the node handling the connection, not the entire cluster.
# To get complete metrics for a multi-shard cluster, run this script against
# each shard's primary node individually and aggregate the results. You can
# find per-shard endpoints using:
#   aws elasticache describe-replication-groups --replication-group-id <id>
#
# Requirements:
#   - valkey-cli installed (or redis-cli)
#   - bc (for floating-point math in summary output)
#   - Network access to the ElastiCache endpoint (must run from within the VPC
#     or a bastion/VPN with security group access on port 6379. Running from a
#     local laptop will timeout unless VPN/tunnel is configured.)
#   - For AUTH-enabled clusters, set REDIS_PASSWORD env var
#   - For RBAC (ACL) auth, also set REDIS_USER env var
#   - For non-TLS clusters, set NO_TLS=1
#   - If valkey-cli was compiled without TLS support, set NO_TLS=1
# ============================================================

set -e

ENDPOINT="${1:?Usage: $0 <endpoint> [port] [output_prefix]}"
PORT="${2:-6379}"
PREFIX="${3:-cluster}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Detect CLI
CLI="valkey-cli"
if ! command -v valkey-cli &>/dev/null; then
    if command -v redis-cli &>/dev/null; then
        CLI="redis-cli"
    else
        echo "Error: valkey-cli (or redis-cli) not found. Install with: brew install valkey" >&2
        exit 1
    fi
fi

if [ -n "$REDIS_PASSWORD" ]; then
    export REDISCLI_AUTH="$REDIS_PASSWORD"
fi

# RBAC user support
USER_ARGS=""
if [ -n "${REDIS_USER:-}" ]; then
    USER_ARGS="--user $REDIS_USER"
fi

# TLS support: check if NO_TLS is set, or if the CLI lacks TLS support.
# NOTE: The "$CLI --tls --help" probe below is a best-effort heuristic. Some
# CLI versions may return non-zero even when TLS is supported, or succeed
# without actual TLS support. If this detection gives wrong results, set
# NO_TLS=1 (for non-TLS endpoints) or leave it unset (for TLS endpoints)
# explicitly to bypass the probe.
TLS_ARGS="--tls"
if [ "${NO_TLS:-0}" = "1" ]; then
    TLS_ARGS=""
elif ! $CLI --tls --help &>/dev/null 2>&1; then
    echo "Warning: $CLI does not appear to support --tls (compiled without SSL?)." >&2
    echo "         This check ('$CLI --tls --help') can be unreliable across CLI versions." >&2
    echo "         Set NO_TLS=1 to suppress this check, or rebuild with TLS support." >&2
    echo "         Proceeding without --tls." >&2
    TLS_ARGS=""
fi

if ! command -v bc &>/dev/null; then
    echo "Warning: 'bc' not found. Summary calculations will be skipped." >&2
    NO_BC=1
fi

echo "Collecting metrics from ${ENDPOINT}:${PORT}..."
echo "Using: ${CLI}"

# 1. Memory info
echo "  Collecting memory info..."
$CLI -h "$ENDPOINT" -p "$PORT" $TLS_ARGS $USER_ARGS INFO memory > "${PREFIX}_memory_${TIMESTAMP}.txt"

# 2. Command stats
echo "  Collecting commandstats..."
$CLI -h "$ENDPOINT" -p "$PORT" $TLS_ARGS $USER_ARGS INFO commandstats > "${PREFIX}_commandstats_${TIMESTAMP}.txt"

# 3. Replication info (to identify primary vs replica)
echo "  Collecting replication info..."
$CLI -h "$ENDPOINT" -p "$PORT" $TLS_ARGS $USER_ARGS INFO replication > "${PREFIX}_replication_${TIMESTAMP}.txt"

# 4. Server info (engine version, uptime)
echo "  Collecting server info..."
$CLI -h "$ENDPOINT" -p "$PORT" $TLS_ARGS $USER_ARGS INFO server > "${PREFIX}_server_${TIMESTAMP}.txt"

echo ""
echo "Done. Files created:"
echo "  ${PREFIX}_memory_${TIMESTAMP}.txt"
echo "  ${PREFIX}_commandstats_${TIMESTAMP}.txt"
echo "  ${PREFIX}_replication_${TIMESTAMP}.txt"
echo "  ${PREFIX}_server_${TIMESTAMP}.txt"
echo ""
echo "Key values to extract:"
echo ""

# Extract key metrics
DATASET=$(grep "used_memory_dataset:" "${PREFIX}_memory_${TIMESTAMP}.txt" | cut -d: -f2 | tr -d '[:space:]' || true)
ROLE=$(grep "role:" "${PREFIX}_replication_${TIMESTAMP}.txt" | cut -d: -f2 | tr -d '[:space:]' || true)
UPTIME=$(grep "uptime_in_seconds:" "${PREFIX}_server_${TIMESTAMP}.txt" | cut -d: -f2 | tr -d '[:space:]' || true)

if [ -z "${NO_BC:-}" ]; then
    if [ -n "$DATASET" ]; then
        DATASET_GB=$(echo "scale=4; $DATASET / 1073741824" | bc)
        echo "  used_memory_dataset: ${DATASET} bytes (${DATASET_GB} GB)"
    fi
    if [ -n "$ROLE" ]; then
        echo "  role: ${ROLE}"
    fi
    if [ -n "$UPTIME" ]; then
        UPTIME_DAYS=$(echo "scale=1; $UPTIME / 86400" | bc)
        echo "  uptime: ${UPTIME_DAYS} days"
        echo ""
        echo "To get daily commands, divide each command's 'calls' by ${UPTIME_DAYS}"
    fi
fi

echo ""
echo "Next steps:"
echo "  1. If this is a primary node, use avg_memory_gb = ${DATASET_GB:-<value>}"
echo "  2. Parse commandstats into CSV format for detailed estimation"
echo "  3. Run: python serverless_estimator.py --input clusters.csv --commandstats commandstats.csv"
