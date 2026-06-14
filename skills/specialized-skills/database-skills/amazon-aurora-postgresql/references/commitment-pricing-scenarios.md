# Commitment Pricing Decision Scenarios

Match the user's workload to one of these patterns, then recommend accordingly.

## Scenario A: Steady 24/7 Production on a Fixed Family

**Example**: e-commerce backend on `db.r7g.2xlarge`, two readers + one writer, running 24/7 for the last 2 years, no plan to migrate.

**Recommendation**: 3yr All-Upfront RI for the writer and baseline readers. Highest savings (~55-60% off on-demand).

**Watch out**: If you might migrate to r8g before the term ends, the RI doesn't transfer — you'd be paying for unused r7g capacity. In that case, 1yr RI or DSP is safer.

## Scenario B: Steady Production but Want Flexibility

**Example**: Stable workload, but the team is actively evaluating newer instance generations and may switch within 12-18 months.

**Recommendation**: 1yr DSP. Covers Gen-7 and newer Aurora instance families (does NOT cover r6g/r5 or older — use RIs for those). Up to ~20% discount on provisioned instances (up to ~35% on serverless). Family-agnostic within the Gen-7+ set; you keep the freedom to switch generations or move to serverless mid-term.

## Scenario C: Highly Variable Workload (Provisioned)

**Example**: Batch processing jobs that run 8 hours/day, 5 days a week. Effective utilization ~24%.

**Recommendation**: Stay on-demand, or consider switching to Aurora serverless. RI break-even is ~40-50% utilization — below that, commitments cost more than on-demand. If a migration to serverless is viable, the auto-scale-to-zero benefit often beats any commitment.

## Scenario D: Aurora serverless

**Example**: Aurora serverless cluster, min 2 ACU / max 32 ACU, averaging 6 ACU over the month.

**Recommendation**: RIs don't apply. Compare 1yr DSP (on the average ACU commitment) vs on-demand. DSP typically saves 20-30% on ACU-hours. Only commit to the baseline ACU level you're confident will be consumed 24/7 — the hourly $/hr commitment bills whether you use it or not.

## Scenario E: Mixed Fleet Across Families

**Example**: 10 clusters, mix of r6g (legacy), r7g (new), and serverless.

**Recommendation**: Hybrid.

- RI on the r6g instances (DSP doesn't cover r6g)
- DSP covers the r7g clusters AND the serverless ACU usage
- Migrate r6g → r7g over time, shift more commitment to DSP

Model each segment separately in the analyzer. A single account-wide DSP can span the new-gen provisioned + serverless portions, while RIs cover the legacy fleet.

## Scenario F: I/O-Optimized Cluster

**Example**: Production cluster on `db.r7g.4xlarge` using Aurora I/O-Optimized (30% compute premium).

**Recommendation**: Both RI and DSP can discount I/O-Optimized compute. RIs apply to the full I/O-Optimized rate, but I/O-Optimized consumes ~30% more normalized units per hour than Aurora Standard, so to fully cover an I/O-Optimized cluster with RIs you must purchase ~30% more reserved units (or rely on RI size flexibility). DSP covers I/O-Optimized ACU/compute usage automatically without that extra step and stays family-agnostic, which is often simpler for I/O-Optimized fleets — run the numbers; the analyzer accounts for the 1.3x factor when you pass `--io-optimized`.

## Scenario G: Workload Planned for Retirement / Migration

**Example**: App being migrated off Aurora to DynamoDB / Redshift within 6-12 months.

**Recommendation**: No commitment. RI and DSP are use-it-or-lose-it for the full term. The break-even point on a 1yr commitment assumes full-term usage; shutting down at month 8 wastes 4 months of commitment.

## Quick Decision Tree

```
Is the cluster Aurora serverless?
├── YES → Only DSP. Compare DSP 1yr vs on-demand.
└── NO
    ├── Is utilization < 40%? → Stay on-demand (or move to serverless)
    ├── Is the instance family r6g / older?
    │   ├── YES → RI only (DSP doesn't cover). 1yr vs 3yr based on confidence.
    │   └── NO → Compare RI vs DSP. DSP if flexibility matters, 3yr RI if locked in.
    └── Is the cluster I/O-Optimized? → Lean DSP for simplicity; if using RI, buy ~30% more reserved units (or use size flexibility) since I/O-Optimized consumes 1.3x normalized units.
```

## Sizing the Commitment

Never commit to more than your **steady baseline**. A cluster that runs at 10 ACU most of the time but spikes to 40 should commit only to 10 ACU worth of DSP — the spikes can stay on-demand.

For RIs, commit to instances that run 24/7 (the writer always, long-lived readers). Do not RI a reader that's torn down during off-hours.
