# Networking — Multi-Region via AWS Cloud WAN

Use Cloud WAN when applications in multiple AWS regions need to reach a single ODB network, or when a centralized global network policy is required.

## Architecture

```
Region A: App VPC ──┐
                    ├── Cloud WAN ── Region B: Transit VPC ── ODB Peering ── ODB Network
On-prem (VPN/DX) ───┘
```

## Key Concepts

- **Core network** — the global Cloud WAN construct managed via a network policy document.
- **Segments** — logical isolation between workloads (e.g., `production`, `dev`).
- **Attachments** — VPCs, VPNs, DX gateways attached to the core network.
- **Transit VPC** — lives in the ODB region and holds the ODB peering + Route 53 Resolver endpoints.

## Step-by-Step

### 1. Create global network and core network

Done via AWS console or CloudFormation. Define segments and attachment policies in the Cloud WAN policy document.

### 2. Attach the transit VPC (in the ODB region)

```bash
aws networkmanager create-vpc-attachment \
  --core-network-id <core-id> \
  --vpc-arn <transit-vpc-arn> \
  --subnet-arns <transit-subnet-arns> \
  --tags Key=SegmentName,Value=production
```

The transit VPC must hold the ODB peering (see **networking-odb-peering.md** (loaded reference)).

### 3. Attach app VPCs in other regions

Each app VPC attaches to Cloud WAN in its own region with the same segment tag. Cloud WAN propagates routes within a segment automatically.

### 4. Configure route propagation

- Ensure the ODB client subnet CIDR is propagated to all segments that need it via the Cloud WAN policy.
- Each app VPC route table: `ODB client subnet CIDR → Cloud WAN attachment`.

### 5. Cross-region DNS

The Route 53 Resolver outbound endpoint must live in the ODB region (transit VPC). Two options for remote regions:

- **Resolver inbound endpoint in the transit VPC** — remote-region VPCs have a forwarding rule pointing at the inbound endpoint IPs.
- **Route 53 Profiles** — share a rule set across regions.

### 6. On-premises

Attach Site-to-Site VPN or DX Gateway to Cloud WAN. On-prem DNS must forward `oraclevcn.com` to the resolver inbound endpoint (same pattern as the TGW hybrid case — see **networking-enterprise-hybrid.md** (loaded reference)).

## Latency

- Cross-region adds 10–80 ms depending on region pair. Cloud WAN rides the AWS backbone, not the public internet.
- For sub-millisecond OLTP, deploy the app in the same region as the ODB network.

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| ODB CIDR not propagated to remote segments | Timeout from remote VPCs | Update Cloud WAN segment routing policy |
| DNS forwarding not set cross-region | NXDOMAIN remotely | Resolver inbound endpoint + forwarding rule per remote VPC |
| On-prem DNS not forwarding `oraclevcn.com` | NXDOMAIN from on-prem | Conditional forwarder → inbound endpoint IPs |
| Core network policy mismatch | Attachments stuck in `PENDING_NETWORK_UPDATE` | Validate policy JSON, re-run `put-core-network-policy` |
