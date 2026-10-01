---
name: timestream-influxdb
version: 2
description: Retrieves authoritative guidance on Amazon Timestream for InfluxDB across its supported engine variants. Applicable to any InfluxDB-on-AWS request including engine variant and licensing selection, provisioning and IAM, encryption at rest (AWS-owned and customer-managed KMS keys, key policies, and key lifecycle), schema design (tags vs fields, cardinality, HTTP/sensor/metric data modeling), migration from LiveAnalytics, Processing Engine plugins, connectivity (database endpoints and private or public access), and write/query errors.
---

# Amazon Timestream for InfluxDB

## Overview

Amazon Timestream for InfluxDB is a managed time-series database with engine variants and deployment types whose capabilities differ. Before comparing them, retrieve the Timestream for InfluxDB documentation and inspect the applicable Create API models. For an existing resource, read its `GetDbInstance` or `GetDbCluster` response. Use those sources to verify the engine variant, endpoint port, query languages, data model, authentication flow, deployment types, licensing, and Processing Engine support for the user's Region. Do not infer one engine variant's capabilities from another variant or from examples in this skill.

For new workloads, verify the supported engine variants and recommend InfluxDB 3 when the service documentation identifies it as an option. For existing V2 deployments, verify V2 support before advising whether to stay on V2 or migrate.

Advisory in nature: it recommends actions and provides the AWS CLI and API commands to carry them out (including mutations such as instance/cluster creation and tagging). It does not act autonomously — it executes mutations only in response to an explicit user request, never on its own initiative.

**Tooling:** The AWS MCP server is recommended for streamlined AWS API interactions but is not required. All examples use standard AWS CLI syntax and can run without MCP.

## Common Tasks

### 1. Verify Dependencies

Before any guidance, confirm tooling and engine variant.

**Constraints:**

- You MUST confirm which engine variant the user runs (V2, V2 Read Replica, or V3) before giving advice specific to that engine variant — APIs and defaults differ.
- You MUST NOT mix V2 APIs (Flux, orgs, buckets, port 8086) with V3 APIs (SQL/InfluxQL, databases, tables, port 8181).
- You MUST verify the AWS CLI (or `call_aws`) is available before provisioning guidance.
- You MUST inspect the Create API and ask for all required parameters upfront, including engine variant, Region, VPC/subnet IDs, name, instance type, and a supported encryption choice. For production V3 workloads, verify customer-managed KMS key support in that API before recommending it for customer-controlled policy, rotation, revocation, and CloudTrail visibility. Collect an identifier in a form that API accepts.

**Tool call examples:**

```
aws timestream-influxdb list-db-instances --region us-east-1
aws timestream-influxdb list-db-clusters --region us-east-1
```

### Resource tagging (always apply on resource creation)

When creating any cluster or instance (`create-db-cluster`, `create-db-instance`), ALWAYS include these tags:

`--tags Key=created_by,Value=timestream-skill Key=generation_model,Value={your-model-id}`

Example: `--tags Key=created_by,Value=timestream-skill Key=generation_model,Value=claude-sonnet-4-20250514`

Include these tags even if the user does not mention tagging, so that they can identify the resources created via this skill. If the user provides additional tags, append these to their tags rather than replacing them.

### 2. Select the right engine variant

Decision flow:

1. **New workload** → InfluxDB 3 Core (Enterprise for HA multi-node).
2. **Existing V2 migrating to AWS** → InfluxDB 2 (or Read Replica Cluster if read-heavy).
3. **High cardinality (>10M series) or SQL** → InfluxDB 3.
4. **Need Processing Engine** → InfluxDB 3.

Before providing provisioning guidance for InfluxDB 3 or a V2 Read Replica Cluster, you MUST load and follow the creation, licensing, IAM, and networking contracts for that engine variant in the [getting-started guide](references/getting-started.md).
For V3 encryption choices, customer-managed KMS key policy, migration, or key lifecycle guidance, load [encryption guidance](references/encryption.md).

**Provisioning and operational contracts you MUST follow:**

