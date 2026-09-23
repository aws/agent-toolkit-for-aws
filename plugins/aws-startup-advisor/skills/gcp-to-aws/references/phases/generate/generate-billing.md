# Generate Phase: Billing-Only Migration Plan

> Loaded by generate.md when estimation-billing.json exists.

**Execute ALL steps in order. Do not skip or optimize.**

**Known limitations:** Partial IaC discovery (mixed Terraform + billing-only services) is not yet supported. Confidence scoring per service based on billing SKU specificity is not yet implemented.

## Overview

This file produces a **complexity-scaled migration plan** with wider timelines and lower confidence thresholds than the infrastructure path. Billing-only data provides service-level spend but lacks configuration details (instance sizes, replication settings, networking topology). The plan accounts for this uncertainty with:

- Complexity tier classification to right-size the timeline (small: 2-4 weeks, medium: 6-10 weeks, large: 12-18 weeks)
- Wider success criteria thresholds scaled by tier
- Explicit recommendation to run IaC discovery before executing the plan

## Prerequisites

Read the following artifacts from `$MIGRATION_DIR/`:

- `aws-design-billing.json` (REQUIRED) — Billing-based service mapping from Phase 3
- `estimation-billing.json` (REQUIRED) — Billing-only cost estimates from Phase 4
- `billing-profile.json` (REQUIRED) — GCP billing breakdown from Phase 1
- `preferences.json` (REQUIRED) — User migration preferences from Phase 2

If any required file is missing: **STOP**. Output: "Missing required artifact: [filename]. Complete the prior phase that produces it."

## Part 1: Context and Limitations

### What Billing Data Provides

- Service-level monthly spend (which GCP services are in use)
- Relative cost distribution (which services are most expensive)
- AI signal detection (whether AI/ML services appear in billing)
- SKU-level hints about usage patterns

### What Billing Data Does NOT Provide

- Instance sizes and configurations (CPU, memory, storage)
- Networking topology (VPC, subnets, firewall rules)
- Database engines and versions
- Replication and high-availability settings
- Inter-service dependencies
- Scaling configurations (min/max instances, autoscaling policies)
- Security configurations (IAM roles, encryption settings)

### Recommendation

> **For a more accurate migration plan, provide Terraform files and re-run discovery.**
> This billing-only plan is suitable for initial budgeting and stakeholder discussions,
> but must be refined with IaC discovery before executing the actual migration.

## Part 2: Complexity-Scaled Timeline

> **Before building the timeline, load `references/shared/migration-complexity.md` and classify the migration tier using the inputs from `aws-design-billing.json`, `billing-profile.json`, and `preferences.json`.**

Use the **Billing-Only Path** stage templates from `migration-complexity.md` for the determined tier. The three tiers produce different timelines:

### Small Tier (2-4 weeks)

No parallel-run stage. Discovery and provisioning overlap. Suitable for migrations with <=3 services, <$1K/month, no databases, single-AZ, no compliance.

- **Stage 1: Discovery + Provisioning (Week 1)**
  - Quick audit of GCP infrastructure (few services, low complexity)
  - Provision AWS VPC, compute, and supporting resources
  - Configure IAM roles and security groups
- **Stage 2: Deploy + Test (Week 2)**
  - Deploy applications to AWS
  - Run functional and integration tests
  - Validate cost tracking against estimates
- **Stage 3: Cutover + Validation (Weeks 3-4)**
  - Execute cutover during maintenance window (DNS switch)
  - 24-hour intensive monitoring
  - Stabilization and GCP teardown planning

### Medium Tier (6-10 weeks)

Shortened parallel run. Discovery takes 1-2 weeks instead of 4. For migrations with 4-8 services, $1K-$10K/month, or databases present.

- **Stage 1: Discovery Refinement (Weeks 1-2)**
  - Audit current GCP infrastructure
  - Document instance sizes, database configs, networking topology
  - Map dependencies between services
  - Refine AWS design based on discovered configurations
