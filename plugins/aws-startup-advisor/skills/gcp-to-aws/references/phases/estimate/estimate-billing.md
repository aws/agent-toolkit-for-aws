# Estimate Phase: Billing-Only Cost Analysis

> Loaded by estimate.md when aws-design-billing.json exists and aws-design.json does NOT exist.

**Execute ALL steps in order. Do not skip or optimize.**

**Known limitations:** Cost inference from billing SKU details (tighter ranges), historical trend projection, and AWS Cost Calculator integration are not yet supported.

## Pricing Mode

Without source configuration (CPU, memory, disk, scaling), billing-only estimates use **GCP-cost-ratio projections** (Step 2 below) rather than precise per-resource AWS pricing lookups. The pricing cache and MCP API are not directly used for per-service calculations — instead, GCP actual spend is scaled by service-type multipliers.

Overall accuracy: ±30-40% due to the lack of configuration detail.

## Overview

When only billing data was available for design, cost estimates carry wider ranges. Without source configuration, we cannot calculate precise AWS costs. Instead, we produce low/mid/high estimates per service based on typical AWS pricing for the mapped service type.

**Input:** `$MIGRATION_DIR/aws-design-billing.json`, `$MIGRATION_DIR/billing-profile.json`, `$MIGRATION_DIR/preferences.json`
**Output:** `$MIGRATION_DIR/estimation-billing.json`

## Prerequisites

Read from `$MIGRATION_DIR/`:

**From `aws-design-billing.json`:**

- `services[]` — GCP services with AWS mappings and confidence levels
- `metadata.design_source` — must be `"billing_only"`

**From `billing-profile.json`:**

- `services[]` — GCP services with monthly costs and SKUs
- `summary.total_monthly_spend` — Total GCP spend (this is the baseline)

**From `preferences.json`:**

- `design_constraints` — User preferences for optimization approach

## Step 1: Establish GCP Baseline from Billing

Use `billing-profile.json` as the authoritative GCP cost baseline:

```
GCP Monthly Baseline: $[total_monthly_spend]

Per-service breakdown:
  [service 1]: $[monthly_cost]
  [service 2]: $[monthly_cost]
  ...
```

This is actual spend data — higher confidence than inferred costs.

### CUD-Aware Baseline Adjustment

If `billing-profile.json` contains `commitments.has_active_cuds == true`:

1. **Use list price as baseline**: The `services[].monthly_cost` values already reflect list price (commitment fee rows are excluded). Use these directly — do not subtract CUD credits from the baseline.
2. **Exclude commitment fees from workload costs**: Commitment fee rows (e.g., "Commitment v1: E2 Cpu") are billing artifacts, not workload costs. They are already excluded from `services[]` by the discover phase.
3. **Note the customer's effective discount**: Record `commitments.effective_discount_percent` for the comparison narrative. The customer currently pays this percentage below list price on GCP.

If `commitments.has_active_cuds == false` or the `commitments` section is absent, proceed with `total_monthly_spend` as-is.

## Step 2: Generate AWS Cost Ranges

For each service in `aws-design-billing.json`, produce low/mid/high estimates:

### Range Calculation

Since we lack source configuration, apply percentage-based ranges around the GCP cost:

```
For each service:
  GCP monthly cost: $X

  Low estimate:  $X x 0.6  (aggressive optimization, smallest viable config)
  Mid estimate:  $X x 1.0  (roughly equivalent config, typical pricing)
  High estimate: $X x 1.4  (premium config, higher availability, no optimization)
```

### Adjust Ranges by Service Type

Some service types have tighter ranges than others:

| Service Type             | Range Factor | Rationale                                   |
| ------------------------ | ------------ | ------------------------------------------- |
| Compute (Cloud Run, GKE) | ±30%         | Pricing varies by config and scaling        |
| Database (Cloud SQL)     | ±35%         | Engine, HA, and sizing drive large variance |
| Storage (GCS)            | ±15%         | Storage pricing is relatively stable        |
| Messaging (Pub/Sub)      | ±20%         | Usage-based, somewhat predictable           |
| Networking (LB, DNS)     | ±20%         | Fixed + usage components                    |
| AI (Vertex AI)           | ±40%         | Model choice drives massive variance        |

### Adjust by SKU Hints

