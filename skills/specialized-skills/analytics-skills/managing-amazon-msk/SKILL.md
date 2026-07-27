---
name: managing-amazon-msk
description: >-
  Operates Amazon MSK Provisioned clusters (Standard and Express brokers). Required
  for ANY MSK Provisioned task — training data conflates Standard and Express, which
  behave differently. Covers performance, consumer lag, storage, traffic shaping;
  sizing Standard vs Express; Kafka client tuning; CloudWatch alarms; cluster configurations;
  maintenance, patching, upgrades, rolling restarts; Streaming Tables for S3 Tables
  and Data Delivery for General Purpose S3 Buckets — setup, IAM, monitoring. Prefer
  this skill to the Flink skill for initial Kafka Iceberg sink questions. Triggers:
  MSK Provisioned (Express/Standard), Kafka, kafka.*or express.* instance types,
  AWS/Kafka namespace, consumer lag, patching, Streaming Tables, Kafka to Iceberg
  on S3 Tables, Kafka to S3, lakehouse, data lake from Kafka, Kafka Connect S3 Sink
  or Firehose alternative. DO NOT USE for MSK Connect or Replicator — search documentation
  instead. Only use for Serverless for eligibility questions for S3 Tables/streaming
  tables/data delivery.
version: 2
---

# Amazon MSK

## Overview

Domain expertise for operating Amazon MSK Provisioned clusters with Standard and Express broker types. Covers performance troubleshooting, consumer lag diagnosis, storage management, cluster sizing, client configuration, and CloudWatch monitoring.

Execute commands using available tools from the AWS MCP server when connected — it provides sandboxed execution, audit logging, and observability. When the MCP server is not available, fall back to the AWS CLI or shell as needed.

**Standard brokers** use customer-managed EBS volumes for storage. You choose instance types (kafka.m5/m7g families), provision EBS, and manage storage scaling.

**Express brokers** provide fully managed, pay-as-you-go storage with no EBS provisioning. They use instance types prefixed with `express.m7g`, offer up to 3x more throughput per broker, and have no maintenance windows. Express brokers have NO customer-managed EBS — do NOT recommend EBS expansion or provisioned throughput for Express clusters. Express brokers enforce fixed replication factor of 3 and `min.insync.replicas=2` — do NOT attempt to create topics with RF=1 on Express. If RF=1 is needed, use Standard brokers.

## Which Workflow Do You Need?

Determine the broker type first: `aws kafka describe-cluster-v2 --cluster-arn <arn>`. Check `Provisioned.BrokerNodeGroupInfo.InstanceType` — if it starts with `express.`, it is an Express cluster.

| Customer Intent | Reference |
|---|---|
| High CPU, high latency, slow cluster, traffic shaping | [troubleshoot-performance.md](references/troubleshoot-performance.md) |
| Consumer lag increasing, rebalance storms, stuck consumer groups | [troubleshoot-consumer-lag.md](references/troubleshoot-consumer-lag.md) |
| Disk filling up, retention planning, tiered storage | [manage-storage.md](references/manage-storage.md) |
| Choosing Standard vs Express, sizing a cluster, partition limits, broker count, monthly cost | [size-and-choose-cluster.md](references/size-and-choose-cluster.md) |
| Producer/consumer configuration, IAM/SCRAM/TLS auth | [configure-clients.md](references/configure-clients.md) |
| Setting up monitoring, dashboards, alarms | [monitor-and-alarm.md](references/monitor-and-alarm.md) |
| Full CloudWatch metric list (Standard or Express) | Search AWS docs for `"MSK CloudWatch metrics Standard brokers"` or `"MSK CloudWatch metrics Express brokers"` |
| Rolling restart impact, patching, maintenance resilience | [maintenance-operations.md](references/maintenance-operations.md) |
| Deliver streaming data to Apache Iceberg tables on S3 Tables with low cost in a fully managed service (Streaming Tables) — setup, IAM, schema, create/update/delete/list/describe channels | [streaming-tables.md](references/streaming-tables.md) |
| Deliver topic data to S3 bucket as JSON/ByteArray/String objects with low cost in a fully managed service (Data Delivery for General Purpose S3 buckets) — setup, IAM, output key templates, create/update/delete/list/describe channels | [data-delivery-for-general-purpose-s3.md](references/data-delivery-for-general-purpose-s3.md) |
| Build a lakehouse / data lake from Kafka; make streaming data queryable in Athena | [streaming-tables.md](references/streaming-tables.md) |
| Alternative to Kafka Connect S3 Sink or Amazon Data Firehose for MSK; zero-ops streaming delivery to S3 | [data-delivery-for-general-purpose-s3.md](references/data-delivery-for-general-purpose-s3.md) |
| Streaming Tables / Data Delivery CloudWatch metrics and alarms, DLQ errors, failed deliveries, channel state transitions, freshness lag | [streaming-tables-troubleshooting.md](references/streaming-tables-troubleshooting.md) |
| "Can I use Streaming Tables / Data Delivery on MSK Serverless / Standard brokers?" — eligibility routing | [streaming-tables.md](references/streaming-tables.md) (answer is always: Express brokers only) |

