# Inline Formulas and Coverage Tables (when you can't run the script)

Back to [instructions.md](commitment-pricing-instructions.md). See also [basics.md](commitment-pricing-basics.md) and [worked-examples.md](commitment-pricing-worked-examples.md).

Run `python3 scripts/commitment_pricing_analyzer.py ...` if shell is available; otherwise compute inline using the tables and rules below.

## DSP instance-family coverage

**Critical fact: Database Savings Plans do NOT cover every Aurora instance family.** RIs cover everything; DSP is restricted.

| Family | DSP eligible? | RI eligible? | If family is DSP-ineligible: |
|---|---|---|---|
| db.r6g | **NO** | Yes | RI is the only commitment option. Suggest r7g or r8g migration to unlock DSP flexibility. |
| db.r6i | **NO** | Yes | Same as r6g. |
| db.r5 | **NO** | Yes | Older generation; consider r7g migration for DSP + modern compute. |
| db.r4, db.r3 | **NO** | Yes | Legacy. RI only. Migration strongly advised for any long-term commitment. |
| db.r7g | **Yes** | Yes | DSP and RI both available. |
| db.r7i | **Yes** | Yes | DSP and RI both available. |
| db.r8g | **Yes** | Yes | Latest supported generation; DSP and RI both available. |
| db.t4g, db.t3 | **NO** | Yes | Burstable; not DSP-eligible. |
| Aurora serverless | **DSP only** | **NO** | RI does not apply to Aurora serverless. 1-year DSP is the only commitment option. |

When a user has an ineligible family (r6g, r6i, r5, r4, r3, or burstable), you MUST **definitively state** that DSP does not cover it — don't hedge with "may not be available." And you MUST recommend migration to r7g or r8g specifically as a way to unlock DSP flexibility, because size-flex within a DSP commitment is one of its biggest value props.

## Commitment discount rates (Aurora, us-east-1, approximate)

These are conservative scenario estimates and sit below AWS's published maxima (RDS/Aurora RIs reach up to ~45% on 1-year and up to ~66% on 3-year terms — see [Aurora pricing](https://aws.amazon.com/rds/aurora/pricing/)). Use live-fetched rates from the script when available.

| Commitment | Savings vs On-Demand | Payment options | Term | Upfront (for All-Upfront) |
|---|---|---|---|---|
| 1-year RI, No Upfront | ~20% | Monthly | 1 year | $0 |
| 1-year RI, Partial Upfront | ~25% | Half upfront + monthly | 1 year | ~50% of term cost |
| 1-year RI, All Upfront | ~30% (up to ~45%) | All upfront | 1 year | 100% of term cost |
| 3-year RI, No Upfront | — not available — | | | No Upfront RIs are 1-year only (AWS docs) |
| 3-year RI, Partial Upfront | ~45% | Half upfront + monthly | 3 years | ~50% of term cost |
| 3-year RI, All Upfront | ~55% (up to ~66%) | All upfront | 3 years | 100% of term cost |
| 1-year DSP (No Upfront only) | up to ~35% serverless / up to ~20% provisioned | Monthly | 1 year | $0 |
| **3-year DSP** | **— not available for Aurora —** | | | Use 3-year RI instead |

DSP has exactly **one** payment option — No Upfront, 1-year term. There is no Partial/All Upfront DSP. Customers wanting to prepay can use the separate AWS Billing "advance pay" feature, which does not change the DSP discount rate. No Upfront RIs are also 1-year only; only Partial Upfront and All Upfront are purchasable for the 3-year term.

**DSP size-flex advantage**: a DSP commit at (say) $100/hr covers *any* mix of DSP-eligible Aurora instance sizes/regions totalling ≤ $100/hr of effective on-demand spend. An RI is pinned to a specific family-size-region — you can re-sell but not reassign freely. For fleet-scale or uncertain-mix workloads, DSP flexibility is worth ~5–10% even when per-unit discount is lower than RI.

## Commitment savings formula

`committed_monthly_cost = on_demand_monthly_cost × (1 − discount_pct)`

Then `absolute_savings_per_month = on_demand_monthly − committed_monthly`, and `savings_pct = discount_pct × 100`.

For offline mode, use the on-demand rate from [../serverless-advisory/formulas-and-examples.md §Provisioned compute pricing](serverless-advisory-formulas-and-examples.md#provisioned-compute-pricing-table-on-demand-us-east-1) or the DSP for Aurora serverless section below. For live mode, the script pulls rates from the AWS Savings Plans + RI Offerings APIs.

## Aurora serverless + DSP: mechanics and gotchas

Aurora serverless is **DSP-only** (no RI). DSP for Aurora serverless has specific behavior the user needs to understand before committing:

1. **DSP bills the committed `$/hr` continuously, 24/7 — including when the cluster is auto-paused at 0 ACU.** If you commit $1/hr and the cluster scale-to-zeros at night, you are still billed $1/hr during that idle window. The commit is use-it-or-lose-it.
2. **Therefore, size the commitment to the steady baseline ACU, NOT peak.** If ACU ranges from 2 (overnight) to 20 (business hours), commit to something near the overnight baseline (2 ACU = ~$0.24/hr at us-east-1), and let the peaks run on-demand. Over-committing is a net loss.
3. **Both RI and DSP cover the full I/O-Optimized instance-hour price (base + 30% premium).** The difference is operational, not coverage. With **RIs**, an I/O-Optimized instance consumes ~1.3x the normalized RI units of the equivalent Standard instance, so to fully cover an I/O-Optimized fleet you buy ~30% more RI units of the same family (size flexibility rounds fractions to whole units) — e.g., 10 db.r6g.large Standard RIs → 13 needed → buy 3 more. No portion is left at on-demand. With **DSP**, coverage is automatic and family-agnostic, so there is no extra-unit step. For an I/O-Optimized fleet, **DSP is often the simpler commitment** because you don't have to size the +30% RI top-up — but both vehicles can fully discount the premium.
4. **DSP is 1-year only for Aurora** — 3-year DSP does not exist in this product.
5. RDS Proxy, binary logging (binlog) enabled, Global Database primary, and Zero-ETL all **disable scale-to-zero**, so if any of these are in play you don't need to worry about the auto-pause DSP waste — but the commit should still be sized to steady baseline, not peak, for the same waste-avoidance reason.
