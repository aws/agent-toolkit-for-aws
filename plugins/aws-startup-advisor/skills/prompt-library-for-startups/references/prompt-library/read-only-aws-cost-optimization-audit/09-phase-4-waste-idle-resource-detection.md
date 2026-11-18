<!-- markdownlint-disable -->

## PHASE 4: WASTE & IDLE RESOURCE DETECTION

**Coverage is defined by the 3.5 inventory, not by this section list.** Sections 4.1 through 4.12 are fast-path playbooks for the resource types startups most often waste money on; 4.13 is the gate that reconciles what they analysed against what the account actually spends. Phase 4 is not `COMPLETE` until that reconciliation passes.

**Native detection first.** Sections 4.1 and 4.2 cover 12 resource types and apply context custom queries cannot, such as checking route table associations before flagging a DR NAT Gateway. Sections 4.2.1 onward are a fallback when native detection is unavailable and a supplement for what it does not cover. Say which sections you skipped because native detection covered them.

### 4.1 Cost Optimization Hub

MCP: `cost_optimization` `list_recommendation_summaries` grouped by `ActionType`, then `list_recommendations`.

```bash
aws cost-optimization-hub list-recommendations \
  --filter '{"actionTypes":["Stop","Rightsize","Upgrade","MigrateToGraviton","Delete","ScaleIn","PurchaseSavingsPlans","PurchaseReservedInstances"]}' \
  --output json --query 'items[].{Resource:resourceId,Region:region,Action:actionType,Current:currentResourceType,Rec:recommendedResourceType,Savings:estimatedMonthlySavings,Cost:estimatedMonthlyCost,Effort:implementationEffort,Restart:restartNeeded,Rollback:rollbackPossible,Source:source}'
```

Three API details, each of which silently blanks the savings column if you get it wrong:

- **`estimatedMonthlySavings` is a flat number**, currency in `currencyCode`. Compute Optimizer nests the same concept at `savingsOpportunity.estimatedMonthlySavings.value`. Using that path here yields nulls.
- **Omit `--order-by`.** Its `dimension` is a free-form string with no documented enum and a wrong value fails the call. Sort client-side.
- **`--max-results` is a page size, not a total.** Let the CLI paginate, or state that you sampled.

Enums: `actionTypes` are `Rightsize`, `Stop`, `Upgrade`, `PurchaseSavingsPlans`, `PurchaseReservedInstances`, `MigrateToGraviton`, `Delete`, `ScaleIn`; `implementationEfforts` are `VeryLow`, `Low`, `Medium`, `High`, `VeryHigh`. The filter above lists all eight action types deliberately; dropping one is undeclared sampling under Rule 3, and two are easy to lose (`Upgrade` is how the Hub reports gp2 to gp3, `ScaleIn` covers over-scaled groups). Also available: `estimatedSavingsPercentage`, `currentResourceSummary`, `recommendedResourceSummary`, `recommendationLookbackPeriodInDays`.

`rollbackPossible=true` with `restartNeeded=false` is an Appendix A Tier 1 candidate. `source` (`ComputeOptimizer` or `CostExplorer`) tells you where a row came from, but dedup against 4.2 and Phase 6 keys on resource ID plus action type per 8.1; the same resource arrives from both sources with different `source` values.

### 4.2 Compute Optimizer idle recommendations

Covers `EC2Instance`, `AutoScalingGroup`, `EBSVolume`, `ECSService`, `RDSDBInstance`, `NatGateway`, `DynamoDBTable`, `ElastiCacheCluster`, `MemoryDBCluster`, `DocumentDBCluster`, `WorkSpaces`, `SageMakerEndpoint`. Per region:

```bash
aws --region "$region" compute-optimizer get-idle-recommendations \
  --query 'idleRecommendations[].{Resource:resourceId,Type:resourceType,Finding:finding,Savings:savingsOpportunityAfterDiscounts.estimatedMonthlySavings.value,SavingsPreDiscount:savingsOpportunity.estimatedMonthlySavings.value,Why:findingDescription}' \
  --output table
```

`finding` distinguishes three cases needing different actions: `Idle` is running but unused, `Unattached` is orphaned, `Unused` is provisioned and never consumed. Carry `findingDescription` into the report; it is stronger evidence than a threshold you picked yourself.

**State the lookback window with every idle finding; it is part of the evidence.** The default analysis window is 14 days and it is not uniform: EBS volume and NAT Gateway attachment status is analysed over 32 days, WorkSpaces connection activity over 63, and the EC2, Auto Scaling group, and RDS window follows the account's rightsizing preference (14, 32, or 93 days; 93 is a paid feature needing enhanced infrastructure metrics). A 63-day verdict carries more confidence than a 14-day one, so carry the window into the report's evidence column (8.2 section 3) and set the owner's expectation accordingly. Verified against the Compute Optimizer idle recommendations documentation, September 2026.

**Savings figures: prefer `savingsOpportunityAfterDiscounts` wherever populated.** It nets off existing Savings Plans discounts and reflects what the customer actually stops paying, whereas `savingsOpportunity` is pre-discount and overstates the benefit for any account with commitments. This applies to every Compute Optimizer call in this document. State which figure you used.

### 4.2.1 Idle fallback without Compute Optimizer

Run this only where 4.2 is unavailable: not enrolled, the 2.2 wait declined, or the region unsupported. Say so when you do, and skip it entirely where 4.2 ran, so the same resource never arrives from both paths. Enrollment is opt-in and takes 12 to 24 hours to produce findings, so an unenrolled account is the common case in this segment, and without a fallback the most common waste item there, a running instance nobody uses, goes undetected while the section reads `PARTIAL`.

The evidence rules are 4.6's: a missing metric is `METRICS UNAVAILABLE`, never idle, and every finding still passes 4.13 step 5 against the bill. CPU alone cannot prove idleness, because a queue worker or proxy serves real traffic at 1 percent CPU, so require CPU and network to sit at the floor together. Per region:

