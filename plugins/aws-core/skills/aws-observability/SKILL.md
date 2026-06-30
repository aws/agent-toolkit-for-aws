---
name: aws-observability
description: >-
  Builds, configures, debugs, and optimizes AWS observability with CloudWatch (Log Insights,
  Metrics, Alarms, Dashboards, EMF), X-Ray, CloudTrail, and ADOT (AWS Distro for OpenTelemetry),
  AND enables/onboards services to Application Signals using ADOT auto-instrumentation SDKs.
  Covers Log Insights queries, alarms (metric, composite, anomaly), dashboards, custom
  metrics/EMF, X-Ray tracing and sampling, ADOT collector config, CloudTrail auditing, and
  end-to-end Application Signals enablement via ADOT SDKs (CloudWatch Observability EKS add-on,
  CloudWatch Agent IAM, OTLP endpoints, ServiceEvents, Dynamic Instrumentation)
  on EC2, ECS, EKS, and Lambda in Python, Node.js, Java, and .NET.
  Applies to CloudWatch, alarms, dashboards, EMF, X-Ray, traces, CloudTrail, ADOT,
  monitoring, synthetics/canaries, OR enabling/onboarding/instrumenting
  a service for Application Signals using ADOT, ServiceEvents, auto-instrumentation,
  or making a service show up in Application Signals.
  Not for app logging or security threat detection.
version: 2
metadata:
  service: [cloudwatch, xray, cloudtrail, synthetics]
  task: [build, deploy, debug, optimize, configure, enable, onboard, instrument]
  persona: [developer, devops]
  workload: [observability]
---

# AWS Observability

## Overview

Domain expertise for AWS observability across metrics, logs, and traces, covering the full lifecycle: **enabling/onboarding** Application Signals on a service using ADOT (AWS Distro for OpenTelemetry) auto-instrumentation SDKs through **operating** it (CloudWatch alarms, dashboards, Log Insights, custom metrics, EMF, X-Ray trace analysis, CloudTrail auditing, ADOT collector config).

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) — enables running CLI commands, querying CloudWatch, and validating configurations directly. All guidance also works with standard AWS CLI access.

**Note:** Reference files contain specific runtime versions, quota values, and feature matrices that may change. When precision matters (e.g., deploying to production, choosing a runtime, or checking a quota), confirm values against current AWS documentation rather than relying solely on the values in these files.

## Routing

| User need | Action |
|-----------|--------|
| Enabling/onboarding a service to Application Signals (auto-instrumentation) | Read [application-signals-onboarding.md](references/application-signals-onboarding.md) |
| Propagating ServiceEvents git/deployment metadata through CI/CD | Read [application-signals-cicd-metadata.md](references/application-signals-cicd-metadata.md) |
| Per-platform/per-language enablement steps | Read the matching `references/appsignals-guides/<platform>-<language>.md` (e.g. [eks-python.md](references/appsignals-guides/eks-python.md)) |
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
| [application-signals-onboarding.md](references/application-signals-onboarding.md) | Enable Application Signals auto-instrumentation: EKS add-on, CloudWatch Agent IAM, OTLP endpoints, ServiceEvents env vars, Dynamic Instrumentation — two-tier scope by platform/language |
| [application-signals-cicd-metadata.md](references/application-signals-cicd-metadata.md) | ServiceEvents git & deployment metadata propagation through CI/CD (the 5 `OTEL_AWS_SERVICE_EVENTS_*` vars) |
| `references/appsignals-guides/` (e.g. [eks-python.md](references/appsignals-guides/eks-python.md)) | 16 per-platform × per-language enablement guides (EC2/ECS/EKS/Lambda × Python/Node.js/Java/.NET) |
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
