---
name: agents-connect
description: >
  Use when connecting an AgentCore Runtime or Harness to external APIs, MCP
  servers, Lambda tools, or OpenAPI services through Gateway, or controlling
  Gateway tools with Cedar policies. Covers Gateway targets, API keys, OAuth,
  outbound credentials, and policy engines. For inbound Runtime auth use
  agents-harden; for private VPC networking use agents-build.
allowed-tools: Read Grep Glob Bash
metadata:
  type: skill
  version: "1.0.0"
  author: aws-agentcore
  requires-cli: ">=1.0.0"
---

# connect

Connect an agent to external tools through AgentCore Gateway and choose outbound authentication for each target.

## When to use

- Connect an external MCP server, Lambda function, OpenAPI service, or another project Runtime.
- Add an API key or OAuth credential provider.
- Restrict tool calls using Cedar policies; load [references/policy.md](references/policy.md).

For an app calling your agent, use [agents-build integration](../agents-build/references/integrate.md). For a new MCP server project, use `agents-get-started`.

## Process

### 1. Check CLI and project

Run `agentcore --version`; require v1.0.0 or later. If the CLI is older, upgrade with `npm install -g @aws/agentcore@latest` and recheck. Read `agentcore/agentcore.json`. Version 2 is the v1 project format. If it is version 1, commit the project, review `agentcore migrate`, then apply the reviewed plan with `agentcore migrate --yes`.

Locate the project Gateway under `agentCoreGateways` and the Runtime or Harness that will call it. If there is no project, first create one using `agentcore create --name <ProjectName> --template empty`, or work in the user's existing project. Do not create a second project without preserving their current work.

### 2. Choose a target

| Service | v1 approach |
|---|---|
| External MCP server | `agentcore add gateway-target --gateway <gateway> --name <target> --endpoint https://.../mcp` |
| Runtime in this project | `agentcore add gateway-target --gateway <gateway> --name <target> --runtime <runtime>` |
| Lambda function by ARN | `--target-configuration file://<target>.json` with `targetType: "lambdaFunctionArn"` |
| OpenAPI service | `--target-configuration file://<target>.json` with `targetType: "openApiSchema"` |
| Curated Knowledge Base or web search connector | `agentcore add gateway-connector --gateway <gateway> --name <target> --connector <connector>`; add `--knowledge-base <id>` for a Knowledge Base |
| AWS SDK call using the Runtime's role | Call the AWS SDK directly from agent code |

The v1 shortcut uses `--endpoint` or `--runtime`. The v0 `--type`, `--lambda-arn`, `--schema`, and `--tool-schema-file` flags are gone. For full target configuration, include `name`, `targetType`, and the type's required fields in the JSON file. Do not combine `--target-configuration` with shortcut `--name` or `--outbound-auth` flags; authentication goes inside the JSON object in that form. Run `agentcore add gateway-target --help` and `agentcore build` when adapting a target schema.

### 3. Create an authenticated Gateway

Gateway's default authorizer is `NONE`. Set inbound auth deliberately when creating it:

```bash
agentcore add gateway --name MyGateway --authorizer-type AWS_IAM
```

For JWT, pass `--authorizer-type CUSTOM_JWT --authorizer-configuration file://authorizer.json`; use the project's `authorizerConfiguration` shape in the v1 schema. The gateway authorizer controls who can call the Gateway. It does not authenticate the Gateway to a target.

Enable `--enable-semantic-search` if the Gateway needs tool search. This must be configured on the Gateway; merely calling `x_amz_bedrock_agentcore_search` does not enable it.

### 4. Configure outbound authentication

**Public MCP server:**

```bash
agentcore add gateway-target \
  --gateway MyGateway --name WeatherTools \
  --endpoint https://mcp.example.com/mcp --outbound-auth none
```

**OAuth MCP server:** register the client credential, then reference it by name:

```bash
agentcore add credentials oauth \
  --name WeatherOAuth \
  --client-id <client-id> \
  --discovery-url https://auth.example.com/.well-known/openid-configuration \
  --scopes read write \
  --client-secret file://<local-secret-file>
agentcore add gateway-target \
  --gateway MyGateway --name WeatherTools \
  --endpoint https://mcp.example.com/mcp \
  --outbound-auth oauth --credential-name WeatherOAuth \
  --scope read --scope write
```

The CLI rejects inline `--client-secret` and `--api-key` values. Use a local secret file, `-` for stdin, or the matching `--client-secret-reference` / `--api-key-secret-reference` with an existing Secrets Manager secret. Keep local secret files out of git. Check `agentcore add credentials oauth --help` for vendored OAuth configuration.

**API key provider:**

```bash
agentcore add credentials api-key --name MyAPIKey --api-key file://<local-secret-file>
```

For a complete OpenAPI target, put the provider name in `outboundAuth` in its JSON configuration:

```json
{
  "name": "MyAPI",
  "targetType": "openApiSchema",
  "schemaSource": {"inline": {"path": "specs/api.json"}},
  "outboundAuth": {"type": "API_KEY", "credentialName": "MyAPIKey"}
}
```

```bash
agentcore add gateway-target --gateway MyGateway --target-configuration file://my-api-target.json
```

For an existing Lambda, use the complete configuration form:

```json
{
  "name": "MyTools",
  "targetType": "lambdaFunctionArn",
  "lambdaFunctionArn": {
    "lambdaArn": "arn:aws:lambda:us-east-1:123456789012:function:my-tools",
    "toolSchemaFile": "tools.json"
  }
}
```

Do not add `outboundAuth` to a `lambdaFunctionArn` target: the gateway role invokes Lambda through IAM. Scope that role to the intended function.

### 5. Build, deploy, and wire the agent

```bash
agentcore build
agentcore deploy --region <region>
agentcore status --json
```

On the first deploy, the CLI creates the default target using the effective AWS account and region; subsequent deploys can select `--target <name>`. Read the deployed Gateway URL from `agentcore status --json`. The deployed Runtime receives `AGENTCORE_GATEWAY_<UPPERCASE_NAME>_URL`; check the exact name in its generated README or environment. In local `agentcore dev`, this deployed URL is absent unless supplied explicitly. The agent framework still needs MCP client wiring to discover and call the Gateway's tools.

A Harness uses a Gateway tool entry in `app/<harness>/harness.yaml`, referencing the deployed Gateway ARN. Its config and a Runtime's MCP client code are different paths; use the one matching the project.

### 6. Verify and troubleshoot

- Inspect `agentcore status --json` and `agentcore gateway target list --gateway-id <deployed-gateway-id> --json` for deployed resources.
- For a Runtime error, use `agentcore logs runtime --name <runtime> --since 1h --level error`; for a Harness, use `agentcore logs harness --name <harness> --since 1h --level error`.
- Compare the target's `outboundAuth` type and credential name with its provider in `agentcore.json`. A Gateway URL alone does not tell you the outbound auth state.
- For Cedar authorization, load [references/policy.md](references/policy.md).

Direct API calls from agent code are suitable when the service has no Gateway target shape or the AWS SDK already uses the Runtime's IAM role. For API keys and OAuth in code, register providers with `agentcore add credentials api-key` or `oauth`, then use the AgentCore Identity SDK decorators. The deployed Runtime obtains providers through Identity; local development may need `agentcore/.env.local`. Do not place secrets in Runtime environment variables.
