# code-interpreter

Add the AgentCore Code Interpreter tool so your agent can execute code in a sandboxed environment — Python, JavaScript, or TypeScript.

## When to use

- Your agent needs to run math, data analysis, or transform data where a calculation is more reliable than an LLM answer
- Your agent generates code as an answer and you want it executed (and its output verified) before returning
- Your agent needs to read/write files (CSV, JSON, plots) that should persist to S3
- You need an isolated, session-scoped code sandbox

Do NOT use this reference for:

- Interacting with web pages — see [`browser.md`](browser.md)
- Running arbitrary long-lived services — Code Interpreter is for short-lived code execution, not hosting servers
- Shell commands *inside your live agent session's own microVM* — that's `InvokeAgentRuntimeCommand`, covered in [`integrate.md`](integrate.md)

## Mental model

Code Interpreter is a **managed sandbox**, one per session, running in an isolated microVM. Your code can:

- Execute Python, JavaScript, or TypeScript
- Read/write files on a local filesystem (up to 100 MB inline upload, up to 5 GB via S3)
- Make network calls (if internet access is enabled on the resource)
- Use pre-installed libraries (pandas, numpy, scikit-learn, torch, etc. — see docs for the current list)

Sessions are **stateful within a session** (variables and files persist across `execute_code` calls in the same session) and **ephemeral across sessions** (start a new session and the filesystem is clean).

## Prerequisites

- Python 3.10+ in your agent environment
- `bedrock-agentcore` SDK
- IAM permissions for `bedrock-agentcore:*CodeInterpreter*` actions, scoped to the resource ARN
- Model access if calling via an agent framework (the framework calls a model to decide when to execute code)

IAM policy skeleton:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "CodeInterpreterAccess",
    "Effect": "Allow",
    "Action": [
      "bedrock-agentcore:CreateCodeInterpreter",
      "bedrock-agentcore:GetCodeInterpreter",
      "bedrock-agentcore:ListCodeInterpreters",
      "bedrock-agentcore:StartCodeInterpreterSession",
      "bedrock-agentcore:StopCodeInterpreterSession",
      "bedrock-agentcore:InvokeCodeInterpreter",
      "bedrock-agentcore:GetCodeInterpreterSession",
      "bedrock-agentcore:ListCodeInterpreterSessions"
    ],
    "Resource": "arn:aws:bedrock-agentcore:<REGION>:<ACCOUNT_ID>:code-interpreter/*"
  }]
}
```

Check current action names against the docs — the list evolves.

## Path A — Strands agent with Code Interpreter (recommended for most)

```python
from strands import Agent
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

tool = AgentCoreCodeInterpreter(region="<REGION>")

agent = Agent(
    tools=[tool.code_interpreter],
    system_prompt=(
        "You are an assistant that validates claims with code. "
        "When asked to compute, calculate, or analyze, write Python and run it."
    ),
)

result = agent("What are the first 10 Fibonacci numbers?")
print(result.message["content"][0]["text"])
```

Install: `pip install bedrock-agentcore strands-agents strands-agents-tools`

The agent decides when to execute code, starts sessions on demand, and stops them. Under the hood, the tool uses the AWS-managed `aws.codeinterpreter.v1` resource — no resource creation needed.

**Dropping into an AgentCore Runtime entrypoint:**

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from model.load import load_model
import os

app = BedrockAgentCoreApp()
REGION = os.getenv("AWS_REGION", "us-east-1")

@app.entrypoint
def invoke(payload, context):
    tool = AgentCoreCodeInterpreter(region=REGION)
    agent = Agent(
        model=load_model(),
        tools=[tool.code_interpreter],
        system_prompt="Validate computations with code.",
    )
    return {"response": str(agent(payload.get("prompt", "")))}

if __name__ == "__main__":
    app.run()
```

## Path B — Direct SDK for programmatic execution

Use when your code — not an agent — decides what to run. Good for ETL, data transformation, and agent-internal validation.

```python
from bedrock_agentcore.tools.code_interpreter_client import code_interpreter_session

REGION = "us-east-1"

with code_interpreter_session(REGION) as session:
    # Stateful: variables persist across calls within the session
    session.execute_code("import pandas as pd")
    session.execute_code("df = pd.DataFrame({'x': [1, 2, 3]})")
    result = session.execute_code("df.describe().to_string()")
    print(result.stdout)
```

