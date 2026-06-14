# Aurora Express Configuration — Feature Overview

## Response requirements

When explaining what express configuration IS, you MUST include ALL of:

1. You MUST state that it provisions an **Aurora serverless** cluster (not just "Aurora" or "Aurora PostgreSQL")
2. You MUST mention the **internet access gateway** as the connectivity mechanism (no customer VPC)
3. You MUST cite a docs.aws.amazon.com URL (e.g. https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html)
4. You MUST NOT claim Aurora MySQL is supported in express configuration

---

This file expands on what `SKILL.md` summarizes about Aurora PostgreSQL express configuration. It is pulled into context on demand when the user digs into how the AWS-managed connectivity layer works, how multi-AZ routing is delivered without a customer VPC, or which defaults the express flow applies. Verify current behavior, defaults, and regional availability in the AWS User Guide.

## Internet access gateway

Express configuration clusters replace the customary customer-VPC plumbing (VPC, subnet group, route tables, security groups, VPC endpoints) with an AWS-managed routing layer that terminates PostgreSQL wire-protocol connections on the cluster's behalf. The user picks a cluster name; AWS returns an endpoint hostname. Nothing is peered, attached, or configured at the network layer.

Functionally, this layer is a public connectivity front-end: it accepts TLS-wrapped PostgreSQL connections, routes them to the underlying Aurora serverless cluster, and handles AZ placement and failover transparently. Because it is AWS-managed, the user has no control over listen ports, cipher policy, network-layer IP allow lists, or protocol-level tuning. Authentication uses IAM database authentication only — express clusters do not support password-based authentication on the master user or Secrets Manager integration. The master user is automatically configured for IAM auth, and subsequent database users must be too.

The exact AWS documentation term for this component — "internet access gateway", "managed connectivity layer", or another name — should be confirmed in the AWS User Guide before citing it verbatim in customer-facing material. Whatever the published term, the functional model is the same: AWS-managed, multi-AZ, distributed, no customer-side config.

Because connectivity is public-internet-facing, workloads that require the cluster to be reachable only from inside a customer VPC (VPC endpoints, PrivateLink-only routing, on-prem peering via Transit Gateway, or strict egress controls) are not a fit. They belong on Full Configuration, where the cluster is placed in a customer-owned VPC and standard Aurora networking applies.

## Multi-AZ routing

The managed connectivity layer is distributed across multiple Availability Zones by default. Users get AZ-level resiliency for the connection path without configuring a subnet group or selecting AZs — failover and AZ placement are handled entirely by AWS. From the application's perspective this matches the HA posture of a standard Aurora serverless cluster: clients connect to an endpoint, and the underlying topology is AWS-managed.

Because the user does not select subnets, there is nothing to tune around AZ selection, subnet CIDR ranges, or route priorities. If a workload requires precise control over AZ placement (for example, co-locating the database with application compute in a specific AZ), Full Configuration with a customer VPC and a customer-selected subnet group is the appropriate choice. Subject to change — verify current AZ-selection behavior in the User Guide.

## Preconfigured defaults

Express configuration applies the following defaults. Values marked "verify in the AWS User Guide" are subject to change; check current documentation before relying on a specific value.

- **Engine**: Aurora PostgreSQL. The major/minor version offered is the AWS default — verify in the [Aurora PostgreSQL User Guide page](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html).
- **Capacity mode**: Aurora serverless with ACU-based auto-scaling. Provisioned instance classes are not selectable.
- **Min / max ACU**: the AWS default Aurora serverless capacity range — verify in the AWS User Guide. Applied when the user does not customize capacity; whether the express flow lets the user override them is subject to change.
- **Networking**: AWS-managed connectivity layer (internet access gateway). No customer VPC, subnet group, or security group is used or attachable.
- **Parameter group**: the default Aurora PostgreSQL cluster parameter group for the selected engine version. Changeable after creation — but swapping a cluster's parameter group is a Tier 3 / Block operation for this skill (it can break running applications), so the skill will not execute it; apply a customer-managed parameter group via the AWS Console or change-control (static parameters take effect after a reboot). See the [Aurora PostgreSQL parameters User Guide page](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.PostgreSQL.CommonDBATasks.Parameters.html). If a workload needs non-default parameters from the outset (e.g. a custom `shared_preload_libraries` or tuned `max_connections`), that is a signal Full Configuration is the better starting point.
- **Storage type**: Aurora Standard at create — Aurora I/O-Optimized is not selectable during express create; it can be switched on after creation. Verify in the [Aurora storage configuration User Guide page](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-storage-type.html).
- **Backup retention**: the Aurora default for an express serverless cluster — verify in the AWS User Guide.
- **Encryption at rest**: enabled using an AWS-owned key (SSE-RDS), which is AWS-controlled, not viewable or manageable in your account, and cannot be modified for express clusters. This is a distinct key type from the account-visible AWS managed key (aws/rds), now a legacy option. Customer-managed KMS keys are a Full Configuration concern — verify availability in the AWS User Guide.
- **Deletion protection / final snapshot**: follow the Aurora defaults — verify in the AWS User Guide.

## Regional availability

Express configuration is available in a subset of AWS regions that can expand over time. Do not enumerate regions inline — point users to the [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html) User Guide page for the current list.

## Source documentation

- Create with express configuration (primary reference): https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html
- Aurora serverless: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html
- Aurora PostgreSQL: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html
- Aurora storage type (Standard vs I/O-Optimized): https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-storage-type.html
- Aurora PostgreSQL parameters: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.PostgreSQL.CommonDBATasks.Parameters.html
- AWS What's New — Aurora PostgreSQL express configuration: https://aws.amazon.com/about-aws/whats-new/2026/03/amazon-aurora-postgresql-database/
