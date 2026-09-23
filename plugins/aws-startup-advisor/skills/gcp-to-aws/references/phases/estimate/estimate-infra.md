# Estimate Phase: Infrastructure Cost Analysis

> Loaded by estimate.md when aws-design.json exists.

**Execute ALL steps in order. Do not skip or optimize.**

## Pricing Mode

The parent `estimate.md` determines pricing source before loading this file.

**Price lookup order for each AWS service in `aws-design.json`:**

1. **`shared/pricing-cache.md` (primary)** — Read once. Set `pricing_source.status: "cached"`. **Before using, check staleness:** compute `days_since_cache = today − cache "Last updated" date`. If `days_since_cache > 30`, keep `status: "cached"` (the schema enum is `cached | cached_fallback | unavailable`; there is no `cached_stale` status) and flag staleness in `pricing_source.fallback_staleness` — set `is_stale: true` and `staleness_warning: "Pricing cache is more than 30 days old — AI model prices may have changed. Verify against aws.amazon.com/bedrock/pricing."` — then prepend that warning to the estimate output. Infrastructure prices (Fargate, RDS, S3, etc.) remain reliable; only AI model prices are affected by staleness. If `days_since_cache ≤ 30`, use the price directly with `is_stale: false`.
2. **Unavailable** — If a service is NOT in the cache, set `pricing_source: "unavailable"`. Add to `services_with_missing_fallback` and warn the user.

For typical migrations (Fargate, Aurora/RDS, Aurora Serverless v2, S3, ALB, NAT Gateway, Lambda, Secrets Manager, CloudWatch, ElastiCache, DynamoDB), ALL prices are in `pricing-cache.md`. Zero MCP calls needed.

## Step 0: Validate Design Output

Before pricing queries, validate `aws-design.json`:

1. **File exists**: If missing, **STOP**. Output: "Phase 3 (Design) not completed. Run Phase 3 first."
2. **Valid JSON**: If parse fails, **STOP**. Output: "Design file corrupted (invalid JSON). Re-run Phase 3."
3. **Required fields**:
   - `clusters` array is not empty: If empty, **STOP**. Output: "No clusters in design. Re-run Phase 3."
   - Each cluster has `resources` array: If missing, **STOP**. Output: "Cluster [id] missing resources. Re-run Phase 3."
   - Each resource has `aws_service` field: If missing, **STOP**. Output: "Resource [address] missing aws_service. Re-run Phase 3."
   - Each resource has `aws_config` field: If missing, **STOP**. Output: "Resource [address] missing aws_config. Re-run Phase 3."

If all validations pass, proceed to Part 1.

## Pricing Recipes (Reference Only — Cache Is Primary)

Pricing is cache-only. The table below is retained as a reference for service codes but
should NOT be used to call any live pricing MCP (none is configured).

| AWS Service          | service_code      | filters                                                                                                                                                                                                                                  | output_options                                                                                                                                     |
| -------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fargate              | AmazonECS         | `[{"Field":"productFamily","Value":"Compute"}]`                                                                                                                                                                                          | `{"pricing_terms":["OnDemand"],"product_attributes":["usagetype","location"],"exclude_free_products":true}`                                        |
| Aurora PostgreSQL    | AmazonRDS         | `[{"Field":"databaseEngine","Value":"Aurora PostgreSQL"},{"Field":"deploymentOption","Value":"Single-AZ"}]`                                                                                                                              | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","databaseEngine","deploymentOption","location"],"exclude_free_products":true}` |
| RDS PostgreSQL       | AmazonRDS         | `[{"Field":"databaseEngine","Value":"PostgreSQL"},{"Field":"deploymentOption","Value":"Multi-AZ"}]`                                                                                                                                      | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","databaseEngine","deploymentOption","location"],"exclude_free_products":true}` |
| Aurora MySQL         | AmazonRDS         | `[{"Field":"databaseEngine","Value":"Aurora MySQL"},{"Field":"deploymentOption","Value":"Single-AZ"}]`                                                                                                                                   | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","databaseEngine","deploymentOption","location"],"exclude_free_products":true}` |
| Aurora Serverless v2 | AmazonRDS         | `[{"Field":"usagetype","Value":["Aurora:ServerlessV2Usage","Aurora:ServerlessV2IOOptimizedUsage"],"Type":"ANY_OF"}]`                                                                                                                     | `{"pricing_terms":["OnDemand"],"product_attributes":["usagetype","databaseEngine","location"],"exclude_free_products":true}`                       |
| S3                   | AmazonS3          | `[{"Field":"storageClass","Value":"General Purpose"}]`                                                                                                                                                                                   | `{"pricing_terms":["OnDemand"],"product_attributes":["storageClass","volumeType","location"],"exclude_free_products":true}`                        |
| ALB                  | AWSELB            | `[{"Field":"productFamily","Value":"Load Balancer-Application"}]`                                                                                                                                                                        | `{"pricing_terms":["OnDemand"],"product_attributes":["productFamily","location"],"exclude_free_products":true}`                                    |
| NAT Gateway          | AmazonEC2         | `[{"Field":"productFamily","Value":"NAT Gateway"}]`                                                                                                                                                                                      | `{"pricing_terms":["OnDemand"],"product_attributes":["productFamily","location","group"],"exclude_free_products":true}`                            |
| Lambda               | AWSLambda         | `[{"Field":"group","Value":"AWS-Lambda-Duration"}]`                                                                                                                                                                                      | `{"pricing_terms":["OnDemand"],"product_attributes":["group","location","usagetype"],"exclude_free_products":true}`                                |
| Secrets Manager      | AWSSecretsManager | `[]`                                                                                                                                                                                                                                     | `{"pricing_terms":["OnDemand"],"exclude_free_products":true}`                                                                                      |
| CloudWatch Logs      | AmazonCloudWatch  | `[{"Field":"usagetype","Value":"DataProcessing-Bytes"}]`                                                                                                                                                                                 | `{"pricing_terms":["OnDemand"],"product_attributes":["productFamily","location","usagetype"],"exclude_free_products":true}`                        |
| ElastiCache Redis    | AmazonElastiCache | `[{"Field":"cacheEngine","Value":"Redis"},{"Field":"instanceType","Value":"cache.t4g","Type":"CONTAINS"}]`                                                                                                                               | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","cacheEngine","location"],"exclude_free_products":true}`                       |
| EC2 (Graviton/x86)   | AmazonEC2         | `[{"Field":"instanceType","Value":"<m7g.xlarge or x86 equivalent>"},{"Field":"operatingSystem","Value":"Linux"},{"Field":"tenancy","Value":"Shared"},{"Field":"preInstalledSw","Value":"NA"},{"Field":"capacitystatus","Value":"Used"}]` | `{"pricing_terms":["OnDemand"],"product_attributes":["instanceType","location"],"exclude_free_products":true}`                                     |
| DynamoDB             | AmazonDynamoDB    | `[]`                                                                                                                                                                                                                                     | `{"pricing_terms":["OnDemand"],"product_attributes":["group","location"],"exclude_free_products":true}`                                            |

**Important notes on MCP filters:**

- **Fargate**: Use `productFamily=Compute`, NOT EC2-style filters (operatingSystem, tenancy, capacitystatus do not exist in AmazonECS)
- **Aurora (PostgreSQL/MySQL)**: Use `deploymentOption=Single-AZ`. Aurora handles multi-AZ replication natively — there is no "Multi-AZ" pricing option for Aurora
- **Lambda**: Filter by `group=AWS-Lambda-Duration` for compute pricing, separate call with `group=AWS-Lambda-Requests` for request pricing
- **CloudWatch**: Filter by specific `usagetype=DataProcessing-Bytes` for log ingestion pricing (avoids pulling all vended log types)

**Batching rule:** If MCP calls are needed, group up to 4 requests in parallel per turn.

---

## Part 1: Calculate Current GCP Costs

Determine the current GCP monthly infrastructure costs. Use the best available source:

