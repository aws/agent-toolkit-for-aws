---
_fragment: infra
_of_phase: estimate
_contributes:
  - estimation-infra.json
---

# Estimate infrastructure

## Source baseline

Apply the source hierarchy without blending sources. Invoice/export and user-stated values retain their own as-of date and currency. Cache pricing is eligible only when `as_of + max_age_days` includes the estimate date, currency is USD, and every billed resource has an exact normalized plan or legacy-alias match. Plan resolution is one step: use the inventory's `plan_normalized` (the Blueprint parser and the live normalizer both compute it from `references/shared/render-plan-aliases.json`), or apply that table yourself when a captured plan carries none, then look the canonical id up exactly in the cache. A plan the table leaves null, or a canonical id with no cache row, is `unavailable`; never substitute the nearest plan. An unmatched or stale row is `unavailable`, not zero and not a partial source total.

When no source in the hierarchy yields a baseline, write `current_costs` as exactly `source: "unavailable"` with `render_monthly: null`; every other `source` carries a numeric `render_monthly`. The report renders that baseline cell as the literal text `unavailable`, and the report validator accepts only this pairing while still requiring exact amounts whenever `render_monthly` is a number.

Price Key Value from normalized memory plan IDs, including `3g` and `50g`; aliases resolve through the same shared table before lookup. Price service plans using CPU and RAM as independent captured dimensions. Price Workflow Flex as `(active_cpu_hours × 0.20) + (active_gb_hours × 0.05) + (retained_state_gb × 0.25)`, respecting the one-second 0.1 CPU/0.1 GB per-run minimum. Fixed Workflow plans use task duration multiplied by the exact hourly row. Missing task duration makes Workflow source cost unavailable.

## Rightsizing evidence gate

Load `rightsizing-thresholds.json`. A resource earns `measured` sizing only when the metric window spans at least seven days, expected-sample coverage is at least 0.80, resolution is one of 30/60/300/3600 seconds, outcomes contain points rather than successful-empty/plan-gated values, and instance series are aligned to lifecycle intervals. Do not sum replacement instances as concurrent capacity or interpolate idle gaps as zero.

If any gate fails, right-sized capacity equals capacity-preserving capacity, confidence remains `inferred`, and the explanation names every failed threshold. Down-sizing additionally requires CPU p95, memory p95, memory peak, headroom, and source minimums to pass the numeric limits in the knowledge file. AI/agent infrastructure applies the named memory-headroom multiplier, but the AI execution track stays unpriced.

Cron runtime is unavailable unless customer-provided or captured run history establishes actual duration with sufficient evidence. A schedule alone never creates monthly runtime. Workflow and task durations follow the same evidence rule.

## AWS rate rows
Price each AWS component of a mapping from `references/vendored/pricing/aws-infra-pricing.json`. `knowledge/estimate/render-service-rate-map.json` names the row, `_no_cost_services` entry, or `_absent_services` entry for every component a selector can emit. A line is null in exactly two cases, and each records an `exclusion_reason` and appears in `unpriced_line_ids`. `no_rate`: a component is in `_absent_services`. `no_quantity`: the quantity the rate multiplies is not established, for example a cron with no run history (a schedule alone never creates runtime), a Workflow with no duration, EFS with no captured capacity, Step Functions or ECR with no captured volume, or Aurora sized to a class in `_unavailable_instances`. Otherwise the line carries an amount. Never invent a quantity to avoid a null, and never substitute a neighbouring rate. The render pricing-coverage test fails when a sizing-table output or design service has no row or entry.
## Dual totals and floors

For each selected AWS mapping, emit parallel `capacity_preserving` and `right_sized` line objects with quantity, unit, rate, formula, monthly amount or null, pricing source, confidence, and exclusion reason. Apply service-specific Multi-AZ handling from the cache; never use a blanket multiplier. A target-region mismatch keeps the us-east-1 amount but adds the required region note and widens confidence; it does not invent a multiplier.

For each scenario:

1. Sum only non-null rounded line amounts.
2. Record all null lines in `unpriced_line_ids`.
3. Set `is_floor` true when that list is nonempty and label the numeric value “known-cost floor,” never “total.”
4. Require every design mapping to produce a priced, no-direct-charge, or explicitly unpriced line.
5. Compute delta only from the two known-cost floors and carry incompleteness into the explanation.

Estate-wide costs attach to Design mappings so every line keeps a `source_resource_id` in the Design set. Fold the CloudWatch Logs ingestion and storage cost, sized from `observability.log_retention`, into the line for the `render.environment` mapping and name it in `aws_service` (for example `AWS deployment environment stack + Amazon CloudWatch Logs, Metrics, and Alarms (30-day retention)`). Price the one stack KMS key (`kms.tf`, `aws_kms_key.stack`) once when any Design resource records `customer_managed_key: true`, and fold it into the line of the first such store in mapping order; stores without the field add no KMS cost. Do not emit separate estate-wide lines. When `cost.budget_guardrail` is a limit, compare the known-cost floor to it in the explanation and say when the floor is incomplete. Human labor, migration engineering, and downtime are considerations with no dollar amount. Commitment opportunities follow the vendored eligibility matrix and do not reduce the capacity-preserving on-demand total; Compute Savings Plans remain percent-only until 30–90 days of AWS usage establishes a floor.
## ECS Express Mode pricing
A Fargate mapping with `aws_config.ecs_mode: "express"` is priced like a standard Fargate service: task vCPU and GB-hours from the same tables plus its allocated share of the ALB fixed fee. Express Mode has no service charge, but up to 25 Express services share one ALB per VPC and scheme. Render keeps exactly one estimate line per design mapping, so the shared ALB never becomes its own line. Allocate it across the mapping lines instead:

1. Group Express mappings by VPC and ALB scheme (public placement is internet-facing, private placement is internal, never combined). Let `count` be the group size.
2. The group's fixed fee is `ceil(count / 25)` times the reviewed `alb.monthly_fixed` rate, converted to whole cents.
3. Sort the group's mappings by `source_resource_id` in byte order. Each line carries `floor(fee_cents / count)` cents, and the first `fee_cents mod count` lines carry one extra cent, so the allocated amounts sum to the group fee exactly.
4. Show the allocated fixed amount as its own component in that line's formula, next to its Fargate and LCU components. LCU is estimated per service and stays on that service's line.
5. Apply the same allocation in `capacity_preserving` and `right_sized`; the group and its fee do not change between scenarios.

A standard HTTP service, including any mapping with no `ecs_mode`, keeps its own ALB cost inside its single line and never joins an Express group. The scenario lines stay equal to `accounting.accounted_resource_ids`, and one ALB fixed fee is charged per 25 Express services per VPC and scheme.
