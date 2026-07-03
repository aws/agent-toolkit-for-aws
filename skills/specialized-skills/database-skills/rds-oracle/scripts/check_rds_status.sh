#!/bin/bash
# Check RDS Oracle instance status, endpoint, security groups, and configuration
# Usage: bash check_rds_status.sh <db-instance-identifier> [region]
#
# Requires: AWS CLI configured with appropriate permissions

set -euo pipefail

INSTANCE_ID="${1:?Usage: $0 <db-instance-identifier> [region]}"
REGION="${2:-}"

REGION_ARGS=()
if [ -n "$REGION" ]; then
    REGION_ARGS=(--region "$REGION")
fi

echo "=== RDS Oracle Instance Status ==="
echo "Instance: ${INSTANCE_ID}"
echo "Time:     $(date)"
echo ""

# 1. Basic instance info
echo "--- Instance Details ---"
aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].{
        Status: DBInstanceStatus,
        Engine: Engine,
        EngineVersion: EngineVersion,
        Class: DBInstanceClass,
        Endpoint: Endpoint.Address,
        Port: Endpoint.Port,
        MultiAZ: MultiAZ,
        PubliclyAccessible: PubliclyAccessible,
        StorageEncrypted: StorageEncrypted,
        LicenseModel: LicenseModel
    }' \
    --output table

# 2. Endpoint and port
echo ""
echo "--- Connection Details ---"
ENDPOINT=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].Endpoint.Address' --output text)
PORT=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].Endpoint.Port' --output text)
DB_NAME=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].DBName' --output text)

echo "Endpoint:     ${ENDPOINT}"
echo "Port:         ${PORT}"
echo "DB Name/SID:  ${DB_NAME}"
echo "Connect DSN:  ${ENDPOINT}:${PORT}/${DB_NAME}"
echo ""

# 3. Security groups
echo "--- Security Groups ---"
aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].VpcSecurityGroups[*].{GroupId: VpcSecurityGroupId, Status: Status}' \
    --output table

SG_IDS=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].VpcSecurityGroups[*].VpcSecurityGroupId' --output text)

for SG_ID in ${SG_IDS}; do
    echo "  Inbound rules for ${SG_ID} on port ${PORT}:"
    aws ec2 describe-security-groups \
        --group-ids "${SG_ID}" \
        "${REGION_ARGS[@]}" \
        --query "SecurityGroups[0].IpPermissions[?FromPort==\`${PORT}\` || FromPort==null]" \
        --output table 2>/dev/null || echo "  (no rules found for port ${PORT})"
    echo ""
done

# 4. Public accessibility check
PUBLICLY_ACCESSIBLE=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].PubliclyAccessible' --output text)

if [ "${PUBLICLY_ACCESSIBLE}" = "True" ]; then
    echo "WARNING: Instance is publicly accessible — recommended to disable this"
else
    echo "PASS: Instance is NOT publicly accessible (good)"
fi
echo ""

# 5. Kerberos / Domain membership
echo "--- Kerberos / Domain Membership ---"
DOMAIN_INFO=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].DomainMemberships' --output table 2>/dev/null)

if [ -z "${DOMAIN_INFO}" ] || echo "${DOMAIN_INFO}" | grep -q "None"; then
    echo "Not joined to any directory (Kerberos not configured)"
else
    echo "${DOMAIN_INFO}"
fi
echo ""

# 6. Option groups (SSL/NNE)
echo "--- Option Groups ---"
aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].OptionGroupMemberships[*].{OptionGroupName: OptionGroupName, Status: Status}' \
    --output table
echo ""

# 7. Storage encryption
ENCRYPTED=$(aws rds describe-db-instances \
    --db-instance-identifier "${INSTANCE_ID}" \
    "${REGION_ARGS[@]}" \
    --query 'DBInstances[0].StorageEncrypted' --output text)

if [ "${ENCRYPTED}" = "True" ]; then
    KMS_KEY=$(aws rds describe-db-instances \
        --db-instance-identifier "${INSTANCE_ID}" \
        "${REGION_ARGS[@]}" \
        --query 'DBInstances[0].KmsKeyId' --output text)
    echo "PASS: Storage encryption enabled (KMS key: ${KMS_KEY})"
else
    echo "WARN: Storage encryption is NOT enabled"
fi
echo ""

echo "=== Status check complete ==="
