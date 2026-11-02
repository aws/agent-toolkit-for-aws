# MSK Replicator

Cross-cluster replication for migration, disaster recovery, active-active/active-passive, and multi-Region fan-out. Determine the topology and account layout first: which account each cluster lives in, which account the replicator itself will run in, and whether either cluster is Amazon MSK or third-party Kafka. That determines the `KafkaClusterProperty` type for each side, which in turn determines the auth, networking, and secret configuration described below.

## Choosing the `KafkaClusterProperty` type for each side

`AWS::MSK::Replicator`'s `KafkaClusters` list takes exactly two `KafkaClusterProperty` entries, each typed as either `AmazonMskCluster` or `ApacheKafkaCluster`. Choose the type based on whether the replicator can resolve the cluster natively, not just on whether it happens to be running Kafka:

| Scenario | Local cluster type | Remote cluster type |
|---|---|---|
| Both clusters are Amazon MSK, in the **same AWS account** as the replicator | `AmazonMskCluster` | `AmazonMskCluster` |
| One cluster is Amazon MSK in a **different AWS account** than the replicator | `AmazonMskCluster` (the one in the replicator's account) | `ApacheKafkaCluster` (the one in the other account — reference it as self-managed even though it is genuinely MSK) |
| Remote cluster is genuinely third-party/self-managed Kafka | `AmazonMskCluster` (your MSK side) | `ApacheKafkaCluster` |

Use `AmazonMskCluster` and reference the cluster by ARN whenever the replicator and that cluster share an account — this gets you IAM auth and skips the cluster-ID lookup entirely. Use `ApacheKafkaCluster` whenever the replicator cannot resolve the cluster's ARN directly, which includes any cross-account Amazon MSK cluster. When the remote side is `ApacheKafkaCluster` because it's a cross-account Amazon MSK cluster, apply the MSK-specific auth and secret rules below. When it's genuinely third-party Kafka, configure auth to match however that broker is actually set up instead.

### Set `vpcConfig` only on the `AmazonMskCluster` entry
Configure the replicator's ENI placement (`subnetIds`, `securityGroupIds`) exclusively on the `AmazonMskCluster` entry's `vpcConfig`. `vpcConfig` is not a supported field on `ApacheKafkaCluster` and the API rejects it:

```
The vpcConfig parameter is only supported for AmazonMskCluster.
```

Make sure the VPC behind the `AmazonMskCluster` entry already has a network path to the remote broker (VPC peering, PrivateLink, Transit Gateway, or Direct Connect) — the replicator uses existing routing and does not establish new connectivity for you.

Add a self-referencing ingress rule for the Kafka ports (9092/9094/9096/9098) on the security group used in `vpcConfig`, so the replicator's own ENIs can reach the local cluster's brokers over that same security group.

### Use SASL/SCRAM mechanism `SHA512` when the remote cluster is Amazon MSK
When the remote side is a cross-account Amazon MSK cluster referenced as `ApacheKafkaCluster`, set `clientAuthentication.saslScram.mechanism` to `'SHA512'`. Amazon MSK [only enables SCRAM-SHA-512](https://docs.aws.amazon.com/msk/latest/developerguide/msk-password-limitations.html) for SASL/SCRAM, never SHA-256, even though AWS's published `CreateReplicator` examples for self-managed sources show `"mechanism": "SHA256"` (that value applies to third-party brokers actually configured for SHA-256). Using `SHA256` against an MSK broker fails with:

```
Client SASL mechanism 'SCRAM-SHA-256' not enabled in the server,
enabled mechanisms are [SCRAM-SHA-512]
```

### Look up the real Kafka cluster ID for `apacheKafkaClusterId`
Set `apacheKafkaClusterId` to the cluster's actual Kafka cluster ID, retrieved directly from the broker:

```
kafka-cluster.sh cluster-id --bootstrap-server <broker>:9096 --config <sasl.properties>
```

Do not pass a human-readable name or label — the field accepts any string at creation time with no validation, but the replicator will fail once it attempts to connect, reporting `ConnectivityError.SourceApacheClusterIdInvalid` or `TargetApacheClusterIdInvalid` after sitting in `CREATING` for several minutes. Look up the cluster ID separately for every physical cluster you reference this way — a Standard and an Express cluster in the same account have distinct cluster IDs even if they serve the same logical workload.

### Create a copy of the SASL/SCRAM secret in the replicator's own account
Store the replicator's `clientAuthentication.saslScram.secretArn` in a Secrets Manager secret that lives in the **same account as the replicator**, even when the remote cluster and its own copy of the same secret live in a different account (required for `BatchAssociateScramSecret` on that cluster). In cross-account setups this means maintaining two Secrets Manager secrets with the same username/password: one in the source cluster's account for `BatchAssociateScramSecret`, and one in the replicator's account purely for the replicator config. The API enforces this directly:

```
The secretArn must be in the same account as the replicator.
```

### Verify SCRAM secret association explicitly — do not rely on API success alone
After calling `BatchAssociateScramSecret` (directly or via a custom resource), confirm the association succeeded by running:

```
aws kafka list-scram-secrets --cluster-arn <arn>
```

`BatchAssociateScramSecret` can return HTTP 200 while every secret in the request fails to associate — the per-secret failure is nested in `responseElements.unprocessedScramSecrets`, visible only in CloudTrail, not surfaced as an API error. A common cause is a missing KMS grant:

```json
"unprocessedScramSecrets": [{
  "secretArn": "arn:aws:secretsmanager:...:secret:AmazonMSK_...",
  "errorCode": "InvalidSecretArn",
  "errorMessage": "You are not authorized to invoke the CreateGrant operation on the KMS key that is used to encrypt the secret."
}]
```

MSK performs the KMS `CreateGrant` call as the IAM principal that invoked `BatchAssociateScramSecret` (e.g. a Lambda execution role behind a custom resource), not as the `kafka.amazonaws.com` service principal. Grant `kms:CreateGrant` and `kms:DescribeKey` on the secret's KMS key to that calling identity, scoped to the key's ARN, rather than to the MSK service principal on the key policy.

## Set `topicNameConfiguration` explicitly — do not rely on the default

Set `topicNameConfiguration: { type: 'IDENTICAL' }` whenever you need replicated topics to keep the exact source topic name — for example, transparent active-active/active-passive failover without reconfiguring clients, or any scenario that depends on the replicator's loop-prevention behavior (the `__mskmr` header check only matters when source and target topic names can collide). If you omit `topicNameConfiguration`, the replicator defaults to `PREFIXED_WITH_SOURCE_CLUSTER_ALIAS`, producing names like `<source-cluster-alias>.<original-topic-name>` — a different, valid choice when you don't need name parity, but treat it as a deliberate choice rather than an assumed default.

For bidirectional replication using `IDENTICAL` naming:

- Create both directions' replicators (forward and reverse) in the **same AWS account**.
- Reference each physical cluster with a **single, consistent type** (`AmazonMskCluster` or `ApacheKafkaCluster`) across both replicator definitions. Do not swap a cluster's type between the two directions — this breaks cross-account alias resolution and causes records to be re-replicated instead of being recognized as already-replicated.

## Size partition count before scaling the replicator

Partition count on the source and target clusters is the binding constraint on replication throughput, not replicator capacity. Replicator scaling only converts into throughput when there are enough partitions to spread load across, so check partition count first whenever throughput sits below target or `ReplicationLatency` climbs. AWS's own remedy for rising `ReplicationLatency` is to [check whether the clusters have enough partitions](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-metrics-ref.html).

Scaling cannot rescue an under-partitioned topic: 2 GB/s spread over 5 topic-partitions is unreachable at any replicator size, while the same 2 GB/s over ~100 partitions is achievable. Throughput also has to be *balanced* across those partitions — one hot partition caps the topic regardless of how many partitions exist.

### Published sizing table

The [recommended minimum partition counts](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-bp-sizing.html):

| Target throughput | Minimum partitions |
|---|---|
| 50 MB/s | 167 |
| 100 MB/s | 334 |
| 250 MB/s | 833 |
| 500 MB/s | 1666 |
| 1000 MB/s | 3333 |

Every row is exactly **0.3 MB/s per partition** — the conservative cross-Region figure. Use the table as published for cross-Region replication. For same-Region it over-provisions by roughly 10-30x, so treat it as a safe upper bound rather than a requirement and size from the per-partition ranges below.

### Per-partition throughput ranges

Capacity-modelling estimates only. These move with record size, batching, and cluster and replicator configuration, and are not service commitments — do not quote them to customers as guaranteed numbers.

| Topology | Typical per topic-partition | Tuned ceiling observed |
|---|---|---|
| Cross-Region | ~300 KB/s | 10-30 MB/s with tuned record batching, cluster configs, and replicator configs |
| Same-Region | 3-10 MB/s | — |

Aggregate throughput in the multiple-GB/s range is reachable same-Region when load spreads evenly over a sufficient partition count, subject to the per-replicator quota below. If customer is unable to reach desired throughput, recommend opening an AWS Support Case to investigate.

### Quotas that cap a single replicator

| Dimension | Quota | Adjustable |
|---|---|---|
| Replicators per account | 15 | Yes, via AWS Support |
| Topics per replicator | 750, selected in sorted order | Yes, via AWS Support |
| Ingress throughput per replicator | 1 GB/s | Yes, via AWS Support |
| Record size, cross-Region | 10 MB (`message.max.bytes`) | Yes, via AWS Support |
| Record size, same-Region | 20 MB (`message.max.bytes`) | Yes, via AWS Support |

The 1 GB/s ingress cap lands exactly where the published sizing table tops out, so anything past ~1 GB/s has to shard across multiple replicators — bounded in turn by 15 per account. The 750-topic cap is the other reason to shard, and it selects in sorted order, so topics past the limit are skipped silently rather than reported as an error. Track `TopicCount` to confirm the replicator picked up every topic you expected.

Provision source and target clusters for replication traffic *on top of* existing production load — the replicator consumes from the source (egress) and produces to the target (ingress). AWS recommends identical capacity on both sides.

### Confirm throughput from metrics, not configuration

Replicator metrics live in the `AWS/Kafka` namespace under the `ReplicatorName` dimension, in the **target cluster's Region**, and are available per-topic via `ReplicatorName, Topic`:

| Metric | Use |
|---|---|
| `ReplicatorThroughput` | Bytes/s actually replicated. A per-topic drop points at connectivity or cluster health — check `KafkaClusterPingSuccessCount` and `AuthError` next. |
| `ReplicatorBytesInPerSec` | Bytes/s processed, including loop-filtered records. This is the billed quantity. |
| `ReplicationLatency` | Source-produce to target-write, per partition (`Maximum`). Rising latency usually means too few partitions. |
| `MessageLag` | How far the replicator trails the **source cluster** — not source-to-target lag. Watch it reach 0 to confirm a catch-up or migration cutover finished. |
| `ReplicationFailures` | Should be 0. Non-zero points at record size, timestamp, or batch-size violations — check record size against the 10/20 MB caps above. |
| `ThrottleTime` | Per `ClusterAlias`. Above 0 means brokers are throttling the replicator; 0 alongside healthy latency and throughput means throttling is tuned correctly. |

Under `IDENTICAL` topic naming, `ReplicatorBytesInPerSec` exceeds `ReplicatorThroughput` by the volume of loop-filtered records, and you are billed on the larger number — bidirectional `IDENTICAL` setups pay data processing and transfer charges on records that get filtered rather than written. Under `PREFIXED_WITH_SOURCE_CLUSTER_ALIAS` nothing is filtered and the two metrics match, which makes an unexpected gap between them a useful signal that loop filtering is active.

A topic whose `ReplicationLatency` falls to 0 while the source topic's `MessagesInPerSec` stays non-zero indicates a topic-level authorization failure, not an idle topic — `AuthError` does not cover topic-level auth errors. Check the replicator's service execution role against that topic.

## Grant `kafka-cluster:DeleteTopic` alongside standard produce/consume permissions

Include `kafka-cluster:DeleteTopic` in any IAM policy that will need to remove topics, including the replicator's own internal bookkeeping topics during cleanup. A standard produce/consume/create-topic policy set (`Connect`, `DescribeTopic`, `CreateTopic`, `AlterTopic`, `WriteData`, `ReadData`) does not include it by default, and its absence only surfaces as `TopicAuthorizationException` at delete time.

See the [IAM Replicator permissions reference](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-iam-ref.html) for the full set of `kafka:*` control-plane permissions the replicator's own service execution role needs beyond `AWSMSKReplicatorExecutionRole`.

## Clean up internal bookkeeping topics explicitly

Enumerate and delete the replicator's internal bookkeeping topics as an explicit step in any teardown — deleting the replicator does not remove them. Each replication direction creates topics on both clusters resembling:

```
__amazon_msk_replicator_configs_<name>_<uuid>
__amazon_msk_replicator_offsets_<name>_<uuid>
__amazon_msk_replicator_status_<name>_<uuid>
__amazon_msk_replicator_source_heartbeats_<name>-<suffix>
__amazon_msk_replicator_target_heartbeats_<name>-<suffix>
mskr-offset-syncs.<cluster-id>.internal / .incoming.internal
checkpoints.internal / outgoing.checkpoints.internal
```

See [manage-topics.md](manage-topics.md) for topic deletion.

## Enable log delivery at creation time

Configure `logDelivery.replicatorLogDelivery.cloudWatchLogs` when you create the replicator, not afterward. Without it, `describe-replicator`'s terse `StateInfo` field is the only diagnostic signal available if something goes wrong. Adding log delivery to an existing replicator triggers a resource replacement (a new replicator, restarting replication from the configured starting position), so enable it up front instead.

```
aws kafka describe-replicator --replicator-arn <arn> --query 'ReplicatorState,StateInfo'
```

## Poll both `StateInfo` and CloudWatch Logs while a replicator is `CREATING`

Check `describe-replicator`'s `StateInfo` field and the configured CloudWatch log group together, since either one may surface the actionable error first depending on the failure mode, and `CREATING` can take anywhere from a few minutes to 30+ minutes:

- An invalid `apacheKafkaClusterId` produces no CloudWatch log output at all until the replicator gives up — `StateInfo` is the only signal.
- An auth mechanism mismatch or bad credentials produces continuous CloudWatch log noise throughout `CREATING`.

## Verify loop-prevention with an end-to-end produce/consume check, not resource state alone

Confirm replication is working correctly — and not looping — with a produce-then-double-read check, repeated per cluster type if you have separate Standard/Express replicator pairs:

1. Produce one record on the source topic.
2. Consume from earliest offset on the target topic — expect exactly 1 record.
3. Re-consume from earliest offset on the **source** topic — expect exactly 1 record (confirms the reverse replicator did not bounce the record back).

`ReplicatorState: RUNNING` and a correct `list-scram-secrets` result are necessary checks but do not by themselves confirm the absence of a duplicate-write loop.

## Example: same-account MSK-to-MSK (CDK)

```typescript
const local: msk.CfnReplicator.KafkaClusterProperty = {
  amazonMskCluster: { mskClusterArn: sourceCluster.attrArn },
  vpcConfig: {
    subnetIds: vpc.privateSubnets.map((s) => s.subnetId),
    securityGroupIds: [replicatorSecurityGroup.securityGroupId],
  },
};
const remote: msk.CfnReplicator.KafkaClusterProperty = {
  amazonMskCluster: { mskClusterArn: targetCluster.attrArn },
  vpcConfig: {
    subnetIds: vpc.privateSubnets.map((s) => s.subnetId),
    securityGroupIds: [replicatorSecurityGroup.securityGroupId],
  },
};
```

## Example: cross-account MSK-to-MSK (remote referenced as self-managed)

```typescript
const local: msk.CfnReplicator.KafkaClusterProperty = {
  amazonMskCluster: { mskClusterArn: localCluster.attrArn },
  vpcConfig: {
    subnetIds: vpc.privateSubnets.map((s) => s.subnetId),
    securityGroupIds: [replicatorSecurityGroup.securityGroupId],
  },
};
const remote: msk.CfnReplicator.KafkaClusterProperty = {
  // No vpcConfig here - only valid on the AmazonMskCluster entry.
  // Connectivity comes from local's VPC via peering/TGW/PrivateLink to the
  // remote account's broker IPs.
  apacheKafkaCluster: {
    apacheKafkaClusterId: remoteApacheKafkaClusterId, // real cluster ID from kafka-cluster.sh, not a label
    bootstrapBrokerString: remoteBootstrapBrokerString,
  },
  clientAuthentication: {
    saslScram: {
      mechanism: 'SHA512', // required when the remote is Amazon MSK
      secretArn: localCopyOfRemoteSecret.secretArn, // must live in the replicator's own account
    },
  },
  encryptionInTransit: { encryptionType: 'TLS' },
};
```

## References

- [MSK Replicator overview](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator.html)
- [CreateReplicator API examples for self-managed Kafka clusters](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-external-api-examples.html)
- [Topic naming for MSK Replicator](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-topic-naming.html)
- [Active-active replication](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-active-active.html)
- [Active-passive cluster setup](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicators-active-passive-cluster-setup.html)
- [IAM permissions reference for Replicator](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-iam-ref.html)
- [SASL/SCRAM password limitations](https://docs.aws.amazon.com/msk/latest/developerguide/msk-password-limitations.html)
- [Sizing and partitions best practices](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-bp-sizing.html)
- [Replicator metrics reference](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-metrics-ref.html)
- [Monitor an MSK Replicator](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator-monitor.html)
- [MSK Replicator quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html)
