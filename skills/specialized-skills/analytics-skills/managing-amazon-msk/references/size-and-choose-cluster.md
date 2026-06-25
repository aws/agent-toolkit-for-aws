# Size and Choose an MSK Cluster

## For any sizing question, run [`scripts/msk_sizing.py`](../scripts/msk_sizing.py)

If the user is asking how many brokers, what instance size, what cost, etc., you **MUST** run [`scripts/msk_sizing.py`](../scripts/msk_sizing.py) before answering. Do not size by hand. Do not estimate from memory. Run the script from the skill directory with `python3`.

The script is the source of truth for broker counts and costs in this skill — it models broker capacity (EBS, NIC, partitions, PST, storage), AZ rounding, 1-AZ-down headroom, fan-out, Tiered Storage detection, EBS headroom, cross-AZ producer replication, optional cross-AZ consumer fetch, Express storage and data-in charges, and PST cost. It enumerates every Standard and Express instance size and returns a "Recommended pick per class" section naming the lowest-cost option per class within the broker quota.

Required workflow for any sizing answer:

1. Translate the user's inputs (avg/peak ingress, avg/peak egress, partitions, retention, primary retention, RF, PST, rack affinity) into the script's flags. If a value is missing, ask before guessing.
2. Run the script with `--explain`. Always pass `--retention-hours` and `--primary-retention-hours` — set them equal to disable Tiered Storage; set retention > primary to enable it.
3. Read the "Recommended pick per class" section. Quote those instance types, broker counts, bottlenecks, and total monthly costs back to the user verbatim — do not round, re-derive, or substitute your own numbers.
4. Use the `--explain` per-instance breakdown only to explain *why* the script picked what it did, never to override the recommendation.

You may suggest a larger size than the recommended pick only when (a) the user explicitly asks for one, or (b) the workload exceeds the broker quota and a quota increase is impractical. In both cases, name the recommended pick first and the alternative second.

```
python scripts/msk_sizing.py \
  --avg-data-in-mbs 100  --peak-data-in-mbs 500 \
  --avg-data-out-mbs 200 --peak-data-out-mbs 1000 \
  --num-partitions 1000 \
  --retention-hours 720  --primary-retention-hours 24 \
  --explain
```

Flag reference:

- `--explain` — print per-constraint analysis (which dimension is the bottleneck and by how much) and per-cost-factor breakdown (brokers, storage, Tiered Storage, Provisioned ST, Express data-in, cross-AZ) for every instance and the recommended pick per class. **Always include this flag.**
- `--broker-quota N` — change the per-cluster broker quota used to pick a "recommended" instance per class. Default is 60 (the MSK Provisioned default soft quota). The script picks the cheapest instance per class whose broker count fits within the quota.
- `--use-max-partitions` — size against the hard partition cap instead of the recommended cap (use only when the user accepts the operational risk).
- `--pst-per-broker-mbs` — apply a Provisioned Storage Throughput limit (4xlarge+ Standard only). Pass when the user mentions PST, gp3 provisioned throughput, or EBS write IO bottleneck.
- `--utilization-standard` / `--utilization-express` — override the headroom factor (defaults: 0.50 / 0.75). Do not change unless the user explicitly asks.
- `--no-rack-affined-consumers` — include consumer fetch traffic in the cross-AZ cost (use when consumers fetch from any leader rather than local-AZ replicas). Affects cost only, not broker count.

The narrative steps below explain what the script computes and when each constraint dominates. Use them to interpret `--explain` output, **never as a substitute for running the script**.

## Standard vs Express: Decision Framework

