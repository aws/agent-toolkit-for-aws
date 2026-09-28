# GCP Infrastructure Pricing Cache (source-side rates)

**Last updated:** 2026-07-19
**Region basis:** us-central1 (GCP list prices vary by region — note the region when the inventory is elsewhere)
**Sources:** cloud.google.com/sql/pricing, cloud.google.com/memorystore/docs/redis/pricing, cloud.google.com/compute/vm-instance-pricing, cloud.google.com/kubernetes-engine/pricing
**Currency:** USD · **Accuracy:** ±15% per rate; a baseline derived from these rates carries the Part 1 rung-2 label (±20–30%)

> Use this cache to derive the **current GCP monthly baseline** from discovered
> resource sizing when no billing export exists (estimate-infra.md Part 1
> rung 2). These are SOURCE-side (GCP) rates — never use them to price AWS
> services. Hours/month: 730.

---

## Cloud SQL (`google_sql_database_instance`) — Enterprise edition

| Component                                                                     | Rate                                                                                                                                                        |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| vCPU                                                                          | $0.0413 /vCPU/hour                                                                                                                                          |
| RAM                                                                           | $0.0070 /GB/hour                                                                                                                                            |
| SSD storage (`PD_SSD`, the default — assume it when `dataDiskType` is absent) | $0.170 /GB/month                                                                                                                                            |
| HDD storage (`PD_HDD`)                                                        | $0.090 /GB/month                                                                                                                                            |
| Backup storage                                                                | $0.080 /GB/month — backup volume is not in the capture; when backups are enabled, use provisioned disk GB as an upper bound, labeled "(backup upper bound)" |

**Tier decoding:**

- `db-custom-C-M` → C vCPUs, M MB of RAM (e.g. `db-custom-2-8192` = 2 vCPU + 8 GB)
- Shared-core flat rates: `db-f1-micro` ≈ $0.0105/hr, `db-g1-small` ≈ $0.0350/hr
- `availabilityType: REGIONAL` (HA) → **2×** the vCPU + RAM + storage subtotal
  (GCP bills the standby); `ZONAL` → 1×

Monthly = (C × 0.0413 + (M/1024) × 0.0070) × 730 × HA-multiplier + disk_GB × storage rate × HA-multiplier. The backup upper-bound line is NOT multiplied by the HA multiplier (backups are taken once, not per replica).

## Memorystore for Redis (`google_redis_instance`) — per GB-hour by capacity band

| Capacity (GB) | Basic  | Standard (HA) |
| ------------- | ------ | ------------- |
| 1–4 (M1)      | $0.049 | $0.077        |
| 5–10 (M2)     | $0.039 | $0.062        |
| 11–35 (M3)    | $0.031 | $0.050        |
| 36–100 (M4)   | $0.024 | $0.039        |
| >100 (M5)     | $0.021 | $0.034        |

Monthly = `memorySizeGb` × band rate (by `tier`) × 730.

## Compute Engine (`google_compute_instance`) — on-demand, us-central1

| Machine type  | $/hour  |
| ------------- | ------- |
| e2-micro      | 0.00838 |
| e2-small      | 0.01675 |
| e2-medium     | 0.03351 |
| e2-standard-2 | 0.06701 |
| e2-standard-4 | 0.13402 |
| e2-standard-8 | 0.26805 |
| n1-standard-1 | 0.0475  |
| n1-standard-2 | 0.0950  |
| n1-standard-4 | 0.1900  |
| n2-standard-2 | 0.0971  |
| n2-standard-4 | 0.1942  |

Persistent disk: pd-standard $0.040/GB-mo, pd-ssd $0.170/GB-mo, pd-balanced
$0.100/GB-mo. Machine type not in this table → do NOT guess; mark that resource
`"unpriced_gcp"` and add a warning.

## GKE (`google_container_cluster`)

- Cluster management fee: $0.10/cluster/hour (≈ $73/month; first zonal/autopilot
  cluster's fee is covered by the GCP free tier — note it, still count it)
- Standard mode nodes: price each node pool as `machineType` × node count via
  the Compute Engine table
- **Autopilot mode** (`autopilot.enabled: true`): pod-resource usage-based —
  NOT derivable from sizing; exclude (see below)

## NOT derivable from sizing — always exclude from a derived baseline

Usage-based services have no meaningful list-price-from-sizing derivation.
Exclude them from the rung-2 baseline total, name each in `warnings[]`, and
state that a billing export (rung 1) is the upgrade input:

- Cloud Run / Cloud Functions (request + vCPU-second billing)
- Pub/Sub, egress/network data processing
- Cloud Storage buckets (capture has no size), BigQuery, Spanner processing
- GKE Autopilot workloads

> **Staleness:** if today is more than 30 days after **Last updated** above,
> treat these rates as potentially stale and note it in the estimate output
> (same convention as `pricing-cache.md`); GCP list prices change rarely, but
> verify via cloud.google.com/products/calculator when precision matters.
