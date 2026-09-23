# Infrastructure Estimate Schema

Schema for `estimation-infra.json`, produced by `estimate-infra.md`.

---

## Cost tiers (`projected_costs` / `cost_comparison`)

The fields **`aws_monthly_premium`**, **`aws_monthly_balanced`**, **`aws_monthly_optimized`** (under `projected_costs`) and **`option_a_premium`**, **`option_b_balanced`**, **`option_c_optimized`** (under `cost_comparison`) are **three pricing scenarios** for the **same** GCP->AWS mapping in `aws-design.json`. They are **not** three alternative Terraform roots.

**`scenario_deltas` (required with three tiers):** `projected_costs.scenario_deltas` itemizes, per non-Balanced scenario, what concretely differs from Balanced **for this stack** — the estimate engine already knows (it priced the differences); this field makes the reader see them instead of inferring from generic labels. Each entry names the change AND its consequence when the change is architectural, not just financial (e.g. dropping a NAT Gateway is a network-posture change, not merely savings):

```json
"scenario_deltas": {
  "premium": [
    "RDS Multi-AZ instead of single-AZ (+$14/mo) — removes the single-AZ assumption",
    "Provisioned compute headroom (+$X/mo)"
  ],
  "optimized": [
    "Drops NAT Gateway (-$33/mo) — tasks move to public subnets or VPC endpoints; security-posture change, not just savings",
    "Assumes 1-year commitment pricing on compute (-$Y/mo) — requires an upfront commitment decision"
  ]
}
```

Validation: when all three tiers are present, `scenario_deltas.premium` and `scenario_deltas.optimized` are non-empty string arrays; every architectural delta (resource added/removed vs the Balanced design) states its consequence, and commitment-based savings name the commitment. Readers of pre-extension artifacts must tolerate absence.

| Tier key        | User-facing label | Subtitle (use in reports / MIGRATION_GUIDE)                                |
| --------------- | ----------------- | -------------------------------------------------------------------------- |
| **`premium`**   | Premium           | _Highest resilience / highest monthly estimate in this model_              |
| **`balanced`**  | Balanced          | _Default scenario; compare GCP to this first_                              |
| **`optimized`** | Optimized         | _Lower monthly estimate; reservations / Spot / storage trade-offs assumed_ |

**How to read:** Scenario order is **highest -> middle -> lowest** monthly AWS estimate for the modeled architecture. **Balanced** is the **primary** comparison row vs the GCP baseline. **Premium** and **Optimized** are **bounds** (HA vs cost-optimization skew).

**Terraform:** When the Generate phase produces `terraform/`, it implements **one** infrastructure baseline aligned with the **Balanced** scenario (`aligned_with_estimate_tier` in the `migration_summary` output). **Premium** and **Optimized** remain **estimate-only** unless the customer edits IaC. See `references/phases/generate/generate-artifacts-infra.md` (`terraform/README.md`, `main.tf` header comment).

---

## estimation-infra.json schema