| Factor | Standard | Express |
|---|---|---|
| Storage | Customer-managed EBS (1 GiB - 16 TiB per broker) | Fully managed, pay-as-you-go, unlimited |
| Throughput per broker | Depends on instance type + EBS volume type + provisioned throughput | Defined per broker size (up to 500 MiB/s ingress); up to 3x more throughput per broker than equivalent Standard instance sizes |
| Maintenance windows | Yes — cluster enters MAINTENANCE state during patching | No maintenance windows — stays ACTIVE |
| Scaling speed | Hours for partition rebalancing | Up to 20x faster scaling |
| Storage management | Manual or auto-scaling EBS; optional tiered storage | No storage management required |
| Replication factor | Configurable (default 3) | Fixed at 3 |
| min.insync.replicas | Configurable (default 2) | Fixed at 2 |
| unclean.leader.election | Configurable (default true for non-tiered) | Fixed at false |
| Instance families | kafka.t3, kafka.m5, kafka.m7g | express.m7g only |
| Availability zones | 2 or 3 AZs | 3 AZs only |

**Choose Express for most workloads.** Express provides fully managed storage, no maintenance windows, faster scaling, up to 3x more throughput per broker, and managed best-practice defaults — making it the right choice for the majority of use cases.

**Choose Standard only when:** You need fine-grained control over broker configuration (e.g., custom `min.insync.replicas`, `unclean.leader.election`, replication factor other than 3) or you require a 2-AZ deployment.

## Sizing Standard Clusters

### Step 1: Determine throughput requirement

Calculate total ingress (write) throughput across all topics. Account for replication: total broker write IO = ingress × RF. For RF=3 and 100 MiB/s ingress, total write IO = 300 MiB/s across the cluster.

### Step 2: Choose instance type

Check the [MSK Best Practices for Standard brokers](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices.html) for current partition limits per Standard broker size. Larger instance types support more partitions.

For m5.4xl+ or m7g.4xl+, optimize throughput by tuning `num.io.threads` and `num.network.threads`. **Important**: Do not increase `num.network.threads` without first increasing `num.io.threads` — this can cause queue saturation.

| Instance Size | Recommended `num.io.threads` | Recommended `num.network.threads` |
|---|---|---|
| m5.4xlarge / m7g.4xlarge | 16 | 8 |
| m5.8xlarge / m7g.8xlarge | 32 | 16 |
| m5.12xlarge / m7g.12xlarge | 48 | 24 |
| m5.16xlarge / m7g.16xlarge | 64 | 32 |
| m5.24xlarge | 96 | 48 |

### Step 3: Calculate number of brokers

Divide total write IO by per-broker throughput capacity. Per-broker throughput is limited by the lowest of: EBS volume throughput, EC2-to-EBS network bandwidth, and EC2 egress bandwidth. **The broker count must be a multiple of the number of AZs (2 or 3).** Round up to the next valid multiple to ensure even partition distribution across availability zones.