- **Stage 2: Service Migration (Weeks 3-5)**
  - Provision AWS infrastructure (VPC, compute, databases, storage)
  - Deploy applications, set up CI/CD pipelines
  - Integration testing and data migration dry run
- **Stage 3: Parallel Run (Weeks 6-7)**
  - Run both environments simultaneously
  - Compare performance, reliability, and costs
  - Validate data consistency
- **Stage 4: Cutover and Validation (Weeks 8-10)**
  - Execute cutover (DNS switch, traffic migration)
  - 48-hour intensive monitoring
  - Stabilization and GCP teardown planning

### Large Tier (12-18 weeks)

Full conservative plan with extended discovery and parallel-run phases. For migrations with 9+ services, >$10K/month, multi-region, compliance, or AI alongside infrastructure.

- **Stage 1: Discovery Refinement (Weeks 1-4)**
  - Weeks 1-2: Manual infrastructure audit, dependency mapping, configuration documentation
  - Weeks 3-4: Refine AWS design, re-estimate costs, identify services needing different AWS targets
  - Consider running IaC discovery if Terraform files become available
- **Stage 2: Service Migration (Weeks 5-9)**
  - Weeks 5-6: Provision AWS infrastructure (VPC, compute, databases, storage)
  - Weeks 7-8: Deploy applications, set up CI/CD, migrate to staging
  - Week 9: Integration testing, performance baseline, data migration dry run
- **Stage 3: Parallel Run (Weeks 10-12)**
  - Run both GCP and AWS simultaneously
  - Compare performance, reliability, and costs
  - Validate data consistency between environments
  - Monitor for 2+ weeks before cutover decision
- **Stage 4: Cutover and Validation (Weeks 13-15+)**
  - Execute cutover (DNS switch, traffic migration)
  - 48-hour intensive monitoring
  - Stabilization and GCP teardown planning

## Part 3: Risk Assessment

Risks are scaled by complexity tier. Use the **Risk Scaling by Tier** table in `references/shared/migration-complexity.md` to set probability values. The table below shows risk templates — replace the probability column with the tier-appropriate value.

### Standard Risks

| Risk                                                   | Small Prob. | Medium Prob. | Large Prob. | Impact | Mitigation                                                                                                          |
| ------------------------------------------------------ | ----------- | ------------ | ----------- | ------ | ------------------------------------------------------------------------------------------------------------------- |
| Incorrect service sizing                               | low         | medium       | high        | high   | Discovery phase audit; right-size after validation                                                                  |
| Missing dependencies discovered late                   | low         | medium       | high        | medium | Manual dependency mapping in discovery; buffer in timeline                                                          |
| Data migration complexity underestimated               | n/a         | medium       | high        | high   | Dry run before cutover; parallel run as safety net (medium/large only)                                              |
| Cost overrun due to unknown configurations             | low         | medium       | high        | medium | Set billing alerts at 80% of high estimate; weekly cost reviews                                                     |
| Performance regression from incorrect sizing           | low         | medium       | medium      | high   | Parallel run comparison (medium/large); resize before cutover                                                       |
| Longer timeline than planned                           | low         | medium       | high        | medium | Build buffer into schedule; communicate planned timeline upfront                                                    |
| Unmapped services block migration                      | low         | medium       | medium      | high   | Address unknowns in discovery refinement                                                                            |
| BigQuery migration complexity (if BigQuery in billing) | high        | high         | high        | high   | Engage AWS account team for specialist guidance on query patterns, data volumes, ETL pipelines, and BI integrations |

For the determined tier, include only risks with probability > "n/a". Use the probability from that tier's column.

## Part 4: Per-Service Migration Steps

For each service in `aws-design-billing.json.services[]`, generate a migration step template.

### Migration Step Template