```json
{
  "phase": "estimate",
  "design_source": "infrastructure",
  "timestamp": "2026-02-24T14:00:00Z",
  "pricing_source": {
    "status": "cached|cached_fallback|unavailable",
    "message": "Using cached prices from 2026-03-04 (±5-10% accuracy)|Using cached prices from 2026-03-04, cache older than 30 days (±5-25% accuracy)|Pricing unavailable for [service]",
    "fallback_staleness": {
      "last_updated": "2026-02-24",
      "days_old": 3,
      "is_stale": false,
      "staleness_warning": null
    },
    "services_by_source": {
      "cached": ["Fargate", "RDS Aurora", "S3", "ALB"],
      "fallback": ["NAT Gateway"],
      "estimated": []
    },
    "services_with_missing_fallback": []
  },
  "accuracy_confidence": "±5-10%|±15-25%",

  "current_costs": {
    "source": "billing_data|inventory_estimate|preferences|user_provided|unavailable",
    "accuracy": "±5% (billing) | ±20-30% (inventory_estimate) — states the SOURCE's confidence; distinct from top-level accuracy_confidence, which covers AWS pricing mode",
    "gcp_monthly": 300,
    "gcp_annual": 3600,
    "baseline_note": "From billing-profile.json actual spend data — or the mandatory derived-baseline caveat for inventory_estimate",
    "breakdown": { "compute": 75, "database": 50, "storage": 40, "networking": 20, "other": 15 },
    "derivation": [],
    "excluded_resources": [],
    "warnings": []
  },

  "projected_costs": {
    "aws_monthly_premium": 1003,
    "aws_monthly_balanced": 265,
    "aws_monthly_optimized": 194,
    "aws_annual_optimized": 2328,
    "breakdown": {
      "compute": {
        "service": "Fargate",
        "monthly": 71,
        "alternative": { "service": "Lambda", "monthly": 9, "savings": 62 }
      },
      "database": {
        "service": "Aurora PostgreSQL",
        "monthly": 269,
        "alternative": { "service": "RDS PostgreSQL", "monthly": 75, "savings": 194 }
      },
      "storage": {
        "service": "S3 Standard + Intelligent-Tiering",
        "monthly": 86,
        "alternative": { "service": "S3-IA", "monthly": 65, "savings": 21 }
      },
      "networking": { "service": "ALB + NAT Gateway", "monthly": 53 },
      "supporting": { "secrets_manager": 1.20, "cloudwatch": 35.30 }
    }
  },

  "cost_comparison": {
    "gcp_monthly_baseline": 300,
    "option_a_premium": {
      "aws_monthly": 1003,
      "monthly_difference": 703,
      "annual_difference": 8436,
      "percent_change": "+234%"
    },
    "option_b_balanced": {
      "aws_monthly": 265,
      "monthly_difference": -35,
      "annual_difference": -420,
      "percent_change": "-12%"
    },
    "option_c_optimized": {
      "aws_monthly": 194,
      "monthly_difference": -106,
      "annual_difference": -1272,
      "percent_change": "-35%"
    },
    "commitment_context": {
      "gcp_has_active_cuds": true,
      "gcp_effective_discount_percent": 8.2,
      "gcp_monthly_at_list": 300,
      "gcp_monthly_net_of_discounts": 275,
      "aws_compute_savings_plan_discount": "up to 66% (Fargate/Lambda/EC2; max term); typical 20-40% (1yr no-upfront)",
      "aws_database_savings_plan_discount": "up to 35% (serverless) / up to 20% (provisioned RDS/Aurora)",
      "aws_rds_reserved_instance_discount": "up to 69% (specific instance family, 3yr All Upfront)",
      "aws_1yr_savings_plan_typical_discount": "20-40%",
      "aws_3yr_savings_plan_typical_discount": "40-66%",
      "note": "GCP baseline uses list price for apples-to-apples comparison. Customer currently saves 8.2% via CUDs. Database Savings Plans and RDS RIs are mutually exclusive per workload. For Cloud Run → Fargate, establish 30-90 day AWS baseline before Compute Savings Plans."
    }
  },

  "migration_cost_considerations": {
    "billing_data_available": true,
    "categories": [
      "Data transfer (GCP egress fees based on migration volume)"
    ],
    "note": "GCP charges for outbound data transfer during migration. Volume depends on database sizes and storage to migrate."
  },

  "roi_analysis": {
    "recurring_savings": {
      "monthly_difference_balanced": -35,
      "monthly_difference_optimized": -106,
      "annual_difference_balanced": -420,
      "annual_difference_optimized": -1272,
      "note": "Negative = AWS cheaper. Based on balanced/optimized tiers vs GCP baseline."
    },
    "operational_efficiency_factors": [
      "Reduced operational overhead from managed services (Fargate, RDS)",
      "Reduced on-call burden from AWS-managed HA, patching, and scaling",
      "Engineering time freed for product work instead of infrastructure maintenance"
    ],
    "non_cost_benefits": [
      "Operational efficiency (fewer engineers needed for managed services)",
      "Better global reach (more AWS regions)",
      "Broader service catalog for future workloads",
      "Better enterprise tool integration",
      "Vendor diversification (reduce single-vendor risk)",
      "Auto-scaling, spot instances, savings plans flexibility"
    ],
    "note": "GCP data transfer egress fees (if estimated) are vendor one-time charges excluded from recurring ROI calculations. Human/professional-services migration costs are not modeled here."
  },

  "optimization_opportunities": [
    {
      "opportunity": "Database Savings Plans",
      "type": "database_savings_plan",
      "target_services": ["RDS", "Aurora"],
      "savings_monthly": 15,
      "savings_percent": "up to 20% (provisioned)",
      "commitment": "1-year no-upfront",
      "timing": "post-migration or after instance right-sizing",
      "implementation_effort": "low",
      "prerequisite": "Confirm target instance class; omit savings_monthly when DB on-demand < $50/month",
      "description": "Cloud SQL 24/7 usage is predictable. Database Savings Plans offer flexibility post-migration. Mutually exclusive with RDS RIs on the same workload.",
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
    },
    {
      "opportunity": "Compute Savings Plans",
      "type": "compute_savings_plan",
      "target_services": ["Fargate", "Lambda"],
      "savings_monthly": null,
      "savings_percent": "20-66%",
      "commitment": "1-year or 3-year",
      "timing": "post-migration (after 30-90 days of usage data)",
      "implementation_effort": "low",
      "prerequisite": "Establish AWS compute usage baseline before committing",
      "description": "GCP compute billing (Cloud Run or GKE re-platform) makes pre-migration commitment sizing unreliable. Use Cost Explorer recommendations after migration.",
      "references": [
        "https://aws.amazon.com/savingsplans/compute-pricing/",
        "https://aws.amazon.com/savingsplans/faqs/"
      ]
    },
    {
      "opportunity": "S3 Infrequent Access",
      "target_services": ["S3"],
      "savings_monthly": 52,
      "savings_percent": "38%",
      "commitment": "none",
      "implementation_effort": "low",
      "description": "Move infrequently accessed data to S3-IA storage class"
    },
    {
      "opportunity": "Spot Instances for Batch",
      "target_services": ["EC2"],
      "savings_monthly": 6,
      "savings_percent": "70%",
      "commitment": "none",
      "implementation_effort": "medium",
      "description": "Use Spot instances for fault-tolerant batch processing jobs"
    }
  ],

  "financial_summary": {
    "current_gcp_monthly": 300,
    "projected_aws_balanced_monthly": 265,
    "projected_aws_optimized_monthly": 194,
    "monthly_savings_balanced": 35,
    "monthly_savings_optimized": 106,
    "annual_savings_optimized": 1272,
    "recommendation": "Migrate with optimizations for best ROI"
  },

  "recommendation": {
    "path": "migrate_optimized",
    "path_label": "Migrate with Optimizations",
    "outcome": "conditional_go",
    "outcome_label": "Go, with conditions",
    "roi_justification": "2.6 month payback with operational efficiency; $475K 5-year savings",
    "confidence": "high",
    "migrate_if": [
      "operational efficiency matters",
      "AWS-specific services needed",
      "long-term AWS strategy"
    ],
    "stay_if": [
      "cost is the only metric and AWS is more expensive",
      "team deeply experienced with GCP"
    ],
    "track_outcomes": [
      {
        "track": "compute_database",
        "outcome": "go",
        "note": "Fargate + RDS; the phased backbone"
      },
      { "track": "ai_text", "outcome": "go", "note": "Nova Lite via provider adapter" },
      {
        "track": "ai_image",
        "outcome": "conditional_go",
        "note": "Keeps current provider via the adapter until the image-quality eval passes; does not gate other tracks"
      },
      {
        "track": "analytics",
        "outcome": "defer_for_evidence",
        "note": "BigQuery — specialist engagement, parallel track"
      }
    ],
    "conditions": [
      "Confirm database availability requirement — Multi-AZ was assumed, not confirmed (2x cost factor)",
      "AI image: evaluate image quality vs current provider before swapping — track-scoped; a failed eval demotes this track only"
    ],
    "decision_basis": {
      "measured": [
        "GCP baseline from billing export ($8,200/mo)",
        "Cloud SQL disk size from Terraform (10 GB)"
      ],
      "assumed": ["Multi-AZ availability (defaulted)", "24/7 Cloud Run traffic (defaulted)"],
      "unknown": ["Compliance requirements (Q2 unanswered)"]
    },
    "would_flip_if": [
      "Single-AZ acceptable → AWS estimate drops ~$140/mo, strengthens go",
      "HIPAA applies → BAA services + controls add ~$25/mo and re-gate region choice"
    ],
    "next_steps": [
      "Review financial case with stakeholders",
      "Confirm service tier selections (Aurora vs RDS, Fargate vs Lambda)",
      "Get approval to proceed to Execute phase",
      "Schedule migration timeline per cluster evaluation order"
    ]
  }
}
```

