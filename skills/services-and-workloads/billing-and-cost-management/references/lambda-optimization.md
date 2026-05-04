# Lambda Optimization

> **Pricing note:** All prices shown are us-east-1 approximate as of early 2026. Prices vary by region and may change. Always verify current pricing via the Price List API before reporting to users.

## Memory-CPU Relationship

Lambda allocates CPU proportional to memory:

- 1,769 MB = 1 full vCPU
- 10,240 MB = 6 vCPUs

Over-provisioning memory gives more CPU, which can reduce duration enough to lower total cost. Cost = Invocations × Duration(ms) × Memory(GB) × Price/GB-ms + Request charges.

## Compute Optimizer for Lambda

**Requirements:** ≤1,792 MB memory AND ≥50 invocations in the lookback period.

Metrics analyzed: Invocations, Duration, Errors, Throttles, Memory Utilization. The engine simulates candidate memory sizes, projects duration, and selects the size that finishes within timeout and produces greatest monthly savings.

Findings: `NotOptimized` (can be improved), `Optimized`, `Unavailable` (insufficient data). Note: Lambda and EC2 use different finding value sets. Lambda: `NotOptimized`/`Optimized`/`Unavailable`. EC2: `Overprovisioned`/`Underprovisioned`/`Optimized`/`NotOptimized`.

```bash
aws compute-optimizer get-lambda-function-recommendations \
  --filters Name=Finding,Values=NotOptimized
```

## Optimization Levers

| Strategy | Savings | Effort |
|----------|---------|--------|
| Switch to arm64 (Graviton) | ~20% cost + ~10-15% faster | Low — config change |
| Right-size memory with Power Tuning | 10-50% | Medium |
| Use SnapStart (Java/Python/.NET) | Eliminates provisioned concurrency cost | Low |

```bash
# Switch to arm64
aws lambda update-function-configuration \
  --function-name my-function --architectures arm64
```

## Gotchas

- arm64 not available in all regions; native compiled dependencies need arm64 builds
- Reserved concurrency (free) ≠ Provisioned concurrency (paid) — most common Lambda cost confusion
- Provisioned concurrency costs ~$0.015/GB-hour even when idle — use SnapStart instead where possible
- Lambda needs 14 days of CloudWatch metrics before Compute Optimizer generates recommendations
- Use `alexcasalboni/aws-lambda-power-tuning` Step Functions state machine for systematic memory optimization
