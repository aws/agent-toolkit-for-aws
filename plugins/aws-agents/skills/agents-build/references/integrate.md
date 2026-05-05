# integrate

Help a developer call their deployed agent from an application.

## When to use

- Developer has a deployed agent and wants to call it from their app
- Developer needs the agent URL and auth credentials
- Developer wants to handle streaming responses from the agent
- Developer needs to manage conversation sessions across multiple calls
- Developer is building a frontend, backend service, or CLI that consumes the agent
- Caller and agent are in different AWS accounts (cross-account invocation)

Do NOT use for:

- Giving the agent tools to call external APIs → use `agents-connect`
- Deploying the agent → use `agents-deploy`
- Debugging agent responses → use `agents-debug`
- Securing the agent endpoint for production → use `agents-harden` (but this skill covers the client-side auth code)

## Input

`$ARGUMENTS` can be:

- A language or framework: "from React", "in Python", "Node.js backend"
- An auth preference: "using IAM", "with JWT"
- Empty — the skill will detect the project context and guide accordingly

## Process

### Step 1: Check deployment status

Read `agentcore/agentcore.json` to get the agent name. Then check if it's deployed:

```bash
agentcore status --type agent
```

**If not deployed:** "Your agent needs to be deployed before you can call it from an app. Run `agentcore deploy` first, or use the `agents-deploy` skill for guidance."

Do not proceed until the agent is deployed.

### Step 2: Get the agent endpoint

```bash
agentcore fetch access --name <AgentName> --type agent
```

This returns:

- **Agent Runtime ARN** — needed for SDK invocation
- **Endpoint URL** — for direct HTTPS calls
- **Auth configuration** — what auth method is configured

Note the auth type from the output. It determines how the client app authenticates.

### Step 3: Determine auth method

Read the agent's `authorizerType` field from `agentcore/agentcore.json` (it's a top-level field on the runtime entry; JWT details live in the separate `authorizerConfiguration` object on the same runtime).

| Auth type | How the client authenticates | Best for |
|---|---|---|
| **None** (default) | IAM SigV4 signing on the request | Backend services with AWS credentials |
| **AWS_IAM** | IAM SigV4 signing on the request | Backend services, Lambda-to-agent calls |
| **CUSTOM_JWT** | Bearer token in Authorization header | Web/mobile apps with an identity provider |

**If no authorizer is configured:** The agent uses IAM auth by default. The calling identity needs `bedrock-agentcore:InvokeAgentRuntime` permission.

**If CUSTOM_JWT:** The client sends a JWT from the configured identity provider. The agent validates it against the discovery URL, allowed audience, and allowed clients configured during setup.

### Step 4: Generate client code

Based on the developer's language preference (from `$ARGUMENTS` or ask), generate the appropriate client code.

#### Python (boto3) — IAM auth

```python
import boto3
import json
from botocore.exceptions import ClientError

client = boto3.client("bedrock-agentcore", region_name="<REGION>")

try:
    response = client.invoke_agent_runtime(
        agentRuntimeArn="<AGENT_RUNTIME_ARN>",
        qualifier="DEFAULT",  # or a specific version number
        payload=json.dumps({
            "prompt": "Hello, what can you do?"
        }).encode(),
        runtimeSessionId="session-123",  # reuse for multi-turn conversations
    )

    # Handle streaming response — response["response"] is a StreamingBody
    stream = response["response"]
    if hasattr(stream, "iter_lines"):
        for line in stream.iter_lines():
            if line:
                print(line.decode(), end="", flush=True)
    else:
        # Some SDK versions return raw bytes — read all at once
        content = stream.read()
        print(content.decode() if isinstance(content, bytes) else content)

except ClientError as e:
    code = e.response["Error"]["Code"]
    if code == "AccessDeniedException":
        # Missing bedrock-agentcore:InvokeAgentRuntime permission
        raise RuntimeError("Caller lacks InvokeAgentRuntime permission") from e
    elif code == "ValidationException":
        # Wrong ARN, bad payload format, invalid session ID
        raise RuntimeError(f"Invalid request: {e}") from e
    elif code == "ThrottlingException":
        # Retry with exponential backoff
        raise
    else:
        raise
```

#### Python (HTTPS) — JWT auth

```python
import requests

AGENT_URL = "<ENDPOINT_URL>"
JWT_TOKEN = "<TOKEN_FROM_YOUR_IDP>"

response = requests.post(
    AGENT_URL,
    headers={
        "Authorization": f"Bearer {JWT_TOKEN}",
        "Content-Type": "application/json",
    },
    json={"prompt": "Hello, what can you do?"},
    stream=True,
)

for chunk in response.iter_content(chunk_size=None):
    print(chunk.decode(), end="", flush=True)
```

