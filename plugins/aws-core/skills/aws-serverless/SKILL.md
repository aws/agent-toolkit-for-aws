---
name: aws-serverless
description: Builds, deploys, manages, debugs, configures, and optimizes serverless applications on AWS using Lambda, API Gateway, Step Functions, EventBridge, and SAM/CDK. Covers cold starts, CORS debugging, event source mappings, troubleshooting, concurrency, SnapStart, Powertools, function URLs, EventBridge Scheduler, Lambda layers, and production readiness. Triggers on mentions of Lambda, API Gateway, Step Functions, SAM templates, CDK serverless stacks, DynamoDB stream triggers, SQS event sources, cold starts, timeouts, 502/504 errors, throttling, concurrency, CORS, Powertools, or any event-driven architecture on AWS, even without the word "serverless." Does not apply to EC2, ECS/Fargate containers, or Amplify hosting.
version: 1
---

# AWS Serverless

Domain expertise for building serverless applications on AWS: Lambda, API Gateway, Step Functions, EventBridge, event source mappings, concurrency, cold starts, deployment, and troubleshooting.

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) — run CLI commands, query CloudWatch, validate configs directly. All guidance also works with standard AWS CLI access.

## Specialized skills — check these first

These cover capabilities and procedures the general references below do **not**. Several are specialized features or step-by-step tested procedures you would otherwise miss. Route to the matching skill before falling back to the references.

### Advanced Lambda compute (easy to overlook)

| Use this skill | When the workload involves |
|---|---|
| **aws-lambda-microvms** | Strong tenant isolation, sandboxed/untrusted code execution (AI agent code sandboxes, REPLs, notebooks, CI runners), long-lived sessions, suspend/resume with preserved state, port-listening servers (gRPC, WebSocket, custom TCP), Firecracker microVMs, snapshot-resumable compute, up to 8-hour lifetimes |
| **aws-lambda-durable-functions** | Durable execution, checkpoint-and-replay, long-running multi-step workflows written as plain code (TS/Python/Java), automatic state persistence, saga pattern in code, human-in-the-loop callbacks, executions up to 1 year, `context.step`/`context.wait`/`context.invoke`, `withDurableExecution`, `durable-execution-sdk` |
| **aws-lambda-managed-instances** | Lambda Managed Instances (LMI), capacity providers, EC2-backed Lambda, steady high-volume traffic (50M+ req/mo) wanting Savings Plans / Reserved Instance pricing, `PerExecutionEnvironmentMaxConcurrency`, `CapacityProviderConfig`, multi-concurrent execution environments |

### Step-by-step task procedures (tested CLI SOPs)

| Use this skill | For the task |
|---|---|
| **connecting-lambda-to-api-gateway** | Wire an existing Lambda to a new REST/HTTP API: proxy integration, permissions, CORS, throttling, access logging, deployment |
| **connecting-lambda-to-dynamodb** | Connect Lambda to DynamoDB: IAM execution role, read/write permissions, stream event source mapping |
| **creating-api-gateway-stage** | Create an API Gateway stage with CloudWatch logging, X-Ray tracing, throttling, WAF association, and authorization |
| **deploying-custom-domain-rest-api** | Deploy a Regional REST API with custom domain: ACM cert, Lambda backend, request authorizer, base path mapping, Route 53 DNS |
| **debugging-lambda-timeouts** | Systematically diagnose a timing-out Lambda: config, CloudWatch logs/metrics, VPC, cold starts, memory, downstream calls |
| **processing-s3-uploads-with-step-functions** | Deploy an event-driven workflow: S3 upload → EventBridge → Step Functions → Lambda (small files) or Fargate (large files), with VPC/ECR/ECS/IAM |

## Routing (general references in this skill)

| User need | Read |
|-----------|------|
| Building a new serverless app — pattern selection | [architecture.md](references/architecture.md) |
| Lambda config, cold starts, SnapStart, memory, VPC, layers, Function URLs | [lambda.md](references/lambda.md) |
| Concurrency (reserved, provisioned, ESM controls) | [concurrency.md](references/concurrency.md) |
| Event sources (SQS, DynamoDB Streams, SNS, Kinesis), filtering, batch failures | [event-sources.md](references/event-sources.md) |
| Step Functions, EventBridge rules/pipes/scheduler | [orchestration.md](references/orchestration.md) |
| API Gateway quotas, authorizers, WebSocket | [api-gateway.md](references/api-gateway.md) |
| SAM/CDK resource types and fast iteration | [deployment.md](references/deployment.md) |
| Production readiness, observability, anti-patterns | [production.md](references/production.md) |
| Debugging an error (exact string → cause → fix) | [troubleshooting.md](references/troubleshooting.md) |
| Powertools handler template | [powertools-handler.py](assets/powertools-handler.py) |

**Note:** Reference files contain specific runtime versions, quotas, and feature matrices that change. When precision matters (production, runtime choice, quotas), confirm against current AWS documentation. The references focus on values and gotchas that are easy to get wrong — not on basics.
