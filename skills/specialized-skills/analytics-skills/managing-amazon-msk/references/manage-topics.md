# Managing Kafka Topics on Amazon MSK

Two ways to manage topics on MSK Provisioned clusters: the native MSK **topic operations APIs** (`CreateTopic`/`DescribeTopic`/`UpdateTopic`/`DeleteTopic`/`ListTopics`) and Kafka's own admin protocol via a Kafka client (`kafka-topics.sh`, `kafka-python`, etc., or `AWS::MSK::Topic`/`CfnTopic` in IaC, which wraps the native API). Prefer the native MSK APIs / `CfnTopic` over standing up Kafka admin clients whenever the cluster and Kafka version support them.

## Prefer the native MSK topic APIs over Kafka admin clients

`ListTopics`, `DescribeTopic`, `DescribeTopicPartitions`, `CreateTopic`, `UpdateTopic`, and `DeleteTopic` are AWS APIs (CLI, SDK, CloudFormation, console) that manage Kafka topics without needing network access to brokers, a Kafka client library, or IAM/SCRAM/mTLS client auth setup. Use these by default instead of building a Kafka admin client (bastion host, Lambda with `kafka-python`, etc.) for topic CRUD.

**Requirements** — check these before assuming the API is available:

- MSK **Provisioned** only — not available for MSK Serverless.
- Kafka version **3.6.0 or later**.
- Cluster must be in `ACTIVE` state.
- Standard IAM permissions (below) — the calling identity does not need Kafka-level SASL/IAM client auth, only the `kafka-cluster:*` IAM actions on the cluster/topic ARN.

**Propagation lag**: topic API responses reflect state that updates approximately every minute. After a create/update/delete, allow about a minute before querying and expecting the change reflected — don't treat an immediate stale read as a failure.

### IAM permissions per operation

| Operation | Required actions | Resource(s) |
|---|---|---|
| `ListTopics` | `kafka-cluster:Connect`, `kafka-cluster:DescribeTopic` | Cluster ARN, Topic ARN (wildcard `*` allowed to match all topics) |
| `DescribeTopic` | `kafka-cluster:Connect`, `kafka-cluster:DescribeTopic`, `kafka-cluster:DescribeTopicDynamicConfiguration` | Cluster ARN, Topic ARN |
| `DescribeTopicPartitions` | `kafka-cluster:Connect`, `kafka-cluster:DescribeTopic`, `kafka-cluster:DescribeTopicDynamicConfiguration` | Cluster ARN, Topic ARN |
| `CreateTopic` | `kafka-cluster:Connect`, `kafka-cluster:CreateTopic` | Cluster ARN, Topic ARN |
| `UpdateTopic` | `kafka-cluster:Connect`, `kafka-cluster:DescribeTopic`, `kafka-cluster:AlterTopic`, `kafka-cluster:AlterTopicDynamicConfiguration` | Cluster ARN, Topic ARN |
| `DeleteTopic` | `kafka-cluster:Connect`, `kafka-cluster:DescribeTopic`, `kafka-cluster:DeleteTopic` | Cluster ARN, Topic ARN |

`kafka-cluster:Connect` is scoped to the **cluster** ARN in the policy; every other action is scoped to the **topic** ARN. A policy built by copying a typical produce/consume permission set often omits `kafka-cluster:DeleteTopic` — add it explicitly whenever a workflow needs to delete topics (including replicator-created internal bookkeeping topics, see [msk-replicator.md](msk-replicator.md)), since its absence only surfaces as a `TopicAuthorizationException` at delete time, not at policy-attach time.

### CLI usage

