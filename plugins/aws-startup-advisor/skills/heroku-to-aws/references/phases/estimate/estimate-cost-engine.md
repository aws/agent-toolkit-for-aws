---
_fragment: cost-engine
_of_phase: estimate
_contributes:
  - estimation-infra.json
---

# Estimate Phase: Cost Engine

> Self-contained cost-calculation sub-file. Selects the pricing mode, validates the
> design inputs, and computes the full financial picture: current Heroku costs,
> projected AWS costs (per-service + tiers), observability, comparison, migration
> considerations, ROI, optimization opportunities, complexity tier, and the
> recommendation. The final artifact write, handoff gate, and phase-status update
> are owned by the assembler (`estimate-assemble.md`).

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Pricing Mode Selection

Execute `references/vendored/estimate/pricing-mode.md` (the canonical
Step 0, vendored from `skills/shared/estimate/pricing-mode.md` and kept
byte-identical by `shared:sync`) as this step: cache staleness check, MCP
retry ladder, pricing-mode display, and the per-service pricing hierarchy
(including the `estimated` and `unavailable` rungs). Do not restate or
fork that logic here.

For typical Heroku migrations (Elastic Beanstalk, Fargate, RDS, Aurora, ElastiCache, ALB, NAT Gateway, S3, CloudWatch, Secrets Manager, EventBridge, SES, OpenSearch, MQ), ALL prices are in `aws-infra-pricing.json`. Zero MCP calls needed.

---

## Step 1: Prerequisites

The entry gate (design completed, inputs present + valid JSON, non-empty
`services[]`) is enforced by this phase's `_preconditions` frontmatter per
`INTERPRETER.md` § Gate protocol — it has already passed before this fragment
runs. Then:

1. Read `$MIGRATION_DIR/heroku-resource-inventory.json`. Extract `billing_profile` section (may be null/absent).

Proceed to Part 1.

---

## Part 1: Determine Current Heroku Costs

Use the best available source for Heroku monthly baseline (first match wins):

1. **`billing_profile` in inventory (preferred)** — Use actual billing data as the Heroku baseline. Highest confidence.
   - Extract `billing_profile.total_monthly_cost` as the total
   - Extract `billing_profile.line_items[]` for per-app breakdown
   - Set `current_costs.source: "billing_data"`

2. **Live-captured prices + dyno cache** — If no billing data AND at least one
   add-on resource carries `config.monthly_price_usd` (the account's actual
   billed plan rates from the Platform API capture). The gate is the presence of
   live prices, not merely that live discovery ran: a live run that captured
   ZERO priced add-ons (e.g. a dyno-only app) has nothing live-priced in it —
   fall to rung 3, whose `pricing_cache` label and ±5% accuracy describe that
   baseline honestly.
   - **Add-ons:** sum `config.monthly_price_usd` across add-on resources — these
     are exact, and they price plans the cache has never heard of (no
     `"unpriced_heroku"` holes for priced add-ons)
   - **Dynos:** the API does not price formations; look up each formation's
     `dyno_type` in `references/shared/heroku-pricing-cache.md` (±5% published
     flat rates) × `quantity`
   - Set `current_costs.source: "live_prices_plus_cache"`
   - Set `current_costs.accuracy: "exact for add-ons, ±5% for dynos"`
   - An add-on WITHOUT `monthly_price_usd` (e.g. a Terraform-only entry) falls
     through to the rung-3 cache lookup for that resource only; if neither
     prices it, mark `"unpriced_heroku"` and add to warnings
   - `baseline_note` (mandatory): "Derived from your account's actual add-on
     prices plus published dyno rates — not an invoice. Excludes usage-based
     charges (bandwidth, build minutes), team seats, credits, and discounts;
     your invoice may differ."

3. **Heroku pricing cache** — If no billing data and no live-captured prices, Load `references/shared/heroku-pricing-cache.md` and derive costs from discovered resources:
   - For each resource in inventory, look up its plan in the cache tables (case-insensitive exact match)
   - Multiply dyno costs by `formation.quantity`
   - Sum all matched resources to get `heroku_monthly_estimated`
   - Set `current_costs.source: "pricing_cache"`
   - Set `current_costs.accuracy: "±5%"`
   - If any resource plan is not found in cache, mark as `"unpriced_heroku"` and exclude from total; add to warnings

4. **User-provided** — If neither live prices nor the pricing cache match any resource (unlikely with Terraform or live discovery), ask: "I need your current Heroku monthly spend to produce a meaningful cost comparison. What is your approximate Heroku monthly cost?" Use the answer.
   - Set `current_costs.source: "user_provided"`

5. **Unavailable** — If user declines: present AWS costs without Heroku comparison.
   - Set `current_costs.source: "unavailable"`
   - Note: "Heroku baseline unavailable — AWS costs shown without comparison."

Whenever a baseline was determined (any source except `"unavailable"`), present it as:

- Total monthly cost, with its source and accuracy stated plainly (invoice data vs actual plan prices vs rate card vs user estimate)
- Per-app breakdown (dyno, add-on, platform charges)
- Billing period (billing-data source only) or `baseline_note` (derived sources)

---

## Part 2: Calculate Projected AWS Costs

For each service in `aws-design.json → services[]`, calculate monthly cost by applying the formula from the Per-Service Calculation Formulas table below, looking up its rates from `references/vendored/pricing/aws-infra-pricing.json`. Track `pricing_source` per service. (`hours_per_month` = 730, from `_meta`.)

