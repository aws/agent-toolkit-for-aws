---
name: aws-serverless
description: Builds, deploys, manages, debugs, configures, and optimizes serverless applications on AWS using Lambda, API Gateway, Step Functions, EventBridge, and SAM/CDK. Covers cold starts, CORS debugging, event source mappings, troubleshooting, concurrency, SnapStart, Powertools, function URLs, EventBridge Scheduler, Lambda layers, Durable Functions, durable execution, checkpoint-and-replay, and production readiness. Use when the user mentions Lambda, API Gateway, Step Functions, SAM templates, CDK serverless stacks, DynamoDB stream triggers, SQS event sources, cold starts, timeouts, 502/504 errors, throttling, concurrency, CORS, Powertools, Durable Functions, durable execution, checkpoint-and-replay, or any event-driven architecture on AWS, even if they don't say "serverless." Do NOT use for EC2, ECS/Fargate containers, or Amplify hosting.
version: 1
---

# AWS Serverless
## Overview

Domain expertise for building serverless applications on AWS. Covers Lambda configuration, API Gateway debugging, Step Functions orchestration, EventBridge patterns, event source mappings, concurrency tuning, cold start optimization, deployment with SAM/CDK, production readiness, and troubleshooting across all serverless services.

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) — enables running CLI commands, querying CloudWatch, and validating configurations directly. All guidance also works with standard AWS CLI access.

**Note:** Reference files contain specific runtime versions, quota values, and feature matrices that may change. When precision matters (e.g., deploying to production, choosing a runtime, or checking a quota), confirm values against current AWS documentation rather than relying solely on the values in these files.

## Routing

| User need | Action |
|-----------|--------|
| Building a new serverless app | Read [architecture.md](references/architecture.md) for pattern selection, then [deployment.md](references/deployment.md) for SAM/CDK templates |
| Debugging an error | Read [troubleshooting.md](references/troubleshooting.md) — starts with the 5 most common fixes |
| Optimizing performance or cost | Read [lambda.md](references/lambda.md) for cold starts and memory tuning, [production.md](references/production.md) for readiness checklist |
| Configuring event sources (SQS, DDB Streams, SNS) | Read [event-sources.md](references/event-sources.md) |
| Step Functions, EventBridge, or orchestration | Read [orchestration.md](references/orchestration.md) |
| Concurrency configuration | Read [concurrency.md](references/concurrency.md) |
| API Gateway setup | Read [api-gateway.md](references/api-gateway.md) |
| Common anti-patterns | Read the anti-patterns section in [production.md](references/production.md) |
| Starting with Powertools | Use [powertools-handler.py](assets/powertools-handler.py) as a template |
| Spans multiple areas | Read the most specific reference first, then consult others as needed |

## Files

| File | Content |
|------|---------|
| [lambda.md](references/lambda.md) | Runtime, memory/CPU, cold starts, SnapStart, layers, containers |
| [api-gateway.md](references/api-gateway.md) | REST vs HTTP API, stages, auth, throttling, mapping |
| [event-sources.md](references/event-sources.md) | SQS, DDB Streams, SNS, S3, Kinesis triggers |
| [orchestration.md](references/orchestration.md) | Step Functions, EventBridge rules/pipes/scheduler |
| [concurrency.md](references/concurrency.md) | Reserved vs provisioned, scaling, ESM concurrency |
| [architecture.md](references/architecture.md) | Patterns, reference architectures, service selection |
| [deployment.md](references/deployment.md) | SAM/CDK resource types, globals, fast iteration |
| [production.md](references/production.md) | Readiness checklist, observability, anti-patterns |
| [troubleshooting.md](references/troubleshooting.md) | Error → cause → fix for all serverless services |
