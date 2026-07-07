# Networking — VPC, Security Groups, Cross-VPC, DNS

## Security groups — the key rule

**Same VPC:** use security group IDs as the source.
**Cross-VPC (peering, Transit Gateway):** use CIDR blocks as the source. SG-to-SG references do not cross VPC boundaries.

This one rule catches ~30% of all RDS connectivity issues.

### Same VPC (recommended)

```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-sqlserver \
  --protocol tcp --port 1433 \
  --source-group sg-app
```

Benefits:

- No IP hardcoding
- Works even when app servers are recreated with new IPs
- Policy-driven: authorize the role, not the address

### Cross-VPC via Transit Gateway or VPC Peering

```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-sqlserver \
  --protocol tcp --port 1433 \
  --cidr 10.1.0.0/16
```

CIDR should be the source VPC or subnet range.

## RDS endpoint format

```
mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com
│     │             │          │
│     │             │          └── AWS service domain
│     │             └── Region
│     └── Random identifier
└── DB instance identifier
```

The endpoint always resolves to a **private** IPv4 address when your VPC has `enableDnsSupport=true` and `enableDnsHostnames=true`. It can also resolve to a public IP if:

- `PubliclyAccessible: true` is set on the instance (not recommended)
- The client is outside AWS and resolves via public DNS

## Cross-VPC patterns

### VPC Peering

Simplest for two VPCs that need to talk:

```bash
aws ec2 create-vpc-peering-connection \
  --vpc-id vpc-app \
  --peer-vpc-id vpc-rds

aws ec2 accept-vpc-peering-connection \
  --vpc-peering-connection-id pcx-xxxx

# Route table in each VPC — add routes to the other's CIDR
aws ec2 create-route --route-table-id rtb-app \
  --destination-cidr-block 10.1.0.0/16 \
  --vpc-peering-connection-id pcx-xxxx

aws ec2 create-route --route-table-id rtb-rds \
  --destination-cidr-block 10.0.0.0/16 \
  --vpc-peering-connection-id pcx-xxxx
```

Both directions required. If only one is configured, connections hang or fail.

### Transit Gateway

For three or more VPCs, or centralized egress:

```bash
# Create TGW
aws ec2 create-transit-gateway --description "central-tgw"

# Attach each VPC
aws ec2 create-transit-gateway-vpc-attachment \
  --transit-gateway-id tgw-xxxx \
  --vpc-id vpc-app \
  --subnet-ids subnet-app-a subnet-app-b

aws ec2 create-transit-gateway-vpc-attachment \
  --transit-gateway-id tgw-xxxx \
  --vpc-id vpc-rds \
  --subnet-ids subnet-rds-a subnet-rds-b

# Route tables — each VPC points the other's CIDR at TGW
aws ec2 create-route --route-table-id rtb-app \
  --destination-cidr-block 10.1.0.0/16 \
  --transit-gateway-id tgw-xxxx
```

TGW SG rules on RDS must use **CIDR**, not SG reference.

### Cross-VPC DNS resolution

By default, `mydb.xxxx.us-east-1.rds.amazonaws.com` resolves to a private IP **only inside the owning VPC**. From the peer VPC, it resolves to the **public IP** (if public) or fails.

Fix with `AllowDnsResolutionFromRemoteVpc` on the peering connection:

```bash
aws ec2 modify-vpc-peering-connection-options \
  --vpc-peering-connection-id pcx-xxxx \
  --accepter-peering-connection-options '{"AllowDnsResolutionFromRemoteVpc":true}' \
  --requester-peering-connection-options '{"AllowDnsResolutionFromRemoteVpc":true}'
```

Without this, cross-VPC `nslookup` returns public IPs, and connections bypass the peering connection entirely — going over the public internet (and often failing due to RDS being private).

For TGW, you typically need a Route 53 private hosted zone shared with each attached VPC (use RAM) so DNS resolution works consistently.

## Route 53 private hosted zone — friendly endpoints

Give RDS a friendly DNS name that works across VPCs:

