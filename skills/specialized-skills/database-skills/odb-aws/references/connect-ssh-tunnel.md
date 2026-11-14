# Connect — SSH Tunnel (Laptop / Developer Workstation)

ODB@AWS databases have **no public endpoint**. Laptop clients cannot reach the SCAN hostname directly. The only supported developer access pattern is a tunnel through an EC2 bastion in the peered VPC:

```
Laptop ── SSM / SSH Port Forward ── EC2 Bastion (in peered VPC) ── ODB Network
```

Two methods:
1. **SSM Session Manager port forwarding** — preferred; no SSH keys, no open inbound ports, IAM-scoped, CloudTrail audit.
2. **Traditional SSH local port forwarding** — when SSM is not available.

## Method 1 — SSM Port Forwarding

### Prerequisites

- EC2 bastion in the **peered VPC** with:
  - Route to ODB client subnet CIDR
  - Route 53 Resolver forwarding rule associated with the VPC
  - Outbound TCP 1521/2484 to ODB client subnet CIDR
  - SSM Agent running (Amazon Linux 2023 / AL2 have it pre-installed)
  - IAM role with `AmazonSSMManagedInstanceCore`
  - No inbound SG rules required
- **Laptop**: AWS CLI v2 + `session-manager-plugin`. IAM permission `ssm:StartSession` scoped to the bastion instance.

### Start the tunnel

```bash
# TCP
aws ssm start-session \
  --target i-0abc1234 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{
    "host": ["cluster-abc-scan.sub1.vcn1.oraclevcn.com"],
    "portNumber": ["1521"],
    "localPortNumber": ["1521"]
  }' \
  --region us-east-1

# TCPS
aws ssm start-session \
  --target i-0abc1234 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{
    "host": ["cluster-abc-scan.sub1.vcn1.oraclevcn.com"],
    "portNumber": ["2484"],
    "localPortNumber": ["2484"]
  }' \
  --region us-east-1
```

If local ports 1521/2484 are in use, pick high ports like `11521`/`12484` and match them in clients.

## Method 2 — SSH Local Port Forwarding

Bastion must have SSH keypair, inbound TCP 22 from your IP, a public IP or Elastic IP (or be reachable via corporate VPN).

```bash
# TCP
ssh -i /path/to/key.pem -L 1521:cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521 ec2-user@<bastion-ip> -N

# TCPS
ssh -i /path/to/key.pem -L 2484:cluster-abc-scan.sub1.vcn1.oraclevcn.com:2484 ec2-user@<bastion-ip> -N
```

For jump-host chains:

```bash
ssh -i /path/to/key.pem \
  -J ec2-user@<jump-host-public-ip> \
  -L 1521:cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521 \
  ec2-user@<bastion-private-ip> -N
```

`~/.ssh/config` helper:

```
Host odb-bastion
    HostName <bastion-ip>
    User ec2-user
    IdentityFile /path/to/key.pem
    LocalForward 1521 cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521
    LocalForward 2484 cluster-abc-scan.sub1.vcn1.oraclevcn.com:2484
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Then: `ssh -N odb-bastion`.

## Connecting Through the Tunnel

All clients connect to `localhost:<localPort>` instead of the SCAN hostname.

### python-oracledb

```python
# TCP
conn = oracledb.connect(
    user="app_user", password=password,
    dsn="localhost:1521/orclpdb1.sub1.vcn1.oraclevcn.com",
)

# TCPS — set ssl_server_dn_match=False over tunnel
conn = oracledb.connect(
    user="app_user", password=password,
    dsn="localhost:2484/orclpdb1.sub1.vcn1.oraclevcn.com",
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    wallet_password=wallet_password,
    ssl_server_dn_match=False,  # cert CN = SCAN hostname ≠ localhost
)
```

### JDBC

```java
// TCP
String url = "jdbc:oracle:thin:@//localhost:1521/orclpdb1.sub1.vcn1.oraclevcn.com";

// TCPS over tunnel — disable DN match
String url = "jdbc:oracle:thin:@(DESCRIPTION="
  + "(ADDRESS=(PROTOCOL=TCPS)(HOST=localhost)(PORT=2484))"
  + "(CONNECT_DATA=(SERVICE_NAME=orclpdb1.sub1.vcn1.oraclevcn.com))"
  + "(SECURITY=(SSL_SERVER_DN_MATCH=FALSE)))";
```

### SQLcl / SQL*Plus

```bash
# TCP
sql app_user/<password>@"localhost:1521/orclpdb1.sub1.vcn1.oraclevcn.com"

# TCPS — add a local tnsnames.ora entry with SSL_SERVER_DN_MATCH=FALSE
export TNS_ADMIN=/opt/oracle/wallet
sql app_user/<password>@mydb_tunnel
```

### SQL Developer / DBeaver

Prefer the **built-in SSH tunnel** tab in the tool itself — when the tool handles forwarding, the client resolves the real SCAN hostname through the tunnel and `SSL_SERVER_DN_MATCH=TRUE` works. See **connect-cli-gui.md** (loaded reference).

## Setting Up the Bastion

### Minimal bastion for SSM (no public IP, no inbound SG rules)

```bash
aws ec2 run-instances \
  --image-id ami-0abcdef1234567890 \
  --instance-type t3.micro \
  --subnet-id subnet-in-peered-vpc \
  --security-group-ids sg-bastion \
  --iam-instance-profile Name=SSMBastion \
  --no-associate-public-ip-address \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=odb-bastion}]' \
  --region us-east-1
```

IAM role `SSMBastion` should attach `AmazonSSMManagedInstanceCore`.

Bastion SG:
- No inbound rules.
- Outbound TCP 1521/2484 to ODB client subnet CIDR.
- Outbound HTTPS 443 to SSM endpoints (or use VPC endpoints for `ssm`, `ssmmessages`, `ec2messages`).

### Bastion for traditional SSH

Same as above, but:
- Public subnet with Elastic IP.
- Inbound TCP 22 from your IP or corporate CIDR.
- Launch with `--key-name <keypair>`.

## TCPS Over Tunnel — Gotchas

- `SSL_SERVER_DN_MATCH` MUST be `FALSE` (or omitted) on external tunnel access because the cert CN is the SCAN hostname but the client connects to `localhost`.
- The wallet's `tnsnames.ora` still lists the SCAN hostname — use Easy Connect with `localhost` or add a local TNS alias.
- Wallet password is still required — the tunnel does not bypass TLS.

## Security

- Prefer SSM over SSH — IAM-controlled, no keys to rotate, session logs in CloudTrail.
- Scope `ssm:StartSession` to specific instance IDs and users.
- Rotate SSH keys regularly when using Method 2.
- Keep bastions minimal (t3.micro, no application software).
- Enable SSM session logging to S3 / CloudWatch for audit.
- Tunnel access is for developers and admins only — production workloads MUST connect directly from VPC-resident compute.

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Connecting to SCAN hostname from laptop with no tunnel | Timeout / NXDOMAIN | Use SSM/SSH tunnel |
| `SSL_SERVER_DN_MATCH=TRUE` over external tunnel | ORA-29024 | Set to `FALSE` for tunnel-only use |
| Bastion not in peered VPC | Tunnel connects, Oracle times out | Move bastion to peered VPC |
| SSM Agent not running | "Target is not connected" | Start SSM Agent, verify IAM role |
| Forgot `-N` on SSH | Opens a shell, no tunnel | Add `-N` for tunnel-only |
| Bastion SG missing outbound 1521/2484 | Tunnel connects, Oracle times out | Add outbound rules |
