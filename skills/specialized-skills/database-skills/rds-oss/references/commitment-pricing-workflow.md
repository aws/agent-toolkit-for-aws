# RDS Commitment Pricing Workflow

Estimate monthly cost savings from RDS Reserved Instances (RI) and Database Savings Plans (DSP) for RDS MySQL, MariaDB, and PostgreSQL. Fetches live RI offerings and DSP rates from AWS Pricing and Savings Plans APIs. Read-only — never purchases commitments.

## When This Applies

User mentions: "should I buy a reserved instance / RI", "how much would a savings plan save", "compare 1-year vs 3-year", "RI vs DSP", "commitment pricing for RDS", "No Upfront / Partial Upfront / All Upfront", Multi-AZ pricing. Do NOT use this workflow for Aurora — Aurora has a separate commitment-pricing skill with different rules (Aurora DSP is 1yr-only; Aurora RIs interact with I/O-Optimized).

## Tasks

### 1. Acquire Workload Parameters

The analyzer supports two modes.

**Live single-instance:** DB instance identifier, region.
**Offline:** instance type, engine (`mysql`, `mariadb`, or `postgres`), number of instances, region, optional `--multi-az` flag.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST ask which engine (`mysql`, `mariadb`, or `postgres`) for offline mode
- You MUST confirm captured parameters before running the analyzer
- You SHOULD ask about the user's confidence horizon (1 vs 3 years)
- You MUST NOT default the engine — RDS RIs are engine-specific, and a wrong engine produces wrong numbers

### 2. Run the Analyzer

**Constraints:**

- You MUST use the script; RI and DSP math is non-trivial and combines multiple API surfaces
- You MUST pass `--region` and (for offline mode) `--engine` matching the workload
- You SHOULD pass `--format json` (the analyzer emits JSON) and present the results as a formatted table to the user

```bash
# Live single instance
python3 scripts/rds_commitment_pricing_analyzer.py --instance my-rds-db --region us-east-1

# Offline
python3 scripts/rds_commitment_pricing_analyzer.py --region us-east-1 offline \
  --instance-type db.r7g.2xlarge --engine mysql --num-instances 2

# Offline Multi-AZ
python3 scripts/rds_commitment_pricing_analyzer.py --region us-east-1 offline \
  --instance-type db.r7g.2xlarge --engine postgres --num-instances 1 --multi-az
```

### 3. Interpret Coverage Limits

**Constraints:**

- You MUST surface the script's `notes` array — these cover common misconceptions
- You MUST NOT claim DSP savings for instance families the analyzer marks as ineligible (r5, r6g, older). DSP only covers latest-generation families (r7g, r7i, r8g, r8gd, m7g, m7i, c7g, c7i, x8g).
- You MUST explain Multi-AZ RI pricing: Multi-AZ RIs cost more than Single-AZ, and a Single-AZ RI does NOT cover a Multi-AZ instance. The user must buy the correct deployment type.
- For RDS, there is NO Serverless option — do NOT mention ACU pricing, scale-to-zero, or any Aurora-specific concepts
- You SHOULD cite [commitment-basics.md](commitment-basics.md) for RI vs DSP mechanics and [commitment-scenarios.md](commitment-scenarios.md) for workload-pattern decisions

### 4. Present Results

Every comparison MUST include:

1. A table: On-Demand, 1yr RI (best payment option), 3yr RI, 1yr DSP, 3yr DSP
2. Each row's monthly cost, savings vs On-Demand in **dollars AND percentage**, upfront payment, term
3. A clear recommendation with the winning option and reasoning
4. Tradeoffs: family lock-in, cash flow, upgrade plans, Multi-AZ considerations, region lock-in
5. The script's `notes` when present (DSP ineligibility, Multi-AZ separation, etc.)

**Constraints:**

- You MUST cite both dollar and percentage savings — neither alone is sufficient (dollars alone hide the scale; percentages alone hide the magnitude)
- You MUST show upfront payment when non-zero — cash-flow impact matters for finance approval
- You MUST NOT run any purchase API (`purchase-reserved-db-instances-offering`, Savings Plans purchase calls) because this workflow is advisory-only
- You MAY reference the AWS console path (RDS → Reserved Instances, or Billing → Savings Plans) so the user knows where to execute the commitment manually

### 5. Scenario Guidance

For workload-pattern questions, pull guidance from [commitment-scenarios.md](commitment-scenarios.md).

**Constraints:**

- You SHOULD match the user's workload to a scenario in the scenarios reference and explain why
- You MUST NOT recommend 3yr terms for workloads the user indicates may be retired within the term, because RIs and DSPs are use-it-or-lose-it
- You MUST warn that RDS RIs do NOT transfer to Aurora if the user is considering Aurora migration within the term — different engine, different commitment product
- You MUST warn that RDS RIs are region-locked if the user is considering moving the workload to a different region

## Troubleshooting

- **Instance not found**: Wrong identifier or region. Verify with `aws rds describe-db-instances --region <region>`.
- **RI/DSP fetch returns empty**: Newly launched instance types or non-standard regions. Offer offline mode.
- **3-year DSP**: A 3-year Database Savings Plan exists for RDS (unlike Aurora which is 1yr only). Present both 1yr and 3yr DSP options.
- **DSP not available for this family**: Instance family older than DSP coverage. Explain RI is the only option; suggest migration to newer family.
- **Multi-AZ confusion**: Multi-AZ RIs are separate offerings from Single-AZ. The user must match the deployment type.

## References

- [commitment-basics.md](commitment-basics.md) — RI vs DSP mechanics, payment options, break-even, RDS-vs-Aurora differences
- [commitment-scenarios.md](commitment-scenarios.md) — workload-pattern decision scenarios and quick decision tree
