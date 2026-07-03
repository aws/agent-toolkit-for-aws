# RDS for Oracle — SSM Port Forwarding

Connect to a private RDS Oracle from your laptop via SSM without a bastion host, VPN, or public endpoint.

Two patterns:

- **Pattern A — Local → SSM port forward → RDS.** Forward a local port through an EC2 instance; local tools connect to `localhost`. Use for SQL Developer / Toad / sqlplus from your laptop.
- **Pattern B — SSM shell into EC2 → connect to RDS.** Start an interactive SSM session on an EC2 and connect from there. Use when the EC2 has Oracle client installed.

## Prerequisites

- EC2 in the same VPC as RDS (or peered) with SSM agent running
- EC2 IAM instance profile with `AmazonSSMManagedInstanceCore`
- AWS CLI v2 + Session Manager plugin locally:

  ```bash
  brew install --cask session-manager-plugin   # macOS
  ```

- Security group: EC2 → RDS on 1521
- Verify SSM registration: `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=<id>" --query 'InstanceInformationList[0].PingStatus'` → `"Online"`

## Pattern A — Port forward

```bash
aws ssm start-session \
  --target i-xxxxxxxxxxxxxxxxx \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{
    "host": ["mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com"],
    "portNumber": ["1521"],
    "localPortNumber": ["1521"]
  }'
```

Keep the terminal open. If local port 1521 is busy, use `"11521"` (or any free port).

Then connect local tools to `localhost:1521`:

**SQL Developer** — Hostname `localhost`, Port `1521`, Service Name `ORCL`, Username `admin`.

**Toad for Oracle** — Host `localhost`, Port `1521`, Service Name `ORCL`, Connect As **Normal** (not SYSDBA — RDS doesn't allow SYS). Requires Oracle Client (thick mode) since Toad cannot do thin.

**sqlplus / SQLcl** — never pass password on command line:

```bash
sqlplus /nolog
SQL> CONNECT admin@localhost:1521/ORCL
# prompts for password

# SQLcl
sql admin@localhost:1521/ORCL
```

**Python**:

```python
import oracledb
conn = oracledb.connect(user="admin", password="<from-secrets-manager>", dsn="localhost:1521/ORCL")
```

**Java**:

```java
String url = "jdbc:oracle:thin:@localhost:1521/ORCL";
Connection conn = DriverManager.getConnection(url, "admin", "<from-secrets-manager>");
```

## Pattern B — SSM shell

```bash
aws ssm start-session --target i-xxxxxxxxxxxxxxxxx
```

Drops you into a shell on the EC2 — no SSH key needed. From there, connect to RDS using the EC2's locally-installed tools.

### Quick reachability check from EC2

```bash
nc -zv mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com 1521
```

If that succeeds, use sqlplus / SQLcl / python3 on the EC2 to connect directly to the RDS endpoint (no forwarding).

## SSM VPC endpoints (private subnet, no NAT)

If the EC2 is in a private subnet with no internet egress, create three VPC endpoints:

```bash
VPC=vpc-xxx; SUBNET=subnet-xxx; SG=sg-xxx
for svc in ssm ssmmessages ec2messages; do
  aws ec2 create-vpc-endpoint \
    --vpc-id $VPC \
    --service-name com.amazonaws.<region>.$svc \
    --vpc-endpoint-type Interface \
    --subnet-ids $SUBNET \
    --security-group-ids $SG \
    --private-dns-enabled
done
```

Endpoint SG: allow inbound 443 from the EC2 SG.

## TLS over the tunnel (port 2484)

If RDS has TLS enabled:

```bash
aws ssm start-session \
  --target i-xxxxxxxxxxxxxxxxx \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{
    "host": ["mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com"],
    "portNumber": ["2484"],
    "localPortNumber": ["2484"]
  }'
```

**Critical: `SSL_SERVER_DN_MATCH = FALSE` for tunnel access.** The RDS cert CN is the endpoint hostname, but the client connects to `localhost` — DN matching will fail.

**Python**:

```python
conn = oracledb.connect(
    user="admin", password="<from-secrets-manager>",
    dsn="localhost:2484/ORCL",
    ssl_server_dn_match=False
)
```

**Java**:

```java
String url = "jdbc:oracle:thin:@(DESCRIPTION="
           + "(ADDRESS=(PROTOCOL=TCPS)(HOST=localhost)(PORT=2484))"
           + "(CONNECT_DATA=(SERVICE_NAME=ORCL))"
           + "(SECURITY=(SSL_SERVER_DN_MATCH=FALSE)))";
```

**`sqlnet.ora`** (sqlplus/Toad over tunnel):

```
SSL_SERVER_DN_MATCH = FALSE
WALLET_LOCATION =
  (SOURCE = (METHOD = FILE)
    (METHOD_DATA = (DIRECTORY = /path/to/wallet)))
```

> **⚠️ Use `SSL_SERVER_DN_MATCH=FALSE` ONLY for local SSM tunnel dev.** It disables server identity verification. Never in production — prod apps connect directly from VPC-resident compute with DN matching enabled.

## Auth over tunnel

| Method | Works? |
|---|---|
| Username/password | ✅ Yes |
| Secrets Manager (fetch locally, then connect) | ✅ Yes |
| Kerberos | ❌ No — tickets don't traverse the tunnel; only the Oracle port is forwarded. Use password for tunnel access. |

## SQL Developer / DBeaver built-in SSH tunnel (alternative)

SQL Developer 23+ and DBeaver have their own SSH tunneling UI. Both require the EC2 bastion to accept **SSH (port 22)** inbound — not SSM-only. If you have SSM-only bastions, use the separate-terminal `aws ssm start-session` approach above.

## Quick-connect script

```bash
#!/bin/bash
# Usage: connect-rds-oracle.sh <instance-id> <rds-endpoint> [local-port]
INSTANCE_ID="${1:?Usage: $0 <instance-id> <rds-endpoint> [local-port]}"
RDS_ENDPOINT="${2:?Usage: $0 <instance-id> <rds-endpoint> [local-port]}"
LOCAL_PORT="${3:-1521}"

PARAMS=$(jq -n --arg host "$RDS_ENDPOINT" --arg lp "$LOCAL_PORT" \
  '{"host":[$host],"portNumber":["1521"],"localPortNumber":[$lp]}')

aws ssm start-session \
  --target "${INSTANCE_ID}" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "$PARAMS"
```

## Common issues

| Symptom | Cause | Fix |
|---|---|---|
| `TargetNotConnected` | SSM agent down, missing IAM role | Check IAM instance profile has `AmazonSSMManagedInstanceCore`; verify agent: `systemctl status amazon-ssm-agent` |
| Session starts but Oracle connect times out | EC2 → RDS SG path broken | EC2 SG outbound 1521 to RDS SG; RDS SG inbound 1521 from EC2 SG |
| `Address already in use` on local port | Another local process on 1521 | Use `localPortNumber: 11521` (or any free port) |
| Session drops after 20 min idle | SSM default idle timeout | Raise in Session Manager preferences, or reconnect |
| `Session Manager plugin not found` | Plugin not installed | `brew install --cask session-manager-plugin` |
| `ORA-29024` over TLS tunnel | `SSL_SERVER_DN_MATCH = TRUE` against localhost | Set `SSL_SERVER_DN_MATCH = FALSE` for tunnel |