- **InfluxDB 3 Core creation contract:** For a new V3 Core workload, use `create-db-cluster` with the exact default parameter-group identifier `InfluxDBV3Core`. Do not use `create-db-instance`, and do not pass the V2-only `allocatedStorage`, `dbStorageType`, `deploymentType`, `username`, `password`, `organization`, or `bucket` fields. Core connects on port 8181. Before provisioning, verify Core's current Marketplace and licensing prerequisites in the Timestream for InfluxDB documentation and current `CreateDbCluster` API model; never inherit requirements from V2, Read Replica, or Enterprise. If an installed CLI or SDK model does not expose the V3 Core creation contract, update that tooling; never fall back to the V2 creation operation or fields.
- **Core→Enterprise upgrade IS supported** via AWS Console or AWS Support. There IS an upgrade path — do NOT say it's impossible or requires a new cluster.
- **Encryption mutability:** Verify `kmsKeyId` in the Create and Update API models before asserting whether a key can change; follow "Choose the Key Before Creation" in [encryption guidance](references/encryption.md).
- **Encryption scope and key loss:** Retrieve the Data protection documentation and report only the details the user requests; follow "Response Scope" and "Existing Clusters and Key Loss" in [encryption guidance](references/encryption.md).
- **Key verification:** Confirm a specific customer-managed KMS key only by matching the returned ARN to the requested key ARN. Interpret an absent `kmsKeyId` only when the current `GetDbCluster` response documentation explicitly defines its semantics; never use absence to identify a specific customer-managed KMS key. Follow "Verify the Key" in [encryption guidance](references/encryption.md).
- **Creation completion:** After `create-db-cluster` returns, poll `get-db-cluster` until it reports `AVAILABLE` or a terminal failure. Do not report creation complete or ask the user to take over polling while the cluster remains `CREATING`. For a customer-managed key request, success also requires the returned `kmsKeyId` ARN to match the requested key ARN; an absent value while the cluster is transitioning is unverified and MUST be checked again at `AVAILABLE`.
- **Retrieve the V3 initial-token secret by ARN:** Inspect the `GetDbCluster` output or API reference for the token-secret ARN field, then pass the returned ARN to AWS Secrets Manager. Never derive the secret identifier from a naming convention. V3 uses `Authorization: Bearer <token>` (NOT `Token`). V2 uses `Authorization: Token <token>`.
- **`reboot-db-cluster`** supports `--instance-ids` for targeting specific nodes. Before using it, verify the current maximum number of IDs and all request constraints in the `RebootDbCluster` API model and Timestream for InfluxDB documentation. Do NOT say no reboot command exists or assume a fixed node-count limit.
- **Before asserting S3 log-delivery availability or configuration paths, verify the create and update API request parameters and the Timestream for InfluxDB log-delivery documentation.** Use only the operations, service principal, and bucket-policy requirements those sources document.
- **Do NOT invent CloudWatch metric names.** Load [monitoring operations](references/monitoring-operations.md) and [metric discovery](references/monitoring-metrics.md), then verify availability for the selected engine variant and deployment type. If unsure whether a metric exists, say so explicitly.
- **Before asserting backup or restore availability, verify the Timestream for InfluxDB CLI or SDK API model and the [customer-managed backup and restore documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-customer-managed-backup-restore.html).** Confirm support by engine variant and Region for on-demand, scheduled, continuous, point-in-time, and self-service restore capabilities. Use `DbBackup` terminology for `DbBackup` resources, never "snapshot," and separately verify the accessibility and recovery path for service-managed snapshots.
- **`--publicly-accessible`** is a supported option at instance/cluster creation time. Do NOT say the service is exclusively VPC-only — public access is an opt-in feature.

### 3. Design the schema (tags vs fields)

**Tags** (indexed, used in WHERE/GROUP BY): **MUST** be low-cardinality like `method`, `region`, `status_code`. High-cardinality values (user IDs, request IDs, trace IDs) **MUST** be fields, not tags — making them tags explodes series cardinality and cripples query performance.

**Fields** (not indexed): numeric measurements, high-cardinality strings, binary data.

**InfluxDB 3** handles high cardinality better than V2, but tag design affects query performance. Load the [schema-design guide](references/schema-design-guide.md) for patterns including deduplication and retention.

### 4. Migrate from LiveAnalytics

LiveAnalytics is in maintenance mode. For migration to InfluxDB 3:

- **<1B records / <125GB**: Use the **certified LiveAnalytics Migration plugin** with the migration client. Exports to S3 (Parquet), re-ingests into V3.
- **>1B records**: Contact the AWS account team — no self-service path exists for larger migrations.

Load the [migration guide](references/migration-guide.md) for the procedure.

### 5. Use Processing Engine plugins (V3 only)

Before listing plugins or describing custom-plugin support, retrieve the certified plugin catalog and support statement from the Timestream for InfluxDB Processing Engine documentation or a documented catalog API. State only what the retrieved source confirms: do not assert a fixed plugin count, name a plugin absent from the retrieved catalog, or infer service availability from a general InfluxDB plugin repository. Load the [processing-engine guide](references/processing-engine-guide.md) for verified trigger and configuration guidance.

