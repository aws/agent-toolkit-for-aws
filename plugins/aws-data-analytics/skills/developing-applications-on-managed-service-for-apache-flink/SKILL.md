---
name: developing-applications-on-managed-service-for-apache-flink
description: >
  MANDATORY for Flink or Amazon Managed Service for Apache Flink (MSF) questions. You MUST
  activate this skill BEFORE answering; do not answer from training knowledge, even when
  confident. MSF has service-specific constraints (KPU model, prohibited checkpoint and
  parallelism config in app code, the v1/v2 identifier split, two-phase IaC deploys, snapshot
  lifecycle, Flink 1.x to 2.x migration) that override generic Flink knowledge. Triggers: Flink,
  MSF, Managed Flink, KinesisAnalytics(V2), KPU, ParallelismPerKPU, savepoint, snapshot,
  SnapshotMode, operator UID, FlinkKinesisConsumer, KinesisStreamsSource, KafkaSource, EFO,
  CreateApplication, UpdateApplication, CreateSnapshot, Kryo, RocksDB, EXACTLY_ONCE, watermark,
  CDC binlog/WAL, AWS/KinesisAnalytics CloudWatch. NOT for choosing a service to land Kafka or
  Kinesis data in Iceberg: managing-amazon-msk owns Kafka to Iceberg,
  managing-amazon-kinesis-data-streams owns KDS. Use this skill for the Flink IcebergSink itself.
---

# Managed Service for Apache Flink

## Overview

Domain expertise for Apache Flink applications on Amazon Managed Service for Apache Flink (MSF). Covers development, KPU resource management, connectors, state management, monitoring, IaC deployment, and version migration.

Execute commands using available tools from the AWS MCP server when connected — it provides sandboxed execution, audit logging, and observability. When the MCP server is not available, fall back to the AWS CLI or shell as needed.

## General Guidance

Before starting, ensure you have a clear understanding of the user persona, use case, and requirements:

STOP: Determine the users background and use case before proceeding:

- Are they new to Flink? New to Managed Service for Apache Flink?
- Are they familiar with Java development?
- Is the use case complex with lots of business logic? Or simple and declarative?

These will inform how to organize the project, and whether to use Flink Table API or DataStream API. In general, assume the DataStream API.

### Example Workflow for New Applications

```
1. User asks to build a Flink application
2. Confirm user's goals and use case
3. READ [best-practices.md](references/best-practices.md)
4. READ [dependency-management.md](references/dependency-management.md)
5. READ relevant connector guides (e.g. [kinesis-connector-guide.md](references/kinesis-connector-guide.md))
6. Generate code following the loaded guidance
7. Validate against best practices
8. READ environment-setup.md via [environment-setup.md](references/environment-setup.md)
9. Compile and test locally
```

### Example Workflow for General Questions

```
1. User asks about real time delivery of data to Iceberg
2. Confirm user's goals and use case
3. READ [best-practices.md](references/best-practices.md)
4. READ [iceberg-connector-guide.md](references/iceberg-connector-guide.md)
5. READ other reference files as needed
6. Answer question with loaded guidance
```

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's **own bundled files** — the `references/` documents —
from different places. Determine how the skill was loaded before you read a reference:

- **Loaded through the AWS MCP `retrieve_skill` tool call.** The skill is **not
  installed on the local filesystem**; its reference files do not exist on disk.
  You MUST fetch each reference through the same `retrieve_skill` tool by
  passing the `file` parameter (for example,
  `file="references/snapshot-management.md"`), and answer from the content that
  tool returns. Do NOT `file_read` these paths from the local or working
  directory, and do NOT search the filesystem for them — they are not there,
  and any local file that happens to match the name is unrelated to this skill.
  If a reference cannot be retrieved, say so rather than answering from training
  knowledge, which for MSF-specific behavior is frequently wrong.
- **Installed locally** (the skill lives in a local skills directory such as
  `.claude/skills/developing-applications-on-managed-service-for-apache-flink/`,
  `~/.claude/skills/developing-applications-on-managed-service-for-apache-flink/`, or
  `.kiro/skills/developing-applications-on-managed-service-for-apache-flink/`). Read
  references from the local skill directory using the relative paths shown
  throughout this documentation.

This distinction applies **only** to the skill's own packaged files. Every artifact
created during a session or supplied by users are read from and written to
the user's working directory regardless of how the skill was loaded. Never
fetch or write customer data through `retrieve_skill`.

## Reference Files

- You MUST use this skill and its reference files to answer any question on these topics.
- Do NOT answer from training knowledge or by searching general AWS documentation when the question concerns Apache Flink, Managed Service for Apache Flink, KPU sizing, Flink monitoring, deployment, migration, real-time analytics, or Iceberg/LakeHouse streaming with Flink
  - You MUST load the relevant reference files below before taking other steps.
  - The reference files contain MSF-specific details (thresholds, statistics, namespaces, constraints) that differ from generic Flink guidance and are required for correct responses.