#### JavaScript/TypeScript (AWS SDK) — IAM auth

```typescript
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore";

const client = new BedrockAgentCoreClient({ region: "<REGION>" });

const response = await client.send(
  new InvokeAgentRuntimeCommand({
    agentRuntimeArn: "<AGENT_RUNTIME_ARN>",
    qualifier: "DEFAULT",
    payload: new TextEncoder().encode(
      JSON.stringify({ prompt: "Hello, what can you do?" })
    ),
    runtimeSessionId: "session-123",
  })
);

// response.response is the streaming body
const decoder = new TextDecoder();
for await (const chunk of response.response) {
  process.stdout.write(decoder.decode(chunk));
}
```

#### JavaScript/TypeScript (fetch) — JWT auth

```typescript
const AGENT_URL = "<ENDPOINT_URL>";
const JWT_TOKEN = "<TOKEN_FROM_YOUR_IDP>";

const response = await fetch(AGENT_URL, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${JWT_TOKEN}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ prompt: "Hello, what can you do?" }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  process.stdout.write(decoder.decode(value));
}
```

### Step 5: Session management

Explain how sessions work:

- **`runtimeSessionId`** — pass the same value across multiple calls to maintain conversation context
- Generate a unique session ID per user conversation (e.g., UUID)
- Sessions are server-side — the agent remembers the conversation history for that session ID
- If you omit the session ID, each call is stateless (no conversation memory)

```python
import uuid

# New conversation
session_id = str(uuid.uuid4())

# First turn
invoke(session_id, "What's the weather in Seattle?")

# Follow-up in same conversation
invoke(session_id, "What about tomorrow?")

# New conversation — new session
new_session_id = str(uuid.uuid4())
invoke(new_session_id, "Different topic entirely")
```

### Step 6: Protocol-specific guidance

Read the agent's `protocol` from `agentcore/agentcore.json`.

**If HTTP (default):** The patterns above apply directly.

**If MCP:** The agent exposes an MCP endpoint. Clients connect using the MCP protocol (Streamable HTTP). Point the developer to MCP client libraries for their language.

**If A2A:** The agent exposes an Agent-to-Agent endpoint with a card at `/.well-known/agent-card.json`. The calling agent discovers capabilities via the card and communicates over JSON-RPC 2.0. See [`references/multi-agent.md`](multi-agent.md) in this skill for A2A integration patterns.

### Step 7: Integration patterns that look right but fail

Two patterns come up often enough in support cases to call out directly.

**API Gateway `/{proxy+}` with a URL-encoded Runtime ARN.** Fronting AgentCore Runtime with an API Gateway REST API whose resource is `/{proxy+}` and whose integration URI is the encoded runtime ARN appears to work — the deploy succeeds and short requests return. Longer requests fail at around 2 minutes with `Integration closed connection prematurely` in the logs, regardless of `integrationTimeoutInMillis`. `HTTP_PROXY` is a generic forwarding integration; it doesn't handle SigV4, streaming, or session semantics the way the SDK client does.

Use one of these instead:

- Call Runtime directly from the client with the `bedrock-agentcore` SDK (Step 4 above). This is the intended path.
- Put a Lambda between API Gateway and Runtime if you need API Gateway for rate limiting, a public HTTPS endpoint, or other reasons. The Lambda receives the request, calls `invoke_agent_runtime`, and streams the response back. The Lambda's execution role needs `bedrock-agentcore:InvokeAgentRuntime`. Be aware that API Gateway has a 29-second hard ceiling on synchronous responses — this works only for fast agents. For anything multi-step, use the direct SDK path instead.

**Lambda-in-front for synchronous agent responses hits a short timeout ceiling.** A `Client → API Gateway → Lambda → Runtime` chain caps at ~29 seconds because of the API Gateway synchronous response limit. Any agent that reasons, calls multiple tools, or uses a non-trivial model will exceed it. If you're hitting timeouts on a Lambda wrapping Runtime, the fix is usually to drop the Lambda and let the client call Runtime directly — Runtime supports streaming responses natively, which is typically the reason teams add a Lambda in the first place.

### Step 8: Cross-account invocation

Calling an agent in a different AWS account than your caller uses standard AWS cross-account IAM patterns — no AgentCore-specific plumbing. The caller account assumes a role in the agent's account, gets temporary credentials, and uses them to sign the invoke request.