```
Service: [gcp_service] → [aws_service]
Monthly Cost: $[monthly_cost] (GCP) → $[aws_mid] estimated (AWS)
How chosen: Estimated from billing only (JSON: billing_inferred) — see design-refs/fast-path.md User-facing vocabulary

Steps:
1. [ ] Determine actual configuration (instance size, storage, etc.)
   - TODO: Check GCP console or Terraform for [gcp_service] configuration
2. [ ] Provision AWS [aws_service] with discovered configuration
3. [ ] Migrate data (if applicable)
4. [ ] Test functionality and performance
5. [ ] Validate cost aligns with estimate

Unknowns:
- Instance sizing: TODO — verify in GCP console
- Scaling configuration: TODO — verify current autoscaling policies
- Dependencies: TODO — map which services depend on this one
```

### Example: Cloud Run to Fargate

```
Service: Cloud Run → Fargate
Monthly Cost: $450.00 (GCP) → $270-$630 estimated (AWS)
How chosen: Estimated from billing only (JSON: billing_inferred)
SKU Hints: CPU Allocation Time, Memory Allocation Time

Steps:
1. [ ] Determine actual configuration
   - TODO: Check CPU/memory allocation per Cloud Run service
   - TODO: Check concurrency and scaling settings
   - TODO: Check number of Cloud Run services
2. [ ] Create Fargate task definitions with matching CPU/memory
3. [ ] Set up ALB and target groups
4. [ ] Deploy container images to ECR
5. [ ] Configure autoscaling to match Cloud Run behavior
6. [ ] Test endpoint connectivity and performance

Unknowns:
- CPU allocation: TODO — check Cloud Run service configurations
- Memory allocation: TODO — check Cloud Run service configurations
- Number of services: TODO — count from GCP console or gcloud CLI
- Concurrency settings: TODO — check Cloud Run concurrency limits
```

### Unmapped Services

For each entry in `aws-design-billing.json.unknowns[]`:

```
Service: [gcp_service] — UNMAPPED
Monthly Cost: $[monthly_cost] (GCP)
Reason: [reason]
Suggestion: [suggestion]

Action Required:
- [ ] TODO: Manually identify the AWS equivalent for [gcp_service]
- [ ] TODO: Determine configuration and sizing
- [ ] TODO: Add to migration plan once mapped
```

## Part 5: Success Criteria

Thresholds scaled by complexity tier. Simpler migrations have fewer unknowns and tighter targets. Use the **Success Criteria Scaling by Tier > Billing-Only Path** table in `references/shared/migration-complexity.md`.

| Criteria                    | Small                      | Medium                     | Large                      |
| --------------------------- | -------------------------- | -------------------------- | -------------------------- |
| Performance within baseline | Within 15% of GCP          | Within 20% of GCP          | Within 20% of GCP          |
| Monitoring stability        | 24-hour watch period       | 48-hour watch period       | 48-hour watch period       |
| Post-migration stability    | 14-day observation         | 30-day observation         | 45-day observation         |
| Cost variance               | Within 25% of mid estimate | Within 30% of mid estimate | Within 40% of mid estimate |
| Data integrity              | 100%                       | 100%                       | 100%                       |
| Service availability        | 99%                        | 99%                        | 99%                        |

Apply the column matching the determined complexity tier.

## Part 6: Output Format

Generate `generation-billing.json` in `$MIGRATION_DIR/` with the following schema.

The example below shows a **small** tier migration. Adjust `complexity_tier`, `complexity_inputs`, `duration_drivers`, `tier_bound_by`, `approach`, phases, risk probabilities, and success metric thresholds according to the determined tier (see Part 2, Part 3, Part 5, and `references/shared/migration-complexity.md`).