| Goal | Reference | When to Load |
|------|-----------|-------------|
| Best practices | [best-practices.md](references/best-practices.md) | **Always** before writing code |
| Maven dependencies | [dependency-management.md](references/dependency-management.md) | New project or adding connectors |
| Local dev environment | [environment-setup.md](references/environment-setup.md) | Docker-based local development |
| MSF architecture | [msf-overview.md](references/msf-overview.md) | KPU model and service constraints |
| MSF constraints and patterns | [msf-constraints-and-patterns.md](references/msf-constraints-and-patterns.md) | MSF vs self-managed Flink, service-level vs application-level configuration separation, MSF-specific resource/network/storage limits, common MSF patterns |
| Quotas, ENI planning, MSF vs EMR, source/sink choice | [foundation-operations.md](references/foundation-operations.md) | Capacity planning, service selection, architecture design, CLI/IAM/CloudWatch identifier disambiguation |
| IAM execution role, trust policy, action prefix, service principal | [foundation-operations.md](references/foundation-operations.md) | Writing IAM policies for MSF — covers the `kinesisanalytics:` (no v2) action prefix, `kinesisanalytics.amazonaws.com` (no v2) trust principal, and the v2/non-v2 disconnect that is the most common source of permission and AssumeRole failures |
| Flink 2.x migration | [flink-2x-migration.md](references/flink-2x-migration.md) | Version upgrades, state compatibility |
| KPU sizing | [resource-optimization.md](references/resource-optimization.md) | Right-sizing, performance diagnosis, scaling |
| Scaling decisions on running apps | [scaling-decisions.md](references/scaling-decisions.md) | In-flight scaling matrix, cost/memory impact of scale changes, autoscaling behavior, anti-patterns |
| Cost estimation | [pricing-calculator.md](references/pricing-calculator.md) | Budget planning, sizing-to-cost mapping, optimization levers |
| Application lifecycle ops | [application-lifecycle.md](references/application-lifecycle.md) | Start/stop, deploy code, rollback, runtime properties, delete. For anything snapshot-specific load `snapshot-management.md` instead |
| Snapshots and savepoints: which type, backup, restore, retention cost | [snapshot-management.md](references/snapshot-management.md) | Any snapshot question — choosing between enhanced snapshots and application snapshots (legacy), switching an application into enhanced snapshot mode (a one-way change), creating and tracking snapshots, finding them, restoring an application or cloning state into a different application, moving snapshots through Amazon S3, snapshot IAM and AWS KMS permissions, and snapshot storage cost and retention |
| Restart loop diagnosis | [first-fault-isolation.md](references/first-fault-isolation.md) | Crashing/restarting apps, finding original failure vs loop sustainers, Flink Dashboard live diagnosis |
| Checkpoint tuning | [checkpoint-tuning.md](references/checkpoint-tuning.md) | Checkpoint impact on KPU memory and CPU, frequency vs network bandwidth trade-offs, checkpoint duration exceeding interval, OOM/GC during checkpoints |
| Job graph design | [job-graph-architecture.md](references/job-graph-architecture.md) | Performance issues, splitting jobs |
| Job graph anti-patterns | [job-graph-anti-patterns.md](references/job-graph-anti-patterns.md) | Data skew detection and mitigation, monolith job anti-pattern, high fan-out anti-pattern, removing multiple shuffles, when to split a large application |
| Monitoring and alarms | [monitoring-and-metrics.md](references/monitoring-and-metrics.md) | CloudWatch dashboards, alarms, metrics |
| Logging | [logging-configuration.md](references/logging-configuration.md) | Log4j2, CloudWatch Logs setup |
| Kinesis connectors | [kinesis-connector-guide.md](references/kinesis-connector-guide.md) | Kinesis source and sink builders, polling configuration and throttling (`READER_EMPTY_RECORDS_FETCH_INTERVAL`, `SHARD_GET_RECORDS_MAX`, `ReadProvisionedThroughputExceeded`, `LimitExceededException`), legacy connector migration |
| Kinesis Enhanced Fan-Out (EFO) | [kinesis-efo-guide.md](references/kinesis-efo-guide.md) | When to use EFO vs polling, EFO source configuration, consumer lifecycle (`JOB_MANAGED` vs `SELF_MANAGED`), parallelism vs shard count, IAM permissions, troubleshooting |
| Iceberg integration (write APIs, distribution modes, partitioning) | [iceberg-connector-guide.md](references/iceberg-connector-guide.md) | Iceberg write APIs (append, upsert, dynamic), distribution modes (NONE/HASH/RANGE), CoW vs MoR, read patterns, partitioning, DDL. **Does NOT contain catalog choice or maintenance approaches** — for those, load `iceberg-tuning-and-operations.md`. |
| Iceberg tuning, operations, catalog choice, maintenance | [iceberg-tuning-and-operations.md](references/iceberg-tuning-and-operations.md) | Provides  maintenance approaches for S3 Tables, Glue + Glue auto-compaction, and Glue + Flink embedded maintenance with JDBC lock for catalog-choice questions; small files problem and mitigations; Flink TableMaintenance API, post-commit maintenance, lock factories; IcebergSink monitoring, anti-patterns. |
| CDC connectors | [cdc-connector-guide.md](references/cdc-connector-guide.md) | MySQL, PostgreSQL, Oracle, SQL Server, MongoDB CDC |
| IaC and deployment | [iac-and-deployment.md](references/iac-and-deployment.md) | CloudFormation, CDK, Terraform, two-phase deployment |
| Serialization | [serialization-guide.md](references/serialization-guide.md) | POJO, Avro, Kryo guidance |
| State management | [state-management.md](references/state-management.md) | TTL, state types, migration safety |

## Additional Resources

- [GitHub Issues](https://github.com/awslabs/managed-service-for-apache-flink-agent-steering-files/issues)
