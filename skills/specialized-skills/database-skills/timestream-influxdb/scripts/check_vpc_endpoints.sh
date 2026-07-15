#!/usr/bin/env bash
# Check if S3 VPC Gateway Endpoint exists for InfluxDB 3 private deployments.
# Usage: ./check_vpc_endpoints.sh <vpc-id> <region>
set -euo pipefail

VPC_ID="${1:?Usage: check_vpc_endpoints.sh <vpc-id> <region>}"
REGION="${2:?Usage: check_vpc_endpoints.sh <vpc-id> <region>}"

echo "Checking S3 VPC endpoints for ${VPC_ID} in ${REGION}..."

ENDPOINTS=$(aws ec2 describe-vpc-endpoints \
  --region "$REGION" \
  --filters "Name=vpc-id,Values=${VPC_ID}" "Name=service-name,Values=com.amazonaws.${REGION}.s3" \
  --query 'VpcEndpoints[*].{Id:VpcEndpointId,State:State,Type:VpcEndpointType,RouteTableIds:RouteTableIds}' \
  --output json 2>/dev/null) || { echo "ERROR: Failed to query VPC endpoints. Check AWS credentials and region."; exit 1; }

COUNT=$(echo "$ENDPOINTS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

if [ "$COUNT" -eq 0 ]; then
  echo ""
  echo "❌ NO S3 VPC endpoint found for ${VPC_ID}"
  echo ""
  echo "InfluxDB 3 requires an S3 Gateway Endpoint in private subnets."
  echo "Create one with:"
  echo ""
  echo "  aws ec2 create-vpc-endpoint \\"
  echo "    --vpc-id ${VPC_ID} \\"
  echo "    --service-name com.amazonaws.${REGION}.s3 \\"
  echo "    --route-table-ids <your-route-table-id> \\"
  echo "    --vpc-endpoint-type Gateway \\"
  echo "    --region ${REGION}"
  echo ""
  echo "Note: The endpoint must be in the SAME account VPC (shared subnets won't work)."
  exit 1
else
  echo ""
  echo "✅ Found ${COUNT} S3 VPC endpoint(s):"
  echo "$ENDPOINTS" | python3 -c "
import sys, json
for ep in json.load(sys.stdin):
    print(f\"  {ep['Id']} — State: {ep['State']}, Type: {ep['Type']}\")
    if ep.get('RouteTableIds'):
        print(f\"    Route tables: {', '.join(ep['RouteTableIds'])}\")
"
  exit 0
fi