### Per-Service Calculation Formulas

Rates below come from the named keys in `aws-infra-pricing.json` — do not hardcode them here. The formula shape + key inputs are shown for reference.

| AWS Service               | Formula (rates from `aws-infra-pricing.json`)                                                                                                            | Key inputs from `aws_config`                                                  |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **Elastic Beanstalk**     | EC2: `ec2.instances[instance_type]` × 730 × running instance estimate + ALB: `alb.monthly_fixed` + LCU estimate (if LoadBalanced). EB service fee is $0. | `instance_type`, `min_instances`, `max_instances`, `environment_type`         |
| **Fargate**               | (task_cpu/1024 × `fargate.per_vcpu_hour` + task_memory/1024 × `fargate.per_gb_mem_hour`) × 730 × desired_count                                           | `task_cpu`, `task_memory`, `desired_count`                                    |
| **EKS (cluster + nodes)** | `eks.control_plane_monthly` + `eks.node_rates_monthly[type]` × node_count + ALB per web service                                                          | `eks_cluster.node_groups[].instance_types`, `desired_size`, web service count |
| **ALB**                   | `alb.monthly_fixed` + LCU estimate (`alb.per_lcu_hour` × 730)                                                                                            | Per web service with `load_balancer: true`                                    |
| **RDS PostgreSQL**        | `rds_postgresql.instances[class]` × 730 + storage_gb × `rds_postgresql.storage_per_gb_month` (rate is baked_in Multi-AZ — do NOT double)                 | `instance_class`, `storage_gb`, `multi_az`                                    |
| **Aurora PostgreSQL**     | `aurora_postgresql.instances[class]` × 730 + storage_gb × `aurora_postgresql.storage_per_gb_month` + I/O estimate (intrinsic multi-AZ)                   | `instance_class`, `storage_gb`                                                |
| **ElastiCache Redis**     | `elasticache.nodes[type]` × 730 (× 2 if Multi-AZ — `multiplier_x2`)                                                                                      | `node_type`, `multi_az`                                                       |
| **MSK**                   | `msk.brokers[type]` × 730 × broker_count + storage_gb × `msk.storage_per_gb_month` (intrinsic multi-AZ)                                                  | `broker_instance_type`, `broker_count`, `storage_per_broker_gb`               |
| **CloudWatch Logs**       | log_volume_gb × `cloudwatch.log_ingestion_per_gb` + storage × `cloudwatch.log_storage_per_gb_month`                                                      | `retention_days`, estimated log volume                                        |
| **S3**                    | storage_gb × `fast_path_services.s3.storage_per_gb_month` + request estimates (or `s3.monthly_baseline_est`)                                             | `storage_gb` (from Bucketeer/Cloudinary mapping)                              |
| **Amazon SES**            | `fast_path_services.ses.monthly_baseline_est` (flat baseline; see `_basis`)                                                                              | Flat estimate from SendGrid mapping                                           |
| **EventBridge Scheduler** | `fast_path_services.eventbridge.monthly_baseline_est` (flat; per_million_events basis)                                                                   | From Heroku Scheduler mapping                                                 |
| **Amazon MQ**             | `fast_path_services.amazon_mq.instance_monthly_est` + storage                                                                                            | From CloudAMQP mapping                                                        |
| **Amazon OpenSearch**     | `fast_path_services.opensearch.instance_monthly_est` + storage                                                                                           | From Bonsai Elasticsearch mapping                                             |
| **Secrets Manager**       | secret_count × `fast_path_services.secrets_manager.per_secret_month` + API calls × `per_10k_api_calls` (or `monthly_baseline_est`)                       | Config var count from inventory                                               |
| **NAT Gateway**           | `nat_gateway.monthly_fixed` + data processing estimate (`nat_gateway.per_gb_processed`)                                                                  | From VPC design (if new VPC)                                                  |
| **RDS Proxy**             | `rds_proxy.per_vcpu_hour` × 730 × vCPUs                                                                                                                  | When connection pooling mapped                                                |
| **Route 53**              | `route53.hosted_zone_monthly` + query estimate (`route53.per_million_queries`)                                                                           | When DNS strategy = route53                                                   |
| **CloudFront**            | `fast_path_services.cloudfront.per_gb_first_10tb` × GB + request costs (or `cloudfront.monthly_baseline_est`)                                            | From Cloudinary composite mapping                                             |
| **X-Ray**                 | `cloudwatch.xray_per_million_traces` × trace_millions                                                                                                    | Only if tracing detected in source                                            |

### Unpriced Resource Handling

IF pricing data for a service is unavailable from both MCP and cache:

1. Mark the resource's cost as `"unpriced"` in the per-service breakdown
2. **Exclude** from the total monthly cost sum
3. Add to `warnings[]`: "Pricing unavailable for [service_id] ([aws_service]). Requires manual cost verification."
4. Add service name to `pricing_source.services_with_missing_fallback[]`

### EKS Cost Calculation

When `aws-design.json` contains EKS services (`aws_service: "EKS"`):

1. **EKS Control Plane**: `eks.control_plane_monthly` (fixed, one cluster regardless of node count)
2. **EC2 Node Group**: Look up the node instance type's monthly rate in `eks.node_rates_monthly[type]` × `desired_size` nodes. The monthly rates (m6i.large, m6i.xlarge, m6i.4xlarge, r6i.4xlarge, m6i.8xlarge, m6i.16xlarge) are maintained in `aws-infra-pricing.json` — do not hardcode them here.
3. **ALB for web services**: Same as Fargate ALB pricing (`alb.monthly_fixed` per web service)
4. **NAT Gateway** (if private subnets): Same as Fargate path (`nat_gateway.monthly_fixed` + data processing)

