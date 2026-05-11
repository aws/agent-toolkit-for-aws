# Cost Explorer API Patterns

> **Pricing note:** All prices shown are approximate as of early 2026 and may change. Always verify current pricing before reporting to users.

## Defaults

- Metric: `UnblendedCost` (single account). Use `AmortizedCost` when customer has SPs/RIs.
- Exclude Credits/Refunds: `--filter '{"Not":{"Dimensions":{"Key":"RECORD_TYPE","Values":["Credit","Refund"]}}}'`
- End date is **exclusive**: `Start=2026-03-01,End=2026-04-01` returns all of March.
- Max 2 GroupBy dimensions per request.

## Critical Gotchas

**EC2 service names:** EC2 charges split into two services. `"Amazon Elastic Compute Cloud - Compute"` is instance usage. `"EC2 - Other"` (with spaces around hyphen) is NAT Gateway, EBS, data transfer. WRONG: `"EC2-Other"`, `"EC2Other"`. If "EC2 - Other" returns $0, call `GetDimensionValues` to confirm the exact service name, then retry.

**RECORD_TYPE not CHARGE_TYPE:** The dimension for charge type filtering is `RECORD_TYPE`. Using `CHARGE_TYPE` throws `ValidationException`.

**Empty Total with GroupBy:** By design — `Total` is empty when `GroupBy` is used. Sum grouped results using a script (see `references/deterministic-calculations.md`), or make a separate call without GroupBy.

**Filter validation:** Cost Explorer does not distinguish between valid filters with no data and invalid filters. If a filter returns no results, call `GetDimensionValues` to verify the filter value exists.

**API cost:** Each `GetCostAndUsage` or `GetCostForecast` call costs $0.01. Cache results.

**Hourly granularity:** Requires opt-in in Cost Explorer preferences. Only available for past 14 days. Hourly + resource-level only works for EC2 Compute.

**Tags take 24 hours** to appear after activation, and only for resources that incurred costs after activation — not retroactive.

## Usage Quantity Analysis

When using `USAGE_QUANTITY` metric:

- MUST group by usage type OR filter for usage types with the same unit (e.g., GB-month)
- NEVER aggregate different usage units (GB-months + instance-hours)
- If API returns usage units of `"NA"`, multiple units were aggregated — discard these results

## Data Transfer Analysis

Data transfer costs in Cost Explorer are spread across multiple usage type patterns. Use a script with regex for accurate filtering — do NOT rely on broad keyword matching (`Bytes`, `Transfer`) as it produces many false positives.

**Core data transfer** (product family "Data Transfer" in CUR):

- `DataTransfer-*-Bytes` — Internet ingress/egress, intra-region cross-AZ
- `*-AWS-Out-Bytes`, `*-AWS-In-Bytes` — inter-region transfer
- `*-Bytes-Internet`, `*-Bytes-AWS` — Global Accelerator
- `CloudFront-*-Bytes` — CloudFront to/from origin
- `*-DataXfer-*` — Direct Connect
- `*-ABytes-*` — S3 Transfer Acceleration

**Networking data processing** (billed under respective services, not under "Data Transfer"):

- `*-NatGateway-Bytes` — per-byte NAT Gateway processing (service: `EC2 - Other`)
- `*-VpcEndpoint-Bytes` — per-byte VPC Endpoint / PrivateLink processing (service: `Amazon Virtual Private Cloud`)
- `*-TransitGateway-Bytes` — per-byte Transit Gateway processing (service: `Amazon Virtual Private Cloud`)
- `*-DataProcessing-Bytes` — per-byte processing, but source varies by service:
  - `Elastic Load Balancing` → NLB/GLB data processing (networking, include)
  - `AmazonCloudWatch` → VPC Flow Logs processing (observability, exclude)
  - Other services → check context before including

Group by both `SERVICE` and `USAGE_TYPE` to disambiguate `DataProcessing-Bytes`. Only include it when the service is `Elastic Load Balancing`.

**Networking infrastructure** (hourly charges for networking resources that facilitate data movement):

