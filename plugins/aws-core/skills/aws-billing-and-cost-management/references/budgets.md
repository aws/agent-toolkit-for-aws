# AWS Budgets

> **Pricing note:** All prices shown are approximate as of early 2026 and may change. Always verify current pricing before reporting to users.

## Budget Types

| Type | Use Case |
|------|----------|
| COST | Track spend against dollar amount (default) |
| USAGE | Track usage quantity (e.g., EC2 hours) |
| RI_UTILIZATION | Alert when RI utilization drops below threshold |
| SAVINGS_PLANS_UTILIZATION | Alert when SP utilization drops |

Use `FORECASTED` notification type to catch runaway costs before they hit threshold.

## Create Budget with Alerts

```bash
aws budgets create-budget --region us-east-1 \
  --account-id 123456789012 \
  --budget '{"BudgetName":"Monthly-Total","BudgetLimit":{"Amount":"1000","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' \
  --notifications-with-subscribers '[
    {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"team@example.com"}]},
    {"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"SNS","Address":"arn:aws:sns:us-east-1:123456789012:budget-alerts"}]}
  ]'
```

Each threshold is a separate entry in `NotificationsWithSubscribers`. Do NOT put multiple thresholds in one notification object.

## Tag-Based Budget

Use `CostFilters` with `TagKeyValue` key and `tag-key$tag-value` format:

```json
"CostFilters": {"TagKeyValue": ["user:Environment$production"]}
```

## Budget Actions

Automatically apply IAM deny policies or SCPs when threshold is breached. Use for hard spending limits. Budget Actions cannot directly stop EC2 instances — use SNS → Lambda for custom actions.

## Gotchas

- **Budgets API requires `us-east-1` region** for global billing data
- Monitoring-only budgets (no actions) are free — unlimited
- First 2 action-enabled budgets are free; additional action-enabled budgets cost $0.10/day each
- Budget Reports cost $0.01 per report delivered
- Budget alerts evaluate once per day — up to 24-hour delay, not real-time
- `FORECASTED` alerts use ML-based forecasting — useful for catching runaway costs early
- Budget Actions are powerful but dangerous — test in non-prod first
- RI/SP utilization budgets default to 100% — set to 80% for practical alerting
