# RDS Commitment Pricing Decision Scenarios

## Scenario A: Steady 24/7 Production, Fixed Family

**Example**: RDS MySQL on `db.r7g.2xlarge`, Multi-AZ, running 24/7 for 2+ years.

**Recommendation**: 3yr All-Upfront RI (Multi-AZ offering). Highest savings (~55-60%).

**Watch out**: If migrating to r8g before term ends, RI doesn't transfer. Use 1yr RI or DSP instead.

## Scenario B: Steady Production, Want Flexibility

**Example**: Stable workload, but team may switch instance generations within 12-18 months.

**Recommendation**: 1yr DSP. Covers any eligible RDS instance family. ~20-35% discount, family-agnostic.

## Scenario C: Variable Workload

**Example**: Batch jobs running 8 hours/day, 5 days/week. ~24% utilization.

**Recommendation**: Stay on-demand. RI break-even is ~40-50% utilization. Below that, commitments cost more.

## Scenario D: Mixed Fleet Across Engines

**Example**: 5 RDS MySQL instances + 3 RDS PostgreSQL instances, mix of r6g and r7g.

**Recommendation**: Hybrid approach.

- RI for r6g instances (DSP doesn't cover r6g) — engine-specific RIs
- DSP covers r7g instances across both MySQL and PostgreSQL
- Migrate r6g → r7g over time, shift more to DSP

## Scenario E: Multi-AZ with Read Replicas

**Example**: RDS PostgreSQL Multi-AZ primary + 2 Single-AZ read replicas.

**Recommendation**:

- Multi-AZ RI for the primary (must be Multi-AZ offering)
- Single-AZ RI for each read replica (separate offerings)
- Or DSP to cover all three with one commitment

## Scenario F: Planned Migration to Aurora

**Example**: RDS MySQL being migrated to Aurora MySQL within 6-12 months.

**Recommendation**: No RDS commitment. RI and DSP are use-it-or-lose-it. If you buy an RDS MySQL RI and migrate to Aurora, the RI is wasted. Wait until post-migration, then evaluate Aurora commitment options.

## Quick Decision Tree

```
Is utilization < 40%?
├── YES → Stay on-demand
└── NO
    ├── Is the instance family r6g / older?
    │   ├── YES → RI only (DSP doesn't cover). Engine-specific.
    │   └── NO → Compare RI vs DSP
    ├── Planning to migrate to Aurora?
    │   ├── YES → No commitment (RI doesn't transfer cross-engine)
    │   └── NO → Continue
    ├── Want flexibility across families?
    │   ├── YES → DSP (1yr or 3yr)
    │   └── NO → 3yr RI for max savings
    └── Multi-AZ?
        ├── YES → Must buy Multi-AZ RI offering (not Single-AZ)
        └── NO → Single-AZ RI
```

## Sizing the Commitment

Never commit to more than your steady baseline. Do not RI a read replica that's torn down during off-hours. For DSP, commit to the 24/7 baseline $/hr and leave peaks on-demand.
