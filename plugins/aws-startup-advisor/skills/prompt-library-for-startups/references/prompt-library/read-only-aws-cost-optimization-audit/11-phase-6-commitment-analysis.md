<!-- markdownlint-disable -->

## PHASE 6: COMMITMENT ANALYSIS

**This phase runs last of the analysis phases on purpose.** A commitment sized on a baseline still containing Phase 4 waste and Phase 5 over-provisioning locks that waste in for one to three years.

**Credit gate.** If 3.4 shows credits funding a material share of the spend this phase would commit against, commitment purchases become **post-credit planning**, not a current recommendation. The reasons, verified against [Applying AWS credits](https://repost.aws/knowledge-center/credits-ri) in September 2026: credits never cover Savings Plan or RI **upfront** fees; they can cover recurring commitment charges only while balance remains and only for products in the credit's **Applicable Products** list (Billing console, Credits page); and the commitment outlives the credits, converting usage that today costs the customer nothing into a binding cash obligation. Native SP and RI recommendations are computed from usage and are credit-blind, so present every §6.2 figure with that caveat. Anchor the recommendation timeline on the credit expiry date from 1.5: usage history for sizing, expiry for timing. If balance and expiry were not provided, say the commitment analysis is unsafe to act on until they are known, and mark the section `PARTIAL`.

### 6.1 Current coverage and utilization

MCP: `sp_performance` `get_savings_plans_utilization` for per-type month-to-date figures matching the console, then `get_savings_plans_coverage`, then `ri_performance` `get_reservation_coverage` and `get_reservation_utilization`. Always pass a `SERVICE` dimension filter to `ri_performance` for a specific service; without one it returns a blended all-service aggregate that will not match the console.

```bash
# Trailing 30-day window; label it as such per the 1.3 windows rule.
for op in savings-plans-coverage savings-plans-utilization reservation-coverage reservation-utilization; do
  aws ce get-$op --time-period Start="$START_30D",End="$TODAY" --granularity MONTHLY
done
```

Record coverage against an 80 percent target, utilization against 95 percent, RI coverage and utilization, commitment expiry dates (`savingsplans:Describe*` is in the Prerequisites supplement for this), and the On-Demand versus committed gap.

Utilization below 95 percent is a finding on its own: the customer already pays for capacity they do not use, and buying more compounds it.

**From a member account every figure in this section is account-local.** Cost Explorer sees the organization only from the management account, and Compute Savings Plans bought in the payer apply across member accounts while their coverage shows in the payer view. So 0 percent coverage seen from a member account does not mean the organization holds no commitments; that misleading zero is the normal member-account view. When 1.1.2 recorded a member account: label every 6.1 figure "account-local", mark 6.2 and 6.3 `PARTIAL (member account - organization commitments not visible)`, and state in the report that acting on a purchase recommendation without the payer view risks buying a commitment the organization already holds. Ask the user whether someone with management-account access can confirm the organization's coverage before Phase 6 output is acted on; in unattended mode record that question as an open item.

### 6.2 Purchase recommendations

`get-savings-plans-purchase-recommendation` returns cached results. Refreshing needs `ce start-savings-plans-purchase-recommendation-generation`, a write action you must not call.

Tell the user: "Your Savings Plans recommendations may be stale. Refreshing needs `aws ce start-savings-plans-purchase-recommendation-generation`, a write call I will not make. You can run it, it takes 30 to 90 seconds and is capped at three runs per day per billing family, or I can use cached data and flag its date." Record the `GenerationTimestamp` of whatever you use. In unattended mode (Rule 8), use the cached data and flag its timestamp without asking.

**Four types.** `SavingsPlansType` accepts `COMPUTE_SP`, `EC2_INSTANCE_SP`, `SAGEMAKER_SP`, `DATABASE_SP`. Some AWS pages still list only three and are stale; treat [Savings Plans types](https://docs.aws.amazon.com/savingsplans/latest/userguide/plan-types.html) as authoritative for the type list and discounts. The Database SP term and payment constraint is not on that page; its sources are the [Savings Plans FAQ](https://aws.amazon.com/savingsplans/faqs/) and the [Database Savings Plans pricing page](https://aws.amazon.com/savingsplans/database-pricing/), which states the one-year no-upfront constraint directly. The FAQ also notes the advance pay feature as the route for customers who want to pay ahead anyway. All checked September 2026.

| Type | Covers | Max discount | Terms | Payment |
| --- | --- | --- | --- | --- |
| `COMPUTE_SP` | EC2, Lambda, Fargate, any family, size, Region, OS, tenancy | up to 66% | 1 or 3 yr | all three |
| `EC2_INSTANCE_SP` | EC2 only, locked to one family in one Region | up to 72% | 1 or 3 yr | all three |
| `DATABASE_SP` | Aurora, RDS, DynamoDB, ElastiCache (Valkey engine only), DocumentDB, Neptune, Keyspaces, Timestream, DMS, OpenSearch; provisioned and serverless | up to 35% | **1 yr only** | **No Upfront only** |
| `SAGEMAKER_SP` | SageMaker AI | up to 64% | 1 or 3 yr | all three |

`DATABASE_SP` does **not** cover Redshift or MemoryDB, which stay RI or Reserved Node services, and within ElastiCache it covers the Valkey engine only: the pricing page lists Valkey instances and serverless and nothing else, so Redis OSS and Memcached usage stays on RIs. Verify current engine coverage with `aws-knowledge` before modelling; checked September 2026. For RDS for SQL Server it discounts the instance price only; Windows and SQL Server licence charges stay at On-Demand. Two more exclusions worth stating in coverage math: EKS control-plane charges are not covered by any Savings Plan even though the worker nodes' EC2 usage is, and Dedicated Instances carry a $2 per hour per-Region fee that Savings Plans do not discount.

```bash
# Compute SP scenarios
for opt in NO_UPFRONT ALL_UPFRONT; do
  aws ce get-savings-plans-purchase-recommendation --savings-plans-type COMPUTE_SP \
    --term-in-years ONE_YEAR --payment-option "$opt" --lookback-period-in-days SIXTY_DAYS
done
aws ce get-savings-plans-purchase-recommendation --savings-plans-type COMPUTE_SP \
  --term-in-years THREE_YEARS --payment-option NO_UPFRONT --lookback-period-in-days SIXTY_DAYS

# DATABASE_SP is offered one-year No-Upfront only (per the FAQ). The API does
# not reject other combinations - a three-year request returns HTTP 200 - so
# request only the valid one; a response for an unpurchasable term is noise.
# EC2_INSTANCE_SP gives a higher discount but locks family and Region, so only model it
# where both are genuinely stable.
for t in DATABASE_SP SAGEMAKER_SP EC2_INSTANCE_SP; do
  aws ce get-savings-plans-purchase-recommendation --savings-plans-type "$t" \
    --term-in-years ONE_YEAR --payment-option NO_UPFRONT --lookback-period-in-days SIXTY_DAYS
done
```

This audit sizes commitments for the audited account only. In a management account, add the `LINKED_ACCOUNT` filter from the management-account scoping convention, or the recommendation covers the whole organization. From a member account, recommendations are computed on that account's usage alone and carry the 6.1 duplicate-purchase caveat. In an organization, Savings Plans and RI discounts are shared across accounts by default, so a commitment sized on one account can overlap another account's needs; say that an organization-wide purchase decision should be made from the management account's view after every account has been audited. Enums: `TermInYears` is `ONE_YEAR`/`THREE_YEARS`, `LookbackPeriodInDays` is `SEVEN_DAYS`/`THIRTY_DAYS`/`SIXTY_DAYS`, `AccountScope` is `PAYER`/`LINKED`.

### 6.3 Sizing the commitment

1. Take `HourlyCommitmentToPurchase`, AWS's computed optimum.
2. **Subtract the On-Demand spend of anything flagged for deletion in Phase 4 or downsizing in Phase 5.** State this adjustment explicitly. Skipping it is the most expensive mistake in this exercise.
3. Apply a conservative multiplier to the adjusted figure: 0.7 conservative, 0.85 moderate.
4. Sanity-check against the usage distribution below. Around 60 to 70 percent of steady-state baseline is the usual landing zone for a first Compute Savings Plan.
5. Flag any gap above 20 percent between the native recommendation and your adjusted figure for human review.

Anchor on a percentile, not the absolute minimum. `CurrentMinimumHourlyOnDemandSpend` and the cheapest single day in 90 are both easily distorted by one outage or deploy window, so anchoring strictly below them leaves real money unclaimed.

```bash
aws ce get-cost-and-usage --time-period Start="$START_90D",End="$TODAY" \
  --granularity DAILY --metrics "UnblendedCost" \
  --filter '{"And":[
      {"Dimensions":{"Key":"SERVICE","Values":[
        "Amazon Elastic Compute Cloud - Compute","AWS Lambda","Amazon Elastic Container Service"]}},
      {"Not":{"Dimensions":{"Key":"RECORD_TYPE","Values":["Credit","Refund"]}}}]}' \
  --output json | jq -r '
    [.ResultsByTime[].Total.UnblendedCost.Amount | tonumber] | sort as $d | ($d|length) as $n
    | {min: $d[0], p10: $d[($n*0.1|floor)], p50: $d[($n*0.5|floor)]}
    | "min daily=\(.min)  p10=\(.p10)  median=\(.p50)  p10 hourly=\(.p10/24)"'
```

The `RECORD_TYPE` exclusion matters: credits and refunds post as negative line items that drag daily totals down, and a percentile computed over them anchors the commitment below real usage.

If P10 is zero or near zero the usage is too intermittent to commit against. Say so rather than recommending a token commitment. And per the credit gate at the top of this phase, a sound P10 still does not make a commitment timely for a credit-funded account.

**Before anyone buys**, point them at Savings Plans Purchase Analyzer in the Billing console. It simulates any commitment against actual historical usage and returns resulting savings, coverage, and utilization, which beats any estimate in this report. Make it the required pre-purchase step in Appendix A.

### 6.4 Reserved Instances

RIs stay right in three cases: a service or engine no Savings Plan covers, such as Redshift, MemoryDB, and ElastiCache on Redis OSS or Memcached; a zonal capacity reservation, since only a zonal RI guarantees physical capacity in a specific AZ; and a workload whose family and Region are locked for the full term, where the RI rate can beat the SP rate.

For Aurora, RDS, ElastiCache for Valkey, DocumentDB, and OpenSearch a Database Savings Plan and an RI are alternatives, not a stack, and cannot both cover the same workload. Model both and recommend the better. They can coexist across different workloads, so a mixed recommendation is fine if you say which applies where.

`--service` is a free-form string, not an enum, and an unrecognized value returns an empty recommendation rather than an error. Discover exact names first, then use them verbatim:

```bash
aws ce get-dimension-values --dimension SERVICE \
  --time-period Start="$START_30D",End="$TODAY" --query 'DimensionValues[].Value' --output text

for svc in "Amazon Relational Database Service" "Amazon ElastiCache" \
           "Amazon OpenSearch Service" "Amazon Redshift" "Amazon MemoryDB"; do
  echo "=== $svc ==="
  aws ce get-reservation-purchase-recommendation --service "$svc" \
    --term-in-years ONE_YEAR --payment-option NO_UPFRONT --lookback-period-in-days SIXTY_DAYS
done
```

An empty `Recommendations` array means either no steady-state usage worth reserving or a name mismatch: distinguish them by checking whether the service appears in the Phase 3 breakdown before reporting "no opportunity". `Filter` here supports only `NOT` and only on `LINKED_ACCOUNT`, so Region and instance type cannot be filtered. `PageSize` caps at 6000.

### 6.5 Output

Present scenarios only; no purchase command appears anywhere, per Rule 1. For each, state the hourly rate, monthly and annual savings, term, payment option, what happens if usage falls below the commitment, and that it cannot be cancelled. For a credit-funded account, lead with the credit gate: label every scenario "for purchase after credit expiry on [date]" and state the runway impact in months, not just the savings percentage. Route the purchase to Appendix A as a console procedure with a named approver, noting that in an organization commitments apply across accounts by default, so the purchase decision belongs to whoever sees the whole organization, not to one account's audit.

---

<!-- markdownlint-enable -->
