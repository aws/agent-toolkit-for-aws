# Aurora serverless — Inline Formulas and Pricing Tables

Companion to [instructions.md](serverless-advisory-instructions.md). Use this when you can't run `scripts/acu_calculator.py` and must compute inline, or when you need the pricing tables. Worked examples are in [worked-examples.md](serverless-advisory-worked-examples.md).

## Inline Formulas (when you can't run the script)

Run `python3 scripts/acu_calculator.py estimate --flag...` if shell is available. Otherwise compute inline using these formulas and the tables below.

### ACU sizing formula

Aurora serverless sizes between **min_ACU** and **max_ACU**. One ACU ≈ 2 GiB memory + proportional CPU. Memory/CPU ratios differ by original provisioned family:

| Family | Memory per ACU (GiB) | ACU coefficient (vCPU → ACU) | Notes |
|---|---|---|---|
| r6g, r7g, r8g (memory-optimized) | 2.0 | 4 | Aurora's default "r-ratio" — 1 vCPU at sustained full CPU ≈ 4 ACU |
| t3, t4g (burstable) | 1.0 | 2 | Rarely right-sized for serverless; recommend provisioned if workload is steady |
| x2g (memory-extreme) | 4.0 | 4 | High memory-per-ACU; good candidate when working set is the bottleneck |

**min_ACU** (steady baseline) = `max(0.5, cpu_avg% / 100 × vCPUs × ACU_coef)`, rounded up to nearest 0.5

**peak_ACU** (raw burst) = `cpu_max% / 100 × vCPUs × ACU_coef`, rounded up to nearest 0.5

**typical_ACU** (weighted) = `(0.95 × cpu_p95% + 0.05 × cpu_max%) / 100 × vCPUs × ACU_coef`, rounded up to nearest 0.5

**max_ACU** (recommended ceiling) = `max(round_up(peak_ACU × 1.30), round_up(typical_ACU × 1.50))`, capped at 256. Note peak_ACU and max_ACU are distinct: peak is the raw burst, max adds headroom — e.g. peak 12.0 → max 16.0.

If `cpu_avg` is not given, estimate as `cpu_avg ≈ 0.60 × cpu_p95`.

If working_set_GiB is supplied, enforce **min_ACU ≥ working_set_GiB / 2.0** (memory floor) — the min must provision at least as much RAM as the working set, or page-cache churn will negate the sizing.

### ACU pricing table (on-demand, us-east-1)

| Region | ACU/hour (Aurora serverless) | Notes |
|---|---|---|
| us-east-1, us-east-2, us-west-2 | $0.12 | Standard Aurora regions |
| eu-west-1, eu-central-1 | $0.14 | EU |
| ap-northeast-1 | $0.15 | APAC |
| ap-southeast-1, ap-southeast-2 | $0.20 | APAC |
| me-south-1 | $0.15 | Higher-tier regions |
| af-south-1 | $0.16 | Higher-tier regions |
| sa-east-1 | $0.25 | Higher-tier regions |

**Monthly compute (Aurora serverless)** = `ACU × ACU_rate × 730 hours × num_instances`.

For a range estimate, report: low = `min_ACU × rate × 730`, mid = `typical_ACU × rate × 730`, high = `max_ACU × rate × 730`.

### Provisioned compute pricing table (on-demand, us-east-1)

Use this to compare against Aurora serverless cost. Multiply by ~1.15 for us-west-2/eu-west-1, ~1.25 for APAC.

| Instance | vCPU | RAM (GiB) | $/hr (us-east-1) | $/mo (730h) |
|---|---|---|---|---|
| db.r6g.large | 2 | 16 | $0.260 | $190 |
| db.r6g.xlarge | 4 | 32 | $0.519 | $379 |
| db.r6g.2xlarge | 8 | 64 | $1.038 | $758 |
| db.r6g.4xlarge | 16 | 128 | $2.076 | $1,515 |
| db.r6g.8xlarge | 32 | 256 | $4.152 | $3,031 |
| db.r7g.large | 2 | 16 | $0.276 | $201 |
| db.r7g.xlarge | 4 | 32 | $0.553 | $404 |
| db.r7g.2xlarge | 8 | 64 | $1.106 | $807 |
| db.r7g.4xlarge | 16 | 128 | $2.211 | $1,614 |
| db.r7g.8xlarge | 32 | 256 | $4.422 | $3,228 |
| db.r8g.large | 2 | 16 | $0.276 | $201 |
| db.r8g.xlarge | 4 | 32 | $0.552 | $403 |
| db.r8g.2xlarge | 8 | 64 | $1.104 | $806 |
| db.r8g.4xlarge | 16 | 128 | $2.208 | $1,612 |
| db.r8g.8xlarge | 32 | 256 | $4.416 | $3,224 |
| db.t4g.medium | 2 | 4 | $0.073 | $53 |
| db.t4g.large | 2 | 8 | $0.146 | $107 |

Rates are Aurora On-Demand (Aurora Standard, Single-AZ) in us-east-1 (static fallback values). Aurora MySQL and Aurora PostgreSQL compute rates are identical for these instance classes. These are fallback values for inline estimation only — the `acu_calculator.py` script fetches live pricing from the AWS Pricing API (or public bulk pricing CSV) at runtime when available.

### Storage and I/O pricing (both Standard and serverless, us-east-1)

| Item | Standard $/unit | Notes |
|---|---|---|
| Storage | $0.10 per GiB-month | Charged on consumed, not allocated |
| I/O | $0.20 per million request | Aurora Standard — see [../io-optimized/instructions.md](io-optimized-instructions.md) for when I/O-Optimized breakeven applies |
| Backup storage | $0.021 per GiB-month | After 1× cluster size free |

Regional multiplier: us-west-2 / eu-west-1 ≈ 1.15×, APAC ≈ 1.25×.
