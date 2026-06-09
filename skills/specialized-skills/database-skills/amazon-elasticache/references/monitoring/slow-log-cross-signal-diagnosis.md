# Slow Log Cross-Signal Diagnosis

**When to use:** Intermittent latency spikes, customer-facing timeouts, or paged alerts where EngineCPUUtilization rose briefly on one node. Wants to identify which commands caused the spike, from which clients, against which keys. Node-based clusters with slow-log delivery enabled.
**When not needed:** Sustained latency (troubleshooting.md High Latency). Slow-log not enabled (set up via log-delivery.md). Serverless (slow log not available; use troubleshooting.md Throttling + CloudWatch latency metrics).

## Preconditions

| Deployment | Applicability |
|---|---|
| Serverless | Does not apply. SLOWLOG, CLIENT LIST, INFO commandstats all blocked. |
| Node-based | Full playbook. Slow-log delivery must be enabled (to CloudWatch Logs or Amazon Data Firehose). This playbook assumes CloudWatch Logs as the destination; if using Firehose, adapt the log-query steps accordingly. |

Verify slow-log delivery is configured (the log group name is user-specified, not a fixed path):

```bash
aws elasticache describe-replication-groups \
  --replication-group-id <replication-group-id> \
  --region <region> \
  --query 'ReplicationGroups[0].LogDeliveryConfigurations'
```

Look for an entry with `LogType: slow-log` and note the `DestinationDetails` (CloudWatch Logs log group name or Firehose stream name). If the destination is Firehose rather than CloudWatch Logs, the `aws logs filter-log-events` commands in Tier B will not apply; query your Firehose destination (e.g., S3, OpenSearch) instead.

**TLS note:** All `valkey-cli` examples in this playbook include `--tls`. Omit `--tls` if your cluster does not have transit encryption enabled.

### Command availability (node-based only)

| Command | Notes |
|---|---|
| SLOWLOG GET [count] | Read slow-log entries. Without a count argument, returns the latest 10 entries by default. Use `SLOWLOG GET -1` to retrieve all entries up to `slowlog-max-len` (default 128). |
| SLOWLOG LEN | Total entries stored. |
| COMMANDLOG GET \<count\> | Valkey 8.1+ only. Richer categorization (slow-command, large-reply, large-request). |
| INFO commandstats | Per-command call count, total microseconds, microseconds-per-call. |
| CLIENT LIST [TYPE \<type\>] | Enumerate clients. Parse for cmd=, addr=, age=, idle=, name=. |

---

## Tier A: Triage with CloudWatch

Pin the incident window before pulling logs. CloudWatch only, zero cluster impact.

### Step 1: Confirm the spike window

Query `EngineCPUUtilization` per node at 1-minute resolution:

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache --metric-name EngineCPUUtilization \
  --dimensions Name=CacheClusterId,Value=<node-id> \
  --start-time <incident-start> --end-time <incident-end> \
  --period 60 --statistics Maximum --region <region>
```

Identify the node and exact 5-minute window where CPU peaked.

**Stop condition:** If no node shows a CPU peak during the reported time range, the latency is not engine-thread-bound. Route to troubleshooting.md High Latency or Connection Spikes.

### Step 2: Confirm latency correlation

Query `SuccessfulReadRequestLatency` at p99 over the same window:

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache --metric-name SuccessfulReadRequestLatency \
  --dimensions Name=CacheClusterId,Value=<node-id> \
  --start-time <window-start> --end-time <window-end> \
  --period 60 --extended-statistics p99 --region <region>
```

P99 spike aligned with CPU spike confirms engine-bound nature.

### Step 3: Identify command-family signature

```bash
for family in StringBasedCmds HashBasedCmds ListBasedCmds SetBasedCmds SortedSetBasedCmds StreamBasedCmds; do
  aws cloudwatch get-metric-statistics \
    --namespace AWS/ElastiCache --metric-name $family \
    --dimensions Name=CacheClusterId,Value=<node-id> \
    --start-time <window-start> --end-time <window-end> \
    --period 60 --statistics Sum --region <region>
done
```

The family that spiked most sharply points to the data type of the slow command.

---

## Tier B: Narrow with slow-log correlation

### Step 1: Pull slow-log entries for the window

```bash
aws logs filter-log-events \
  --log-group-name <your-log-group-name> \
  --log-stream-name-prefix elasticache/<engine-name>/<cache-cluster-id> \
  --start-time <window-start-ms> --end-time <window-end-ms> \
  --region <region>
```

