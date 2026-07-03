# RDS Commitment Pricing — Mechanics

## Reserved Instances (RI)

RIs are a per-instance commitment for RDS. You commit to a specific instance class, engine, and deployment type (Single-AZ or Multi-AZ) in a region for 1 or 3 years.

### Payment Options

| Option | Upfront | Recurring | Typical Discount (3yr) |
|--------|---------|-----------|------------------------|
| No Upfront | $0 | Monthly fee | ~40-50% |
| Partial Upfront | ~50% of term | Lower monthly | ~50-55% |
| All Upfront | Full term cost | $0 | ~55-60% |

### Size Flexibility

RDS RIs have size flexibility within the same instance family and engine. A `db.r7g.2xlarge` RI can cover 2× `db.r7g.xlarge`. Size flexibility does NOT apply across families or engines.

### Multi-AZ

Multi-AZ RIs are separate offerings. A Single-AZ RI does NOT cover a Multi-AZ instance. You must purchase the correct deployment type.

### What RI Doesn't Cover

- Storage or I/O (no RI for GP3/IO1 storage)
- Cross-engine: a MySQL RI doesn't cover PostgreSQL or MariaDB
- Cross-family: an r7g RI doesn't cover r6g or m7g

## Database Savings Plans (DSP)

DSP is a $/hour account-wide commitment. You commit to spending $X/hr on RDS compute; in return you get a discounted rate.

### Key Properties

- 1-year or 3-year terms available for RDS (unlike Aurora which is 1yr only)
- Covers RDS MySQL, MariaDB, and PostgreSQL compute
- Family-agnostic within eligible families
- Account-wide: applies to consolidated billing family
- Payment options: No Upfront, Partial Upfront, All Upfront

### Coverage Limits

DSP covers latest-gen families: r7g, r7i, r8g, r8gd, m7g, m7i, c7g, c7i, x8g. Older families (r6g, r5) are NOT covered.

### Typical Discount

1yr DSP: ~20-35%. 3yr DSP: ~35-50%. Less than equivalent RI terms but more flexible.

## Mutual Exclusion

Only one discount per instance-hour. Priority: RI first, then DSP, then on-demand.

You can mix RI + DSP: RI for steady baseline on one family, DSP for cross-family or variable usage.

## Break-Even

RIs save money when utilization exceeds ~40-60% of the term. Below that, on-demand is cheaper.

## RDS vs Aurora Differences

- RDS DSP supports both 1yr and 3yr terms (Aurora DSP is 1yr only)
- RDS has no Serverless option — all instances are provisioned
- RDS has no I/O-Optimized storage tier — no 30% compute premium to worry about
- RDS Multi-AZ RIs are separate from Single-AZ (Aurora handles this at the cluster level)
- RDS RI is engine-specific: MySQL RI ≠ PostgreSQL RI ≠ MariaDB RI
