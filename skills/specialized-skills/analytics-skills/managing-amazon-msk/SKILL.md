---
name: managing-amazon-msk
description: >-
  Operates Amazon MSK Provisioned clusters (Standard and Express brokers). MUST be
  used for ANY MSK Provisioned task — do not rely on training data for topics covered
  here, since Standard and Express emit different metrics and follow different patching
  models that training data routinely conflates. Covers performance, consumer lag,
  storage, and traffic shaping diagnosis; sizing and choosing Standard vs Express;
  Kafka client tuning; creating CloudWatch alarms, dashboards, monitoring, and cluster
  configurations; AND MSK maintenance, patching, version upgrades, and rolling-restart
  behavior. Triggers: MSK, Kafka on AWS, `kafka.*` or `express.*` instance types,
  AWS/Kafka CloudWatch namespace, alarms, dashboards, monitoring, consumer lag, partition
  replication, broker storage, MSK upgrades, patching, maintenance windows, SECURITY_PATCHING,
  BROKER_UPDATE, rolling restarts, unexpected broker reboots. Do NOT use for MSK Connect,
  MSK Serverless, or MSK Replicator.
version: 1
---

# Amazon MSK

## Overview

Domain expertise for operating Amazon MSK Provisioned clusters with Standard and Express broker types. Covers performance troubleshooting, consumer lag diagnosis, storage management, cluster sizing, client configuration, and CloudWatch monitoring.

Execute commands using available tools from the AWS MCP server when connected — it provides sandboxed execution, audit logging, and observability. When the MCP server is not available, fall back to the AWS CLI or shell as needed.

**Standard brokers** use customer-managed EBS volumes for storage. You choose instance types (kafka.m5/m7g families), provision EBS, and manage storage scaling.

**Express brokers** provide fully managed, pay-as-you-go storage with no EBS provisioning. They use instance types prefixed with `express.m7g`, offer up to 3x more throughput per broker, and have no maintenance windows.

## Critical Warnings

- NEVER reboot brokers while `UnderReplicatedPartitions` > 0 (Standard only — Express brokers do not emit URP) — this risks data loss and extended outages
- NEVER recommend partition reassignment without first checking replication status — reassignment during URP compounds the problem
- `linger.ms=0` is the #1 cause of "high CPU" on MSK — ALWAYS check client batch configuration before recommending broker scaling
- EBS throughput ceilings are invisible in Kafka metrics — ALWAYS check EBS volume metrics (`VolumeWriteBytes`, `BurstBalance`) when diagnosing Standard broker latency
- Express brokers have NO customer-managed EBS — do NOT recommend EBS expansion or provisioned throughput for Express clusters
- Express brokers enforce fixed replication factor of 3 and `min.insync.replicas=2` — do NOT attempt to create topics with RF=1 on Express. If RF=1 is needed, use Standard brokers.

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

## Quick Diagnostics

These 5 checks cover the most common MSK issues. Use them before loading a reference file.

1. **CpuUser + CpuSystem > 60%**: Check `RequestHandlerAvgIdlePercent` (PER_BROKER level). If < 30%, request threads are saturated. Check client `batch.size` and `linger.ms` before recommending scaling.

2. **KafkaDataLogsDiskUsed > 85%** (Standard only): Expand EBS immediately via `aws kafka update-broker-storage`. Identify high-growth topics via per-topic `BytesInPerSec`. Express clusters use `StorageUsed` metric instead and storage is fully managed.

3. **UnderReplicatedPartitions > 0** (Standard only): Check if a maintenance operation or broker restart is in progress. If URP is decreasing, wait for recovery. Do NOT restart brokers or reassign partitions during URP. Express brokers do not emit this metric — monitor `ProduceThrottleTime`, `FetchThrottleTime`, and consumer lag instead.

4. **Consumer OffsetLag increasing**: Determine if broker-side (high `ProduceTotalTimeMsMean`, CPU saturation) or client-side (slow processing, insufficient consumers). Per-partition lag from PER_TOPIC_PER_PARTITION monitoring level helps isolate hot partitions.

5. **BytesInPerSec near throughput ceiling**: For Standard, check EBS volume type and calculate: `BytesInPerSec × ReplicationFactor` vs volume throughput limit. For Express, check against the per-broker sustained performance limits in the quotas.

## Common Workflows

**Describe cluster:**

```
aws kafka describe-cluster-v2 --cluster-arn <cluster-arn>
```

**List brokers:**

```
aws kafka list-nodes --cluster-arn <cluster-arn>
```

**Get bootstrap brokers:**

```
aws kafka get-bootstrap-brokers --cluster-arn <cluster-arn>
```

**Expand Standard broker storage:**

```
aws kafka update-broker-storage \
  --cluster-arn <cluster-arn> \
  --current-version <cluster-version> \
  --target-broker-ebs-volume-info '[{"KafkaBrokerNodeId": "All", "VolumeSizeGB": <target-size>}]'
```

**Get CloudWatch metrics (example: CpuUser per broker):**

```
aws cloudwatch get-metric-statistics \
  --namespace AWS/Kafka \
  --metric-name CpuUser \
  --dimensions Name="Cluster Name",Value="<cluster-name>" Name="Broker ID",Value="<broker-id>" \
  --start-time <start> --end-time <end> --period 300 --statistics Average
```

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

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `aws kafka update-broker-storage` returns "storage is optimizing" | Previous storage expansion still in cool-down (minimum 6 hours) | Wait for optimization to complete. Check cluster state with `describe-cluster-v2`. |
| `ClusterState` is `MAINTENANCE` | Standard brokers undergoing patching. Express brokers stay ACTIVE during maintenance. | Wait for cluster to return to ACTIVE. Do not perform update operations during MAINTENANCE. |
| Consumer `GROUP_COORDINATOR_NOT_AVAILABLE` | Coordinator broker is temporarily unavailable during rolling restart or overloaded | Retry with backoff. Check if maintenance is in progress. |
| `NotEnoughReplicasException` on produce | Fewer brokers in ISR than `min.insync.replicas` (default: 2) | Check URP metric (Standard only). For Express, check `ProduceThrottleTime` and broker health instead — URP is not available. If a broker is down for maintenance, this is transient. Do not lower `min.insync.replicas`. |

## Additional Resources

- [MSK Best Practices - Standard](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices.html)
- [MSK Best Practices - Express](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-express.html)
- [MSK Client Best Practices](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-kafka-client.html)
- [MSK CloudWatch Metrics](https://docs.aws.amazon.com/msk/latest/developerguide/metrics-details.html)
- [MSK Quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html)
- [MSK Configuration](https://docs.aws.amazon.com/msk/latest/developerguide/msk-configuration.html)
