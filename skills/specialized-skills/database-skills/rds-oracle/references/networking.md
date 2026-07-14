# RDS for Oracle — Networking

Security groups, cross-VPC connectivity, and Route 53 private endpoints.

**Security rule: do NOT enable public access on RDS Oracle.** Keep `Publicly Accessible: No`, private subnets only. External access goes through VPN, Direct Connect, or SSM port forwarding.

## Security groups — the three patterns

### Pattern A — App in same VPC (or peered VPC via SG reference)

RDS SG inbound:

| Type | Protocol | Port | Source |
|---|---|---|---|
| Oracle-RDS | TCP | 1521 | Application SG id |

App SG outbound:

| Type | Protocol | Port | Destination |
|---|---|---|---|
| Oracle-RDS | TCP | 1521 | RDS SG id |
| HTTPS | TCP | 443 | Secrets Manager VPC endpoint SG (preferred), or `com.amazonaws.<region>.secretsmanager` prefix list |

### Pattern B — App in a different VPC (Transit Gateway, or peering without SG-ref support)

Cross-VPC SG-id references only work with VPC peering when `AllowDnsResolutionFromRemoteVpc = true`. For Transit Gateway or any unclear case, use **CIDR-based rules**:

RDS SG inbound:

| Type | Protocol | Port | Source |
|---|---|---|---|
| Oracle-RDS | TCP | 1521 | App VPC CIDR (e.g. `10.0.0.0/16`) |

### Pattern C — On-prem app via VPN/Direct Connect

Requires an established VPN or Direct Connect:

| Type | Protocol | Port | Source |
|---|---|---|---|
| Oracle-RDS | TCP | 1521 | On-prem CIDR block(s) |

Never make RDS publicly accessible as a workaround.

### AWS CLI

```bash
# Same-VPC
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-oracle \
  --protocol tcp --port 1521 \
  --source-group sg-app \
  --region us-east-1

# Cross-VPC via CIDR
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-oracle \
  --protocol tcp --port 1521 \
  --cidr 10.10.0.0/16 \
  --region us-east-1
```

### Secrets Manager VPC endpoint (recommended)

Keeps Secrets Manager traffic off the internet:

```
Service: com.amazonaws.<region>.secretsmanager
Type: Interface
Private DNS: Enabled
SG: allow inbound TCP 443 from app SG
```

## Cross-VPC connectivity

### Option 1 — Transit Gateway (recommended for hub-and-spoke)

```bash
aws ec2 create-transit-gateway --description cross-vpc-tgw

aws ec2 create-transit-gateway-vpc-attachment \
  --transit-gateway-id tgw-xxxx --vpc-id vpc-app \
  --subnet-ids subnet-app-a subnet-app-b

aws ec2 create-transit-gateway-vpc-attachment \
  --transit-gateway-id tgw-xxxx --vpc-id vpc-rds \
  --subnet-ids subnet-rds-a subnet-rds-b

# Forward AND return route tables
aws ec2 create-route --route-table-id rtb-app \
  --destination-cidr-block <rds-vpc-cidr> --transit-gateway-id tgw-xxxx
aws ec2 create-route --route-table-id rtb-rds \
  --destination-cidr-block <app-vpc-cidr> --transit-gateway-id tgw-xxxx
```

Then SG inbound on RDS using the **app VPC CIDR** (SG-id refs don't cross TGW).

### Option 2 — VPC Peering (1:1, cross-region supported)

```bash
aws ec2 create-vpc-peering-connection --vpc-id vpc-app --peer-vpc-id vpc-rds

# Accept (cross-account only)
aws ec2 accept-vpc-peering-connection --vpc-peering-connection-id pcx-xxxx

# Routes on both sides
aws ec2 create-route --route-table-id rtb-app \
  --destination-cidr-block <rds-vpc-cidr> --vpc-peering-connection-id pcx-xxxx
aws ec2 create-route --route-table-id rtb-rds \
  --destination-cidr-block <app-vpc-cidr> --vpc-peering-connection-id pcx-xxxx

# Enable DNS across peering (critical)
aws ec2 modify-vpc-peering-connection-options \
  --vpc-peering-connection-id pcx-xxxx \
  --requester-peering-connection-options '{"AllowDnsResolutionFromRemoteVpc":true}' \
  --accepter-peering-connection-options '{"AllowDnsResolutionFromRemoteVpc":true}'
```

### Peering vs TGW

| | VPC Peering | Transit Gateway |
|---|---|---|
| Transitive routing | No | Yes |
| Scalability | 1:1 per pair | Hub-and-spoke |
| SG-id cross-reference | Yes (with `AllowDnsResolution`) | **No — use CIDR** |
| Cost | Data transfer only | Hourly + data transfer |
| Bandwidth | No limit | 50 Gbps per attachment |

## DNS resolution across VPCs

RDS endpoints resolve to private IPs inside the RDS VPC. For apps in other VPCs:

- **TGW with `DnsSupport` enabled + VPC `enableDnsSupport`/`enableDnsHostnames`** — simplest same-account case.
- **Route 53 private hosted zone with CNAME** to the RDS endpoint; associate with both VPCs.
- **Route 53 Resolver rules** forwarding `<region>.rds.amazonaws.com` to the RDS VPC DNS (VPC + 2 IP).

### Kerberos caveat

If using Kerberos, the app VPC must also resolve the AD domain. Share AWS Managed Microsoft AD via RAM, or add a Route 53 Resolver rule forwarding the AD domain to the AD DNS IPs.

## Route 53 private endpoint (friendly DNS name)

Use a human-readable DNS like `oracledb.example.internal`.

```bash
# Create PHZ (first time)
aws route53 create-hosted-zone \
  --name example.internal \
  --vpc VPCRegion=us-east-1,VPCId=vpc-xxxxxxxx \
  --caller-reference "rds-oracle-$(date +%s)" \
  --hosted-zone-config PrivateZone=true

# Create CNAME to RDS endpoint
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890 \
  --change-batch '{
    "Changes":[{"Action":"UPSERT","ResourceRecordSet":{
      "Name":"oracledb.example.internal","Type":"CNAME","TTL":300,
      "ResourceRecords":[{"Value":"mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com"}]
    }}]
  }'
```

TTL guidance: 300s normal, drop to 60s before a planned failover. Multi-AZ failover is handled by RDS's own DNS; the CNAME follows automatically.

Pointing at CMAN instead of RDS directly: set the CNAME to the CMAN NLB DNS name (see `cman-proxy.md`).

## Quick diagnostic (from an app instance)

```bash
nslookup mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com     # DNS resolution
nc -zv mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com 1521  # TCP reachability
ip route get <rds-vpc-cidr-first-ip>                        # route exists
```

Or run `scripts/test_connectivity.sh <endpoint> 1521` and `scripts/check_security_groups.sh <instance-id>`.

## Troubleshooting

| Symptom | Check |
|---|---|
| DNS doesn't resolve cross-VPC | Enable DNS on peering/TGW, or add PHZ / Resolver rule |
| Timeout after DNS resolves | Route tables missing in one direction, or SG missing inbound from app CIDR |
| Intermittent timeouts | NACL ephemeral port range (1024-65535) blocked for return traffic |
| Works from one AZ, not another | Route table only associated with some subnets |
| `ORA-12170` | Network path blocked — check routes, SGs, NACLs |
| `ORA-12541` | DNS resolved to wrong IP — verify endpoint resolves to RDS private IP |
| Kerberos auth fails cross-VPC | App VPC can't reach AD DNS — add resolver rule forwarding the AD domain |
