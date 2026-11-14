---
name: odb-aws
version: 1
description: "Oracle Database@AWS (ODB@AWS) toolkit for Exadata Database Service and Autonomous Database running on OCI-managed Exadata inside AWS. Covers ODB@AWS connectivity scenarios including cannot connect to Exadata on AWS, ORA-12170 timeout, ORA-12154 could not resolve connect identifier, ORA-29024 certificate validation with SSM tunnel, ORA-28759, ODB peering, Route 53 Resolver DNS forwarding for oraclevcn.com, SCAN hostname, connecting Lambda with python-oracledb, multiple VPCs to the same Exadata via Transit Gateway and RAM, wallet from Secrets Manager, TCPS, and OCI IAM. Includes network topology, app code for Python/Java/Node.js/SQLcl/SQL Developer/DBeaver, and TNS/DNS/wallet diagnostics."
---

# Oracle Database@AWS Toolkit

## Safety guidance

This skill covers creating and modifying ODB@AWS-adjacent AWS resources when the user requests it. The agent MUST confirm the action with the user before executing. Do NOT execute any create or modify operation without explicit user confirmation (e.g., "yes", "proceed", "confirmed", "go ahead"). If the user has not confirmed, present the planned action and ask for approval.

**Scope note:** Exadata Database Service infrastructure itself is provisioned by Oracle/OCI and is out of scope for `aws odb create-*` commands. This skill's create/modify operations apply to the AWS-side networking, identity, and credential resources that make an ODB@AWS connection work.

### Writing files and artifacts (graceful degradation)

Some tasks ask you to save output to a file (for example a connection config, a diagnostic report, a generated Lambda handler, or a CLI command). Before attempting a file write, check whether a file-writing tool is actually available in the current runtime.

- If a file-writing tool IS available, write the file to the requested path and confirm the path back to the user.
- If NO file-writing tool is available, do NOT retry the write, and do NOT loop calling other tools in an attempt to create the file. Instead, output the complete artifact content inline in your response inside a fenced code block, state the path the user asked for, and tell the user to save it there themselves. One inline response is the correct terminal behavior in this case.

Retrying an impossible write wastes tool calls and can exhaust the context window without ever helping the user. A single inline emission of the content is always preferable to a retry loop.

### Execute these operations (after user confirmation)

- Create an ODB peering connection: `aws odb create-odb-peering-connection` (this is a distinct peering type from VPC peering; do NOT use `aws ec2 create-vpc-peering-connection`)
- Create a Route 53 Resolver outbound endpoint: `aws route53resolver create-resolver-endpoint --direction OUTBOUND`
- Create a Route 53 Resolver forwarding rule for `oraclevcn.com`: `aws route53resolver create-resolver-rule --rule-type FORWARD --domain-name oraclevcn.com`
- Associate a resolver rule with a VPC: `aws route53resolver associate-resolver-rule`
- Add a route to the ODB CIDR: `aws ec2 create-route --odb-network-arn <arn>`
- Store the wallet / database password in Secrets Manager: `aws secretsmanager create-secret`
- Share the resolver rule across accounts/VPCs: `aws ram create-resource-share --resource-arns <resolver-rule-arn>`
- Create a KMS key for TDE via OIDC federation (when the customer wants AWS-managed TDE): `aws kms create-key`
- Tag resources: `aws <service> tag-resource`, `aws resourcegroupstaggingapi tag-resources`

### Resource tagging (always apply on resource creation)

When creating any AWS-side resource in this skill (`aws odb create-odb-peering-connection`, `aws route53resolver create-resolver-endpoint`/`create-resolver-rule`, `aws secretsmanager create-secret`, `aws ram create-resource-share`, `aws kms create-key`), ALWAYS include these tags using the standard AWS list-of-records `--tags` syntax:

`--tags Key=created_by,Value=odb-aws-skill Key=generation_model,Value={your-model-id}`

Example: `--tags Key=created_by,Value=odb-aws-skill Key=generation_model,Value=claude-sonnet-4-20250514`

