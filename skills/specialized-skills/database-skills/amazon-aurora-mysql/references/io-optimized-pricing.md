# Aurora Storage Pricing — Standard vs I/O-Optimized

## Pricing Constants (us-east-1)

| Component | Standard | I/O-Optimized |
|-----------|----------|---------------|
| Storage ($/GiB-month) | $0.10 | $0.225 |
| I/O requests | $0.20 per million | $0 (included) |
| Compute multiplier | 1.0× | 1.30× (30% premium) |

Pricing varies by region. The analyzer script fetches live pricing from the AWS Pricing API when credentials are available; static constants above are the fallback.

## The 25% Breakeven Rule

Let:

- `C` = compute cost per month (Standard)
- `S` = storage GiB × $0.10
- `I` = I/O cost per month

Total Standard cost: `T_std = C + S + I`
Total I/O-Optimized cost: `T_io = 1.30·C + 2.25·S + 0` (no I/O)

Break-even (where `T_io = T_std`):

```
1.30·C + 2.25·S = C + S + I
0.30·C + 1.25·S = I
I / T_std = 0.30·C + 1.25·S over (C + S + I)
```

Empirically across typical Aurora workloads, this collapses to the simple rule: **if I/O cost is ≥ 25% of total cluster spend, switch to I/O-Optimized.**

AWS documents this same 25% threshold in their [Aurora storage documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Overview.StorageReliability.html).

## What Storage Type Does NOT Affect

- Performance — both configurations use the same distributed SSD cluster volume across 3 AZs
- Durability or availability — identical
- Instance types, engine versions, parameter groups, networking
- Aurora serverless ACU ranges — the 30% multiplier applies to ACU-hour pricing the same way

## Switching Between Storage Types

This skill executes the storage-type switch only after explicit user confirmation, with a downtime / 30-day-cooldown warning first (see instructions.md Task 5 — it is a "warn then execute" operation per SKILL.md safety guardrails):

- Switch is a cluster-level modification: `--storage-type aurora-iopt1` (for I/O-Optimized) or `aurora` (for Standard)
- Switching from Aurora Standard to Aurora I/O-Optimized is limited to once every 30 days. Switching from Aurora I/O-Optimized back to Aurora Standard can be done at any time (no 30-day limit)
- The switch is online (no downtime, no restart) for non-NVMe instance classes. Clusters with NVMe/Optimized Reads instances (r6gd, r8gd, r6id) require a restart with brief unavailability.
- Switch takes effect immediately for billing

## Commitment Pricing Interaction

- Reserved Instances apply to Aurora I/O-Optimized clusters in full, including the 30% premium. Aurora automatically accounts for the price difference: an I/O-Optimized instance consumes 30% more normalized RI units per hour than the same instance on Standard, so it burns down RI capacity ~1.3× faster. There is no portion forced to on-demand rates
- Database Savings Plans cover both Standard and I/O-Optimized compute
- If the user has RIs covering a provisioned fleet, those RIs still apply on I/O-Optimized. To fully cover the 30%-higher normalized-unit consumption, purchase roughly 30% additional RIs of the same instance family (size flexibility lets you round to whole units). No RI discount is forfeited
