# Bedrock Cost Attribution and Tracking

Track, allocate, and manage Bedrock inference costs across teams, products, and models. Bedrock charges per input/output token with model-specific rates.

## Table of Contents

- [Cost Attribution Approaches](#cost-attribution-approaches)
- [Application Inference Profiles](#application-inference-profiles)
- [IAM Principal-Based Attribution](#iam-principal-based-attribution)
- [CloudWatch Usage Monitoring](#cloudwatch-usage-monitoring)
- [Budget Alerts](#budget-alerts)

## Cost Attribution Approaches

| Approach | Best For | Setup Effort |
|----------|----------|-------------|
| Application inference profiles + cost allocation tags | Per-product or per-team cost tracking in Cost Explorer | Medium — create profiles, tag, activate in Billing |
| IAM principal-based (CUR 2.0) | Per-developer or per-role attribution | Low — automatic in CUR 2.0, no Bedrock config needed |
| Model invocation logging + custom analytics | Fine-grained per-request analysis (token counts, latency, model) | High — enable logging, build queries |

For most teams, **application inference profiles with cost allocation tags** is the recommended approach. It provides clean cost breakdowns in Cost Explorer without custom analytics.

## Application Inference Profiles

### Setup Workflow

#### 1. Create an Application Inference Profile

```bash
aws bedrock create-inference-profile \
  --inference-profile-name "<TEAM_OR_PRODUCT_NAME>" \
  --model-source "copyFrom=arn:aws:bedrock:<REGION>::foundation-model/<MODEL_ID>" \
  --region <REGION> --profile <PROFILE>
```

Note the returned `inferenceProfileArn`.

#### 2. Tag the Profile

```bash
aws bedrock tag-resource \
  --resource-arn <INFERENCE_PROFILE_ARN> \
  --tags key=CostCenter,value=<COST_CENTER> key=Project,value=<PROJECT> \
  --region <REGION> --profile <PROFILE>
```

#### 3. Activate Cost Allocation Tags

In the AWS Billing console (or via API), activate the tags as cost allocation tags. Tags take ~24 hours to appear in Cost Explorer after activation.

#### 4. Use the Profile for Inference

Replace the base model ID with the inference profile ARN in application code:

```python
response = bedrock_runtime.converse(
    modelId="<INFERENCE_PROFILE_ARN>",
    messages=[...],
    inferenceConfig={"maxTokens": 1024}
)
```

#### 5. Verify in Cost Explorer

After 24–48 hours, filter Cost Explorer by the tag keys. Bedrock costs appear under `Amazon Bedrock` service, grouped by tag values.

## IAM Principal-Based Attribution

CUR 2.0 automatically records the IAM caller identity for every Bedrock API call. No Bedrock-specific setup required.

To use: tag IAM roles/users with keys like `department`, `costCenter`, or `project`, then filter CUR 2.0 data by those tags. Works for per-developer tracking when each developer assumes a distinct IAM role.

Limitation: only tracks who made the call, not which product or feature triggered it. Use inference profiles for product-level attribution.

## CloudWatch Usage Monitoring

Key metrics for cost monitoring (namespace `AWS/Bedrock`, dimension `ModelId`):

| Metric | Cost Signal |
|--------|------------|
| `InputTokenCount` | Input token spend (charged per token) |
| `OutputTokenCount` | Output token spend (higher per-token rate) |
| `InvocationCount` | Request volume |
| `CacheReadInputTokens` | Tokens served from cache (90% cheaper than standard input) |
| `CacheWriteInputTokens` | Cache write tokens (25% surcharge over standard input) |

### Cost Analysis Script

```bash
python3 scripts/analyze-bedrock-costs.py --days <DAYS> --region <REGION> --profile <PROFILE>
```

The script queries Cost Explorer for Bedrock spend grouped by usage type (model + token direction) over the specified period.

## Budget Alerts

Set up AWS Budgets to alert when Bedrock spend approaches a threshold:

```bash
aws budgets create-budget --account-id <ACCOUNT_ID> \
  --budget '{"BudgetName":"bedrock-monthly","BudgetLimit":{"Amount":"<AMOUNT>","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST","CostFilters":{"Service":["Amazon Bedrock"]}}' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"<EMAIL>"}]}]' \
  --profile <PROFILE>
```

This alerts at 80% of the monthly budget. Adjust threshold and notification targets as needed.