**Total EKS monthly cost** = `eks.control_plane_monthly` + (node_monthly_rate × node_count) + ALB_costs + NAT_costs. Pods are NOT charged a per-task cost (compute is billed via the EC2 nodes); ALB and NAT are the separate lines above, not re-added here.

### Elastic Beanstalk Cost Calculation

When `aws-design.json` contains Elastic Beanstalk services (`aws_service: "Elastic Beanstalk"`):

1. **EC2 instances**: Look up the instance type's hourly rate in `ec2.instances[instance_type]` × 730 hours × the running instance estimate. For the Balanced tier, use steady-state `min_instances` so EB and Fargate comparisons use comparable running-capacity assumptions. Show `max_instances` as scaling headroom, not as 730 hours of guaranteed spend.
2. **ALB** (LoadBalanced environments only): use the same ALB formula as standalone ALB entries: `alb.monthly_fixed` plus an LCU estimate. SingleInstance non-web environments do NOT incur ALB cost.
3. **EBS storage**: EC2 On-Demand pricing does not include EBS root volumes. Add per instance: `ebs.gp3_per_gb_month` × (`aws_config.root_volume_gb` when the design specifies one, else `ebs.eb_root_volume_gb_default`) × the running instance estimate. Do not claim a 30GB EC2 allowance.
4. **NAT Gateway**: If the VPC design places EB instances in private subnets that require outbound internet access, include the same NAT Gateway line used by the other compute paths.

**Total EB monthly cost** = (EC2_hourly × 730 × running_instance_estimate) + ALB_costs (web only) + applicable networking/storage supporting costs. EB itself charges $0 — all costs are the underlying resources.

**EB vs Fargate cost comparison note**: When presenting EB estimates alongside a Fargate alternative, disclose that EB pricing is EC2-instance based while Fargate pricing is task-size based. Use comparable running-capacity assumptions for the Balanced tier.

**EKS vs Fargate cost comparison note**: When presenting EKS estimates alongside the Heroku baseline, include this note:

> "EKS with EC2 nodes is typically cheaper than Fargate for sustained workloads (>60% utilization) because there is no per-pod Fargate surcharge. However, EKS has a higher base cost (`eks.control_plane_monthly` control plane + minimum 2 nodes) and requires Kubernetes operational expertise."

### Cost Tier Calculation

Calculate 3 cost tiers to show the optimization range:

| Tier          | Description              | Adjustments                                                                                                                |
| ------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| **Premium**   | Highest resilience       | Multi-AZ everything, latest-gen instances, no Spot, enhanced monitoring                                                    |
| **Balanced**  | Standard setup (default) | On-demand pricing, Multi-AZ where configured, standard monitoring                                                          |
| **Optimized** | Cost-minimized           | Reserved pricing assumption (20-40% discount), Spot for interruption-tolerant workers (EB or Fargate), S3-IA for cold data |

**Balanced** is the primary comparison tier. Generated Terraform (Phase 5) aligns with **Balanced**.

### Total Cost Calculation

```
total_monthly = sum(individual_resource_costs) — excluding "unpriced" resources
```

Verify: total equals the arithmetic sum of all individually calculated resource costs. This is the **Property 16** invariant.

---

## Part 2B: Observability Cost Estimation (CloudWatch)

Heroku includes basic logging via its log drain. AWS CloudWatch charges from the first GB. This section ensures observability costs are not a surprise.

### Step 1: Estimate Log Volume