The context manager handles start/stop. Do not leak sessions.

**Language selection** — default is Python. For JavaScript/TypeScript, pass `language="javascript"` or `language="typescript"` to `execute_code` (or the runtime setting at session start). See the runtime selection doc for the current supported runtimes.

## Path C — Custom Code Interpreter with S3 access

The managed `aws.codeinterpreter.v1` resource has no S3 write permissions. For agents that produce artifacts (plots, reports, processed datasets) you want to persist, create a **custom Code Interpreter** with an execution role that has S3 access.

This is a CreateCodeInterpreter call (SDK/API, not exposed via `agentcore` CLI at time of writing). The execution role's trust policy grants `bedrock-agentcore.amazonaws.com` the ability to assume it, and its permissions policy grants `s3:PutObject` and related actions on your artifact bucket. Check the docs for the current `CreateCodeInterpreter` shape and the exact trust policy format.

**Same-account S3 rule.** The S3 bucket must be in the **same AWS account** as the Code Interpreter resource. Cross-account buckets are not supported as targets even with the right bucket policy — `CreateCodeInterpreter` fails with a validation error. If you need the artifacts in another account, replicate from the same-account bucket afterward.

## Observability

- **CloudWatch logs** — stdout/stderr from executed code, plus session lifecycle events
- **CloudTrail** — every `StartCodeInterpreterSession`, `InvokeCodeInterpreter`, `StopCodeInterpreterSession` call
- **Metrics** — in `AWS/BedrockAgentCore` namespace

## Pre-installed libraries

The managed Python runtime includes: `pandas`, `numpy`, `scipy`, `matplotlib`, `plotly`, `scikit-learn`, `torch`, `torchvision`, `statsmodels`, and dozens more for data analysis / ML. Check the current list in the docs before telling a user "library X is preinstalled" — the list changes with platform updates.

For libraries not preinstalled, call `install_packages(["your-lib==1.2"])` in your session (or `!pip install ...` via `execute_command`). Installed packages last only for the session.

## Session lifecycle — always close

```python
# Right — context manager
with code_interpreter_session(region) as session:
    session.execute_code("...")

# Right — try/finally with explicit client
client = CodeInterpreterClient(region=region)
client.start()
try:
    client.execute_code("...")
finally:
    client.stop()

# Wrong — leaked session sits until timeout
```

Default session timeout is 900 seconds (15 min), max 28800 seconds (8 hours). Leaked sessions cost money.

## VPC mode

Code Interpreter supports VPC — same pattern as Runtime and Browser (service-linked role, your subnets, your security group). See [`vpc.md`](vpc.md).

**Public internet from the sandbox** requires a NAT gateway on a private subnet, same as Runtime. Public subnets don't give Code Interpreter ENIs internet access. If the code needs `pip install` to reach PyPI, plan for NAT.

## Common failures

**"Access denied" on StartCodeInterpreterSession:** IAM missing the action on the resource ARN. Use `aws sts get-caller-identity` to confirm which identity you attached the policy to.

**"ValidationException: Role does not have access to required S3 buckets":** S3 bucket is in a different account. Move the bucket or replicate from an in-account staging bucket.

**Code times out:** Default execute timeout is short. Split long jobs into chunks, or use a custom Code Interpreter with extended timeouts. Don't try to run 30-minute training jobs in Code Interpreter — that's a SageMaker / Batch job.

**"Module not found" despite being listed as preinstalled:** The preinstalled list may differ between `python` and `nodejs` runtimes. Verify runtime selection and list matches.

## Output

- Which path fits (Strands tool vs direct SDK vs custom with S3)
- Working code with session lifecycle handled
- IAM policy scoped to the code-interpreter resource

## Quality criteria

- Sessions are always wrapped in a context manager or try/finally — never leaked
- IAM is scoped to `code-interpreter/*` in the account, not `Resource: "*"`
- S3 destination buckets are in the same account as the Code Interpreter resource
- Language / runtime selection is explicit when the code isn't Python