**EBS throughput is often the bottleneck.** Default GP2/GP3 volumes cap at 250 MiB/s. For higher throughput, enable provisioned storage throughput (GP3) on broker sizes `kafka.m5.4xlarge`+ or `kafka.m7g.2xlarge`+. Check the [MSK storage throughput documentation](https://docs.aws.amazon.com/msk/latest/developerguide/msk-provision-throughput-management.html) for current max provisioned throughput per broker size.

Without provisioned throughput, a broker with RF=3 and 83 MiB/s client ingress already hits the 250 MiB/s ceiling (83 × 3 = 249 MiB/s write IO). Factor this into your broker count calculation. See [manage-storage.md](manage-storage.md) for provisioning details.

**Pair PST with `num.replica.fetchers`.** Provisioned storage throughput does not deliver its full benefit until you also raise `num.replica.fetchers` from the default of 2. Both changes must be in effect for the cluster to reach the new throughput target. AWS recommends ([source](https://docs.aws.amazon.com/msk/latest/developerguide/msk-provision-throughput-management.html#provisioned-throughput-config)):

| Broker size | `num.replica.fetchers` |
|---|---|
| kafka.m5.4xlarge | 4 |
| kafka.m5.8xlarge | 8 |
| kafka.m5.12xlarge | 14 |
| kafka.m5.16xlarge | 16 |
| kafka.m5.24xlarge | 16 |

For M7g sizes, use the value for the equivalent M5 size as a starting point. After flipping PST on, expect a transitional period (up to 24 hours; ~6 hours per fully utilized 1 TiB volume) where the new throughput ramps in.

**Important**: Maintain CPU utilization (CpuUser + CpuSystem) under 60% to retain headroom for operational events. For a precise per-instance broker count and cost breakdown, run [`scripts/msk_sizing.py`](../scripts/msk_sizing.py) with `--explain` (see top of this document). The [MSK Sizing and Pricing spreadsheet](https://view.officeapps.live.com/op/view.aspx?src=https%3A%2F%2Fdy7oqpxkwhskb.cloudfront.net%2FMSK_Sizing_Pricing.xlsx) is an alternative for offline what-if analysis.

### Step 4: Size EBS storage

Calculate: `client_ingress_per_broker × retention_seconds × RF` for each broker, where `client_ingress_per_broker` is the client write rate divided by broker count (excluding replication). Add 20% headroom. Maximum 16,384 GiB per broker. Enable auto-scaling with utilization target of 50-60%.

## Sizing Express Clusters

### Step 1: Determine throughput requirement

Calculate ingress AND egress separately. **Egress includes all consumer groups**: if 5 consumer groups each read the full stream, egress = 5 × ingress. This read amplification is the primary sizing driver for Express.

### Step 2: Choose broker size and count

Check the [MSK Express broker quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html#msk-express-quota) for current per-broker throughput limits (sustained and maximum) per Express broker size. Each size has a sustained ingress/egress threshold (no degradation) and a maximum quota (hard throttle).

Size using the **sustained performance** values. If throughput exceeds sustained limits, you may experience degraded performance. If it reaches the maximum quota, MSK will throttle client traffic.

Divide total required ingress/egress by per-broker sustained limits. Use whichever dimension (ingress or egress) requires more brokers. **The broker count must be a multiple of 3 (Express requires 3 AZs).** Round up to the next multiple of 3.

Run [`scripts/msk_sizing.py`](../scripts/msk_sizing.py) with `--explain` to get the precise broker count, bottleneck, and cost breakdown across every Express size. The "Recommended pick per class" section names the lowest-cost Express size that fits within the broker quota.

**Example**: 100 MiB/s ingress, 5 consumer groups → 500 MiB/s egress. Using express.m7g.2xlarge (125 MiB/s sustained egress): 500/125 = 4 brokers minimum → round up to **6 brokers** (next multiple of 3).

### Step 3: Check partition limits

Check the [MSK Express broker quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html#msk-express-quota) for current partition limits per Express broker size. Larger Express broker sizes support more partitions. Ensure your total partition count (including replicas — always 3× on Express) stays below the recommended limit for your broker size.

### Step 4: No storage sizing needed

Express storage is fully managed and pay-as-you-go. No provisioning required.

### Partition reassignment on Express

Express clusters use **Intelligent Rebalancing** by default, which automatically manages partition distribution across brokers. When Intelligent Rebalancing is enabled, you cannot manually reassign partitions using `kafka-reassign-partitions.sh`. Manual partition reassignment is only available if Intelligent Rebalancing is disabled. If you need to redistribute partitions after adding brokers, either rely on Intelligent Rebalancing or disable it first and use the manual tool (limit to 20 partitions per reassignment call).

## Connection Limits

| Dimension | Standard | Express |
|---|---|---|
| Max TCP connections per broker (IAM) | 3000 | 3000 |
| Max TCP connection rate per broker (IAM) | 100/s (M5/M7g), 4/s (T3) | 100/s |
| Max TCP connections per broker (non-IAM) | No enforced limit | No enforced limit |

## Account and Cluster Limits

Check the [MSK Provisioned quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html#msk-provisioned-quota) for current account-level and per-cluster broker limits. These are adjustable via quota increase requests.
