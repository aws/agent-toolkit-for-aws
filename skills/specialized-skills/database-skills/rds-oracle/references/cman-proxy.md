# RDS for Oracle — Oracle Connection Manager (CMAN)

**RDS for Oracle does NOT support RDS Proxy.** Use Oracle CMAN on EC2 when you need connection multiplexing, access control, session timeout management, or a proxy layer.

CMAN requires **Oracle Enterprise Edition (BYOL)**. The CMAN EC2 host itself needs no separate license.

Source: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/oracle-cman.html

## Architecture

```
Clients → CMAN (EC2, private subnet) → RDS Oracle
```

On-prem clients connect to CMAN via VPN/Direct Connect. CMAN provides a stable proxy in front of the RDS endpoint.

## EC2 setup

- Oracle Linux 7/8, minimum `t3.medium` for light workloads
- Requires **full Oracle Client with CMAN module** (Instant Client does NOT include `cmctl`)
- SG allowing inbound 1521 from clients, outbound 1521 to RDS

Install the full Oracle Client 19c (silent install):

```bash
# As root
yum install -y oracle-database-preinstall-19c.x86_64
mkdir -p /u01 && chown oracle:oinstall /u01

# As oracle user
export INSTALL_HOME=/u01
mkdir -p /u01/app/oracle/product/client19300 $INSTALL_HOME/stage
cd $INSTALL_HOME/stage
unzip LINUX.X64_193000_client.zip

cat > $INSTALL_HOME/stage/clientinstall.rsp <<EOF
oracle.install.responseFileVersion=/oracle/install/rspfmt_clientinstall_response_schema_v19.0.0
ORACLE_HOSTNAME=$(hostname)
UNIX_GROUP_NAME=oinstall
INVENTORY_LOCATION=/u01/app/oraInventory
SELECTED_LANGUAGES=en
ORACLE_HOME=/u01/app/oracle/product/client19300
ORACLE_BASE=/u01/app/oracle
oracle.install.client.installType=Custom
oracle.install.client.customComponents="oracle.sqlplus:19.0.0.0.0","oracle.network.client:19.0.0.0.0","oracle.network.cman:19.0.0.0.0","oracle.network.listener:19.0.0.0.0"
EOF

$INSTALL_HOME/stage/client/runInstaller -silent \
  -responseFile $INSTALL_HOME/stage/clientinstall.rsp \
  ORACLE_HOME_NAME=client19300

# As root
/u01/app/oraInventory/orainstRoot.sh
/u01/app/oracle/product/client19300/root.sh
```

Add to `~oracle/.bash_profile`:

```bash
export ORACLE_HOME=/u01/app/oracle/product/client19300
export PATH=$PATH:$ORACLE_HOME/bin
```

Verify: `cmctl` runs without errors.

## CMAN configuration

`$ORACLE_HOME/network/admin/cman.ora`:

```
CMAN =
  (CONFIGURATION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = 0.0.0.0)(PORT = 1521))
    (RULE_LIST =
      # Wildcard (SRC=*)(DST=*)(SRV=*) is for INITIAL TESTING ONLY and MUST be replaced before production use.
      # Restrict to your client CIDR(s) and service name, and reject everything else:
      (RULE = (SRC = 10.0.0.0/16)(DST = *)(SRV = ORCL)(ACT = ACCEPT))
      (RULE = (SRC = *)(DST = *)(SRV = *)(ACT = REJECT))
    )
    (PARAMETER_LIST =
      MAX_CONNECTIONS = 256
      MAX_GATEWAY_PROCESSES = 8
      MIN_GATEWAY_PROCESSES = 2
      LOG_LEVEL = USER
      SESSION_TIMEOUT = 0
      INBOUND_CONNECT_TIMEOUT = 60
      OUTBOUND_CONNECT_TIMEOUT = 60
    )
  )
```

### Production access rules

Restrict by source CIDR or service name, deny everything else:

```
(RULE_LIST =
  (RULE = (SRC = 10.0.0.0/16)(DST = *)(SRV = ORCL)(ACT = ACCEPT))
  (RULE = (SRC = 172.16.0.0/12)(DST = *)(SRV = ORCL)(ACT = ACCEPT))
  (RULE = (SRC = *)(DST = *)(SRV = *)(ACT = REJECT))
)
```

### Idle-session timeout per rule

```
# Close sessions idle > 300 seconds
(RULE =
  (SRC = 10.0.0.0/16)(DST = *)(SRV = *)(ACT = ACCEPT)
  (ACTION_LIST = (MIT = 300))
)
```

## Start CMAN

```bash
export ORACLE_HOME=/u01/app/oracle/product/client19300
export PATH=$ORACLE_HOME/bin:$PATH

cmctl startup -c CMAN
cmctl show status -c CMAN
cmctl show connections -c CMAN
```

