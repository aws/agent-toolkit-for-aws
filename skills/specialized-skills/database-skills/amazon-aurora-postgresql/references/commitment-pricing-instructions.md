# Aurora Commitment Pricing Workflow

Estimate monthly cost savings from Aurora Reserved Instances (RI) and Database Savings Plans (DSP) for one cluster, a fleet, or user-supplied workloads (including Aurora serverless). Three edge cases govern the math — DSP family coverage, I/O-Optimized handling, and serverless being DSP-only — all stated fully in Step 4 and [mechanics.md](commitment-pricing-mechanics.md). Purchases are blocked — see SKILL.md Safety guidance. Execute commands via the AWS MCP server when connected (sandboxed, audited); else use the AWS CLI or shell.

## When This Applies

User mentions: Reserved Instance, RI, Savings Plan, DSP, commitment pricing, No/Partial/All Upfront, 1-year vs 3-year, or whether a commitment is worth buying.

## Critical edge case: cluster has no DB instances (`skipped: true`)

**Before running ANY analysis on a specific cluster, check whether it has DB instances attached.** If `aws rds describe-db-clusters --db-cluster-identifier <id>` returns an empty `DBClusterMembers: []` array, OR the analyzer returns `skipped: true`, the cluster EXISTS but has no compute — you CANNOT run a commitment-pricing analysis on it.

See **[skipped-cluster.md](commitment-pricing-skipped-cluster.md)** for the cluster-name heuristic (treat `empty` / `no-instances` / `limitless` identifiers as skipped), the causes (paused, mid-migration, Aurora Limitless), the **required response template**, and the **MUST NOT** guardrails.

## Tasks

### 1. Acquire Workload Parameters

Modes:

- **Live single-cluster**: cluster identifier, region.
- **Live fleet**: region.
- **Offline — provisioned**: instance type, number of instances, region, optional `--io-optimized` flag.
- **Offline — Aurora serverless**: average ACU (steady baseline), region, optional `--io-optimized` flag.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST detect Aurora serverless clusters in live mode and warn the user — only DSP applies; RIs do not
- You MUST warn that Database Savings Plans bill the committed hourly rate continuously, including during auto-pause periods — the user pays the committed rate even when the cluster is scaled to zero ACU
- You MUST recommend sizing the DSP commitment at or below average ACU usage to avoid overpaying during low-usage or auto-pause periods
- You MUST confirm captured parameters before running the analyzer
- You SHOULD ask about the user's confidence horizon (1 vs 3 years) — it shapes the recommendation

### 2. Run the Analyzer

**Constraints:**

- You MUST use the script; RI and DSP math (including I/O-Optimized premium allocation) is non-trivial and must be handled consistently
- You MUST pass `--region` matching the workload's region
- You SHOULD prefer `--format json` when post-processing and `--format table` for direct user display

```bash
# Live single cluster
python scripts/commitment_pricing_analyzer.py --cluster my-cluster --region us-east-1

# Fleet
python scripts/commitment_pricing_analyzer.py --all --region us-east-1

# Offline provisioned
python scripts/commitment_pricing_analyzer.py offline \
  --instance db.r7g.2xlarge --num-instances 2 --region us-east-1

# Offline Aurora serverless (DSP only)
python scripts/commitment_pricing_analyzer.py offline \
  --serverless --avg-acu 8 --region us-east-1
```

### 3. Handle Skipped Clusters

The analyzer returns `skipped: true` for clusters with no DB instances (last writer/reader deleted, or Aurora Limitless) — no compute to commit to. An auto-paused scale-to-zero serverless instance still appears in the cluster and is analyzable; it is not an empty cluster.

**Constraints:**

- You MUST surface skipped clusters to the user with the script's `reason` string
- You MUST NOT attempt to force a commitment comparison on a skipped cluster
- You SHOULD direct Aurora Limitless users to its CU-based pricing model (outside RI/DSP scope)

### 4. Interpret Coverage Limits

**Constraints:**

- You MUST surface the script's `notes` array to the user — these are the most common misconceptions
- You MUST NOT claim DSP savings for an instance family the analyzer marks as ineligible (r6g, r5, and older) because DSP only covers latest-gen families
- You MUST explain the I/O-Optimized RI vs DSP math honestly — **both RI and DSP cover the full I/O-Optimized instance-hour price (base + 30% premium).** With RIs, an I/O-Optimized instance consumes ~1.3x the normalized RI units of the equivalent Standard instance, so you buy ~30% more RI units (size flexibility rounds fractions) to fully cover it — no portion is forced to on-demand. **DSP covers I/O-Optimized automatically and is family-agnostic**, so it needs no extra-unit calculation. That operational simplicity — not a coverage gap in RIs — is why DSP is often the easier commitment vehicle for I/O-Optimized fleets.

### 5. Present Results

Every comparison MUST include:

1. A row-by-row table: On-Demand, 1yr RI (best payment option), 3yr RI, 1yr DSP
2. Each row's monthly cost, savings vs On-Demand in both dollars AND percentage, upfront payment, and term length
3. A clear recommendation with the winning option and reasoning
4. Tradeoffs relevant to the decision (family lock-in, cash flow, upgrade plans)
5. The script's `notes` when present (DSP ineligibility, I/O-Optimized interaction)

**Constraints:**

- You MUST cite both dollar and percentage savings for each option
- You MUST show upfront payment when non-zero — it is a material cash-flow consideration
- You MUST NOT run any purchase API because this workflow estimates, not commits
- You MAY reference the AWS console path for users who want to proceed (RDS → Reserved Instances, or Billing → Savings Plans)

### 6. Scenario Guidance

For workload-pattern questions (steady vs variable, fleet mix, migration horizon), pull guidance from [scenarios.md](commitment-pricing-scenarios.md).

**Constraints:**

- You SHOULD match the user's workload to a scenario in the reference and explain why
- You MUST NOT recommend 3yr terms for workloads the user indicates may be retired or migrated within the term

## Troubleshooting

See [worked-examples.md §Troubleshooting](commitment-pricing-worked-examples.md#troubleshooting) for common failure modes: cluster-not-found, empty offerings, 3-year DSP requests, DSP-ineligible families, over-baseline commits, and max-capacity=0 auto-pause warnings.

## Deep-Dive References

Run the analyzer when shell is available; otherwise compute inline using the references below.

- [skipped-cluster.md](commitment-pricing-skipped-cluster.md) — no-compute heuristic, required response template, MUST NOT guardrails.
- [mechanics.md](commitment-pricing-mechanics.md) — DSP-vs-RI family coverage table, Aurora us-east-1 discount-rate table, savings formula, serverless + DSP gotchas. Offline rates: [../serverless-advisory/formulas-and-examples.md §Provisioned compute pricing](serverless-advisory-formulas-and-examples.md#provisioned-compute-pricing-table-on-demand-us-east-1-aurora-postgresql).
- [worked-examples.md](commitment-pricing-worked-examples.md) — three agent response patterns plus Troubleshooting.
- [basics.md](commitment-pricing-basics.md) — RI vs DSP mechanics, size flexibility, payment options, coverage limits.
- [scenarios.md](commitment-pricing-scenarios.md) — workload-pattern scenarios plus a decision tree.
