# Cost Audit Workflow

> **Pricing note:** All prices shown are us-east-1 approximate as of early 2026. Prices vary by region and may change. Always verify current pricing via the Price List API before reporting to users.

Execute when a user asks to audit costs, reduce their bill, or find savings. Prioritize: immediate (delete unused) → short-term (right-size, configure) → long-term (commitments).

## Step 1: Top Cost Drivers

```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-03-01,End=2026-04-01 \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

## Step 2: Month-over-Month Comparison

Run the same query for the previous month. Calculate percent change per service **using a script** (see `references/deterministic-calculations.md`). Flag services with >20% increase.

## Step 3: Optimization Recommendations (Start with COH)

Use Cost Optimization Hub to get all recommendations, prioritized by savings. COH consolidates and de-duplicates across Compute Optimizer, Cost Explorer rightsizing, SPs, RIs, and idle resources. See `references/cost-optimization-hub.md` for CLI commands and correct parameter syntax.

## Step 4: Find Idle/Unused Resources

```bash
# Unattached EBS volumes
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query "Volumes[].{ID:VolumeId,Size:Size,Type:VolumeType}" --output table

# Unattached Elastic IPs (~$3.65/month each — all public IPv4 addresses cost $0.005/hr whether in-use or idle)
aws ec2 describe-addresses \
  --query "Addresses[?!InstanceId && !NetworkInterfaceId]"
```

## Step 5: Check Commitment Coverage

```bash
aws ce get-savings-plans-coverage \
  --time-period Start=2026-03-01,End=2026-04-01 --granularity MONTHLY
aws ce get-savings-plans-utilization \
  --time-period Start=2026-03-01,End=2026-04-01 --granularity MONTHLY

# Reserved Instance coverage & utilization
aws ce get-reservation-coverage \
  --time-period Start=2026-03-01,End=2026-04-01 --granularity MONTHLY
aws ce get-reservation-utilization \
  --time-period Start=2026-03-01,End=2026-04-01 --granularity MONTHLY
```

## Step 6: Per-Service Quick Wins

```bash
# Log groups without retention
aws logs describe-log-groups \
  --query "logGroups[?!retentionInDays].{Name:logGroupName,StoredBytes:storedBytes}" --output table

# Lambda functions still on x86_64
aws lambda list-functions \
  --query "Functions[?Architectures[0]=='x86_64'].{Name:FunctionName,Memory:MemorySize}" --output table

# Existing S3 gateway endpoints (cross-reference against all VPCs to find missing ones)
aws ec2 describe-vpc-endpoints --filters Name=service-name,Values=*s3* \
  --query "VpcEndpoints[].{VPC:VpcId,Service:ServiceName}"

# Existing DynamoDB gateway endpoints
aws ec2 describe-vpc-endpoints --filters Name=service-name,Values=*dynamodb* \
  --query "VpcEndpoints[].{VPC:VpcId,Service:ServiceName}"
```

## Step 7: Generate Report

Structure findings as: Top Cost Drivers (table) → Immediate Savings (delete unused) → Short-Term (right-size, configure) → Long-Term (commitments) → Estimated Total Monthly Savings.

Label all figures as ACTUAL DATA (from API) or ESTIMATED SAVINGS (calculated via script). NEVER hallucinate cost numbers.