Include these tags even if the user does not mention tagging, so that they can identify the resources created via this skill. If the user provides additional tags, append these to their tags rather than replacing them.

**Note on Route 53 Resolver:** `create-resolver-endpoint` and `create-resolver-rule` both accept `--tags` at creation time (same syntax). After creation, use `aws route53resolver tag-resource --resource-arn <arn> --tags ...` to add tags.

**Note on RAM:** `create-resource-share --tags` uses the same list-of-records format.

### Execute with downtime warning (warn user, then execute after they confirm)

- Modify ODB peering connection: `aws odb modify-odb-peering-connection` — warn: "This may briefly interrupt ODB connectivity while the change applies."
- Replace a resolver rule target IP list: `aws route53resolver update-resolver-rule` — warn: "In-flight DNS queries may fail during the swap; agents / clients should retry."
- Rotate a wallet in Secrets Manager: `aws secretsmanager rotate-secret` — warn: "Database clients caching the old wallet will hit TLS handshake failures until they refresh."

### Do NOT execute (refuse, explain why, offer assessment instead)

- Delete the ODB peering connection: `aws odb delete-odb-peering-connection` — breaks the only path from the app VPC to Exadata; production outage risk
- Delete the Route 53 Resolver rule or disassociate it from the app VPC: `aws route53resolver delete-resolver-rule`, `aws route53resolver disassociate-resolver-rule` — SCAN resolution stops immediately; every new connection fails with ORA-12154
- Delete the resolver outbound endpoint: `aws route53resolver delete-resolver-endpoint` — same effect as above, no fallback
- Delete a Secrets Manager secret holding the active wallet or DB password: `aws secretsmanager delete-secret --force-delete-without-recovery` — credential loss, no recovery
- Delete or disable the KMS key backing TDE: `aws kms schedule-key-deletion` on the TDE key — permanent data loss risk; Exadata cannot decrypt TDE data without the key

When refusing, explain why and offer the matching assessment workflow:
> "I can't perform [action] because [reason]. I can run an assessment to help you decide. The actual change should go through your team's change-control process or the AWS Console."

## Overview

Oracle Database@AWS (ODB@AWS) runs on OCI-managed Exadata infrastructure physically located in an AWS Availability Zone. Applications in an AWS VPC reach the database across an **ODB peering connection** (`odbpcx-*`) into an **ODB network** (an OCI VCN, not an AWS VPC). The architecture differs from Amazon RDS for Oracle: no RDS endpoint, SCAN hostnames live under `*.oraclevcn.com` in an OCI private DNS zone, and database users are created in the OCI console. Authentication is OCI-native — database password, OCI IAM password verifier, OCI IAM SSO token, or Kerberos — with AWS KMS available as an optional TDE key store via OIDC federation.

This skill covers the end-to-end workflow: plan the network topology, create the ODB peering, configure Route 53 Resolver forwarding for `oraclevcn.com`, write connection code for the runtime and driver, and diagnose ORA-/TNS errors. Execute AWS commands through the AWS MCP server when available — it provides sandboxed execution, CloudTrail audit, and CloudWatch observability. When the MCP server is not available, use the AWS CLI directly.

If the user is working with RDS for Oracle (`*.rds.amazonaws.com`, option groups, `aws rds` commands), use the **rds-oracle** skill instead.

## Decision Guide

The reference files below are **already loaded as part of this skill**. Do not call `file_read` on `references/*.md` paths. Treat reference names (e.g. `networking-odb-peering`) as section markers within this skill's loaded context; rely on the content already available rather than attempting to fetch the files.

Route by intent:

