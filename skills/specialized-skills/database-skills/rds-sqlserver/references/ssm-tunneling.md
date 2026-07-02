# SSM port forwarding — RDS SQL Server from laptop

For developers who need to connect SSMS, Azure Data Studio, or a local Python script to a private RDS SQL Server without enabling public access, VPN, or a bastion host with SSH.

## Why SSM tunnel

- RDS stays private — no public exposure
- No SSH key management
- IAM-audited via CloudTrail
- Works through corporate firewalls (outbound 443 only)
- Works on any laptop OS (macOS, Linux, Windows)

## Prerequisites

- EC2 jump host in the same VPC as RDS (or peered)
- Jump host has:
  - SSM agent running (Amazon Linux 2/2023 have it by default)
  - IAM instance profile with `AmazonSSMManagedInstanceCore` managed policy
  - SG outbound 1433 → RDS SG, outbound 443 → SSM endpoints
- RDS SG inbound 1433 from jump host SG
- Laptop: AWS CLI v2 + Session Manager plugin
- User IAM identity has `ssm:StartSession` permission on the EC2 resource

### Install Session Manager plugin

```bash
# macOS
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/mac/sessionmanager-bundle.zip" -o "sessionmanager-bundle.zip"
unzip sessionmanager-bundle.zip
sudo ./sessionmanager-bundle/install -i /usr/local/sessionmanagerplugin -b /usr/local/bin/session-manager-plugin

# Linux (deb)
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb

# Windows
# Download and run https://s3.amazonaws.com/session-manager-downloads/plugin/latest/windows/SessionManagerPluginSetup.exe

# Verify
session-manager-plugin
```

## Start the tunnel

```bash
aws ssm start-session \
  --target i-0123456789abcdef0 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{
    "host": ["mydb.xxxx.us-east-1.rds.amazonaws.com"],
    "portNumber": ["1433"],
    "localPortNumber": ["11433"]
  }'
```

Leave this running in a separate terminal. Connect to `localhost:11433` from your client.

Using `11433` (not `1433`) avoids conflict with any local SQL Server Express installation.

## Connect from various tools

### SSMS (SQL Server Management Studio)

- Server name: `localhost,11433` (**comma, not colon**)
- Authentication: SQL Server Authentication
- Login: admin (your RDS master user)
- Password: from Secrets Manager
- **Connection Properties → Connection** → "Encrypt connection" = checked
- **Connection Properties → Connection** → "Trust server certificate" = checked (**dev only**, because cert CN won't match localhost)

### Azure Data Studio

- Connection type: Microsoft SQL Server
- Server: `localhost,11433`
- Encrypt: True
- Trust server certificate: True (dev only)

### Python (pymssql)

```python
import pymssql
conn = pymssql.connect(
    server="localhost",
    port="11433",        # the local port you chose
    user="admin",
    password=pw,
    database="mydb",
    tds_version="7.3",
    encryption="request",  # use "request" for tunnel — cert won't match localhost
)
```

### sqlcmd

```bash
sqlcmd -S localhost,11433 -U admin -P "$PW" -d mydb \
  -C                      # trust server certificate (dev only — cert CN mismatch expected)
```

### .NET / SqlClient

```csharp
var connStr = "Server=localhost,11433;Database=mydb;" +
              "User Id=admin;Password=secret;" +
              "Encrypt=Mandatory;" +
              "TrustServerCertificate=True;";   // dev only — cert CN mismatch
```

## Why `TrustServerCertificate=True` through the tunnel

The RDS certificate CN is `mydb.xxxx.us-east-1.rds.amazonaws.com` but your client connects to `localhost`. Default TLS behavior requires CN match — fails without `TrustServerCertificate=True` (or equivalent).

**This is for dev tunnels only.** The tunnel itself is end-to-end encrypted via SSM (WebSocket over TLS to SSM endpoints, TCP to RDS inside the VPC). The TLS layer is a second encryption layer — trusting the cert through the tunnel only means you accept that the CN doesn't match `localhost`.

**Production workloads must connect from VPC-resident compute** (EC2/ECS/Lambda in the same VPC) using the real endpoint with full cert validation.

## Windows auth through the tunnel — don't

SSM runs as the EC2 system account, not your user. `Integrated Security=True` through a tunnel will:

- Connect as the EC2 system account (which has no AD identity) → NTLM fallback or fail
- Not test anything meaningful about your user's domain credentials

For Windows auth testing, RDP to a domain-joined EC2 and run SSMS there.

## IAM policy for developers

Limit `ssm:StartSession` to the specific document + instance:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StartSessionPortForward",
      "Effect": "Allow",
      "Action": ["ssm:StartSession"],
      "Resource": [
        "arn:aws:ec2:us-east-1:111122223333:instance/i-0123456789abcdef0",
        "arn:aws:ssm:us-east-1::document/AWS-StartPortForwardingSessionToRemoteHost"
      ]
    },
    {
      "Sid": "TerminateAndResume",
      "Effect": "Allow",
      "Action": ["ssm:TerminateSession", "ssm:ResumeSession"],
      "Resource": "arn:aws:ssm:*:111122223333:session/${aws:username}-*"
    }
  ]
}
```

## Troubleshooting the tunnel

| Symptom | Cause |
|---|---|
| `TargetNotConnected` | EC2 SSM agent not running or IAM role missing `AmazonSSMManagedInstanceCore` |
| Tunnel starts but `localhost:11433` connection refused | EC2 SG can't reach RDS (outbound 1433 not allowed, or RDS SG inbound missing) |
| Tunnel starts, connects, then SSMS pre-login fails | TLS version mismatch — upgrade SSMS to 18.x+ |
| Cert validation error with `TrustServerCertificate=False` | Set `TrustServerCertificate=True` — CN will never match localhost through a tunnel |

Check SSM agent status from the jump host:

```bash
sudo systemctl status amazon-ssm-agent
sudo tail -f /var/log/amazon/ssm/amazon-ssm-agent.log
```

## Verify the tunnel works end-to-end

```bash
# Terminal 1: start tunnel
aws ssm start-session --target i-xxxx \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["mydb.xxxx.us-east-1.rds.amazonaws.com"],"portNumber":["1433"],"localPortNumber":["11433"]}'

# Terminal 2: test reachability
nc -zv localhost 11433
# Connection to localhost port 11433 [tcp/*] succeeded!

# Terminal 2: SQL query
sqlcmd -S localhost,11433 -U admin -P "$PW" -Q "SELECT @@SERVERNAME" -C
# Returns RDS server name
```
