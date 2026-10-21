# Troubleshooting — ORA / TNS / Network / DNS / Wallet / TCPS / OCI IAM / Tunnel Errors

Diagnose top-down: **DNS → TCP → TLS → Auth**. Stop at the first failing layer.

Run these first:

```bash
python3 scripts/resolve_scan.py <scan-hostname>
bash scripts/check_odb_connectivity.sh <scan-hostname> <port>
bash scripts/fetch_odb_network_info.sh <odb-network-id> <region>
```

## ORA / TNS Quick Reference

| Error | Most likely ODB@AWS cause | Fix reference |
|---|---|---|
| ORA-12154 (can't resolve identifier) | Route 53 Resolver rule missing / wrong domain / not associated with VPC | **networking-dns-resolver.md** (loaded reference) |
| ORA-12170 (TNS connect timeout) | Missing ODB client-CIDR route in app VPC route table | **networking-odb-peering.md** (loaded reference) |
| ORA-12514 (listener doesn't know service) | Wrong service name, PDB not open, or SID used with SCAN | **authorization-db-users.md** (loaded reference) |
| ORA-12541 (no listener) | Wrong port (1521/2484/custom Autonomous TCPS port) | **networking-odb-peering.md** (loaded reference) |
| ORA-28759 (failure to open file) | Wallet path, missing `cwallet.sso`, file permissions, wrong wallet password | **auth-wallet-tcps.md** (loaded reference) |
| ORA-28040 (no matching auth protocol) | `ojdbc6`/`ojdbc7` — upgrade to `ojdbc11.jar` | **connect-java.md** (loaded reference) |
| ORA-28276 (invalid OCI IAM token) | Token expired, clock skew > 5 min, wrong identity domain | **auth-oci-iam.md** (loaded reference) |
| ORA-01017 (invalid username/password) | Wrong password, locked account, DB vs OCI IAM password confusion | **auth-wallet-tcps.md** (loaded reference) |
| ORA-29024 (cert validation failure) | Truststore path, expired cert, DN mismatch, or tunnel + `DN_MATCH=TRUE` | **connect-ssh-tunnel.md** (loaded reference) |
| ORA-28860 (fatal SSL error) | TLS version / cipher mismatch, or corrupted wallet | `openssl s_client -tls1_2` / `-tls1_3` |

Do NOT suggest Oracle Client reinstallation for ORA-28759 on thin-mode python-oracledb or node-oracledb — thin mode does not use the Oracle Client.

## DNS Layer

```bash
dig <scan-hostname> +short
aws route53resolver list-resolver-rules --region <region> \
  --query "ResolverRules[?DomainName=='oraclevcn.com']"
aws route53resolver list-resolver-rule-associations --region <region> \
  --query "ResolverRuleAssociations[?VPCId=='<vpc-id>']"
aws route53resolver get-resolver-rule --resolver-rule-id <rule-id> --region <region>
```

| Cause | Fix |
|---|---|
| No rule | Create per **networking-dns-resolver.md** (loaded reference) |
| Rule not associated with VPC | `associate-resolver-rule` |
| Rule targets SCAN IPs | Re-target at DNS listener IPs |
| SG blocks DNS | Allow UDP/TCP 53 egress to ODB client CIDR |
| Wrong domain | Recreate with `oraclevcn.com` |

Works in one VPC but not another → the rule is only associated with one VPC. Associate the other or share via AWS RAM.

## Network Layer — ORA-12170

```bash
nc -zv <scan-hostname> 1521 -w 5
aws ec2 describe-route-tables --route-table-ids <rtb-id> --region <region>
aws ec2 describe-security-groups --group-ids <sg-id> --region <region>
aws ec2 describe-network-acls --filters Name=association.subnet-id,Values=<subnet-id>
aws odb get-odb-peering-connection --odb-peering-connection-id <odbpcx-id> --region <region>
aws odb get-odb-network --odb-network-id <odb-id> --region <region> --query 'availabilityZoneId'
```

| Cause | Fix |
|---|---|
| Missing ODB CIDR route | `aws ec2 create-route --odb-network-arn ...` |
| SG blocks 1521/2484 egress | Add outbound rule |
| NACL denies | Allow 1521/2484 + ephemeral ports |
| Peering not `AVAILABLE` | Wait or recreate |
| AZ mismatch | Move app to matching `availabilityZoneId` |

Intermittent timeouts: RAC failover (~1/3 of new connections fail during a node outage — add retry), stale pool connections (enable `pool_pre_ping` / `pool_recycle`), or automation reverting SG changes.

Works from one subnet but not another: each subnet has its own route table; every app subnet's route table must include the ODB CIDR route.

## TCPS / TLS Layer

```bash
openssl s_client -connect <scan-hostname>:2484 -servername <scan-hostname> 2>/dev/null \
  | openssl x509 -noout -subject -dates
```

Over SSM/SSH tunnel: set `SSL_SERVER_DN_MATCH=FALSE` (cert CN = SCAN hostname, client connects to `localhost`). See **connect-ssh-tunnel.md** (loaded reference).

Hangs on TCPS: port 2484 blocked by SG/NACL, Autonomous DB using a custom TCPS port (verify in OCI console), or corporate firewall doing deep packet inspection.

## Wallet Layer

Works locally but fails in Lambda:

| Wallet location | Lambda path | Notes |
|---|---|---|
| Deployment package | `/var/task/wallet/` | Read-only |
| Lambda layer | `/opt/wallet/` | Read-only |
| `/tmp` | `/tmp/wallet/` | Recommended — extract at cold start from Secrets Manager binary secret |

See the Lambda pattern in **compute-runtimes.md** (loaded reference).

`sqlnet.ora` path issues (thick mode / JDBC): wallet's `sqlnet.ora` has a hardcoded `DIRECTORY`. Thin mode overrides via `config_dir`/`wallet_location`; thick and JDBC respect it — edit or set `TNS_ADMIN` to override.

## OCI IAM Auth Layer

ORA-28276 — see the quick-reference row. For Lambda, fetch a fresh token per invocation (no cross-invocation caching).

Password verifier mismatch (ORA-01017 under OCI IAM):

```sql
SELECT username, authentication_type, external_name FROM dba_users WHERE username = 'OCI_USER';
```

`authentication_type` must be `GLOBAL` and `external_name` must match the OCI IAM OCID. Fixes: user logs in to OCI IAM to trigger verifier re-sync after password change; verify the OCID; check identity domain.

## SSH / SSM Tunnel Layer

"Target is not connected" (SSM):

```bash
aws ssm describe-instance-information --filters Key=InstanceIds,Values=<instance-id>
```

Causes: SSM Agent not running, IAM role lacks `AmazonSSMManagedInstanceCore`, no outbound HTTPS to SSM endpoints, instance stopped. Fix: restart `amazon-ssm-agent`, attach the policy, add NAT or VPC endpoints for `ssm`, `ssmmessages`, `ec2messages`.

Tunnel connects, Oracle times out: bastion not in peered VPC, bastion SG missing outbound 1521/2484, bastion subnet missing ODB CIDR route, bastion VPC missing the Route 53 Resolver rule, or wrong SCAN hostname in tunnel parameters. From the bastion via SSM: `dig <scan-hostname> +short` and `nc -zv <scan-hostname> 1521 -w 5`.

ORA-29024 / DN mismatch over tunnel: set `SSL_SERVER_DN_MATCH=FALSE` for tunnel-only use. See **connect-ssh-tunnel.md** (loaded reference).

SSH tunnel drops when idle: add `ServerAliveInterval 60` / `ServerAliveCountMax 3`.

Slow queries over tunnel: extra hop + VPN overhead. For bulk ops, run from an EC2 in the peered VPC; tunnel access is for developers and admins only.

## Access, Credentials, and Quotas

- `AccessDenied` on `odb:*` — attach a scoped policy (`odb:Describe*`, `odb:List*`, `odb:CreateOdbPeeringConnection`, matching `ec2:*` and `route53resolver:*`); do not grant `*`.
- `ExpiredToken` / `RequestExpired` — `aws sts get-caller-identity`, `aws sso login`, or `ada credentials update`.
- `ThrottlingException` / `Rate exceeded` — retry once with jitter; narrow scope if persistent.
- `ResourceNotFoundException` on `aws odb get-odb-network` — wrong region or network deleted. Try `aws odb list-odb-networks --region <region>`.
