# Aurora Commitment Pricing — Mechanics Deep Dive

## Reserved Instances (RI)

RIs are a **per-instance commitment** for provisioned Aurora. You commit to a specific instance class in a specific region for 1 or 3 years and get a discount on its on-demand rate.

### Payment Options

| Option | Upfront | Recurring | Term | Discount ceiling |
|--------|---------|-----------|------|------------------|
| No Upfront | $0 | Monthly fee | 1yr only | up to ~30% |
| Partial Upfront | ~50% of term | Lower monthly | 1 or 3yr | up to ~63% (3yr) |
| All Upfront | Full term cost | $0 | 1 or 3yr | up to ~66% (3yr) |

These are AWS-published **ceilings** (the up-to maxima). The per-scenario estimates in [mechanics.md](commitment-pricing-mechanics.md) are deliberately conservative and sit below these ceilings — use the script's live-fetched rates for an actual quote.

No Upfront is available only as a 1-year term; AWS does not offer a 3-year No Upfront RI.

Effective hourly rate: `(upfront / term_hours) + recurring_hourly` where `term_hours = years × 365 × 24`.

### Size Flexibility

An RI for one instance size in a family covers equivalent normalized units of other sizes. Example:

- 1× `db.r7g.2xlarge` RI can cover 2× `db.r7g.xlarge` OR 4× `db.r7g.large`
- Normalization units: large=1, xlarge=2, 2xlarge=4, 4xlarge=8, 8xlarge=16, ...

Size flexibility does NOT apply across families or generations. An r7g RI doesn't cover r8g, r6g, or m7g.

### What RI Doesn't Cover

- Aurora serverless (ACU pricing)
- Storage or I/O requests (no RI for storage in Aurora)

RIs **do** cover Aurora I/O-Optimized compute, but each I/O-Optimized instance consumes 1.3x the normalized RI units of the equivalent Aurora Standard instance. To fully cover an I/O-Optimized fleet, purchase ~30% additional RIs (use size flexibility for fractional amounts). Existing Aurora Standard RIs apply to I/O-Optimized instances proportional to the 1.3x consumption.

## Database Savings Plans (DSP)

DSP is a **$/hour account-wide commitment**. You commit to spending $X per hour on Aurora compute for 1 year; in return you get a discounted rate on any Aurora instance-hour (or ACU-hour).

### Key Properties

- Only 1-year term — no 3-year DSP
- Covers ALL Aurora compute: provisioned + Aurora serverless + I/O-Optimized premium
- Family-agnostic: one DSP covers r7g, r8g, c7g, etc. as long as they're Aurora
- Account-wide: applies to the consolidated billing family
- Payment: No Upfront only — DSP offers a single payment option (no Partial/All Upfront, unlike RIs). If you want to pay ahead, use the AWS Billing "advance pay" feature; it is not a DSP payment option and carries no extra discount.

### Coverage Limits

DSP only covers **latest-gen instance families**: r7g, r7i, r8g, r8gd, m7g, c7g, and similar. Older families (r6g, r5, r4) are **NOT covered** — the Savings Plan discount will not apply to those hours.

If your fleet runs on r6g, you have two choices:

1. Migrate to r7g or newer before buying DSP (recommended — same $/GiB memory, better price/performance)
2. Buy RIs for the r6g instances instead

### Typical Discount

1yr DSP discount vs on-demand depends on deployment type: up to ~20% for provisioned instances and up to ~35% for serverless (the 35% headline is the serverless ceiling). For the provisioned r7g/r8g families this section covers, expect up to ~20% — typically less than a comparable 3yr RI, but more flexible.

## Mutual Exclusion

Only one discount applies per instance-hour. Priority:

1. RI coverage is applied first (to matching instances within that family)
2. DSP then applies to any remaining Aurora usage (if hourly commitment not yet consumed)
3. Anything above your DSP commitment bills at on-demand

You can mix RI + DSP strategically — e.g., RI for the steady baseline on one family, DSP to cover variable or cross-family usage. But the analyzer in this skill shows them as alternatives for clarity.

## Break-Even Considerations

RIs save money when the instance runs **more than ~40-60% of the term**. Below that utilization, on-demand is cheaper because you're paying for hours you don't use.

- 1yr No-Upfront: break-even around 50% utilization
- 3yr All-Upfront: break-even around 40% utilization (but you front the cash)

If you're planning to migrate, upgrade, or shut down the cluster within the term, the commitment often costs more than on-demand.

## I/O-Optimized Interaction

On I/O-Optimized clusters, compute is charged at 1.30× the standard rate. RI coverage applies to I/O-Optimized compute, but I/O-Optimized draws down RI normalized units 1.3x faster than Aurora Standard. To fully cover an I/O-Optimized cluster, buy ~30% more RIs (e.g., 10 db.r6g.large RIs → 13 needed → buy 3 more).

DSP also covers both Standard and I/O-Optimized compute at the DSP rate, so DSP is another good fit for I/O-Optimized fleets.

## Multi-AZ and Failover

RI/DSP cover the writer and reader instances. Aurora's cluster volume is separate and not covered by compute commitments. Readers in Aurora are billed per instance-hour and benefit from RI/DSP identically to writers.

## Aurora serverless Pricing

- RIs: not applicable
- DSP: covers ACU-hours for Aurora serverless
- DSP discount on ACU-hours is up to ~35% — typically LARGER than the up-to-20% discount on provisioned instances, making DSP especially valuable for serverless fleets

If a workload is truly variable (auto-pausing, scale-to-zero), DSP may not save money because you're committing to hourly $/hr even when the cluster is paused.