### recommendation block in estimation-infra.json

The `recommendation` block is the single source of truth for migrate/stay guidance. Consumed by Estimate chat output AND HTML migration report (Section 0). Do not duplicate this logic in the report template.

| `path` value          | `path_label` (display)         |
| --------------------- | ------------------------------ |
| `"migrate_optimized"` | `"Migrate with Optimizations"` |
| `"migrate_phased"`    | `"Phased Migration"`           |
| `"stay"`              | `"Stay on GCP"`                |

**Decision outcome (additive — v2 fields):** `outcome` expresses the _decision_, independent of the execution-path vocabulary above. `path` answers "how would we migrate"; `outcome` answers "should we, now". Both are written; consumers that only read `path` keep working.

| `outcome` value        | `outcome_label` (display) | Meaning                                                                                                                                                       |
| ---------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `"go"`                 | `"Go"`                    | Evidence supports migrating now; no unresolved material assumption                                                                                            |
| `"conditional_go"`     | `"Go, with conditions"`   | Migrate, but named conditions (see `conditions[]`) must be confirmed or bounded first                                                                         |
| `"defer_for_evidence"` | `"Defer — get evidence"`  | A hard trigger fired (see `estimate-infra.md` trigger table); decision needs one named piece of evidence. **Expected rare** — when in doubt, `conditional_go` |
| `"stay"`               | `"Stay on GCP"`           | Evidence favors staying — reachable on any decisive factor, not only "cost is sole metric"                                                                    |

