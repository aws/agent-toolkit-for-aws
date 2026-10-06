# AWS Pricing Cache

**Last updated:** 2026-09-03
**Region:** us-east-1
**Currency:** USD
**Accuracy:** ±5-10% for infrastructure services (sourced from AWS Price List API), ±15-25% for AI models (sourced from public pricing pages)

> Prices may vary by region and change over time. Use for estimation only; there is no live pricing lookup — for the latest rates, check the public AWS pricing pages (e.g. https://aws.amazon.com/bedrock/pricing). **Amazon Nova** figures in the Bedrock subsection often reference **US East (Ohio)** and **inference mode** (global vs geo); other services in this file default to **us-east-1** unless noted.
> **Staleness warning:** If today's date is more than 30 days after the **Last updated** date above, treat AI model prices as potentially stale (±15-25% accuracy may widen). Infrastructure prices (Fargate, RDS, S3, etc.) change rarely and remain reliable longer. When staleness is detected, keep `pricing_source.status: "cached"` (the schema enum is `cached | cached_fallback | unavailable` — there is no `cached_stale` status) and record the staleness in the dedicated `pricing_source.fallback_staleness` object: set `is_stale: true` and `staleness_warning: "Pricing cache is more than 30 days old — AI model prices may have changed. Verify against [aws.amazon.com/bedrock/pricing](https://aws.amazon.com/bedrock/pricing/)."` Surface that same warning to the user in the estimate output.
>
> **Lifecycle is not a cached price field.** The `Status` column below is a dated snapshot, not permission to skip the lifecycle check. Before selecting any model, call `GetFoundationModel` or `ListFoundationModels` and read `modelLifecycle.status`. For a model launched on or after 2026-09-07, also read its model card: its Legacy period may be 45 days rather than 6 months, and it will never appear in the Legacy/EOL table. See `vendored/ai/ai-model-lifecycle.md`.

---

## Compute

### Fargate

| Metric                     | Rate      |
| -------------------------- | --------- |
| Per vCPU-hour (x86)        | $0.04048  |
| Per GB memory-hour (x86)   | $0.004445 |
| Per vCPU-hour (ARM64)      | $0.03238  |
| Per GB memory-hour (ARM64) | $0.003556 |

Linux, on-demand. ARM64 (Graviton) is ~20% below x86 per AWS Fargate pricing. Default dev-tier sizing is 0.5 vCPU.

### Lambda

| Metric                          | Rate                            |
| ------------------------------- | ------------------------------- |
| Per request                     | $0.0000002                      |
| Per GB-second (x86, first 6B)   | $0.0000166667                   |
| Per GB-second (x86, over 6B)    | $0.000015                       |
| Per GB-second (arm64, first 6B) | $0.0000133334                   |
| Per GB-second (arm64, over 6B)  | $0.000012                       |
| Free tier                       | 1M requests + 400K GB-sec/month |

arm64 (Graviton) is ~20% below x86 per GB-second; per-request price is the same for both architectures.

### Elastic Beanstalk

| Metric      | Rate                                              |
| ----------- | ------------------------------------------------- |
| Service fee | $0.00 (free — no additional charge for EB itself) |

Costs are the underlying resources (EC2, ALB, EBS, CloudWatch). Typical estimates:

Profiles below use the Graviton (`t4g.*`) default that the design phase now emits for EB; for x86 environments use the `t3.*` equivalents (~15–20% higher).

| Profile                                        | Underlying Resources             | Estimated Monthly |
| ---------------------------------------------- | -------------------------------- | ----------------- |
| Dev (single instance, t4g.small, no ALB)       | EC2 t4g.small                    | ~$12              |
| Dev + RDS (t4g.small + db.t4g.micro)           | EC2 + RDS db.t4g.micro           | ~$28–48           |
| Prod (load-balanced, 2× t4g.medium, ALB)       | 2× EC2 + ALB + EBS               | ~$85–110          |
| Prod + RDS (2× t4g.medium, ALB, db.t4g.medium) | 2× EC2 + ALB + RDS db.t4g.medium | ~$165–210         |

### EKS

| Metric                | Rate   |
| --------------------- | ------ |
| Cluster fee per hour  | $0.10  |
| Cluster fee per month | $73.00 |

Worker nodes billed separately as EC2 or Fargate.

### EC2 (On-Demand, Linux, x86)

| Instance  | $/hour | $/month |
| --------- | ------ | ------- |
| t3.micro  | 0.0104 | 7.58    |
| t3.small  | 0.0208 | 15.17   |
| t3.medium | 0.0416 | 30.34   |
| t3.large  | 0.0832 | 60.68   |
| m5.large  | 0.096  | 70.08   |
| m5.xlarge | 0.192  | 140.16  |
| c5.large  | 0.085  | 62.05   |
| c5.xlarge | 0.17   | 124.10  |

### EC2 (On-Demand, Linux, Graviton/ARM64)

~15–20% below the x86 equivalent at the same vCPU/memory. Dev-tier rows cached below; set `pricing_source: "unavailable"` for any family or size not listed.

| Instance   | $/hour | $/month | x86 equivalent |
| ---------- | ------ | ------- | -------------- |
| t4g.micro  | 0.0084 | 6.13    | t3.micro       |
| t4g.small  | 0.0168 | 12.26   | t3.small       |
| t4g.medium | 0.0336 | 24.53   | t3.medium      |
| t4g.large  | 0.0672 | 49.06   | t3.large       |
| m7g.large  | 0.0816 | 59.57   | m5.large       |
| m7g.xlarge | 0.1632 | 119.14  | m5.xlarge      |
| c7g.large  | 0.0725 | 52.93   | c5.large       |
| c7g.xlarge | 0.145  | 105.85  | c5.xlarge      |
| r7g.large  | 0.1071 | 78.18   | r6i.large      |
| r7g.xlarge | 0.2142 | 156.37  | r6i.xlarge     |

---

## Database

### Aurora PostgreSQL (On-Demand)

Aurora replicates across 3 AZs by default. Pricing is listed as Single-AZ — do NOT use Multi-AZ filter with MCP.

| Instance       | $/hour |
| -------------- | ------ |
| db.t4g.medium  | 0.073  |
| db.t4g.large   | 0.146  |
| db.r6g.large   | 0.26   |
| db.r6i.large   | 0.29   |
| db.r7g.xlarge  | 0.553  |
| db.r8g.large   | 0.276  |
| db.r8g.xlarge  | 0.552  |
| db.r8g.2xlarge | 1.104  |
| db.r8g.4xlarge | 2.208  |
| db.r8g.8xlarge | 4.416  |

| Storage/IO               | Rate  |
| ------------------------ | ----- |
| Storage per GB-month     | $0.10 |
| I/O per million requests | $0.20 |

### Aurora MySQL (On-Demand)

Same Multi-AZ note as Aurora PostgreSQL.

| Instance      | $/hour |
| ------------- | ------ |
| db.t4g.medium | 0.073  |
| db.t4g.large  | 0.146  |

Storage and I/O same as Aurora PostgreSQL.

### Aurora Serverless v2

Scales between min and max ACU. Both PostgreSQL and MySQL cost the same per ACU.

| Metric                     | Rate  |
| -------------------------- | ----- |
| Standard per ACU-hour      | $0.12 |
| I/O Optimized per ACU-hour | $0.16 |
| Storage per GB-month       | $0.10 |
| I/O per million requests   | $0.20 |

Min ACU = 0.5, scales to 256 ACU.

### RDS PostgreSQL (On-Demand, Multi-AZ)

| Instance       | $/hour |
| -------------- | ------ |
| db.t4g.micro   | 0.032  |
| db.t4g.small   | 0.065  |
| db.t4g.medium  | 0.129  |
| db.t4g.large   | 0.258  |
| db.t4g.xlarge  | 0.517  |
| db.t4g.2xlarge | 1.034  |

| Storage      | Rate  |
| ------------ | ----- |
| Per GB-month | $0.23 |

### RDS MySQL (On-Demand, Single-AZ)

For Multi-AZ, approximately double these rates.

| Instance      | $/hour | $/month |
| ------------- | ------ | ------- |
| db.t3.small   | 0.034  | 24.82   |
| db.t3.medium  | 0.068  | 49.64   |
| db.t3.large   | 0.136  | 99.28   |
| db.t4g.micro  | 0.016  | 11.68   |
| db.t4g.small  | 0.032  | 23.36   |
| db.t4g.medium | 0.065  | 47.45   |
| db.m5.large   | 0.171  | 124.83  |

| Storage             | Rate   |
| ------------------- | ------ |
| Per GB-month        | $0.23  |
| Backup per GB-month | $0.023 |

### DynamoDB (On-Demand)

| Metric                | Rate   |
| --------------------- | ------ |
| Read per million RRU  | $0.125 |
| Write per million WRU | $0.625 |
| Storage per GB-month  | $0.25  |

### ElastiCache Redis (On-Demand)

Single-AZ pricing. For Multi-AZ, approximately double.

| Node             | $/hour | $/month |
| ---------------- | ------ | ------- |
| cache.t3.micro   | 0.017  | 12.41   |
| cache.t3.small   | 0.034  | 24.82   |
| cache.t3.medium  | 0.068  | 49.64   |
| cache.t4g.micro  | 0.016  | —       |
| cache.t4g.small  | 0.032  | —       |
| cache.t4g.medium | 0.065  | —       |
| cache.r6g.large  | 0.206  | 150.38  |

---

## Storage

### S3

| Tier                       | Rate per GB-month |
| -------------------------- | ----------------- |
| Standard (first 50 TB)     | $0.023            |
| Standard (next 450 TB)     | $0.022            |
| Standard (over 500 TB)     | $0.021            |
| Standard-IA                | $0.0125           |
| Glacier Flexible Retrieval | $0.0036           |

| Requests                 | Rate    |
| ------------------------ | ------- |
| PUT per 1K               | $0.005  |
| GET per 1K               | $0.0004 |
| S3-IA retrieval per GB   | $0.01   |
| Glacier retrieval per GB | $0.01   |

---

## Networking

### Application Load Balancer

| Metric        | Rate    |
| ------------- | ------- |
| Per ALB-hour  | $0.0225 |
| Per LCU-hour  | $0.008  |
| Monthly fixed | $16.43  |

### Network Load Balancer

| Metric        | Rate    |
| ------------- | ------- |
| Per NLB-hour  | $0.0225 |
| Per LCU-hour  | $0.006  |
| Monthly fixed | $16.43  |

### NAT Gateway

| Metric           | Rate   |
| ---------------- | ------ |
| Per hour         | $0.045 |
| Per GB processed | $0.045 |
| Monthly fixed    | $32.85 |

### VPC

VPC itself is free. Add-ons:

| Component                   | Rate   |
| --------------------------- | ------ |
| VPN connection per hour     | $0.05  |
| VPN monthly                 | $36.50 |
| Interface endpoint per hour | $0.01  |
| Interface endpoint monthly  | $7.30  |

### Route 53

| Metric                       | Rate  |
| ---------------------------- | ----- |
| Hosted zone per month        | $0.50 |
| Per million standard queries | $0.40 |
| Per million latency queries  | $0.60 |
| Health check per month       | $0.50 |

### CloudFront (US/Europe)

| Metric                        | Rate                |
| ----------------------------- | ------------------- |
| Per GB transfer (first 10 TB) | $0.085              |
| Per 10K HTTPS requests        | $0.01               |
| Free tier                     | 1 TB transfer/month |

---

## Supporting Services

### Secrets Manager

| Metric               | Rate  |
| -------------------- | ----- |
| Per secret per month | $0.40 |
| Per 10K API calls    | $0.05 |

### CloudWatch

| Metric                                   | Rate   | Notes                                                                            |
| ---------------------------------------- | ------ | -------------------------------------------------------------------------------- |
| Log ingestion per GB (Standard)          | $0.50  |                                                                                  |
| Log ingestion per GB (Infrequent Access) | $0.25  | 50% cheaper than Standard; no Live Tail, subscription filters, or metric filters |
| Log storage per GB-month                 | $0.03  | Same for both Standard and Infrequent Access                                     |
| Insights query per GB scanned            | $0.005 | Same for both log classes                                                        |
| Custom metric per month (≤10K)           | $0.30  | Flat rate at startup scale; $0.10 for 10K–250K, $0.05 for 250K+                  |
| Standard alarm per month                 | $0.10  |                                                                                  |
| High-resolution alarm per month          | $0.30  |                                                                                  |
| Dashboard per month (first 3 free)       | $3.00  |                                                                                  |

Free tier (not subtracted in estimates — startup apps often exceed quickly):

- 5 GB log ingestion + archive + Insights queries
- 10 custom metrics + 10 standard alarms
- 3 dashboards (50 metrics each)

### X-Ray

| Metric                       | Rate  | Notes                 |
| ---------------------------- | ----- | --------------------- |
| Traces recorded per million  | $5.00 | First 100K free/month |
| Traces retrieved per million | $0.50 | First 1M free/month   |
| Traces scanned per million   | $0.50 | First 1M free/month   |

### CloudWatch Container Insights (ECS/Fargate)

| Metric                       | Rate  | Notes                                      |
| ---------------------------- | ----- | ------------------------------------------ |
| Per-task performance log/GB  | $0.50 | Same as standard log ingestion             |
| Cluster/service/task metrics | $0.30 | Per custom metric — can accumulate quickly |

### SQS

| Metric                        | Rate              |
| ----------------------------- | ----------------- |
| Standard per million requests | $0.40             |
| FIFO per million requests     | $0.50             |
| Free tier                     | 1M requests/month |

### SNS

| Metric                    | Rate               |
| ------------------------- | ------------------ |
| Per million publishes     | $0.50              |
| SQS delivery per million  | $0.00              |
| HTTP delivery per million | $0.60              |
| Free tier                 | 1M publishes/month |

### EventBridge

| Metric             | Rate  |
| ------------------ | ----- |
| Per million events | $1.00 |

---

## Analytics

### Redshift Serverless

| Metric               | Rate   |
| -------------------- | ------ |
| Per RPU-hour         | $0.375 |
| Storage per GB-month | $0.024 |

Minimum 8 RPU base capacity.

### Athena

| Metric         | Rate  |
| -------------- | ----- |
| Per TB scanned | $5.00 |

Columnar formats (Parquet, ORC) and partitioning reduce scan volume.

### SageMaker

| Training Instance    | $/hour |
| -------------------- | ------ |
| ml.m5.large          | 0.115  |
| ml.m5.xlarge         | 0.23   |
| ml.g4dn.xlarge (GPU) | 0.736  |

| Inference Instance | $/hour | $/month |
| ------------------ | ------ | ------- |
| ml.t3.medium       | 0.05   | 36.50   |
| ml.m5.large        | 0.115  | 83.95   |

Serverless inference: $0.0000200 per second per GB memory.

---

## Amazon Bedrock model and service pricing

Bedrock pricing is provider-neutral and canonical in
`references/vendored/ai/bedrock-pricing-cache.md`. Load that cache for every Bedrock
model and service rate; this file intentionally does not duplicate those values.

## Source Provider Pricing (for Migration Comparison)

Use alongside Bedrock pricing to calculate migration ROI.

### Gemini (Standard Tier)

Prices per 1M tokens. Source: [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing), verified May 2026.

| Model                 | Input $/1M | Output $/1M | Context | Tier     |
| --------------------- | ---------- | ----------- | ------- | -------- |
| Gemini 3.5 Flash      | 1.50       | 9.00        | 1M      | flagship |
| Gemini 3.1 Pro        | 2.00       | 12.00       | 1M      | flagship |
| Gemini 3.1 Flash-Lite | 0.25       | 1.50        | 1M      | budget   |
| Gemini 2.5 Pro        | 1.25       | 10.00       | 1M      | flagship |
| Gemini 2.5 Flash      | 0.30       | 2.50        | 1M      | fast     |
| Gemini 2.0 Flash      | 0.10       | 0.40        | 1M      | fast     |
| Gemini 2.0 Flash Lite | 0.075      | 0.30        | 1M      | budget   |

> **Gemini 3.1 Pro breakpoint pricing:** $4.00/$18.00 per 1M for prompts >200k tokens (vs $2.00/$12.00 for ≤200k). Table above uses ≤200k rates.
> **Gemini 3.5 Flash** is now GA and the current flagship Flash model, replacing Gemini 2.5 Flash as the primary Flash-tier recommendation. At $1.50/$9.00 it is 5x more expensive than Gemini 2.5 Flash — the Bedrock cost savings case is significantly stronger against 3.5 Flash.

### OpenAI (Standard Tier)

Prices per 1M tokens. GPT-5.5 and GPT-5.5 Pro use the same breakpoint pricing structure as GPT-5.4 at 272K input tokens. GPT-5.4 and GPT-5.4 Pro use **breakpoint pricing** at 272K input tokens: rates below are for <272K context; above 272K, input is 2x and output is 1.5x.

> **Tier note — these rows are OpenAI's STANDARD tier.** Bedrock in-region for the same models is priced at OpenAI's
> _data residency_ tier, exactly 1.10x the figures below (see the **OpenAI on Bedrock** section above). So for
> GPT-5.6 Sol / Terra / Luna, GPT-5.5 and GPT-5.4 a same-model move is a ~10% increase, not parity — compute it from
> the Bedrock table, not by assuming these numbers carry over. The rows below are the right source-side baseline for
> a customer on OpenAI standard, and remain the only figures available for models with **no** Bedrock equivalent
> (GPT-5.x Pro, GPT-5.2/5.1, GPT-4.x, o-series).

| Model         | Input $/1M   | Output $/1M  | Context | Tier      |
| ------------- | ------------ | ------------ | ------- | --------- |
| GPT-5.6 Sol   | _unverified_ | _unverified_ | 1M      | frontier  |
| GPT-5.6 Terra | _unverified_ | _unverified_ | 1M      | flagship  |
| GPT-5.6 Luna  | 0.20         | 1.20         | 1M      | fast      |
| GPT-5.5       | 5.00         | 30.00        | 1M      | flagship  |
| GPT-5.5 Pro   | 30.00        | 180.00       | 1M      | premium   |
| GPT-5.4       | 2.50         | 15.00        | 1.05M   | flagship  |
| GPT-5.4 Mini  | 0.75         | 4.50         | —       | fast      |
| GPT-5.4 Nano  | 0.20         | 1.25         | —       | budget    |
| GPT-5.4 Pro   | 30.00        | 180.00       | 1.05M   | premium   |
| GPT-5.2       | 1.75         | 14.00        | 200K    | flagship  |
| GPT-5.1       | 1.25         | 10.00        | 200K    | flagship  |
| GPT-5 Mini    | 0.25         | 2.00         | 200K    | fast      |
| GPT-5 Nano    | 0.05         | 0.40         | 128K    | budget    |
| GPT-4.1       | 2.00         | 8.00         | 1M      | flagship  |
| GPT-4.1 Mini  | 0.40         | 1.60         | 1M      | fast      |
| GPT-4.1 Nano  | 0.10         | 0.40         | 1M      | budget    |
| GPT-4o        | 2.50         | 10.00        | 128K    | flagship  |
| o3            | 2.00         | 8.00         | 200K    | reasoning |
| o4-mini       | 1.10         | 4.40         | 200K    | reasoning |

## Security Baseline

**Per-unit rates verified via AWS Pricing API for us-east-1 on 2026-05-04.**
**Config pricing effective 2025-09-01; Security Hub pricing effective 2026-03-01.**
**Re-verify if migrating to a non-us-east-1 region or if any of these services re-prices.**

### CloudTrail

| Metric                                          | Rate                                       |
| ----------------------------------------------- | ------------------------------------------ |
| Management events (first trail per region/type) | $0.00                                      |
| Management events (additional trails)           | $2.00 per 100K events                      |
| Data events                                     | $0.10 per 100K events (not used by Tier 1) |

### GuardDuty

| Metric                      | Rate                       | Notes                                           |
| --------------------------- | -------------------------- | ----------------------------------------------- |
| First 30 days               | $0.00                      | Free trial per account                          |
| CloudTrail event analysis   | $4.00 per 1M events        | First 500M/mo; scales down thereafter           |
| VPC Flow Log / DNS analysis | $1.00 per GB               | First 500 GB/mo                                 |
| DNS query analysis          | $1.00 per 1M queries       |                                                 |
| Small-startup typical       | ~$2–25/mo (typical $14/mo) | After free trial, with ~2M CloudTrail events/mo |

### AWS Config (pricing effective 2025-09-01)

| Metric                             | Rate                                   | Notes                                                                  |
| ---------------------------------- | -------------------------------------- | ---------------------------------------------------------------------- |
| Continuous configuration item      | $0.003 per item                        | Records every change                                                   |
| Daily configuration item           | $0.012 per daily item                  | Once-per-day snapshot; cheaper for slow-changing accounts, less signal |
| Small-startup typical (continuous) | ~$2–10/mo                              | 50–300 CIs/mo continuous                                               |
| Source                             | AWS Pricing API, us-east-1, 2026-05-04 |                                                                        |

### AWS Security Hub (pricing effective 2026-03-01)

| Metric                         | Rate                                   | Notes                                                                |
| ------------------------------ | -------------------------------------- | -------------------------------------------------------------------- |
| First 30 days                  | $0.00                                  | Free trial per account                                               |
| Security checks                | $0.001 per check                       | First 100K checks/mo; tapers above                                   |
| Per-EC2-hour monitoring        | $0.0052083/hr                          | ~$3.80/mo per instance                                               |
| Per-Lambda-function monitoring | $0.000434/hr                           | ~$0.32/mo per function                                               |
| Per-container-image scanning   | $0.0002894/hr                          |                                                                      |
| Small-startup typical          | ~$1–15/mo                              | After trial; Fargate-only startups pay nothing for the EC2 dimension |
| Source                         | AWS Pricing API, us-east-1, 2026-05-04 |                                                                      |

### AWS Budgets

| Metric                      | Rate                     | Notes                                      |
| --------------------------- | ------------------------ | ------------------------------------------ |
| First 2 budgets per account | $0.00                    | Free tier                                  |
| Additional budgets          | $0.02 per budget per day | Tier 1 emits 1 budget, so effectively free |
