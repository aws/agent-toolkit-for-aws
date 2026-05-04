# Bedrock Quota Health Check

Monitor and manage Bedrock model quotas to prevent throttling. Bedrock enforces two quota types per model per region: requests per minute (RPM) and tokens per minute (TPM).

## Table of Contents

- [How Quota Reservation Works](#how-quota-reservation-works)
- [Audit Workflow](#audit-workflow)
- [CloudWatch Metrics](#cloudwatch-metrics)
- [When You're Being Throttled](#when-youre-being-throttled)
- [Quota Increase Requests](#quota-increase-requests)

## How Quota Reservation Works

Bedrock reserves TPM quota at request start based on: `InputTokens + CacheWriteInputTokens + CacheReadInputTokens + maxTokens`. If `maxTokens` is unset, it defaults to the model's maximum (up to 64K–128K), reserving far more quota than needed.

**Example (Claude Sonnet, 2M TPM quota):**

- `maxTokens=1000`, 500 input tokens: reserves 1,500 → ~1,333 concurrent requests
- `maxTokens` unset (defaults to 64K): reserves ~64,500 → ~31 concurrent requests

This is the most common cause of unexpected `ThrottlingException`. Always set `maxTokens` explicitly.

Cache read tokens are included in the initial reservation but released at settlement — prompt caching effectively increases your usable TPM capacity.

## Audit Workflow

### 1. Check Current Quotas

```bash
aws service-quotas list-service-quotas --service-code bedrock --region <REGION> --profile <PROFILE> --query "Quotas[?starts_with(QuotaName, 'Invoke')].{Name:QuotaName, Value:Value}" --output table
```

### 2. Check Recent Usage vs Limits

Run the quota health script:

```bash
python3 scripts/check-quota-health.py --region <REGION> --profile <PROFILE>
```

The script compares current quota limits against peak CloudWatch metrics over the last 24 hours and flags models approaching their limits.

### 3. Assess maxTokens Impact

Review application code for Bedrock calls without explicit `maxTokens`. Each unset call wastes quota proportional to the model's max output tokens.

## CloudWatch Metrics

Key metrics in the `AWS/Bedrock` namespace (dimension: `ModelId`):

| Metric | What It Tells You |
|--------|------------------|
| `InvocationCount` | RPM usage — compare against RPM quota |
| `InvocationThrottles` | Throttled requests — any value > 0 needs attention |
| `InputTokenCount` | Input token consumption per request |
| `OutputTokenCount` | Actual output tokens — use to right-size `maxTokens` |
| `InvocationLatency` | Latency distribution — spikes may correlate with throttling |

**Sample CloudWatch Logs Insights query** (requires model invocation logging enabled):

```
fields @timestamp, @message
| filter modelId like /claude/
| stats count() as requests, sum(inputTokenCount) as totalInput, sum(outputTokenCount) as totalOutput by bin(1m)
| sort @timestamp desc
```

## When You're Being Throttled

Decision table for resolving `ThrottlingException`:

| Situation | Action |
|-----------|--------|
| `maxTokens` not explicitly set | Set it to expected output length — biggest single impact |
| Traffic is bursty | Use cross-region inference profiles (`us.`, `eu.`, `global.` prefix) to distribute across regions |
| Steady-state traffic exceeds quota | Request a quota increase (see below) |
| Latency-sensitive workload | Use `priority` service tier for preferential processing |
| Non-time-critical workload | Use `flex` service tier (may queue during peak, lower cost) |
| Consistent high-volume | Request quota increase + use cross-region inference for headroom |

## Quota Increase Requests

```bash
aws service-quotas request-service-quota-increase --service-code bedrock --quota-code <QUOTA_CODE> --desired-value <VALUE> --region <REGION> --profile <PROFILE>
```

To find the quota code for a specific model:

```bash
aws service-quotas list-service-quotas --service-code bedrock --region <REGION> --profile <PROFILE> --query "Quotas[?contains(QuotaName, '<MODEL_NAME>')].{Code:QuotaCode, Name:QuotaName, Value:Value}"
```

Quota increases are reviewed by AWS — plan 1–3 business days. For urgent production needs, open an AWS Support case.