```bash
# Create private hosted zone
aws route53 create-hosted-zone \
  --name db.internal \
  --vpc VPCRegion=us-east-1,VPCId=vpc-xxxx \
  --caller-reference $(date +%s) \
  --hosted-zone-config PrivateZone=true

# Associate additional VPCs (for cross-VPC access)
aws route53 associate-vpc-with-hosted-zone \
  --hosted-zone-id Z123456ABCDEF \
  --vpc VPCRegion=us-east-1,VPCId=vpc-peer

# Create CNAME to RDS
aws route53 change-resource-record-sets \
  --hosted-zone-id Z123456ABCDEF \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "prod-db.db.internal",
        "Type": "CNAME", "TTL": 60,
        "ResourceRecords": [{"Value": "mydb.xxxx.us-east-1.rds.amazonaws.com"}]
      }
    }]
  }'
```

Clients connect to `prod-db.db.internal` — shorter, environment-aware, and can be updated for blue/green deployments without code changes.

### CNAME for AD DNS (Windows auth)

Windows auth requires Kerberos, which requires the server name to match an SPN in Active Directory. The RDS endpoint has no SPN. You must:

1. Create a CNAME in your AD DNS pointing to the RDS endpoint
   (e.g. `database-1.corp.example.com` → `mydb.xxxx.us-east-1.rds.amazonaws.com`)
2. Register the SPN for the CNAME (RDS does this automatically for AWS Managed Microsoft AD)
3. Clients connect to the CNAME, not the RDS endpoint

See `ad-kerberos.md`.

## NACLs

Network ACLs are stateless and must explicitly allow:

- Inbound 1433 from source CIDR
- **Outbound ephemeral ports 1024-65535** (return traffic)

The "outbound ephemeral ports" is the subtle one. Default NACLs allow all, so this rarely matters. Custom NACLs have broken RDS connections by allowing inbound 1433 but not the return traffic.

## VPC endpoints for AWS services

When Lambda/ECS in private subnets need to reach Secrets Manager without going over NAT:

```bash
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxx \
  --service-name com.amazonaws.us-east-1.secretsmanager \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-priv-a subnet-priv-b \
  --security-group-ids sg-endpoint \
  --private-dns-enabled
```

Endpoint SG inbound 443 from app SG.

Common endpoints to create for RDS SQL Server workloads:

- `secretsmanager` — fetch DB credentials
- `kms` — decrypt customer-managed secret keys
- `logs` — CloudWatch Logs for audit/metrics
- `ec2` — if SDK calls describe-instances etc.
- `s3` (gateway — free) — ECR image layer pulls, S3 integration
- `ecr.api` + `ecr.dkr` — ECS/EKS image pulls

## Testing connectivity

### From an EC2 jump host

```bash
# TCP reachability
nc -zv mydb.xxxx.us-east-1.rds.amazonaws.com 1433

# DNS
dig mydb.xxxx.us-east-1.rds.amazonaws.com
# Should be 10.x.x.x (private) not 52.x.x.x (public)

# TLS handshake
openssl s_client -connect mydb.xxxx.us-east-1.rds.amazonaws.com:1433 \
  -starttls mssql  # not all openssl versions support this
```

For full diagnostics including TDS/pre-login, use the bundled `scripts/test_connection.py`.

### Common issues

| Symptom | Root cause | Fix |
|---|---|---|
| DNS resolves to public IP cross-VPC | `AllowDnsResolutionFromRemoteVpc` off, or not associated with peer VPC | Enable flag or add PHZ association |
| TCP refused from peer VPC | RDS SG using SG reference; needs CIDR | Add CIDR ingress rule |
| Connection times out (15s+) | Route table missing route to peer CIDR | Add route via TGW/peering |
| NAT gateway required from private subnet | No VPC endpoint for Secrets Manager | Create interface endpoint |
| Cross-AZ latency noticed | RDS in one AZ, app in another | Deploy Multi-AZ cluster or co-locate |

## Multi-AZ

RDS Multi-AZ creates a standby in a different AZ. The endpoint automatically switches to the standby during failover. No code changes — just tune driver timeouts to handle the 60-120 second failover window.

Pool settings for failover robustness:

- HikariCP: `maxLifetime=1800000` (30 min), `connectionTestQuery="SELECT 1"`, `validationTimeout=5000`
- SQLAlchemy: `pool_pre_ping=True, pool_recycle=1800`
- .NET: `Connection Lifetime=300` in connection string
- tedious/mssql: pool `idleTimeoutMillis: 600000`