Validation:

- `path` is one of: `"migrate_optimized"`, `"migrate_phased"`, `"stay"`
- `path_label` matches the corresponding display string for `path`
- `outcome`, when present, is one of: `"go"`, `"conditional_go"`, `"defer_for_evidence"`, `"stay"` (readers MUST tolerate absence — pre-extension artifacts)
- `conditions` is a non-empty array of strings when `outcome == "conditional_go"`
- `decision_basis`, when present, has `measured`, `assumed`, and `unknown` string arrays (any may be empty)
- `would_flip_if`, when present, is an array of strings
- `outcome == "stay"` requires `path == "stay"`; `outcome == "defer_for_evidence"` may pair with any `path` (path shows what migration _would_ look like)
- `migrate_if` and `stay_if` are non-empty arrays of strings
- **Scope rule (`stay_if` / `conditions`):** the whole-stack `stay_if` list is reserved for factors that argue for staying **entirely** (e.g. compute economics dominating a sparse-traffic app). A factor affecting a single track (one AI workload's quality eval, one deferred service's specialist plan) is **track-scoped**: it goes in `conditions[]` prefixed with its track ("AI image: …") and/or shapes that track's entry in `track_outcomes` — it MUST NOT appear as a whole-stack stay reason. This generalizes the existing BigQuery rule (deferral is not a reason to stay unless analytics must cut over in the same window) to every track.
- `track_outcomes`, when present, is an array of `{track, outcome, note}`; `track` is one of `compute_database`, `ai_text`, `ai_image`, `ai_agentic`, `analytics` (use only tracks that exist in the design); `outcome` uses the same enum as `recommendation.outcome`. **Required when the stack has more than one track** (AI artifacts and/or deferred services alongside infrastructure). The stack-level `outcome` is then a summary: it must not be worse than the compute/database track's outcome merely because a secondary track has a condition — a failing track demotes that track, never the stack. Readers of pre-extension artifacts must tolerate absence.
- `next_steps` is a non-empty array of strings
- Block is **REQUIRED** in `estimation-infra.json` output (Part 7 must write it; Part 7 always writes the v2 fields)

## Observability Entry in `projected_costs.breakdown`

When Part 2B of `estimate-infra.md` produces an observability cost, it is included as an entry in `projected_costs.breakdown[]` with this shape:

```json
{
  "service": "CloudWatch + X-Ray (Observability)",
  "low": 4.00,
  "mid": 5.21,
  "high": 8.00,
  "accuracy": "±30%",
  "pricing_source": "cached",
  "components": {
    "log_ingestion": 3.50,
    "log_storage": 0.21,
    "custom_metrics": 1.50,
    "alarms": 0.00,
    "tracing": 0.00
  },
  "volume_source": "heuristic",
  "note": "GCP Cloud Operations includes 50 GB/month free logging, free alerting, and free profiling. CloudWatch always-free tier includes 5 GB logs, 10 custom metrics, and 10 alarms per month. Estimate assumes usage above free-tier limits."
}
```

**Validation for observability entry:**

- `components` keys are exactly: `log_ingestion`, `log_storage`, `custom_metrics`, `alarms`, `tracing`
- `volume_source` is one of: `"heuristic"`, `"billing"` (reflects log volume source — the largest cost component; metrics are always heuristic regardless of this field)
- `tracing` is 0 when no tracing signals detected in source — do not add X-Ray costs unprompted
- `mid` equals the sum of all `components` values
- This entry REPLACES any CloudWatch/log/metric portion in the "Supporting" row — never both

## `architecture_comparison` (optional — Graviton/ARM64)

Present in `estimation-infra.json` only when `preferences.json` → `design_constraints.cpu_architecture.value` is `graviton` or `mixed` (see `estimate-infra.md` Part 2C and `shared/schema-graviton.md`). Omit entirely for `x86`.

```json
"architecture_comparison": {
  "graviton_monthly": 245.00,
  "x86_equivalent_monthly": 298.00,
  "savings_amount": 53.00,
  "savings_percent": 17.8,
  "note": "Hourly price savings only; performance uplift may allow further downsizing after load testing"
}
```

