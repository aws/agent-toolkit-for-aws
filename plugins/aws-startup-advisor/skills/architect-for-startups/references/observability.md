# Observability — Startup Decision Guide

## Stage-Based Recommendation

### Pre-PMF (Seed / <$1M ARR)

- **CloudWatch only. No Datadog, no New Relic, no Grafana Cloud.** Third-party observability tools cost $15-50/host/month and grow linearly. At this stage, CloudWatch + Embedded Metric Format is sufficient and covered by AWS credits.
- **3 metrics, 3 alarms, 1 dashboard.** Error rate, p99 latency, and request count. That's it. You don't need 47 dashboards for 1 service.
- **Log retention: 7 days dev, 30 days prod.** The default "never expire" will silently accumulate $50-200/month in log storage within 6 months.
- **Skip X-Ray until you have 3+ services.** Tracing a monolith tells you nothing useful. Tracing across service boundaries is where it helps.

### Post-PMF / Growth ($1M-$10M ARR)

- Add X-Ray or OpenTelemetry when you have 3+ services and debugging cross-service issues takes >1 hour.
- Consider Datadog/New Relic ONLY if CloudWatch Logs Insights becomes too slow for your team's debugging workflow. The convenience costs 5-10x.
- Increase log retention to 90 days prod when you have compliance requirements.
- Add anomaly detection on request count and latency (needs 2 weeks of baseline data).

### Scale ($10M+ ARR)

- OpenTelemetry for vendor-neutral instrumentation.
- Centralized observability platform decision (CloudWatch vs third-party based on team size and budget).
- This is when the Datadog bill becomes justified ($50K+/year but saves engineering time at 20+ engineers).

## Cost Traps

| Trap                                  | Impact                                                                                                | Fix                                                                                                    |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Log retention: never expire (default) | $0.03/GB/month storage — grows forever. 100GB/month of logs = $36/year in year 1, $72 in year 2, etc. | Set retention policy on creation. 30 days prod.                                                        |
| Custom metrics via PutMetricData      | $0.30/metric/month + $0.01/1000 API calls                                                             | Use Embedded Metric Format in Lambda — creates metrics from logs at zero API cost                      |
| High-cardinality custom metrics       | Dimensions multiply: 100 users × 10 endpoints = 1000 metrics = $300/month                             | Use Logs Insights for high-cardinality analysis, reserve metrics for low-cardinality aggregates        |
| X-Ray 100% sampling in prod           | $5.00/million traces recorded + storage                                                               | Sample: 1/sec + 5% additional. For startups this is usually enough.                                    |
| Datadog before $5M ARR                | $15-50/host/month + $1.70/million log events. 10 containers + logs = $500-2000/month easily           | CloudWatch is included in AWS credits. Switch when team size (>10 engineers) justifies the UX premium. |
| CloudWatch Dashboards                 | $3/dashboard/month — sounds small, proliferates fast                                                  | 1 dashboard per service max. Use automatic dashboards for exploration.                                 |
| Contributor Insights                  | $0.02/rule/100 log events evaluated. High-volume logs = surprise bill                                 | Enable only on specific log groups for incident investigation, disable after                           |

## Counterintuitive Advice

- **Fewer alarms = faster response.** 3 well-chosen alarms that always require action beat 30 alarms that are "probably fine." Every alarm should have a runbook. If you can't write the runbook, delete the alarm.
- **Alarm on symptoms, not causes.** "Error rate >1%" tells you something is broken. "CPU >80%" tells you... maybe nothing is wrong. Users feel symptoms, not causes.
- **CloudWatch Logs Insights is underrated.** Startups reach for Elasticsearch/Datadog because they assume CloudWatch is limited. Logs Insights with structured JSON logging handles 95% of debugging queries for teams under 20 engineers.
- **Embedded Metric Format is the single most important observability feature for Lambda-based startups.** It turns log lines into metrics at zero additional cost. You get custom metrics for free.
- **Don't build a "golden dashboard" until you've been in production for 3 months.** You'll build the wrong dashboard on day 1 because you don't know what fails yet. Start with the 3 basics and add panels as you learn from incidents.

## Minimum Viable Observability

### Seed Stage Checklist

- [ ] Structured JSON logging (enables Logs Insights queries)
- [ ] Log retention set on all log groups (7d dev, 30d prod)
- [ ] 3 alarms: error rate, p99 latency, 5xx count (SNS → email/Slack)
- [ ] 1 dashboard: request count, error rate, latency p99
- [ ] Lambda: use Embedded Metric Format for custom metrics (free)
- [ ] CloudTrail enabled (default trail — free for management events)

### Post-PMF Additions

- [ ] X-Ray sampling on API Gateway + Lambda (1/sec + 5%)
- [ ] Anomaly detection on request count (catches traffic drops = outage)
- [ ] DLQ monitoring alarms (ApproximateNumberOfMessagesVisible > 0)
- [ ] Composite alarm for service health (error rate AND latency breach)
- [ ] Log retention 90 days in prod

## When to Graduate

| Trigger                                                  | Action                                                              |
| -------------------------------------------------------- | ------------------------------------------------------------------- |
| First customer-facing outage you can't diagnose in 30min | Add X-Ray tracing                                                   |
| Debugging takes >1hr regularly                           | Increase log retention, add structured fields                       |
| 3+ services with cross-service calls                     | Distributed tracing (X-Ray or OTEL)                                 |
| 10+ engineers needing observability                      | Evaluate Datadog/New Relic (UX justifies cost)                      |
| SOC2 audit                                               | 90-day log retention, CloudTrail in all accounts                    |
| Monthly observability bill >$500 on CloudWatch           | Audit: log retention, custom metrics cardinality, unused dashboards |

## Credits Consideration

CloudWatch costs (logs, metrics, dashboards, X-Ray) are covered by AWS Activate credits. While you have credits:

- Don't optimize log retention aggressively — keep 90 days everywhere for debugging convenience
- Use X-Ray at higher sampling rates to build intuition about your system
- Create dashboards freely for learning

Set a calendar reminder 6 months before credits expire to implement cost-optimized retention policies.
