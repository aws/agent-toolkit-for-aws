# Aurora serverless — Core Concepts

## Aurora Capacity Units (ACU)

- 1 ACU ≈ 2 GiB memory + corresponding CPU and networking
- Range: **0.5 to 256 ACU per instance**, in **0.5 ACU increments** (min/max configured at the cluster level; each instance scales independently within that range — a 3-instance cluster can consume up to 768 ACU total)
- Available for the Aurora PostgreSQL-Compatible Edition

## Scaling Behavior

- Scales **continuously** (not in steps) based on CPU, connections, and available memory
- Scale-up: near-instant (seconds), no connection disruption
- Scale-down: continuous and granular (capacity re-evaluated every second; scales down when current capacity exceeds load). The scale-down rate is governed by current capacity, not a fixed cooldown — no "~15 min cooldown" applies to Aurora serverless (v2). (The 15-min cooldown belonged to the deprecated Aurora Serverless v1.) Certain features (global databases, Performance Insights, Enhanced Monitoring, CloudWatch Logs export, pg_audit, elevated max_connections) can hold capacity above minimum.

## Scale-to-Zero (Auto-Pause)

**Supported versions:**

- Aurora PostgreSQL: 16.3+, 15.7+, 14.12+, 13.15+

**Incompatible with:** RDS Proxy, logical replication (`wal_level=logical`), Global Database (primary), Zero-ETL, Babelfish

**Trigger:** 0 user connections for the configured timeout. Aurora background processes keep CPU at ~8-10% even when idle — this is normal and does not prevent pause.

**Resume latency:** ~15s if paused <24h, ~30s if paused >24h.

## ACU Sizing from Provisioned Instances

```
weighted_cpu = (P95_CPU × 0.95 + Max_CPU × 0.05) / 100
raw_acu = weighted_cpu × vCPU_count × family_ratio
estimated_acu = round_up_to_nearest_0.5(raw_acu)
```

**Family ratios** (ACU per vCPU):

| Family | Ratio | Reason |
|--------|-------|--------|
| r-series (r6g, r7g, r8g) | 4 | Memory-optimized |
| m-series (m5, m6g) | 2 | General-purpose |
| t-series (t3, t4g) | 2 | Burstable |
| c-series (c5, c6g) | 1 | Compute-optimized |

## Min/Max ACU Configuration

**Minimum ACU** — covers:

1. Average CPU load (prevents scaling churn)
2. Connection memory floor: ~10 MB per connection → 100 connections ≈ 0.5 ACU
3. Working set floor (advisory): 1 GiB working set ≈ 0.5 ACU. Setting min below this trades cost for occasional I/O latency spikes on scale-up.

Formula: `min_acu = MAX(0.5, avg_cpu_acu, connection_acu_floor)`

**Maximum ACU** — covers peaks with headroom (per instance):

- `max_acu = MIN(peak_acu × 1.3, 256)`
- Ensure max ≥ typical × 1.5 for burst capacity
- If per-instance peak exceeds 256 ACU, workload exceeds serverless capacity on a single instance
- Total cluster peak ACU = per-instance peak × number of instances

## Pricing (us-east-1)

| Component | Standard | I/O-Optimized |
|-----------|---------|---------------|
| ACU-Hour | $0.12 | $0.156 (30% premium) |
| Storage ($/GiB-month) | $0.10 | $0.225 |
| I/O requests | $0.20/million | Included |

Monthly cost:

```
compute = estimated_acu × $0.12/ACU-Hr × 730 hours
storage = storage_gib × $0.10/GiB-month   (Standard; × $0.225/GiB-month for I/O-Optimized)
monthly = compute + storage
```

**Commitment discounts:** Database Savings Plans (1-year) cover serverless ACU. Reserved Instances do NOT apply to serverless.
