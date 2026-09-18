# Discovery Procedure

Read this file before Steps 2 and 3. Use it to establish the workload's infrastructure and application architecture before evaluating framework questions.

## Step 2: Infrastructure Discovery

Analyze all infrastructure-as-code and deployment configurations in the codebase. If the review is description-only (no code or IaC available), skip the file examination in this step and build the infrastructure picture from the user-provided architecture description instead.

When code or IaC is available, you MUST examine:

- CDK projects in any supported language (detect `cdk.json`, CDK construct imports, or `aws-cdk-lib` dependencies)
- CloudFormation templates (YAML, JSON)
- Terraform configurations (.tf files)
- SAM/Serverless Framework templates
- CI/CD pipeline definitions (CodePipeline, GitHub Actions, etc.)
- Monitoring configurations (CloudWatch alarms, dashboards)
- Deployment configurations (CodeDeploy, ECS deployment settings)

For each infrastructure component, document:

- Resource type, logical name, and configuration
- File path and line numbers where defined
- Security-relevant configs (IAM, encryption, network)
- Resilience configs (multi-AZ, backups, scaling)
- Cost-relevant configs (instance types, capacity mode)

**SECURITY**: If discovery finds a hardcoded secret, credential, IAM access key, third-party API key, password, or connection string, never reproduce its value in the conversation, diagram, evidence, or report. Cite only the file path and line number, identify the secret type, and redact the value. For an IAM access key, recommend migration to IAM roles with temporary credentials, such as instance profiles, ECS task roles, Lambda execution roles, or IAM Identity Center sessions. For third-party API keys, passwords, and connection strings, recommend AWS Secrets Manager or AWS Systems Manager Parameter Store using `SecureString`.

You MUST create an architecture diagram in PlantUML — from the discovered resources, or from the user-provided architecture description when no code/IaC is available — showing:

- All major components and their relationships
- Data flows and external dependencies
- Trust and network boundaries

## Step 3: Application Architecture Discovery

When application code is available, analyze it for architectural patterns (for a description-only review, derive these from the user-provided description where possible):

- Entry points (API handlers, event processors, scheduled tasks)
- Service communication patterns (sync/async, retries, timeouts, circuit breakers)
- Data access patterns (queries, caching, connection management)
- Error handling and resilience patterns
- Authentication/authorization logic
- Observability instrumentation (logging, tracing, metrics)

## Internal gate: discovery complete

Validate discovery internally before evaluation — on a non-interactive review, do NOT stop for the user:

- Infrastructure inventory built (or, for a description-only review, the architecture reconstructed from the user's description).
- Key application / architecture patterns identified.
- Scope recorded for the coverage audit (files/resources analyzed, or "description-only").

If all three hold, proceed to Step 4 (acquire the live corpus). Pause for the user ONLY when the user explicitly requested interactive checkpoints, or when a required scope decision genuinely cannot be inferred (e.g. an ambiguous review target) — in that case ask the specific question and wait. Otherwise continue without confirmation.
