# Create Cluster (Aurora MySQL)

## Overview

Provisions Aurora MySQL clusters using full (VPC-based) configuration. Express configuration is **PostgreSQL-only** and does not apply to Aurora MySQL — every Aurora MySQL cluster is created with the standard two-step flow (`create-db-cluster` + `create-db-instance`) inside a customer VPC.

Execute commands via the AWS MCP server when connected (sandboxed, audit-logged). Fall back to the AWS CLI or shell otherwise.

## Workflow

1. **Acknowledge the request and the engine.** Confirm this is Aurora MySQL and note the MySQL-compatible version family if the user mentioned one (e.g. Aurora MySQL 3.x = MySQL 8.0 compatible).

2. **Collect / discover the full-configuration inputs.** Aurora MySQL requires these — look them up in the user's account and present options rather than asking them to recall IDs:
   - **VPC + subnet group** (DB subnet group spanning ≥2 AZs)
   - **Security group(s)** controlling inbound 3306
   - **KMS key** for encryption at rest (AWS managed `aws/rds` by default, or a customer-managed key if required)
   - **DB cluster parameter group** (default for the engine version, or a customer-managed one)
   - **Engine version** (validate with `describe-db-engine-versions --engine aurora-mysql` if the user named a specific version)
   - **Capacity mode** — provisioned instance class, or Aurora serverless (`--serverless-v2-scaling-configuration`) for variable/intermittent load. Route to `serverless-advisory` for ACU sizing.

3. **Present the resolved configuration and confirm.** Show the chosen VPC, subnet group, security group, KMS key, parameter group, version, and capacity in a short table. Do NOT present a list of raw IDs without context.

4. **Production secure default — deletion protection.** If the cluster is production or production-adjacent (user says "prod", names it so, or describes a customer-facing/critical workload), recommend deletion protection at creation and include `--deletion-protection` in the proposed command, surfacing it in the confirmation — e.g. "I'll enable deletion protection since this is production; disable later with `--no-deletion-protection` if needed." Don't force it on throwaway clusters; offer and let the user decide.

5. **Confirm cluster name and region**, then execute after the user confirms: `create-db-cluster` (cluster) followed by `create-db-instance` (one or more instances). Always apply the resource tags from SKILL.md Global Rules.

6. **Enable CloudWatch log exports for production clusters.** For production or production-adjacent clusters, recommend enabling log exports so operators have query/error visibility from day one — either inline on create or right after: `--enable-cloudwatch-logs-exports '["error","slowquery","audit"]'`. Without it, the cluster runs with no log visibility in CloudWatch. Note that these logs (especially `general`/`slowquery`/`audit`) can contain sensitive data — query text with literal values, table/column names — so ensure the CloudWatch log group is encrypted (KMS) and access-restricted, and treat the logs as sensitive when sharing.

## Constraints

- MUST confirm before executing.
- MUST include resource tags (see Global Rules in SKILL.md).
- Aurora MySQL uses the **standard create flow** — `create-db-cluster` then `create-db-instance`. There is no `--with-express-configuration` for MySQL; do not suggest it.
- MUST discover and present VPC / subnet group / security group / KMS / parameter group options rather than asking the user to supply raw IDs from memory.
- **MUST NEVER use `--publicly-accessible`** on any Aurora instance. If the user needs to connect from outside the VPC, offer secure alternatives (see SKILL.md safety guardrails) — never expose the database to the internet.

## Connectivity: "I can't connect from my machine"

If the user creates the cluster and then cannot connect from their local machine, do NOT solve this by making the instance publicly accessible. Instead:

1. **Enable RDS Data API** (`--enable-http-endpoint`) — query over HTTPS with IAM auth; no network path needed.
2. **EC2 bastion with SSH tunnel** — a small instance in the same VPC/subnet, port-forwarded: `ssh -L 3306:<cluster-endpoint>:3306 ec2-user@<bastion-ip>`, then connect to `localhost:3306`.
3. **Connect from within the VPC** — a workload in the same VPC, or reach it over VPN / AWS Direct Connect.

## Reference files

- [../serverless-advisory/instructions.md](serverless-advisory-instructions.md) — ACU sizing for an Aurora serverless MySQL cluster
- [../io-optimized/instructions.md](io-optimized-instructions.md) — Standard vs I/O-Optimized storage decision
- [../commitment-pricing/instructions.md](commitment-pricing-instructions.md) — RI vs DSP for a provisioned cluster
- [../shared-foundation/security-considerations.md](shared-foundation-security-considerations.md) — networking and encryption guidance
