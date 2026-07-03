#!/bin/bash
# Check security group rules for an RDS Oracle instance
# Usage: bash check_security_groups.sh <db-instance-identifier> [source-sg-or-cidr] [region]
#
# Validates that the RDS security group allows inbound on the Oracle port
# from the specified source (security group ID or CIDR block)

set -euo pipefail

INSTANCE_ID="${1:?Usage: $0 <db-instance-identifier> [source-sg-or-cidr] [region]}"
SOURCE="${2:-}"
REGION="${3:-}"

REGION_ARGS=()
if [ -n "$REGION" ]; then
    REGION_ARGS=(--region "$REGION")
fi

echo "=== Security Group Check for RDS Oracle ==="
echo "Instance: ${INSTANCE_ID}"
echo "Source:   ${SOURCE:-any}"
echo "Time:     $(date)"
echo ""

PORT=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].Endpoint.Port' --output text 2>/dev/null)

if [ -z "$PORT" ] || [ "$PORT" = "None" ]; then
    echo "FAIL: Cannot find instance '${INSTANCE_ID}'"
    exit 1
fi

[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "FAIL: Invalid port value '${PORT}'"; exit 1; }

echo "Oracle port: ${PORT}"
echo ""

SG_IDS=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].VpcSecurityGroups[*].VpcSecurityGroupId' --output text)

FOUND_RULE=false

for SG_ID in ${SG_IDS}; do
    echo "--- Security Group: ${SG_ID} ---"

    RULES=$(aws ec2 describe-security-groups \
        --group-ids "${SG_ID}" \
        "${REGION_ARGS[@]}" \
        --query 'SecurityGroups[0].IpPermissions' --output json)

    ORACLE_RULES=$(echo "${RULES}" | PORT="${PORT}" python3 -c "
import json, sys, os
rules = json.load(sys.stdin)
port = int(os.environ['PORT'])
for rule in rules:
    from_port = rule.get('FromPort', 0)
    to_port = rule.get('ToPort', 0)
    if from_port <= port <= to_port or (from_port == 0 and to_port == 0):
        sources = []
        for cidr in rule.get('IpRanges', []):
            sources.append(cidr.get('CidrIp', ''))
        for sg in rule.get('UserIdGroupPairs', []):
            sources.append(sg.get('GroupId', ''))
        for prefix in rule.get('PrefixListIds', []):
            sources.append(prefix.get('PrefixListId', ''))
        for src in sources:
            print(f'  Port {from_port}-{to_port}: {src}')
" 2>/dev/null)

    if [ -n "${ORACLE_RULES}" ]; then
        echo "  Inbound rules allowing port ${PORT}:"
        echo "${ORACLE_RULES}"

        if [ -n "${SOURCE}" ]; then
            if echo "${ORACLE_RULES}" | grep -qF "${SOURCE}"; then
                echo "  PASS: Source '${SOURCE}' is allowed"
                FOUND_RULE=true
            else
                echo "  WARN: Source '${SOURCE}' NOT found in rules"
            fi
        else
            FOUND_RULE=true
        fi
    else
        echo "  WARN: No inbound rules found for port ${PORT}"
    fi
    echo ""
done

if [ "${FOUND_RULE}" = true ]; then
    if [ -n "${SOURCE}" ]; then
        echo "=== PASS: Security group allows ${SOURCE} on port ${PORT} ==="
    else
        echo "=== PASS: Security group has rules for port ${PORT} ==="
    fi
else
    echo "=== FAIL: No matching security group rule found ==="
    echo "  Fix: Add an inbound rule to the RDS security group:"
    echo "    Protocol: TCP"
    echo "    Port: ${PORT}"
    if [ -n "${SOURCE}" ]; then
        echo "    Source: ${SOURCE}"
    else
        echo "    Source: <your-application-security-group-or-cidr>"
    fi
fi