## systemd service

`/etc/systemd/system/oracle-cman.service`:

```ini
[Unit]
Description=Oracle Connection Manager
After=network.target

[Service]
Type=forking
User=oracle
Environment=ORACLE_HOME=/u01/app/oracle/product/client19300
ExecStart=/u01/app/oracle/product/client19300/bin/cmctl startup -c CMAN
ExecStop=/u01/app/oracle/product/client19300/bin/cmctl shutdown -c CMAN
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable oracle-cman
sudo systemctl start oracle-cman
```

## Security groups (three-tier)

| Resource | Direction | Port | Source/Destination |
|---|---|---|---|
| Client SG | Outbound | 1521 | CMAN SG |
| CMAN SG | Inbound | 1521 | Client SG (or on-prem CIDR) |
| CMAN SG | Outbound | 1521 | RDS SG |
| RDS SG | Inbound | 1521 | **CMAN SG** (not the client SG) |

## High availability — NLB across two AZs

```
Clients → NLB (TCP 1521) → CMAN-AZ1, CMAN-AZ2 → RDS Oracle
```

- Two CMAN EC2 instances, one per AZ
- Network Load Balancer with TCP 1521 listener
- Target group health check: TCP 1521
- Route 53 CNAME `oracle-cman.example.internal` → NLB DNS name

This survives single-AZ failures and lets you patch one CMAN at a time.

## Client configuration

Point clients at the CMAN EC2 / NLB, not RDS directly.

### Python

```python
import oracledb
dsn = "cman-ec2-private-ip:1521/ORCL"
conn = oracledb.connect(user="dbadmin", password="<from-secrets-manager>", dsn=dsn)
```

### Java

```java
String url = "jdbc:oracle:thin:@cman-ec2-private-ip:1521/ORCL";
```

### `tnsnames.ora`

```
ORCL_VIA_CMAN =
  (DESCRIPTION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = cman-ec2-private-ip)(PORT = 1521))
    (CONNECT_DATA = (SERVICE_NAME = ORCL)(SERVER = CMAN)))
```

## Traffic Director Mode (session multiplexing)

Set the RDS parameter `REMOTE_LISTENER` to the CMAN address to enable Traffic Director Mode:

```
REMOTE_LISTENER = <cman-ec2-private-ip>:1521
```

Set this on a DB parameter group, associate with the RDS instance, reboot.

## JDBC thin driver proxy — SOURCE_ROUTE

JDBC thin doesn't use `tnsnames.ora`. Use a SOURCE_ROUTE descriptor in the URL:

```java
String url = "jdbc:oracle:thin:@(DESCRIPTION="
           + "(SOURCE_ROUTE=YES)"
           + "(ADDRESS=(PROTOCOL=TCP)(HOST=<cman-ec2-ip>)(PORT=1521))"
           + "(ADDRESS=(PROTOCOL=TCP)(HOST=<rds-endpoint>)(PORT=1521))"
           + "(CONNECT_DATA=(SERVICE_NAME=ORCL)))";
```

## Terraform outline

```hcl
resource "aws_instance" "cman" {
  ami           = data.aws_ami.oracle_linux.id
  instance_type = "t3.medium"
  subnet_id     = var.private_subnet_id
  vpc_security_group_ids = [aws_security_group.cman.id]
  tags = { Name = "oracle-cman" }
}

resource "aws_security_group" "cman" {
  name_prefix = "cman-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 1521
    to_port         = 1521
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
    cidr_blocks     = var.onprem_cidrs
  }

  egress {
    from_port       = 1521
    to_port         = 1521
    protocol        = "tcp"
    security_groups = [aws_security_group.rds_oracle.id]
  }
}
```

## Why not RDS Proxy?

**RDS Proxy does not support Oracle.** RDS Proxy supports MySQL, PostgreSQL, and SQL Server only. For Oracle connection multiplexing, CMAN is the supported path.

## CMAN log files

`$ORACLE_HOME/diag/netcman/<hostname>/<cman-alias>/trace/` — check when CMAN won't start or connections fail.

## Common failure modes

- **`cmctl startup` fails** — `ORACLE_HOME` not set; `cman.ora` syntax error (run `cmctl validate`); port 1521 already in use.
- **Clients can't connect through CMAN** — SG inbound on CMAN EC2 missing; CMAN not running; client DSN points at RDS instead of CMAN.
- **Connections drop** — `SESSION_TIMEOUT` too low; NLB health check wrong; check CMAN logs.
- **`ORA-12529` rejected** — source IP not in an `ACCEPT` rule. Add the CIDR or broaden the rule.
