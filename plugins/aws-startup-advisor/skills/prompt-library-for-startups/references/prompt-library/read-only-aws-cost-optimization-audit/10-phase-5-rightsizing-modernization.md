<!-- markdownlint-disable -->

## PHASE 5: RIGHTSIZING & MODERNIZATION

### 5.1 Compute Optimizer recommendations

Needs both opt-ins from 2.2. Findings are regional. The 4.2 rule on `savingsOpportunityAfterDiscounts` applies to all of these. Per region:

```bash
CO_SAVE='recommendationOptions[0].savingsOpportunityAfterDiscounts.estimatedMonthlySavings.value'

aws --region "$region" compute-optimizer get-ec2-instance-recommendations \
  --query "instanceRecommendations[].{Instance:instanceName,Current:currentInstanceType,Finding:finding,Rec:recommendationOptions[0].instanceType,Risk:recommendationOptions[0].performanceRisk,Savings:$CO_SAVE}" --output table

aws --region "$region" compute-optimizer get-ec2-instance-recommendations \
  --recommendation-preferences '{"cpuVendorArchitectures":["AWS_ARM64"]}' \
  --query "instanceRecommendations[].{Instance:instanceName,Current:currentInstanceType,Graviton:recommendationOptions[0].instanceType,Savings:$CO_SAVE}" --output table

aws --region "$region" compute-optimizer get-auto-scaling-group-recommendations \
  --query "autoScalingGroupRecommendations[].{ASG:autoScalingGroupName,Current:currentConfiguration.instanceType,Rec:recommendationOptions[0].configuration.instanceType,Savings:$CO_SAVE}" --output table

aws --region "$region" compute-optimizer get-ebs-volume-recommendations \
  --query 'volumeRecommendations[].{Volume:volumeArn,CurrentType:currentConfiguration.volumeType,CurrentSize:currentConfiguration.volumeSize,RecType:volumeRecommendationOptions[0].configuration.volumeType,RecSize:volumeRecommendationOptions[0].configuration.volumeSize,Savings:volumeRecommendationOptions[0].savingsOpportunity.estimatedMonthlySavings.value}' --output table

aws --region "$region" compute-optimizer get-lambda-function-recommendations \
  --query 'lambdaFunctionRecommendations[].{Function:functionName,CurrentMem:currentMemorySize,RecMem:memorySizeRecommendationOptions[0].memorySize,Savings:memorySizeRecommendationOptions[0].savingsOpportunity.estimatedMonthlySavings.value}' --output table

aws --region "$region" compute-optimizer get-ecs-service-recommendations \
  --query 'ecsServiceRecommendations[].{Service:serviceArn,Finding:finding,CurCPU:currentServiceConfiguration.cpu,CurMem:currentServiceConfiguration.memory,RecCPU:serviceRecommendationOptions[0].cpu,RecMem:serviceRecommendationOptions[0].memory,Savings:serviceRecommendationOptions[0].savingsOpportunity.estimatedMonthlySavings.value}' --output table

aws --region "$region" compute-optimizer get-rds-database-recommendations \
  --query 'rdsDBRecommendations[].{DB:resourceArn,Engine:engine,Idle:idle,Finding:instanceFinding,Storage:storageFinding,Reasons:instanceFindingReasonCodes,Current:currentDBInstanceClass,Rec:instanceRecommendationOptions[0].dbInstanceClass,Risk:instanceRecommendationOptions[0].performanceRisk,Savings:instanceRecommendationOptions[0].savingsOpportunityAfterDiscounts.estimatedMonthlySavings.value}' --output table
```

`cpuVendorArchitectures` is EC2 only; it is not valid on the ECS, RDS, or Lambda APIs.

**Performance risk uses two scales, split by field, not by service.** `performanceRisk` on a recommendation option is a number, 0 to 4 where higher is riskier, on EC2 and RDS alike; the SDKs type it as a double (verified against the Compute Optimizer API reference, September 2026). The string scale `VeryLow`/`Low`/`Medium`/`High` lives in the current-state fields, `currentPerformanceRisk` on EC2 and `currentInstancePerformanceRisk` on RDS. Do not merge the scales into one report column, and never soften the value.

