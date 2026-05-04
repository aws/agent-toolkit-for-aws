# CloudWatch Dashboards

Widget types, cross-account/region patterns, dynamic labels, and recommended defaults.

## Contents
- [Widget types](#widget-types)
- [Cross-account and cross-region](#cross-account-and-cross-region)
- [Dynamic labels](#dynamic-labels)
- [Dashboard variables](#dashboard-variables)
- [Sharing constraints](#sharing-constraints)
- [Recommended defaults](#recommended-defaults)
- [CDK patterns](#cdk-patterns)

---

## Widget types

| Widget | Use case |
|--------|----------|
| **Line** | Time series trends (latency, request count) |
| **Stacked area** | Composition over time (error types breakdown) |
| **Number** | Single KPI value (current error rate) |
| **Bar** | Comparisons across categories |
| **Table** | Tabular metric data display |
| **Pie** | Proportional breakdown |
| **Gauge** | Current value against a range |
| **Explorer** | Dynamic resource group metrics (auto-discovers new resources) |
| **Logs table** | Log Insights query results inline |
| **Alarm status** | Alarm state visualization |
| **Markdown** | Free-form text, links, section headers |

---

## Cross-account and cross-region

### Prerequisites
- CloudWatch Observability Access Manager (OAM) configured
- Monitoring account + source account links established
- IAM roles for cross-account access

### Dashboard body JSON
Each widget supports `accountId` and `region` parameters:
```json
{
  "type": "metric",
  "properties": {
    "metrics": [["AWS/Lambda", "Errors", "FunctionName", "my-fn"]],
    "region": "us-west-2",
    "accountId": "123456789012"
  }
}
```

### Limitations
- Search expressions operate within the widget's configured region (set `region` per widget for cross-region search)
- Cross-account composite alarms are not supported. However, with OAM, metric alarms in a monitoring account can watch metrics from source accounts.
- Cross-account alarms do NOT support ANOMALY_DETECTION_BAND, INSIGHT_RULE, or SERVICE_QUOTA functions

---

## Dynamic labels

Use dynamic values in metric widget labels (common tokens shown; AWS supports 28+ tokens including time-based variants like `${MAX_TIME}`, `${LAST_TIME_RELATIVE}`, and property tokens like `${PROP('MetricName')}`, `${PROP('Region')}`):

| Token | Value |
|-------|-------|
| `${MAX}` | Maximum value in visible range |
| `${MIN}` | Minimum value |
| `${AVG}` | Average value |
| `${SUM}` | Sum |
| `${LAST}` | Most recent value |
| `${FIRST}` | First value |
| `${LABEL}` | Default metric label |
| `${PROP('Dim.Name')}` | Dimension value |
| `${DATAPOINT_COUNT}` | Number of data points |

Example: `"label": "${PROP('FunctionName')} p99=${MAX}ms"`

Max 6 dynamic values per label. `${LABEL}` can only be used once per label.

---

## Dashboard variables

Variables add dropdown/radio/text inputs that dynamically filter all widgets on a dashboard. Up to 25 variables per dashboard.

Two types:
- **Property variables**: Populate from CloudWatch dimension values (e.g., all `FunctionName` values in `AWS/Lambda`)
- **Pattern variables**: Free-text input matched against metric patterns

Variables are a top-level `variables` array in the dashboard body JSON, peer to `widgets`. They eliminate the need for per-function or per-instance dashboards.

Shared dashboard viewers cannot change variable values — the dashboard renders with the default value only.

---

## Sharing constraints

- Shared users **cannot see** composite alarm widgets, Logs Insights widgets, or custom widgets unless you add the corresponding permissions (`DescribeAlarms`, CloudWatch Logs query permissions, Lambda invoke) to the sharing IAM policy
- `cloudwatch:GetMetricData` and `ec2:DescribeTags` **cannot be scoped** — shared users can query all metrics and EC2 tags in the account
- Cognito resources are created in **us-east-1** regardless of dashboard region

---

## Best-practice defaults

| Setting | Default | Best practice |
|---------|----------|------------|
| `start` | `-PT3H` | **`-PT8H`** (covers a shift) |
| `periodOverride` | AUTO | **`INHERIT`** (let widgets control) |
| Layout width | varies | **24** for full-width, **12** for side-by-side |
| Alarm widgets | none | **Always include** alarm status row at top |

### Dashboard structure pattern
1. **Row 1**: Markdown header + alarm status widgets (24-wide)
2. **Row 2**: Key business metrics (Number widgets, 6-wide each)
3. **Row 3**: Request/error rate graphs (Line widgets, 12-wide)
4. **Row 4**: Latency percentiles (Line widget, 24-wide)
5. **Row 5**: Log Insights query results (Logs table, 24-wide)

### Sharing
- Share publicly or with specific email addresses via Amazon Cognito
- Shared dashboards accessible via URL without AWS console login
- Check the [CloudWatch pricing page](https://aws.amazon.com/cloudwatch/pricing/) for current dashboard costs

### API limits
- PutDashboard, GetDashboard, ListDashboards, DeleteDashboards: all 10 TPS (adjustable)

---

## CDK patterns

### Dashboard with alarm and graph widgets
```typescript
import { Dashboard, AlarmWidget, GraphWidget, TextWidget, PeriodOverride } from 'aws-cdk-lib/aws-cloudwatch';

const dashboard = new Dashboard(this, 'ServiceDashboard', {
  dashboardName: `${serviceName}-${stage}`,
  start: '-PT8H',
  periodOverride: PeriodOverride.INHERIT,
});

dashboard.addWidgets(
  new TextWidget({ width: 24, height: 1, markdown: '# Service Health' }),
  new AlarmWidget({ width: 12, height: 6, title: 'Error Rate', alarm: errorRateAlarm }),
  new AlarmWidget({ width: 12, height: 6, title: 'Latency P99', alarm: latencyAlarm }),
  new GraphWidget({
    width: 24, height: 6,
    title: 'Invocations & Errors',
    left: [fn.metricInvocations({ period: Duration.minutes(1) })],
    right: [fn.metricErrors({ period: Duration.minutes(1) })],
  }),
);
```

### Automatic dashboards
Pre-built per-service dashboards are available by default (EC2, Lambda, S3, etc.). No setup required. Use these as starting points, then customize.