```bash
# Create
aws kafka create-topic \
  --cluster-arn <cluster-arn> \
  --topic-name orders \
  --partition-count 3 \
  --replication-factor 3

# List / describe
aws kafka list-topics --cluster-arn <cluster-arn>
aws kafka describe-topic --cluster-arn <cluster-arn> --topic-name orders
aws kafka describe-topic-partitions --cluster-arn <cluster-arn> --topic-name orders

# Update (e.g. change retention via base64-encoded configs)
aws kafka update-topic \
  --cluster-arn <cluster-arn> \
  --topic-name orders \
  --configs $(echo -n '{"retention.ms":"604800000"}' | base64)

# Delete
aws kafka delete-topic --cluster-arn <cluster-arn> --topic-name orders
```

`--configs` is a Base64-encoded **JSON object** of topic-config key/value pairs (e.g. `{"retention.ms":"604800000","cleanup.policy":"delete"}`) — not the `server.properties` line format used elsewhere for broker/cluster configuration (see the [create cluster configuration workflow](../SKILL.md#common-workflows) in the main SKILL.md, which is a different API and does use real-newline `key=value` lines). Encode the JSON string, not individual lines, before base64-encoding it. `DescribeTopic`/`ListTopics` responses return `configs` the same way — base64-decode to get the JSON object back, not properties-file text.

## IaC: prefer `AWS::MSK::Topic` (`CfnTopic`) over a custom resource

`aws-cdk-lib` (≥ ~2.251) ships `AWS::MSK::Topic` / `CfnTopic` natively — it wraps the same `CreateTopic`/`UpdateTopic`/`DeleteTopic` APIs above. Use it directly for any topic that needs to be provisioned as part of a stack. Do **not** build a Lambda-backed custom resource (e.g. Python + `kafka-python` + an IAM SASL token provider) to create topics — this requires bundling a Kafka client, VPC placement for the Lambda, dependency/version management, and reimplements what the native resource already does with none of that overhead.

```typescript
const topic = new msk.CfnTopic(this, 'OrdersTopic', {
  clusterArn: cluster.attrArn,
  topicName: 'orders',
  partitionCount: 3,
  replicationFactor: 3,
  // Optional: base64-encoded JSON object of topic configs (not server.properties lines)
  // configs: Buffer.from(JSON.stringify({ 'retention.ms': '604800000' })).toString('base64'),
});
topic.node.addDependency(cluster); // topic creation requires an ACTIVE cluster
```

Same version/Kafka-version constraints apply as the CLI/API above (Provisioned only, Kafka 3.6.0+, cluster must be `ACTIVE` before the topic resource can be created — add an explicit `addDependency` on the cluster construct since CloudFormation doesn't otherwise know to wait for `ACTIVE`).

## When you still need a Kafka admin client

Some topic-adjacent operations aren't covered by the MSK topic APIs (e.g. per-partition reassignment beyond what `UpdateTopic` exposes, consumer group management beyond what Replicator handles, ACL management outside IAM policies). For those, fall back to `kafka-topics.sh`/`kafka-consumer-groups.sh` from a bastion or client host with IAM or SASL/SCRAM auth configured — see [configure-clients.md](configure-clients.md) for client auth setup.

## References

- [Topic Operations overview](https://docs.aws.amazon.com/msk/latest/developerguide/msk-topic-operations-information.html)
- [Create topics in an Amazon MSK cluster](https://docs.aws.amazon.com/msk/latest/developerguide/msk-create-topic.html)
- [List topics](https://docs.aws.amazon.com/msk/latest/developerguide/msk-list-topics.html)
- [Get detailed information about a topic](https://docs.aws.amazon.com/msk/latest/developerguide/msk-describe-topic.html)
- [Update a topic](https://docs.aws.amazon.com/msk/latest/developerguide/msk-update-topic.html)
- [Delete a topic](https://docs.aws.amazon.com/msk/latest/developerguide/msk-delete-topic.html)
- [MSK simplifies Kafka topic management with new APIs and console integration](https://aws.amazon.com/about-aws/whats-new/2026/02/amazon-msk-kafka-topics-public-apis) (Feb 2026 launch announcement)
- [create-topic CLI reference](https://docs.aws.amazon.com/cli/latest/reference/kafka/create-topic.html)
