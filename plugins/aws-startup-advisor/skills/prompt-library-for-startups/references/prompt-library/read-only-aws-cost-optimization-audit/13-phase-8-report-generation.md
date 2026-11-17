<!-- markdownlint-disable -->

## PHASE 8: REPORT GENERATION

Use the format chosen in 1.5. For CSV, flatten to: Category, Resource, Environment, Current Monthly Cost, Proposed Action, Estimated Monthly Savings, Confidence, Priority, Effort, Risk, Owner Sign-off.

### 8.1 Savings estimate rules

**Every recommendation carries an estimated monthly saving in dollars.** No figure means it cannot be prioritized. Where no exact number is derivable, give a conservative range labelled as an estimate.

Derive in this order:

1. **Native API values**, the most defensible. Paths differ by service, the usual cause of blank columns: Compute Optimizer `savingsOpportunityAfterDiscounts.estimatedMonthlySavings.value` (or `savingsOpportunity...` pre-discount), both null unless the 2.2 preference is on; Cost Optimization Hub `estimatedMonthlySavings`, a flat number; SP and RI recommendations `estimatedMonthlySavings` in the detail.
2. **Actual observed cost.** `cost_explorer` `getCostAndUsageWithResources` over 14 days, extrapolated. Beats list-price arithmetic because it reflects discounts already applied. Requires the resource-level data preference from 2.2; if the first call fails on the missing opt-in, record it and drop to step 3 rather than asking the user to enable a preference that carries a standing charge.
3. **Live pricing lookup.** `aws_pricing` for the exact type, size, and Region. Never a hardcoded price.
4. **Modelled target state.** `aws-pricing-calculator` for architectural changes; include the shareable link.

Say whether each figure is pre-discount or post-discount; for an account with commitments the two differ substantially.

Tag confidence: `HIGH` for native API or observed cost, `MEDIUM` for a pricing lookup, `LOW` for anything modelled. State the assumption behind every `LOW` figure, such as the off-hours schedule or assumed Spot discount.

Do not double count. A resource flagged idle in Phase 4 and oversized in Phase 5 yields one saving. **Deduplicate on resource ARN or ID plus action type**, across 4.1, 4.2, 4.2.1, 5.1, and Phase 6. The Hub `source` field alone cannot do it: when Hub and Compute Optimizer both report the same resource, the two entries carry different `source` values and different savings figures, so keying on `source` keeps both. Where the deduplicated pair disagrees on the number, keep the more conservative figure and note the spread. Say that you deduplicated. Reconcile against actual spend: identified savings above 40 percent of the bill means re-check for double counting first, and **record the outcome of that re-check in the workpaper** - crossing the threshold silently is not a pass. Every idle or delete finding in the total must also carry its 4.13 step 5 branch, so no saving is claimed on traffic the account was billed for. Savings on commitment-covered resources carry the 4.13 step 6 date, realised at commitment expiry or absorption, never immediately.

### 8.2 Report structure

Header: date, audited account ID and account type, regions in scope, scope exclusions, total spend for the last complete calendar month, total identified savings and percentage, audit completeness (`COMPLETE`/`PARTIAL`), credential mode (least-privilege role or acknowledged write-capable, plus the MCP identity per Rule 2), audit mode (attended, or unattended with every Rule 8 gate conversion listed), and identifier masking (masked or full).

**1. Executive summary.** Table of category, monthly savings, percent of spend, effort, confidence, across: commitments, idle cleanup, rightsizing, data transfer and networking, storage and log lifecycle, non-production scheduling, architecture modernization, plus a total row. Add the 12-month trend shape, largest month-over-month movers with causes, and the three highest-value actions in one sentence each. For a credit-funded account, state gross spend, net spend, and credit runway from 3.4 in the opening lines, and express the total identified savings as runway extension in months as well as dollars.

**2. Completeness and limitations.** Every `warn` from 2.5, every permission failure from 2.1, every `PARTIAL` or `SKIPPED` section, whether SP data was cached and its timestamp, and sampled-versus-total counts. This section carries the mandatory **4.13 coverage table**: service, monthly cost, share of bill, analysed yes or no, method (native / playbook / fallback / not analysed and why), plus the stated materiality threshold and the unanalysed residual as a percentage of the bill. List every `METRICS UNAVAILABLE` and `TRAFFIC BILLED, METRICS ZERO` result here too: a resource whose metrics and bill disagree is a limitation on the audit, not a finding about the resource. **This goes second, not last:** a reader needs the gaps before acting on numbers.

**3. Idle and unused resources.** Columns: resource type, ID/name, size, region, env, monthly cost, proposed action, risk, owner sign-off, and **evidence**: the metrics read, their window, and the 4.13 step 5 branch that cleared the finding against the bill. Sort by cost descending. Every row needs an environment classification; every destructive proposal needs the data-loss risk and reversal path; `PROD` or `UNKNOWN` shows `Required` for sign-off. A row citing zero measured usage against a usage-based charge does not belong in this section; it belongs in section 2.

**4. Rightsizing.** Columns: resource, current, recommended, current $/mo, new $/mo, savings/mo, performance risk, env. Carry risk through verbatim and label which scale it uses.

**5. Data transfer and networking.** The usage-type breakdown, the cause mapped to each finding, and the fix: Gateway endpoint, AZ-aware routing, CloudFront, or endpoint consolidation.

**6. Commitments.** Columns: scenario, hourly commitment, monthly savings, savings percent, term, cancellable. State current coverage against 80 percent, utilization against 95 percent, the recommended commitment with the Phase 4 and 5 waste adjustment shown explicitly, and the P10 hourly anchor. For a credit-funded account, open with the credit gate outcome: credit balance, expiry, and the earliest recommended purchase date. Add the RI versus Database SP comparison where both apply, showing which wins and why.

**7. Architecture and modernization.** Columns: recommendation, resources, current $/mo, projected $/mo, savings/mo, effort, confidence, dependencies. Name each dependency: arm64 build for Graviton, interruption tolerance for Spot, maintenance window for a storage class change.

**8. Governance gaps.** Budgets and configuration, anomaly monitors and whether they have subscriptions, active cost allocation tags, untagged share, count of unclassifiable resources. Excluded from the headline total.

**9. Prioritized action plan.** Columns: rank, action, monthly savings, effort, savings per hour of effort, risk, owner. Order by savings divided by effort, with two overrides: cleanup and rightsizing precede commitment purchases, and items needing sign-off come after equivalent-value items that do not. Close with monthly and annualized totals.

---

<!-- markdownlint-enable -->