**Validation for architecture_comparison entry:**

- All four numeric fields present; `savings_amount` equals `x86_equivalent_monthly − graviton_monthly`
- `savings_percent` equals `savings_amount / x86_equivalent_monthly × 100` (one decimal)
- Models the hourly price discount **only** — never performance-uplift capacity reduction
- Not a fourth pricing tier — Graviton is the architecture within the Balanced/Premium/Optimized totals
- Canonical field definitions live in `shared/schema-graviton.md`

## Output Validation Checklist

- `design_source` is `"infrastructure"`
- `pricing_source.status` is `"cached"`, `"cached_fallback"`, or `"unavailable"` (pricing is cache-only — there is no `"live"` status because no live pricing tool is configured, and there is no `"cached_stale"` status either: a stale cache is `status: "cached"` with `fallback_staleness.is_stale: true`)
- `pricing_source.fallback_staleness.is_stale` is `true` when the cache is older than its staleness threshold, with a non-null `staleness_warning`; `false` otherwise
- `accuracy_confidence` matches the pricing mode (±5-10% for cached, ±15-25% for fallback)
- `current_costs.source` is `"billing_data"` if `billing-profile.json` was used, `"inventory_estimate"`, `"preferences"`, `"user_provided"` (asked during estimate), or `"unavailable"` (user declined) otherwise
- `current_costs.gcp_monthly` matches billing-profile.json total (if used) or is a reasonable estimate
- `projected_costs` has all three tiers (premium, balanced, optimized)
- **Tier semantics:** Three totals are **scenario $** only (same design); **Balanced** matches generated Terraform baseline — see **Cost tiers** section above; user-facing labels must use the subtitles there (also `estimate-infra.md` Present Summary / `generate-artifacts-report.md`)
- `projected_costs.breakdown` covers compute, database, storage, networking, supporting services, and observability
- Every service in `aws-design.json` is represented in the cost breakdown
- `projected_costs.breakdown` observability entry (when present) REPLACES any CloudWatch/log/metric costs in the "Supporting" row — never double-count
- `cost_comparison` shows all three options with monthly and annual differences
- `cost_comparison.commitment_context` is present if `billing-profile.json` has `commitments.has_active_cuds == true`; omitted otherwise
- `migration_cost_considerations.billing_data_available` is `true` if `billing-profile.json` exists, `false` otherwise
- If `billing_data_available` is `true`: `migration_cost_considerations.categories` lists **GCP vendor egress / data transfer** only (never human or professional-services costs)
- If `billing_data_available` is `false`: `migration_cost_considerations.categories` is empty; `note` explains that billing data is required for GCP egress fee estimates
- `roi_analysis` presents recurring monthly/annual savings (or increase) per tier
- `roi_analysis` is honest — if migration increases cost, say so and justify with non-cost benefits
- `optimization_opportunities` only includes strategies relevant to the designed architecture, per the eligibility matrix in `references/shared/ri-sp-eligibility.md` — never claim Database Savings Plan coverage for an ElastiCache target that isn't Valkey, and never claim DynamoDB Reserved Capacity eligibility for on-demand or Standard-IA tables
- Each `optimization_opportunities[]` entry includes required fields: `opportunity`, `target_services`, `savings_percent`, `implementation_effort`, `description`. Optional fields: `type`, `savings_monthly` (null when post-migration sizing unavailable), `commitment`, `timing`, `prerequisite`, `references`, `alternative`
- Compute Savings Plans entries for Cloud Run migrations MUST NOT include `savings_monthly` sized from GCP billing — use `savings_monthly: null` and `timing: post-migration`
- Database Savings Plans entries MAY include `savings_monthly` only when projected DB on-demand exceeds $50/month
- `optimization_opportunities` savings are incremental to **Balanced** on-demand totals — not additive on **Optimized** tier (which already embeds reservation/Spot assumptions)
- The Cost Optimization Opportunities section renders even when the design has no RI/SP-eligible service — per `ri-sp-eligibility.md`'s three-state model, state explicitly which state the design landed in rather than omitting the section
- `financial_summary` provides a clear executive-level view
- `recommendation` block exists with `path`, `path_label`, `migrate_if`, `stay_if`, and `next_steps` all populated
- `recommendation.path` is one of: `"migrate_optimized"`, `"migrate_phased"`, `"stay"`
- `recommendation.next_steps` includes actionable items
- No references to AI-specific costs (those belong in `estimate-ai.md`)
- No references to billing-only estimates (those belong in `estimate-billing.md`)
- All cost values are numbers, not strings
- Output is valid JSON
