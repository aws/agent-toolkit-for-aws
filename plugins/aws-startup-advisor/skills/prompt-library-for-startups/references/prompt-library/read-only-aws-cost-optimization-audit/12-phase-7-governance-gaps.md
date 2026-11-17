<!-- markdownlint-disable -->

## PHASE 7: GOVERNANCE GAPS

### 7.1 Tagging

**Cost allocation tags resolve only from the management account.** From a member account, `list-cost-allocation-tags` fails with "Linked account doesn't have access to cost allocation tags". When 1.1.2 recorded a member account, expect that failure: mark this section `SKIPPED (member account - requires payer)`, do not run the per-key loop below on the empty output, and record the recommendation as "re-run 7.1 from the management account". The near-miss key check below still works from a member account, because `ce get-tags` reads that account's own tag keys.

```bash
aws ce list-cost-allocation-tags --status Active \
  --query 'CostAllocationTags[].{Key:TagKey,Type:Type}' --output table
```

An empty result from the management account is the finding: no spend can be attributed. An error from a member account is a `SKIPPED`, never "no findings" (Rule 3); the two are different results. Read the `Type` column before concluding anything: `AWSGenerated` keys such as `aws:createdBy` are activated by a checkbox and attribute spend to a creator identity, not to a team or product. An account whose only active keys are `AWSGenerated` has cost allocation tags in name and nothing usable for chargeback, which is its own finding.

For each active `UserDefined` key, measure the untagged share:

```bash
aws ce list-cost-allocation-tags --status Active --output json \
  --query 'CostAllocationTags[?Type==`UserDefined`].TagKey' \
  | jq -r '.[]' | while IFS= read -r key; do
  echo "=== $key ==="
  aws ce get-cost-and-usage --time-period Start="$START_30D",End="$TODAY" \
    --granularity MONTHLY --metrics "UnblendedCost" --group-by Type=TAG,Key="$key"
  aws resourcegroupstaggingapi get-resources \
    --query "length(ResourceTagMappingList[?!not_null(Tags[?Key=='$key'])])"
done
```

The group with an empty value is untagged spend. Report it as a percentage of total, because that is the share of the bill nobody owns. Two caveats on the numbers. `tag:GetResources` does not cover every AWS service, so the untagged resource count is a systematic undercount; per Rule 3, label it `PARTIAL (tagging API service coverage)` rather than presenting it as exact. And tag activation is not retroactive: Cost Explorer attributes spend to a tag only from activation onward, so "activate CostCenter" fixes next month's attribution, not last month's.

**Near-miss keys.** `CostCenter`, `costcenter`, and `cost-center` are three distinct keys; spend splits across them and each individually looks partially populated. Check for case and separator variants across all tag keys in use, active or not:

```bash
aws ce get-tags --time-period Start="$START_30D",End="$TODAY" \
  --query 'Tags[]' --output json | jq -r '.[]' \
  | awk '{norm=tolower($0); gsub(/[-_ ]/,"",norm); print norm "\t" $0}' \
  | sort | awk -F'\t' '$1==prev {print "NEAR-MISS KEYS: \"" prevkey "\" vs \"" $2 "\""} {prev=$1; prevkey=$2}'
```

Each near-miss family is one consolidation recommendation for Appendix A Tier 1: pick the canonical key, retag the variants, deactivate the losers. Per Rule 4, report tag keys and coverage percentages, not values.

### 7.2 Budgets and anomaly detection

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{Name:BudgetName,Type:BudgetType,Limit:BudgetLimit.Amount,Actual:CalculatedSpend.ActualSpend.Amount,Forecast:CalculatedSpend.ForecastedSpend.Amount}' --output table

# describe-budgets returns no notification data; thresholds and subscribers need their own calls.
aws budgets describe-budgets --account-id "$ACCOUNT_ID" --query 'Budgets[].BudgetName' --output json \
  | jq -r '.[]' | while read -r budget; do
  echo "=== $budget ==="
  aws budgets describe-notifications-for-budget --account-id "$ACCOUNT_ID" --budget-name "$budget" \
    --query 'Notifications[].{Type:NotificationType,Cmp:ComparisonOperator,Threshold:Threshold,Unit:ThresholdType}' --output json \
    | jq -c '.[]' | while read -r notif; do
    echo "$notif"
    aws budgets describe-subscribers-for-notification --account-id "$ACCOUNT_ID" --budget-name "$budget" \
      --notification "$(jq -nc --argjson n "$notif" \
          '{NotificationType:$n.Type,ComparisonOperator:$n.Cmp,Threshold:$n.Threshold,ThresholdType:$n.Unit}')" \
      --query 'Subscribers[].{Type:SubscriptionType,Address:Address}' --output table
  done
done

aws ce get-anomaly-monitors --query 'AnomalyMonitors[].{Name:MonitorName,Type:MonitorType}' --output table
aws ce get-anomaly-subscriptions --query 'AnomalySubscriptions[].{Name:SubscriptionName,Frequency:Frequency}' --output table
```

Subscriber addresses are email addresses; per Rule 4 report whether the target is a distribution list or an individual, not the address itself. Check at least one budget exists, thresholds sit below 100 percent so alerts arrive before the overrun, both actual and forecast alerts are configured, and notifications go to a distribution list rather than one person. A monitor with no subscription produces findings nobody sees, so check both. Use `get-anomaly-monitors` for configuration; the `cost_anomaly` MCP tool returns detected anomalies, not configuration.

Governance improvements enable future savings detection rather than reducing spend now, so keep them out of the headline total.

---

<!-- markdownlint-enable -->
