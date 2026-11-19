# Upgrade MSK Standard Brokers to Express In Place

Use this workflow to upgrade an existing Amazon MSK Provisioned cluster from Standard brokers to Express brokers in place. The cluster ARN and endpoint are preserved, so applications continue to use the same bootstrap string while MSK adds Express brokers, reassigns topics, and decommissions Standard brokers when the operator completes the upgrade.

In-place upgrade is available in AWS Regions where MSK Express brokers are supported.

Broker provisioning and broker decommissioning are long-running asynchronous operations. Adding Express brokers can take hours and shows little progress while it runs; decommissioning brokers is usually faster. Topic reassignment time depends on the number of partitions moved and data volume. Monitor each operation's returned ARN, and do not infer a stall from periods without visible progress.

> **Operator safety:** Treat an unidentified account or cluster as production. Verify the caller, account, Region, cluster ARN, current state, and intended action before every write. Obtain explicit approval before each remediation write (a new MSK configuration revision or `UpdateClusterConfiguration`, a replication-factor reassignment, or a topic configuration change), initiating the upgrade, starting or stopping topic reassignment, rolling back, completing the upgrade, deleting an assessment, or deleting test resources. Decommissioning Standard brokers is irreversible.

## Contents

- [How the upgrade works](#how-the-upgrade-works)
- [Prerequisites](#prerequisites)
- [Run a readiness assessment](#run-a-readiness-assessment)
- [Remediate findings safely](#remediate-findings-safely)
- [Initiate the upgrade](#initiate-the-upgrade)
- [Monitor upgrade progress](#monitor-upgrade-progress)
- [Manage topic reassignment](#manage-topic-reassignment)
- [Complete or roll back the upgrade](#complete-or-roll-back-the-upgrade)
- [Post-upgrade recommendations](#post-upgrade-recommendations)
- [Security considerations](#security-considerations)
- [Considerations and limitations](#considerations-and-limitations)
- [API summary](#api-summary)
- [References](#references)

## How the upgrade works

MSK uses Apache Kafka replication to reassign topic partitions between broker types within the same cluster.

1. **Assess readiness, recommended.** Run an assessment at any time to check cluster and topic configurations against Express requirements. Initiating the upgrade automatically revalidates the configuration, so a previously completed assessment is recommended but not required by the service.
2. **Initiate the upgrade.** MSK adds Express brokers matching the count and size of the Standard brokers. The cluster temporarily runs in mixed mode.
3. **Reassign topics.** MSK reassigns partitions from Standard to Express brokers. Replication throughput caps limit the bandwidth reassignment uses.
4. **Complete or roll back.** After validating applications and reassigning every topic to Express, decommission the Standard brokers. Before that point, individual topics or the full upgrade can be rolled back to Standard.

The two migration modes are:

| Mode | CLI value | Behavior |
|---|---|---|
| Automatic | `--topic-reassignment AUTO` | MSK adds Express brokers and moves all topics. Complete after validation. |
| Controlled | `--topic-reassignment MANUAL` | MSK adds Express brokers without moving topics. Use `StartTopicReassignment` for individual topics or batches, validate each batch, then complete. |

## Prerequisites

Before initiating the upgrade, verify:

- the cluster is MSK Provisioned and uses Standard brokers on a supported instance type: M5, M7g, or M8g. `kafka.t3.small` is not supported, because no Express size matches it; resize the brokers first ([Update the Amazon MSK cluster broker size](https://docs.aws.amazon.com/msk/latest/developerguide/msk-update-broker-type.html))
- the cluster uses Kafka 3.9.x and KRaft metadata management
- deployment across 3 AZs. A 2-AZ cluster cannot be upgraded in place; the path is to replicate it with MSK Replicator to a new Express cluster in 3 AZs, which is a migration (use the `migrate-to-msk` skill)
- tiered storage is disabled
- every topic has replication factor `3`
- `min.insync.replicas` is not stored as a customer topic override; Express manages the required value
- per-broker partition replicas fit the Express target size; see [Check the partition budget](#check-the-partition-budget)

Describe the cluster and capture a fresh version before each broker-type update:

```bash
aws sts get-caller-identity

aws kafka describe-cluster-v2 \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>'

CURRENT_VERSION=$(aws kafka describe-cluster-v2 \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --query 'ClusterInfo.CurrentVersion' \
  --output text)
```

### Check the partition budget

This check is required even when the assessment returns no blocking findings. The assessment reports partition capacity as a `WARNING` at most, and a capacity finding can name one broker when every broker is affected.

1. Read each Standard broker's CloudWatch `PartitionCount` (namespace `AWS/Kafka`, dimensions `Cluster Name` and `Broker ID`), and use the highest. It counts every partition replica on the broker, so it already reflects replication factor.

   ```bash
   aws cloudwatch get-metric-statistics \
     --region '<REGION>' \
     --namespace AWS/Kafka \
     --metric-name PartitionCount \
     --dimensions 'Name=Cluster Name,Value=<CLUSTER_NAME>' 'Name=Broker ID,Value=<BROKER_ID>' \
     --start-time '<ONE_HOUR_AGO>' --end-time '<NOW>' \
     --period 300 --statistics Maximum
   ```

   If replication factor will be raised during remediation, add the extra replicas per broker.
2. Leave headroom for MSK-managed internal topics (`__amazon_msk_*`). Each Express broker hosts its own replicas of these, and they count against the same limit. They can add tens of replicas per broker.
3. Compare the total with the recommended and maximum partitions per broker for the target Express size in the [Express partition quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html#msk-express-broker-partition-quota).

- Above the maximum: do not initiate. Reassignment fills the Express brokers to the limit and then fails, leaving topics stranded on Standard so the upgrade cannot complete. Reduce partitions, delete unused topics, or choose a larger Express size by first resizing the Standard brokers.

Do not infer eligibility from cached version or instance-type lists. Read the current MSK upgrade documentation at execution time, run the managed assessment, and remediate the findings it returns before initiating the broker-type update. Follow [Remediate findings safely](#remediate-findings-safely) for the order and approvals.

## Run a readiness assessment

A readiness assessment checks cluster and topic configurations against Express requirements. Running it before the upgrade is recommended but not required. MSK automatically revalidates configurations when the upgrade is initiated and proceeds only after all checks pass.

Create the assessment:

```bash
ASSESSMENT_ARN=$(aws kafka create-assessment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --assessment-type UPDATE_BROKER_TYPE \
  --assessment-parameters '{"TargetInstanceType":"<EXPRESS>"}' \
  --query 'AssessmentArn' \
  --output text)
```

Check its status and summary:

```bash
aws kafka describe-assessment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --assessment-arn "$ASSESSMENT_ARN"
```

List detailed findings after completion:

```bash
aws kafka list-assessment-findings \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --assessment-arn "$ASSESSMENT_ARN"
```

Read the results from these fields:

- `DescribeAssessment` returns `Summary.HasBlockingFindings`, `Summary.TotalFindings`, counts in `Summary.BySeverity` (`ERROR`, `WARNING`, `INFO`) `Summary.ByCategory` (for example `TOPIC_CONFIGURATION`, `BROKER_CONFIGURATION`), and `Summary.FindingsCapped`. Read `FindingsCapped` from `Summary`; a top-level field of the same name can be null or absent.
- Each finding has `Severity`, `Category`, `Resource`, `Message`, `FindingId`, and `Remediation.Action`.
- A finding with `Severity: ERROR` blocks the upgrade. `WARNING` and `INFO` findings do not block.
- The cluster is ready only when a new assessment returns `Summary.HasBlockingFindings: false`.
- Compare `Summary.TotalFindings` with the number of findings you paged through with `list-assessment-findings`; a lower count means the read was incomplete.
- If `Summary.FindingsCapped` is `true`, the returned list is incomplete. Fix the visible `ERROR` findings, then run a new assessment.
- A clean assessment does not cover the partition budget; run [Check the partition budget](#check-the-partition-budget) as well.

Classify each finding by its returned `Severity`, and take the fix from its `Remediation.Action`. The table below explains common findings; when they differ from the assessment, follow the assessment. The table adds steps the assessment does not state, such as replacing `log.retention.hours` with `log.retention.ms`; those additions do not conflict with the assessment and are still required. Plan and apply every fix through [Remediate findings safely](#remediate-findings-safely).

Common blocking findings:

| Finding | Blocking condition | Required action |
|---|---|---|
| Replication factor | Any topic has RF other than `3` | Raise to RF `3` with `kafka-reassign-partitions.sh` and a reassignment JSON that lists three brokers for every partition. `kafka-configs.sh` and the MSK `UpdateTopic` API cannot change replication factor. A replication throttle left behind after the reassignment also blocks the upgrade; clear it with `--verify` |
| `min.insync.replicas` | A topic stores a customer override, including an override of `2` | First confirm the brokers' effective `min.insync.replicas` is `2`, because the topic falls back to the broker value. Then delete the topic override. While the override is stored, MSK rejects every configuration change to that topic once the upgrade starts |
| `unclean.leader.election.enable` | The effective broker setting is `true`, from the cluster's custom MSK configuration or from the MSK default configuration when the custom one does not set it | Set it to `false` in an MSK configuration; create a custom configuration if the cluster uses the default one. Do not apply it with `kafka-configs.sh` or `AlterConfigs`, because a dynamic value also blocks the upgrade. Leave it out of configuration revisions after the upgrade completes; Express manages it |
| Unsupported broker configuration | The cluster's MSK configuration sets a key that Express does not support, for example `log.retention.hours` | For `log.retention.hours` (or `log.retention.minutes`), replace with `log.retention.ms` to the same duration in that revision. For other configs, assess on a case by case basis.|
| `segment.ms` | Any customer topic stores a `segment.ms` override | Delete the override |
| `segment.bytes` | Any customer topic stores a `segment.bytes` override | Delete the override |
| `max.compaction.lag.ms` | Any topic has a value below one day | Raise to at least `86400000` (1 day), as the assessment reports |
| Partition size | A partition exceeds Express local disk capacity | Reduce partition size by lowering retention or splitting the topic |
| Availability Zones | The cluster does not meet the placement requirement returned by the current assessment | Satisfy that Availability Zone requirement, then reassess |

Internal `__*` topics such as `__consumer_offsets` can store overrides like `segment.bytes`; the assessment does not flag them, so leave them unchanged.

> **Behavior change:** when a topic moves to Express, MSK sets `message.timestamp.after.max.ms`, `message.timestamp.before.max.ms`, and `message.timestamp.difference.max.ms` on it to `86400000` (1 day). Producers that send `CreateTime` record timestamps more than a day before or after broker time are then rejected. Before moving topics, ask whether any producer backfills, replays, or forwards records with old or future timestamps, and warn the user. You can proactively set `message.timestamp.after.max.ms`, `message.timestamp.before.max.ms` to higher values to support the user's use case.

Express behavior changes that the assessment may report as `WARNING` or `INFO`:

- Express manages `log.segment.bytes` internally, so a custom value is ignored.
- Express manages a service-defined set of broker configurations internally; use the current assessment findings and MSK documentation to identify them.
- Express adds broker-level limits in addition to customer per-user and per-client quotas.

Topic fixes use Kafka tooling. Get the bootstrap string with `aws kafka get-bootstrap-brokers`, using the field for the cluster's authentication: `BootstrapBrokerStringSaslIam` for IAM, `BootstrapBrokerStringSaslScram` for SASL/SCRAM, or `BootstrapBrokerStringTls` for mTLS. Use it with the existing authenticated client configuration; never downgrade encryption or authentication for remediation. The commands below pass that configuration through `--command-config`. For IAM-authenticated clusters, follow [Configure clients for IAM access control](https://docs.aws.amazon.com/msk/latest/developerguide/configure-clients-for-iam-access-control.html). These commands require network access to brokers, so the user may wish to run them in their organization's approved mechanism (a bastion host, IaC, or other mechanisms). Ask the user how to run these commands in their environment.

Raise replication factor, then run `--verify` with the same JSON after the reassignment completes. `--verify` reports completion and removes the throttle that `--throttle` set:

```bash
kafka-reassign-partitions.sh --bootstrap-server '<TLS_BOOTSTRAP>' \
  --command-config '<CLIENT_PROPERTIES>' \
  --reassignment-json-file '<REASSIGNMENT_JSON>' \
  --throttle '<BYTES_PER_SECOND>' \
  --execute

kafka-reassign-partitions.sh --bootstrap-server '<TLS_BOOTSTRAP>' \
  --command-config '<CLIENT_PROPERTIES>' \
  --reassignment-json-file '<REASSIGNMENT_JSON>' \
  --verify
```

Delete unsupported topic overrides and raise compaction lag:

```bash
kafka-configs.sh --bootstrap-server '<TLS_BOOTSTRAP>' \
  --command-config '<CLIENT_PROPERTIES>' \
  --entity-type topics \
  --entity-name '<TOPIC_NAME>' \
  --alter \
  --delete-config 'segment.ms,segment.bytes'

kafka-configs.sh --bootstrap-server '<TLS_BOOTSTRAP>' \
  --command-config '<CLIENT_PROPERTIES>' \
  --entity-type topics \
  --entity-name '<TOPIC_NAME>' \
  --alter \
  --add-config 'max.compaction.lag.ms=86400000'
```

Include in `--delete-config` only the keys the assessment reported for that topic.

Delete a `min.insync.replicas` override as a separate step, only after confirming the brokers' effective value is `2`. Do not add or rewrite it, because Express manages the setting:

```bash
kafka-configs.sh --bootstrap-server '<TLS_BOOTSTRAP>' \
  --command-config '<CLIENT_PROPERTIES>' \
  --entity-type topics \
  --entity-name '<TOPIC_NAME>' \
  --alter \
  --delete-config 'min.insync.replicas'
```

`ListAssessments` lists assessments for a cluster under the `Assessments` key. `DeleteAssessment` removes an assessment and its findings to free quota. Deleting an assessment is a write action and requires approval.

## Remediate findings safely

Remediation fixes are writes against a live cluster. Obtain explicit approval before each of these: creating a new MSK configuration revision or applying it with `UpdateClusterConfiguration`, a replication-factor reassignment, and any topic configuration change. Before asking, present the planned change, its impact from the table below, and its place in the required order. Report the impact before approval, not after the change.

### Read-only checks

Gather these without writing to the cluster. See [monitor-and-alarm.md](monitor-and-alarm.md) for metric names and thresholds.

- Each topic's own `retention.ms` and `retention.bytes`, and which topics rely on the broker default.
- Broker disk usage and headroom.
- The brokers' effective `min.insync.replicas`, and any topic-level `min.insync.replicas` override on topics with replication factor below `3`.
- Producer `acks`, retry, and `delivery.timeout.ms` settings, when the operator can provide them.
- Current broker CPU and request-handler idle, before removing thread-pool overrides.
- The current MSK configuration, to plan the new revision.
- Partition replicas per broker after raising replication factor, against the Standard limit for update operations (see order step 3).

```bash
kafka-configs.sh --bootstrap-server '<TLS_BOOTSTRAP>' \
  --command-config '<CLIENT_PROPERTIES>' \
  --entity-type topics \
  --describe

kafka-configs.sh --bootstrap-server '<TLS_BOOTSTRAP>' \
  --command-config '<CLIENT_PROPERTIES>' \
  --entity-type brokers \
  --entity-name '<BROKER_ID>' \
  --describe --all
```

Read the current MSK configuration. `ServerProperties` is base64-encoded:

```bash
aws kafka describe-cluster-v2 \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --query 'ClusterInfo.Provisioned.CurrentBrokerSoftwareInfo.[ConfigurationArn,ConfigurationRevision]'

aws kafka describe-configuration-revision \
  --region '<REGION>' \
  --arn '<CONFIGURATION_ARN>' \
  --revision '<REVISION>' \
  --query 'ServerProperties' \
  --output text | base64 --decode
```

### Required order

1. Run the read-only checks above.
2. Keep the broker retention default: in the new configuration revision, replace `log.retention.hours` or `log.retention.minutes` with `log.retention.ms` set to the same duration. This keeps retention unchanged both for existing topics that rely on the default and for topics created later. If the user instead wants the Kafka default (168 hours), tell them it applies to every topic without its own `retention.ms`, including future ones, and first set `retention.ms` on existing topics that must keep their current retention.
3. Before raising replication factor, compute partition replicas per broker after the change. If it exceeds the Standard broker's maximum partitions that support update operations ([Standard best practices](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices.html)), MSK blocks the configuration update in step 5. Make room first by reducing partitions or deleting unused topics, or resize the brokers. Then raise replication factor to `3` for every topic with a throttle, so the copy does not saturate the brokers. Confirm the partitions are no longer under-replicated, then clear throttles with `kafka-reassign-partitions.sh --verify`.
4. Make the topic-level configuration changes: deletes and raised values. These are online and need no restart.
5. Create one new MSK configuration revision that contains every broker-level fix, and apply it with `update-cluster-configuration`. This triggers a rolling restart. Wait for the operation to reach `UPDATE_COMPLETE`; it can stay `UPDATE_IN_PROGRESS` well after the last broker has restarted. See [configure-cluster.md](configure-cluster.md#apply-workflow) for the create and apply commands, and [maintenance-operations.md](maintenance-operations.md#what-happens-during-a-rolling-restart) for rolling-restart behavior and client settings.
6. Watch application health through the restart. Then run a new assessment and require `Summary.HasBlockingFindings: false`.

Reasons for this order:

- A topic with replication factor `2` and `min.insync.replicas=2` drops below min ISR whenever one of its replica brokers restarts, so `acks=all` producers fail with `NotEnoughReplicas` during the rolling restart.
- Removing a broker retention override without replacing it with `log.retention.ms` changes retention for every topic that relies on the default, now and in future, and can fill disks.
- Configuration updates are restricted once the upgrade starts, so finish every broker-level fix before `UpdateBrokerType`.

### Impact of each fix

| Change | What the cluster falls back to or does | Risk | What to check or tell the user |
|---|---|---|---|
| Replace `log.retention.hours` with `log.retention.ms` | Nothing, when the duration is the same | None | Confirm the converted value (hours × 3,600,000) |
| Drop the broker retention override entirely | Every topic without its own retention, including topics created later, uses the Kafka default of 168 hours | Disks can fill on Standard storage before the upgrade; stored-data cost rises on Express afterwards | Tell the user; set retention on existing topics that must keep it first (order step 2) |
| Raise replication factor to `3` | Copies each topic's existing data to the new replica | Extra network, disk, and CPU while the copy runs | Check per-broker replicas against the Standard update-operation limit, use `--throttle`, check disk headroom, and clear the throttle with `--verify` |
| Apply the new MSK configuration | Rolling restart, one broker at a time; leadership moves and clients see brief retries | Unsafe while any topic has replication factor below `3` | Confirm order step 3 is complete and client retry settings tolerate a broker restart |
| Remove thread-pool overrides | Values return to the service default until Express manages them | Lower throughput if the values were raised for load | Check CPU and request-handler idle first |
| Set `unclean.leader.election.enable=false` | A partition that loses every in-sync replica goes offline instead of electing an out-of-sync leader | More durable, less available | Tell the user about this behavior change |
| Raise `max.compaction.lag.ms` to at least 1 day | Superseded values and tombstones can stay readable for up to 1 day | Conflicts with requirements that rely on faster compaction | Ask whether anything, such as data-deletion obligations, depends on the current value |
| Delete a `min.insync.replicas` topic override | The topic uses the broker value | Lower durability if the broker value is below `2` | Confirm the broker value is `2` first |

Every fix above can be reverted until data is lost. A full disk and an offline partition cannot be undone, which is why the order above exists.

## Initiate the upgrade

`--target-instance-type` takes a different value at each step. Pass `--topic-reassignment` explicitly on every `update-broker-type` call; do not rely on the default.

| Step | Command | `--target-instance-type` | `--topic-reassignment` |
|---|---|---|---|
| Initiate (enter mixed mode) | `update-broker-type` | `<STANDARD>-<EXPRESS>` | `AUTO` or `MANUAL` |
| Move topics to Express | `start-topic-reassignment` | `<EXPRESS>` | not applicable |
| Move topics back to Standard | `start-topic-reassignment` | `<STANDARD>` | not applicable |
| Complete on Express | `update-broker-type` | `<EXPRESS>` | `MANUAL` |
| Full rollback to Standard | `update-broker-type` | `<STANDARD>` | `MANUAL` |

`<STANDARD>` is the cluster's Standard instance type, for example `kafka.m7g.large`. Record it before you initiate; afterwards `describe-cluster-v2` returns the mixed value. `<EXPRESS>` is the Express type you assessed against. Express M8g types (`express.m8g.*`) are supported targets and give better price-performance than Express M7g. Standard `kafka.m5` and `kafka.m7g` clusters can upgrade directly to Express M8g, for example with the mixed value `kafka.m7g.large-express.m8g.large`. Prefer an M8g target where it is offered in the cluster's Region, and use [size-and-choose-cluster.md](size-and-choose-cluster.md) to compare the two. The mixed value joins them with a hyphen, Standard first, for example `kafka.m7g.large-express.m7g.large`. MSK documentation pages that say the broker type cannot be changed through the API predate in-place upgrade.

### Automatic mode

```bash
aws kafka update-broker-type \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --current-version "$CURRENT_VERSION" \
  --target-instance-type '<STANDARD>-<EXPRESS>' \
  --topic-reassignment AUTO
```

MSK adds Express brokers and automatically reassigns all topics, applying replication throughput caps.

### Controlled mode

```bash
aws kafka update-broker-type \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --current-version "$CURRENT_VERSION" \
  --target-instance-type '<STANDARD>-<EXPRESS>' \
  --topic-reassignment MANUAL
```

MSK adds Express brokers without reassigning topics. The command returns a `ClusterOperationArn`.

Track broker provisioning:

```bash
aws kafka describe-cluster-operation-v2 \
  --region '<REGION>' \
  --cluster-operation-arn '<CLUSTER_OPERATION_ARN>'
```

MSK validates the cluster and topic configurations before proceeding. It then provisions the same number and size of Express brokers as the Standard brokers.

Poll `ClusterOperationInfo.OperationState` only; `OperationSteps` can be null, so do not parse it. The operation starts `PENDING` while MSK validates, then moves to `UPDATE_IN_PROGRESS`; that transition is the sign validation passed. Provisioning then shows little progress: the Express brokers may not appear in `list-nodes` or publish metrics until the operation reaches `UPDATE_COMPLETE`. `UPDATE_COMPLETE` on the initiation operation is the signal that topics can be reassigned.

## Monitor upgrade progress

Use:

- the MSK console for reassigned, in-progress, and remaining topic counts
- `ListTopicReassignments` to list reassignment operations and statuses
- `DescribeTopicReassignment` for completed topics and reassigned-partition progress
- `ListNodes` to confirm both broker types during mixed mode
- `DescribeTopicPartitions` to see which brokers host and lead each partition
- `ListTopics` `OutOfSyncReplicaCount` per topic for replica health
- CloudWatch per-topic, per-broker `BytesInPerSec` to follow placement changes

```bash
aws kafka list-topic-reassignments \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>'

aws kafka describe-topic-reassignment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --topic-reassignment-operation-arn '<REASSIGNMENT_ARN>'

aws kafka list-topics \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>'

aws kafka describe-topic-partitions \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --topic-name '<TOPIC_NAME>'

aws kafka list-nodes \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>'
```

Topic reassignment statuses are `PENDING`, `IN_PROGRESS`, `COMPLETE`, `FAILED`, `STOPPING`, and `STOPPED`. A reassignment starts `PENDING`, and its topic and partition totals read `0` until it is resolved. Treat reassignment API progress as an indicator rather than the sole completion gate: the migrated-partition count may not advance until a topic finishes, so follow progress with `DescribeTopicPartitions` and per-broker traffic. Require the expected terminal operation state, verify placement with `DescribeTopicPartitions` and `ListNodes`, and confirm application health before proceeding.

### Tell Standard and Express brokers apart

In `list-nodes` output, use `BrokerNodeInfo.BrokerNodeType` (`STANDARD` or `EXPRESS`) to classify each broker. Do not use `InstanceType`: in mixed mode both broker types can report the same value, such as `m7g.large`. The output also includes controller nodes; skip entries without `BrokerNodeInfo`. Map `BrokerNodeInfo.BrokerId` to broker type, then compare it with each partition's replicas and leader from `describe-topic-partitions` to find where a topic lives. `BrokerId` is returned as a float (for example `4.0`) while partition replica IDs are integers, so convert before comparing.

```bash
aws kafka list-nodes \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --query 'NodeInfoList[?BrokerNodeInfo].BrokerNodeInfo.[BrokerId,BrokerNodeType]' \
  --output text
```

### Partition health in mixed mode

Express brokers publish a different set of CloudWatch metrics from Standard brokers. Partition-health metrics such as `UnderReplicatedPartitions`, `UnderMinIsrPartitionCount`, and `OfflinePartitionsCount` come only from Standard brokers, so in mixed mode they cover only the Standard side, and they stop once the Standard brokers are decommissioned. A zero or a missing datapoint does not prove health on Express.

Gate each batch on partition state read from the cluster itself, which covers both broker types, together with the application's own produce and consume signals:

- `list-topics` `OutOfSyncReplicaCount` must be `0` for every topic.
- `describe-topic-partitions` must show a leader for every partition of the moved topics, with every replica in sync.

### Follow placement changes

Express brokers start mixed mode already hosting replicas and leading partitions of MSK-managed internal topics that `list-topics` does not return. Record each broker's `PartitionCount` and `LeaderCount` before the first reassignment and measure changes against that starting point, not against zero. Standard brokers also keep leading internal-topic partitions after every listed topic has moved, so a Standard `LeaderCount` that never reaches `0` is expected; it is not a completion gate. The clearer progress signal is per-topic, per-broker `BytesInPerSec` (needs the `PER_TOPIC_PER_BROKER` monitoring level): as a topic moves, its incoming traffic shifts from Standard broker IDs to Express broker IDs.

## Manage topic reassignment

For a controlled reassignment, use `StartTopicReassignment` to reassign topics individually or in batches. Before every reassignment write, list the cluster's topics, resolve each include and exclude expression to a nonempty exact topic set, show that set to the operator, and obtain approval for that exact set. Recheck the selected topics' current placement immediately before submitting the write.

Reassign one topic:

```bash
aws kafka start-topic-reassignment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --target-instance-type '<EXPRESS>' \
  --client-token '<CLIENT_TOKEN>' \
  --topics-to-include '^orders$'
```

Reassign multiple topic patterns:

```bash
aws kafka start-topic-reassignment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --target-instance-type '<EXPRESS>' \
  --client-token '<CLIENT_TOKEN>' \
  --topics-to-include 'orders.*' 'payments.*'
```

Reassign all remaining topics:

```bash
aws kafka start-topic-reassignment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --target-instance-type '<EXPRESS>' \
  --client-token '<CLIENT_TOKEN>' \
  --topics-to-include '.*'
```

`--target-instance-type` here is the destination broker type alone, never the mixed value. Set `<CLIENT_TOKEN>` to a new value (for example from `uuidgen`) for each reassignment you intend to start, and reuse it only when retrying that same request after a lost response, so a retry cannot start a second reassignment. `--topics-to-include` accepts up to 10 regex patterns. `list-topics` returns `__consumer_offsets`, and `.*` matches it, so an all-topics reassignment moves it. Completion requires every listed topic on Express, including `__consumer_offsets`. Moving it moves the group coordinators, so consumer groups briefly rejoin; schedule it for a low-traffic window and tell the user. Exclude it from earlier batches with `--topics-to-exclude '^__consumer_offsets$'` if you want to move it last. Use `--topics-to-exclude` to exclude topics. Start with lower-risk topics, validate application behavior after each batch, and reassign higher-traffic topics gradually. Produce latency can rise while topics move, and larger batches raise it more, so use small batches for latency-sensitive workloads. Stop a reassignment for produce or consume errors, partitions without a leader, or latency outside the application's tolerance, not for a temporary latency rise alone.

### Stop an in-flight reassignment

```bash
aws kafka stop-topic-reassignment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --topic-reassignment-operation-arn '<REASSIGNMENT_ARN>'
```

Only the in-flight partitions return to the source broker type. Topics and partitions already reassigned remain on the target broker type, and topics not yet reassigned remain on the source broker type. Only one reassignment can run on a cluster at a time: poll `list-topic-reassignments` until the stopped operation shows `STOPPED` before starting another. After resolving the issue, call `StartTopicReassignment` to resume; the new reassignment has its own operation ARN, so use that ARN for any later stop.

### If a reassignment fails

A reassignment can end `FAILED` for several reasons, and its error message can be generic. A failed reassignment can leave a topic split, with some partitions on each broker type.

1. Read `ErrorInfo` from `describe-topic-reassignment` and note which topics and partitions did not move (`describe-topic-partitions`).
2. Check partition replicas on each destination broker against the Express maximum. Full brokers are a common cause; see [Check the partition budget](#check-the-partition-budget).
3. Check partition health (`OutOfSyncReplicaCount`, partition leaders) and that no Kafka-level reassignment or replication throttle is left behind (`kafka-reassign-partitions.sh --list`).
4. Once the cause is fixed, call `StartTopicReassignment` again for the same topics; partitions that already moved are not moved again. Retrying without fixing the cause, such as full brokers, fails again.
5. If the cause cannot be fixed, move every topic back to Standard and roll back, or resize. If no cause is found, contact AWS Support with the reassignment ARN.

### Roll back selected topics to Standard

```bash
aws kafka start-topic-reassignment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --target-instance-type '<STANDARD>' \
  --client-token '<CLIENT_TOKEN>' \
  --topics-to-include '^orders\.eu$'
```

The selected topic returns to Standard while other reassigned topics remain on Express.

### Move every topic back to Standard

```bash
aws kafka start-topic-reassignment \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --target-instance-type '<STANDARD>' \
  --client-token '<CLIENT_TOKEN>' \
  --topics-to-include '.*'
```

Wait for the operation to complete and verify with `describe-topic-partitions` that every topic is on Standard before decommissioning Express brokers.

## Complete or roll back the upgrade

### Complete on Express

Decommissioning Standard brokers is irreversible. After completion, returning to Standard brokers requires a new Standard cluster and a migration with MSK Replicator. After every topic reaches Express, keep the cluster in mixed mode for a representative 24–48 hour bake while monitoring application health, quotas, configuration behavior, reassignment terminal state, broker placement, and partition health. Immediately before completion, recheck these gates and obtain separate explicit approval to remove the rollback path. Retrieve a fresh `CurrentVersion`, because it changes after initiation.

```bash
CURRENT_VERSION=$(aws kafka describe-cluster-v2 \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --query 'ClusterInfo.CurrentVersion' \
  --output text)

aws kafka update-broker-type \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --current-version "$CURRENT_VERSION" \
  --target-instance-type '<EXPRESS>' \
  --topic-reassignment MANUAL
```

Poll the returned operation with `describe-cluster-operation-v2` until it reaches `UPDATE_COMPLETE`. Standard brokers drop out of `list-nodes` before the operation finishes, while `NumberOfBrokerNodes` still shows the old count, so neither is a completion signal.

If any topic remains on Standard, the command fails with `ValidationException`. Reassign all topics to Express before trying to complete the upgrade again.

### Full rollback to Standard

First move all topics back to Standard as shown above. Then retrieve a fresh `CurrentVersion` and decommission Express brokers:

```bash
CURRENT_VERSION=$(aws kafka describe-cluster-v2 \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --query 'ClusterInfo.CurrentVersion' \
  --output text)

aws kafka update-broker-type \
  --region '<REGION>' \
  --cluster-arn '<CLUSTER_ARN>' \
  --current-version "$CURRENT_VERSION" \
  --target-instance-type '<STANDARD>' \
  --topic-reassignment MANUAL
```

Poll the operation until `UPDATE_COMPLETE`, as for completion. The cluster returns to Standard-only operation. The upgrade can be restarted later.

## Post-upgrade recommendations

After completing the upgrade:

- continue monitoring application performance and topic health after Standard brokers are decommissioned
- evaluate performance against the pre-upgrade baseline and right-size the Express footprint; latency can be higher than on Standard when partitions per broker are above the Express recommended value
- turn on [Intelligent Rebalancing](https://docs.aws.amazon.com/msk/latest/developerguide/intelligent-rebalancing.html). It is off on upgraded clusters, unlike new Express clusters, and is needed to keep partitions balanced and to add or remove brokers in one operation. Turn it on before right-sizing
- optionally switch clients to the Express `boot-*` bootstrap endpoints from `get-bootstrap-brokers`, which spread metadata connections across brokers; existing broker-specific endpoints such as `b-1.*` keep working
- update alarms and dashboards built for Standard brokers: replace `KafkaDataLogsDiskUsed` with `StorageUsed`, and retire EBS metrics such as `BurstBalance`
- confirm producers are not rejected by the `message.timestamp.*` limits Express sets on each topic
- review readiness-assessment `WARNING` and `INFO` findings for configurations that Express manages internally
- omit `unclean.leader.election.enable` from future MSK configuration updates; Express manages it and may reject a configuration that includes it
- review customer per-user and per-client quotas together with Express broker-level ingress and egress limits

## Security considerations

Apply the [Amazon MSK security guidance](https://docs.aws.amazon.com/whitepapers/latest/amazon-msk-migration-guide/amazon-managed-streaming-for-apache-kafka-amazon-msk.html) throughout the upgrade:

- Grant the operator only the control-plane read and write actions required for assessment, configuration remediation, broker updates, topic reassignment, and operation inspection. Use a separate least-privilege role for the approved upgrade rather than broad administrator credentials.
- Keep brokers on private connectivity. Preserve TLS encryption and the cluster's existing authenticated client path during every validation and remediation step. Prefer [IAM access control](https://docs.aws.amazon.com/msk/latest/developerguide/iam-access-control.html) when it fits the workload; otherwise preserve the configured mTLS or SASL/SCRAM mechanism and Kafka ACLs.
- Confirm the cluster's encryption-at-rest configuration remains effective throughout the upgrade. Do not weaken or replace its KMS settings as part of the broker transition.
- Keep credentials and SCRAM secrets out of commands, files committed to source control, logs, and generated evidence. Use temporary role credentials and Secrets Manager where applicable.
- Use CloudTrail to audit MSK API actions. Enable broker logging and monitor CloudWatch application, broker, partition-health, and reassignment signals throughout mixed mode and final decommissioning. Encrypt CloudWatch Logs groups and S3 log destinations with KMS keys and least-privilege resource policies that meet the workload's security requirements.
- Before each write, reverify the caller, account, Region, exact cluster ARN, current version, operation scope, and approved topic set. Stop on any mismatch or ambiguous operation ownership.

## Considerations and limitations

- **Availability:** Applications remain available while MSK moves data, and traffic continues through the broker holding each partition.
- **Billing:** Both Standard and Express brokers are billed while the cluster is in mixed mode.
- **Operations:** Producing and consuming data, creating and deleting topics, modifying ACLs, and managing security credentials remain available during the upgrade. Some cluster-level operations, including Kafka version upgrades, configuration updates, and Standard broker-count changes, are restricted.
- **Endpoint:** The cluster endpoint is preserved. Applications continue using the same bootstrap string, and Kafka metadata handles leader redirection as topics are reassigned.
- **Consumer offsets:** MSK replicates consumer offsets as part of topic reassignment so stateful applications resume from the same processing position.
- **New topics in Automatic mode:** Topics created during an automatic reassignment are placed on Express brokers.

## API summary

| API | Use during the upgrade |
|---|---|
| `UpdateBrokerType` | Initiate with `AUTO` or `MANUAL`, complete by specifying only Express, or fully roll back by specifying only Standard. |
| `StartTopicReassignment` | Reassign topics between broker types using include or exclude regex patterns. |
| `StopTopicReassignment` | Stop an active reassignment and return its in-flight topic to the source broker type. |
| `DescribeTopicReassignment` | Poll total and completed topics and total and reassigned partitions. |
| `ListTopicReassignments` | List reassignment operations and filter by status. |
| `CreateAssessment` | Start a readiness assessment. |
| `DescribeAssessment` | Poll assessment status and retrieve its findings summary. |
| `ListAssessments` | List assessments for a cluster. |
| `ListAssessmentFindings` | Retrieve detailed findings. |
| `DeleteAssessment` | Delete an assessment and its findings to free quota. |
| `ListTopics` | Read each topic's `OutOfSyncReplicaCount`. |
| `DescribeTopicPartitions` | Read each partition's leader, replicas, and in-sync replicas to identify placement and health. |
| `ListNodes` | Identify Standard and Express brokers during mixed mode by `BrokerNodeInfo.BrokerNodeType`. |
| `GetBootstrapBrokers` | Retrieve bootstrap strings during the upgrade; applications continue using the same bootstrap string. |
| `DescribeClusterOperationV2` | Poll `OperationState` for initiation, completion, and rollback; `OperationSteps` can be null. |

## References

The Amazon MSK Developer Guide is the source of truth for the upgrade procedure:

- [Upgrade Standard brokers to Express brokers](https://docs.aws.amazon.com/msk/latest/developerguide/msk-upgrade-standard-to-express.html)
- [Upgrade readiness assessment](https://docs.aws.amazon.com/msk/latest/developerguide/msk-upgrade-assessment.html)
- [Initiate the in-place upgrade](https://docs.aws.amazon.com/msk/latest/developerguide/msk-upgrade-initiate.html)
- [Manage topic migration during upgrade](https://docs.aws.amazon.com/msk/latest/developerguide/msk-upgrade-manage-topics.html)
- [Monitor and validate the upgrade](https://docs.aws.amazon.com/msk/latest/developerguide/msk-upgrade-monitor-validate.html)
- [Complete or roll back the upgrade](https://docs.aws.amazon.com/msk/latest/developerguide/msk-upgrade-complete.html)
- [In-place upgrade API reference summary](https://docs.aws.amazon.com/msk/latest/developerguide/msk-upgrade-api-reference.html)
