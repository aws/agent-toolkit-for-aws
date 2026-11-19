# Networking — Multi-VPC via Transit Gateway

When multiple VPCs in the same region need to reach the same ODB network, use a Transit Gateway (TGW) with a transit VPC that holds the single ODB peering. This is simpler and cheaper than one ODB peering per VPC.

## Architecture

```
App VPC 1 ──┐
App VPC 2 ──┤── TGW ── Transit VPC ── ODB Peering ── ODB Network
App VPC 3 ──┘
```

## Step-by-Step

### 1. Create the Transit Gateway

```bash
aws ec2 create-transit-gateway \
  --description "ODB multi-VPC transit" \
  --options DefaultRouteTableAssociation=enable,DefaultRouteTablePropagation=enable,DnsSupport=enable \
  --region us-east-1
```

### 2. Create a dedicated transit VPC

Its CIDR MUST NOT overlap with ODB client/backup subnets or any app VPC. It holds the ODB peering and the Route 53 Resolver outbound endpoint.

### 3. Attach all VPCs to the TGW

```bash
aws ec2 create-transit-gateway-vpc-attachment \
  --transit-gateway-id tgw-0123456789abcdef0 \
  --vpc-id vpc-0transit1111111 \
  --subnet-ids subnet-transit-a subnet-transit-b \
  --region us-east-1
```

Repeat for each app VPC.

### 4. Create ODB peering from the transit VPC

Follow **networking-odb-peering.md** (loaded reference) using the transit VPC as `--peer-network-id`.

### 5. Configure TGW and VPC route tables

TGW route table — add a route to the ODB client subnet CIDR via the transit VPC attachment:

```bash
aws ec2 create-transit-gateway-route \
  --transit-gateway-route-table-id tgw-rtb-0abc \
  --destination-cidr-block 10.20.0.0/24 \
  --transit-gateway-attachment-id tgw-attach-transit
```

Each app VPC route table — add a route to the ODB client subnet CIDR via the TGW:

```bash
aws ec2 create-route \
  --route-table-id rtb-app1 \
  --destination-cidr-block 10.20.0.0/24 \
  --transit-gateway-id tgw-0123456789abcdef0
```

Transit VPC route table — add return routes to each app VPC CIDR via the TGW.

### 6. Set up DNS

Follow **networking-dns-resolver.md** (loaded reference). Place the outbound endpoint in the transit VPC and share the forwarding rule with the app VPCs via AWS RAM.

## Security Groups

- Transit VPC SG: allow inbound TCP 1521/2484 from app VPC CIDRs and outbound UDP/TCP 53 to ODB DNS listeners.
- App VPC SGs: allow outbound TCP 1521/2484 to the ODB client subnet CIDR.

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Missing TGW route for ODB CIDR | Timeout from app VPCs | Add route in TGW route table |
| Missing return route in transit VPC | Asymmetric routing, intermittent drops | Add app VPC CIDRs → TGW in transit VPC route table |
| Resolver endpoint in each app VPC | Works but wasteful | Put endpoint in transit VPC, share rule via RAM |
| CIDR overlap between transit VPC and app VPCs | Peering or TGW attachment fails | Re-plan CIDR allocation |