**Setup in the agent's account (Account B):**

Create an IAM role that trusts the caller account and has permission to invoke the runtime.

```json
// Trust policy — who can assume this role
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<CALLER_ACCOUNT_ID>:root"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"sts:ExternalId": "<unique-external-id>"}
    }
  }]
}
```

```json
// Permissions policy — what this role can do
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "bedrock-agentcore:InvokeAgentRuntime",
    "Resource": "arn:aws:bedrock-agentcore:<REGION>:<AGENT_ACCOUNT_ID>:runtime/<RUNTIME_NAME>-*"
  }]
}
```

Scope the `Principal` in the trust policy as narrowly as possible (a specific role ARN in the caller account rather than `:root` for anything beyond proof-of-concept). Use an `ExternalId` to prevent the confused deputy problem.

**In the caller's app (Account A):**

```python
import boto3
import json

# Assume the role in Account B
sts = boto3.client("sts")
assumed = sts.assume_role(
    RoleArn="arn:aws:iam::<AGENT_ACCOUNT_ID>:role/<ROLE_NAME>",
    RoleSessionName="agent-invoker",
    ExternalId="<unique-external-id>",
)
creds = assumed["Credentials"]

# Use the temporary credentials to invoke the runtime
agentcore = boto3.client(
    "bedrock-agentcore",
    region_name="<REGION>",
    aws_access_key_id=creds["AccessKeyId"],
    aws_secret_access_key=creds["SecretAccessKey"],
    aws_session_token=creds["SessionToken"],
)

response = agentcore.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:<REGION>:<AGENT_ACCOUNT_ID>:runtime/<RUNTIME_NAME>",
    qualifier="DEFAULT",
    payload=json.dumps({"prompt": "hello"}).encode(),
    runtimeSessionId="session-123",
)
```

**Production notes:**

- Cache the assumed-role credentials. They're valid for the session duration (default 1 hour). Re-assume when they're close to expiring, not on every request.
- Boto3's `Session` with a profile using `role_arn` and `source_profile` can automate this if your caller environment supports AWS config profiles. `assume_role` in code is the explicit version.
- If the caller is in a Lambda, ECS task, or EC2 instance, the execution/task role is what gets the AssumeRole permission. That role's trust policy is what gets listed in Account B's trust policy.
- The runtime's own resource policy (if any) is separate from IAM. Typically you don't need a resource policy for cross-account — the IAM role in Account B is what grants access.

## Running shell commands inside a live agent session (`InvokeAgentRuntimeCommand`)