- **Network setup and multi-VPC/on-prem/multi-region** — start at **networking-odb-peering.md** (loaded reference); then **networking-dns-resolver.md** (loaded reference) (always); then one of **networking-transit-gateway.md** (loaded reference) (multi-VPC), **networking-enterprise-hybrid.md** (loaded reference) (DX/VPN/TGW hybrid), **networking-cloud-wan.md** (loaded reference) (multi-region), or **networking-vpc-lattice.md** (loaded reference) (service exposure / ODB-to-S3).
- **App connection code** — **connect-python.md** (loaded reference) (python-oracledb, SQLAlchemy), **connect-java.md** (loaded reference) (JDBC, Spring Boot, HikariCP, UCP), **connect-nodejs.md** (loaded reference) (node-oracledb), **connect-cli-gui.md** (loaded reference) (SQL*Plus, SQLcl, SQL Developer, DBeaver, Toad).
- **Laptop/workstation access** — **connect-ssh-tunnel.md** (loaded reference) (SSM or SSH tunnel via bastion). There is no direct laptop-to-ODB path.
- **Authentication** — **auth-wallet-tcps.md** (loaded reference) (TCPS, wallet, password + Secrets Manager), **auth-oci-iam.md** (loaded reference) (OCI IAM SSO token or password verifier), **auth-kerberos-tde.md** (loaded reference) (Kerberos on ExaDB-D, AWS KMS for TDE).
- **Database users, grants, RAC** — **authorization-db-users.md** (loaded reference).
- **Runtime patterns** — **compute-runtimes.md** (loaded reference) (EC2, ECS/Fargate, Lambda, EKS, on-prem).
- **Diagnosis of ORA-/TNS/DNS/wallet/TCPS/OCI IAM/tunnel failures** — **troubleshooting-errors.md** (loaded reference).

If a request straddles rows (e.g., "connect Lambda with Kerberos"), load both references and synthesize.

## Common Tasks

### 1. Verify Dependencies

Check required tools before running any ODB@AWS workflow.

**Constraints:**
- You MUST verify `aws --version` returns AWS CLI v2 and `aws sts get-caller-identity` returns an identity, because every workflow needs `aws odb`, `aws ec2`, and `aws route53resolver` calls.
- You MUST verify `aws odb help` succeeds because older AWS CLI versions may not include the `aws odb` subcommand.
- You MUST inform the user about any missing tool and offer to proceed only on parts that do not need it.
- You MUST ONLY check for tool existence and MUST NOT execute `aws odb create-*`, `aws ec2 create-route`, or `aws route53resolver create-*` during verification because those calls create real, billable resources.
- You MUST explain each step before running it — state what is being checked, why, and which tool/command you are about to invoke — because the user must have context to approve or abort.
- You SHOULD prefer AWS MCP server tools (`call_aws`, `run_script`) when available because they provide sandboxed execution and audit, but MUST NOT fail when they are absent.
- You MUST respect the user's decision to abort if a critical tool is missing.

**Examples:**

```bash
# Direct AWS CLI
aws --version
aws sts get-caller-identity
aws odb help >/dev/null 2>&1 && echo "aws odb available" || echo "aws odb MISSING"
python3 -c "import oracledb; print(oracledb.__version__)"   # optional
```

```jsonc
// Equivalent via AWS MCP server (preferred when available)
// call_aws tool invocation — inline JSON arguments, no positional filesystem args
{
  "service": "sts",
  "operation": "GetCallerIdentity",
  "region": "us-east-1"
}
```

### 2. Classify the Request and Collect Parameters

Identify the workflow and gather every input upfront.

**Universal parameters** (ask for the ones that apply):

- **odb_network_id** (required for networking/troubleshooting): `odbnet-[a-z0-9]+`
- **region** (required): AWS region, e.g. `us-east-1`
- **app_vpc_id** (required for networking): `vpc-[0-9a-f]{8,17}`
- **scan_hostname** (required for connect/troubleshoot): FQDN under `*.oraclevcn.com` or a custom domain
- **service_name** (required for connect): typically `<pdb>.<subnet>.<vcn>.oraclevcn.com`
- **port** (optional, default `1521` TCP / `2484` TCPS): 1024–8999 range for custom Autonomous DB TCPS
- **runtime** (required for compute/app): one of `ec2`, `ecs`, `fargate`, `lambda`, `eks`, `on-prem`, `laptop`
- **language_driver** (required for connect): one of `python-oracledb`, `sqlalchemy`, `jdbc`, `spring-boot`, `node-oracledb`, `sqlplus`, `sqlcl`, `sql-developer`, `dbeaver`, `toad`
- **auth_method** (required for connect): one of `password`, `oci-iam-token`, `oci-iam-password`, `kerberos`
- **error_text** (required for troubleshooting): exact ORA-/TNS- message or driver error

