# Create a Bedrock Agent with Action Groups

## Table of Contents

- Overview
- Parameters
- Steps: Validate Prerequisites, Create Agent, Add Action Group, Associate Knowledge Base, Prepare Agent, Create Agent Alias, Test Agent
- Multi-Agent Orchestration
- Session Management
- Security Considerations

## Overview

Deterministic procedure for creating a Bedrock Agent with action groups,
optional Knowledge Base association, and deployment. This procedure is invoked
from the bedrock skill when a user wants to create an AI agent that can
take actions via Lambda functions or return control to the calling application.

## Parameters

- **agent_name** (required): Name for the agent
- **model_id** (required): Foundation model or inference profile ID
- **instructions** (required): System prompt / agent instructions
- **action_group_type** (required): `openapi_schema` | `function_definition` | `return_of_control`
- **knowledge_base_id** (optional): KB to associate with the agent
- **lambda_arn** (optional): Lambda function ARN for action group execution

**Constraints for parameter acquisition:**

- You MUST verify required parameters (`agent_name`, `model_id`, `instructions`, `action_group_type`) are provided. If any are missing, ask for them upfront in a single prompt.
- For `instructions`: if not specified, suggest instructions based on the agent's stated purpose and ask the user to confirm before proceeding
- If all parameters are provided or resolved, proceed to Step 1 — do not ask the user to confirm what they already specified.
- You SHOULD ask about optional parameters (`knowledge_base_id`, `lambda_arn`) in the same prompt

## Steps

**General constraints:**

- You MUST present an overview of the steps before starting
- You MUST explain to the user what step is being executed and why before running each command
- You MUST respect the user's decision to abort at any point

### 1. Validate Prerequisites

**Constraints:**

- You MUST verify the AWS CLI is available and configured before proceeding
- You MUST inform the user about any missing tools and ask if they want to proceed
- You MUST verify model access is enabled for the specified model_id: `aws bedrock list-foundation-models --region <region>`
- You SHOULD NOT use hyphens in the agent name — prefer underscores or camelCase. While the API allows hyphens, some model-level tool name resolution may have issues with them
- You MUST verify the user has `bedrock:CreateAgent` permission
- You MUST inform the user about any missing prerequisites before proceeding
- When selecting a model for the agent, you MUST check whether the model has In-Region availability in your region — see [Regional Availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html). If the model does not have In-Region availability in your region, you MUST use an inference profile ID (e.g., `us.anthropic.claude-sonnet-4-6`) instead of the base model ID — using the base model ID will fail with `ValidationException`. Use `aws bedrock list-inference-profiles --region <region>` to find the correct inference profile ID. If the model has In-Region availability, the base model ID is sufficient. See [Supported inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)

### 2. Create Agent

**Constraints:**