```bash
for iid in $(aws --region "$region" ec2 describe-instances \
               --filters "Name=instance-state-name,Values=running" \
               --query 'Reservations[].Instances[].InstanceId' --output text); do
  cpu=$(metric_agg AWS/EC2 CPUUtilization "$region" Maximum "Name=InstanceId,Value=$iid")
  net=$(metric_agg AWS/EC2 NetworkOut     "$region" Sum     "Name=InstanceId,Value=$iid")
  if absent "$cpu" || absent "$net"; then
    echo "METRICS UNAVAILABLE | $region | $iid | cpu=$cpu netOut=$net"
    continue
  fi
  # Compare bytes in awk: num() would truncate the scientific notation large sums
  # arrive in (see 4.7).
  low_net=$(awk -v v="$net" 'BEGIN {print (v < 52428800) ? 1 : 0}')   # under 50 MB total in 14d
  if [ "$(num "$cpu")" -lt 3 ] && [ "$low_net" -eq 1 ]; then
    echo "IDLE EC2 CANDIDATE | $region | $iid | maxCPU=${cpu}% netOut14d=$(awk -v v="$net" 'BEGIN {printf "%.1f MB", v/1048576}')"
  fi
done

for cc in $(aws --region "$region" elasticache describe-cache-clusters \
              --query 'CacheClusters[].CacheClusterId' --output text); do
  conn=$(metric_agg AWS/ElastiCache CurrConnections "$region" Maximum "Name=CacheClusterId,Value=$cc")
  if absent "$conn"; then
    echo "METRICS UNAVAILABLE | $region | $cc | AWS/ElastiCache CurrConnections absent 14d"
  elif [ "$(num "$conn")" -le 4 ]; then
    # Redis and Valkey hold two to four internal connections open, so a handful of
    # connections is the engine's idle floor, not client traffic. Never require exactly zero.
    echo "IDLE ELASTICACHE CANDIDATE (connections at internal floor 14d) | $region | $cc"
  fi
done
```