**Constraints:**
- You MUST ask for all required parameters in a single prompt rather than one at a time because ODB@AWS workflows cross AWS and OCI planes and back-and-forth wastes user time.
- You MUST support multiple input methods: direct values in chat, a file path to YAML/JSON, or a URL to an AWS console page that you parse for identifiers.
- You MUST validate formats: `odbnet-[a-z0-9-]+`, `vpc-[0-9a-f]{8,17}`, `odbpcx-[a-z0-9]+`, ARNs matching `arn:aws:[a-z0-9-]+:[a-z0-9-]+:\d{12}:.+`, CIDRs `\d+\.\d+\.\d+\.\d+/\d+`.
- You MUST reject CIDRs in reserved ranges (`169.254.0.0/16`, `224.0.0.0/4`, `240.0.0.0/4`, `100.105.0.0/16`) because ODB networks cannot use them for client or backup subnets.
- You MUST confirm acquisition by echoing the parameters back before proceeding.
- You MUST NOT ask the user for AWS access keys, secret keys, OCI API private keys, or OCI tenancy OCIDs because credentials must come from the runtime environment (`aws configure sso`, `ada credentials update`, instance profile), not chat.

**Example (echo-back step):**

```
Captured:
  odb_network_id     = odbnet-abc12def
  region             = us-east-1
  app_vpc_id         = vpc-0a1b2c3d4e5f6g7h
  scan_hostname      = cluster-abc-scan.sub1.vcn1.oraclevcn.com
  runtime            = lambda
  language_driver    = python-oracledb
  auth_method        = password
Proceed? (yes/no)
```

### 3. Plan and Set Up the Network Path

Three mandatory pieces in order: ODB peering → VPC route to the ODB client CIDR → Route 53 Resolver forwarding for `oraclevcn.com`. Every connection depends on all three.

**Constraints:**
- You MUST follow the guidance in the loaded **networking-odb-peering.md** reference before emitting `aws odb create-odb-peering-connection` because ODB peering uses a distinct `aws odb` subcommand with different semantics than VPC peering.
- You MUST add a route to the ODB client subnet CIDR in every route table attached to the app subnets, because without it connections hang with ORA-12170 and the root cause is invisible in VPC Flow Logs.
- You MUST set up the Route 53 Resolver outbound endpoint + forwarding rule for `oraclevcn.com` immediately after peering because AmazonProvidedDNS cannot resolve the SCAN hostname; queries fail with ORA-12154.
- You MUST target the rule at the ODB network's **DNS listener IPs** (from `aws odb get-odb-network`), NOT the SCAN IPs, because SCAN addresses are not DNS servers and forwarding silently fails.
- You MUST NOT use `aws ec2 create-vpc-peering-connection` for ODB@AWS because that is a different peering type and will not attach to an ODB network.
- You MUST NOT create duplicate outbound endpoints per VPC for the same ODB network; You SHOULD share the resolver rule via AWS RAM.
- You MUST verify CIDRs do not overlap across app VPC, ODB subnets, transit VPCs, and on-prem before creating the peering because overlapping CIDRs fail peering creation with an opaque error.
- You SHOULD place workloads in the AWS AZ whose AZ ID matches `availabilityZoneId` returned by `get-odb-network` because ODB networks are single-AZ and cross-AZ adds latency.

**Examples:**