Three RDS fields change the recommendation rather than the number. `idle` is a `True`/`False` string marking a database nobody uses, which is a stop-or-delete conversation, not a resize. `storageFinding` is graded separately from `instanceFinding`, so a correctly sized instance can still have over-provisioned storage, with the saving in `storageRecommendationOptions`. `instanceFindingReasonCodes` containing `NewGenerationDBInstanceClassAvailable` or `NewEngineVersionAvailable` is a modernization finding for 5.2. Do not rely on those reason codes to surface Extended Support charges: instances paying Extended Support can be reported `Optimized` with empty reason codes, so an `Optimized` RDS fleet can still carry the largest RDS finding. The 4.6 usage-type check is the only detector.

### 5.2 Instance generation and Graviton

Per region:

```bash
aws --region "$region" ec2 describe-instances --filters "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceType' --output text | tr '\t' '\n' | sort | uniq -c | sort -rn
```

Group by family and generation, flag older generations, identify Graviton candidates. Verify current generation names and their regional availability with `aws-knowledge` (`get_regional_availability`) rather than any hardcoded list.

Graviton needs an arm64 build, so flag it as a code-change dependency, not a configuration change. Managed services such as RDS, ElastiCache, and OpenSearch are the easy wins because AWS handles the architecture.

### 5.3 Non-production scheduling

**A tag nominates; only a measured usage profile qualifies.** The environment separation from 1.5 (account, tag, or naming convention) selects candidates and nothing more. An instance tagged `Environment=dev` can hold steady CPU and tens of MB of hourly network output through 02:00 to 06:00: provably working at 3am, and a tag-only rule would schedule it off. For startups without mature tagging, which 7.1 establishes as the norm, a tag is the weakest available signal. If the user could not describe the environment separation at all, then per Rule 7 everything is production, this section produces nothing, and that is itself a governance finding.

Selection follows the 1.5 answer, not a hardcoded tag. The blocks below use `ENV_TAG_KEY` and `NONPROD_VALUES` from the preamble; set them from that answer before running anything here. If separation is by account, skip the tag filter and treat every running instance in the non-production accounts as a candidate. If it is by naming convention, select on the `Name` tag pattern instead. Steps 2 and 3 are identical in all three cases; only step 1's selection differs.

Step 1, select candidates:

```bash
aws --region "$region" ec2 describe-instances \
  --filters "Name=instance-state-name,Values=running" "Name=tag:$ENV_TAG_KEY,Values=$NONPROD_VALUES" \
  --query "Reservations[].Instances[].{ID:InstanceId,Type:InstanceType,Launch:LaunchTime,Env:Tags[?Key=='$ENV_TAG_KEY'].Value|[0]}" --output table
```

Step 2, profile each candidate by hour of day over 14 days before recommending anything. 336 hourly datapoints fit one call per metric:

```bash
for iid in $(aws --region "$region" ec2 describe-instances \
               --filters "Name=instance-state-name,Values=running" \
                         "Name=tag:$ENV_TAG_KEY,Values=$NONPROD_VALUES" \
               --query 'Reservations[].Instances[].InstanceId' --output text); do
  echo "=== $iid ==="
  aws --region "$region" cloudwatch get-metric-statistics --namespace AWS/EC2 \
    --metric-name CPUUtilization --dimensions "Name=InstanceId,Value=$iid" \
    --start-time "$TS_14D" --end-time "$TS_NOW" --period 3600 --statistics Average \
    --output json | jq -r '.Datapoints | group_by(.Timestamp[11:13]) | .[]
      | "\(.[0].Timestamp[11:13]):00 avgCPU=\((map(.Average)|add/length)*100|round/100)"' | sort
  aws --region "$region" cloudwatch get-metric-statistics --namespace AWS/EC2 \
    --metric-name NetworkOut --dimensions "Name=InstanceId,Value=$iid" \
    --start-time "$TS_14D" --end-time "$TS_NOW" --period 3600 --statistics Sum \
    --output json | jq -r '[.Datapoints[].Sum] | if length == 0 then "NetworkOut: no data"
      else "NetworkOut hourly: min=\((min/1048576)|floor)MB max=\((max/1048576)|floor)MB" end'
done
```

Step 3, decide from the profile, not the tag:

- **Quiet window present.** Off-hours CPU and network sit at a small fraction of business-hours levels. Recommend a schedule matching the measured quiet window, and state the window next to the number: a weekday 08:00 to 20:00 schedule runs 60 of 168 hours, roughly 64 percent off. This is the only case that produces a scheduling recommendation.
- **Flat working profile.** Hourly network minimum within the same order of magnitude as its maximum, or CPU that never drops, means the instance works around the clock, tag or no tag. Disqualify it and say why; do not schedule it.
- **Flat near-zero profile.** CPU under 1 percent every hour with trivial network is not a scheduling candidate, it is an idle candidate: route it to the Phase 4 idle findings with Rule 7 sign-off. This applies to untagged instances too; Rule 7 classifies them production for destructive action, not immune from being reported.

