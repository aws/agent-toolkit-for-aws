# ElastiCache Cluster Setup for KV Caching

## Table of contents

- Supported configuration
- Shell setup and helpers
- Prerequisites
- Cache password secret
- Users and ACL setup
- Eviction policy and TTL
- Create the cluster
- Shard count and capacity
- Verify the cluster
- Working with the valkey-large-object module
- Constraints and limitations
- Teardown

## Supported configuration

The node type selects the module, the DRAM and NVMe tiers, and EFA RDMA (no separate API parameter).

| Setting | Required value |
|---------|---------------|
| Node type | `cache.i8ge.48xlarge`. For the hardware (memory, NVMe, network bandwidth), see [Amazon EC2 I8g instances](https://aws.amazon.com/ec2/instance-types/i8g/) |
| Engine | `valkey`, version `9.1` or later |
| Cluster mode | Enabled |
| Automatic failover | Enabled (the API requires it for cluster mode, also with 0 replicas) |
| Replicas per shard | 0 |
| Availability Zone | All shards in the **same** Availability Zone as the GPU servers |
| Transit encryption | Enabled, mode `required` |
| At-rest encryption | On by default for Valkey. Keep `--at-rest-encryption-enabled`. For a customer managed key, add `--kms-key-id <key-arn>` |

The module runs in **Tiered** mode: objects live on NVMe with a DRAM read cache.

Choose the newest engine version 9.1 or later, and its parameter group family (for example `valkey9` for 9.x; the default group is `default.<family>.cluster.on`):

```bash
aws elasticache describe-cache-engine-versions --region $AWS_REGION --engine valkey \
  --query 'CacheEngineVersions[].[EngineVersion,CacheParameterGroupFamily]' --output text
```

## Shell setup and helpers

Every name comes from `CLUSTER_NAME` (at most 33 characters: a letter, then letters, digits, single hyphens), so caches do not collide. `TAGS` holds the `Project` tag (teardown deletes only resources with it) and the attribution tags; set `MODEL_ID` to your own model identifier. If an AWS Organizations tag policy refuses `created_by` or `generation_model`, remove that tag and continue.

Run this block in every new shell; the other references use these helpers. A failed check prints `STOP:`: stop there and report. Helpers `return` and never `exit`, so the shell stays open.

```bash
export AWS_SDK_UA_APP_ID=AWSSkill-ElastiCache
export AWS_REGION=<region> CLUSTER_NAME=<cluster-name> PROJECT=<project-tag> MODEL_ID=<your-model-id>
[[ $CLUSTER_NAME =~ ^[a-zA-Z]([a-zA-Z0-9]|-[a-zA-Z0-9])*$ ]] && [ ${#CLUSTER_NAME} -le 33 ] \
  || echo "STOP: CLUSTER_NAME must start with a letter, use single hyphens, and be at most 33 characters"
[[ $PROJECT =~ ^[A-Za-z0-9._:/+=@-]+$ ]] || echo "STOP: PROJECT contains invalid tag characters"
[[ $MODEL_ID =~ ^[A-Za-z0-9._:/+=@-]+$ ]] || echo "STOP: MODEL_ID contains invalid tag characters"
export ENGINE_VERSION=<engine-version> FAMILY=<parameter-group-family>   # see "Supported configuration"
export SECRET_ID=${CLUSTER_NAME}-cache-password   # or the ID of an existing secret
TAGS=(Key=Project,Value="$PROJECT" Key=created_by,Value=distributed-kv-caching-skill Key=generation_model,Value="$MODEL_ID")

# Secret step (see "Secret steps"). Print the cache password; pipe it to the consumer only.
get_pw() { aws secretsmanager get-secret-value --region $AWS_REGION --secret-id "$SECRET_ID" \
  --query SecretString --output text; }

# retry <tries> <seconds> <command...>: repeat until the command returns 0. It stops at once
# when the command returns 2 (a final failure), and returns 1 when the tries end.
retry() { local n=$1 s=$2 i rc; shift 2
  for i in $(seq $n); do if "$@"; then return 0; else rc=$?; fi; [ $rc = 2 ] && return 2; sleep $s; done; return 1; }

# on_primaries <valkey-cli args>: run on every primary (INFO reaches one node). Returns 1 if a node fails.
on_primaries() { local c H M rc=0
  M=$(aws elasticache describe-replication-groups --region $AWS_REGION --replication-group-id $CLUSTER_NAME \
    --query 'ReplicationGroups[0].MemberClusters' --output text) && [ -n "$M" ] && [ "$M" != None ] \
    || { echo "STOP: no member clusters"; return 1; }
  for c in $M; do
    H=$(aws elasticache describe-cache-clusters --region $AWS_REGION --cache-cluster-id $c \
          --show-cache-node-info --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' --output text) \
      && [ -n "$H" ] || { echo "== $c: no endpoint"; rc=1; continue; }
    echo "== $c"; get_pw | valkey-cli --tls -h $H -p 6379 --user kv-cache-user --askpass "$@" || rc=1
  done; return $rc; }

# rg_ok: 0 when the replication group is available, 1 while it changes, 2 on any other status.
rg_ok() { local S; S=$(aws elasticache describe-replication-groups --region $AWS_REGION \
    --replication-group-id $CLUSTER_NAME --query 'ReplicationGroups[0].Status' --output text) || return 1
  case "$S" in available) return 0 ;; creating|modifying) return 1 ;; *) echo "replication group: $S"; return 2 ;; esac; }
```

`on_primaries` needs `valkey-cli` 8.0 or later with TLS (`BUILD_TLS=yes`), on a client in the same VPC, Availability Zone, and security group. `CONFIG GET` does not work on managed clusters; read settings with `INFO`.

**Re-runs.** Before each create, describe the resource by name: reuse it if it matches, else stop and ask the builder. After each command that sets a variable, run `test -n "$VAR"` and stop if it is empty.

### Secret steps

This is the one home for the secret-step rule. A secret step creates, reads, or uses the cache password or the LMCache API key: `get-random-password`, `create-secret`, `put-secret-value`, `create-user` or `modify-user` with passwords, and `get_pw` with the helpers that call it (`on_primaries`). Each such block starts with `# Secret step`.

- You MUST run it only in a shell where the secret goes only to a pipe or a 0600 file, never to the command output. You MUST NOT run it through an AWS API tool that returns the response to you (for example the MCP `call_aws` tool, which also refuses `file://` arguments): the secret would go into the model context, the transcript, and the tool log.
- You MUST NOT print, echo, or paste a secret, and MUST NOT add `--debug` (it prints request and response bodies).
- If no such shell is available, stop and ask the builder to run these steps.

## Prerequisites

Read the VPC, private subnet, and Availability Zone from a GPU server ([network isolation](SKILL.md#security-considerations)).

```bash
read VPC_ID SUBNET_AZ AZ < <(aws ec2 describe-instances --region $AWS_REGION \
  --instance-ids <gpu-instance-id> \
  --query 'Reservations[0].Instances[0].[VpcId,SubnetId,Placement.AvailabilityZone]' --output text)
aws ec2 describe-subnets --region $AWS_REGION --subnet-ids $SUBNET_AZ \
  --query 'Subnets[0].AvailableIpAddressCount'   # MUST be at least the shard count

# Subnet group for the one Availability Zone (no PrimaryAvailabilityZone needed later)
aws elasticache create-cache-subnet-group --region $AWS_REGION \
  --cache-subnet-group-name ${CLUSTER_NAME}-subnets \
  --cache-subnet-group-description "KV caching, single AZ" \
  --subnet-ids $SUBNET_AZ --tags "${TAGS[@]}"
```

### Security group

EFA requires a group that allows **all traffic to and from itself**. Both self-referencing rules MUST be present, else RDMA transfers fail. Attach it to the cluster and the GPU servers ([client-setup.md](references/client-setup.md#security-group)).

```bash
export SG_ID=$(aws ec2 create-security-group --region $AWS_REGION \
  --group-name ${CLUSTER_NAME}-efa --description "KV caching EFA + Valkey" --vpc-id $VPC_ID \
  --tag-specifications "ResourceType=security-group,Tags=[{Key=Project,Value=$PROJECT},{Key=created_by,Value=distributed-kv-caching-skill},{Key=generation_model,Value=$MODEL_ID}]" \
  --query GroupId --output text)
test -n "$SG_ID"
SELF="IpProtocol=-1,UserIdGroupPairs=[{GroupId=$SG_ID}]"
aws ec2 authorize-security-group-ingress --region $AWS_REGION --group-id $SG_ID --ip-permissions "$SELF"
aws ec2 authorize-security-group-egress  --region $AWS_REGION --group-id $SG_ID --ip-permissions "$SELF"
# The default 0.0.0.0/0 egress rule does not carry EFA traffic. Revoke it (in an IPv6 VPC, also ::/0).
# The GPU servers keep internet egress through their other groups.
aws ec2 revoke-security-group-egress --region $AWS_REGION --group-id $SG_ID \
  --ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]'
```

In a new shell, find the group by name:

```bash
SG_ID=$(aws ec2 describe-security-groups --region $AWS_REGION \
  --filters Name=group-name,Values=${CLUSTER_NAME}-efa Name=vpc-id,Values=$VPC_ID \
  --query 'SecurityGroups[0].GroupId' --output text); [ -n "$SG_ID" ] && [ "$SG_ID" != None ] || echo "STOP: no group"
```

## Cache password secret

- The secret value MUST be the password only, as plain text, not a key/value JSON secret: the launcher uses `SecretString` as the password.
- ElastiCache passwords MUST have 16 to 128 printable characters and MUST NOT contain `,` `"` `/` or `@`. A 32-character alphanumeric password meets these rules.
- The password MUST NOT be on a command line, in a shell variable, in a config file, or in a log. Pipe `get_pw` to the consumer, or use a 0600 file and delete it after use.
- For an existing secret, set `SECRET_ID` to it and check these rules. Teardown deletes only the secret named `${CLUSTER_NAME}-cache-password`; it never deletes an existing secret.
- The blocks run in a subshell `( ... )`, so `umask 077` and the `trap` do not stay in the shell.

```bash
# Secret step (see "Secret steps")
( umask 077; PW_FILE=$(mktemp) || exit 1; trap 'rm -f "$PW_FILE"' EXIT
  aws secretsmanager get-random-password --region $AWS_REGION --password-length 32 \
    --exclude-punctuation --query RandomPassword --output text | tr -d '\n' > "$PW_FILE" && [ -s "$PW_FILE" ] &&
  aws secretsmanager create-secret --region $AWS_REGION --name "$SECRET_ID" \
    --kms-key-id <kms-key-arn> --secret-string "file://$PW_FILE" --tags "${TAGS[@]}" >/dev/null )
```

Omit `--kms-key-id` for the AWS managed key.

## Users and ACL setup

The LMCache Valkey adapter supports only password authentication: it passes a user name and password to `ServerCredentials` and does not use the valkey-glide `IamAuthConfig`.

A Valkey user group needs no `default` user, and attaching it to a cluster turns off the `default` user ([RBAC guide](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Clusters.RBAC.html)). Put only the LMCache user in the group. You MUST NOT create a user with `--no-password-required`: ElastiCache refuses it for the Valkey engine.

`jq` builds the input file, so the password is not in argv and no character breaks the JSON:

```bash
# Secret step (see "Secret steps")
( umask 077; PW_FILE=$(mktemp) && IN_FILE=$(mktemp) || exit 1; trap 'rm -f "$PW_FILE" "$IN_FILE"' EXIT
  get_pw | tr -d '\n' > "$PW_FILE" && [ -s "$PW_FILE" ] || exit 1
  jq -n --rawfile pw "$PW_FILE" --arg id "${CLUSTER_NAME}-user" --arg project "$PROJECT" --arg model "$MODEL_ID" \
    --arg acl "<access string for the transport, from the table below>" \
    '{UserId: $id, UserName: "kv-cache-user", Engine: "valkey",
      AuthenticationMode: {Type: "password", Passwords: [$pw]}, AccessString: $acl,
      Tags: [{Key: "Project", Value: $project}, {Key: "created_by", Value: "distributed-kv-caching-skill"},
             {Key: "generation_model", Value: $model}]}' > "$IN_FILE" &&
  aws elasticache create-user --region $AWS_REGION --cli-input-json "file://$IN_FILE" >/dev/null )

aws elasticache create-user-group --region $AWS_REGION --user-group-id ${CLUSTER_NAME}-ug \
  --engine valkey --user-ids ${CLUSTER_NAME}-user --tags "${TAGS[@]}"

# The group MUST be active before the cluster create (else InvalidUserGroupState).
# No CLI waiter exists: poll every 15 s for at most 10 min; stop on any other status.
ug_active() { local S; S=$(aws elasticache describe-user-groups --region $AWS_REGION \
    --user-group-id ${CLUSTER_NAME}-ug --query 'UserGroups[0].Status' --output text) || return 1
  case "$S" in active) return 0 ;; creating|modifying) return 1 ;; *) echo "user group: $S"; return 2 ;; esac; }
retry 40 15 ug_active || echo "STOP: user group not active"
```

Access strings. LMCache writes keys as `<key_prefix>@<key>`, so `~<key_prefix>@*` limits the user to LMCache keys; the `key_prefix` MUST NOT be empty and MUST match `^[A-Za-z0-9._:-]+$` — reject any value that contains glob characters (`*`, `?`, `[`), spaces, or other special characters before creating the user, because they widen the key pattern or inject ACL tokens. For several prefixes, list one `~<prefix>@*` per prefix; you MUST NOT use a wildcard prefix such as `~*@*`. `<glide>` stands for the commands that valkey-glide uses to connect and read the topology: `+PING +client|setinfo +client|setname +cluster|slots +cluster|info`.

| Client | Access string |
|---|---|
| LMCache, `rdma` | `on ~<key_prefix>@* +@largeobj +EXISTS +DEL +EXPIRE +INFO <glide>` |
| LMCache, `blob-tcp` | `on ~<key_prefix>@* ~__lmcache_blob_tcp_probe__ +@largeobj +EXISTS +DEL +EXPIRE +INFO <glide>`. Each worker sends `BLOB.INFO __lmcache_blob_tcp_probe__` at connect; without the probe key, LMCache does not start |
| LMCache, `tcp` | `on ~<key_prefix>@* +GET +SET +EXISTS +DEL +INFO <glide>`. The TTL is in the same `SET ... EX`, so no `@largeobj` and no `+EXPIRE` |
| Read-only | `on ~<key_prefix>@* +BLOB.TCP_GET +BLOB.RDMA_HELLO +BLOB.RDMA_GET +BLOB.INFO +EXISTS +INFO <glide>` |

Write `<glide>` out in full. You MUST NOT grant `@read`, `@keyspace`, `@dangerous`, `KEYS`, or `SCAN`: key patterns do not filter the output of `KEYS` and `SCAN`, and `KEYS` on a large node blocks it. `@largeobj` and `BLOB.*` need Valkey 9.1 or later. For `NOPERM`, see [troubleshooting.md](references/troubleshooting.md#authentication-failure).

## Eviction policy and TTL

The module obeys `maxmemory-policy`. Choose one option before you create the cluster:

- **Option A: default parameter group (`volatile-lru`).** Use `default.<family>.cluster.on` (for example `default.valkey9.cluster.on`), and set `ttl_seconds` in the LMCache adapter config, so that every LMCache key has a TTL and can be evicted.
- **Option B: custom parameter group (`allkeys-lru`).** For LMCache keys with no TTL. Use a dedicated cluster, because `allkeys-lru` can evict the keys of other applications.

Under `volatile-lru`, keys with no TTL are never evicted, so writes fail when the cache is full. Under `noeviction`, a write that does not fit fails with OOM.

**TTL rules** (the one home for TTL per transport):

- `tcp` sets the TTL in the same `SET ... EX`.
- `rdma` and `blob-tcp` send a separate `EXPIRE` after each store (one more round trip, not atomic). The access string MUST have `+EXPIRE`, else each `EXPIRE` fails with `NOPERM`, LMCache logs a failed store, and the object keeps no TTL, so `volatile-lru` cannot evict it and the disk fills.
- The TTL counts from the write; a read does not reset it. Set it above the longest session and above the p99 of `lmcache_mp_real_reuse_gap_seconds` (or the KVTrace reuse gap).
- Keys written before you set `ttl_seconds` have no TTL.
- Under Option B, `ttl_seconds` is optional, for session-scoped expiry only. A TTL does not lower the cost (nodes cost the same full or empty) and can drop data that LRU would keep, so do not set one when conversations return at unpredictable times.

**Option B group.** A new group (for example family `valkey9`) has `cluster-enabled no`, which fails a cluster-mode create. Set both values and check them:

```bash
aws elasticache create-cache-parameter-group --region $AWS_REGION \
  --cache-parameter-group-name ${CLUSTER_NAME}-params --cache-parameter-group-family $FAMILY \
  --description "KV caching params" --tags "${TAGS[@]}"
aws elasticache modify-cache-parameter-group --region $AWS_REGION \
  --cache-parameter-group-name ${CLUSTER_NAME}-params --parameter-name-values \
  "ParameterName=cluster-enabled,ParameterValue=yes" "ParameterName=maxmemory-policy,ParameterValue=allkeys-lru"
aws elasticache describe-cache-parameters --region $AWS_REGION --cache-parameter-group-name ${CLUSTER_NAME}-params \
  --query "Parameters[?ParameterName=='cluster-enabled' || ParameterName=='maxmemory-policy'].[ParameterName,ParameterValue]"
```

`cluster-enabled` applies only at create; `maxmemory-policy` is dynamic. Move a running cluster to Option B only if it is dedicated to LMCache (`allkeys-lru` can evict other applications' keys on a shared cluster). Create the group, get the builder's approval, assign it, wait, and repeat the post-fill check's policy read until every primary shows `allkeys-lru` (the status can stay `available` before the change starts):

```bash
# After the builder confirms the cluster is dedicated to LMCache:
# aws elasticache modify-replication-group --region $AWS_REGION --replication-group-id $CLUSTER_NAME \
#   --cache-parameter-group-name ${CLUSTER_NAME}-params --apply-immediately
# retry 120 30 rg_ok || echo "STOP: replication group not available"
```

**Post-fill check (both options).** After `largeobj_disk_utilization_pct` passes 90, on every primary: `maxmemory_policy` is the chosen policy, `evicted_keys` MUST grow, and `largeobj_disk_capacity_exceeded` MUST stay 0. If `evicted_keys` stays flat while `largeobj_disk_capacity_exceeded` grows, LMCache keys have no TTL under `volatile-lru`: set `ttl_seconds`, or move to Option B (recovery: [troubleshooting.md](references/troubleshooting.md#diagnose-a-full-cache)).

```bash
# Secret step (see "Secret steps")
for s in memory stats largeobj; do on_primaries INFO $s || echo "STOP: INFO $s failed on a primary"; done \
  | grep -E '^==|STOP|maxmemory_policy|evicted_keys|disk_utilization_pct|disk_capacity_exceeded'
```

## Create the cluster

Before the create, you MUST show the builder the shard count, the node type (`cache.i8ge.48xlarge`), the hourly price per node × shards, and the monthly estimate (hourly × 730), from the builder's price or the [ElastiCache pricing page](https://aws.amazon.com/elasticache/pricing/). Billing starts at create. Run it only after the builder approves.

Patching empties the cache, so ask for a low-traffic maintenance window (at least 60 minutes). Create the encrypted log group first; the KMS key policy MUST allow CloudWatch Logs to use the key.

```bash
export SHARDS=<shard-count>  # Fixed at create time. See "Shard count and capacity".
LOG_GROUP=/elasticache/${CLUSTER_NAME}
aws logs create-log-group --region $AWS_REGION --log-group-name $LOG_GROUP \
  --kms-key-id <kms-key-arn> --tags "Project=$PROJECT,created_by=distributed-kv-caching-skill,generation_model=$MODEL_ID"
LOGDEST="DestinationType=cloudwatch-logs,DestinationDetails={CloudWatchLogsDetails={LogGroup=$LOG_GROUP}},LogFormat=json"

aws elasticache create-replication-group --region $AWS_REGION \
  --replication-group-id $CLUSTER_NAME \
  --replication-group-description "KV cache for LLM inference" \
  --engine valkey --engine-version $ENGINE_VERSION \
  --cache-node-type cache.i8ge.48xlarge \
  --cache-parameter-group-name default.$FAMILY.cluster.on \
  --cluster-mode enabled --num-node-groups $SHARDS --replicas-per-node-group 0 \
  --automatic-failover-enabled \
  --cache-subnet-group-name ${CLUSTER_NAME}-subnets --security-group-ids $SG_ID \
  --transit-encryption-enabled --transit-encryption-mode required \
  --at-rest-encryption-enabled \
  --user-group-ids ${CLUSTER_NAME}-ug \
  --preferred-maintenance-window <ddd:hh24:mi-ddd:hh24:mi> \
  --log-delivery-configurations "LogType=slow-log,$LOGDEST" "LogType=engine-log,$LOGDEST" \
  --tags "${TAGS[@]}"
```

For Option B, use `--cache-parameter-group-name ${CLUSTER_NAME}-params`.

Wait for `available` for at most 60 minutes. `rg_ok` stops at once on any other status (for example `create-failed`): stop and report. The configuration endpoint goes to `startup_nodes`.

```bash
if retry 120 30 rg_ok; then
  aws elasticache describe-replication-groups --region $AWS_REGION \
    --replication-group-id $CLUSTER_NAME \
    --query 'ReplicationGroups[0].ConfigurationEndpoint.Address' --output text
else
  echo "STOP: replication group not available"
fi
```

## Shard count and capacity

This section is the one home for the shard-count rule. Choose the count at create time: large-object node types do not support shard changes. To change it, create a new cluster, which starts empty. Before you plan a resize, check the [ElastiCache documentation](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/WhatIs.html).

Each shard adds:

- **NVMe.** 120 TB per node, the same as `i8ge.48xlarge`. Usable capacity is lower (file system and encryption overhead, space the module keeps). Read `largeobj_disk_used_bytes` at run time.
- **DRAM read cache.** Size changes at run time (`largeobj_dram_capacity_bytes`).
- **Bandwidth** ([Amazon EC2 I8g instances](https://aws.amazon.com/ec2/instance-types/i8g/)).

Take the larger of the capacity need and the bandwidth need ([cost-assessment.md](references/cost-assessment.md#estimate-with-kvtrace), [optimization.md](references/optimization.md#shard-count)).

## Verify the cluster

Each member cluster is one primary; check every one:

```bash
# Secret step (see "Secret steps")
on_primaries INFO largeobj
```

(valkey-glide: `custom_command(["INFO", "largeobj"], route=AllNodes())`.) A `largeobj` section on every primary means that the module is loaded.

| Field | Meaning |
|---|---|
| `largeobj_num_objects`, `largeobj_evictions` | Objects stored, objects evicted |
| `largeobj_dram_allocated_bytes` / `largeobj_dram_capacity_bytes`, `largeobj_dram_utilization_pct` | DRAM tier |
| `largeobj_disk_used_bytes`, `largeobj_disk_utilization_pct` | NVMe tier |
| `largeobj_rdma_sessions` | Active RDMA sessions |
| `largeobj_rdma_read_bytes` | Bytes the server read from client memory. A client **store** (`BLOB.RDMA_SET`) adds to it |
| `largeobj_rdma_write_bytes` | Bytes the server wrote into client memory. A client **load** (`BLOB.RDMA_GET`) adds to it |
| `largeobj_rdma_read_errors`, `largeobj_rdma_write_errors` | MUST stay 0. Else see [troubleshooting.md](references/troubleshooting.md#rdma-transfer-fails-after-successful-hello) |
| `largeobj_disk_capacity_exceeded` | Writes refused, disk full. MUST stay 0 (see [Eviction policy and TTL](#eviction-policy-and-ttl)) |
| `largeobj_crc_mismatch` | Writes refused, CRC did not match. MUST stay 0 (see [troubleshooting.md](references/troubleshooting.md#err-crc-mismatch-after-transfer)) |
| `largeobj_dram_pool_exhausted`, `largeobj_disk_staging_buffer_exhausted` | Pool allocation failures (see [troubleshooting.md](references/troubleshooting.md#elasticache-cluster-issues)) |

An end-to-end test proves both directions only when, summed over the primaries, `largeobj_rdma_read_bytes` and `largeobj_rdma_write_bytes` are both above 0 (test steps: [lmcache-setup.md](references/lmcache-setup.md#before-production-traffic)). For CloudWatch metrics and alarms, see [optimization.md](references/optimization.md#monitoring-cache-effectiveness).

### Fault test

Run it only before production traffic, after the builder confirms. It removes the egress self-rule for 60 seconds; the `trap` puts it back also if the shell ends early, because without it RDMA stops for every member.

```bash
SELF="IpProtocol=-1,UserIdGroupPairs=[{GroupId=$SG_ID}]"
( trap 'aws ec2 authorize-security-group-egress --region $AWS_REGION --group-id $SG_ID --ip-permissions "$SELF"' EXIT
  aws ec2 revoke-security-group-egress --region $AWS_REGION --group-id $SG_ID --ip-permissions "$SELF"
  sleep 60 )
aws ec2 describe-security-groups --region $AWS_REGION --group-ids $SG_ID --query "SecurityGroups[0].IpPermissionsEgress"
```

During the 60 seconds, send already-stored prompts longer than one chunk; they stop, because RDMA transfers have no timeout. Pass: they complete within a few minutes after the restore, and the RDMA error counters stop growing.

## Working with the valkey-large-object module

LMCache calls the BLOB commands. Call them yourself only to debug.

- **`BLOB.TCP_SET`, `BLOB.TCP_GET`.** Bulk strings over TLS, from any client (test below; delete the key, it has no TTL).
- **`BLOB.RDMA_HELLO`, `BLOB.RDMA_SET`, `BLOB.RDMA_GET`.** Need EFA-registered memory, so not from `valkey-cli`. Each LMCache worker sends HELLO once at connect.
- **`BLOB.INFO key [LEN|CRC|TIER]`.** Size, CRC32C, or tier (`dram` or `disk`), without the data.
- **`DEL key`.** Frees DRAM and NVMe. LMCache keys normally go by eviction or TTL.

```bash
# Secret step (see "Secret steps")
CLI="valkey-cli --tls -c -h <cluster-endpoint> -p 6379 --user kv-cache-user --askpass"
get_pw | $CLI BLOB.TCP_SET <key_prefix>@test-key "hello-world"   # OK
get_pw | $CLI BLOB.TCP_GET <key_prefix>@test-key                 # "hello-world"
get_pw | $CLI DEL <key_prefix>@test-key                          # (integer) 1
```

Constraints for all BLOB commands:

- You MUST NOT put BLOB commands in `MULTI`/`EXEC`, an atomic batch, or a Lua script.
- Objects MUST be at or below 536,870,912 bytes (512 MiB).
- Multi-key commands MUST stay in one hash slot.
- `CONFIG` and `MODULE LIST` are blocked on ElastiCache. Use `INFO largeobj`.

## Constraints and limitations

The API rejects these with `InvalidParameterCombination` or `InvalidParameterValue`. The error text is an example and can change.

| Constraint | Example error text |
|-----------|-------------------|
| Non-Valkey engine, or engine version < 9.1 | "require engine 'valkey'", "require engine version 9.1 or later" |
| Cluster mode disabled | "require cluster mode enabled" |
| Replicas > 0 | "ReplicasPerNodeGroup must be 0" |
| Shards in different AZs | "All shards must reside in the same Availability Zone" |
| Transit encryption off or `preferred` | "require TransitEncryptionEnabled to be true with TransitEncryptionMode required" |
| Snapshot restore or retention > 0, durability, data tiering, Global Datastore, Multi-Region, Multi-AZ | "... is not supported for large-objects node types", "SnapshotRetentionLimit must be 0", "cannot be combined with" |
| Node type change, shard count change | "Changing the node type ... is not supported", "Modifying the shard configuration is not supported" |
| `create-cache-cluster` API | "supported only by CreateReplicationGroup" |

Other limits: no Serverless caches; no automatic backups; patching loses all cached data; only Regions that offer `cache.i8ge.48xlarge`.

## Teardown

You MUST list what you will delete and get confirmation. First restore the original group lists of the GPU servers' interfaces ([client-setup.md](references/client-setup.md#security-group)). In a new shell, run [Shell setup and helpers](#shell-setup-and-helpers), set `VPC_ID`, and find `SG_ID` by name.

You MUST delete only resources that this skill created: `mine` checks the `Project` and `created_by` tags before each delete, and skips and reports a resource without both of this skill's tags. Teardown deletes the secret only when `SECRET_ID` is `${CLUSTER_NAME}-cache-password`, never an existing secret of the builder. The IAM inline policy has no tags; delete it only by the name `${CLUSTER_NAME}-read-secret`. Delete in this order: the next delete fails while the previous resource is in use.

```bash
read ACCT PART < <(aws sts get-caller-identity --region $AWS_REGION --query '[Account,Arn]' --output text)
PART=$(echo "$PART" | cut -d: -f2); [ -n "$ACCT" ] && [ -n "$PART" ] || echo "STOP: no caller identity"
mine() { [ -n "$PROJECT" ] || { echo "STOP: PROJECT is empty"; return 1; }
  local p="$1" c="$2" r="$3"; [ "$p" = "$PROJECT" ] && [ "$c" = "distributed-kv-caching-skill" ] \
    || { echo "SKIP $r: Project='$p' created_by='$c'"; return 1; }; }
ec_mine() { local tags; tags=$(aws elasticache list-tags-for-resource --region $AWS_REGION --resource-name \
  arn:$PART:elasticache:$AWS_REGION:$ACCT:$1 --query "TagList[?Key=='Project'||Key=='created_by'].[Key,Value]" --output text) || { echo "SKIP $1: cannot read tags"; return 1; }
  mine "$(echo "$tags" | awk '$1=="Project"{print $2}')" "$(echo "$tags" | awk '$1=="created_by"{print $2}')" $1; }
ug_gone() { local e; e=$(aws elasticache describe-user-groups --region $AWS_REGION \
    --user-group-id ${CLUSTER_NAME}-ug 2>&1 >/dev/null) && return 1
  case "$e" in *UserGroupNotFound*) return 0 ;; *Throttl*|*RequestLimitExceeded*) return 1 ;;
    *) echo "$e"; return 2 ;; esac; }
no_enis() { local o; o=$(aws ec2 describe-network-interfaces --region $AWS_REGION --filters Name=group-id,Values=$SG_ID \
  --query 'NetworkInterfaces[].NetworkInterfaceId' --output text) || return 1; [ -z "$o" ]; }   # leave after minutes

teardown() { local LG=/elasticache/${CLUSTER_NAME}
  if ec_mine replicationgroup:$CLUSTER_NAME; then
    aws elasticache delete-replication-group --region $AWS_REGION --replication-group-id $CLUSTER_NAME || return 1
    retry 6 0 aws elasticache wait replication-group-deleted --region $AWS_REGION \
      --replication-group-id $CLUSTER_NAME || { echo "STOP: replication group still exists"; return 1; }
  fi
  if ec_mine usergroup:${CLUSTER_NAME}-ug; then
    aws elasticache delete-user-group --region $AWS_REGION --user-group-id ${CLUSTER_NAME}-ug || return 1
    retry 40 15 ug_gone || { echo "STOP: user group not deleted, or its state is unknown"; return 1; }
  fi
  ec_mine user:${CLUSTER_NAME}-user && aws elasticache delete-user --region $AWS_REGION --user-id ${CLUSTER_NAME}-user
  ec_mine parametergroup:${CLUSTER_NAME}-params && aws elasticache delete-cache-parameter-group \
    --region $AWS_REGION --cache-parameter-group-name ${CLUSTER_NAME}-params   # Option B only
  ec_mine subnetgroup:${CLUSTER_NAME}-subnets && aws elasticache delete-cache-subnet-group \
    --region $AWS_REGION --cache-subnet-group-name ${CLUSTER_NAME}-subnets
  local log_tags; log_tags=$(aws logs list-tags-for-resource --region $AWS_REGION --resource-arn \
    arn:$PART:logs:$AWS_REGION:$ACCT:log-group:$LG --output json --query 'tags') || { echo "SKIP $LG: cannot read tags"; }
  mine "$(echo "$log_tags" | jq -r '.Project // empty')" "$(echo "$log_tags" | jq -r '.created_by // empty')" $LG &&
    aws logs delete-log-group --region $AWS_REGION --log-group-name $LG
  local sec_tags; [ "$SECRET_ID" = "${CLUSTER_NAME}-cache-password" ] && sec_tags=$(aws secretsmanager describe-secret \
    --region $AWS_REGION --secret-id "$SECRET_ID" --query 'Tags' --output json) &&
  mine "$(echo "$sec_tags" | jq -r '.[] | select(.Key=="Project").Value // empty')" \
       "$(echo "$sec_tags" | jq -r '.[] | select(.Key=="created_by").Value // empty')" "$SECRET_ID" &&
    aws secretsmanager delete-secret --region $AWS_REGION --secret-id "$SECRET_ID"
  aws iam delete-role-policy --region $AWS_REGION --role-name <gpu-instance-role> --policy-name ${CLUSTER_NAME}-read-secret
  local sg_tags; sg_tags=$(aws ec2 describe-security-groups --region $AWS_REGION --group-ids $SG_ID \
    --query 'SecurityGroups[0].Tags' --output json) || { echo "SKIP $SG_ID: cannot read tags"; return 1; }
  mine "$(echo "$sg_tags" | jq -r '.[] | select(.Key=="Project").Value // empty')" \
       "$(echo "$sg_tags" | jq -r '.[] | select(.Key=="created_by").Value // empty')" $SG_ID || return 1
  retry 40 30 no_enis || { echo "STOP: interfaces still use $SG_ID"; return 1; }   # at most 20 minutes
  aws ec2 delete-security-group --region $AWS_REGION --group-id $SG_ID
}
teardown
```

`delete-secret` keeps the secret for 30 days (a new secret with that name fails meanwhile). Add `--force-delete-without-recovery` only after the builder confirms.

Leak check: each MUST return NotFound or an empty list.

```bash
aws elasticache describe-replication-groups --region $AWS_REGION --replication-group-id $CLUSTER_NAME
aws elasticache describe-user-groups --region $AWS_REGION --user-group-id ${CLUSTER_NAME}-ug
aws elasticache describe-users --region $AWS_REGION --user-id ${CLUSTER_NAME}-user
aws elasticache describe-cache-subnet-groups --region $AWS_REGION --cache-subnet-group-name ${CLUSTER_NAME}-subnets
aws ec2 describe-security-groups --region $AWS_REGION --group-ids $SG_ID
aws logs describe-log-groups --region $AWS_REGION --log-group-name-prefix /elasticache/${CLUSTER_NAME} --query 'logGroups[].logGroupName'
```