1. **`billing-profile.json` (preferred)** — Use actual billing data as the GCP baseline. Highest confidence (±5%).
2. **`gcp-resource-inventory.json` (fallback)** — Derive costs from discovered
   resource sizing using `references/shared/gcp-infra-pricing-cache.md` — never
   from remembered GCP prices. Wider range (±20-30%). Procedure:
   - For each inventory resource, apply the matching rate-card derivation
     (Cloud SQL tier decoding × HA multiplier + disk; Memorystore GB × tier
     band; GCE/GKE-node machine types × 730; GKE cluster fee). Config field
     names may be capture-shaped (`settings.tier`, `settings.dataDiskSizeGb`,
     `memorySizeGb`) or Terraform-shaped (`tier`, `disk_size`) — resolve
     either.
   - Resources the rate card marks NOT derivable (Cloud Run, Functions,
     Pub/Sub, buckets, Autopilot, egress) are EXCLUDED from the total with
     reason `"usage_based"`; name each in `warnings[]` with: "usage-based —
     not derivable from sizing; provide a billing export for the full
     baseline." (Exclusion reason enum: `usage_based`, `no_standing_charge`,
     `unpriced_gcp` — nothing else.)
   - A sized resource whose rate is missing from the card → `"unpriced_gcp"`,
     excluded, warned. Never guess a rate. When `settings.dataDiskType` is
     absent, assume `PD_SSD` (the Cloud SQL default) and say so in the
     derivation entry. When `settings.backupConfiguration.enabled` is true,
     add a backup-storage line using the card's backup rate against the
     provisioned disk size as an upper bound, labeled "(backup upper bound)".
   - No-standing-charge resources (VPC networks/subnets, service accounts,
     IAM, secrets at trivial volume) are excluded with reason
     `"no_standing_charge"` — NOT the usage-based warning.
   - Set `current_costs.source: "inventory_estimate"` (the value
     `schema-estimate-infra.md` already enumerates) and
     `current_costs.accuracy: "±20-30%"`.
   - Shape: `current_costs.breakdown` stays the schema's category-keyed map
     (`compute` / `database` / `cache` / `storage` / ...); record the
     per-resource arithmetic in an additive `current_costs.derivation[]`
     array (address, resolved config, calculation string, monthly), and the
     exclusions in `current_costs.excluded_resources[]` +
     `current_costs.warnings[]`.
   - `baseline_note` (mandatory): "Derived from discovered resource sizing ×
     GCP list rates — not a bill. Excludes usage-based services (Cloud Run,
     bandwidth, storage volume), sustained-use/committed-use discounts, and
     credits; your invoice may differ materially."
3. **`preferences.json` → `gcp_monthly_spend`** — User-provided monthly spend from clarification.
4. **Ask the user** — If none of the above are available, ask: "I need your current GCP monthly spend to produce a meaningful cost comparison. What is your approximate GCP monthly infrastructure cost?" Use the user's answer. If the user declines or is unsure, present AWS costs without a GCP comparison and note: "GCP baseline unavailable — AWS costs shown without comparison."

Present the GCP baseline as a total and per-service breakdown, noting which source was used.

**Baseline-quality display label (derived from `current_costs.source` — no new field):**

| `current_costs.source` | Display label                                                                                   |
| ---------------------- | ----------------------------------------------------------------------------------------------- |
| `"billing_data"`       | "Measured from your GCP billing (±5%)"                                                          |
| `"inventory_estimate"` | "Estimated from resource configs (±20–30%) — standing charges only; excludes usage-based costs" |
| `"preferences"`        | "Your stated spend band from Clarify (midpoint used)"                                           |
| `"user_provided"`      | "Your stated figure (unverified)"                                                               |
| `"unavailable"`        | "No GCP baseline — AWS costs shown without comparison"                                          |

**Not-comparable rule (hard):** Never present an inventory-only GCP figure side-by-side with a user spend band (or vice versa) as if they measure the same thing — an inventory estimate captures standing charges for discovered resources, not the full bill. When both exist and disagree by more than the accuracy band, show both, labeled, with one line: "These measure different things — the billing figure (or your stated band) is the decision baseline; the inventory figure only covers discovered resources." Every GCP-vs-AWS comparison row states its baseline label.

### CUD-Aware Baseline (when billing data available)

If `billing-profile.json` contains `commitments.has_active_cuds == true`:

1. **Use list price as the GCP baseline**: The `services[].monthly_cost` values already use list price (commitment fee rows excluded by discover phase). Use `cost_basis.total_at_list` as the total GCP baseline for comparison.
2. **Do not include commitment fees in workload costs**: Commitment fee rows are billing artifacts with no AWS equivalent — they are already excluded from `services[]`.
3. **Record the effective discount for Part 3**: Note `commitments.effective_discount_percent` — this is the customer's current GCP discount rate that will be compared against AWS Savings Plan rates.

This ensures the comparison is GCP list price vs. AWS on-demand (both uncommitted baselines), with commitment options presented separately as optimization opportunities.

---

## Part 2: Calculate Projected AWS Costs

**Security baseline coverage (always required):** Add a `security_baseline` entry to `projected_costs.breakdown` with `service: "AWS Security Baseline (Tier 1)"`, low/mid/high estimates of $3/$15/$30 per month, `accuracy: "±25%"`, and a `components` sub-object breaking down CloudTrail S3 storage (~$1.50/mo mid), GuardDuty (~~$13/mo mid after free trial), AWS Budgets ($0), and the free controls. If `preferences.json.compliance` contains any of `soc2`, `pci`, `hipaa`, `fedramp`, also add a sibling `security_baseline_compliance` entry with low/mid/high estimates of $3/$14/$25 per month, `accuracy: "±25%"`, `emission_reason` field citing the declared compliance values, and a `components` sub-object breaking down AWS Config (~$6/mo mid continuous), Config S3 storage (~~ $0.50/mo mid), Security Hub + FSBP (~$7/mo mid after free trial), and extra standards (free). Per-unit rates are grounded in the AWS Pricing API for us-east-1 as of 2026-05-04 (Config pricing effective 2025-09-01, Security Hub effective 2026-03-01). Cite source as `references/shared/pricing-cache.md § Security Baseline`. Both line items are added as flat additives to each tier total (Premium/Balanced/Optimized) rather than being tier-dependent.

For each service in `aws-design.json`, calculate monthly cost using rates from `pricing-cache.md`. Track `pricing_source` per service.

**Secret Manager coverage (mandatory):** If any mapped resource has `gcp_type` of `google_secret_manager_secret` or `google_secret_manager_secret_version`, ensure an `aws_service` entry for **Secrets Manager** is present in the estimate breakdown. Do not collapse this into a generic "supporting" line item.

**BigQuery / deferred analytics (mandatory):** For any resource where `aws_service` is exactly **`Deferred — specialist engagement`** OR `gcp_type` starts with `google_bigquery_`:

- **Do not** apply Athena, Redshift, Glue, or EMR rates as the plugin’s “projected” analytics stack.
- **Exclude** these resources from Premium / Balanced / Optimized **numeric totals** (or list them under a `deferred_services[]` / `excluded_from_totals` section in `estimation-infra.json` with reason: _pending specialist engagement_).
- In the user-facing summary, state that **AWS analytics costs are unknown** until the **AWS account team** and/or **data analytics migration partner** defines the target architecture.

Calculate 3 cost tiers to show the optimization range:

| Tier          | Description                             | Examples                                                            |
| ------------- | --------------------------------------- | ------------------------------------------------------------------- |
| **Premium**   | Latest generation, highest availability | db.r6g instances, Fargate Spot disabled, Multi-AZ everything        |
| **Balanced**  | Standard generation, typical setup      | db.t4g instances, Fargate on-demand, Single-AZ where acceptable     |
| **Optimized** | Cost-minimized with trade-offs          | db.t4g with reserved pricing, Fargate Spot 70%, S3-IA for cold data |

**Per-service calculation approach:**