```json
{
  "phase": "generate",
  "generation_source": "billing_only",
  "confidence": "low",
  "complexity_tier": "small",
  "complexity_inputs": {
    "service_count": 2,
    "monthly_spend": 75.71,
    "has_databases": false,
    "has_stateful_storage": false,
    "has_ai_workloads": false,
    "availability": "single-az",
    "compliance": "none",
    "multi_region": false
  },
  "timestamp": "2026-02-26T14:30:00Z",
  "migration_plan": {
    "duration_drivers": [
      "Few services, no databases (binding: service_count <= 3)",
      "Billing-only discovery gap - configs audited during Stage 1"
    ],
    "tier_bound_by": "service_count <= 3",
    "approach": "compressed",
    "phases": [
      {
        "name": "Discovery + Provisioning",
        "sequence_note": "ordinal - see stage order",
        "key_activities": [
          "Quick infrastructure audit",
          "AWS provisioning",
          "IAM and security configuration"
        ]
      },
      {
        "name": "Deploy + Test",
        "sequence_note": "ordinal - see stage order",
        "key_activities": [
          "Application deployment",
          "Functional and integration testing",
          "Cost validation"
        ]
      },
      {
        "name": "Cutover + Validation",
        "sequence_note": "ordinal - see stage order",
        "key_activities": [
          "DNS switch during maintenance window",
          "24-hour intensive monitoring",
          "Stabilization and GCP teardown planning"
        ]
      }
    ],
    "services": [
      {
        "gcp_service": "Compute Engine",
        "aws_service": "EC2",
        "monthly_cost_gcp": 75.46,
        "estimated_cost_aws_mid": 75.46,
        "confidence": "billing_inferred",
        "human_expertise_required": false,
        "unknowns": ["instance sizing", "scaling config"]
      }
    ]
  },
  "risks": [
    {
      "category": "incorrect_sizing",
      "probability": "low",
      "impact": "high",
      "mitigation": "Discovery audit; right-size after validation",
      "phase_affected": "Discovery + Provisioning"
    }
  ],
  "success_metrics": {
    "performance_threshold": "within 15% of GCP baseline",
    "monitoring_period_hours": 24,
    "stability_period_days": 14,
    "cost_variance_threshold": "within 25% of mid estimate",
    "data_integrity": "100%",
    "availability_target": "99%"
  },
  "recommendation": {
    "approach": "Compressed migration",
    "confidence": "low",
    "iac_discovery_offered": true,
    "note": "For tighter estimates and a shorter timeline, provide Terraform files and re-run discovery.",
    "key_risks": [
      "Configuration uncertainty",
      "Missing dependency information",
      "Cost variance due to unknown sizing"
    ]
  }
}
```

## Output Validation Checklist

- `phase` is `"generate"`
- `generation_source` is `"billing_only"`
- `confidence` is `"low"`
- `complexity_tier` is one of `"small"`, `"medium"`, `"large"`
- `complexity_inputs` object is present with all required fields (service_count, monthly_spend, has_databases, has_stateful_storage, has_ai_workloads, availability, compliance, multi_region)
- `migration_plan.duration_drivers` is a non-empty string array consistent with the tier's driver table; `tier_bound_by` present; **no `total_weeks` or hour fields**
- `migration_plan.approach` matches tier: small = `"compressed"`, medium = `"standard_with_discovery"`, large = `"conservative_with_discovery"`
- `migration_plan.phases` stage names match the tier template from Part 2
- `migration_plan.services` covers every service from `aws-design-billing.json`
- `risks` array has at least 2 entries (small), 4 entries (medium), or 5 entries (large)
- Each risk `probability` matches the tier column from Part 3
- `success_metrics` thresholds match the tier column from Part 5
- `recommendation.iac_discovery_offered` is `true`
- `recommendation.confidence` is `"low"`
- `recommendation` contains no effort-hour fields
- Output is valid JSON

## Completion Handoff Gate (Fail Closed)

Before returning control to `generate.md`, require:

- `generation-billing.json` exists and passes the Output Validation Checklist above.

If this gate fails: STOP and output: "generate-billing did not produce a valid `generation-billing.json`; do not continue Generate Stage 2."

## Generate Phase Integration

The parent orchestrator (`generate.md`) uses `generation-billing.json` to:

1. Gate Stage 2 artifact generation — `generate-artifacts-billing.md` requires this file
2. Provide billing context to `generate-artifacts-docs.md` for MIGRATION_GUIDE.md
3. Set phase completion status in `.phase-status.json`
