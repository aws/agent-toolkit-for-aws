# Aurora Express Configuration — Worked Use Cases

This file reasons from a user's requirements to an Express-vs-Full recommendation. Each example identifies the decisive constraint or use-case fit — the single documented fact that tips the recommendation — and cites it.

Every example is grounded in the AWS Aurora User Guide and the Express Configuration announcement. Express configuration capabilities may evolve; verify the specific constraint in the AWS User Guide before making a production call.

## Example 1: Dev sandbox for a PostgreSQL app

A single developer spins up a PostgreSQL database to back a service they are prototyping. No production traffic, no compliance regime, no VPC isolation required, no colleagues connecting from on-prem.

**Recommendation:** Express Configuration.

This matches the documented good-fit profile in the [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html) User Guide page: a development sandbox where the user wants PostgreSQL in seconds without managing a VPC, subnet group, or security groups. The AWS-managed connectivity layer meets the developer's needs (public endpoint with TLS), Aurora serverless auto-scales within the default ACU range so idle cost stays low, and the cluster is reachable without any network-layer setup.

The decisive fit signal is "no VPC isolation needed" — when that changes, the recommendation flips.

## Example 2: Production workload with VPC isolation

A production PostgreSQL workload for a small SaaS product. The application tier runs in a customer VPC; the database must sit in the same VPC, reachable only from the application's subnets. The team has existing security groups, a documented security posture, and VPC Flow Logs enabled.

**Recommendation:** Full Configuration, not Express Configuration.

Express configuration does not support customer VPC placement — clusters are not placed in a customer VPC, subnet group, or security group. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html). Any workload requiring the cluster to be reachable only from within a customer VPC, depending on security-group-based network policy, or participating in VPC Flow Logs for audit is disqualified by construction. Direct the user to Full Configuration with Aurora PostgreSQL and an appropriate subnet group / security group setup in their VPC.

The decisive fit signal is "must run inside my VPC" — one sentence on the user side, one constraint on the AWS side, and the call is clear.

## Example 3: Hackathon or weekend project

Two developers start a weekend project on Friday evening. They want a PostgreSQL database up before they finish the first migration, and will throw the project away if it does not work out.

**Recommendation:** Express Configuration.

The documented "in seconds" provisioning model and "no infrastructure setup" property make this workload a fit. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html). No VPC to configure, no subnet group to plan, no parameter tuning — the developers focus on the project. If it grows into something production-shaped with VPC requirements, the migration paths in `migration.md` apply.

The decisive fit signal is "time to first query matters more than network control" — the opposite of Example 2.

## Example 4: Aurora MySQL migration

A team is consolidating a MySQL 5.7 workload onto Aurora and wants the fastest path to a running cluster.

**Recommendation:** Not supported in Express Configuration; use Full Configuration with Aurora MySQL.

Express configuration is Aurora PostgreSQL only. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html). The engine is fixed to PostgreSQL; the user cannot pick Aurora MySQL in this flow. Direct the user to Full Configuration with the Aurora MySQL engine; for major-version upgrade planning or v2→v3 specifics, route to `aurora-upgrade-advisor`.

The decisive fit signal is "engine: MySQL" — a hard incompatibility with the express flow.

## Example 5: Internal dev tool with SSO / IAM database authentication

An internal tool that lets employees browse data for debugging. The team wants to avoid managing passwords; SSO-backed IAM database authentication is a hard requirement.

**Recommendation:** Strong fit — express configuration requires IAM authentication.

Express clusters use IAM database authentication exclusively (no password auth) — the only supported method via the internet access gateway. The workload's requirement for IAM/SSO-backed auth aligns with express configuration's constraints, assuming no other VPC-isolation or engine-compatibility requirements disqualify it.

## Example 6: Compliance-regulated workload (HIPAA, PCI, internal policy)

A workload processing regulated data (for example, PHI under HIPAA, cardholder data under PCI DSS, or data under an internal policy mandating customer-controlled network placement and customer-managed KMS keys).

**Recommendation:** Full Configuration, not Express Configuration.

Such regimes typically require customer-controlled network placement (customer VPC, security groups, VPC Flow Logs for audit) and encryption-at-rest under a customer-managed KMS key. Express configuration does not support customer VPC placement and is encrypted at rest with an AWS owned key (SSE-RDS, an AWS-controlled key customers cannot view or manage) — not a customer-managed KMS key. Sources: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html), [Encrypting Amazon Aurora resources](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Overview.Encryption.html). Both are subject to change — verify in the AWS User Guide — but as documented, the express flow's compliance posture is not a fit for this workload class.

The decisive fit signal is "customer-managed KMS key required" or "customer-controlled network placement required" — either one disqualifies the express flow.

## How to apply these examples to your workload

When a user describes a workload, produce a freeform narrative recommendation and cite at least one documented constraint or use-case fit as justification. The examples above show the shape of that reasoning: identify the decisive constraint, cite the AWS source, and make the call.

When the description is ambiguous (for example, "a new app" with no mention of VPC or engine), ask one clarifying question — typically whether the workload requires VPC isolation and whether it requires Aurora MySQL. Those two questions resolve most Express-vs-Full decisions. Once clear, give the recommendation in plain prose, cite the constraint, and — if "not a fit for Express" — direct the user to Full Configuration with the specific engine or networking requirement that disqualified Express.

## Source documentation

- Create with express configuration: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html
- Aurora serverless: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html
- Aurora PostgreSQL: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html
- IAM database authentication: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.html
- Encrypting Aurora resources: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Overview.Encryption.html