The thresholds (daily-maximum CPU under 3 percent, under 50 MB of `NetworkOut` in 14 days, connections at the engine's internal floor) are conservative screens, not verdicts: this path lacks the context 4.2 applies, so every hit is a candidate for owner confirmation, classified per Rule 7. The daily `Maximum` here cannot show a quiet window; an instance that clears these thresholds but runs below its provisioned capacity belongs in 5.3, the same handoff 4.6 makes for databases. Findings here overlap 5.3's flat-near-zero branch by design; the 8.1 dedup on resource ID plus action type resolves it.

### 4.3 Data transfer and NAT egress

Data transfer is routinely 5 to 15 percent of a bill, is the line item customers are most often surprised by, and rarely appears in native recommendations.

```bash
aws ce get-cost-and-usage --time-period Start="$START_3M",End="$MONTH_START" \
  --granularity MONTHLY --metrics "UnblendedCost" --group-by Type=DIMENSION,Key=USAGE_TYPE \
  --output json | jq -r '[.ResultsByTime[-1].Groups[]
    | select(.Keys[0] | test("DataTransfer|Bytes|NatGateway"; "i"))
    | {k: .Keys[0], v: (.Metrics.UnblendedCost.Amount | tonumber)}]
    | sort_by(-.v) | .[] | select(.v > 1) | "\(.v | floor)\t\(.k)"'
```

Per region, inventory endpoints and measure NAT egress:

```bash
aws --region "$region" ec2 describe-vpc-endpoints \
  --query 'VpcEndpoints[].{ID:VpcEndpointId,Service:ServiceName,Type:VpcEndpointType,State:State}' --output table

for ngw in $(aws --region "$region" ec2 describe-nat-gateways --filter "Name=state,Values=available" \
               --query 'NatGateways[].NatGatewayId' --output text); do
  for m in BytesInFromSource BytesOutToDestination BytesInFromDestination BytesOutToSource; do
    v=$(LOOKBACK="$TS_32D" metric_agg AWS/NatGateway "$m" "$region" Sum "Name=NatGatewayId,Value=$ngw")
    # Report MB, not GB: integer GB division prints 0 for anything under 1 GiB, which is how
    # real traffic disappears. Format in awk, which handles the scientific notation the CLI
    # returns for large sums and that num() would truncate to a single digit.
    if absent "$v"; then echo "NAT $ngw $m 32d: NO DATA"
    else awk -v g="$ngw" -v m="$m" -v v="$v" \
           'BEGIN {printf "NAT %s %s 32d: %.1f MB\n", g, m, v/1048576}'; fi
  done
done
```

All four metrics matter: `NatGateway-Bytes` bills processed data in both directions, so egress alone understates the traffic behind the charge, and a `NO DATA` row is missing data rather than zero traffic. 4.7 turns these readings into a verdict.

Map each finding to one of four causes:

- **S3 or DynamoDB traffic through NAT.** A Gateway endpoint is free and removes both the NAT processing charge and the per-GB transfer. Signal: high NAT egress with no `s3` or `dynamodb` endpoint.
- **Cross-AZ tier chatter.** `DataTransfer-Regional-Bytes` usage types, caused by an app tier talking to a database or cache primary in another AZ. Fixed by AZ-aware routing or read replicas.
- **Uncached internet egress.** High `DataTransfer-Out-Bytes` from S3 or an ALB with no CloudFront in front. CloudFront egress is cheaper and absorbs repeat requests.
- **Interface endpoint sprawl.** Interface endpoints bill hourly per endpoint per AZ, so a rarely used one can cost more than the NAT traffic it replaced. Check low-traffic endpoints too.

Measure interface endpoint use before keeping one; the hour charge accrues whether traffic flows or not. Twelve endpoints across three AZs bill roughly 240 USD per month in hours alone, even with zero bytes processed. `BytesProcessed` in `AWS/PrivateLinkEndpoints` reports only while traffic flows, and `list-metrics` returns only metrics with datapoints in roughly the last two weeks, so absence there means no recent traffic:

```bash
for vpce in $(aws --region "$region" ec2 describe-vpc-endpoints \
                --filters Name=vpc-endpoint-type,Values=Interface \
                --query 'VpcEndpoints[].VpcEndpointId' --output text); do
  azs=$(aws --region "$region" ec2 describe-vpc-endpoints --vpc-endpoint-ids "$vpce" \
          --query 'length(VpcEndpoints[0].SubnetIds)' --output text)
  # An empty Metrics array is the actual test here: no datapoints published means no traffic.
  # But a denied or throttled call returns nothing either, and num() coerces both to 0 - so
  # the exit status, not the value, is what separates "no traffic" from "no answer". Without
  # this split, an AccessDenied prints a removal recommendation for a busy endpoint.
  if n=$(aws --region "$region" cloudwatch list-metrics --namespace AWS/PrivateLinkEndpoints \
           --metric-name BytesProcessed --dimensions "Name=VPC Endpoint Id,Value=$vpce" \
           --query 'length(Metrics)' --output text 2>&1); then
    if absent "$n"; then
      echo "METRICS UNAVAILABLE | $region | $vpce | list-metrics returned no value over ~2w; not a removal candidate"
    elif [ "$(num "$n")" -eq 0 ]; then
      echo "INTERFACE ENDPOINT, NO TRAFFIC ~2w | $region | $vpce | ${azs} AZs billing hourly"
    fi
  else
    echo "METRICS UNAVAILABLE | $region | $vpce | cloudwatch list-metrics failed: $n"
  fi
done
```

Cross-check against `VpcEndpoint-Hours` usage types in the 3.5 inventory, and price the hour rate per AZ with `aws_pricing`. An unused endpoint is Tier 2: removing it breaks private connectivity for anything that later needs that service, so confirm with the owner and state the reversal (recreate the endpoint).

Get per-GB rates from `aws_pricing` for the specific Region; they differ substantially.

### 4.4 Stopped instances, orphaned storage, public IPv4

Per region:

```bash
aws --region "$region" ec2 describe-instances --filters "Name=instance-state-name,Values=stopped" \
  --query "Reservations[].Instances[].{ID:InstanceId,Type:InstanceType,Reason:StateTransitionReason,Name:Tags[?Key=='Name'].Value|[0],Env:Tags[?Key=='$ENV_TAG_KEY'].Value|[0]}" --output table

aws --region "$region" ec2 describe-volumes --filters "Name=status,Values=available" \
  --query 'Volumes[].{ID:VolumeId,Size:Size,Type:VolumeType,Created:CreateTime}' --output table

aws --region "$region" ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].{IP:PublicIp,AllocationId:AllocationId}' --output table
aws --region "$region" ec2 describe-addresses --query 'length(Addresses)' --output text

aws --region "$region" ec2 describe-snapshots --owner-ids self \
  --query "Snapshots[?StartTime<='${START_90D}'].{ID:SnapshotId,Size:VolumeSize,Date:StartTime}" --output table

# Self-owned AMIs backing no instance. The AMI is free; its snapshots are not.
used=$(aws --region "$region" ec2 describe-instances --query 'Reservations[].Instances[].ImageId' \
         --output text | tr '\t' '\n' | sort -u)
for ami in $(aws --region "$region" ec2 describe-images --owners self \
               --query 'Images[].ImageId' --output text); do
  echo "$used" | grep -qx "$ami" || echo "UNUSED AMI | $region | $ami"
done
```

**Stopped instances carry data-loss risk.** The saving is only the EBS storage, so reward is small and terminating destroys the root volume unless a snapshot exists. Record owner, last stop date, snapshot presence, and environment first. `PROD` or `UNKNOWN` means "confirm with owner", not "terminate".

**Public IPv4 is charged whether attached or not.** Since 1 February 2024 every public IPv4 address costs USD 0.005 per hour, roughly 3.65 per month, including addresses on running instances; the old "only unassociated EIPs are billed" model is gone. Report two findings: unassociated Elastic IPs, which are pure waste and Tier 1 once you confirm no DNS record or allowlist references them; and total IPv4 footprint, since instances in private subnets behind NAT or a load balancer may not need a public address. Free Tier accounts get 750 in-use hours monthly for 12 months, so check account age before quoting IPv4 savings to an early-stage customer.

Check whether an unused AMI is referenced by a launch template or Auto Scaling group before proposing deregistration.

### 4.5 Idle load balancers

Per region:

```bash
for arn in $(aws --region "$region" elbv2 describe-load-balancers \
               --query 'LoadBalancers[].LoadBalancerArn' --output text); do
  tg=$(aws --region "$region" elbv2 describe-target-groups --load-balancer-arn "$arn" \
         --query 'length(TargetGroups)' --output text)
  [ "$tg" = "0" ] && echo "IDLE LB (no target groups) | $region | $arn"
done
aws --region "$region" elb describe-load-balancers \
  --query 'LoadBalancerDescriptions[?length(Instances)==`0`].{Name:LoadBalancerName,Created:CreatedTime}' --output table
```

A load balancer with target groups but no healthy targets is also a candidate, but check `RequestCount` over 14 days first: one fronting an Auto Scaling group that scaled to zero is working as designed.

### 4.6 Idle databases

Zero connections alone is not evidence. Background jobs, stored procedures, and event subscriptions run without persistent connections, so require all four signals over 14 days.

Two rules guard this check, because without them healthy production databases get flagged for deletion. First, `describe-db-instances` returns DocumentDB and Neptune instances too, and each engine publishes to its own CloudWatch namespace: query `AWS/RDS` for a DocumentDB instance and every metric returns `None`. Second, a missing metric is missing data, never zero (Rule 3): four `None` values coerced to zeros read as a perfectly idle database and manufacture a delete recommendation. Branch on `Engine`, and emit `METRICS UNAVAILABLE` instead of `IDLE` when any signal is absent. Per region:

```bash
aws --region "$region" rds describe-db-instances \
  --query 'DBInstances[].[DBInstanceIdentifier,Engine]' --output text |
while read -r db engine; do
  case "$engine" in
    docdb*)   ns="AWS/DocDB" ;;   # DocumentDB: same four metric names, own namespace
    neptune*) echo "MANUAL REVIEW | $region | $db | engine=$engine | Neptune publishes different metric names in AWS/Neptune; RDS thresholds do not apply"; continue ;;
    *)        ns="AWS/RDS" ;;
  esac
  dim="Name=DBInstanceIdentifier,Value=$db"
  c=$(metric_agg "$ns" DatabaseConnections "$region" Maximum "$dim")
  u=$(metric_agg "$ns" CPUUtilization      "$region" Maximum "$dim")
  r=$(metric_agg "$ns" ReadIOPS            "$region" Maximum "$dim")
  w=$(metric_agg "$ns" WriteIOPS           "$region" Maximum "$dim")
  if [ "$c" = "None" ] || [ -z "$c" ] || [ "$u" = "None" ] || [ -z "$u" ] ||
     [ "$r" = "None" ] || [ -z "$r" ] || [ "$w" = "None" ] || [ -z "$w" ]; then
    echo "METRICS UNAVAILABLE | $region | $db | engine=$engine ns=$ns | conns=$c cpu=$u readIOPS=$r writeIOPS=$w"
    continue   # missing data is a Rule 3 finding, not an idle database
  fi
  if [ "$(num "$c")" -lt 10 ] && [ "$(num "$u")" -lt 5 ] &&
     [ "$(num "$r")" -lt 100 ] && [ "$(num "$w")" -lt 50 ]; then
    echo "IDLE | $region | $db | engine=$engine | conns=$(num "$c") cpu=$(num "$u") readIOPS=$(num "$r") writeIOPS=$(num "$w")"
  fi
done

for cl in $(aws --region "$region" redshift describe-clusters \
              --query 'Clusters[].ClusterIdentifier' --output text); do
  c=$(metric_agg AWS/Redshift DatabaseConnections "$region" Maximum "Name=ClusterIdentifier,Value=$cl")
  if absent "$c"; then
    echo "METRICS UNAVAILABLE | $region | $cl | AWS/Redshift DatabaseConnections absent 14d; not an idle verdict"
  elif [ "$(num "$c")" -eq 0 ]; then
    echo "IDLE REDSHIFT (0 connections 14d) | $region | $cl"
  fi
done

aws --region "$region" redshift describe-clusters \
  --query 'Clusters[].{ID:ClusterIdentifier,NodeType:NodeType,Nodes:NumberOfNodes}' --output table
aws --region "$region" redshift describe-reserved-nodes \
  --query 'ReservedNodes[].{NodeType:NodeType,Count:NodeCount,State:State}' --output table
```

Check whether an idle RDS instance is a read replica, Multi-AZ standby, or DR target; all three legitimately show low activity. Pausing a Redshift cluster preserves data and is reversible, so prefer it over deletion. Compare active clusters against reserved nodes for the commitment gap.

**Route the middle ground to 5.3.1.** This check has two outcomes, `IDLE` or silence, so a database that clears the thresholds while running far below its provisioned capacity produces nothing here. That is the most common database finding in a non-production account and it belongs in 5.3.1, which profiles by hour of day. List every such instance explicitly, with its four readings, so the handoff is visible rather than implied. Do not turn a daily `Maximum` from this section into a scheduling claim: it cannot show a quiet window, and any off-hours percentage derived from it is invented.

**RDS Extended Support.** A database on an engine version past its standard support window bills a separate per-vCPU-hour Extended Support charge that can exceed the instance's own cost several times over, and often explains a month-over-month increase on its own. It is invisible to instance-level checks and to Compute Optimizer, which reported those same instances `Optimized`. The 3.5 inventory is the detector:

```bash
grep -i 'ExtendedSupport' "$SPEND_INVENTORY" | sort -t$'\t' -k3 -rn
```

Any hit is a finding on its own. The remediation is a major engine version upgrade (Appendix A Tier 2, needs validation), and the saving is the full Extended Support line.

**OpenSearch Serverless.** A collection bills an always-on OCU minimum even at zero traffic, and `opensearch list-domain-names` does not see collections; these calls need the `aoss:` permissions from the Prerequisites supplement. Per region:

```bash
aws --region "$region" opensearchserverless list-collections \
  --query 'collectionSummaries[].{ID:id,Name:name,Status:status}' --output table

# OCU metrics are account-level: dimension ClientId is the account ID.
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
socu=$(num "$(metric_agg AWS/AOSS SearchOCU   "$region" Maximum "Name=ClientId,Value=$ACCOUNT_ID")")
iocu=$(num "$(metric_agg AWS/AOSS IndexingOCU "$region" Maximum "Name=ClientId,Value=$ACCOUNT_ID")")
echo "AOSS standing OCUs 14d | $region | search=$socu indexing=$iocu"
```

A standing OCU level beside near-zero workload is the finding: the account pays the floor for collections doing little. A collection paying several hundred USD per month in OCU floor while its queries would cost a few dollars is a typical shape. Price OCU-hours with `aws_pricing`, and verify current OCU minimums with `aws-knowledge`; they have changed over time. Consolidation or deletion is the fix, with Rule 7 sign-off and a data-loss statement, since deleting a collection deletes its data.

### 4.7 Idle NAT Gateways

Prefer 4.2, which checks route table associations.

**Read all four byte metrics, and let the bill arbitrate.** `NatGateway-Bytes` charges every byte the gateway processes, in both directions and on both legs, while `BytesOutToDestination` measures one leg only. A zero on that single metric therefore cannot falsify a byte charge, and treating it as proof of idleness is how a NAT that processed real traffic gets proposed for deletion. Sum `BytesInFromSource`, `BytesOutToDestination`, `BytesInFromDestination`, and `BytesOutToSource`, and reconcile the total against `NatGateway-Bytes` in the 3.5 inventory per 4.13 step 5.

**Know the limit of that arbitration: Cost Explorer cannot attribute NAT bytes to a gateway.** Usage types carry a Region billing code, not a resource ID, so `NatGateway-Bytes` resolves no finer than the Region no matter how the query is grouped. The bill can therefore settle a zero-metric verdict only where the Region holds exactly **one** gateway. With one gateway per AZ - the normal shape - a single busy gateway would otherwise mark every other gateway in the Region as active, which suppresses the finding this section exists to produce. Branch on the count instead, and where attribution is genuinely unavailable, say so: an unresolvable line item is a finding, an omitted one is not.

Scope the charge to the Region with its billing code, and resolve that code from the AWS Region billing codes reference rather than by pattern. Two irregularities catch people out. `eu-west-1` is `EU`, not `EUW1`. And `us-east-1` is `USE1` in that table, but **the prefix is omitted from many us-east-1 usage types**: AWS's own S3 billing documentation states it (`TimedStorage-ByteHrs`, not `USE1-TimedStorage-ByteHrs`), and the legacy EC2 and VPC usage types, `NatGateway-Bytes` among them, follow the same convention, while newer ones such as CloudWatch's `USE1-S3-Egress-Bytes` do carry it. So in us-east-1 match both the prefixed and the bare form; a bare usage type with no Region code *is* us-east-1. A grep for one form only silently finds nothing, `NAT_CENTS` reads 0, and the arbitration below stops arbitrating without saying so. Fallback, per region:

```bash
# Billed data processing for THIS Region, in cents so the comparison stays integer.
# No matching line yields 0, which is a valid answer: nothing was billed - but only once
# the pattern is right, so the block prints what it matched.
REGION_CODE=XXXX   # agent-resolved billing code for $region: USE1, EU, EUC1, APS3, ...
if [ "$region" = "us-east-1" ]; then
  NAT_PATTERN=$'\t''\(USE1-\)\?NatGateway-Bytes'   # prefixed or bare: both are us-east-1
else
  NAT_PATTERN=$'\t'"${REGION_CODE}-NatGateway-Bytes"
fi
NAT_CENTS=$(grep -i -- "$NAT_PATTERN" "$SPEND_INVENTORY" \
              | awk -F'\t' '{t+=$3} END {printf "%.0f", t*100}')
echo "NAT bytes billed in $region ($REGION_CODE): $(grep -c -i -- "$NAT_PATTERN" "$SPEND_INVENTORY") inventory line(s), ${NAT_CENTS:-0} cents"

# Gateway count decides whether the Region-level charge can arbitrate at all.
NGW_IDS=$(aws --region "$region" ec2 describe-nat-gateways --filter "Name=state,Values=available" \
            --query 'NatGateways[].NatGatewayId' --output text)
NGW_COUNT=$(echo "$NGW_IDS" | wc -w)

for ngw in $NGW_IDS; do
  dim="Name=NatGatewayId,Value=$ngw"
  c=$(LOOKBACK="$TS_32D" metric_agg AWS/NatGateway ActiveConnectionCount "$region" Maximum "$dim")

  # Every byte metric the data-processing charge bills on, not just egress to the internet.
  # Accumulate in awk: byte sums arrive as floats or scientific notation, and num() would
  # truncate 1.7382E11 to 1, turning 173 GB into a rounding artifact.
  miss=0; total=0
  for m in BytesInFromSource BytesOutToDestination BytesInFromDestination BytesOutToSource; do
    v=$(LOOKBACK="$TS_32D" metric_agg AWS/NatGateway "$m" "$region" Sum "$dim")
    if absent "$v"; then miss=1
    else total=$(awk -v a="$total" -v b="$v" 'BEGIN {printf "%.0f", a + b}'); fi
  done

  # Route table references: a referenced gateway with no traffic is a standby path, not waste.
  refs=$(aws --region "$region" ec2 describe-route-tables \
           --filters "Name=route.nat-gateway-id,Values=$ngw" \
           --query 'length(RouteTables)' --output text)

  if absent "$c" || [ "$miss" -eq 1 ]; then
    echo "METRICS UNAVAILABLE | $region | $ngw | one or more AWS/NatGateway metrics absent over 32d; not an idle verdict"
  elif [ "$(num "$c")" -eq 0 ] && [ "$total" -eq 0 ]; then
    nat_usd=$(awk -v c="$NAT_CENTS" 'BEGIN {printf "%.2f", c/100}')
    if [ "${NAT_CENTS:-0}" -gt 0 ] && [ "$NGW_COUNT" -eq 1 ]; then
      # Sole gateway in the Region, so the Region's byte charge is unambiguously this one's.
      echo "TRAFFIC BILLED, METRICS ZERO | $region | $ngw | sole gateway in Region; NatGateway-Bytes billed $nat_usd USD against 0 measured bytes 32d; treat as ACTIVE, reconcile before any deletion (4.13 step 5)"
    elif [ "${NAT_CENTS:-0}" -gt 0 ]; then
      # Bytes were billed somewhere in the Region, but not attributably here. Neither verdict
      # is available from this data, so report the gap rather than guessing either way.
      echo "IDLE CANDIDATE, REGION BILLED BYTES, PER-GATEWAY ATTRIBUTION UNAVAILABLE | $region | $ngw | 0 connections and 0 bytes on all four metrics 32d, but $NGW_COUNT gateways share $nat_usd USD of NatGateway-Bytes in this Region and Cost Explorer cannot attribute bytes per gateway; referenced by $(num "$refs") route table(s). Resolve with VPC Flow Logs filtered on this gateway's ENI before proposing anything. NOT a deletion candidate as it stands (4.13 step 5)"
    elif [ "$(num "$refs")" -gt 0 ]; then
      echo "NAT GW NO TRAFFIC, ROUTED | $region | $ngw | 0 bytes 32d but referenced by $refs route table(s): standby path, hours-only saving, owner confirmation required"
    else
      echo "IDLE NAT GW (32d no connections, no bytes any direction, no route table reference) | $region | $ngw"
    fi
  fi
done
```

Five outcomes, and only one of them is a deletion candidate. Never publish a NAT finding without recording which branch produced it.

| Verdict | Meaning | Action |
| --- | --- | --- |
| `METRICS UNAVAILABLE` | One or more of the five metrics absent over 32 days | No verdict. Rule 3 finding |
| `TRAFFIC BILLED, METRICS ZERO` | Sole gateway in the Region, and the Region was billed for bytes | Bill wins. Divide the charge by the Region's per-GB rate from `aws_pricing` to state the implied volume, and report the gateway as **active** |
| `IDLE CANDIDATE, REGION BILLED BYTES, PER-GATEWAY ATTRIBUTION UNAVAILABLE` | Zero on every metric, but other gateways in the Region could account for the Region's byte charge | Report the attribution gap as the finding. The hourly charge is real and quantifiable; the data-processing question is not answerable from Cost Explorer. Name VPC Flow Logs on the gateway's ENI as the resolution, and propose nothing until it runs |
| `NAT GW NO TRAFFIC, ROUTED` | Zero bytes, no Region byte charge, but a route table points at it | Real finding worth the hourly charge. The reversal is losing egress for anything that later needs it, so owner confirmation, never a delete command |
| `IDLE NAT GW` | Zero bytes, no Region byte charge, no route table reference | The deletion candidate |

Do not collapse the third row into the second. An account-wide byte comparison lets one busy gateway mark every other gateway in the Region active, so in a multi-AZ account the last two rows become unreachable and 4.7 produces nothing.

### 4.8 S3 storage

Uses the size-ranked list from 2.4.

```bash
while read -r size bucket region; do
  # Rule 3 carve-out: absence of the configuration is the test.
  aws --region "$region" s3api get-bucket-lifecycle-configuration --bucket "$bucket" >/dev/null 2>&1 \
    || echo "NO LIFECYCLE | $bucket | $((size/1073741824)) GB"
  mp=$(aws --region "$region" s3api list-multipart-uploads --bucket "$bucket" \
         --query 'length(Uploads)' --output text)
  [ "$(num "$mp")" -gt 0 ] && echo "INCOMPLETE MULTIPART | $bucket | $mp parts billed as storage"
done < "$TOP_BUCKETS"   # from 2.4; on a resumed session rehydrate the top-buckets block or re-run 2.4
```

Incomplete multipart uploads bill as storage indefinitely and do not appear in the console object list, which makes them a common quiet cost. The fix is a lifecycle rule with `AbortIncompleteMultipartUpload`, Tier 1. Rank lifecycle findings by size: a 10 TB bucket with no policy matters, a 2 MB one does not.

### 4.9 CloudWatch Logs retention

Default retention is never expire, so storage grows without bound; at scale this is often a top-ten cost driver. `describe-log-groups` returns at most 50 per page, so let the CLI paginate and do not pass `--limit`. Per region:

```bash
aws --region "$region" logs describe-log-groups \
  --query 'logGroups[?!not_null(retentionInDays)].{Name:logGroupName,StoredBytes:storedBytes,Class:logGroupClass}' \
  --output json | jq -r 'sort_by(-.StoredBytes)[] | select(.StoredBytes > 10737418240)
    | "NO RETENTION >10GB | \(.Name) | \(.StoredBytes/1073741824|floor) GB | \(.Class // "STANDARD")"'

aws --region "$region" logs describe-log-groups --log-group-class STANDARD \
  --query 'logGroups[].{Name:logGroupName,StoredBytes:storedBytes}' \
  --output json | jq -r 'sort_by(-.StoredBytes) | .[:20][]
    | "STANDARD CLASS | \(.Name) | \(.StoredBytes/1073741824|floor) GB"'
```

There are three log classes, not two: `STANDARD`, `INFREQUENT_ACCESS`, `DELIVERY`. Filter server-side with `--log-group-class`, because a client-side `!= INFREQUENT_ACCESS` test wrongly flags Delivery groups, which exist only to route Lambda logs to S3 or Firehose and retain events for a fixed two days. `logGroupClass` is absent rather than `STANDARD` on older groups, hence the `jq` default.

Infrequent Access cuts ingestion cost but supports a feature subset, so check the consumers first: `GetLogEvents` and `FilterLogEvents` are **unsupported**, so anything tailing or reading the group through those APIs breaks; metric filters, subscription filters, and Live Tail are also unavailable. Logs Insights querying is supported on IA and is not a disqualifier, and since March 2026 neither are data protection masking or OpenSearch PPL and SQL; anomaly detection, field indexing, and embedded metric format remain Standard-only. Good candidates: RDS audit and slow query logs, VPC Flow Logs, compliance-retention logs nobody reads. Get per-GB rates from `aws_pricing`.

**Intelligent Tiering** (GA July 2026) is a second, complementary lever: an account-level setting that moves **stored** log data across Standard, Infrequent Access, and Archive Instant Access storage tiers on 30- and 90-day access patterns, promoting data back to Standard on access, with no feature restrictions. The IA log class cuts ingestion cost per group and restricts features; Intelligent Tiering cuts storage cost account-wide and restricts nothing, so the two combine. Check whether it is configured, per region:

```bash
# Needs logs:GetStorageTierPolicy from the Prerequisites supplement. Per Rule 3 the outcomes
# differ: a not-found or empty response is "not configured", AccessDenied is a permission
# finding, and neither may be reported as the other.
aws --region "$region" logs get-storage-tier-policy
```

When `TimedStorage` usage types are material in the 3.5 inventory and no storage tier policy exists, recommend enabling Intelligent Tiering as Appendix A Tier 1: account-level, non-destructive, no per-group changes. Verify tier pricing and regional availability with `aws-knowledge`; at GA it covered all commercial Regions except me-south-1 and me-central-1.

**The CloudWatch bill is more than log storage.** Split the CloudWatch spend by usage type before concluding anything from the storage checks above; an account can pay tens of USD per month for custom metrics while this section's 10 GiB storage threshold emits nothing. When the bill is metrics, a check that looks only at logs misses it.

```bash
grep -i 'CloudWatch' "$SPEND_INVENTORY" | sort -t$'\t' -k3 -rn | head -15
```

Usage types containing `MetricMonitorUsage` are custom metrics billed per metric-month; alarm, dashboard, and API-call usage types are similarly named. When metrics dominate the CloudWatch line, inventory the custom namespaces (`list-metrics`, filtering out `AWS/` namespaces) and flag orphaned emitters and high-cardinality namespaces for owner review; the usual causes are an agent or exporter left running after a migration, and per-dimension metric explosions.

### 4.10 SageMaker

Per region:

```bash
aws --region "$region" sagemaker list-notebook-instances --status-equals InService \
  --query 'NotebookInstances[].{Name:NotebookInstanceName,Type:InstanceType,Modified:LastModifiedTime}' --output table

for ep in $(aws --region "$region" sagemaker list-endpoints --status-equals InService \
              --query 'Endpoints[].EndpointName' --output text); do
  i=$(metric_agg AWS/SageMaker Invocations "$region" Sum "Name=EndpointName,Value=$ep")
  if absent "$i"; then
    echo "METRICS UNAVAILABLE | $region | $ep | AWS/SageMaker Invocations absent 14d; not an idle verdict"
  elif [ "$(num "$i")" -eq 0 ]; then
    echo "IDLE SAGEMAKER ENDPOINT (0 invocations 14d) | $region | $ep"
  fi
done

aws --region "$region" sagemaker list-training-jobs --status-equals InProgress \
  --query 'TrainingJobSummaries[].{Name:TrainingJobName,Created:CreationTime}' --output table
```

A running notebook with an old `LastModifiedTime` is a strong signal, but confirm with the owner. Long-running training jobs may be stuck or legitimately long.

### 4.11 Containers: EKS, ECS, ECR

Per region:

```bash
for c in $(aws --region "$region" eks list-clusters --query 'clusters[]' --output text); do
  for ng in $(aws --region "$region" eks list-nodegroups --cluster-name "$c" --query 'nodegroups[]' --output text); do
    aws --region "$region" eks describe-nodegroup --cluster-name "$c" --nodegroup-name "$ng" \
      --query 'nodegroup.{NG:nodegroupName,Types:instanceTypes,Desired:scalingConfig.desiredSize,Min:scalingConfig.minSize,Max:scalingConfig.maxSize,Capacity:capacityType}' --output table
  done
  aws --region "$region" eks list-addons --cluster-name "$c" --query 'addons[]' --output text
done

for c in $(aws --region "$region" ecs list-clusters --query 'clusterArns[]' --output text); do
  aws --region "$region" ecs describe-clusters --clusters "$c" --include SETTINGS \
    --query 'clusters[].{Name:clusterName,CapacityProviders:capacityProviders}' --output table
  for s in $(aws --region "$region" ecs list-services --cluster "$c" --query 'serviceArns[]' --output text); do
    aws --region "$region" ecs describe-services --cluster "$c" --services "$s" \
      --query 'services[].{Name:serviceName,Desired:desiredCount,Running:runningCount,Launch:launchType}' --output table
  done
done

for repo in $(aws --region "$region" ecr describe-repositories \
                --query 'repositories[].repositoryName' --output text); do
  n=$(aws --region "$region" ecr list-images --repository-name "$repo" \
        --filter tagStatus=UNTAGGED --query 'length(imageIds)' --output text)
  [ "$(num "$n")" -gt 0 ] && echo "ECR UNTAGGED | $region | $repo | $n images"
done
```

Look for node groups where `minSize` equals `maxSize`, meaning no elasticity; no Karpenter or Cluster Autoscaler; all-On-Demand where Spot would fit; and ECS services with desired count above zero and running count of zero, a broken deployment still holding capacity. Count EKS control planes as a fixed per-cluster charge no Savings Plan discounts; a barely used cluster's cheapest fix is consolidation, not commitment.

**Untagged ECR images are not automatically safe to delete.** Deployments can reference an image by digest, so an untagged image may be running in production. Recommend a lifecycle policy expiring untagged images older than 14 to 30 days, which lets running workloads roll forward. Do not recommend bulk deletion.

### 4.12 DynamoDB, EBS volume type, Lambda

Per region:

```bash
for t in $(aws --region "$region" dynamodb list-tables --query 'TableNames[]' --output text); do
  mode=$(aws --region "$region" dynamodb describe-table --table-name "$t" \
           --query 'Table.BillingModeSummary.BillingMode' --output text)
  # Absent BillingModeSummary means PROVISIONED, the original default.
  if [ "$mode" = "PROVISIONED" ] || [ "$mode" = "None" ]; then
    p=$(aws --region "$region" dynamodb describe-table --table-name "$t" \
          --query 'Table.ProvisionedThroughput.ReadCapacityUnits' --output text)
    peak=$(num "$(metric_agg AWS/DynamoDB ConsumedReadCapacityUnits "$region" Maximum "Name=TableName,Value=$t")")
    echo "DDB | $region | $t | provisionedRCU=$p | peakConsumed=$peak"
  fi
done

aws --region "$region" ec2 describe-volumes --filters Name=volume-type,Values=gp2 \
  --query 'Volumes[].{ID:VolumeId,Size:Size,IOPS:Iops,State:State}' --output table
```

Peak consumed below 20 percent of provisioned over 14 days makes a table a candidate for on-demand mode or downsizing; check whether auto scaling is already attached first.

gp3 is generally cheaper per GB than gp2 with a better performance baseline, and the modification is online. Get both per-GB prices per Region from `aws_pricing`; the gap varies and the arithmetic changes for volumes with high provisioned IOPS or throughput.

Uninvoked Lambda functions cost nothing unless they have provisioned concurrency, so treat unused functions as hygiene rather than savings, and check provisioned concurrency before quoting a figure.

### 4.12.1 Amazon Bedrock

**Gate.** Check the 3.5 inventory for Bedrock lines first: none means `SKIPPED (no Bedrock spend)`, spend below the 4.13 threshold means note the amount and stop here. This is the one deliberate exception to the no-more-playbooks stance behind 4.13: the generic fallback can inventory and price, but the levers that actually move a GenAI bill (model tier, token mix, caching, batch, Provisioned Throughput) are invisible to it.

```bash
grep -i 'Bedrock' "$SPEND_INVENTORY" | sort -t$'\t' -k3 -rn
```

No extra Cost Explorer call: the 3.5 inventory already carries the usage types, whose names encode Region prefix, billing dimension, and model ID, for example `USE1-InvocationsModelInputTokens:anthropic.claude-sonnet-4` (input tokens, us-east-1) or `USE1-ProvisionedModelUnit:...` (Provisioned Throughput). Group by model, split input from output tokens, and rank by cost.

**Model tier concentration.** Price the input and output token rates for each model in use with `aws_pricing` or `aws-knowledge`; never quote a tier multiple from memory - the gap between a small model and a frontier model on similar tasks is one to two orders of magnitude and moves with every release. Spend concentrated on an expensive model is a finding, and the remediation is an evaluation, not a downgrade: ask whether the tasks routed to that model have been tested on a cheaper one. Model right-sizing works like EC2 right-sizing - the audit names the concentration, the customer tests the alternative.

**Token mix.** Compute the input-to-output cost ratio per model from the inventory. Heavily input-skewed (above roughly 5:1 by cost) suggests stable system prompts or RAG context resent on every call: prompt caching, where the model supports it, prices cached input tokens at roughly a tenth of the standard rate (verify per model with `aws-knowledge`), and context pruning cuts what the model reads but never uses. Heavily output-skewed suggests generous `max_tokens` settings or agentic loops emitting long traces. Both are `LOW`-confidence findings per 8.1 until the workload owner confirms the pattern.

**Provisioned Throughput.** Per region:

```bash
aws --region "$region" bedrock list-provisioned-model-throughputs \
  --query 'provisionedModelSummaries[].{Name:provisionedModelName,Model:modelArn,Units:modelUnits,Commitment:commitmentDuration,Status:status,Created:creationTime}' \
  --output table
```

For each: compare capacity against the invocation spend from the inventory (CloudWatch `AWS/Bedrock` invocation metrics refine this). Under-used units are the same finding as an oversized instance, but a committed unit (`OneMonth`, `SixMonths`) cannot be released mid-term, so per 4.13 step 6 the saving dates to commitment expiry, which makes it Tier 2, not Tier 1. No `commitmentDuration` means hourly billing: verify it is intentional and not a load-test leftover, which is a genuine Tier 2 stop candidate. The reverse finding exists too: sustained on-demand token spend can justify Provisioned Throughput, but that is a binding commitment - route it through the Phase 6 credit gate and clean-up-first ordering like every other commitment, price it with `aws_pricing`, and give it the Appendix A commitment treatment: console path, named approver, no runnable command.

**Batch and Region.** Batch inference prices at half of on-demand for workloads that tolerate hours of delay (verify current terms with `aws-knowledge`); billing data cannot tell real-time from batch-eligible apart, so this is a question for the owner, not an API check. Where the same model appears under several Region prefixes, price both Regions: model pricing varies by Region, and inference placed for availability may be paying a premium worth stating.

Permissions: `bedrock:ListProvisionedModelThroughputs` comes from the Prerequisites supplement; `ViewOnlyAccess` already carries `bedrock:ListCustomModels`. Without the supplement action, mark this section `PARTIAL (no Bedrock API access)` and keep the inventory-based findings, which need no Bedrock API at all.

### 4.13 Coverage reconciliation (completion gate)

Phase 4 may not be marked `COMPLETE` until it reconciles against the 3.5 inventory. The playbooks above can all run cleanly and still walk past an account's largest single line item. This gate makes sure they do not.

1. **Materiality threshold: 2 percent of the last complete month's bill, or 50 USD per month, whichever is higher.** State the threshold used. Every service at or above it requires either a written finding or an explicit "no action, and why"; silence is not an answer.
2. **Reconcile.** Walk the 3.5 service ranking top-down. Mark each material service with how it was analysed: `native` (4.1/4.2), `playbook` (4.2.1, 4.3 to 4.12), `fallback` (below), or `not analysed` with the reason. Subtract analysed spend from the inventory total and state the residual as a percentage of the bill.
3. **Generic fallback** for a material service with no playbook. This document deliberately has no dedicated section for FSx, EFS, Athena, Glue, Kinesis, MSK, ACM, and most of the rest of the catalog; the fallback is how they get covered without a longer checklist:
   - Pull the service's usage types from `$SPEND_INVENTORY`; the usage type names the billable unit (provisioned throughput, OCU-hours, private CA months, shard hours).
   - Inventory the resources with the service's own `List*` and `Describe*` calls plus `tag:GetResources` (the `ViewOnlyAccess` policy grants the metadata reads).
   - Price the unit with `aws_pricing` and check the count and size against what the usage suggests is needed.
   - Report the line item as a named finding: "no service-specific playbook - manual review required", with the resource inventory, monthly cost, and the obvious question to ask (for example an ACM Private CA in a dev account at 400 USD per month, or an FSx file system sized far above its data). Naming the gap is a finding; omitting it is not.
4. **Publish the coverage table** in the report (see 8.2 section 2): service, monthly cost, share of bill, analysed yes or no, method. A reader must be able to see what was skipped without reverse-engineering it from silence.
5. **Reverse reconciliation: every idle finding back to the bill.** Steps 1 to 4 answer "did we look at this service." This step answers the opposite question, "does our verdict agree with what AWS charged," and it is the one that catches a fabricated zero. For each resource flagged idle, unused, or delete-candidate, look up its usage types in `$SPEND_INVENTORY` and classify the charge:
   - **Fixed charges only** (`NatGateway-Hours`, `LoadBalancerUsage`, `InstanceUsage`, endpoint hours, OCU floor): the bill accrues whether traffic flows or not, so it corroborates the finding. Proceed.
   - **Usage-based charges present and non-zero** (`NatGateway-Bytes`, `DataTransfer-*`, request or IO counts): the account was billed for work the metric says did not happen. The bill wins. Report `TRAFFIC BILLED, METRICS ZERO` with both numbers and the implied volume at the Region's per-unit rate, treat the resource as active, and do not propose deletion. Reconcile before concluding: the metric may be the wrong one for that charge, may cover the wrong leg of the path, or may simply be absent.
   - **No usage type at all** in the inventory: the resource is genuinely costing nothing, so there is no saving to claim. Report it as hygiene, not savings.

   State the outcome of this step for every Tier 2 and Tier 3 candidate in the workpaper. A delete recommendation whose reverse reconciliation was not performed does not ship.
6. **Commitment coverage timing, for every deletion or stop candidate.** Where a flagged resource's usage is coverable by a Savings Plan or RI (EC2, Fargate, Lambda, and the RI services), check the 6.1 coverage data before dating the saving. A resource fully covered by an active commitment produces no cash saving until the commitment expires or other eligible usage absorbs the freed coverage: the commitment bills the same amount either way. Do not conclude the resource should keep running until expiry - that is sunk-cost reasoning, and running idle hardware recovers nothing. Recommend the deletion or stop as normal, date the realised saving to commitment expiry or absorption, and name the real levers in Appendix A: modifying the RI, exchanging a convertible RI, or selling a standard EC2 RI on the Reserved Instance Marketplace. Savings Plans and RIs do not auto-renew unless a queued purchase exists, so the follow-up is a reminder to re-evaluate before expiry, not a cancellation.

```bash
awk -F'\t' '{t+=$3} END {printf "3.5 inventory total: %.2f USD\n", t}' "$SPEND_INVENTORY"

# Reverse reconciliation, per flagged resource: what did AWS actually bill for this service?
# Any usage-based line here contradicts a zero-metric idle verdict (step 5).
grep -iE 'NatGateway-Bytes|DataTransfer|Requests|IOUsage|ProcessedBytes' "$SPEND_INVENTORY" \
  | sort -t$'\t' -k3 -rn
```

---

<!-- markdownlint-enable -->