If `aws-design-billing.json` has `sku_hints` from SKU analysis, tighten the range:

- SKU indicates specific instance size -> reduce range to ±15%
- SKU indicates storage class -> reduce range to ±10%
- No SKU hints available -> use full range

## Step 3: Total Cost Projection

```
AWS Projected Monthly Cost:
  Low:  $[sum of all low estimates]
  Mid:  $[sum of all mid estimates]
  High: $[sum of all high estimates]

vs GCP Actual Monthly: $[total_monthly_spend]

Difference:
  Best case:  [low vs GCP] (potential savings of $X/month)
  Expected:   [mid vs GCP] (roughly equivalent cost)
  Worst case: [high vs GCP] (potential increase of $X/month)
```

### Commitment-to-Commitment Comparison (if CUDs detected)

If `billing-profile.json` has `commitments.has_active_cuds == true`, add a commitment context note:

```
Commitment Context:
  GCP current effective rate: [effective_discount_percent]% below list price via CUDs
  GCP list price baseline:   $[cost_basis.total_at_list]/month
  GCP net-of-discounts:      $[cost_basis.total_net_of_discounts]/month

  AWS equivalent commitment options:
    Compute Savings Plans (Fargate/Lambda/EC2): up to 66% max; typical 20-40% (1yr no-upfront)
    Database Savings Plans (Aurora/RDS/etc.): up to 35% (serverless) / up to 20% (provisioned); 1yr no-upfront
    RDS Reserved Instances: up to 69% (3yr All Upfront); mutually exclusive with Database SP on same workload
    1-year Compute Savings Plan: typically 20-40% below on-demand
    3-year Compute Savings Plan: typically 40-66% below on-demand

  Fair comparison: GCP list price vs AWS on-demand (both uncommitted)
  Committed comparison: GCP net-of-CUD vs AWS with applicable 1yr commitments
  Cloud Run / GKE → Fargate note: Do not size Compute Savings Plans from GCP billing — establish 30-90 day AWS baseline post-migration. GKE node pools may inform a rough floor estimate only.
```

This ensures the customer understands that their current GCP discount has an AWS equivalent, and the comparison is apples-to-apples.

## Step 4: Human One-Time Migration Costs (Out of Scope)

**Do not** present human labor, professional services, engineering, training, discovery/design effort, or similar people-time work as one-time migration **costs** or budget categories.

Populate `migration_cost_considerations.categories` as an **empty array** `[]`. Use `migration_cost_considerations.note` to state that human and professional-services one-time migration costs are intentionally excluded. You may still recommend IaC discovery in `recommendation.next_steps` or `unknowns` as a **precision** improvement — without framing it as a cost line item.

**Vendor fees:** If you discuss GCP egress in narrative, describe it only as **vendor/network charges** when grounded in `billing-profile.json` (do not invent dollar amounts). Do not mix human effort into “one-time cost” lists.

## Step 5: Document Unknowns

List what would narrow the cost ranges:

```
Unknowns that affect cost precision:
1. Compute sizing (CPU, memory) -- Would narrow compute range from ±30% to ±10%
2. Database engine and HA config -- Would narrow database range from ±35% to ±15%
3. Scaling configuration -- Affects whether Reserved Instances are viable
4. Network topology -- VPC, subnets, peering costs
5. Security requirements -- Encryption, compliance may add costs

Recommendation:
  Run IaC discovery (provide Terraform files) to reduce unknowns.
  This would narrow total estimate range from ±30-40% to ±10-15%.
```

## Step 6: Generate Output

Write `estimation-billing.json`.

### estimation-billing.json schema

