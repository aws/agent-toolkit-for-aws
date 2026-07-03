# RDS for Oracle — Troubleshooting

Common Oracle connectivity errors and fixes. Pair with the `networking.md`, `connection-auth.md`, and compute-runtime references for deeper context.

## Connection errors (ORA-*)

### `ORA-12170` — TNS: Connect timeout

Network can't reach RDS.

- RDS SG inbound on 1521 allows your source (SG id same-VPC, CIDR cross-VPC)
- RDS instance is `available`: `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].DBInstanceStatus'`
- Same VPC or peering/TGW with route tables in both directions
- NACLs not blocking 1521 (or ephemeral return ports 1024-65535)
- On-prem: VPN/Direct Connect up

Test:

```bash
nc -zv <rds-endpoint> 1521
bash scripts/test_connectivity.sh <endpoint> 1521
```

### `ORA-12541` — TNS: no listener

Wrong endpoint or port.

- Verify: `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].Endpoint'`
- Don't use the instance ID as the hostname — use the full `*.rds.amazonaws.com` endpoint
- Check the custom port if `Port` isn't 1521

### `ORA-12514` — service not known

Wrong `SERVICE_NAME` or `SID`.

- Correct DB name: `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].DBName'`
- Try both: `(CONNECT_DATA=(SERVICE_NAME=ORCL))` vs `(CONNECT_DATA=(SID=ORCL))`
- After failover, the listener may take a moment to re-register

### `ORA-12505` — SID not known

Using SID syntax when a Service Name is required (common for newer tools). Switch to:

```
(CONNECT_DATA=(SERVICE_NAME=ORCL))
```

### `ORA-01017` — invalid username/password

- Verify Secrets Manager value: `aws secretsmanager get-secret-value --secret-id <name> --query SecretString --output text`
- Password rotation — fetch fresh creds
- Case-sensitive passwords (RDS setting)
- Special chars in password may need escaping in connection strings

### `ORA-28040` — no matching auth protocol

Client driver too old.

- Update to Oracle 21c+ thin drivers: `python-oracledb 6+`, `ojdbc11` 23.x, `node-oracledb 6+`, ODP.NET Core latest
- Thin mode avoids this entirely

### `ORA-29024` — certificate validation failure (TLS)

Client doesn't trust RDS CA.

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

