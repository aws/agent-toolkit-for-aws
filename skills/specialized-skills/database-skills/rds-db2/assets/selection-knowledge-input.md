# RDS for Db2 selection knowledge

This document is the human-readable companion to `selection-knowledge-input.json`.
It describes the Amazon RDS for Db2 service facts that the cross-service
`aws-database-selection` skill uses to recognize and reason about RDS for Db2
workloads. Both files carry the same facts; the JSON is the machine-readable
form and this Markdown narrates it.

## Service and editions

- **Service:** Amazon RDS for Db2 (`amazon-rds-for-db2`).
- **Engine editions:** Standard Edition (`db2-se`) and Advanced Edition (`db2-ae`).

## Licensing

RDS for Db2 uses a bring-your-own-license model. Provisioning requires two IBM
identifiers supplied on the instance:

- `rds.ibm_customer_id`
- `rds.ibm_site_id`

## Source-migration scenarios

The in-scope source databases and the recommended approach for moving each to
RDS for Db2:

| Source | Approach | Notes |
|---|---|---|
| Db2 for z/OS (`db2-zos`) | Replatform | Schema conversion with ADB2GEN; change data capture via Q Replication/IIDR, Qlik, or Precisely; DMS supports full-load only; AWS SCT is not supported for this source. |
| Db2 LUW on Linux (`db2-luw-linux`) | Restore or replicate | Backup/restore or replication into RDS for Db2. |
| Db2 LUW on AIX (`db2-luw-aix`) | Near-zero-downtime via Q Replication | Continuous replication keeps cutover downtime minimal. |
| Db2 LUW on Windows (`db2-luw-windows`) | Near-zero-downtime via Q Replication | Continuous replication keeps cutover downtime minimal. |
| Db2 on AS400 / IBM i (`db2-as400`) | Replicate | Replication-based path into RDS for Db2. |

## Hard constraints

Managed-service constraints that shape what RDS for Db2 can and cannot do:

- No host SSH access.
- No unfenced C/COBOL stored procedures.
- Code page and collation are immutable after database creation.

## High availability and disaster recovery

- Multi-AZ deployments for in-region resilience.
- Cross-region mounted standby replica for disaster recovery.

## Security

- Customer-managed KMS keys (BYOK) for encryption at rest.
- Self-managed Active Directory with Kerberos authentication.
- Db2 audit delivery to Amazon S3.
- Minimum (least-privilege) IAM policy for the service.

## Anti-patterns

Approaches to avoid when selecting or designing for RDS for Db2:

- Using AWS SCT for a Db2 for z/OS source (not supported for that source).
- Offloading reads from the cross-region mounted standby replica.