Use the per-service log-volume heuristic from [`knowledge/estimate/estimate-defaults.json`](../../../knowledge/estimate/estimate-defaults.json) → `log_volume_gb_per_service` (billing data not applicable for log volume since Heroku's logging model differs). Keyed by service: `fargate_task` (per task), `eb_environment` (per Elastic Beanstalk environment), `rds_or_aurora_instance` (per instance), `alb` (per load balancer), `nat_gateway` (per gateway), `elasticache_node` (per node), `msk_broker` (per broker).

Sum across all applicable services.

### Step 2: Estimate Custom Metrics and Alarms

- `custom_metrics_count = (number of services in aws-design.json × 5)`
- Default floor: 10 custom metrics
- `alarm_count = max(5, number_of_services × 2)` (baseline health/error/latency)

### Step 3: Calculate CloudWatch Costs

```
log_ingestion_cost    = monthly_log_gb × cloudwatch.log_ingestion_per_gb
log_storage_cost      = monthly_log_gb × cloudwatch.log_storage_per_gb_month × retention_months (use preferences.operational.log_retention_days / 30, default: 1)
custom_metrics_cost   = custom_metrics_count × cloudwatch.custom_metric_month
alarms_cost           = alarm_count × cloudwatch.standard_alarm_month
tracing_cost          = 0 (do not add X-Ray costs unless tracing detected in source)

total_observability   = log_ingestion_cost + log_storage_cost + custom_metrics_cost + alarms_cost + tracing_cost
```

(All `cloudwatch.*` rates are in `references/vendored/pricing/aws-infra-pricing.json`.)

### Step 4: Add Observability Entry

Add to `projected_costs.breakdown`:

```json
{
  "service": "CloudWatch + X-Ray (Observability)",
  "low": "<total × 0.7>",
  "mid": "<total>",
  "high": "<total × 1.5>",
  "accuracy": "±30%",
  "pricing_source": "cached",
  "components": {
    "log_ingestion": "<log_ingestion_cost>",
    "log_storage": "<log_storage_cost>",
    "custom_metrics": "<custom_metrics_cost>",
    "alarms": "<alarms_cost>",
    "tracing": "<tracing_cost>"
  },
  "volume_source": "heuristic",
  "note": "Heroku includes basic logging at no extra charge. CloudWatch charges from the first GB. Actual costs depend on log verbosity and retention."
}
```

This entry REPLACES any CloudWatch entries in a "Supporting" row — never double-count.

---

## Part 3: Cost Comparison (Heroku vs AWS)

### When a Heroku Baseline Was Determined (any Part 1 source except `"unavailable"`)

The comparison is the point of this phase — it runs whenever Part 1 produced a
baseline, from ANY source. Do not reserve it for billing data: a
`live_prices_plus_cache` or `pricing_cache` baseline yields the same side-by-side
with its accuracy labeled honestly.

Present a side-by-side comparison:

- **Heroku current monthly total** (from Part 1's baseline, labeled with `current_costs.source` and its accuracy; when derived rather than invoiced, repeat the `baseline_note` caveat next to the number)
- **AWS Premium / Balanced / Optimized monthly totals**
- **Difference** (savings or increase) per tier vs Heroku — monthly and annual
- **Per-app breakdown** for the Balanced tier: for each Heroku app, show:
  - Current Heroku spend — from `billing_profile.line_items` filtered by app
    (billing source), or from that app's summed live prices + cache dyno rates
    (derived sources)
  - Projected AWS spend (sum of services mapped from that app)
  - Difference

Include in `estimation-infra.json`:

```json
"cost_comparison": {
  "heroku_monthly_baseline": "<Part 1 baseline total>",
  "baseline_source": "<current_costs.source>",
  "option_a_premium": {
    "aws_monthly": "<premium total>",
    "monthly_difference": "<premium - heroku>",
    "annual_difference": "<(premium - heroku) × 12>",
    "percent_change": "<+/-X%>"
  },
  "option_b_balanced": {
    "aws_monthly": "<balanced total>",
    "monthly_difference": "<balanced - heroku>",
    "annual_difference": "<(balanced - heroku) × 12>",
    "percent_change": "<+/-X%>"
  },
  "option_c_optimized": {
    "aws_monthly": "<optimized total>",
    "monthly_difference": "<optimized - heroku>",
    "annual_difference": "<(optimized - heroku) × 12>",
    "percent_change": "<+/-X%>"
  }
}
```

### When NO Baseline Was Determined (`current_costs.source == "unavailable"`)

Omit the `cost_comparison` section or set `heroku_monthly_baseline` to null. Present AWS costs without comparison. State: "Heroku baseline unavailable — showing projected AWS costs only. Run live discovery (or provide Heroku invoices) and re-run to see the side-by-side comparison."

---

## Part 4: Migration Cost Considerations

Heroku does not charge egress fees for data transfer during migration (unlike GCP). However, there may be time-based costs during parallel operation.

Key this section off baseline presence (any Part 1 source except `"unavailable"`), not billing data specifically — a derived baseline prices the dual-run window just as well, with the same accuracy caveat as the baseline itself.

### IF a Heroku baseline WAS determined:

```json
"migration_cost_considerations": {
  "baseline_available": true,
  "baseline_source": "<current_costs.source>",
  "categories": [
    "Heroku platform fees during parallel operation (both Heroku and AWS running simultaneously during cutover window): ~<Part 1 baseline total>/month for the duration of the cutover"
  ],
  "note": "Heroku charges are subscription-based. During migration, both Heroku and AWS costs apply until Heroku apps are decommissioned. No data transfer egress fees from Heroku."
}
```

When the baseline is derived (`live_prices_plus_cache` or `pricing_cache`), append to the note: "Dual-run figure is derived from plan prices, not invoices — actual parallel-operation cost may differ by usage-based charges."

### IF NO baseline was determined (`current_costs.source == "unavailable"`):

```json
"migration_cost_considerations": {
  "baseline_available": false,
  "baseline_source": "unavailable",
  "categories": [],
  "note": "Parallel operation costs depend on Heroku spend. Run live discovery (or provide Heroku invoices) for dual-run cost projections."
}
```

---

## Part 5: ROI Analysis

Present monthly and annual cost difference between Heroku baseline and each AWS tier.

- If AWS is cheaper: present monthly and annual savings per tier
- If AWS is more expensive: state clearly and justify with operational benefits

**Operational efficiency factors (qualitative — do not assign dollar values):**

- Full infrastructure control (VPC, security groups, IAM policies)
- Auto-scaling granularity (Fargate service scaling, Aurora auto-scaling)
- Broader AWS service integration (Step Functions, EventBridge, SNS/SQS)
- Cost optimization levers unavailable on Heroku (Spot, Savings Plans, Reserved Instances)
- Reduced vendor lock-in risk

**Non-cost benefits:**

- Global infrastructure (25+ AWS regions vs Heroku's limited regions)
- Compliance certifications (SOC2, HIPAA, PCI, FedRAMP) built into AWS services
- Enterprise integration (Direct Connect, Transit Gateway, Organizations)
- Service breadth (200+ AWS services for future workloads)
- Scaling flexibility (auto-scaling, reserved capacity, burst pricing)

```json
"roi_analysis": {
  "recurring_savings": {
    "monthly_difference_balanced": "<aws_balanced - heroku; negative = AWS cheaper>",
    "monthly_difference_optimized": "<aws_optimized - heroku; negative = AWS cheaper>",
    "annual_difference_balanced": "<× 12>",
    "annual_difference_optimized": "<× 12>",
    "note": "Sign convention: difference = AWS minus Heroku, so negative = AWS cheaper. This is the OPPOSITE sign of financial_summary.monthly_savings_* (savings = Heroku minus AWS) — same fact, difference-vs-savings framing. Any presentation of either number MUST label it (e.g. 'AWS is $X/mo cheaper'), never print a bare signed value."
  },
  "operational_efficiency_factors": [...],
  "non_cost_benefits": [...],
  "note": "Heroku parallel-operation fees during migration window are excluded from recurring ROI calculations."
}
```

---

## Part 6: Cost Optimization Opportunities

Present applicable optimizations with estimated savings. These are **incremental post-migration actions** beyond the Balanced on-demand baseline.

**Eligibility, the three-state rendering model, and the required caveats
(baseline-before-committing, Activate credits, mutual exclusion) are defined
in `references/vendored/estimate/ri-sp-eligibility.md`** (vendored from
`skills/shared/estimate/ri-sp-eligibility.md`, kept byte-identical by
`shared:sync`). Execute that file's eligibility matrix and rendering rules as
part of this step — do not restate or fork the eligibility logic here. This
section covers only the heroku-specific JSON entry shapes and gating
thresholds.

The savings ranges + `target_services` gating come from [`knowledge/estimate/estimate-defaults.json`](../../../knowledge/estimate/estimate-defaults.json) → `optimization_savings_ranges` (keys: `compute_savings_plans`, `database_savings_plans`, `rds_reserved_instances`, `dynamodb_reserved_capacity`, `elasticache_reserved_nodes`, `s3_intelligent_tiering`, `fargate_spot`, `ec2_spot`; each carries `savings_percent` / `target_services` / `timing`). Include ONLY opportunities relevant to the designed architecture (per each entry's `target_services` / `timing`), cross-checked against the vendored eligibility matrix — the JSON below is the entry SHAPE; the vendored file is the eligibility SOURCE OF TRUTH when the two ever disagree (e.g. on ElastiCache engine or deployment mode).

**Always render this section**, even when nothing in the design qualifies for an RI or Savings Plan — per the vendored file's three-state model, state explicitly which state the design landed in rather than omitting the section.

**AWS credits do not cover upfront commitment costs.** Promotional/Activate credits cannot be applied to the upfront cost of Reserved Instances or Savings Plans (Partial Upfront or All Upfront) — they only apply to the ongoing discounted hourly rate. State this once whenever this section is presented (chat summary or report), so a customer on Activate credits does not read "up to 66% off" as free.

**Emit in `optimization_opportunities[]`:**

### Compute Savings Plans (when Fargate or Elastic Beanstalk/EC2 in design)

```json
{
  "opportunity": "Compute Savings Plans",
  "type": "compute_savings_plan",
  "target_services": ["Fargate", "Elastic Beanstalk"],
  "savings_percent": "20-66%",
  "savings_monthly": null,
  "commitment": "1-year or 3-year",
  "timing": "post-migration (after 30-90 days of usage data)",
  "implementation_effort": "low",
  "prerequisite": "Establish AWS compute usage baseline before committing",
  "description": "Heroku dyno billing is flat-rate per dyno type. Fargate tasks and EB-backed EC2 usage patterns may differ — establish AWS baseline before Savings Plan commitment. Use Cost Explorer recommendations after 30+ days.",
  "references": [
    "https://aws.amazon.com/savingsplans/compute-pricing/",
    "https://aws.amazon.com/savingsplans/faqs/"
  ]
}
```

### Database Savings Plans (when RDS/Aurora, or DynamoDB in any capacity mode, or ElastiCache Valkey (node-based or serverless) is in design; projected > $50/month)

**Eligibility check before emitting this entry (per the vendored eligibility matrix — this heading and these bullets must not contradict each other):**

- **RDS/Aurora provisioned** — eligible. Mutually exclusive with RDS Reserved Instances on the same instance. **Aurora Serverless v2** — also Database-SP-eligible, with no RI equivalent (no RI product exists for serverless database capacity).
- **DynamoDB — always Database-SP-eligible regardless of capacity mode** (on-demand, provisioned, or Standard-IA). **DynamoDB provisioned, Standard table class specifically** is also RI-eligible via DynamoDB reserved capacity (mutually exclusive with Database SP on the same capacity). **DynamoDB on-demand or Standard-IA** is Database-SP-eligible only; never emit an RI-style entry for on-demand or Standard-IA DynamoDB — AWS explicitly excludes both from reserved capacity.
- **ElastiCache** — Database-SP-eligible **only when the target engine is Valkey**, in either node-based (provisioned) or serverless mode. `heroku-to-aws`'s default Redis mapping targets **Redis OSS**, which is Database-SP-**ineligible regardless of deployment mode** — check the Design phase's actual selected engine before including ElastiCache in this entry's `target_services`. For a confirmed Redis OSS or Memcached target on a **node-based** cluster, do not list ElastiCache here; instead surface an ElastiCache Reserved Nodes-only note. For a confirmed Redis OSS or Memcached target on **ElastiCache Serverless**, no commitment product of any kind applies — Reserved Nodes require a node-based cluster and do not exist for Serverless; state this plainly rather than falling back to the Reserved Nodes note.

```json
{
  "opportunity": "Database Savings Plans",
  "type": "database_savings_plan",
  "target_services": ["RDS", "Aurora"],
  "savings_percent": "up to 35% (serverless) / up to 20% (provisioned)",
  "savings_monthly": "<calculated or null if < $50/mo>",
  "commitment": "1-year no-upfront",
  "timing": "immediately post-migration or after instance right-sizing",
  "implementation_effort": "low",
  "prerequisite": "Confirm target instance class; omit savings_monthly when DB on-demand < $50/month",
  "description": "Heroku Postgres runs 24/7 with predictable usage. Database Savings Plans offer flexibility to change engines/instances post-migration. Mutually exclusive with RDS RIs on same workload. Include DynamoDB and/or ElastiCache in target_services only per the eligibility check above (ElastiCache: Valkey target only).",
  "alternative": {
    "opportunity": "RDS Reserved Instances",
    "type": "rds_reserved_instances",
    "savings_percent": "up to 69%",
    "trade_off": "Locked to specific instance family and region"
  },
  "references": [
    "https://aws.amazon.com/savingsplans/database-pricing/",
    "https://aws.amazon.com/rds/reserved-instances/"
  ]
}
```

### ElastiCache Reserved Nodes (when target engine is Redis OSS or Memcached AND the cluster is node-based/provisioned — Database-SP-ineligible, and Reserved Nodes require a node-based cluster)

**Do not emit this entry for an ElastiCache Serverless target.** Reserved Nodes require creating a node-based cluster; ElastiCache Serverless has no node concept (billed in ECPUs + GB-hours) and cannot use Reserved Nodes regardless of engine. A Redis OSS/Memcached design on Serverless has **no commitment product of any kind** — state that plainly per the vendored file's "truly no commitment product" state, rather than emitting this entry.

```json
{
  "opportunity": "ElastiCache Reserved Nodes",
  "type": "elasticache_reserved_nodes",
  "target_services": ["ElastiCache"],
  "savings_percent": "30-55%",
  "savings_monthly": null,
  "commitment": "1-year or 3-year",
  "timing": "post-migration (after usage baseline)",
  "implementation_effort": "low",
  "prerequisite": "Confirm node type and count are stable before committing; target cluster must be node-based (provisioned), not ElastiCache Serverless",
  "description": "Database Savings Plans do not cover ElastiCache for Redis OSS or Memcached (Valkey-only) — Reserved Nodes are the commitment lever for this target engine on a node-based cluster. Does not apply to ElastiCache Serverless, which has no reservable nodes.",
  "references": [
    "https://aws.amazon.com/elasticache/pricing/"
  ]
}
```

### EC2 Spot for EB SingleInstance Workers (when interruption-tolerant worker dynos exist)

```json
{
  "opportunity": "Spot Instances for EB Worker Environments",
  "type": "ec2_spot",
  "target_services": ["Elastic Beanstalk"],
  "savings_percent": "60-90%",
  "savings_monthly": "<calculated based on worker environment EC2 costs>",
  "commitment": "none",
  "timing": "during migration (for fault-tolerant workers)",
  "implementation_effort": "medium",
  "prerequisite": "Worker tasks must be fault-tolerant and idempotent",
  "description": "Interruption-tolerant persistent EB SingleInstance worker environments can use Spot-backed EC2 capacity. Configure Spot with aws:ec2:instances EnableSpot and related Spot options; do not describe these workers as SQS consumers unless the application actually uses SQS."
}
```

### Fargate Spot (when worker dynos exist)

```json
{
  "opportunity": "Fargate Spot for Worker Tasks",
  "type": "fargate_spot",
  "target_services": ["Fargate"],
  "savings_percent": "60-70%",
  "savings_monthly": "<calculated based on worker task costs>",
  "commitment": "none",
  "timing": "during migration (for fault-tolerant workers)",
  "implementation_effort": "medium",
  "prerequisite": "Worker tasks must be fault-tolerant and idempotent",
  "description": "Heroku worker dynos mapped to Fargate can use Spot pricing for background/batch work that tolerates interruption."
}
```

Only include optimizations relevant to the designed architecture. Do not include EC2-specific optimizations if no Elastic Beanstalk/EC2 in design.

**No eligible commitment product (per the vendored file's three-state model):** if the design contains nothing from the eligibility matrix's RI/SP-eligible or SP-only rows (e.g. an all-Lambda-equivalent or fully managed-service design with no Fargate/EB/EC2/RDS/Aurora/DynamoDB/ElastiCache), state this explicitly in the section rather than omitting it: "No 1-year/3-year commitment product applies to this architecture." `optimization_opportunities` may be an empty array in this case — do not fabricate an entry to avoid an empty list. Do not silently skip Part 6.

---

## Part 7: Complexity Tier Classification

Load the tier thresholds declared in `_knowledge` (`references/vendored/estimate/complexity-tiers.json`). Classify using these inputs from the current artifacts:

| Input                | Source                                                                            | Key                                                                                                   |
| -------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Service count        | `aws-design.json`                                                                 | `metadata.total_services`                                                                             |
| Monthly spend        | `estimation-infra.json` (just calculated) or `billing_profile.total_monthly_cost` | Projected AWS balanced monthly                                                                        |
| Has databases        | `aws-design.json → services[]`                                                    | `aws_service` in {RDS PostgreSQL, Aurora PostgreSQL, ElastiCache Redis, Amazon MQ, Amazon OpenSearch} |
| Has stateful storage | `aws-design.json → services[]`                                                    | `aws_service` in {S3} with replication hints                                                          |
| Availability         | `preferences.json`                                                                | `global.availability`                                                                                 |
| Compliance           | `preferences.json`                                                                | `global.compliance`                                                                                   |
| Multi-region         | `aws-design.json → services[]`                                                    | More than one distinct `aws_config.region` value                                                      |

**Evaluate from Large down to Small (first match wins):**

### Large — ANY of:

- Service count ≥ 9
- Monthly spend > $10,000
- Multi-region deployment (services span 2+ AWS regions)
- Compliance requirements present (`compliance` is not `"none"`)

### Medium — NOT Large, and ANY of:

- Service count 4–8
- Monthly spend $1,000–$10,000
- Has databases
- Availability is `"multi-az"` or `"multi-az-ha"`

### Small — NOT Large, NOT Medium (ALL of):

- Service count ≤ 3
- Monthly spend < $1,000
- No databases or stateful storage with replication
- Availability is `"single-az"` or unspecified
- No compliance requirements

Include in `estimation-infra.json`:

```json
{
  "complexity_tier": "small|medium|large",
  "complexity_inputs": {
    "service_count": "<N>",
    "monthly_spend": "<projected balanced>",
    "has_databases": true|false,
    "has_stateful_storage": true|false,
    "availability": "<from preferences>",
    "compliance": "<from preferences>",
    "multi_region": true|false
  }
}
```

**Timeline guidance** (infrastructure path):

| Tier   | Weeks | Approach                            |
| ------ | ----- | ----------------------------------- |
| Small  | 2-6   | Compressed                          |
| Medium | 6-12  | Phased cluster migration            |
| Large  | 12-18 | Phased cluster migration (extended) |

---

## Part 8: Recommendation

Present 3 paths:

1. **Migrate with Optimizations (Best ROI)** — optimized service choices, projected savings
2. **Phased Migration (Lower Risk)** — app-by-app per design order, validate each before proceeding
3. **Stay on Heroku** — when the evidence favors staying: AWS materially more expensive without offsetting operational benefit, team leverage from Heroku's managed simplicity with no AWS-specific need, or migration cost/risk exceeding the projected benefit for this stack. **Do not gate "stay" on "cost is the sole metric"** — any decisive factor suffices.

Include migrate/stay decision factors:

- **Migrate if:** infrastructure control matters, AWS-specific services needed, compliance requirements exceed Heroku's offerings, scaling beyond Heroku limits, long-term cost optimization (Savings Plans, Spot)
- **Stay if:** AWS is more expensive without an offsetting benefit for this stack, team benefits from Heroku's managed simplicity, no need for AWS-specific services, migration risk exceeds benefit

### Decision outcome (write alongside `path`)

`path` says how a migration would run; `outcome` says whether to run it now. **`defer_for_evidence` is expected to be RARE** — AWS almost always has the services and the AWS-side estimate can almost always be produced; when in doubt, prefer `conditional_go` with named conditions.

**Hard triggers — any one forces `outcome: "defer_for_evidence"`:**

| # | Trigger                                                                                                                                                                                      | Evidence to name                                                |
| - | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 1 | GovCloud-class compliance ambiguity: compliance unknown AND signals suggest FedRAMP/government requirements — GovCloud vs commercial changes regions, service catalog, and pricing wholesale | Compliance confirmation from the user's legal/compliance owner  |
| 2 | The user's **only** stated motivation is cost savings AND no spend signal exists at all (`billing_profile.available == false` AND the user declined to state Heroku spend)                   | Heroku invoice/billing export, or a stated monthly spend figure |

**Soft triggers — never force defer; add each to `conditions[]` (outcome becomes `conditional_go` instead of `go`) and to `would_flip_if[]`:**

| # | Trigger                                                                                          | Condition wording (adapt to stack)                                                  |
| - | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| 3 | `database_ha` or availability posture resolved by default/plan-tier, never user-confirmed        | "Confirm the availability requirement — Multi-AZ roughly doubles the database line" |
| 4 | `migration_approach` defaulted while the stack has Postgres over ~100GB or zero-downtime signals | "Confirm cutover approach — pg_dump default may not fit this database"              |
| 5 | Pricing staleness beyond the vendored rate card's accuracy band                                  | "Refresh pricing before treating the dollar delta as decision-grade"                |

**Outcome derivation:**

```
IF any hard trigger fired          -> outcome: "defer_for_evidence"
ELSE IF path == "stay"             -> outcome: "stay"
ELSE IF any soft trigger fired     -> outcome: "conditional_go" (conditions[] = fired soft triggers)
ELSE                               -> outcome: "go"
```

Complexity alone selects `path: "migrate_phased"` — it never moves `outcome` away from go/conditional_go. Populate `decision_basis` from provenance: billing/inventory-extracted values → measured; defaulted → assumed; declined/unknown → unknown. Populate `would_flip_if[]` with the 1–3 changes most likely to alter the outcome.

**Presenting a defer (lead with what IS established):** open with what the assessment did determine — "AWS can host this stack; the AWS-side estimate is $X–$Y/mo" — before naming the one missing piece of evidence and how to obtain it. Never present defer as "no answer."

### Persist recommendation to estimation-infra.json

```json
"recommendation": {
  "path": "migrate_optimized|migrate_phased|stay",
  "path_label": "Migrate with Optimizations|Phased Migration|Stay on Heroku",
  "outcome": "go|conditional_go|defer_for_evidence|stay",
  "outcome_label": "Go|Go, with conditions|Defer — get evidence|Stay on Heroku",
  "roi_justification": "<one-sentence ROI case>",
  "confidence": "high|medium|low",
  "migrate_if": ["<factors specific to THIS stack>"],
  "stay_if": ["<factors specific to THIS stack>"],
  "conditions": ["<REQUIRED non-empty when outcome is conditional_go — one per fired soft trigger>"],
  "decision_basis": {
    "measured": ["<evidence from billing/inventory>"],
    "assumed": ["<defaulted inputs feeding this estimate>"],
    "unknown": ["<unconfirmed inputs>"]
  },
  "would_flip_if": ["<1-3 changes most likely to alter the outcome, with direction>"],
  "next_steps": ["<actionable items>"]
}
```

Readers of pre-extension artifacts must tolerate absent v2 fields (`outcome`, `conditions`, `decision_basis`, `would_flip_if`) and fall back to `path`. `outcome: "stay"` only with `path: "stay"`.

**Path selection logic:**

| Scenario                                     | `path` value          | `path_label`                   |
| -------------------------------------------- | --------------------- | ------------------------------ |
| AWS cheaper or operational benefits justify  | `"migrate_optimized"` | `"Migrate with Optimizations"` |
| Complex stack, app-by-app safer              | `"migrate_phased"`    | `"Phased Migration"`           |
| AWS more expensive AND costs are sole metric | `"stay"`              | `"Stay on Heroku"`             |

When Parts 1–8 are complete, control passes to the assembler (`estimate-assemble.md`) to
write `estimation-infra.json`, run the handoff gate, and update phase status.

---

## Pricing Recipes (Reference Only)

These recipes are reference documentation for services not in `references/vendored/pricing/aws-infra-pricing.json`. No live MCP pricing is available; use cached rates and set `pricing_source: "unavailable"` for any service missing from the cache.

| AWS Service       | service_code      | filters                                                                                                     | output_options                                                                                                                                     |
| ----------------- | ----------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fargate           | AmazonECS         | `[{"Field":"productFamily","Value":"Compute"}]`                                                             | `{"pricing_terms":["OnDemand"],"product_attributes":["usagetype","location"],"exclude_free_products":true}`                                        |
| Aurora PostgreSQL | AmazonRDS         | `[{"Field":"databaseEngine","Value":"Aurora PostgreSQL"},{"Field":"deploymentOption","Value":"Single-AZ"}]` | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","databaseEngine","deploymentOption","location"],"exclude_free_products":true}` |
| RDS PostgreSQL    | AmazonRDS         | `[{"Field":"databaseEngine","Value":"PostgreSQL"},{"Field":"deploymentOption","Value":"Multi-AZ"}]`         | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","databaseEngine","deploymentOption","location"],"exclude_free_products":true}` |
| ElastiCache Redis | AmazonElastiCache | `[{"Field":"cacheEngine","Value":"Redis"},{"Field":"instanceType","Value":"cache.t4g","Type":"CONTAINS"}]`  | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","cacheEngine","location"],"exclude_free_products":true}`                       |
| S3                | AmazonS3          | `[{"Field":"storageClass","Value":"General Purpose"}]`                                                      | `{"pricing_terms":["OnDemand"],"product_attributes":["storageClass","volumeType","location"],"exclude_free_products":true}`                        |
| ALB               | AWSELB            | `[{"Field":"productFamily","Value":"Load Balancer-Application"}]`                                           | `{"pricing_terms":["OnDemand"],"product_attributes":["productFamily","location"],"exclude_free_products":true}`                                    |
| NAT Gateway       | AmazonEC2         | `[{"Field":"productFamily","Value":"NAT Gateway"}]`                                                         | `{"pricing_terms":["OnDemand"],"product_attributes":["productFamily","location","group"],"exclude_free_products":true}`                            |
| CloudWatch Logs   | AmazonCloudWatch  | `[{"Field":"usagetype","Value":"DataProcessing-Bytes"}]`                                                    | `{"pricing_terms":["OnDemand"],"product_attributes":["productFamily","location","usagetype"],"exclude_free_products":true}`                        |
| Secrets Manager   | AWSSecretsManager | `[]`                                                                                                        | `{"pricing_terms":["OnDemand"],"exclude_free_products":true}`                                                                                      |
| MSK               | AmazonMSK         | `[{"Field":"productFamily","Value":"Managed Streaming for Apache Kafka"}]`                                  | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","location"],"exclude_free_products":true}`                                     |
| Amazon MQ         | AmazonMQ          | `[{"Field":"productFamily","Value":"Broker Instances"}]`                                                    | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","location"],"exclude_free_products":true}`                                     |
| OpenSearch        | AmazonES          | `[{"Field":"productFamily","Value":"Compute Instance"}]`                                                    | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","location"],"exclude_free_products":true}`                                     |

**Batching rule:** Group up to 4 MCP requests in parallel per turn.

**Important notes:**

- **Aurora**: Use `deploymentOption=Single-AZ` — Aurora handles multi-AZ natively, no "Multi-AZ" pricing option
- **Fargate**: Use `productFamily=Compute`, NOT EC2-style filters
- **CloudWatch**: Filter by `usagetype=DataProcessing-Bytes` for log ingestion pricing