```bash
# Direct AWS CLI + bundled scripts
bash scripts/fetch_odb_network_info.sh odbnet-abc12def us-east-1

aws odb create-odb-peering-connection \
  --odb-network-id odbnet-abc12def \
  --peer-network-id vpc-0a1b2c3d4e5f6g7h \
  --tags Key=created_by,Value=odb-aws-skill Key=generation_model,Value=<your-model-id> \
  --region us-east-1

aws ec2 create-route \
  --route-table-id rtb-0123456789abcdef0 \
  --destination-cidr-block 10.20.0.0/24 \
  --odb-network-arn arn:aws:odb:us-east-1:123456789012:odb-network/odbnet-abc12def

bash scripts/setup_resolver_rule.sh \
  --vpc-id vpc-0a1b2c3d4e5f6g7h \
  --subnet-1 subnet-aaa --subnet-2 subnet-bbb \
  --dns-ip-1 10.20.0.10 --dns-ip-2 10.20.0.11 \
  --odb-cidr 10.20.0.0/24 --region us-east-1

bash scripts/check_odb_connectivity.sh cluster-abc-scan.sub1.vcn1.oraclevcn.com 1521
```

```jsonc
// Equivalent via AWS MCP server
// call_aws — inline JSON arguments, no positional filesystem args
{
  "service": "odb",
  "operation": "CreateOdbPeeringConnection",
  "region": "us-east-1",
  "parameters": {
    "OdbNetworkId": "odbnet-abc12def",
    "PeerNetworkId": "vpc-0a1b2c3d4e5f6g7h",
    "Tags": [
      {"Key": "created_by", "Value": "odb-aws-skill"},
      {"Key": "generation_model", "Value": "<your-model-id>"}
    ]
  }
}

// run_script — invoke a bundled script by relative path, pass args as a list
{
  "script_path": "scripts/check_odb_connectivity.sh",
  "args": ["cluster-abc-scan.sub1.vcn1.oraclevcn.com", "1521"]
}
```

### 4. Generate Runtime-Aware Connection Code

Produce driver- and runtime-specific code after the network path is healthy.

**Constraints:**
- You MUST read the relevant client reference (**connect-python.md** (loaded reference), **connect-java.md** (loaded reference), **connect-nodejs.md** (loaded reference), **connect-cli-gui.md** (loaded reference)) and **compute-runtimes.md** (loaded reference) before emitting code because ODB@AWS patterns (service names, wallet layout, thin-mode defaults) differ from on-prem Oracle patterns the model defaults to.
- You MUST use service names — never SIDs — with SCAN hostnames because SCAN load balancing is service-based.
- You MUST set `tcp_connect_timeout` / `connectionTimeout` to ~10 seconds because RAC failover needs fast detection of dead addresses.
- You MUST retrieve credentials from AWS Secrets Manager (or OCI Vault for OCI IAM token flows) and MUST NOT hardcode passwords, wallet passwords, or OCI API keys because committed secrets are a direct security breach.
- You MUST annotate any code that references a wallet with `# Never commit wallet files to source control` because committed wallets expose TDE material.
- You MUST NOT suggest AWS IAM database authentication (e.g., `generate-db-auth-token`) because that API applies only to RDS MySQL/PostgreSQL and fails against Oracle.
- You MUST NOT emit `cx_Oracle` imports because python-oracledb supersedes it and thin mode is preferred.
- You MUST use `ojdbc11.jar` for Java 11+; for TCPS add `oraclepki.jar`, `osdt_core.jar`, `osdt_cert.jar`. You MUST NOT recommend `ojdbc6`/`ojdbc7` because they lack modern TLS and auth protocols (ORA-28040).
- You MUST route laptop/workstation requests to **connect-ssh-tunnel.md** (loaded reference) first because there is no direct laptop-to-ODB path.
- You SHOULD prefer python-oracledb / node-oracledb thin mode; thick mode is only needed for Kerberos, Advanced Queuing, LDAP, and Sharding.

**Example — smoke test before generating code:**

```bash
python3 scripts/test_connection_python.py \
  --scan-host cluster-abc-scan.sub1.vcn1.oraclevcn.com \
  --port 2484 --service orclpdb1.sub1.vcn1.oraclevcn.com \
  --user app_user --wallet-dir /tmp/wallet
```