- You MUST create the agent: `aws bedrock-agent create-agent --agent-name <name> --foundation-model``<model-id>``--instruction "<instructions>" --agent-resource-role-arn <role-arn>`
- You MUST specify:
  - `agentName`: the agent name (no hyphens)
  - `foundationModel`: If the model does not have In-Region availability in your region (see Step 1), use the inference profile ID (e.g., `us.anthropic.claude-sonnet-4-6`); otherwise use the base model ID
  - `instruction`: the system prompt that defines agent behavior
  - `agentResourceRoleArn`: IAM role with `bedrock:InvokeModel` permission (optional — Bedrock can auto-create a service role, but specifying your own is recommended for least-privilege control). If you create a custom role, the IAM policy Resource ARN MUST match the model ID format:
    - Inference profile ID → `arn:aws:bedrock:<region>:<account-id>:inference-profile/<profile-id>` — **account-id is REQUIRED** (not `::`)
    - Base model ID → `arn:aws:bedrock:<region>::foundation-model/<model-id>` — no account-id (uses `::`)
    - **When using a cross-region inference profile** (e.g., `us.` or `global.` prefix), the foundation model ARN MUST use wildcard region: `arn:aws:bedrock:*::foundation-model/``<model-id>``` — because the request may be routed to any region in the profile
    - Using the wrong ARN format causes `AccessDeniedException`. See [Bedrock IAM resource types](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrock.html#amazonbedrock-resources-for-iam-policies)
    - The IAM action MUST include both `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` — Bedrock Agents may use streaming, and `bedrock:InvokeModel` alone can cause `accessDeniedException` at invocation time (see [Test your agent](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-test.html))
    - For the full and latest set of required permissions for the agent service role (model invocation, S3 schema access, KB access, Lambda), refer to [Create a service role for Amazon Bedrock Agents](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-permissions.html)
    - For least-privilege IAM policies scoped to specific inference profiles, you MUST include both the inference profile ARN and the foundation model ARN. See [Prerequisites for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html) for the required two-statement IAM pattern.
- If you create a custom IAM role, you MUST allow time for IAM propagation before passing it to `create-agent`. If `create-agent` fails with an error indicating Bedrock cannot assume the role, retry with exponential backoff up to 3 attempts — IAM role creation is eventually consistent (see [IAM eventual consistency](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_general.html#troubleshoot_general_eventual-consistency))
- You SHOULD set `idleSessionTTLInSeconds` based on the use case (default 600s)
- You SHOULD encrypt agent resources with a customer-managed KMS key: add `--customer-encryption-key-arn <kms-key-arn>` to the create-agent command
- You MUST wait for agent status to be `NOT_PREPARED` before proceeding

### 3. Add Action Group

**Constraints:**

- You SHOULD NOT use hyphens in action group names — prefer underscores. You MUST NOT use double underscores (`__`) in action group or API names (documented restriction)
- You MUST create the action group: `aws bedrock-agent create-agent-action-group --agent-id <id> --agent-version DRAFT --action-group-name <name> ...`

**For OpenAPI schema type:**

- You MUST upload the OpenAPI schema to S3 first
- You MUST include clear operation descriptions — the agent uses descriptions to decide when to invoke the action group
- You MUST specify the Lambda function ARN for execution

**For function definition type:**

- You MUST include clear descriptions for each function AND each parameter
- Function descriptions that are too vague cause the agent to never trigger the action group
- You MUST specify parameter types and required/optional status

**For return of control type:**

- Set `actionGroupExecutor` to `RETURN_CONTROL`
- The agent returns control to the calling application instead of invoking Lambda
- Use for: human-in-the-loop, external API calls from client side, approval workflows

**Lambda integration (for OpenAPI and function types):**

- The Lambda function MUST have a resource-based policy allowing `bedrock.amazonaws.com` to invoke it, with confused deputy protection conditions:
  - `"Condition": {"StringEquals": {"aws:SourceAccount": "<account-id>"}, "ArnLike": {"aws:SourceArn": "arn:aws:bedrock:<region>:<account-id>:agent/<agent-id>"}}`
  - Without these conditions, any Bedrock agent in any account could invoke your Lambda
- The agent's IAM role MUST have `lambda:InvokeFunction` permission
- **IMPORTANT**: The Lambda input/output event structure differs by action group type. Do NOT mix them:
  - **Function definition type**: input uses `function` and `parameters`; response uses `functionResponse` with `responseBody`
  - **OpenAPI schema type**: input uses `apiPath`, `httpMethod`, `parameters`, and `requestBody`; response uses `apiPath`, `httpMethod`, `httpStatusCode`, and `responseBody`
- Refer to the [AWS documentation on Bedrock agent Lambda event schema](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html) for the current canonical structures — do NOT hardcode event shapes from memory
- All action group parameters arrive as strings in the Lambda event's `value` field. If a parameter represents an object or array, it will be a stringified JSON string — your Lambda handler must explicitly `JSON.parse()` / `json.loads()` these values and handle parse failures gracefully.
- Lambda handlers MUST treat all agent-provided parameters as untrusted input — the agent generates these from user queries and they may contain injection payloads or malformed data

### 4. Associate Knowledge Base (if applicable)

**Constraints:**

- You MUST associate the KB if specified: `aws bedrock-agent associate-agent-knowledge-base --agent-id <id> --agent-version DRAFT --knowledge-base-id <kb-id> --description "<description>"`
- You MUST provide a clear description of what the KB contains — the agent uses this to decide when to query the KB
- You MUST NOT skip `prepare-agent` after association (Step 5)

### 5. Prepare Agent — CRITICAL

**Constraints:**

- You MUST prepare the agent after ANY configuration change: `aws bedrock-agent prepare-agent --agent-id <id>`
  - Adding or modifying action groups
  - Changing instructions
  - Associating or disassociating a Knowledge Base
  - Changing the model
- You MUST NOT skip this step because the agent uses a stale configuration until prepared — this is the #1 cause of "agent not doing what I configured"
- You MUST wait for agent status to be `PREPARED` before proceeding
- You MUST poll status until `PREPARED`: `aws bedrock-agent get-agent --agent-id <id>`

### 6. Create Agent Alias

**Constraints:**

- You MUST create an alias: `aws bedrock-agent create-agent-alias --agent-id <id> --agent-alias-name <alias>`
- Aliases point to agent versions — use for blue/green deployment
- You SHOULD create a `live` or `prod` alias for production use
- You MUST NOT invoke the agent without an alias in production

### 7. Test Agent

**Constraints:**

- The `InvokeAgent` API is a streaming operation — the AWS CLI does not support it. You MUST use the SDK (boto3, JS SDK) to test the agent:

  ```python
  import boto3
  client = boto3.client('bedrock-agent-runtime')
  response = client.invoke_agent(
      agentId='<id>', agentAliasId='<alias-id>',
      sessionId='<session>', inputText='<query>'
  )
  for event in response['completion']:
      if 'chunk' in event:
          print(event['chunk']['bytes'].decode())
  ```

- You MUST pass a `sessionId` for conversation continuity across turns
- You MUST verify:
  - The agent responds to queries within its instruction scope
  - Action groups trigger correctly when expected
  - Knowledge Base queries return relevant results (if KB associated)
- If the agent doesn't behave as expected, You MUST first check if `prepare-agent` was run after the last config change (Step 5)
- You MUST report test results to the user

## Multi-Agent Orchestration

**WARNING**: Agents use a **built-in multi-agent collaboration mechanism**, NOT action groups for inter-agent communication. Supervisor agents that are instructed to "send messages" or "communicate with" sub-agents will hallucinate a non-existent `AgentCommunication::sendMessage` action group and get trapped in retry loops.

**Constraints:**

- You MUST NOT describe inter-agent communication as action groups in supervisor instructions
- You MUST configure multi-agent orchestration using the built-in supervisor/collaborator pattern:
  - Create collaborator agents with their own action groups and KBs
  - Create a supervisor agent that references collaborator agents
  - The supervisor delegates to collaborators through the built-in mechanism
- Refer to the latest AWS documentation on Bedrock multi-agent orchestration for current configuration steps
- Supervisor instructions MUST clearly describe each collaborator agent's capabilities so the supervisor routes correctly

## Session Management

- Pass `sessionId` in every `invoke-agent` call for conversation continuity
- Session attributes (key-value pairs) persist across turns within a session
- Prompt session attributes are available only for the current turn
- Sessions expire after `idleSessionTTLInSeconds` — default 600s
- To end a session explicitly, invoke with `endSession: true`

## Security Considerations

**IAM — least privilege:**

- The agent's `agentResourceRoleArn` MUST be scoped to specific resource ARNs — avoid `bedrock:*` or `AmazonBedrockFullAccess`:
  - For base models, use `arn:aws:bedrock:<region>::foundation-model/``<model-id>```
  - For inference profiles, you MUST include BOTH the inference profile ARN (`arn:aws:bedrock:<region>:<account-id>:inference-profile/<profile-id>`) AND the foundation model ARN — for cross-region profiles, use wildcard region: `arn:aws:bedrock:*::foundation-model/``<model-id>```. See Step 2 for the complete IAM pattern and [Prerequisites for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html)
- Lambda execution roles MUST be scoped to specific function ARNs — avoid `lambda:*`
- Use IAM roles (not IAM users) for all agent and Lambda access

**Lambda security:**

- Lambda resource-based policies MUST include confused deputy protection (`aws:SourceAccount` + `aws:SourceArn`) — already detailed in Step 3
- Lambda handlers MUST validate and sanitize all agent-provided parameters — the agent generates these from user queries and they may contain injection payloads
- You MUST NOT hardcode secrets in Lambda code or environment variables — use Secrets Manager

**Agent instructions as attack surface:**

- Agent instructions are visible to the model and influence behavior — do not include secrets, internal URLs, or sensitive business logic in instructions
- Treat agent instructions as semi-public — they can be extracted via prompt injection attacks

**Session data:**

- Session attributes may contain sensitive user data — configure `idleSessionTTLInSeconds` to the minimum required
- Agent trace output (`enableTrace=true`) may contain user PII, session attributes, and KB retrieval content — do not log trace output to unencrypted or broadly accessible destinations
- CloudTrail logs `bedrock-agent` control plane API calls (CreateAgent, PrepareAgent, etc.) as management events by default
- To log `InvokeAgent` calls, you MUST configure CloudTrail advanced event selectors for the `AWS::Bedrock::AgentAlias` data event type — agent invocations are NOT logged by default
- You SHOULD set up CloudWatch alarms for agent invocation errors and throttling
- For PII workloads: encrypt agent resources with a customer-managed KMS key via `--customer-encryption-key-arn`

- Refer to the latest AWS documentation on Bedrock security best practices
