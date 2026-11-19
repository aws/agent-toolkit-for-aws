#!/usr/bin/env bash
# fetch_odb_network_info.sh — Retrieve ODB network details via aws odb CLI
# Usage: bash fetch_odb_network_info.sh <odb-network-id> <region>

set -euo pipefail

ODB_NETWORK_ID="${1:?Usage: fetch_odb_network_info.sh <odb-network-id> <region>}"
REGION="${2:?Region required}"

echo "=== ODB Network Details ==="
echo "Network ID: ${ODB_NETWORK_ID}"
echo "Region: ${REGION}"
echo ""

# Describe ODB network
echo "--- Network Configuration ---"
aws odb get-odb-network \
  --odb-network-id "$ODB_NETWORK_ID" \
  --region "$REGION" \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
net = data.get('odbNetwork', data)
print(f\"  Status:            {net.get('status', 'N/A')}\")
print(f\"  Client Subnet CIDR: {net.get('clientSubnetCidr', 'N/A')}\")
print(f\"  Backup Subnet CIDR: {net.get('backupSubnetCidr', 'N/A')}\")
print(f\"  Availability Zone:  {net.get('availabilityZone', 'N/A')}\")
print(f\"  AZ ID:             {net.get('availabilityZoneId', 'N/A')}\")
dns_ips = net.get('dnsListenerIps', [])
if dns_ips:
    print(f\"  DNS Listener IPs:  {', '.join(dns_ips)}\")
else:
    print(f\"  DNS Listener IPs:  N/A (check OCI console)\")
print(f\"  VPC ID:            {net.get('peeredVpcId', net.get('vpcId', 'N/A'))}\")
" || echo "❌ Failed to describe ODB network. Check network ID and region."

echo ""

# List peering connections
echo "--- Peering Connections ---"
aws odb list-odb-peering-connections \
  --region "$REGION" \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
peerings = data.get('odbPeeringConnections', [])
if not peerings:
    print('  No peering connections found')
else:
    for p in peerings:
        print(f\"  {p.get('odbPeeringConnectionId', 'N/A')}: {p.get('status', 'N/A')} → VPC {p.get('peerNetworkId', 'N/A')}\")
" || echo "❌ Failed to list peering connections."

echo ""
echo "=== Done ==="
echo ""
echo "Next steps:"
echo "  1. Verify peering status is AVAILABLE"
echo "  2. Add route to client subnet CIDR in app VPC route table"
echo "  3. Set up Route 53 Resolver forwarding rule using DNS Listener IPs"