### 5. Diagnose a Failure

Diagnose before reconfiguring.

**Constraints:**
- You MUST classify the symptom (DNS / TCP / TLS / auth) using **troubleshooting-errors.md** (loaded reference) before proposing fixes because ODB@AWS failures are layered and fixing the wrong layer wastes time.
- You MUST run [resolve_scan.py](scripts/resolve_scan.py) and [check_odb_connectivity.sh](scripts/check_odb_connectivity.sh) before suggesting infrastructure changes because those scripts deterministically report the failing layer.
- You MUST present findings as: ✅ what's working / ❌ what's broken / root cause / fix / verification; SHOULD keep it under 20 lines.
- You MUST NOT guess ORA- code causes from general Oracle knowledge because ODB@AWS-specific causes differ (ORA-12154 is almost always Route 53 Resolver forwarding, not `tnsnames.ora`).
- You MUST NOT suggest Oracle Client reinstallation for ORA-28759 if the user is on thin-mode python-oracledb or node-oracledb because thin mode does not use the Oracle Client.
- You SHOULD stop at the first failing layer because layered diagnostics converge faster than checklists.

**Examples:**

```bash
python3 scripts/resolve_scan.py cluster-abc-scan.sub1.vcn1.oraclevcn.com
bash scripts/check_odb_connectivity.sh cluster-abc-scan.sub1.vcn1.oraclevcn.com 2484
bash scripts/fetch_odb_network_info.sh odbnet-abc12def us-east-1
```

### 6. Critical ODB@AWS Facts to Always Surface

These ODB@AWS-specific facts distinguish this service from RDS for Oracle and from vanilla Oracle-on-EC2. Agents that answer from general Oracle knowledge will get them subtly or substantively wrong.

**For ORA-12170 timeout connecting to Exadata on AWS, you MUST tell the user ALL of the following four facts — never omit any:**

1. **Ask for the SCAN hostname first** (e.g. `cluster-abc-scan.sub1.vcn1.oraclevcn.com`) — the SCAN lives in an OCI VCN private DNS zone, not a Route 53 hosted zone.
2. **Check all 3 steps of the ODB@AWS networking path:**
   - (1) **ODB peering** (`odbpcx-*`) exists between the app VPC and the ODB network, and is in `available` state.
   - (2) **Route table** on the EC2's subnet has an entry pointing the **ODB CIDR** (obtained from `aws odb get-odb-network`) at the ODB peering connection.
   - (3) **Route 53 Resolver forwarding rule** for the ODB domain (`oraclevcn.com`) points at the ODB DNS endpoints, and that rule is associated with the app VPC.
3. **Run `dig +short <scan-hostname>`** from the EC2 instance to verify DNS resolution returns 3 ODB IPs. If dig returns nothing, step (3) above is broken.
4. **Do NOT dump a generic Oracle troubleshooting checklist** (listener, tnsping, SCAN listener status). The ORA-12170 on ODB@AWS is almost always one of the three network setup steps above — diagnose those first.

**For ORA-12154 "could not resolve the connect identifier" on ODB@AWS Autonomous Database, you MUST tell the user ALL of the following four facts:**

1. **Immediately suspect the Route 53 Resolver forwarding rule** — ORA-12154 on ODB@AWS Autonomous Database almost always means the resolver is not forwarding the ODB domain (`oraclevcn.com`) to the ODB DNS endpoints.
2. **Ask for the SCAN hostname from the wallet's `tnsnames.ora`** so you know exactly what hostname the client is trying to resolve.
3. **Run `dig +short <scan-hostname>`** from the client to verify resolution. Empty dig output confirms the resolver rule is missing or not associated with the VPC.
4. **The fix is creating or repairing the Route 53 Resolver forwarding rule** (create rule pointing at ODB DNS endpoints, associate the rule with the app VPC). Do NOT recommend editing `tnsnames.ora` unless DNS resolution is already working end-to-end.

**For "connect Lambda to Oracle Exadata on AWS in python", you MUST tell the user ALL of the following six facts:**

