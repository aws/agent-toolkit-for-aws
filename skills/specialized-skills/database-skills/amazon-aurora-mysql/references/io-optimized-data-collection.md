# Data Collection for I/O-Optimized Assessment

## CloudWatch Metrics Used

The analyzer pulls these from the `AWS/RDS` namespace at cluster level:

| Metric | Statistic | Purpose |
|--------|-----------|---------|
| `VolumeReadIOPs` | Sum | Read I/O requests (billed ops) |
| `VolumeWriteIOPs` | Sum | Write I/O requests (billed ops) |
| `VolumeBytesUsed` | Average | Storage GiB (for storage cost) |

Dimension: `DBClusterIdentifier`. Metrics are pulled at 1-hour granularity and summed over the lookback window.

**Note on naming:** Despite the name "IOPs", `VolumeReadIOPs` and `VolumeWriteIOPs` report I/O **request counts per 5-minute period**, not per-second rates. The script normalizes them accordingly.

## Cluster Metadata from RDS API

`describe-db-clusters` and `describe-db-instances` provide:

- Current storage type (`storage_type`: `aurora` = Standard, `aurora-iopt1` = I/O-Optimized)
- Instance types in the cluster (to price compute correctly)
- Engine and version (for context, does not affect pricing math)
- Allocated storage (as a validation check against CloudWatch `VolumeBytesUsed`)

## Extrapolation for Short Windows

The analyzer extrapolates observed I/O to a 30-day (730-hour) month:

```
monthly_io = (observed_io / observed_hours) × 730
```

Minimum viable window: **7 days**. Below this, Aurora workloads often miss a full weekly cycle (weekdays vs weekends can differ 3-5×), producing misleading extrapolations.

The script sets `data_quality` accordingly:

- `< 3 days`: `insufficient` — do not recommend a switch on this data
- `3-7 days`: `short` — recommendation flagged as tentative
- `7-14 days`: `adequate` — recommendation reliable
- `14+ days`: `good` — recommendation high-confidence

## Switch Cooldown: Another Reason to Wait for More Data

The 30-day limit on changing a cluster's storage type (via `modify-db-cluster --storage-type`) is **one-directional**: switching Standard (`aurora`) → I/O-Optimized (`aurora-iopt1`) is limited to **once every 30 days per cluster**, while reverting I/O-Optimized → Standard can be done **at any time** (no cooldown). So a premature switch *into* I/O-Optimized is not a 30-day cost lock-in — you can revert to Standard immediately. The real cost of churning is that, once you revert, you cannot re-enable I/O-Optimized again for another 30 days.

When the `data_quality` tag is `insufficient` or `short`, the cost of a bad decision is the one-way commitment in the Standard → I/O-Optimized direction: if you switch in on thin data and then want to switch in again after a better read of the workload, you are gated by the 30-day cooldown on that direction. Surface this cooldown to the user as part of the reasoning to wait. Do not describe the Standard → I/O-Optimized direction as freely repeatable; that direction is a meaningful commitment (reverting to Standard, by contrast, is always available).

## Handling Multi-Instance Clusters

Aurora I/O-Optimized pricing applies at the **cluster level**. Compute cost is the sum of all instance-hours in the cluster:

```
compute_monthly = Σ (instance_price_per_hour × 730) for each instance in cluster
```

The 30% premium multiplies the full compute cost. A cluster with one writer + two readers multiplies the premium by 3× the base instance cost.

## Reader-Only vs Writer-Heavy Clusters

I/O billing counts **all reads and writes across all instances in the cluster** — readers are billed for their reads. The analyzer sums CloudWatch volume I/O across the cluster, which already reflects this.

## Aurora serverless Clusters

For Aurora serverless, the analyzer uses observed ACU-hours from `ServerlessDatabaseCapacity` to compute compute cost. The 30% I/O-Optimized premium applies to the ACU-hour rate, same as provisioned.

## Offline Mode Inputs

When AWS credentials aren't available, the user provides:

- `--instance <type>` — e.g., `db.r6g.2xlarge`
- `--num-instances <N>` — total instances in the cluster
- `--storage-gib <N>` — cluster volume size
- `--monthly-io-millions <N>` — estimated monthly I/O requests in millions

The user can get monthly I/O from the Cost Explorer (filter on "Amazon Relational Database Service" + usage type containing `StorageIOUsage`) or from the AWS billing console line items.
