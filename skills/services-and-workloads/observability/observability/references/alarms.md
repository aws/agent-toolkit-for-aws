# CloudWatch Alarms

Configure and manage CloudWatch alarms including metric, composite, and anomaly detection types with evaluation mechanics and recommended defaults.

## Contents
- [Alarm types](#alarm-types)
- [Missing data treatment](#missing-data-treatment)
- [Evaluation mechanics](#evaluation-mechanics)
- [Composite alarms](#composite-alarms)
- [Anomaly detection](#anomaly-detection)
- [Recommended defaults](#recommended-defaults)
- [Common mistakes](#common-mistakes)
- [CDK patterns](#cdk-patterns)

---

## Alarm types

### Metric Alarm
Watches a single metric or metric math expression.

- **States**: OK, ALARM, INSUFFICIENT_DATA
- **Actions**: SNS, EC2 (stop/terminate/reboot/recover), Auto Scaling, Lambda, SSM OpsItems, SSM Incident Manager, CloudWatch Investigations
- **M-of-N evaluation**: `DatapointsToAlarm` (M) out of `EvaluationPeriods` (N)
- **Rate limit**: PutMetricAlarm = 3 TPS (adjustable)

### Composite Alarm
Combines states of other alarms with Boolean logic.

- **Rule operators**: `AND`, `OR`, `NOT`, `AT_LEAST(M, STATE, (alarms...))`
- `AT_LEAST` supports percentages: `AT_LEAST(50%, ALARM, (a1, a2, a3))`
- **Actions**: SNS, Lambda, SSM — **cannot** perform EC2 or Auto Scaling actions
- **Limits**: max 100 underlying alarms per composite, 150 composites per underlying, 500 rule elements
- Composite and all underlying alarms must be in the **same account and Region**
- **Action suppression**: `ActionsSuppressor` alarm can suppress composite alarm actions during known events (deployments, maintenance)

### PromQL Alarm (OpenTelemetry metrics)
Monitors OTel metrics using PromQL instant queries with duration-based pending/recovery periods. Use for metrics sent via OTLP (150 labels, 30-day retention).

---

## Missing data treatment

Four options — the most misunderstood CloudWatch feature.

| Value | Behavior | Use when |
|-------|----------|----------|
| `missing` (DEFAULT) | All missing → INSUFFICIENT_DATA | EC2 stop/terminate/reboot actions |
| `notBreaching` | Missing = within threshold | Error-count metrics (absence = no errors) |
| `breaching` | Missing = violating threshold | Heartbeat/health-check metrics |
| `ignore` | Maintain current state | DynamoDB metrics (service overrides default to `ignore`) |

**Note**: The CloudWatch console defaults DynamoDB alarms to `ignore` instead of the usual `missing`. The API stores whatever you specify.

### Premature alarm transitions

With `treatMissingData=missing`, the pattern M, M, B, M, M can trigger ALARM even with only 1 breaching datapoint. CloudWatch goes to ALARM when the oldest available breaching datapoint is at least as old as `datapointsToAlarm` and all more recent points are breaching or missing.

**Fix**: For non-sparse metrics, explicitly set `notBreaching` or `breaching` — don't rely on the default.

---

## Evaluation mechanics

### Three core settings
1. **Period** — seconds per data point aggregation (valid: 10, 20, 30, or any multiple of 60)
2. **Evaluation Periods** (N) — number of most recent periods to evaluate
3. **Datapoints to Alarm** (M) — how many of N must breach

### Evaluation frequency
- Period ≥ 1 min → evaluated **every minute**
- Period = 10s/20s/30s → evaluated **every 10 seconds**
- If `EvaluationPeriods × Period > 1 day` → evaluated **once per hour**

### Evaluation Range

CloudWatch fetches more data points than the configured Evaluation Periods — the actual lookback window is wider than expected.

**Example**: Alarm with 1-day period, 1 evaluation period, `treatMissingData=breaching`:
- You expect it to fire after 1 day of no data
- CloudWatch actually looks back **~3 days** before firing
- Dead man switch alarms fire **later than expected** due to hourly evaluation

### Evaluation period quotas
- Period ≥ 1 hour → max evaluation window: **7 days**
- Period < 1 hour → max evaluation window: **1 day**

---

## Composite alarms

### When to use
- Reduce alert fatigue: only page when BOTH high CPU AND high error rate
- Service-level health: aggregate per-resource alarms into one service alarm
- Suppress during deployments: use `ActionsSuppressor` to mute during known events

### Rule expression syntax
```
ALARM("error-rate-alarm") AND ALARM("latency-alarm")
ALARM("error-rate-alarm") OR ALARM("throttle-alarm")
NOT ALARM("maintenance-window")
AT_LEAST(2, ALARM, (a1, a2, a3))
AT_LEAST(50%, ALARM, (a1, a2, a3, a4))
```

### Limitations
- **Cannot** perform EC2 actions (stop, terminate, reboot, recover)
- **Cannot** perform Auto Scaling actions
- Composite and all underlying alarms must be in the **same account and Region** (underlying alarms must be same account + Region; monitoring accounts via OAM can watch source account metrics)
- Cross-account observability monitoring account CAN watch source account alarms

---

## Anomaly detection

- Uses `ANOMALY_DETECTION_BAND` function as threshold
- Band width = anomaly detection threshold value (configurable; higher value = thicker band of expected values)
- Trains on up to 2 weeks of metric data (works with less, accuracy improves over time)
- **Cost**: Higher than a regular alarm — see [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/) for current anomaly detection alarm rates
- Rate limit: 1,000 ANOMALY_DETECTION_BAND usages in GetMetricData per second
- Use when: baselines are unknown, workloads are seasonal/variable

---

## Recommended defaults

| Parameter | Common mistake | Recommendation |
|-----------|---------------|----------------|
| `evaluationPeriods` | 1 | **3–5** |
| `datapointsToAlarm` | 1 | **2–3** (M-of-N) |
| `treatMissingData` | `missing` | **Explicitly choose** based on metric type |
| `period` | 300s (5 min) | **60s** (1 min) for faster detection |
| Error rate threshold | 1% | **5%** (then tune down with data) |
| Latency threshold | 1s | **P99 of baseline + 2×** (data-driven) |

**WARNING**: Never use `Average` for duration/latency alarms. Average hides tail latency — use `p99` or `p90`. A function averaging 100ms but with p99 at 5s has a serious problem that Average won't catch.

---

## Common mistakes

1. **M=N=1 with 1-minute periods** — Too sensitive. The most recent datapoint may not have full information. Use "1 out of 2" or "1 out of 3" minimum.

2. **Relying on default `missing` treatment** — Explicitly configure for your metric type. Error metrics should use `notBreaching`. Health checks should use `breaching`.

3. **Not understanding Evaluation Range** — Alarms look back further than configured. Dead man switches with multi-day periods are evaluated once per hour, causing significant delay.

4. **Metric math alarms for EC2 actions** — Alarms based on metric math expressions **cannot** perform EC2 actions (stop, terminate, reboot, recover). Use a simple metric alarm instead.

5. **High-resolution alarms without need** — 10-second evaluation costs more. Each metric in a math expression is billed separately.

6. **Using Average statistic for duration/latency alarms** — Average hides tail latency. A function averaging 100ms with p99 at 5s has a serious problem Average won't catch. Always use `p99` or `p90` via `--extended-statistic p99`.

7. **Ignoring DynamoDB's default override** — DynamoDB alarms default to `ignore` for missing data, not the global `missing`.

8. **Alarms on INSUFFICIENT_DATA state** — Alarms invoke actions only on state **changes**, except Auto Scaling actions which continue invoking while in the new state.

---

## CDK patterns

### Error rate alarm (production pattern)

**Note**: Alarm on error **rate** (percentage via math expression), not raw error count. Raw counts trigger on a single error even during 10,000 successful invocations.

For CLI:
```bash
aws cloudwatch put-metric-alarm --alarm-name MyFunc-ErrorRate \
  --metrics '[
    {"Id":"errors","MetricStat":{"Metric":{"Namespace":"AWS/Lambda","MetricName":"Errors","Dimensions":[{"Name":"FunctionName","Value":"MyFunc"}]},"Period":60,"Stat":"Sum"},"ReturnData":false},
    {"Id":"invocations","MetricStat":{"Metric":{"Namespace":"AWS/Lambda","MetricName":"Invocations","Dimensions":[{"Name":"FunctionName","Value":"MyFunc"}]},"Period":60,"Stat":"Sum"},"ReturnData":false},
    {"Id":"error_rate","Expression":"IF(invocations > 0, errors * 100 / invocations, 0)","Label":"Error Rate %"}
  ]' \
  --threshold 5 --comparison-operator GreaterThanThreshold \
  --evaluation-periods 3 --datapoints-to-alarm 2 \
  --treat-missing-data notBreaching
```

For CDK:
```typescript
import { Alarm, ComparisonOperator, MathExpression, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';
import { Duration } from 'aws-cdk-lib';

const errorRateAlarm = new Alarm(this, 'ErrorRateAlarm', {
  metric: new MathExpression({
    expression: 'IF(invocations > 0, errors * 100 / invocations, 0)',
    usingMetrics: {
      errors: fn.metricErrors({ period: Duration.minutes(1) }),
      invocations: fn.metricInvocations({ period: Duration.minutes(1) }),
    },
  }),
  threshold: 5,
  evaluationPeriods: 3,
  datapointsToAlarm: 2,
  comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
  treatMissingData: TreatMissingData.NOT_BREACHING,
});
```

### Duration/latency alarm (use p99, never Average)
```typescript
const durationAlarm = new Alarm(this, 'DurationP99Alarm', {
  metric: fn.metricDuration({ statistic: 'p99', period: Duration.minutes(1) }),
  threshold: 3000, // 3 seconds
  evaluationPeriods: 3,
  datapointsToAlarm: 2,
  comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
  treatMissingData: TreatMissingData.NOT_BREACHING,
});
```

For CLI:
```bash
aws cloudwatch put-metric-alarm --alarm-name MyFunc-Duration-P99 \
  --namespace AWS/Lambda --metric-name Duration \
  --dimensions Name=FunctionName,Value=MyFunc \
  --extended-statistic p99 --period 60 \
  --evaluation-periods 3 --datapoints-to-alarm 2 \
  --threshold 3000 --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching
```

### Composite alarm
```typescript
import { CompositeAlarm, AlarmRule, AlarmState } from 'aws-cdk-lib/aws-cloudwatch';

const serviceHealthAlarm = new CompositeAlarm(this, 'ServiceHealth', {
  alarmRule: AlarmRule.anyOf(
    AlarmRule.fromAlarm(errorRateAlarm, AlarmState.ALARM),
    AlarmRule.fromAlarm(latencyAlarm, AlarmState.ALARM),
    AlarmRule.fromAlarm(throttleAlarm, AlarmState.ALARM),
  ),
});
```

### Anomaly detection alarm (CloudFormation)
```yaml
Resources:
  AnomalyDetector:
    Type: AWS::CloudWatch::AnomalyDetector
    Properties:
      MetricName: Invocations
      Namespace: AWS/Lambda
      Stat: Sum
  AnomalyAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      ComparisonOperator: LessThanLowerOrGreaterThanUpperThreshold
      # Anomaly detection band already models expected variability, so EvaluationPeriods: 1 is acceptable
      EvaluationPeriods: 1
      Metrics:
        - Expression: ANOMALY_DETECTION_BAND(m1, 2)
          Id: ad1
        - Id: m1
          MetricStat:
            Metric:
              MetricName: Invocations
              Namespace: AWS/Lambda
            Period: 86400
            Stat: Sum
      ThresholdMetricId: ad1
      TreatMissingData: breaching
```