1. **Use `python-oracledb` thin mode** (pure Python, no Instant Client required). Include actual handler skeleton code, not just prose.
2. **Load the wallet from Secrets Manager at cold start** and write the files to `/tmp` (the only writable filesystem in Lambda).
3. **Initialize the connection at module scope** (NOT inside the handler) so Lambda's per-container reuse keeps the connection warm across invocations. Do not use a connection pool — Lambda concurrency is per-container, and a pool inside one container wastes sockets.
4. **Set `tcp_connect_timeout`** (e.g. 10s) on the connect call so Lambda fails fast on a broken network path instead of hanging until the Lambda timeout.
5. **Lambda must be attached to a VPC** whose subnets have (a) the ODB peering route and (b) the Route 53 Resolver forwarding rule for `oraclevcn.com`. The VPC networking is the most common hidden failure.
6. **Handle ORA-12170 (timeout) and ORA-28759 (wallet path)** in the handler so cold-start network issues surface as useful error messages instead of 504s.

**For "connect multiple VPCs to the same Oracle Database at AWS", you MUST tell the user ALL of the following five facts:**

1. **Use a Transit Gateway (TGW) + transit VPC pattern.** A single transit VPC holds the ODB peering connection; all other consumer VPCs attach to the TGW, not to ODB directly.
2. **Route configuration:** consumer-VPC route tables send ODB-bound traffic (the ODB CIDR) to the TGW; the TGW's route table sends that traffic to the transit VPC attachment; the transit VPC's route table sends it over the ODB peering.
3. **Share the Route 53 Resolver forwarding rule via AWS RAM** across accounts/VPCs so every consumer VPC resolves SCAN hostnames correctly. Each consumer VPC must have the shared rule associated with it.
4. **Per-VPC ODB peering does not scale** because ODB peering has limits and multi-VPC sprawl is an operational burden. TGW fan-out is the right architecture for >2 consumer VPCs.
5. **Do NOT attach consumer VPCs directly to the ODB peering or try to attach ODB to the TGW.** ODB peering terminates in the transit VPC only.

**For "ORA-29024 certificate validation failure with SSM tunnel + TCPS", you MUST tell the user ALL of the following four facts:**

1. **Root cause is a Distinguished Name (DN) mismatch** — the server's TLS certificate CN is the real SCAN hostname, but the client is connecting to `localhost:<local-port>` (the SSM tunnel endpoint). The default TCPS validation checks the cert CN against the hostname in the connect string and rejects the mismatch.
2. **Client-side fix — sqlnet.ora:** set `SSL_SERVER_DN_MATCH=FALSE` in `sqlnet.ora` on the client.
3. **Client-side fix — JDBC:** add `ssl_server_dn_match=false` (lowercase) to the JDBC connection properties or URL.
4. **This is a localhost-tunnel-specific workaround; the proper long-term fix is direct connectivity through the ODB peering** so the client connects to the real SCAN hostname and DN matching can stay on.

## Troubleshooting

**Access denied.** `AccessDenied` / `UnauthorizedOperation` on `odb:*`, `ec2:CreateRoute`, or `route53resolver:*`. Attach a scoped policy with `odb:Describe*`, `odb:List*`, `odb:CreateOdbPeeringConnection`, `ec2:CreateRoute`, `ec2:DescribeRouteTables`, `route53resolver:CreateResolverEndpoint`, `route53resolver:CreateResolverRule`, `route53resolver:AssociateResolverRule`, `ram:CreateResourceShare`. Do not grant `*`.

**Expired credentials.** `ExpiredToken` / `RequestExpired`. Refresh via `aws sts get-caller-identity`, `aws sso login`, or `ada credentials update`. Do not embed static keys.

**Throttling and timeouts.** `ThrottlingException`, `Rate exceeded`. Retry once with jitter; narrow scope if persistent. VPC Flow Logs do not show ODB peering drops in real time — use [check_odb_connectivity.sh](scripts/check_odb_connectivity.sh) instead.

