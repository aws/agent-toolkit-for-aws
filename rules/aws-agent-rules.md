# AWS Guidance

- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- Before starting a task, check whether a relevant AWS skill is available.
  Load the skill with `retrieve_skill` and prefer its guidance over
  general knowledge.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

## Secret Safety

- MUST NOT call `secretsmanager get-secret-value` or
  `secretsmanager batch-get-secret-value` -- not via AWS CLI, AWS MCP
  Server, SDK, curl, or any other mechanism.
- MUST NOT access the Secrets Manager Agent daemon directly (localhost:2773
  or any loopback address variant).
- When a task requires a secret value (database password, API key, token),
  use a `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` dynamic
  reference with `asm-exec` instead. This resolves the secret at runtime
  without exposing it to you.
- Load the `aws-secrets-manager` skill for detailed syntax
  and usage patterns.
