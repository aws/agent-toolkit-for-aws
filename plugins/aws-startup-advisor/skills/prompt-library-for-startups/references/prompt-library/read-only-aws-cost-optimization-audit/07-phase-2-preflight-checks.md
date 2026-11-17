<!-- markdownlint-disable -->

## PHASE 2: PREFLIGHT CHECKS

Confirm the data sources exist. Report every failure per Rule 3.

### 2.1 Permission validation

With the Prerequisites policies attached these probes are verification, not discovery: a `FAILED` row means a policy is not attached, or an SCP or permission boundary is denying the call despite it. Both are worth knowing before spending Cost Explorer money, which is why the probes stay even with correct policies.

```bash
umask 077              # raw stderr carries full principal ARNs; do not leave it world-readable
PROBE_LOG=$(mktemp)    # full error text lands here; carry it into Appendix B per Rule 3
# Copy every FAILED line into the workpaper before the shell exits: Appendix B needs the
# exact messages per Rule 3, and this file does not survive the session. The preamble's
# cleanup handler removes it on exit; no trap here (it would replace that handler).
probe() {                      # captures stderr in order to report it, not to hide it
  local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "OK     | $label"
  else
    printf 'FAILED | %s | %s\n' "$label" "$out" >> "$PROBE_LOG"
    echo "FAILED | $label | $(echo "$out" | tr '\n' ' ' | cut -c1-160) [full message in $PROBE_LOG]"
  fi
}
probe "Cost Explorer"     aws ce get-cost-and-usage --time-period Start="$START_7D",End="$TODAY" --granularity DAILY --metrics UnblendedCost
probe "Compute Optimizer" aws compute-optimizer get-enrollment-status
probe "Cost Optim. Hub"   aws cost-optimization-hub list-recommendations --max-results 1
probe "CloudWatch"        aws cloudwatch list-metrics --namespace AWS/EC2 --max-items 1
probe "CW Logs"           aws logs describe-log-groups --limit 1
probe "EC2"               aws ec2 describe-instances --max-items 1
probe "ELB"               aws elbv2 describe-load-balancers --page-size 1
probe "RDS"               aws rds describe-db-instances --max-items 1
probe "ElastiCache"       aws elasticache describe-cache-clusters --max-items 1
probe "OpenSearch"        aws opensearch list-domain-names
probe "OpenSearch Svless" aws opensearchserverless list-collections
probe "Redshift"          aws redshift describe-clusters --max-items 1
probe "DynamoDB"          aws dynamodb list-tables --max-items 1
probe "ECS"               aws ecs list-clusters --max-results 1
probe "EKS"               aws eks list-clusters --max-results 1
# list-functions returns Environment.Variables in the response body, and probe() captures
# stdout on success. Project a count: the probe only needs to know the call succeeded.
probe "Lambda"            aws lambda list-functions --max-items 1 --query 'length(Functions)'
probe "SageMaker"         aws sagemaker list-endpoints --max-results 1
probe "Bedrock"           aws bedrock list-provisioned-model-throughputs --max-results 1
probe "S3"                aws s3api list-buckets
probe "ECR"               aws ecr describe-repositories --max-results 1
probe "Tagging API"       aws resourcegroupstaggingapi get-resources --resources-per-page 1
probe "Budgets"           aws budgets describe-budgets --account-id "$(aws sts get-caller-identity --query Account --output text)"
probe "Organizations"     aws organizations describe-organization
probe "Pricing"           aws pricing describe-services --max-results 1 --region us-east-1
# Both come from ViewOnlyAccess (iam:List*); they back the 1.4 permission-scope verdict.
# A FAILED row here means 1.4 must fail closed rather than report read-only (verified).
probe "IAM attached pol."  aws iam list-attached-role-policies --role-name "$AUDIT_ROLE"
probe "IAM inline pol."    aws iam list-role-policies --role-name "$AUDIT_ROLE"
```

For every `FAILED`: name the service, the error, the likely missing permission, and whether the audit continues with partial data.

### 2.2 Required services

**Cost Explorer.** `OptInRequired` means never activated. An account admin enables it in the Billing console; it backfills up to 12 months. Hard blocker for the whole audit.

**Compute Optimizer enrollment.** `aws compute-optimizer get-enrollment-status`. Not `Active` means stop and ask: opting in is `update-enrollment-status`, a write action you must not run. Give the user the command, note recommendations take 12 to 24 hours, and ask whether to wait or proceed without rightsizing. In unattended mode (Rule 8), never wait: proceed without rightsizing and mark the affected sections `PARTIAL`. Whenever Compute Optimizer is unavailable, run the 4.2.1 fallback so idle EC2 and ElastiCache detection does not disappear with it.

**Compute Optimizer savings need a second, separate opt-in.** Every `savingsOpportunity` value is computed by Cost Explorer and requires the **Receive Amazon EC2 resource recommendations** preference on the Cost Explorer preferences page. Without it you get findings and recommended types but empty savings, stripping the dollar figures out of most of Phase 5.