- `*-NatGateway-Hours` — NAT Gateway hourly charge
- `*-VpcEndpoint-Hours` — VPC Endpoint hourly charge
- `*-TransitGateway-Hours` — Transit Gateway attachment hourly charge
- `GlobalAccelerator*` — Global Accelerator hourly + data transfer
- `*-LCUUsage` — ALB capacity units

Include both networking categories in your analysis as separate sections — customers asking about "data transfer costs" often want to see the full networking picture, not just per-byte charges.

**NOT data transfer** (common false positives):
`Ingestion-Bytes` (CloudWatch Logs), `PaidEventsAnalyzed-Bytes` (CloudTrail), `QueryScanned-Bytes` (Logs Insights), `VendedLog-Bytes`, `LambdaNetworkLogsAnalyzed-Bytes`, `Select-Scanned-Bytes`/`Select-Returned-Bytes` (S3 Select).

**Script:** Query `GetCostAndUsage` grouped by both `SERVICE` and `USAGE_TYPE` (max 2 GroupBy per request), then filter:

```python
import re
TRANSFER_RE = re.compile(r'DataTransfer|AWS-(In|Out)-Bytes|Bytes-(Internet|AWS)|CloudFront-.*-Bytes|DataXfer|-ABytes-')
NETWORKING_PROCESSING_RE = re.compile(r'NatGateway-Bytes|VpcEndpoint-Bytes|TransitGateway-Bytes')
NETWORKING_INFRA_RE = re.compile(r'NatGateway-Hours|VpcEndpoint-Hours|TransitGateway-Hours|GlobalAccelerator|LCUUsage')

# Each group has keys [service, usage_type] and cost
for service, usage_type, cost in results:
    if TRANSFER_RE.search(usage_type):
        pass  # Core data transfer
    elif NETWORKING_PROCESSING_RE.search(usage_type):
        pass  # Networking data processing
    elif 'DataProcessing-Bytes' in usage_type and service == 'Elastic Load Balancing':
        pass  # ELB data processing (networking) — exclude CloudWatch/other services
    elif NETWORKING_INFRA_RE.search(usage_type):
        pass  # Networking infrastructure (hourly)
    # Everything else: not data transfer
```

Usage types with no regional prefix may be us-east-1 or global. The `"EU"` prefix means eu-west-1.

For deeper analysis with resource-level detail, recommend CUR + Athena with `product_family = 'Data Transfer'`. Reference: https://aws.amazon.com/blogs/networking-and-content-delivery/understand-aws-data-transfer-details-in-depth-from-cost-and-usage-report-using-athena-query-and-quicksight/

## Resource-Level Analysis

Use `GetCostAndUsageWithResources` (not `GetCostAndUsage`) for individual resource costs.

- Only available for past 14 days
- Requires opt-in via Cost Management Preferences (per-service)
- MUST include a filter (typically by service) and group by `RESOURCE_ID`
- Resources without opt-in show as `"No Resource ID"`

## Date Handling

- If user says "last month" without a year, use the most recent completed month
- **ALWAYS check the current date before querying.** Use `date` or equivalent to confirm the current year and month. Models frequently default to dates from training data. An analysis of "last month" using the wrong year will return real data that looks plausible but is entirely stale — the most dangerous kind of error.
- NEVER compare a complete month to a partial current month without calculating daily averages
- Cost data has ~24-hour delay — current day data is estimated

## Common CLI Commands

```bash
# Monthly cost by service
aws ce get-cost-and-usage \
  --time-period Start=2026-03-01,End=2026-04-01 \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

# Cost forecast
aws ce get-cost-forecast \
  --time-period Start=2026-04-02,End=2026-05-01 \
  --metric UNBLENDED_COST --granularity MONTHLY

# Get valid dimension values
aws ce get-dimension-values \
  --time-period Start=2026-03-01,End=2026-04-01 \
  --dimension SERVICE

# Cost anomaly detection
aws ce get-anomalies \
  --date-interval '{"StartDate":"2026-03-01","EndDate":"2026-04-01"}'
```
