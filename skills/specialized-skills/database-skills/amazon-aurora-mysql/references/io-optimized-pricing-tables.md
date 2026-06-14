# Aurora I/O-Optimized — Pricing & Data-Quality Tables

Companion to [instructions.md](io-optimized-instructions.md). Use these when you can't run the script and must compute inline. Worked examples are in [worked-examples.md](io-optimized-worked-examples.md).

## Pricing constants (us-east-1)

| Item | Standard | I/O-Optimized | Delta |
|---|---|---|---|
| Compute (per instance-hour) | See [../serverless-advisory/formulas-and-examples.md §Provisioned compute pricing](serverless-advisory-formulas-and-examples.md#provisioned-compute-pricing-table-on-demand-us-east-1) | **+30% on compute** | **Interaction with commitments:** RIs cover I/O-Optimized compute in full (including the 30% premium) — an I/O-Optimized instance consumes ~1.3x the normalized RI units of the equivalent Standard instance, so buy ~30% more RIs to fully cover; no portion is forced to on-demand. **DSP also discounts the full I/O-Optimized price (base + 30% premium) at the DSP rate** — a DSP commit on an I/O-Optimized cluster gets the DSP discount applied to the premium-inclusive price. See [../commitment-pricing/mechanics.md §Aurora serverless + DSP mechanics](commitment-pricing-mechanics.md#aurora-serverless--dsp-mechanics-and-gotchas) for the full treatment. |
| Storage | $0.10 per GiB-month | $0.225 per GiB-month | +125% storage rate |
| I/O | $0.20 per million requests | **$0 (free)** | All I/O is included |

These us-east-1 constants are only a fallback baseline. AWS does not publish a fixed regional multiplier, and Standard vs I/O-Optimized rates do not scale by an identical regional factor — storage, instance, and I/O rates each vary independently by region. For any non-us-east-1 region, the agent MUST use the analyzer's live per-region, per-component rates fetched from the AWS Pricing API rather than applying an estimated multiplier. Any offline cross-region approximation is a rough estimate with no AWS-published basis.

## Monthly cost formulas

**Standard total** = `(compute_$hr × 730 × num_instances) + (storage_GiB × $0.10) + (monthly_io_millions × $0.20)`

**I/O-Optimized total** = `(compute_$hr × 1.30 × 730 × num_instances) + (storage_GiB × $0.225) + 0 (no I/O charge)`

**I/O as % of Standard total** = `(monthly_io_millions × $0.20) / Standard_total × 100`

## Data-quality / lookback-window table

The storage-type switch has a **30-day cooldown that applies to the Standard → I/O-Optimized direction only** — switching to I/O-Optimized is limited to once every 30 days, while reverting to Standard is allowed at any time. Do NOT recommend a Standard → I/O-Optimized switch on thin data because that direction commits you to the outcome for a full month.

| Lookback window | Tag | Can recommend a switch? |
|---|---|---|
| < 3 days | `insufficient` | **NO.** Do not recommend either direction. Tell the user to wait. |
| 3–7 days | `short` | **NO.** Weekly patterns (weekday vs weekend I/O ratios often differ 2–3×) can flip the result. Also surface the 30-day cooldown on the Standard → I/O-Optimized direction as an additional reason to wait. Call the recommendation tentative; minimum wait: reach at least 14 days before acting. |
| 7–14 days | `adequate` | **Yes**, with caveat: if result is within ±3% of 25%, wait for 14+ days. |
| 14+ days | `good` | **Yes.** High-confidence. |

**Why weekly patterns matter:** most OLTP clusters see 40–60% lower I/O on weekends. A cluster that looks like 20% I/O on Mon–Thu can average 14% over a full week. The script's extrapolation over short windows does not capture this. Always wait at least one full week of observation, and recommend 14 days minimum before committing.

## `skipped: true` — what it means

The analyzer returns `skipped: true` when a cluster has **no DB instances** attached. This is NOT a "cluster not found" — the cluster exists, but there is no compute to price.

Common causes:

- **Paused Aurora cluster** — a cluster whose last reader/writer was actually deleted. Storage still exists. (Note: an Aurora serverless instance that has auto-paused at scale-to-zero stays in `DBClusterMembers` with status `available` and IS analyzable — it is not an empty cluster and is not skipped.)
- **(Not a zero-instance cause) Instance being replaced/rebooting** — an operation like a Blue/Green switchover or a `modify-db-instance` reboot does NOT empty `DBClusterMembers`; the instance is still listed as a member (just briefly in a `rebooting`/`replacing` state), so the cluster is NOT skipped for empty membership.

When the analyzer skips a cluster, you MUST:

1. Surface the `skipped: true` result verbatim with the `reason` string.
2. Name the likely cause (last instance deleted, paused, or mid-migration).
3. Offer appropriate next steps:
   - **Last instance deleted / paused**: resume the cluster (attach a writer), let it run for 14+ days, then re-run the assessment.
4. NOT attempt to force a comparison or include the cluster in fleet dollar totals.

## Troubleshooting

**"Cluster not found".** Wrong cluster ID or region. Verify with `aws rds describe-db-clusters --region <region>`.

**CloudWatch returns zero I/O data.** Cluster is new, paused, or wrong region. Confirm with `aws cloudwatch list-metrics --namespace AWS/RDS --dimensions Name=DBClusterIdentifier,Value=<cluster>`. If genuinely idle, Standard is correct.

**Live pricing fetch fails (ExpiredToken / AccessDenied).** Refresh credentials. Script falls back to static us-east-1 pricing; flag that caveat.

**"Skipped — no DB instances".** A paused cluster or one whose last reader/writer was deleted (an empty cluster still incurs storage charges). Restore or add an instance before assessing the Standard vs I/O-Optimized decision. (Note: Aurora Limitless Database — which is locked to I/O-Optimized — is an Aurora PostgreSQL-only capability and does not apply to Aurora MySQL.)

**Result close to the 25% threshold (22–28%).** May flip month-to-month. Monitor 1–2 months before committing, especially if seasonal.