Once an agent's session is running, you can execute shell commands inside that **same session's microVM** — same filesystem, same env, same network namespace — and stream the output back. This sits alongside `InvokeAgentRuntime` (which drives the agent's reasoning loop), not in place of it.

When this is useful:

- Coding/devops agents where your app runs deterministic ops (git pull, build, test, file system inspection) instead of asking the LLM to reason about them
- Seeding the session's filesystem before the agent runs (drop a dataset into `/tmp`, then invoke the agent to analyze it)
- Debugging a stuck or misbehaving session — run `ps`, `ls`, `cat /tmp/log` from outside without going through the agent
- Any workflow where you want the reliability of a scripted command and the context of a warm session

When it's the wrong tool:

- Spawning new sessions to run arbitrary code for users — use the [`code-interpreter.md`](code-interpreter.md) built-in tool instead; it's purpose-built, sandboxed differently, and doesn't consume an agent's session
- Running anything an unrelated caller shouldn't be able to do — commands execute with the runtime's execution role and filesystem

**IAM permission required:** `bedrock-agentcore:InvokeAgentRuntimeCommand` on the runtime ARN. This is a **separate** action from `InvokeAgentRuntime` — scope it explicitly to the callers who need it.

```python
import boto3

client = boto3.client("bedrock-agentcore", region_name="<REGION>")

response = client.invoke_agent_runtime_command(
    agentRuntimeArn="<AGENT_RUNTIME_ARN>",
    qualifier="DEFAULT",
    runtimeSessionId="session-123",   # must be an existing session
    command="ls -la /tmp && cat /tmp/status.json",
)

# Output streams back over HTTP/2 on response["response"]
for chunk in response["response"].iter_chunks():
    print(chunk.decode(), end="", flush=True)
```

**Session must exist.** `InvokeAgentRuntimeCommand` attaches to a running session; it won't create one. If the session has expired or never existed, the call fails. Invoke the agent first (to start the session), then use the session ID for subsequent command calls.

**Same microVM, same filesystem.** A file written by the command is visible to the agent on the next invoke, and vice versa. Use this to pre-load artifacts, then reason over them in the agent. Session isolation still applies — other sessions cannot see these files.

> [!WARNING]
> InvokeAgentRuntimeCommand executes arbitrary shell commands inside a live agent
> session with the runtime's full execution role. Never grant
> bedrock-agentcore:InvokeAgentRuntimeCommand to the same principals that have
> bedrock-agentcore:InvokeAgentRuntime unless they explicitly need shell access.
> Always create a separate IAM policy for command execution. Always enable CloudTrail
> logging for InvokeAgentRuntimeCommand calls. If commands are constructed from
> user-supplied input, validate and sanitize — this is a command injection surface.

**IAM separation:** `InvokeAgentRuntimeCommand` is a distinct IAM action from `InvokeAgentRuntime`. Grant it only to the callers that need shell access — not to every identity that can invoke the agent. Minimal example:

```json
{
  "Effect": "Allow",
  "Action": "bedrock-agentcore:InvokeAgentRuntimeCommand",
  "Resource": "arn:aws:bedrock-agentcore:<REGION>:<YOUR_ACCOUNT_ID>:runtime/<RUNTIME_NAME>-*"
}
```

Keep this in a separate IAM policy from the one that grants `InvokeAgentRuntime`. Attach it only to roles that explicitly need to run commands inside agent sessions.

**Command injection:** The code example above uses a hardcoded command string — intentionally. If your real usage constructs commands from user-supplied input, validate before passing: reject strings containing `&&`, `;`, `$(...)`, backticks, `|`, or other shell metacharacters. Passing unsanitized user input to `InvokeAgentRuntimeCommand` is a direct code execution vulnerability.

**CloudTrail monitoring:** Enable an EventBridge rule to alert on unexpected `InvokeAgentRuntimeCommand` calls:

```bash
aws events put-rule \
  --name AgentCoreCommandExecution \
  --event-pattern '{"source":["aws.bedrock-agentcore"],"detail-type":["AWS API Call via CloudTrail"],"detail":{"eventName":["InvokeAgentRuntimeCommand"]}}' \
  --state ENABLED
```

A compromised caller with this permission can read/write the agent's filesystem, reach any network resource the agent can reach, and use the execution role's credentials — CloudTrail logging is the minimum detection baseline.

## Reference integrations

Two common integration targets have published, reusable patterns you can start from instead of building the integration layer yourself.

**Slack.** [Integrating Amazon Bedrock AgentCore with Slack](https://aws.amazon.com/blogs/machine-learning/integrating-amazon-bedrock-agentcore-with-slack/) walks through a reusable integration layer that brings any AgentCore agent into a Slack workspace. The architecture (API Gateway → Lambda → SQS → AgentCore) handles Slack's 3-second webhook timeout via asynchronous processing: one Lambda validates the Slack signature and returns immediately, another posts a "Processing..." placeholder, and a third invokes the agent and replaces the placeholder with the real response. The pattern maps Slack thread timestamps to AgentCore Memory session IDs and Slack user IDs to actor IDs, so conversation context persists in the same thread over time. The integration layer is decoupled from the agent — you swap in any agent (FinOps, DevOps, incident response) without touching the Slack infrastructure. Deploys with one `cdk deploy`.

**Microsoft Teams.** The same async-processing architecture (API Gateway → Lambda → queue → AgentCore) applies to Teams. See [How Amazon Bedrock transforms Microsoft Teams conversations into actionable insights](https://aws.amazon.com/blogs/industries/how-amazon-bedrock-transforms-microsoft-teams-conversations-into-actionable-insights/) for Teams-specific setup (Bot Framework registration, bot channel configuration). If you've already built the Slack pattern above, the Teams version is primarily a different webhook validator and response formatter.

Both patterns handle the "webhook platform with short timeout" problem in the same way — the chat platform gets an immediate ack and a placeholder, the real agent call happens asynchronously, and the response replaces the placeholder when ready. If you're integrating a third chat platform not listed here, use either blog as a template.

## Output

- The agent's endpoint URL and ARN
- Auth method explanation with client-side code
- Working client code in the developer's preferred language
- Session management guidance
- Protocol-specific notes if applicable

## Quality criteria

- Client code uses the correct SDK client (`bedrock-agentcore`, not `bedrock-agent`)
- Auth method matches what's configured on the agent
- Streaming response handling is included (not just request/response)
- Session ID pattern is explained
- Code is complete and runnable — includes imports, error handling basics