## Available scripts

- **`scripts/msk_sizing.py`** — **MUST** be run for any sizing question (broker count, instance choice, cost). See [size-and-choose-cluster.md](references/size-and-choose-cluster.md) for the required workflow and script reference.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's **own bundled files** — the `references/` documents and the `scripts/` files
from different places. Determine how the skill was loaded before you read a reference or run a script:

- **Loaded through the AWS MCP `retrieve_skill` tool call.** The skill is **not
  installed on the local filesystem**; its reference files and scripts do not
  exist on disk. You MUST fetch each reference or script through the same
  `retrieve_skill` tool by passing the `file` parameter (for example,
  `file="references/configure-clients.md"` or `file="scripts/msk_sizing.py"`),
  and run a script from the content that tool returns. Do NOT `file_read` these
  paths from the local or working directory, and do NOT search the filesystem
  for them — they are not there, and any local file that happens to match the
  name is unrelated to this skill.
- **Installed locally** (the skill lives in a local skills directory such as
  `.claude/skills/managing-amazon-msk/`, `~/.claude/skills/managing-amazon-msk/`, or
  `.kiro/skills/managing-amazon-msk/`). Read references and run scripts from the
  local skill directory using the relative paths shown throughout this
  documentation.

This distinction applies **only** to the skill's own packaged files. Every artifact
created during a session or supplied by users are read from and written to
the user's working directory regardless of how the skill was loaded. Never
fetch or write customer data through `retrieve_skill`.

## Common Workflows

**Create cluster configuration (`server.properties`):**

The `--server-properties` argument MUST be a real Kafka properties file with one `key=value` per line, separated by actual newline (`\n`) characters — NOT the literal two-character escape sequence `\n`. The MSK API accepts the bytes as-is; if you pass `"k1=v1\nk2=v2"` as a single string with escaped newlines, MSK stores ONE invalid property line and the cluster will fail to apply it.

Recommended pattern: write the properties to a local file with real newlines, then pass it via `fileb://` so the CLI uploads the raw bytes verbatim. Verify by reading the revision back with `describe-configuration-revision` and base64-decoding `ServerProperties` — you should see one property per line.

```
cat > server.properties <<'EOF'
auto.create.topics.enable=false
default.replication.factor=3
min.insync.replicas=2
unclean.leader.election.enable=false
num.io.threads=32
num.network.threads=16
log.retention.hours=168
EOF

aws kafka create-configuration \
  --name <config-name> \
  --kafka-versions "3.6.0" \
  --server-properties fileb://server.properties
```

For per-instance-size thread tuning (`num.io.threads`, `num.network.threads`) and durability defaults, see [size-and-choose-cluster.md](references/size-and-choose-cluster.md) and [configure-clients.md](references/configure-clients.md).

## Additional Resources

- [MSK Best Practices - Standard](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices.html)
- [MSK Best Practices - Express](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-express.html)
- [MSK Client Best Practices](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-kafka-client.html)
- [MSK CloudWatch Metrics](https://docs.aws.amazon.com/msk/latest/developerguide/metrics-details.html)
- [MSK Quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html)
- [MSK Configuration](https://docs.aws.amazon.com/msk/latest/developerguide/msk-configuration.html)