```json
{
  "phase": "estimate",
  "timestamp": "[ISO 8601]",
  "metadata": {
    "estimate_source": "billing_only",
    "pricing_source": "cached|cached_fallback|unavailable",
    "confidence_note": "Estimates have wider ranges due to billing-only source"
  },
  "accuracy_confidence": "±30-40%",

  "gcp_baseline": {
    "source": "billing_data",
    "total_monthly_spend": 0.00,
    "service_count": 0,
    "services": [
      {
        "gcp_service": "Cloud Run",
        "monthly_cost": 450.00
      }
    ]
  },

  "aws_projection": {
    "low_monthly": 0.00,
    "mid_monthly": 0.00,
    "high_monthly": 0.00,
    "services": [
      {
        "gcp_service": "Cloud Run",
        "gcp_monthly": 450.00,
        "aws_target": "Fargate",
        "aws_low": 270.00,
        "aws_mid": 450.00,
        "aws_high": 630.00,
        "range_factor": "±30%",
        "unknowns": ["instance sizing", "scaling config"]
      }
    ]
  },

  "cost_comparison": {
    "gcp_monthly": 0.00,
    "aws_monthly_low": 0.00,
    "aws_monthly_mid": 0.00,
    "aws_monthly_high": 0.00,
    "best_case_savings": 0.00,
    "worst_case_increase": 0.00
  },

  "migration_cost_considerations": {
    "categories": [],
    "note": "Human and professional-services one-time migration costs are not presented by this advisor. Billing-only source increases estimate variance; IaC discovery narrows recurring cost ranges.",
    "complexity_factors": ["billing_only_source", "unknown_infrastructure_config"]
  },

  "unknowns": [
    {
      "category": "compute_sizing",
      "impact": "high",
      "resolution": "Provide Terraform files or describe instance configurations"
    },
    {
      "category": "database_config",
      "impact": "high",
      "resolution": "Provide Terraform files or describe database engine, HA, sizing"
    },
    {
      "category": "scaling_config",
      "impact": "medium",
      "resolution": "Describe traffic patterns and scaling requirements"
    },
    {
      "category": "network_topology",
      "impact": "medium",
      "resolution": "Describe VPC, subnet, and peering configuration"
    }
  ],

  "recommendation": {
    "confidence": "low",
    "note": "These estimates are based on billing data only. For precise estimates (±10-15%), run IaC discovery by providing Terraform files.",
    "next_steps": [
      "Review cost ranges with stakeholders",
      "Consider running IaC discovery for tighter estimates",
      "Use mid estimate for initial budgeting",
      "Plan for high estimate as worst-case budget"
    ]
  }
}
```

## Output Validation Checklist

- `metadata.estimate_source` is `"billing_only"`
- `accuracy_confidence` is `"±30-40%"` (never tighter for billing-only)
- `gcp_baseline` matches `billing-profile.json` totals
- Every service has low/mid/high estimates
- `unknowns` array is populated with resolution steps
- `recommendation.confidence` is `"low"` (billing-only never produces high confidence)
- No reference to Terraform-based configurations
- All unknowns documented with impact and resolution
- All cost values are numbers, not strings
- `migration_cost_considerations.categories` is `[]` — no human one-time migration costs presented
- Output is valid JSON

## Completion Handoff Gate (Fail Closed)

Before returning control to `estimate.md`, require:

- `estimation-billing.json` exists and passes the Output Validation Checklist above.

If this gate fails: STOP and output: "estimate-billing did not produce a valid `estimation-billing.json`; do not complete Phase 4."

## Present Summary

After writing `estimation-billing.json`, present a concise summary to the user:

1. **Pricing source and accuracy**: State that estimates are billing-only projections with ±30-40% accuracy due to lack of infrastructure configuration. Example: "Billing-only estimates, accuracy ±30-40%. Provide Terraform files to narrow to ±10-15%."
2. GCP baseline from billing data (total monthly spend)
3. Estimated monthly AWS cost ranges: low / mid / high per service
4. Total projection: best case / expected / worst case vs GCP (labeled as estimated monthly costs)
5. Key unknowns that would narrow the estimates
6. Recommendation: run IaC discovery for tighter estimates (±10-15% vs ±30-40%) — as a precision step, not as a human cost estimate

**Cost labeling rule:** All dollar figures presented to the user MUST be labeled as "estimated monthly costs" or prefixed with "Est." — never present raw dollar amounts as if they are exact.

Keep it under 20 lines. The user can ask for details or re-read `estimation-billing.json` at any time.

## Generate Phase Integration

The Generate phase uses `estimation-billing.json`:

- Uses wide cost ranges for conservative timeline planning
- Recommends IaC discovery as a prerequisite step
- Documents unknowns as prerequisites per generation step
- **Do not** surface human one-time migration **costs** from this artifact — `migration_cost_considerations.categories` remains empty in user-facing docs
