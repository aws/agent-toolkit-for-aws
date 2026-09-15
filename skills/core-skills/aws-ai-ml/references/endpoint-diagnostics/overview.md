# Endpoint Diagnostics

Collects diagnostic information from a SageMaker endpoint using documented AWS APIs. Returns endpoint status, CloudWatch metrics, and recent container logs for the agent to interpret.

## Prerequisites

- AWS credentials configured with permissions described in [minimum_iam_policy.md](references/minimum_iam_policy.md)
- The SDK environment has been verified (SDK version, region, execution role). If not done, activate the `sdk-getting-started` skill first.

## Principles

1. **Read-only**: No mutations — only Describe, GetMetricData, and FilterLogEvents calls
2. **Deterministic**: No heuristics, no scoring, no classification
3. **Graceful degradation**: Each collection step is independent; failures in one do not block others
4. **Agent interprets**: The script collects facts; the agent provides interpretation and guidance
5. **First-variant metrics only**: Instance-level metrics (CPU, Memory, GPU) are collected for the first production variant only. For multi-variant endpoints, the agent should note this limitation when presenting results.

## Trigger

Activate when the user:

- Reports **endpoint** issues, errors, or latency (inference-time problems)
- Asks to check endpoint health, status, or metrics
- Wants to debug inference failures or timeouts on a **deployed endpoint**
- Reports a **deployment failure** (endpoint creation failed)
- Asks about instance count, container logs, or resource utilization of an endpoint

### Do NOT activate for

- **Training job failures** — use the finetuning skill instead. Training jobs and endpoints are separate SageMaker resources.
- **Listing, creating, updating, or deleting endpoints** — this skill diagnoses existing endpoints, not endpoint lifecycle management.
- **Model deployment requests** — use the model-deployment skill instead.
- **Scaling or capacity changes** — this skill collects diagnostics, it does not modify endpoints.

## Requirements

- **Endpoint name**: The SageMaker endpoint to diagnose
- **AWS region**: The region where the endpoint is deployed

## Workflow

### Step 1: Collect inputs

For this step, you need the **endpoint name** and **AWS region**:

1. Check conversation history — the user may have already mentioned the endpoint name or region.
2. Silently read project files (e.g., deployment notebooks, config files, `sdk-getting-started` output) for the region or endpoint name.
3. Only if still unknown, ask the user for the missing values.

⏸ Wait for user response if any values are missing.

### Step 2: Run diagnostics

Execute `collect_diagnostics.py` with the endpoint name and region. Do not create a notebook — run the script directly:

```python
from collect_diagnostics import collect_endpoint_diagnostics
results = collect_endpoint_diagnostics(endpoint_name="my-endpoint", region="us-east-1")

```

The script collects:

- Endpoint status via `DescribeEndpoint`
- CloudWatch metrics (invocations, errors, latency, utilization) for the last 5 minutes
- Container logs from the last 15 minutes (up to 100 events)

### Step 3: Present results

Present the collected data to the user. For any issues found, reference the official AWS troubleshooting guide:
https://docs.aws.amazon.com/sagemaker/latest/dg/deploy-model-troubleshoot.html

## References

- [Minimum IAM Policy](references/minimum_iam_policy.md)
- [AWS Endpoint Troubleshooting Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/deploy-model-troubleshoot.html)
- [CloudWatch Metrics for SageMaker](https://docs.aws.amazon.com/sagemaker/latest/dg/monitoring-cloudwatch.html)
