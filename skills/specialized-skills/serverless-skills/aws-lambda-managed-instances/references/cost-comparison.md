# Lambda vs LMI Cost Comparison

Use the [LMI Pricing Calculator](https://aws-samples.github.io/sample-aws-lambda-managed-instances/) for accurate, up-to-date cost comparisons based on your specific workload parameters (region, instance type, request volume, duration).

When building a cost comparison for a user, gather: region, runtime, requests/month, average duration, memory, and architecture (x86 vs ARM). Plug these into the calculator rather than relying on hardcoded estimates.

## When LMI is NOT Cheaper

- low number of requests/month (fixed 3-instance cost exceeds Lambda)
- Very short functions (< 100ms duration)
- Highly bursty, unpredictable traffic
- Workloads needing scale-to-zero

## Tools

- [LMI Pricing Calculator](https://aws-samples.github.io/sample-aws-lambda-managed-instances/) — interactive comparison tool
- [AWS Pricing Calculator](https://calculator.aws/) — general AWS cost estimation
