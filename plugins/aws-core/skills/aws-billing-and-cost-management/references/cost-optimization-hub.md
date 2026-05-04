# Cost Optimization Hub

Cost Optimization Hub (COH) is the **recommended starting point** for finding savings. It consolidates and de-duplicates recommendations from multiple sources (Compute Optimizer, Cost Explorer rightsizing, Savings Plans, Reserved Instances, idle resources) into a single prioritized view with estimated savings.

## Why Start Here

- **De-duplication:** A single EC2 instance may appear in Compute Optimizer (right-size), Cost Explorer (RI recommendation), AND idle resource detection. COH consolidates these into one recommendation with the highest-impact action.
- **Prioritization:** Recommendations ranked by estimated monthly savings across all services and recommendation types.
- **Aggregation:** Single API to get all optimization opportunities across the account or organization.

## CLI Commands

```bash
# List recommendation summaries grouped by resource type
aws cost-optimization-hub list-recommendation-summaries \
  --group-by ResourceType

# List recommendations sorted by savings (highest first)
aws cost-optimization-hub list-recommendations \
  --order-by '{"dimension":"EstimatedMonthlySavings","order":"Desc"}' \
  --max-results 20

# Get details for a specific recommendation
aws cost-optimization-hub get-recommendation \
  --recommendation-id <id>

# Filter by resource type
aws cost-optimization-hub list-recommendations \
  --filter '{"resourceTypes":["Ec2Instance"]}'
```

## boto3 / call_boto3 Syntax

Parameter **values and inner key names** are the same for CLI and boto3 (top-level parameter names differ — CLI uses kebab-case like `--order-by`, boto3 uses camelCase like `orderBy`):

```python
# List recommendation summaries
# groupBy valid values: AccountId, Region, ActionType, ResourceType,
#   RestartNeeded, RollbackPossible, ImplementationEffort
client.list_recommendation_summaries(groupBy='ResourceType')

# List recommendations sorted by savings
# orderBy.dimension: EstimatedMonthlySavings, EstimatedSavingsPercentage
# orderBy.order: Asc, Desc (case-sensitive — "DESC" will fail)
client.list_recommendations(
    orderBy={'dimension': 'EstimatedMonthlySavings', 'order': 'Desc'},
    maxResults=20
)

# Filter by resource type
client.list_recommendations(
    filter={'resourceTypes': ['Ec2Instance']},
    maxResults=20
)

# Get details for a specific recommendation
client.get_recommendation(recommendationId='<id>')
```

**Common mistakes agents make with COH:**

- Using `RecommendationType` as groupBy (not a valid value — use `ResourceType` or `ActionType`)
- Using `CostReduction` as orderBy dimension (not valid — use `EstimatedMonthlySavings`)
- Using `DESC`/`ASC` instead of `Desc`/`Asc` (case-sensitive)
- Calling non-existent operations like `get_savings_summary` or `describe_recommendations`

## Recommendation Types

| Type | Source | What It Finds |
|------|--------|--------------|
| Rightsizing | Compute Optimizer | Over/under-provisioned EC2, Lambda, EBS, ECS, RDS |
| Idle resources | Compute Optimizer | EC2, EBS, ELB, RDS with near-zero utilization |
| Savings Plans | Cost Explorer | SP purchase recommendations |
| Reserved Instances | Cost Explorer | RI purchase recommendations |
| Graviton migration | Compute Optimizer | x86 → arm64 opportunities |
| EBS optimization | Compute Optimizer | gp2→gp3, io1→io2 migrations |

## Filtering and Action Types

**Action types** (valid values for `filter.actionTypes`):
`Rightsize`, `Stop`, `Upgrade`, `PurchaseSavingsPlans`, `PurchaseReservedInstances`, `MigrateToGraviton`, `Delete`, `ScaleIn`

**Implementation effort levels** (valid values for `filter.implementationEfforts`):
`VeryLow`, `Low`, `Medium`, `High`, `VeryHigh`

**Resource types** (valid values for `filter.resourceTypes`):
`Ec2Instance`, `Ec2AutoScalingGroup`, `EbsVolume`, `LambdaFunction`, `EcsService`, `RdsDbInstance`, `RdsDbInstanceStorage`, `ComputeSavingsPlans`, `Ec2InstanceSavingsPlans`, `SageMakerSavingsPlans`, `Ec2ReservedInstances`, `RdsReservedInstances`, `OpenSearchReservedInstances`, `RedshiftReservedNodes`, `ElastiCacheReservedNodes`, `MemoryDbReservedInstances`, `DynamoDbReservedCapacity`, `AuroraDbClusterStorage`, `NatGateway`

## Idle vs Overprovisioned — Do NOT Confuse

**Idle resources** = near-zero utilization, safe to stop/delete. Action types: `Stop`, `Delete`.
**Overprovisioned resources** = actively used but larger than needed, should be rightsized. Action type: `Rightsize`.

When a user asks "what idle resources can I terminate?" — only include `Stop` and `Delete` action types. Do NOT include `Rightsize` recommendations — those resources are still in use.

## Compute Optimizer Detailed Operations

For deeper per-resource analysis beyond COH summaries, use Compute Optimizer directly:

```python
# Check enrollment first
client.get_enrollment_status()

# Per-resource-type operations (service: compute-optimizer)
client.get_ec2_instance_recommendations(instanceArns=[...], filters=[...])
client.get_auto_scaling_group_recommendations(autoScalingGroupArns=[...])
client.get_ebs_volume_recommendations(volumeArns=[...])
client.get_lambda_function_recommendations(functionArns=[...])
client.get_rds_database_recommendations(resourceArns=[...])
client.get_ecs_service_recommendations(serviceArns=[...])

# Filters accept finding types: Underprovisioned, Overprovisioned, Optimized, NotOptimized
# Recommendation preferences: cpuVendorArchitectures=['AWS_ARM64'] for Graviton, ['CURRENT'] for same arch
```

## De-duplication of Savings Estimates

COH de-duplicates savings across overlapping recommendation types. A single EC2 instance may have recommendations for rightsizing, Savings Plans, Reserved Instances, AND Graviton migration — but implementing one changes the savings from the others.

- `list_recommendation_summaries` returns per-group `estimatedMonthlySavings` that are **NOT de-duped** — summing them will overcount.
- The same response includes `estimatedTotalDedupedSavings` at the top level — this IS the de-duped total. **Always use this field for total savings.**
- `list_recommendations` returns per-recommendation `estimatedMonthlySavings` that are also **NOT de-duped** across recommendations for the same resource.

**NEVER sum individual recommendation savings to get a total.** Use `estimatedTotalDedupedSavings` from `list_recommendation_summaries` instead.

## Workflow

1. **Start with COH** to get the prioritized, de-duplicated list of all savings opportunities
2. **For deeper analysis** on a specific recommendation, use the source service directly:
   - EC2 rightsizing details → `references/ec2-rightsizing.md`
   - SP purchase analysis → `references/savings-plans.md`
   - Lambda memory optimization → `references/lambda-optimization.md`
3. **Calculate savings** using a script (see `references/deterministic-calculations.md`) — NEVER sum savings estimates manually

## Gotchas

- COH requires opt-in: `aws cost-optimization-hub update-enrollment-status --status Active`
- COH is available in us-east-1 only
- Recommendations refresh approximately every 24 hours
- Savings estimates use On-Demand pricing by default — may overstate savings if customer already has SPs/RIs
- COH does NOT include per-service optimizations (S3 lifecycle, CloudWatch log retention, NAT Gateway endpoints) — see `references/service-optimization.md` for those