| Domain                      | Formula                                                                                                                                                                                                                                                                      | Key inputs from aws-design.json                                                       |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Compute (Fargate)           | (vCPU × vCPU rate + memory GB × memory rate) × 730 hours × instance count                                                                                                                                                                                                    | `aws_config.cpu`, `aws_config.memory`                                                 |
| Compute (Lambda)            | requests × request rate + (requests × duration × memory GB) × GB-second rate                                                                                                                                                                                                 | Estimated from usage patterns                                                         |
| Compute (Elastic Beanstalk) | EC2 rate for `instance_type` (EC2 pricing rows) × 730 hours × `min_instances` + ALB fixed monthly + LCU estimate **when `environment_type == "LoadBalanced"`** (SingleInstance has no ALB). EB service fee is $0. One line item per EB environment (per App Engine service). | `aws_config.instance_type`, `aws_config.min_instances`, `aws_config.environment_type` |
| Database (Aurora)           | instance rate × 730 hours × instance count + storage GB × storage rate + I/O estimate                                                                                                                                                                                        | `aws_config.instance_class`, `aws_config.allocated_storage`                           |
| Database (RDS)              | instance rate × 730 hours × instance count + storage GB × storage rate                                                                                                                                                                                                       | `aws_config.instance_class`, `aws_config.allocated_storage`                           |
| Storage (S3)                | GB × per-GB rate + request estimates                                                                                                                                                                                                                                         | `aws_config.storage_gb` or source `gcp_config`                                        |
| Networking (ALB)            | fixed monthly + LCU estimate. **Exclude LoadBalanced Elastic Beanstalk environments** — their ALB is already priced in the EB compute row; do not also count them here (EB manages its own LB, with no standalone `aws_lb` resource).                                        | From compute service count, minus LoadBalanced EB environments                        |
| Networking (NAT)            | fixed monthly × count + GB processed × data rate                                                                                                                                                                                                                             | From VPC design                                                                       |
| Security (Secrets Manager)  | secrets_count × per-secret monthly rate + api_calls_10k × per-10K API rate                                                                                                                                                                                                   | `aws_config.secrets_count`, `aws_config.api_calls_10k` (or inferred defaults)         |
| Supporting                  | Per-unit rates × quantities (secrets, log GB, metrics)                                                                                                                                                                                                                       | Inferred from service count                                                           |

Show calculation breakdown per service: rate × quantity = cost. Present all 3 tiers side-by-side.

---

## Part 2B: Observability Cost Estimation (CloudWatch)

GCP Cloud Operations includes a larger free tier for logging (50 GB/month), metrics (150M samples), alerting, and profiling. CloudWatch also has an always-free tier (5 GB logs, 10 custom metrics, 10 alarms, 1M API requests/month — see [AWS CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)), but allowances are smaller. This section estimates costs **above** those free-tier limits so observability is not a surprise post-migration.

**Relationship to Part 2 "Supporting" line item:** The observability entry produced by this section REPLACES any CloudWatch/log/metric portion that would otherwise appear in the "Supporting" row of Part 2. Do NOT include CloudWatch log ingestion, metrics, or alarms in the Supporting line item — they are fully covered here. Supporting retains only Secrets Manager and any non-observability per-unit charges.

### Pricing source

All rates from `pricing-cache.md § CloudWatch` and `§ X-Ray`. No MCP calls needed.

### Step 1: Determine log volume

**IF billing data IS available** (`billing-profile.json` exists):

Check for Cloud Logging line items:

- Look for `services[].sku` containing `Log Volume`, `Logging`, or `Cloud Logging`
- Extract volume in GiB from the SKU quantity/units field directly (preferred)
- OR derive from GCP cost: `gcp_logging_cost ÷ $0.50/GiB` (GCP's own list rate above free tier) = volume above free tier, then add 50 GiB for the free portion
- **Important:** Use GCP's own rate ($0.50/GiB) to reverse-engineer volume from GCP billing — not AWS rates. Apply AWS rates ($0.50/GB Standard) to the derived volume for the projected cost.
- Set `observability.log_volume_source: "billing"`

**IF billing data is NOT available:**

Use the per-service heuristic table to estimate monthly log volume:

| AWS Service (from aws-design.json) | Estimated log volume/month | Basis                                                                                                                                                  |
| ---------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Fargate task                       | 3 GB per task              | Container stdout/stderr, request logs                                                                                                                  |
| Elastic Beanstalk environment      | 3 GB per environment       | App stdout/stderr + EB platform/deploy logs (one per App Engine service)                                                                               |
| Lambda function                    | 0.2 GB per function        | Invocation logs at INFO level                                                                                                                          |
| RDS/Aurora instance                | 1 GB per instance          | Error log + slow query (audit log off)                                                                                                                 |
| RDS/Aurora instance (audit on)     | 8 GB per instance          | If source has `pgaudit.log`, `log_statement = 'all'`, `cloudsql.log_min_duration_statement`, or explicit audit/general log database flags in Terraform |
| ALB                                | 2 GB per load balancer     | Access logs (if enabled)                                                                                                                               |
| NAT Gateway                        | 1 GB per gateway           | Flow logs (if enabled)                                                                                                                                 |
| ElastiCache                        | 0.5 GB per node            | Slow log only                                                                                                                                          |

**RDS audit detection:** Check for database flags in the source `google_sql_database_instance` Terraform that indicate audit logging: `pgaudit.log`, `log_statement = 'all'`, `cloudsql.log_min_duration_statement`, or general/audit log flags for MySQL. Do NOT use `cloudsql.iam_authentication` as an audit proxy — IAM auth is access control, not audit logging.

Sum all applicable services. Set `observability.log_volume_source: "heuristic"`.

### Step 2: Determine custom metrics count

**IF billing data IS available:**

GCP Cloud Monitoring uses sample-based pricing ($0.10/1000 samples above 150M free) which does not map 1:1 to CloudWatch's per-metric-per-month pricing ($0.30/metric/month). Even with billing data, treat custom metrics as heuristic:

- Count `google_monitoring_alert_policy` resources in `gcp-resource-inventory.json` as a proxy for custom metric complexity
- Multiply alert policy count × 3 (typical metrics per alert: threshold metric + 2 related dimensions)
- Set `observability.metrics_source: "heuristic"` (even when billing data exists — GCP metric pricing is not cleanly convertible to CloudWatch's model)

**IF billing data is NOT available:**

Use the heuristic: `custom_metrics_count = (number of services in aws-design.json × 5) + (number of alert policies from source × 2)`

Default floor: 10 custom metrics.
Default ceiling for small startups: 50 custom metrics.

Set `observability.metrics_source: "heuristic"`.

### Step 2b: Determine alarm count

Count `google_monitoring_alert_policy` resources in `gcp-resource-inventory.json`.

- If count > 0: `alarm_count = count`
- If count is 0 or no alert policies found: `alarm_count = 5` (baseline — most teams set up basic health/error/latency alarms post-migration)

Set `observability.alarm_count_source: "inventory"` or `"default"`.

### Step 3: Determine tracing usage

**IF billing data IS available:**

Check for Cloud Trace line items:

- Extract span volume from SKU quantity/units field directly (preferred)
- OR derive from GCP cost: `gcp_trace_cost ÷ $0.20/million` (GCP's own list rate above 2.5M free tier) = millions of spans above free tier, then add 2.5M
- **Important:** Use GCP's rate ($0.20/M spans) to reverse-engineer volume from GCP billing. Apply AWS X-Ray rate ($5.00/M traces) to that volume for the projected cost.
- Set `observability.tracing_source: "billing"`

**IF billing data is NOT available:**

Check `gcp-resource-inventory.json` or application code for tracing libraries:

- If OpenTelemetry, `@google-cloud/trace-agent`, or `google.cloud.trace` imports detected: assume 1M spans/month (small app baseline)
- If no tracing signals: set `monthly_spans: 0` (tracing not in use; do not add X-Ray costs)

Set `observability.tracing_source: "heuristic"`.

### Step 4: Calculate CloudWatch costs

Default estimate uses Standard log class ($0.50/GB) for all logs. Infrequent Access ($0.25/GB) is an optimization opportunity surfaced in Step 6, not the baseline assumption.

**Always-free tier (apply before billing):** 5 GB logs (ingestion + archive combined), 10 custom metrics, 10 alarms, 1M API requests/month. Subtract these allowances from derived volumes before applying rates.

```
billable_log_gb       = max(0, monthly_log_gb - 5)
log_ingestion_cost    = billable_log_gb × $0.50
log_storage_cost      = billable_log_gb × $0.03 × retention_months (default: 1)
custom_metrics_cost   = max(0, custom_metrics_count - 10) × $0.30  (flat rate; valid for ≤10K metrics at startup scale)
alarms_cost           = max(0, alarm_count - 10) × $0.10
tracing_cost          = max(0, monthly_spans - 100_000) / 1_000_000 × $5.00  (honors X-Ray 100K/month free tier)
dashboard_cost        = max(0, dashboards - 3) × $3.00  (default: 0 — assume ≤3)

total_observability   = log_ingestion_cost + log_storage_cost + custom_metrics_cost + alarms_cost + tracing_cost + dashboard_cost
```

### Step 5: Add to projected costs

Add an `observability` entry to `projected_costs.breakdown`. This entry REPLACES any CloudWatch/log/metric portion in the "Supporting" row — do not double-count.

```json
{
  "service": "CloudWatch + X-Ray (Observability)",
  "low": <total × 0.7>,
  "mid": <total>,
  "high": <total × 1.5>,
  "accuracy": "±30%",
  "pricing_source": "cached",
  "components": {
    "log_ingestion": <log_ingestion_cost>,
    "log_storage": <log_storage_cost>,
    "custom_metrics": <custom_metrics_cost>,
    "alarms": <alarms_cost>,
    "tracing": <tracing_cost>
  },
  "volume_source": "<billing|heuristic>  (reflects log volume source — the largest cost component; metrics are always heuristic regardless of this field)",
  "note": "GCP Cloud Operations includes 50 GB/month free logging, free alerting, and free profiling. CloudWatch always-free tier includes 5 GB logs, 10 custom metrics, and 10 alarms per month. This estimate assumes workload volume above those limits (especially custom metrics). X-Ray tracing is more expensive than Cloud Trace at scale ($5/M vs $0.20/M). Actual costs depend on log verbosity and retention."
}
```

### Step 6: Surface GCP free tier delta in cost comparison

In Part 3 (Cost Comparison), if observability costs exceed $20/month, add a callout:

> **Observability cost note:** Your GCP Cloud Operations costs may appear low or zero due to generous free tiers (50 GB/month logging, 150M metric samples, free alerting). CloudWatch also has always-free allowances (5 GB logs, 10 metrics, 10 alarms), but they are narrower than GCP's. The CloudWatch estimate of $X/month reflects this workload **above those limits**. Consider:
>
> - Reducing log verbosity (WARN-only for production services) to lower ingestion costs
> - Using CloudWatch Logs Infrequent Access class for non-critical logs ($0.25/GB — 50% cheaper than Standard)
> - Evaluating sampling rate for X-Ray traces (10% sampling = 90% cost reduction)
> - CloudWatch Logs Insights for ad-hoc queries instead of always-on metric filters

### Estimation rules

- Do NOT emit observability costs as $0 without running Step 4 — apply CloudWatch always-free allowances first
- After free-tier adjustments, use the computed total (no artificial floor for small dev stacks within billable limits)
- If tracing is not detected in source, do NOT add X-Ray costs (don't upsell)
- Container Insights is NOT included by default — add only if source uses Cloud Monitoring with per-container metrics or if production-tier observability is required
- The observability line item REPLACES CloudWatch entries in the "Supporting" row — never double-count

---

## Part 2C: Architecture Comparison (Graviton vs x86)

_Run only when_ `preferences.json` → `design_constraints.cpu_architecture.value` is `graviton` or `mixed` (i.e., at least one service targets Graviton). Skip entirely for `x86`.

**Load** `references/shared/graviton.md` (savings model) and `references/shared/schema-graviton.md` (the `architecture_comparison` schema).

Model **only the hourly price discount** — never the performance uplift. For the Balanced tier:

1. Sum the Balanced-tier monthly cost of all Graviton-targeted compute (EC2, Fargate, Lambda, Elastic Beanstalk EC2 instances, and Graviton-family managed services) using `pricing-cache.md` Graviton rows. For any family/size not cached, use the EC2 (Graviton/x86) recipe above. This is `graviton_monthly` (the compute portion).
2. Re-price the **same mapping** on the x86 equivalents (use the `x86 equivalent` column in `pricing-cache.md § EC2`, x86 Fargate/Lambda rates, and the x86 managed-service families). This is `x86_equivalent_monthly`.
3. Compute `savings_amount = x86_equivalent_monthly − graviton_monthly` and `savings_percent = savings_amount / x86_equivalent_monthly × 100` (one decimal).

Emit an `architecture_comparison` block in `estimation-infra.json` per the `schema-graviton.md` schema. This is **not** a fourth pricing tier — Graviton is the architecture within the Balanced/Premium/Optimized tiers, and the Balanced tier totals already reflect Graviton pricing when selected.

**Report consistency:** the migration report must render these exact figures (no recomputation in the report layer). Numeric agreement is currently a **manual self-check** — the post-write report validator (`shared/validate-migration-report.md`) is a structural/readability gate and explicitly does not audit dollar figures. Rendering the Graviton savings in the report and adding an automated `architecture_comparison` numeric assertion to `validate-migration-report.py` are tracked as a **follow-up** (see `shared/graviton.md` → "Report rendering").

---

## Part 3: Cost Comparison

Present a side-by-side comparison:

- GCP current monthly total (at list price)
- AWS Premium / Balanced / Optimized monthly totals
- Difference (savings or increase) per tier vs GCP
- Per-service breakdown for the Balanced tier

### Commitment Context (if CUDs detected)

If `billing-profile.json` has `commitments.has_active_cuds == true`, add a `commitment_context` section to the comparison:

- **GCP effective committed rate**: The customer currently pays `effective_discount_percent`% below list via CUDs
- **AWS equivalent**:
  - **Compute Savings Plans** (Fargate, Lambda, EC2): up to 66% vs On-Demand at maximum term/discount; typical 1-year no-upfront **20–40%**
  - **Database Savings Plans** (Aurora, RDS, DynamoDB — any capacity mode, ElastiCache **for Valkey only**, etc.): up to **35%** (serverless) / up to **~20%** (provisioned instances), 1-year no-upfront
  - **RDS Reserved Instances** (alternative to Database Savings Plans on the same workload): up to **69%** (3-year All Upfront); locked to instance family/region — mutually exclusive with Database Savings Plans per workload
- **Fair comparison framing**: Present both an uncommitted comparison (GCP list vs. AWS on-demand) and a committed comparison (GCP net-of-CUD vs. AWS with 1yr commitments where applicable)
- **Migration timing note**: If the customer has active CUDs, note that CUD fees continue regardless of usage — migrating mid-commitment means paying both GCP CUD fees and AWS costs until the CUD term expires. For **Cloud Run → Fargate** or **GKE → Fargate** (re-platform) workloads, recommend establishing a 30–90 day AWS compute baseline before purchasing Compute Savings Plans (see Part 6).

Include in `estimation-infra.json` under `cost_comparison`:

```json
"commitment_context": {
  "gcp_has_active_cuds": true,
  "gcp_effective_discount_percent": 8.2,
  "gcp_monthly_at_list": 2450.00,
  "gcp_monthly_net_of_discounts": 2280.00,
  "aws_compute_savings_plan_discount": "up to 66% (Fargate/Lambda/EC2; max term); typical 20-40% (1yr no-upfront)",
  "aws_database_savings_plan_discount": "up to 35% (serverless) / up to 20% (provisioned) -- covers Aurora, RDS, DynamoDB (any capacity mode), ElastiCache for Valkey only, DocumentDB, Neptune, Keyspaces, Timestream, DMS, OpenSearch",
  "aws_rds_reserved_instance_discount": "up to 69% (specific instance family, 3yr All Upfront)",
  "aws_1yr_savings_plan_typical_discount": "20-40%",
  "aws_3yr_savings_plan_typical_discount": "40-66%",
  "note": "GCP baseline uses list price for apples-to-apples comparison. Customer currently saves 8.2% via CUDs. AWS Savings Plans (compute + database) offer comparable or deeper discounts post-migration. Database Savings Plans and RDS Reserved Instances are mutually exclusive on the same workload. For Cloud Run → Fargate or GKE → Fargate (re-platform), commit Compute Savings Plans after establishing a 30-90 day AWS usage baseline."
}
```

If `commitments.has_active_cuds == false` or the section is absent, omit `commitment_context` from the output.

---

## Part 4: GCP Data Transfer Egress (Vendor Fees Only)

This section covers **GCP vendor/network charges** for outbound data during migration — not human labor or professional-services costs (those are never presented as dollar estimates by this advisor).

**Billing data check:** Before generating this section, check if `$MIGRATION_DIR/billing-profile.json` exists.

### IF billing data IS available (`billing-profile.json` exists):

**Data transfer** — egress fees from GCP during migration. GCP charges for outbound data transfer; volume depends on database sizes and storage to migrate. Use the billing data to estimate the volume of data that needs to move.

Set `billing_data_available: true` in the output `migration_cost_considerations` object.

### IF billing data is NOT available but the inventory carries database/disk sizes:

Provisioned sizes are an UPPER BOUND on one-time migration egress (actual data
≤ provisioned; #149's sizing caveat applies). Present a bounded estimate, never
a point figure:

Set `migration_cost_considerations` to:

```json
{
  "categories": [
    "GCP data transfer egress (upper bound): ≤ <sum of provisioned DB disk + known storage GB> GB × $0.12/GB ≈ ≤ $<N> one-time"
  ],
  "billing_data_available": false,
  "baseline_available": true,
  "note": "Upper bound from PROVISIONED sizes (actual data is typically smaller). Object-storage volume is unknown without billing data — a billing export tightens this to measured volumes."
}
```

### IF neither billing data nor any sized inventory resource exists:

**Omit GCP data transfer fee estimates.** There is no grounding for egress projections. Set `migration_cost_considerations` to:

```json
{
  "categories": [],
  "billing_data_available": false,
  "baseline_available": false,
  "note": "Data transfer cost estimates require GCP billing data. Re-run discovery with a GCP billing export to see GCP egress fee projections."
}
```

In the user-facing summary, when billing data is missing, state: "GCP data transfer egress estimates require billing data. Provide a billing export and re-run discovery to see vendor egress projections."

---

## Part 5: ROI Analysis

Present the monthly and annual cost difference between GCP baseline and each AWS tier (Premium, Balanced, Optimized). This is the recurring savings (or increase) the customer can expect.

- If AWS is cheaper: present the monthly and annual savings for each tier
- If AWS is more expensive: state clearly and note that cost savings alone do not justify migration — operational benefits must be the driver

**Operational efficiency factors to highlight** (qualitative — do not assign dollar values):

- Reduction in operational overhead from managed services (Fargate vs self-managed, RDS vs self-hosted DB)
- Reduced on-call burden from AWS-managed HA, patching, and scaling
- Engineering time freed for product work instead of infrastructure maintenance

**Non-cost benefits to present:** operational efficiency, global reach, service breadth, enterprise integration, vendor diversification, scaling flexibility (auto-scaling, spot instances, savings plans).

**Note:** GCP data transfer egress fees (if estimated in Part 4) are **vendor** one-time charges excluded from recurring ROI calculations — not human migration costs.

---

## Part 6: Cost Optimization Opportunities

**Eligibility, the three-state rendering model, and the required caveats
(baseline-before-committing, Activate credits, mutual exclusion) are defined
in `references/shared/ri-sp-eligibility.md`.** Read that file before emitting
`optimization_opportunities[]` — it is the source of truth for which AWS
commitment product (if any) applies to a given service, including the
ElastiCache Valkey-vs-Redis-OSS split and the DynamoDB on-demand-vs-provisioned
split. The tables below cover the gcp-to-aws-specific entry shapes and
migration-source guidance (Cloud Run/GKE sizing caveats); where the two
disagree, `ri-sp-eligibility.md` governs.

**Always render this section**, even when nothing in the design qualifies for
an RI or Savings Plan — per the vendored file's three-state model, state
explicitly which state the design landed in rather than omitting the section.

**Relationship to cost tiers:** Premium / Balanced / Optimized totals in Part 2 are **pricing scenarios** for the same design. The **Optimized** tier already assumes illustrative trade-offs (e.g. reserved DB pricing, Fargate Spot). Entries in `optimization_opportunities` are **incremental post-migration actions** beyond the Balanced on-demand baseline — do **not** add their savings on top of Optimized tier totals (which already embed assumptions).

**Itemize the scenario deltas (`projected_costs.scenario_deltas` — required with three tiers):** while computing the Premium and Optimized totals, record each concrete difference vs Balanced as a string: what changed, its monthly delta, and — when the change is architectural (a resource added or removed, e.g. NAT Gateway dropped, Multi-AZ added) — its operational consequence. Commitment-based savings must name the commitment ("1-year Savings Plan"). These strings render verbatim in the report's tier table ("vs Balanced, for this stack" column) and in the Present Summary tier table; never present an Optimized total whose embedded architectural changes are not itemized. Schema and examples: `shared/schema-estimate-infra.md` § Cost tiers.

Present applicable optimizations with estimated savings:

| Optimization                   | Savings Range                               | Applies To                                                                                                                                                                                            | When                                            |
| ------------------------------ | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Compute Savings Plans          | 20–66%                                      | Fargate, Lambda, EC2                                                                                                                                                                                  | Post-migration (after 30–90 day usage baseline) |
| Database Savings Plans         | Up to 35% (serverless) / ~20% (provisioned) | Aurora, RDS, DynamoDB (any capacity mode), ElastiCache **for Valkey only**, DocumentDB, Neptune, Keyspaces, Timestream, DMS, OpenSearch                                                               | Post-migration or after instance right-sizing   |
| RDS Reserved Instances         | Up to 69%                                   | RDS, Aurora (provisioned)                                                                                                                                                                             | Post-migration (after architecture stabilizes)  |
| DynamoDB Reserved Capacity     | Up to 54% (1yr) / up to 77% (3yr)           | DynamoDB, **provisioned Standard table class only** — not on-demand or Standard-IA                                                                                                                    | Post-migration (after usage baseline)           |
| ElastiCache Reserved Nodes     | 30–55%                                      | ElastiCache **for Redis OSS or Memcached, node-based (provisioned) only** — the lever when the target engine is not Valkey (Database SP does not cover it); does not exist for ElastiCache Serverless | Post-migration (after usage baseline)           |
| S3 Intelligent-Tiering / S3-IA | 38–50%                                      | S3 storage                                                                                                                                                                                            | During migration                                |
| Spot Instances                 | 60–90%                                      | Batch/non-critical EC2 workloads                                                                                                                                                                      | If batch jobs exist                             |

**RI and Savings Plan / Reserved Capacity are mutually exclusive per workload** (RDS RI vs Database SP on the same instance; DynamoDB reserved capacity vs Database SP on the same table) — never present both as stacking on one resource.

**AWS credits do not cover upfront commitment costs.** Promotional/Activate credits cannot be applied to the upfront cost of Reserved Instances or Savings Plans (Partial Upfront or All Upfront) — they only apply to the ongoing discounted hourly rate. State this once whenever this section is presented (chat summary or report), so a customer on Activate credits does not read "up to 66% off" as free.

**If none of the design's services are RI/SP/Reserved-Capacity/Reserved-Nodes-eligible** (per `references/shared/ri-sp-eligibility.md`'s eligibility matrix — e.g. an AgentCore + S3 + Bedrock-on-demand-only design), do not omit this section. State plainly: "No 1-year/3-year commitment product applies to this architecture." When Bedrock is present, add: "Bedrock inference has a separate mechanism (Provisioned Throughput, 1- or 6-month commitment) — evaluate only above sustained high-volume, predictable traffic; it is not a Savings Plan or RI variant." `optimization_opportunities` may be an empty array in this case — do not fabricate an entry to avoid an empty list.

For each applicable optimization:

- **Compute Savings Plans:** emit percent range and post-migration timing; **omit `savings_monthly`** unless 30+ days of AWS usage data exist — do not size commitments from GCP Cloud Run or GKE billing alone (see below).
- **Database Savings Plans / RDS RIs:** may include preliminary `savings_monthly` when the Design phase mapped a target instance class **and** projected monthly DB on-demand cost exceeds **$50/month**; otherwise percent-only guidance.
- **S3 / Spot:** calculate before/after monthly cost when quantities are known from design.

Cross-reference Clarify when available: `cloud_run_traffic_pattern = business-hours` strengthens post-migration baseline guidance for compute; `constant-24-7` allows slightly more confidence in floor sizing — still post-migration for Compute Savings Plans.

### Compute Savings Plans (Fargate / Lambda)

**Relevance to GCP migrations:**

| Source                                 | Fargate commitment sizing from GCP data?               | Notes                                                                                                                                                                                                                                            |
| -------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Cloud Run → Fargate**                | **Unreliable**                                         | Variable-priced, scales to zero, bills per-request. GCP billing does not map 1:1 to Fargate vCPU-hours.                                                                                                                                          |
| **GKE → Fargate** (re-platform to ECS) | **Unreliable for commitment; useful for sanity check** | Node pools are often 24/7 with known machine types — you can rough-estimate vCPU-hours from node count × machine type. But re-platforming changes task sizing, autoscaling, and bin-packing; do not purchase a Savings Plan from GCP data alone. |
| **GKE → EKS** (keep Kubernetes)        | **Partial**                                            | Compute Savings Plans apply to **EC2 worker nodes** or **EKS Fargate profiles**, not the EKS control plane fee (~$0.10/hr per cluster). Post-migration baseline still recommended after right-sizing.                                            |

**What Compute Savings Plans offer:**

- Up to **66%** savings on Fargate, Lambda, and EC2 vs On-Demand at maximum term/discount ([source](https://aws.amazon.com/savingsplans/compute-pricing/))
- Commitment measured in **$/hour** — not tied to specific instance types, regions, or services
- Applies automatically across EC2, Fargate, and Lambda regardless of instance family, size, AZ, region, OS, or tenancy ([source](https://aws.amazon.com/savingsplans/faqs/))
- 1-year or 3-year terms; deeper discounts for longer terms and higher upfront payment

**Guidance for workloads migrating to Fargate (Cloud Run or GKE re-platform):**

The plugin SHALL present Compute Savings Plans as a **post-migration optimization** and SHALL NOT size a commitment from GCP billing data alone:

1. **Run on On-Demand for 30–90 days post-migration** to establish an AWS usage baseline
2. **Use AWS Cost Explorer Savings Plans Recommendations** — after 30+ days, Cost Explorer generates personalized recommendations based on actual hourly usage floor
3. **Commit to the usage floor, not the average** — cover minimum sustained usage; burst above the commitment bills at On-Demand with no penalty
4. **Consider rolling Savings Plans** — purchase smaller plans staggered quarterly to reduce risk if usage patterns change ([source](https://aws.amazon.com/blogs/aws-cloud-financial-management/how-can-i-use-rolling-savings-plans-to-reduce-commitment-risk/))

**Emit in `optimization_opportunities` when Fargate or Lambda is in `aws-design.json`:**

```json
{
  "opportunity": "Compute Savings Plans",
  "type": "compute_savings_plan",
  "target_services": ["Fargate", "Lambda"],
  "savings_percent": "20-66%",
  "savings_monthly": null,
  "commitment": "1-year or 3-year",
  "timing": "post-migration (after 30-90 days of usage data)",
  "implementation_effort": "low",
  "prerequisite": "Establish AWS compute usage baseline before committing",
  "description": "GCP compute billing (Cloud Run variable pricing or GKE re-platform to Fargate) makes pre-migration commitment sizing unreliable. GKE node pool sizing may sanity-check the floor but do not commit from GCP data alone. Use AWS Cost Explorer recommendations after migration to size the commitment to your actual usage floor.",
  "references": [
    "https://aws.amazon.com/savingsplans/compute-pricing/",
    "https://aws.amazon.com/savingsplans/faqs/"
  ]
}
```

### Database Savings Plans and Reserved Instances (Aurora / RDS)

**Relevance to GCP migrations:** Cloud SQL instances typically run 24/7 with a known instance size. Unlike Cloud Run, Cloud SQL usage translates well to AWS RDS/Aurora steady-state workloads — commitment sizing is more predictable from source configuration.

**Memorystore → ElastiCache and Firestore/Datastore → DynamoDB designs:** Database Savings Plans also apply to DynamoDB (any capacity mode) and to ElastiCache **for Valkey only** — see `references/shared/ri-sp-eligibility.md` and the dedicated "DynamoDB Database Savings Plans and Reserved Capacity" and "ElastiCache Database Savings Plans and Reserved Nodes" subsections below for the emit gates and entry templates. If Design mapped Memorystore for Redis to ElastiCache Redis OSS (not Valkey) on a node-based cluster, do not include ElastiCache in this workload's Database Savings Plan `target_services`; surface an ElastiCache Reserved Nodes opportunity instead. If that Redis OSS/Memcached target is ElastiCache Serverless, neither product applies — Reserved Nodes require a node-based cluster.

**What Database Savings Plans offer:**

- Up to **35%** on serverless deployments; up to **~20%** on provisioned RDS/Aurora instances ([source](https://aws.amazon.com/blogs/aws/introducing-database-savings-plans-for-aws-databases/))
- **1-year term only**, no upfront payment required ([source](https://aws.amazon.com/about-aws/whats-new/2025/12/database-savings-plans-savings/))
- Applies across eligible usage regardless of engine, instance family, size, deployment option, or Region
- **Mutually exclusive with RDS Reserved Instances on the same workload** — choose one discount model per database workload; you may use RIs on one workload and Database Savings Plans on another

**What RDS Reserved Instances offer (alternative):**

- Up to **69%** savings for 1-year or 3-year terms ([source](https://aws.amazon.com/rds/reserved-instances/))
- Payment options: No Upfront (~30%), Partial Upfront (~36% 1yr), All Upfront (~42% 1yr); 3-year terms up to 69%
- Locked to specific instance family, size, and region — less flexible but deeper discounts than Database Savings Plans

**Guidance for Cloud SQL → Aurora/RDS migrations:**

When Cloud SQL maps to a prod-tier instance with **> $50/month** projected on-demand DB cost:

1. Map source instance to AWS instance class (from Design phase)
2. Present Database Savings Plan benefit — 1-year, up to 35% (serverless) or ~20% (provisioned), flexible engine/instance changes
3. Present RI alternative for deeper savings when instance family is stable for 1+ years
4. **Recommend Database Savings Plans over RIs for migrations** — post-migration right-sizing flexibility outweighs RI depth for most customers

For dev-tier databases (< $50/month on-demand), emit percent-only guidance without dollar `savings_monthly`.

**Emit in `optimization_opportunities` when RDS or Aurora (any capacity mode) is in `aws-design.json`:**

```json
{
  "opportunity": "Database Savings Plans",
  "type": "database_savings_plan",
  "target_services": ["Aurora", "RDS"],
  "savings_percent": "up to 35% (serverless) / up to 20% (provisioned)",
  "savings_monthly": 4.50,
  "commitment": "1-year no-upfront",
  "timing": "immediately post-migration or after instance right-sizing",
  "implementation_effort": "low",
  "prerequisite": "Confirm target instance class and expected steady-state usage; omit savings_monthly when DB on-demand < $50/month",
  "description": "Cloud SQL 24/7 usage is predictable. Database Savings Plans offer flexibility to change engines/instances post-migration. Mutually exclusive with RDS RIs on the same workload.",
  "alternative": {
    "opportunity": "RDS Reserved Instances",
    "type": "rds_reserved_instances",
    "savings_percent": "up to 69%",
    "trade_off": "Locked to specific instance family and region — less flexibility during post-migration optimization"
  },
  "references": [
    "https://aws.amazon.com/savingsplans/database-pricing/",
    "https://aws.amazon.com/rds/reserved-instances/",
    "https://aws.amazon.com/about-aws/whats-new/2025/12/database-savings-plans-savings/"
  ]
}
```

### DynamoDB Database Savings Plans and Reserved Capacity (Firestore/Datastore → DynamoDB)

**Relevance to GCP migrations:** Firestore/Datastore usage is often on-demand-equivalent (pay-per-operation), which maps naturally to DynamoDB on-demand — but a workload with steady, predictable access patterns may be designed onto DynamoDB provisioned capacity instead. Per `references/shared/ri-sp-eligibility.md`, DynamoDB is **Database-SP-eligible regardless of capacity mode**, but only **provisioned, Standard table class** DynamoDB is additionally RI-eligible via DynamoDB reserved capacity (1-year or 3-year term, up to 54%/77% savings) — on-demand and Standard-IA cannot buy reserved capacity at all.

**Emit in `optimization_opportunities` when DynamoDB is in `aws-design.json`, regardless of capacity mode:**

```json
{
  "opportunity": "Database Savings Plans",
  "type": "database_savings_plan",
  "target_services": ["DynamoDB"],
  "savings_percent": "up to 35% (serverless-equivalent usage) / up to 20% (provisioned)",
  "savings_monthly": null,
  "commitment": "1-year no-upfront",
  "timing": "immediately post-migration or after usage-pattern right-sizing",
  "implementation_effort": "low",
  "prerequisite": "Applies regardless of DynamoDB capacity mode (on-demand or provisioned)",
  "description": "DynamoDB qualifies for Database Savings Plans in any capacity mode. Provisioned, Standard-table-class DynamoDB additionally qualifies for DynamoDB reserved capacity (see below) — mutually exclusive with Database SP on the same capacity. On-demand and Standard-IA DynamoDB have no RI-equivalent product; Database SP is the only lever for those.",
  "references": [
    "https://aws.amazon.com/savingsplans/database-pricing/"
  ]
}
```

**Add this entry only when the target DynamoDB table is confirmed provisioned, Standard table class (never for on-demand or Standard-IA):**

```json
{
  "opportunity": "DynamoDB Reserved Capacity",
  "type": "dynamodb_reserved_capacity",
  "target_services": ["DynamoDB"],
  "savings_percent": "up to 54% (1-year) / up to 77% (3-year)",
  "savings_monthly": null,
  "commitment": "1-year or 3-year",
  "timing": "post-migration (after usage baseline)",
  "implementation_effort": "low",
  "prerequisite": "Table must be provisioned capacity mode, Standard table class — on-demand and Standard-IA are explicitly excluded from reserved capacity per AWS docs",
  "description": "Provisioned, Standard-table-class DynamoDB usage can purchase reserved capacity (100 WCU/RCU allocations) for a deeper discount than Database Savings Plans. Mutually exclusive with Database Savings Plan coverage on the same capacity.",
  "alternative": {
    "opportunity": "Database Savings Plans",
    "type": "database_savings_plan",
    "savings_percent": "up to 20% (provisioned)",
    "trade_off": "Lower savings than reserved capacity, but flexible across services and does not lock in a specific table's capacity"
  },
  "references": [
    "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/reserved-capacity.html"
  ]
}
```

### ElastiCache Database Savings Plans and Reserved Nodes (Memorystore → ElastiCache)

**Relevance to GCP migrations:** Memorystore for Redis and Memorystore for Memcached map to ElastiCache. Per `references/shared/ri-sp-eligibility.md`, Database Savings Plan coverage for ElastiCache is **Valkey-only** (node-based or serverless) — Redis OSS and Memcached require ElastiCache Reserved Nodes instead, and Reserved Nodes only exist for **node-based (provisioned)** clusters, never ElastiCache Serverless.

**Emit exactly one of the following two entries when ElastiCache is in `aws-design.json`, gated on the Design phase's actual selected engine and deployment mode — never both, and never guess:**

```json
{
  "opportunity": "Database Savings Plans",
  "type": "database_savings_plan",
  "target_services": ["ElastiCache"],
  "savings_percent": "up to 35% (serverless) / up to 20% (provisioned)",
  "savings_monthly": null,
  "commitment": "1-year no-upfront",
  "timing": "immediately post-migration or after right-sizing",
  "implementation_effort": "low",
  "prerequisite": "Target engine must be confirmed Valkey — Database SP does not cover Redis OSS or Memcached on ElastiCache, in either deployment mode",
  "description": "ElastiCache for Valkey (node-based or serverless) qualifies for Database Savings Plans. Emit this entry only when Design's target engine is Valkey.",
  "references": [
    "https://aws.amazon.com/savingsplans/database-pricing/"
  ]
}
```

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
  "prerequisite": "Target engine is Redis OSS or Memcached AND the cluster is node-based (provisioned) — Reserved Nodes do not exist for ElastiCache Serverless",
  "description": "Database Savings Plans do not cover ElastiCache for Redis OSS or Memcached — Reserved Nodes are the commitment lever for this target engine on a node-based cluster. Does not apply if the target is ElastiCache Serverless: state that no commitment product of any kind applies to a Redis OSS/Memcached Serverless target, per ri-sp-eligibility.md's three-state model.",
  "references": [
    "https://aws.amazon.com/elasticache/pricing/"
  ]
}
```

---

## Part 7: Recommendation

Present 3 execution paths:

1. **Migrate with Optimizations (Best ROI)** — optimized service choices, monthly cost, projected annual savings
2. **Phased Migration (Lower Risk)** — cluster-by-cluster per design evaluation order, validate each before proceeding
3. **Stay on GCP** — when the evidence favors staying: AWS materially more expensive without offsetting operational benefit, deep GCP team investment with no AWS-specific need, or migration cost/risk exceeding the projected benefit on this stack. **Do not gate "stay" on "cost is the sole metric"** — any decisive factor suffices.

Include migrate/stay decision factors:

- **Migrate if:** operational efficiency matters, AWS-specific services needed, batch workloads (Spot savings), long-term AWS strategy, growing infrastructure
- **Stay if:** AWS is more expensive without an offsetting benefit for this stack, team deeply experienced with GCP, no need for AWS-specific services

### Decision outcome (write alongside `path`)

The `path` says how a migration would run; `outcome` says whether to run it now. Derive `outcome` from the trigger table, then write both.

**`defer_for_evidence` is expected to be RARE.** AWS almost always has the services, and the AWS-side estimate can almost always be produced — so when in doubt, prefer `conditional_go` with named conditions. Defer only when a responsible verdict is genuinely impossible, not merely incomplete.

**Hard triggers — any one forces `outcome: "defer_for_evidence"`:**

| # | Trigger                                                                                                                                                                                                                                                                                                                     | Evidence to name in `defer` next_steps / `would_flip_if`            |
| - | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| 1 | Deferred services (e.g. BigQuery) that the user must cut over in the **same window** as app infra AND those services are a **material share of spend or workload** — a verdict on the designed slice would misrepresent the migration                                                                                       | Specialist engagement outcome / analytics target architecture       |
| 2 | GovCloud-class compliance ambiguity: `compliance` contains `"unknown"` AND signals suggest FedRAMP/government requirements (gov data, agency customer, ITAR hints). GovCloud vs commercial changes regions, service catalog, and pricing wholesale — a commercial-region verdict could be flatly wrong, not just incomplete | Compliance confirmation from the user's legal/compliance owner      |
| 3 | The user's **only** stated motivation is cost savings AND no spend signal exists at all (no billing, Q3 declined/unknown) — a "migrate to save money" verdict would have zero evidence for its premise                                                                                                                      | Any spend signal: billing export (preferred) or a confirmed Q3 band |

**Soft triggers — never force defer; add each firing trigger to `conditions[]` (outcome becomes `conditional_go` instead of `go`) and to `would_flip_if[]`:**

| # | Trigger                                                                                                                                                            | Condition wording (adapt to stack)                                                                    |
| - | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| 4 | No billing baseline on a cost-motivated ask, but a Q3 spend band exists                                                                                            | "Validate the savings figure against your actual GCP bill — comparison uses your stated band"         |
| 5 | Compliance unknown with non-GovCloud regulated signals (e.g. possible HIPAA — AWS supports it; architecture and ~$25/mo of controls change, the decision survives) | "Confirm compliance requirements — controls and region preferences would be added, verdict unchanged" |
| 6 | Active CUDs without an expiration-aligned plan (`cud_status` is `long_remaining`/`unknown_expiry`)                                                                 | "Confirm CUD expiration and overlap cost before committing a start date"                              |
| 7 | Unresolved multi-region HA vs cost conflict (Q6=Catastrophic but Q1 not Global, or user wavered)                                                                   | "Confirm whether global infrastructure is required — it dominates the cost delta"                     |
| 8 | `availability` applied by default, never user-confirmed                                                                                                            | "Confirm database availability — Multi-AZ assumption roughly doubles the database line"               |
| 9 | Pricing staleness beyond the ±15–25% band                                                                                                                          | "Refresh pricing (cache stale) before treating the dollar delta as decision-grade"                    |

**Outcome derivation:**

```
IF any hard trigger fired          -> outcome: "defer_for_evidence"
ELSE IF path == "stay"             -> outcome: "stay"
ELSE IF any soft trigger fired     -> outcome: "conditional_go" (conditions[] = fired soft triggers)
ELSE                               -> outcome: "go"
```

**Per-track outcomes (required for multi-track stacks):** when the stack has more than one track (AI workloads and/or deferred services alongside infrastructure), derive an outcome per track — `compute_database`, `ai_text`, `ai_image`, `ai_agentic`, `analytics` (only tracks that exist in the design) — and write `recommendation.track_outcomes`. Apply the triggers per track: a hard/soft trigger scoped to one track fires on that track's outcome, not the stack's. **A failing or unproven secondary track demotes that track, never the stack** — e.g. an unresolved image-quality eval makes `ai_image` conditional (fallback: keep current provider via the adapter) while compute+database stay `go`. The stack-level `outcome` summarizes: it must not be worse than the compute/database track's outcome on account of a secondary track's condition. Whole-stack `stay_if` is reserved for factors that argue for staying entirely; track-scoped factors go in `conditions[]` with a track prefix. This generalizes the BigQuery deferral principle (never a stay reason unless same-window cutover is required) to every track.

Complexity alone (complex stack, many clusters) selects `path: "migrate_phased"` — it does **not** move `outcome` away from go/conditional_go. Populate `decision_basis` (measured / assumed / unknown) from constraint provenance: `chosen_by: "extracted"` or billing → measured; `"default"` → assumed; `["unknown"]` values and absent evidence → unknown. Populate `would_flip_if[]` with the 1–3 changes most likely to alter the outcome, each with its direction.

**Presenting a defer (lead with what IS established):** a defer verdict must open with what the assessment did determine — "AWS can host this stack; the AWS-side estimate is $X–$Y/mo" (and the designed-slice mapping) — before naming the one piece of missing evidence and how to obtain it. Never present defer as "we can't tell you anything"; it means "everything is known except one named thing, and that thing blocks a responsible verdict."

### Persist recommendation to estimation-infra.json

Part 7 MUST write the following `recommendation` block to `estimation-infra.json`. This is the single source of truth consumed by the HTML migration report (Section 0) and the Estimate chat summary. Do NOT duplicate this logic elsewhere.

```json
"recommendation": {
  "path": "migrate_optimized|migrate_phased|stay",
  "path_label": "Migrate with Optimizations|Phased Migration|Stay on GCP",
  "outcome": "go|conditional_go|defer_for_evidence|stay",
  "outcome_label": "Go|Go, with conditions|Defer — get evidence|Stay on GCP",
  "roi_justification": "string — one-sentence ROI case from Part 5",
  "confidence": "high|medium|low",
  "migrate_if": [
    "string — each factor that favors migration for THIS stack"
  ],
  "stay_if": [
    "string — each factor that favors staying for THIS stack"
  ],
  "conditions": [
    "string — REQUIRED non-empty when outcome is conditional_go; one entry per fired soft trigger"
  ],
  "decision_basis": {
    "measured": ["string — evidence from billing/Terraform/code"],
    "assumed": ["string — defaulted constraints feeding this estimate"],
    "unknown": ["string — unconfirmed inputs (e.g. compliance unknown)"]
  },
  "would_flip_if": [
    "string — 1-3 changes most likely to alter the outcome, with direction"
  ],
  "next_steps": [
    "string — actionable items from Part 7"
  ]
}
```

**Enum normalization for `path`:**

| Scenario                                     | `path` value          | `path_label` (display)         |
| -------------------------------------------- | --------------------- | ------------------------------ |
| AWS cheaper or operational benefits justify  | `"migrate_optimized"` | `"Migrate with Optimizations"` |
| Complex stack, phase-by-phase safer          | `"migrate_phased"`    | `"Phased Migration"`           |
| AWS more expensive AND costs are sole metric | `"stay"`              | `"Stay on GCP"`                |

Use `path` for machine consumption; `path_label` for display in report and chat.

**Required fields:** `path`, `path_label`, `outcome`, `outcome_label`, `confidence`, `migrate_if` (non-empty array), `stay_if` (non-empty array), `next_steps` (non-empty array). `conditions` is required non-empty when `outcome` is `"conditional_go"`. `decision_basis` and `would_flip_if` are required (arrays may be empty when nothing applies). `roi_justification` is optional (omit when `path` is `"stay"`). Readers of pre-extension artifacts must tolerate absent v2 fields (`outcome`, `conditions`, `decision_basis`, `would_flip_if`) and fall back to `path`.

Tailor `migrate_if` and `stay_if` to THIS stack (deferred services, AI cost delta, CUD lock-in, team GCP depth, etc.) — do not copy the generic Part 7 bullets verbatim unless they apply.

**BigQuery / deferred analytics:** Exclude from estimated AWS monthly run-rate totals and mark **`Deferred — specialist engagement`** in design, but **do not** treat BigQuery as a default reason to stay on GCP. Use `migrate_if` bullets such as engaging the AWS account team for analytics **in parallel** with phased infra migration. Use `stay_if` for BigQuery only when the user **must** cut over analytics in the **same window** as app infra and cannot run a phased analytics track with specialist planning.

---

## Output

Read `shared/schema-estimate-infra.md` for the `estimation-infra.json` schema and validation checklist, then write `estimation-infra.json` to `$MIGRATION_DIR/`.

## Completion Handoff Gate (Fail Closed)

Load `shared/handoff-gates.md`. **Re-read from disk** before checking.

Before returning control to `estimate.md`, require:

- `estimation-infra.json` exists and passes `shared/schema-estimate-infra.md` validation.
- `recommendation.path` is one of `migrate_optimized`, `migrate_phased`, or `stay`
- `recommendation.path_label` is non-empty
- `recommendation.outcome` is one of `go`, `conditional_go`, `defer_for_evidence`, `stay`; `conditions` non-empty when `conditional_go`; `outcome: "stay"` only with `path: "stay"`
- `recommendation.migrate_if` and `recommendation.stay_if` are non-empty arrays (Part 7 MUST persist `recommendation`)

**On FAIL:** Emit `GATE_FAIL | phase=estimate | field=<path> | reason=missing`. **Do NOT patch `estimation-infra.json` to pass the gate.** STOP — do not return control to `estimate.md` for phase completion.

**On PASS:** Emit `HANDOFF_OK | phase=estimate | artifacts=estimation-infra.json` (parent `estimate.md` emits the combined handoff after all routes pass).

## Present Summary

After writing `estimation-infra.json`, present a concise summary to the user:

1. **Pricing source and accuracy**: State whether prices came from cache or live API, and the accuracy range (±5-10% for infrastructure from cache/live, ±15-25% if cache is stale). Example: "Estimates based on cached AWS pricing (2026-03-07), accuracy ±5-10%."
2. GCP baseline vs estimated AWS monthly cost (balanced tier) — one-line comparison, **with the baseline-quality display label from Part 1** (e.g. "GCP baseline $165/mo — measured from your billing (±5%)")
3. Three-tier table: **Premium**, **Balanced**, **Optimized** with estimated monthly costs. Under or beside each label, use the **short subtitles**: Premium — _Highest resilience / highest monthly estimate in this model_; Balanced — _Default scenario; compare GCP to this first_; Optimized — _Lower monthly estimate; reservations / Spot / storage trade-offs assumed_. **Per non-Balanced tier, list its `scenario_deltas` (what concretely differs vs Balanced for this stack)** — a reader must be able to answer "what would I buy at Premium / give up at Optimized" without opening the artifact. Add a one-line **How to read**: three figures are **estimated monthly costs** for the same architecture (high → mid → low); **not** three Terraform stacks. When Terraform is generated later, it aligns with **Balanced**.
4. Per-service estimated monthly cost breakdown (balanced tier, 1 line per service)
5. **If billing data available**: Estimated GCP data transfer egress fees. **If billing data NOT available**: "Data transfer cost estimates require GCP billing data."
6. Estimated monthly and annual savings (or increase) vs GCP per tier
7. **Cost optimization:** if `optimization_opportunities` is non-empty, list the top 2-3 with estimated savings amounts. If it is empty (per the vendored eligibility matrix, nothing in this design is RI/SP-eligible), say so in one line instead of skipping the line entirely: "No 1-year/3-year commitment product applies to this architecture" (add the Bedrock Provisioned Throughput mention from Part 6 when Bedrock is present). Either way, when any commitment product is mentioned, add: "Note: Activate credits don't cover RI/Savings Plan upfront costs."
8. **Recommendation:** `recommendation.outcome_label` first ("Go, with conditions"), then `path_label` as the execution shape, one-line ROI justification when present. **Multi-track stacks: add the per-track line** ("By track: compute+DB go; AI text go; AI image conditional — track only; analytics deferred"). When `conditional_go`: list `conditions[]` (track-prefixed where scoped). When `defer_for_evidence`: name the missing evidence and how to get it. Close with `would_flip_if[]` (1–3 bullets) so the user knows what to watch.

**Cost labeling rule:** All dollar figures presented to the user MUST be labeled as "estimated monthly costs" or prefixed with "Est." — never present raw dollar amounts as if they are exact. This applies to chat output, report tables, and summary lines.

Keep it under 25 lines. The user can ask for details or re-read `estimation-infra.json` at any time.

## Generate Phase Integration

The Generate phase (`generate.md`) uses `estimation-infra.json` as follows:

1. **`projected_costs.breakdown`** — Budget allocation per cluster migration phase
2. **`migration_cost_considerations`** — Data transfer egress cost estimates (if billing data available)
3. **`optimization_opportunities`** — Which optimizations to implement and when (some during initial migration, some post-migration)
4. **`cost_comparison`** — Set cost monitoring targets and alerts for each migrated cluster
5. **`recommendation`** — Migrate/stay guidance (`path`, `path_label`, `migrate_if`, `stay_if`, `next_steps`); consumed by HTML report Section 0
6. **Cost tier vs Terraform** — Generated **`terraform/`** implements **one** baseline aligned with the **Balanced** scenario; **Premium** and **Optimized** are **estimate-only** bands unless the user changes IaC. See `generate-artifacts-infra.md` (`terraform/README.md`, `migration_summary` output).

The generated artifacts reference the cost estimates to set per-cluster cost monitoring thresholds and validate that actual AWS spend aligns with projections after each cluster migration.
