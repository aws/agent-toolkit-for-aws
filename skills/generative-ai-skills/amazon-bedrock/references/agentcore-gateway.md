# AgentCore Gateway — Target Setup Procedure

## Overview

Deterministic procedure for creating an AgentCore Gateway target that converts
REST APIs into MCP tools agents can use. Gateway supports three authentication
types, each with a different setup workflow. The creation order is strict —
credentials MUST be created before the gateway target.

## Parameters

- **auth_type** (required): `api_key` | `lambda_iam` | `oauth`
- **openapi_schema_s3_uri** (required): S3 URI of the OpenAPI schema
- **api_key** (required if api_key auth): The API key value
- **lambda_arn** (required if lambda_iam auth): Lambda function ARN
- **oauth_config** (required if oauth auth): Token endpoint, client ID, scopes

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters (`auth_type`, `openapi_schema_s3_uri`, and auth-type-specific parameters) upfront in a single prompt
- You MUST confirm successful acquisition of all required parameters before proceeding to Step 1

## Steps

**General constraints:**

- You MUST present an overview of the steps before starting
- You MUST explain to the user what step is being executed and why before running each command
- You MUST respect the user's decision to abort at any point

### 0. Verify Dependencies

**Constraints:**

- You MUST verify the AWS CLI is available and configured before proceeding
- You MUST verify AWS CLI version ≥ 2.13.22 (required for AgentCore commands): `aws --version`
- You MUST inform the user about any missing tools and ask if they want to proceed

### 1. Upload OpenAPI Schema to S3

**Constraints:**

- You MUST upload the OpenAPI schema to S3 before creating the gateway target
- Schema MUST be valid OpenAPI 3.0 or 3.1
- You MUST include clear operation descriptions — Gateway uses these to generate MCP tool descriptions
- Upload the schema: `aws s3api put-object --bucket <bucket> --key <key> --body <schema-file>`
- Refer to the latest AWS documentation on AgentCore Gateway OpenAPI schema requirements

### 2. Create Credential Provider (if API key or OAuth)

**Constraints:**

- You MUST create the credential provider BEFORE creating the gateway target — this ordering is mandatory
- Creating a target without credentials results in a "credential provider not found" error

**For API key authentication:**

- You MUST NOT pass the API key as a literal value on the command line — shell history exposes it
- You MUST ask the user to set the key as an environment variable: `export API_KEY=<their-key>`
- Create the credential provider: `aws bedrock-agentcore-control create-api-key-credential-provider --name <name> --api-key "$API_KEY"` — the service encrypts and stores the key in Secrets Manager internally (response includes `apiKeySecretArn`). Do NOT manually create a Secrets Manager secret; the service manages this.
- For key rotation: `aws bedrock-agentcore-control update-api-key-credential-provider --name <name> --api-key "$NEW_API_KEY"` — do NOT call `secretsmanager rotate-secret` directly on the service-managed secret

**For OAuth authentication:**

- The client secret is passed via the `create-oauth2-credential-provider` API call — the service encrypts and stores it in Secrets Manager automatically (response includes `clientSecretArn`). Do NOT manually create a Secrets Manager secret.
- You MUST NOT hardcode client secrets in agent code or configuration
- Configure token endpoint, client ID, client secret, and scopes
- Create the OAuth2 credential provider: `aws bedrock-agentcore-control create-oauth2-credential-provider --name <name> --credential-provider-vendor <vendor> --oauth2-provider-config-input '...'`
- Refer to the latest AWS documentation on AgentCore Gateway OAuth configuration options

**For Lambda/IAM authentication:**

- No credential provider needed — skip to Step 3
- The Gateway uses IAM role-based authentication to invoke the Lambda
- The Lambda MUST have a resource-based policy allowing the Gateway service role to invoke it, with `aws:SourceAccount` and `aws:SourceArn` conditions to prevent confused deputy. Refer to the latest AWS documentation on AgentCore Gateway permissions for current policy patterns.

### 3. Create Gateway Target

**Constraints:**

- Create the target: `aws bedrock-agentcore-control create-gateway-target --gateway-identifier <gateway-id> --name <name> --target-configuration '...' --credential-provider-configurations '...'`
- You MUST link the OpenAPI schema S3 URI from Step 1
- If using API key or OAuth: You MUST link the credential provider ARN from Step 2
- If using Lambda: You MUST specify the Lambda ARN and configure IAM role with `lambda:InvokeFunction` scoped to the specific Lambda ARN — avoid `Resource: "*"`
- You MUST NOT create the target before the credential provider exists (for API key/OAuth)

### 4. Verify Target Status

**Constraints:**

- Poll target status: `aws bedrock-agentcore-control get-gateway-target --gateway-identifier <gateway-id> --target-id <target-id>`
- Wait for status `ACTIVE` before using the target
- If status is `FAILED`:
  - Check IAM permissions
  - Verify OpenAPI schema is valid
  - Verify credential provider exists and is accessible
  - Check CloudTrail for detailed error messages
- If status is stuck in `CREATING` for >10 minutes:
  - Contact AWS Support with the gateway-id and target-id for investigation
  - Refer to the latest AWS documentation or support channels for known issues

### 5. Test Connectivity

**Constraints:**

- You MUST test the gateway target with a sample request before using in production
- Verify the MCP tools generated from the OpenAPI schema match expectations
- You SHOULD report the list of generated MCP tools to the user

## Security Considerations

- **Encryption:** S3 encrypts objects at rest by default (SSE-S3). For sensitive schemas, use SSE-KMS with a customer managed key. Target endpoints MUST use HTTPS — Gateway rejects HTTP endpoints.
- **Least privilege:** Scope IAM roles to specific resource ARNs — the Gateway service role should only access the specific S3 bucket, Secrets Manager secret, and Lambda function needed. Avoid `Resource: "*"`.
- **Sensitive data in logs:** API keys and OAuth tokens may appear in CloudTrail logs. Enable CloudTrail log encryption with KMS. Do NOT log credential values in agent output.
- **Monitoring:** Enable CloudWatch alarms for gateway target errors (5xx rates, latency). Enable CloudTrail for audit logging of all `bedrock-agentcore-control` API calls.
- **TLS:** All target endpoints must use TLS 1.2+. Use ACM certificates for custom domains.
- Refer to the latest AWS documentation on Bedrock security best practices.
