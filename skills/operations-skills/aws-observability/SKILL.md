---
name: aws-observability
description: Builds, configures, debugs, and optimizes AWS observability using CloudWatch (Logs Insights, Metrics, Alarms, Dashboards, EMF), X-Ray, CloudTrail, and ADOT. Covers Log Insights query syntax (fields, filter, stats, parse, pattern, join, subqueries), alarm configuration (metric, composite, anomaly detection, missing data treatment), dashboard design, custom metrics (PutMetricData, EMF, metric filters), X-Ray tracing (ADOT, sampling rules, annotations vs metadata), ADOT collector config, and CloudTrail auditing. Use when the user mentions CloudWatch, Log Insights, alarms, INSUFFICIENT_DATA, dashboards, custom metrics, EMF, X-Ray, traces, sampling, CloudTrail, who deleted, ADOT, OpenTelemetry, observability, monitoring, synthetics, canaries, or troubleshooting alarm behavior. Do NOT use for application logging setup, container log drivers, or security threat detection.
version: 1
metadata:
  service: [cloudwatch, xray, cloudtrail, synthetics]
  task: [build, deploy, debug, optimize, configure]
  persona: [developer, devops]
  workload: [observability]
---

# AWS Observability

## Overview

Domain expertise for AWS observability across metrics, logs, and traces. Covers CloudWatch platform capabilities (alarms, dashboards, Log Insights, custom metrics, EMF), X-Ray trace analysis, CloudTrail operational auditing, and ADOT collector configuration.

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) — enables running CLI commands, querying CloudWatch, and validating configurations directly. All guidance also works with standard AWS CLI access.

**Note:** Reference files contain specific runtime versions, quota values, and feature matrices that may change. When precision matters (e.g., deploying to production, choosing a runtime, or checking a quota), confirm values against current AWS documentation rather than relying solely on the values in these files.

## Routing

| User need | Action |
|-----------|--------|
| Writing Log Insights queries | Read [log-insights.md](references/log-insights.md) |
| Configuring alarms (metric, composite, anomaly) | Read [alarms.md](references/alarms.md) |
| Publishing custom metrics or using EMF | Read [metrics.md](references/metrics.md) |
| Setting up X-Ray tracing or ADOT | Read [tracing.md](references/tracing.md) |
| Building dashboards | Read [dashboards.md](references/dashboards.md) |
| Debugging observability issues | Read [troubleshooting.md](references/troubleshooting.md) — starts with the 5 most common fixes |
| Debugging canary failures | Read [synthetics.md](references/synthetics.md) — see Common failures table |
| CloudTrail operational auditing | Read [cloudtrail.md](references/cloudtrail.md) |
| Setting up Lambda monitoring with CDK | Use [alarm-template.ts](assets/alarm-template.ts) as a starting point |
| Creating synthetic canaries | Read [synthetics.md](references/synthetics.md) |
| Configuring ADOT collector | Use [otel-config.yaml](assets/otel-config.yaml) as a starting point |
| Spans multiple areas | Read the most specific reference first, then consult others as needed |

## Files

| File | Content |
|------|---------|
| [alarms.md](references/alarms.md) | Metric, composite, anomaly detection alarms — configuration, constraints, recommended defaults |
| [log-insights.md](references/log-insights.md) | Complete query syntax, commands, functions, known issues, reusable query library |
| [metrics.md](references/metrics.md) | Custom metrics, EMF spec, metric filters, high-resolution, retention |
| [tracing.md](references/tracing.md) | X-Ray → ADOT migration, sampling rules, annotations vs metadata, collector config |
| [dashboards.md](references/dashboards.md) | Widget types, cross-account/region, dynamic labels, sharing |
| [troubleshooting.md](references/troubleshooting.md) | Error → cause → fix for all observability services |
| [cloudtrail.md](references/cloudtrail.md) | Operational auditing, event types, S3+Athena queries |
| [synthetics.md](references/synthetics.md) | Canary runtime/blueprint constraints, VPC networking, common failures |
| [alarm-template.ts](assets/alarm-template.ts) | Best-practice CDK Lambda monitoring (alarms + dashboard) |
| [otel-config.yaml](assets/otel-config.yaml) | ADOT collector config for X-Ray traces + CloudWatch EMF metrics |