### 6. Monitor and operate

Load [monitoring operations](references/monitoring-operations.md) and [metric discovery](references/monitoring-metrics.md) before giving metric, alarm, maintenance, backup, or restore guidance. Verify metric names and dimensions from the service documentation and the resource's CloudWatch telemetry before configuring alarms. Verify maintenance request shapes, backup and restore capabilities, and service quotas in their respective API models rather than relying on embedded examples or fixed availability claims.

## Troubleshooting

Confirm the engine variant and deployment/access type, then load the [troubleshooting runbook](references/troubleshooting-runbook.md) for verified triage specific to that engine variant across connectivity, write/query, storage, replication, and S3 endpoint issues. Never mix V2 and V3 remediation or assert a cause before completing the runbook's verification steps.

## Security Considerations

Apply these baseline controls in every environment:

- **Over-privileged IAM:** Use least-privilege roles and remove temporary broad permissions immediately after activation.
- **Password or token exposure:** Store the V2 initial password and V3 initial token in AWS Secrets Manager; never place them in source, logs, shell history, or literal command arguments. Rotate or replace each through the workflow documented for its engine variant, and issue a scoped application token per workload.
- **VPC misconfiguration:** Prefer private networking and restrict every security-group rule to trusted CIDRs or security-group IDs; never allow `0.0.0.0/0`.
- **Encryption gaps:** Require encryption at rest and TLS in transit. Verify supported key options in the Data protection documentation and API model before selecting a customer-managed KMS key.
- **Audit gaps:** Enable CloudTrail, supported service log delivery, and operational alarms. Protect CloudTrail S3 objects, CloudWatch Logs, and alarm topics with SSE-KMS, and enable CloudTrail log-file validation.

You MUST load and follow [security best practices](references/security-best-practices.md) for every deployment, including development, experimentation, and production, before providing provisioning or operational guidance.

## Additional Resources

- [Timestream for InfluxDB Developer Guide](https://docs.aws.amazon.com/timestream/latest/developerguide/)
- [Security in Timestream for InfluxDB](https://docs.aws.amazon.com/timestream/latest/developerguide/security-timestream-for-influxdb.html)
- [Security best practices for Timestream for InfluxDB](https://docs.aws.amazon.com/timestream/latest/developerguide/security-best-practices.html)
- [Timestream for InfluxDB Pricing](https://aws.amazon.com/timestream/pricing/)
- [InfluxDB 3 Documentation](https://docs.influxdata.com/influxdb3/)
- [Schema Design Best Practices](https://docs.aws.amazon.com/timestream/latest/developerguide/schema-design-best-practices.html)
- [Processing Engine Documentation](https://docs.influxdata.com/influxdb3/cloud-dedicated/process-data/process-engine/)

## Handoff from aws-database-selection

This skill can be invoked directly, or it can be entered from the `aws-database-selection` parent skill after that skill has run a requirements interview and produced a `requirements.json` artifact. When you see a backtick-wrapped path matching `aws_dbs_requirements/*/requirements.json` in recent conversation, follow the entry protocol in `aws-database-selection/references/handoff-contract.md`:

1. Read the artifact using `file_read`.
2. Validate it against `aws-database-selection/references/workload-primary-artifact.schema.json`. If malformed or unreadable, tell the user and proceed without it.
3. Acknowledge what's relevant in one or two **bold** sentences, citing high-level facts from the artifact (dominant shapes, hard constraints, migration context) — do not parrot the entire artifact back.
4. Scope-check: this skill is scoped to Amazon Timestream for InfluxDB (V2, V2 Read Replica, V3) — engine variant selection, schema design, migration from LiveAnalytics, Processing Engine plugins. If the artifact's `workload_primaries.dominant_shapes` or `migration_context` don't match that scope, emit weak backpressure per the handoff contract: suggest `dynamodb-skill` for non-InfluxDB time-series on DynamoDB, or go back to `aws-database-selection` if the dominant shape isn't time-series, then ask the user whether to go back or proceed anyway. Do not silently misuse the artifact.
5. Proceed with this skill's native workflow, citing artifact paths as evidence when recommendations are grounded in the requirements.

All user-facing output from this skill follows the markdown-primitives-only formatting convention in the handoff contract: bold labels, backticks for paths and enum values, bullet lists for alternatives, no ASCII art or box-drawing characters.