Replace `<your-log-group-name>` with the log group from the precondition check. Log stream names follow the format `elasticache/${engine-name}/${cache-cluster-id}/${cache-node-id}/${log-type}`.

Each entry includes: timestamp, duration (microseconds), client address (`ClientAddress`), and command name. Note: in delivered logs (CloudWatch Logs / Firehose), ElastiCache redacts key names and values, replacing them with `(N more arguments)` to avoid exposing sensitive data. To see full command arguments including keys, use `SLOWLOG GET` directly on the node. Sort by duration descending.

### Step 2: Cross-reference with INFO commandstats

```bash
valkey-cli -h <node-endpoint> -p 6379 --tls INFO commandstats
```

A command that appears repeatedly in the slow-log window AND has high usec_per_call in commandstats is the culprit.

**Stop condition:** If no command exceeds both signals, the spike is not from a recurring slow command. Route to hot-key-detection.md (single-key spike) or troubleshooting.md High Latency.

### Step 3: Identify the key pattern

In delivered logs (CloudWatch Logs / Firehose), key names are redacted. To identify key patterns, use `SLOWLOG GET` directly on the node, which returns full command arguments including keys:

```bash
valkey-cli -h <node-endpoint> -p 6379 --tls SLOWLOG GET 128
```

The first argument of most entries is the key. Group by first-argument prefix. A key or prefix appearing repeatedly is the target.

### Step 4: COMMANDLOG (Valkey 8.1+ only)

Check engine version first. COMMANDLOG is Valkey 8.1+ only. On older engines, skip this step.

```bash
valkey-cli -h <node-endpoint> -p 6379 --tls COMMANDLOG GET 128
```

Categories: `slow-command` (runtime), `large-reply` (oversized response), `large-request` (oversized argument). Tells you WHY a command was slow, not just that it was.

### Cost and impact

All Tier B operations are read-only and subsecond. 2-5 minutes of active querying per incident. Safe on production.

---

## Tier C: Verify with CLIENT LIST and key inspection

### Step 1: Identify the client

Slow-log entries include a `ClientAddress` field (e.g., `"ClientAddress": "10.0.1.42:50234"`). Match against CLIENT LIST:

```bash
valkey-cli -h <node-endpoint> -p 6379 --tls CLIENT LIST
```

Parse for matching `addr=`. The `name=` field identifies the app instance if CLIENT SETNAME is used. Recommend `CLIENT SETNAME <app-instance-id>` on every connection as a convention.

**Stop condition:** If no matching connection (already closed), fall back to VPC flow logs keyed to source IP:port. Do not spend more than 10 minutes on CLIENT LIST attribution alone.

### Step 2: Inspect the target key

```bash
valkey-cli -h <node-endpoint> -p 6379 --tls TYPE <key>
valkey-cli -h <node-endpoint> -p 6379 --tls MEMORY USAGE <key>
```

Cross-reference with big-key-hunter.md if the key is large.

### Step 3: Classify the root cause

| Slow-log signature | Tier C findings | Root cause |
|---|---|---|
| HGETALL key 50x in window | 5MB hash, client is batch job | Big-key read by batch job |
| KEYS pattern:* once | Script or admin operation | Blocking enumeration |
| LRANGE key 0 -1 30x | 100K-item list | Big-list without pagination |
| SORT key | Large sortable collection | O(N log N) sort on prod path |
| EVAL script 100x | High per-call microseconds | Lua script complexity |
| SUBSCRIBE + blocked client | cmd=subscribe age>3600 | Long-held pub/sub subscriber |

---

## Remediation

| Root cause | Fix |
|---|---|
| Big-key read by batch job | Move batch to read replica, paginate (HSCAN/LRANGE with bounds), split value |
| Blocking enumeration (KEYS, SMEMBERS on large sets) | Replace with SCAN/SSCAN/HSCAN/ZSCAN |
| Big-list O(N) reads | Paginate with cursor or bounded LRANGE |
| Expensive Lua script | Profile, reduce allocations, use EVALSHA, move logic to app |
| Long-held blocking commands | Adjust timeout, pool blocked connections separately |
| Operator mistake | Document anti-pattern in team runbooks |

---

## Cross-links

- Root cause is a big key: `big-key-hunter.md`
- Root cause is a hot key (same key, high access): `hot-key-detection.md`
- Concentrated on one shard: `slot-memory-imbalance-detection.md` or `hot-key-detection.md`
- Enabling slow-log delivery: `log-delivery.md`
- Alarm patterns for catching spikes: `alarm-packs.md`
