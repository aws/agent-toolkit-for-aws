# AgentCore Credentials & Security

## Table of Contents

- Credential Provider Patterns
- OAuth Three-Layer Architecture
- Cross-Account Access
- Security Best Practices
- Agent Persistence Patterns

## Credential Provider Patterns

Three authentication types for AgentCore services. Getting the wrong type causes hard-to-debug 401/403 errors.

### API Key Authentication

> **Security consideration:** API keys are long-lived credentials. Prefer IAM authentication (ephemeral, auto-rotated) or OAuth when the target supports it. Use API keys only when the external target requires them (e.g., third-party APIs that only accept API key auth).

```
Setup sequence:
1. Create credential provider with the API key value (transmitted over TLS/SigV4; service encrypts and stores it in Secrets Manager internally)
2. Attach credential provider to Gateway target
```

**Constraints:**

- You MUST NOT pass the API key as a literal value on the command line — shell history exposes it
- You MUST ask the user to set the key as an environment variable: `export API_KEY=<their-key>`
- You MUST create the credential provider: `aws bedrock-agentcore-control create-api-key-credential-provider --name <name> --api-key "$API_KEY"`
- The service stores the key in Secrets Manager internally (response includes `apiKeySecretArn`)
- For rotation: update the API key through the service's control plane: `aws bedrock-agentcore-control update-api-key-credential-provider --name <name> --api-key "$NEW_API_KEY"` — the service re-encrypts and stores the new key internally. Do not call `secretsmanager rotate-secret` directly on the service-managed secret.
- You MUST NOT hardcode API keys in agent code or configuration
- You MUST NOT log or display the API key value in agent output
- You SHOULD enable CloudTrail logging to audit all credential provider API calls — these are control plane management events (`CreateApiKeyCredentialProvider`, `UpdateApiKeyCredentialProvider`, `DeleteApiKeyCredentialProvider`) logged under `eventSource: bedrock-agentcore.amazonaws.com`
- Refer to [AWS security best practices for AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security.html)

### OAuth Authentication

**Constraints:**

- The client secret is passed via the `create-oauth2-credential-provider` API call (the service encrypts and stores it in Secrets Manager automatically — response includes `clientSecretArn`)
- You MUST NOT hardcode client secrets in agent code or configuration
- You MUST NOT log or display client secret values in agent output
- Configure: token endpoint URL, client ID, scopes, grant type
- Create the OAuth2 credential provider: `aws bedrock-agentcore-control create-oauth2-credential-provider --name <name> --credential-provider-vendor <vendor> --oauth2-provider-config-input '...'`
- Refer to the latest AWS documentation on AgentCore OAuth configuration for current supported grant types and vendor options

### IAM Authentication

For Lambda targets and cross-service communication:

- Service roles for AgentCore services
- Cross-service permissions: Runtime → Gateway → external API
- Resource-based policies for cross-account access
- No credential provider needed — IAM handles authentication

## OAuth Three-Layer Architecture

AgentCore has three distinct OAuth layers — agents confuse these:

| Layer | Direction | Purpose |
|-------|-----------|---------|
| **Inbound JWT** | Caller → AgentCore | Validate tokens from callers (Cognito, external IdPs) |
| **Outbound Credential Provider** | Agent → External API | Agent authenticating to external APIs via Gateway |
| **Gateway OAuth** | Gateway → Upstream MCP | Gateway authenticating to upstream MCP servers |

Each layer is configured independently. Getting the wrong layer causes auth failures that look identical (401/403) but have different root causes.

**Supported IdPs for inbound JWT**: Cognito, Okta, Auth0, Azure AD, custom OIDC.

Refer to the latest AWS documentation on AgentCore OAuth architecture for current configuration steps and CDK examples.

## Cross-Account Access

Cross-account Bedrock access requires IAM trust policies on both sides.

**Pattern:**

1. **Calling account**: IAM role with `bedrock:InvokeModel` permission and `sts:AssumeRole` to the target account's role
2. **Target account**: IAM role with trust policy allowing the calling account's principal, plus `bedrock:InvokeModel` permission

**Trust policy pattern (target account role):**

```json
{
  "Effect": "Allow",
  "Principal": {"AWS": "arn:aws:iam::<calling-account-id>:role/<role-name>"},
  "Action": "sts:AssumeRole",
  "Condition": {
    "StringEquals": {
      "sts:ExternalId": "<agreed-external-id>"
    }
  }
}
```

Include `sts:ExternalId` for confused deputy protection. For service-to-service access, use `aws:SourceArn` and `aws:SourceAccount` conditions instead.

**Common failure**: `AccessDeniedException` when calling Bedrock from a different account — verify:

- Trust policy includes the calling account's principal ARN (not just account ID)
- The assumed role has `bedrock:InvokeModel` permission in the target account
- Model access is enabled in the target account's region

Refer to the latest AWS documentation on Bedrock cross-account access for current IAM policy patterns and any service-specific conditions.

## Security Best Practices

| Practice | How |
|----------|-----|
| Resource-based policies | Restrict access to specific principals, accounts, VPCs |
| VPC endpoints | Private AgentCore access without internet traversal |
| IP restrictions | Limit access by source IP range |
| Encryption | Data encrypted at rest and in transit by default |
| Audit logging | Enable CloudTrail for all AgentCore API calls |
| Least privilege | Grant only required permissions per service role |

## Agent Persistence Patterns

Deploying framework-specific agents on AgentCore Runtime:

| Framework | Key Configuration |
|-----------|------------------|
| **Strands Agents** | S3 for file storage, session state via Memory service |
| **LangChain/LangGraph** | Standard Python deployment, state management via Memory |
| **Custom frameworks** | Implement the protocol contract (HTTP/MCP/A2A/AG-UI) |

Refer to the latest AWS documentation on AgentCore deployment for the relevant framework.

**Constraints:**

- All frameworks MUST meet the container contract: ARM64, health check, correct port
- See [container build procedure](agentcore-runtime-container-build.md) for the build workflow
- State persistence SHOULD use the Memory service rather than local filesystem (containers are ephemeral)
