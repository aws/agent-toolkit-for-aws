# Create Cluster

## Overview

Provisions Aurora clusters. Express configuration is the default for PostgreSQL (single API call, no VPC setup). Route to full configuration only when the user requires VPC connectivity, Aurora MySQL, customer-managed KMS, custom parameter groups, or a specific engine version.

Execute commands via the AWS MCP server when connected (sandboxed, audit-logged). Fall back to the AWS CLI or shell otherwise.

## Routing: Express vs Full

**Express (default for PostgreSQL):**

- User asks for PostgreSQL without mentioning VPC, KMS, custom params, or specific version
- Single call: `create-db-cluster --with-express-configuration`
- Do NOT separately specify `--engine-mode`, `--serverless-v2-scaling-configuration`, `--master-username`, or `--manage-master-user-password`

**Full configuration (use when):**

- User explicitly requires VPC connectivity
- User asks for Aurora MySQL (express does not support MySQL)
- User needs customer-managed KMS keys
- User needs custom parameter groups
- User needs a specific engine version
- Two calls: `create-db-cluster` + `create-db-instance`

## Workflow

1. **MUST load [../express-create/instructions.md](express-create-instructions.md) first** before any routing decision or API call. It contains the response requirements, routing rules, and full constraint list. Do NOT skip it and go straight to deeper express-create files.

2. **Identify ALL incompatibility triggers in the user's request.** Every match disqualifies express:
   - **VPC** (any mention of "my VPC", VPC ID, subnet, security group, network isolation)
   - **Aurora MySQL** (express is PostgreSQL-only)
   - **Customer-managed KMS** (any mention of CMK, customer-managed key, custom KMS, specific KMS key ARN/ID)
   - **Custom parameter group** (any mention of custom params, custom parameter group, named parameter group)
   - **Specific engine version** (e.g., "version 15.4", "PostgreSQL 14.9", "PostgreSQL 16.x")

3. **State the routing decision FIRST in your response, before any AWS API call, version lookup, resource discovery, or follow-up question.** This MUST be the literal opening sentence(s) of your reply. Use this template:

   **For express:** "Routing to **express configuration** — your request is compatible with the single-API-call flow. [proceed with express response requirements]"

   **For full configuration:** "Routing to **full configuration** because your request includes [list ALL matched triggers — e.g., 'VPC connectivity, customer-managed KMS, and a custom parameter group', or 'a specific engine version (15.4)', or 'Aurora MySQL']. Express configuration doesn't support these, so I'll use the standard creation flow."

   The trigger list MUST name every incompatibility detected. If the user mentioned VPC + KMS + custom params, all three must appear. **A specific engine version is itself a sufficient trigger** — even if the version turns out to be unavailable or invalid in Aurora, the user's intent to specify a version means they don't want express, so route to full first, then handle version availability second.

   Do NOT skip the routing statement for any reason, including: the version doesn't exist, the cluster name conflicts with a constraint, the user might have misspoken, or the request seems ambiguous. State the routing decision based on what the user asked for, then handle complications afterward.

   **Engine version validation:** If you need `describe-db-engine-versions` to verify the requested version, do it AFTER printing the routing statement. Flow: (1) state "Routing to full configuration because you specified version X.Y", (2) "Let me verify that version is available", (3) call the AWS API. The routing statement must be issued first even if the version turns out invalid — separate concerns.

4. **Then proceed with the chosen path:**
   - **Express:** follow the response requirements in `express-create/instructions.md` (state Aurora serverless, mention internet access gateway, cite AWS docs URL, state "ready in seconds")
   - **Full configuration:** look up resources in the user's account (VPCs, KMS keys, parameter groups, security groups), present options, ask for selections

5. Confirm cluster name and region.
6. **Production secure default — deletion protection.** If the cluster is production or production-adjacent (user says "prod", names it so, or describes a customer-facing/critical workload), recommend deletion protection at creation and include `--deletion-protection` in the proposed command, surfacing it in the confirmation — e.g. "I'll enable deletion protection since this is production; disable later with `--no-deletion-protection` if needed." Don't force it on throwaway clusters; offer and let the user decide.
7. Execute after user confirms.

## Constraints

- MUST confirm before executing
- MUST include resource tags (see Global Rules in SKILL.md)
- MUST use `--with-express-configuration` as a single flag (not manual construction)
- MUST NOT present express vs full as a choice to the user — pick the right one based on requirements and propose it
- **MUST open the response with an explicit routing statement** that names the chosen path (express or full) AND, when routing to full, names every incompatibility trigger detected. Do NOT skip the routing statement and jump straight to resource discovery.
- The routing statement is required even when the answer seems "obvious" — implicit routing (running the right workflow without saying so) leaves the user unsure which path was chosen and why
- **MUST NEVER use `--publicly-accessible`** on any Aurora instance. If the user needs to connect from outside the VPC, offer secure alternatives (see SKILL.md safety guardrails). If the workload doesn't actually require a VPC, route to express instead — express clusters are internet-accessible via IAM auth without exposing the database publicly.

## Connectivity: "I can't connect from my machine"

If the user creates a full-config cluster and then cannot connect from their local machine, do NOT solve this by making the instance publicly accessible. Instead:

1. **Re-evaluate the VPC need.** If none (prototype, no compliance requirement), suggest recreating with express configuration — internet-accessible via IAM auth, zero network setup.
2. **Enable RDS Data API** (`--enable-http-endpoint`) — query over HTTPS with IAM auth; no network path needed.
3. **EC2 bastion with SSH tunnel** — a small instance in the same VPC/subnet, port-forwarded: `ssh -L 5432:<cluster-endpoint>:5432 ec2-user@<bastion-ip>`, then connect to `localhost:5432`.

## Reference files

**Always load (workflow step 1):**

- [../express-create/instructions.md](express-create-instructions.md) — Express entry point: response requirements, routing, constraints

**Load on demand:**

- [../express-create/constraints.md](express-create-constraints.md) — constraint catalog
- [../express-create/feature-overview.md](express-create-feature-overview.md) — connectivity, multi-AZ, defaults
- [../express-create/comparison.md](express-create-comparison.md) — express vs full comparison
- [../express-create/use-cases.md](express-create-use-cases.md) — scenarios that fit (or don't)
- [../express-create/migration.md](express-create-migration.md) — express ↔ full migration
- [../express-create/documentation-links.md](express-create-documentation-links.md) — AWS doc links