- Python: set `wallet_location` to the directory containing the PEM
- Java: split the bundle and import each cert (keytool imports only the first)
- .NET: add to OS trust store (`update-ca-certificates`)
- Over SSM tunnel: `SSL_SERVER_DN_MATCH = FALSE` (cert CN won't match `localhost`)

### `ORA-28860` — fatal SSL error

TLS version or cipher mismatch.

- RDS option group: `SQLNET.SSL_VERSION = 1.2`
- Client supports TLS 1.2
- JDK 8u261+ for full cipher support

## Driver-specific

### Python — `DPI-1047`

Thick mode can't locate Oracle Client.

- Switch to thin mode (python-oracledb 6+ default). Most code paths don't need thick.
- If you need thick: `oracledb.init_oracle_client(lib_dir="/usr/lib/oracle/21/client64/lib")`
- Install `libaio` on Linux

### Python — `DPY-6005` (thin-mode limitation)

Some operation isn't supported in thin mode. Usually Kerberos with in-memory tickets or Advanced Queuing. Switch to thick for just that code path, or find the thin-compatible equivalent.

### Python — `ModuleNotFoundError: oracledb`

```bash
pip install oracledb
```

### Java — `ClassNotFoundException: oracle.jdbc.driver.OracleDriver`

Add `ojdbc11` dependency:

```xml
<dependency>
  <groupId>com.oracle.database.jdbc</groupId>
  <artifactId>ojdbc11</artifactId>
  <version>23.4.0.24.05</version>
</dependency>
```

### Java — UCP `Cannot get Connection from Datasource`

Pool exhausted.

- `maxPoolSize` too low for workload
- Connections not returned (use try-with-resources)
- RDS `max_connections` exceeded across all app instances — check CloudWatch `DatabaseConnections`

### Secrets Manager — `AccessDeniedException`

- Role has `secretsmanager:GetSecretValue` on the correct ARN (including the random suffix)
- If KMS-encrypted with a customer-managed key: add `kms:Decrypt` permission
- VPC endpoint for Secrets Manager? Endpoint policy allows the role?
- From VPC with no internet: need VPC endpoint for Secrets Manager

### Secrets Manager — timeout from Lambda/ECS/EKS

- Lambda in VPC: VPC endpoint or NAT gateway for Secrets Manager
- SG allows outbound 443 to Secrets Manager endpoint

## Platform-specific

### Lambda — cold start > 5s

- Use thin mode (no Oracle Client load)
- Initialize pool at module scope (outside handler), reused across warm invocations
- Provisioned concurrency for latency-sensitive workloads
- Keep memory reasonable (higher memory is faster but costlier; ENI attachment is fixed ~1-2s)

### Lambda — too many RDS connections

Each Lambda instance has its own pool. High concurrency → many connections.

- Keep pool `max` small (1-2 per instance)
- Set Lambda reserved concurrency to cap total instances
- Monitor RDS `DatabaseConnections` CloudWatch metric
- Total max = concurrency × pool max

### ECS Fargate — secrets not injected

- Task **execution** role (not task role) has `secretsmanager:GetSecretValue`
- Secret ARN in task definition matches exactly (with random suffix)
- Subnets have NAT or VPC endpoint for Secrets Manager
- Thin mode preferred for containers — no Oracle Client in image

### EKS — pod can't access Secrets Manager via IRSA

- OIDC provider associated with cluster
- ServiceAccount annotated with IAM role ARN
- IAM role trust policy allows the ServiceAccount
- Role has `secretsmanager:GetSecretValue`
- Pod spec: `serviceAccountName: <sa-name>`

### EKS — too many connections from scaled pods

- Pool `max` small (1-3 per pod)
- HPA `maxReplicas × max` ≤ RDS capacity budget
- Monitor `DatabaseConnections`, set CloudWatch alarms

## SSM port forwarding

### `TargetNotConnected`

SSM agent not running, or missing IAM.

- `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=<id>"` — PingStatus should be `Online`
- IAM instance profile has `AmazonSSMManagedInstanceCore`
- `systemctl status amazon-ssm-agent`

### Tunnel up, Oracle connect times out

- EC2 SG outbound 1521 to RDS SG
- RDS SG inbound 1521 from EC2 SG
- From Pattern B (SSM shell): `nc -zv <rds-endpoint> 1521`

### `Session Manager plugin not found`

```bash
brew install --cask session-manager-plugin
```

### `Address already in use` on local port

```bash
--parameters '{"host":["..."],"portNumber":["1521"],"localPortNumber":["11521"]}'
```

Then connect to `localhost:11521`.

## Kerberos

### `ORA-12631` — Username retrieval failed

- `klist` — no ticket? Run `okinit joedoe@REALM`
- `sqlnet.ora` has `SQLNET.AUTHENTICATION_SERVICES = (KERBEROS5PRE,KERBEROS5)`
- `SQLNET.KERBEROS5_CC_NAME` points to correct cache file
- Windows SQL*Plus: `OSMSFT:` for in-memory; SQL Developer: use file cache

### `ORA-01017` with Kerberos

- DB user is UPPERCASE and `IDENTIFIED EXTERNALLY`:

  ```sql
  CREATE USER "JOEDOE@AD.MYAWS.COM" IDENTIFIED EXTERNALLY;
  GRANT CREATE SESSION TO "JOEDOE@AD.MYAWS.COM";
  SELECT username, authentication_type FROM dba_users WHERE username LIKE '%JOEDOE%';
  ```

### `kerberos-disabled` status

- IAM role `rds-directoryservice-kerberos-access-role` exists with `AmazonRDSDirectoryServiceAccess`
- Directory ID correct, RDS VPC reaches AD DNS
- Remove + re-add domain: `--domain ""` then re-add with `--domain <id>`

### "Cannot find KDC"

- `krb5.conf` realm names UPPERCASE
- KDC hostnames resolve: `nslookup ad.myaws.com`
- TCP/UDP 88 open to KDC
- On-prem AD: forest trust established and working

## DNS / Route 53

### CNAME not resolving

- PHZ associated with the correct VPC
- VPC `enableDnsSupport` and `enableDnsHostnames` both enabled
- `aws route53 list-resource-record-sets --hosted-zone-id <id>` — record exists

### On-prem can't resolve PHZ

- Route 53 Resolver inbound endpoints in the VPC
- On-prem DNS forwards the zone to Resolver endpoint IPs
- VPN/DX allows UDP/TCP 53

## Connection pooling

### Pool exhausted

- `max` too low for workload
- Connections leak — use try-with-resources / context managers
- `wait_timeout` set so requests don't hang
- Monitor CloudWatch `DatabaseConnections`

### Stale connections

Enable validation-on-borrow:

- python-oracledb: handles automatically
- Java UCP: `setValidateConnectionOnBorrow(true)` + `setSQLForValidateConnection("SELECT 1 FROM dual")`
- HikariCP: `setConnectionTestQuery("SELECT 1 FROM dual")`

### `ORA-02396` — exceeded maximum idle time

RDS `IDLE_TIME` profile parameter is closing idle connections.

- Increase/remove `IDLE_TIME` on the DB user profile
- Or set pool `timeout` shorter than `IDLE_TIME` so the pool recycles first

## CMAN

### `cmctl startup` fails

- `ORACLE_HOME` set correctly
- `cman.ora` exists at `$ORACLE_HOME/network/admin/cman.ora`
- Validate: `cmctl validate`
- Port 1521 not in use: `netstat -tlnp | grep 1521`

### Clients can't connect through CMAN

- CMAN EC2 SG allows inbound 1521 from client source
- CMAN EC2 SG allows outbound 1521 to RDS SG
- RDS SG allows inbound 1521 from **CMAN EC2 SG** (not client SG)
- CMAN running: `cmctl show status -c CMAN`
- Client DSN points to CMAN IP, not RDS directly

### `ORA-12529` — connection rejected

Source IP not in an `ACCEPT` rule. Add the CIDR to `RULE_LIST` in `cman.ora`.

## Quick scripts

Bundled in `scripts/`:

| Script | Use |
|---|---|
| `test_connectivity.sh <endpoint> [port]` | DNS + TCP reachability |
| `check_rds_status.sh <instance-id>` | Status, endpoint, SGs, encryption |
| `check_security_groups.sh <instance-id> [source]` | Validate SG rules |
| `test_oracle_connection.py <endpoint> <port> <service> <user>` | Full Python test |
| `check_ssl_status.sql` | Verify encryption on current session |