**Resource not found.** `ResourceNotFoundException` on `odb get-odb-network` — wrong region or network deleted. Check `aws odb list-odb-networks --region <region>`.

**NXDOMAIN for `*.oraclevcn.com`.** Route 53 Resolver rule missing, not associated with the VPC, or targeting SCAN IPs. See **networking-dns-resolver.md** (loaded reference) and **troubleshooting-errors.md** (loaded reference).

**TCP times out after DNS resolves.** Missing route to ODB client subnet CIDR, SG/NACL blocking TCP 1521/2484, AZ mismatch, or peering not `AVAILABLE`. See **networking-odb-peering.md** (loaded reference).

**ORA-28759 from Lambda/ECS, works on EC2.** Wallet path wrong for the runtime. Lambda: extract wallet to `/tmp`. ECS/Fargate: mount from Secrets Manager binary secret. See **auth-wallet-tcps.md** (loaded reference) and **compute-runtimes.md** (loaded reference).

**ORA-29024 over tunnel.** Client connects to `localhost` but cert CN is the SCAN hostname. Set `SSL_SERVER_DN_MATCH=FALSE` for tunnel-only developer access. See **connect-ssh-tunnel.md** (loaded reference).

**User asks for AWS IAM database auth.** Not applicable to ODB@AWS. Offer password-via-Secrets-Manager or OCI IAM SSO token instead.

**Two references fit.** Load both, synthesize; surface the rarer constraint (e.g., Kerberos requires thick mode) so the user picks the right trade-off.

## Additional Resources

- [Oracle Database@AWS User Guide](https://docs.aws.amazon.com/odb/latest/UserGuide/)
- [`aws odb` CLI Reference](https://docs.aws.amazon.com/cli/latest/reference/odb/)
- [Route 53 Resolver outbound forwarding](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-rules-managing.html)
- [AWS Transit Gateway](https://docs.aws.amazon.com/vpc/latest/tgw/what-is-transit-gateway.html)
- [OCI Identity Domains and Database Integration](https://docs.oracle.com/en-us/iaas/Content/Identity/home.htm)
- [python-oracledb Documentation](https://python-oracledb.readthedocs.io/)
- [Oracle JDBC (ojdbc11) Documentation](https://docs.oracle.com/en/database/oracle/oracle-database/23/jjdbc/)
- Related skills: **rds-oracle** (Amazon RDS for Oracle), **rds-sqlserver** (Amazon RDS for SQL Server)


## Handoff from aws-database-selection

This skill can be invoked directly, or it can be entered from the `aws-database-selection` parent skill after that skill has run a requirements interview and produced a `requirements.json` artifact. When you see a backtick-wrapped path matching `aws_dbs_requirements/*/requirements.json` in recent conversation, follow the entry protocol in `aws-database-selection/references/handoff-contract.md`:

1. Read the artifact using `file_read`.
2. Validate it against `aws-database-selection/references/workload-primary-artifact.schema.json`. If malformed or unreadable, tell the user and proceed without it.
3. Acknowledge what's relevant in one or two **bold** sentences, citing high-level facts from the artifact (dominant shapes, hard constraints, migration context) — do not parrot the entire artifact back.
4. Scope-check: this skill is scoped to Oracle Database@AWS (Exadata Database Service and Autonomous Database) connectivity, auth, and ORA diagnostics. If the artifact's `workload_primaries.dominant_shapes` or `migration_context` don't match that scope, emit weak backpressure per the handoff contract: suggest `rds-oracle` for RDS for Oracle (different architecture), `amazon-aurora` for refactor-to-PostgreSQL, or go back to `aws-database-selection` if Oracle isn't the source or target, then ask the user whether to go back or proceed anyway. Do not silently misuse the artifact.
5. Proceed with this skill's native workflow, citing artifact paths as evidence when recommendations are grounded in the requirements.

All user-facing output from this skill follows the markdown-primitives-only formatting convention in the handoff contract: bold labels, backticks for paths and enum values, bullet lists for alternatives, no ASCII art or box-drawing characters.