Also list running instances with no environment tag (the `ENV_TAG_KEY` key): production by Rule 7, and a tagging finding for 7.1.

Base scheduling savings on the measured window, never a generic percentage. Timestamps above are UTC; confirm the team's working timezone before reading a window as "night".

#### 5.3.1 Stateful services: databases and clusters

**Same evidence bar, different mechanics.** Steps 1 to 3 above are written for EC2 and cannot be skipped for a database just because the candidate came from somewhere else. In a serverless or container account the databases are often the *only* schedulable spend, so this is the common path, not the edge case.

Candidates arrive from two directions: a non-production classification per 1.5, and 4.6's middle ground, a database that failed the idle thresholds but sits far below its provisioned capacity. 4.6 has only two outcomes, `IDLE` or silence, so a lightly used database produces no finding there and must be profiled here instead.

Profile by hour of day at `--period 3600`, not the 86400 that 4.6 uses. A single daily `Maximum` is correct for an idle test and structurally cannot show a quiet window, which is the whole question here. Reuse 4.6's engine-to-namespace map; `AWS/RDS` against a DocumentDB instance returns `None` for every metric.

```bash
aws --region "$region" rds describe-db-instances \
  --query 'DBInstances[].[DBInstanceIdentifier,Engine,DBInstanceClass]' --output text |
while read -r db engine class; do
  case "$engine" in
    docdb*)   ns="AWS/DocDB" ;;
    neptune*) echo "MANUAL REVIEW | $db | Neptune metric names differ; profile in AWS/Neptune" ; continue ;;
    *)        ns="AWS/RDS" ;;
  esac
  echo "=== $db ($engine $class) ==="
  for m in DatabaseConnections CPUUtilization; do
    stat=Maximum   # both are gauges per the Conventions statistic rule
    aws --region "$region" cloudwatch get-metric-statistics --namespace "$ns" \
      --metric-name "$m" --dimensions "Name=DBInstanceIdentifier,Value=$db" \
      --start-time "$TS_14D" --end-time "$TS_NOW" --period 3600 --statistics "$stat" \
      --output json | jq -r --arg m "$m" '.Datapoints
        | if length == 0 then "\($m): NO DATA - cannot qualify a schedule"
          else (group_by(.Timestamp[11:13]) | .[]
                | "\($m) \(.[0].Timestamp[11:13]):00 max=\((map(.Maximum)|max)*100|round/100)") end' | sort
  done
done
```

Decide from the profile, with the same three branches as Step 3 and one addition:

- **Quiet window present.** Connections drop to zero, or to a lone monitoring poller, for a contiguous block of hours every day. Recommend a stop-start schedule matching that block and **state the window and the hours-per-week next to the dollar figure**. Savings are proportional to hours stopped, not a genre average.
- **Flat working profile.** Connections never reach zero and CPU never drops. Something holds the database open around the clock: an application pool, a health check, a cron job, or an RDS Proxy. Disqualify scheduling and say which. If the holder is itself a finding, as an idle proxy is, note that removing it is a prerequisite and re-profile afterwards rather than claiming both savings.
- **Flat near-zero profile.** Trivial activity in every hour is an idle candidate, not a scheduling candidate: route it to 4.6 with Rule 7 sign-off.
- **Serverless capacity floor.** Aurora Serverless v2 and similar bill a minimum capacity continuously, so the lever is the floor and auto-pause, not a stop schedule. Verify current auto-pause behaviour and the minimum-capacity semantics with `aws-knowledge` before quoting a number, and check the same persistent-connection holders, because auto-pause keys on activity.

Mechanical constraints to state in Appendix A, verified with `aws-knowledge` rather than assumed: RDS and DocumentDB clusters can be stopped only for a bounded number of days before AWS restarts them, so an off-hours schedule needs automation and a weekend gap may exceed the limit; a stopped instance still bills storage, backups, and snapshots; Multi-AZ, read replicas, and DR targets legitimately show low activity and must not be scheduled on that basis; and resume latency lands on the first caller.

No dollar figure in this subsection may be a generic percentage. Either it is derived from measured stopped hours against the instance's own billed rate from the 3.5 inventory, in which case tag it `MEDIUM`, or it is a modelled range with the assumed window stated, in which case tag it `LOW` per 8.1. A recommendation with no measured window and no stated assumption is not shippable.

---

<!-- markdownlint-enable -->
