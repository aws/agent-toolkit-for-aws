# Deployment Reference

Serverless-specific deployment patterns, resource types, and fast iteration tools.

## Contents

- [SAM resource types](#sam-resource-types)
- [SAM Globals section](#sam-globals-section)
- [CDK serverless constructs](#cdk-serverless-constructs)
- [Fast iteration](#fast-iteration)

---

## SAM resource types

SAM templates extend CloudFormation with `Transform: AWS::Serverless-2016-10-31`. Only `Transform` and `Resources` are required.

| Resource Type | Purpose |
|---|---|
| `AWS::Serverless::Function` | Lambda + IAM role + event source mappings |
| `AWS::Serverless::HttpApi` | HTTP API (API Gateway v2) — recommended |
| `AWS::Serverless::Api` | REST API (v1) — WAF, usage plans, request validation |
| `AWS::Serverless::SimpleTable` | DynamoDB with minimal config |
| `AWS::Serverless::LayerVersion` | Lambda layer |
| `AWS::Serverless::StateMachine` | Step Functions state machine |
| `AWS::Serverless::Connector` | Simplified permissions between resources |
| `AWS::Serverless::Application` | Nested serverless application (SAR or local) |
| `AWS::Serverless::GraphQLApi` | AppSync GraphQL API |
| `AWS::Serverless::WebSocketApi` | WebSocket API (API Gateway v2) |
| `AWS::Serverless::CapacityProvider` | Lambda Managed Instances on customer-owned EC2 |

---

## SAM Globals section

Eliminates duplication across functions/APIs. Supported types: `Function`, `Api`, `HttpApi`, `SimpleTable`, `StateMachine`, `CapacityProvider`.

**Override rules:**

| Type | Behavior |
|---|---|
| Primitives (string, number, boolean) | Resource value **replaces** global |
| Maps (dictionaries) | **Merged** — resource keys override matching global keys |
| Lists (arrays) | Global entries **prepended** to resource entries |

---

## CDK serverless constructs

Prefer L2 constructs — they provide sensible defaults and least-privilege IAM via `grant*` methods.

| Construct | Module | Use for |
|---|---|---|
| `NodejsFunction` | `aws-cdk-lib/aws-lambda-nodejs` | Node.js/TypeScript — bundles with esbuild automatically |
| `PythonFunction` | `@aws-cdk/aws-lambda-python-alpha` | Python — requires Docker for bundling |
| `HttpApi` | `aws-cdk-lib/aws-apigatewayv2` | HTTP API with CORS, JWT auth |
| `HttpLambdaIntegration` | `aws-cdk-lib/aws-apigatewayv2-integrations` | Connect Lambda to HttpApi |

---

## Fast iteration

Both tools are **development-only** — they bypass CloudFormation safety and introduce drift. Use `sam deploy` or CI/CD for production.

### SAM Accelerate

```bash
sam sync --watch --stack-name my-stack                            # Watch mode — auto-syncs on save
sam sync --code --watch --stack-name my-stack                     # Code-only (minimal sync time)
sam sync --code --resource-id MyFunction --watch --stack-name my-stack  # Single function
```

Code changes sync via service APIs in seconds. Infrastructure changes trigger CloudFormation (slower, automatic).

### CDK hotswap / watch

```bash
cdk deploy --hotswap           # Direct resource update, skips non-hotswappable
cdk deploy --hotswap-fallback  # Hotswap with CloudFormation fallback
cdk watch                      # Watch mode (hotswap + file watching)
```

Hotswap supports: Lambda code/config/versions/aliases, Step Functions definitions, ECS images, S3 deployments, CodeBuild projects, AppSync resolvers/functions/schemas.

### Comparison

| Feature | SAM Sync | CDK Hotswap |
|---|---|---|
| Watch mode | `sam sync --watch` | `cdk watch` |
| Code-only sync | `sam sync --code` | `cdk deploy --hotswap` |
| Fallback to full deploy | Automatic | `--hotswap-fallback` |
| Selective resource sync | `--resource-id` | Not supported |
| Code change speed | Seconds | Seconds |
| Production safe | **No** | **No** |
