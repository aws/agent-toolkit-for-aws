#!/usr/bin/env bash
# setup_resolver_rule.sh — Create Route 53 Resolver outbound endpoint + forwarding rule
# Usage: bash setup_resolver_rule.sh --vpc-id <vpc-id> --subnet-1 <subnet-id> --subnet-2 <subnet-id> \
#        --dns-ip-1 <ip> --dns-ip-2 <ip> --odb-cidr <cidr> --region <region> [--domain oraclevcn.com]

set -euo pipefail

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --vpc-id) VPC_ID="$2"; shift 2 ;;
        --subnet-1) SUBNET_1="$2"; shift 2 ;;
        --subnet-2) SUBNET_2="$2"; shift 2 ;;
        --dns-ip-1) DNS_IP_1="$2"; shift 2 ;;
        --dns-ip-2) DNS_IP_2="$2"; shift 2 ;;
        --odb-cidr) ODB_CIDR="$2"; shift 2 ;;
        --region) REGION="$2"; shift 2 ;;
        --domain) DOMAIN="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

DOMAIN="${DOMAIN:-oraclevcn.com}"

echo "=== Route 53 Resolver Setup for ODB@AWS ==="
echo "VPC: ${VPC_ID}"
echo "Subnets: ${SUBNET_1}, ${SUBNET_2}"
echo "DNS Listener IPs: ${DNS_IP_1}, ${DNS_IP_2}"
echo "Domain: ${DOMAIN}"
echo "Region: ${REGION}"
echo ""

# Step 1: Create security group
echo "--- Step 1: Creating security group ---"
SG_ID=$(aws ec2 create-security-group \
  --group-name "odb-resolver-outbound-sg" \
  --description "Route 53 Resolver outbound to ODB DNS" \
  --vpc-id "$VPC_ID" \
  --region "$REGION" \
  --query 'GroupId' --output text)
echo "Created SG: $SG_ID"

# Add egress rules for DNS
aws ec2 authorize-security-group-egress \
  --group-id "$SG_ID" \
  --protocol udp --port 53 \
  --cidr "$ODB_CIDR" \
  --region "$REGION" 2>/dev/null || true

aws ec2 authorize-security-group-egress \
  --group-id "$SG_ID" \
  --protocol tcp --port 53 \
  --cidr "$ODB_CIDR" \
  --region "$REGION" 2>/dev/null || true

echo "Added DNS egress rules"
echo ""

# Step 2: Create outbound endpoint
echo "--- Step 2: Creating outbound endpoint ---"
ENDPOINT_ID=$(aws route53resolver create-resolver-endpoint \
  --name "odb-outbound-endpoint" \
  --direction OUTBOUND \
  --security-group-ids "$SG_ID" \
  --ip-addresses "SubnetId=$SUBNET_1" "SubnetId=$SUBNET_2" \
  --region "$REGION" \
  --query 'ResolverEndpoint.Id' --output text)
echo "Created endpoint: $ENDPOINT_ID"

# Wait for endpoint to be operational
echo "Waiting for endpoint to become OPERATIONAL..."
aws route53resolver wait resolver-endpoint-operational \
  --resolver-endpoint-id "$ENDPOINT_ID" \
  --region "$REGION" 2>/dev/null || \
  sleep 30  # Fallback if wait command not available
echo "Endpoint is ready"
echo ""

# Step 3: Create forwarding rule
echo "--- Step 3: Creating forwarding rule ---"
RULE_ID=$(aws route53resolver create-resolver-rule \
  --name "odb-forward-${DOMAIN//./-}" \
  --rule-type FORWARD \
  --domain-name "$DOMAIN" \
  --resolver-endpoint-id "$ENDPOINT_ID" \
  --target-ips "Ip=$DNS_IP_1,Port=53" "Ip=$DNS_IP_2,Port=53" \
  --region "$REGION" \
  --query 'ResolverRule.Id' --output text)
echo "Created rule: $RULE_ID"
echo ""

# Step 4: Associate rule with VPC
echo "--- Step 4: Associating rule with VPC ---"
aws route53resolver associate-resolver-rule \
  --resolver-rule-id "$RULE_ID" \
  --vpc-id "$VPC_ID" \
  --region "$REGION" >/dev/null
echo "Associated rule with VPC $VPC_ID"
echo ""

echo "=== Setup Complete ✅ ==="
echo ""
echo "Resources created:"
echo "  Security Group: $SG_ID"
echo "  Outbound Endpoint: $ENDPOINT_ID"
echo "  Forwarding Rule: $RULE_ID"
echo ""
echo "Test DNS resolution:"
echo "  dig <scan-hostname> +short"
echo ""
echo "To share this rule with other VPCs, use AWS RAM:"
echo "  aws ram create-resource-share --name odb-resolver-share --resource-arns <rule-arn> --principals <account-id>"