```bash
aws compute-optimizer get-ec2-instance-recommendations --max-results 5 \
  --query 'instanceRecommendations[].recommendationOptions[0].savingsOpportunity.estimatedMonthlySavings.value'
```

All nulls while recommendations otherwise exist means the preference is off. It is a console setting, not an API call. Warn, and fall back to the 8.1 pricing lookups.

**Cost Optimization Hub** needs an org-level opt-in. If unavailable, note it and rely on the per-service checks in Phase 4.

**Cost Explorer resource-level data.** The 8.1 observed-cost path calls `getCostAndUsageWithResources`, which fails with a validation error unless resource-level data is enabled on the Cost Explorer preferences page. It is a console preference, not an API call, and enabling it starts the Rule 5 standing daily charge for hourly usage records, so it is the user's decision. Do not probe it here: the probe is itself a billed request. Note the dependency, let 8.1 test it at first use, and fall back to the 8.1 pricing lookups if the call fails. The API also looks back at most 14 days, which is why 8.1 extrapolates, and returns hourly resource-level granularity for EC2 only; other services resolve at daily.

### 2.3 Metric coverage

Rightsizing accuracy depends on which metrics exist. Per region:

```bash
aws --region "$region" ec2 describe-instances --filters "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{ID:InstanceId,Monitoring:Monitoring.State}' --output table
aws --region "$region" cloudwatch list-metrics --namespace CWAgent --max-items 1
aws --region "$region" rds describe-db-instances \
  --query 'DBInstances[].{DB:DBInstanceIdentifier,MonitoringInterval:MonitoringInterval}' --output table
```

`Monitoring.State=disabled` means 5-minute metrics only. No `CWAgent` namespace means CPU-only analysis with no memory data, risking under-sizing memory-bound instances. `MonitoringInterval=0` means RDS Enhanced Monitoring is off.

### 2.4 Rank buckets by size

Do this once. Sections 4.8 and 4.9 reuse the output, and it avoids spending calls on empty buckets. The `head -15` below is a declared Rule 3 sample: S3 findings cover the **top 15 buckets by size**, and the report says so wherever they are used.

```bash
umask 077               # bucket names can themselves be sensitive
TOP_BUCKETS=$(mktemp)   # unpredictable path; do not hardcode /tmp file names
# 4.8 and 4.9 read this file. Checkpoint its contents into the workpaper as a top-buckets
# block if the audit may span sessions; the path itself does not survive one, and the
# preamble's cleanup handler removes it on exit.
for bucket in $(aws s3api list-buckets --query 'Buckets[].Name' --output text); do
  region=$(aws s3api get-bucket-location --bucket "$bucket" --query 'LocationConstraint' --output text)
  [ "$region" = "None" ] && region="us-east-1"
  size=$(LOOKBACK="$TS_7D" metric_agg AWS/S3 BucketSizeBytes "$region" Maximum \
           "Name=BucketName,Value=$bucket" "Name=StorageType,Value=StandardStorage")
  echo "$(num "$size") $bucket $region"
done | sort -rn | head -15 > "$TOP_BUCKETS"

while read -r size bucket region; do
  # Rule 3 carve-out: absence of the metrics configuration is the test.
  aws --region "$region" s3api get-bucket-metrics-configuration --bucket "$bucket" --id EntireBucket >/dev/null 2>&1 \
    || echo "NO REQUEST METRICS | $bucket | $((size/1073741824)) GB"
done < "$TOP_BUCKETS"
```

### 2.5 Preflight summary

Report a status table with `pass`, `warn`, or `fail` and the impact of each gap:

| Check | Impact if missing |
| --- | --- |
| Credentials valid | Cannot proceed |
| Credentials least-privilege | Write-capable credentials are a degraded mode needing the 1.4 acknowledgment |
| Cost Explorer enabled | No cost data, cannot proceed |
| Compute Optimizer enrolled | No rightsizing; idle EC2 and ElastiCache detection falls back to 4.2.1 |
| CE "EC2 resource recommendations" preference | Compute Optimizer savings fields come back empty |
| CE resource-level data enabled | 8.1 observed-cost figures fall back to pricing lookups |
| Cost Optimization Hub available | Falls back to slower per-service checks |
| CloudWatch metrics readable | Cannot detect idle resources |
| EC2 detailed monitoring | 5-minute rather than 1-minute granularity |
| CloudWatch agent memory metrics | CPU-only rightsizing |
| RDS Enhanced Monitoring | RDS rightsizing less accurate |
| S3 request metrics | Tiering recommendations less precise |
| Budgets readable | Cannot verify budget alerts |
| Organizations access | Account type unknown: treat as member, commitment and tag sections `PARTIAL` |

A `fail` on a blocking row means stop with remediation steps. Every `warn` carries into the report's limitations section. Cost allocation tag coverage is assessed in 7.1.

---

<!-- markdownlint-enable -->
