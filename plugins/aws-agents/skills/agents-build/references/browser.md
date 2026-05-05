# browser

Add the AgentCore Browser tool so your agent can navigate web pages, fill forms, and extract information.

## When to use

- Your agent needs to interact with a website that has no API
- Your agent needs to fill forms, scrape data, or drive a web app
- You want an isolated, session-scoped browser for the agent (not a shared one)
- You want live-view / recording / replay of what the browser did, for debugging or auditing

Do NOT use this reference for:

- Calling an API — use Gateway (`agents-connect`)
- Running code in a sandbox — see [`code-interpreter.md`](code-interpreter.md)
- Serving browser-based UIs to users — that's a different problem (the AGUI protocol, not the Browser tool)

## Mental model

The Browser tool is a **managed Chrome instance**, one per session, running in an isolated microVM. Your agent connects to it over WebSocket (via CDP — Chrome DevTools Protocol) and drives it with an automation framework. You pick the framework:

| Framework | When to use |
|---|---|
| **Strands `AgentCoreBrowser`** | Agent-driven browsing inside a Strands agent. Highest-level, tool-use-native. |
| **Nova Act** | You want an LLM to decide the next action at each step ("click the search box, type X, press enter"). Best for open-ended tasks. |
| **Playwright** | Deterministic scripted automation. Best when you know the exact steps — login flows, scraping a known page structure. |

If you're adding browsing to a Strands agent, use `AgentCoreBrowser` and skip the framework decision — it wraps Nova Act under the hood and fits the agent-tool mental model.

If you're not using Strands, pick between Nova Act (reasoning-driven) and Playwright (script-driven) based on whether the task is open-ended or well-defined.

Sessions are **ephemeral by default** (reset after each use). Default timeout is 15 minutes, max 8 hours. You can run multiple concurrent sessions.

## Prerequisites

- Python 3.10+
- `bedrock-agentcore` SDK installed
- IAM permissions for `bedrock-agentcore:*Browser*` actions (scope to your browser resource ARN in production)
- AWS region that supports Browser — check the docs for the current list
- For Strands path: model access for your chosen model (Claude Sonnet 4.x is the common default)
- For Nova Act path: a Nova Act API key from [nova.amazon.com/act](https://nova.amazon.com/act) (US-based amazon.com accounts only at time of writing)

IAM policy skeleton (attach to the caller identity — your user, role, or AgentCore Runtime execution role):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "BrowserAccess",
    "Effect": "Allow",
    "Action": [
      "bedrock-agentcore:CreateBrowser",
      "bedrock-agentcore:GetBrowser",
      "bedrock-agentcore:ListBrowsers",
      "bedrock-agentcore:StartBrowserSession",
      "bedrock-agentcore:StopBrowserSession",
      "bedrock-agentcore:GetBrowserSession",
      "bedrock-agentcore:ListBrowserSessions",
      "bedrock-agentcore:ConnectBrowserAutomationStream",
      "bedrock-agentcore:ConnectBrowserLiveViewStream"
    ],
    "Resource": "arn:aws:bedrock-agentcore:<REGION>:<ACCOUNT_ID>:browser/*"
  }]
}
```

Check current IAM action names against the docs — the list evolves.

## Path A — Strands agent with the Browser tool (recommended for most)

```python
from strands import Agent
from strands_tools.browser import AgentCoreBrowser

browser_tool = AgentCoreBrowser(region="<REGION>")

agent = Agent(tools=[browser_tool.browser])

result = agent("Find the release date of the latest AgentCore SDK on GitHub.")
print(result.message["content"][0]["text"])
```

Install: `pip install bedrock-agentcore strands-agents strands-agents-tools`

The agent decides when to use the browser, opens sessions on demand, and cleans them up. Under the hood, `AgentCoreBrowser` uses the AWS-managed `aws.browser.v1` resource — no resource creation needed.

**Dropping into an AgentCore Runtime entrypoint:**

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands_tools.browser import AgentCoreBrowser
from model.load import load_model  # scaffolded by `agentcore create`
import os

app = BedrockAgentCoreApp()
REGION = os.getenv("AWS_REGION", "us-west-2")

@app.entrypoint
def invoke(payload, context):
    browser_tool = AgentCoreBrowser(region=REGION)
    agent = Agent(model=load_model(), tools=[browser_tool.browser])
    result = agent(payload.get("prompt", ""))
    return {"response": str(result)}

if __name__ == "__main__":
    app.run()
```

## Path B — Nova Act for reasoning-driven tasks

Use when the task needs an LLM to decide each click/type step.

```python
from bedrock_agentcore.tools.browser_client import browser_session
from nova_act import NovaAct

def run_browser_task(prompt: str, starting_page: str, nova_act_key: str, region: str = "us-west-2"):
    with browser_session(region) as client:
        ws_url, headers = client.generate_ws_headers()
        with NovaAct(
            cdp_endpoint_url=ws_url,
            cdp_headers=headers,
            nova_act_api_key=nova_act_key,
            starting_page=starting_page,
        ) as nova:
            return nova.act(prompt)
```

Install: `pip install bedrock-agentcore nova-act boto3`

The `browser_session` context manager handles start/stop. Do not leak sessions — always use the context manager or wrap raw `BrowserClient` calls in try/finally.

**Credential handling:** the Nova Act API key is a secret. If this is running inside an AgentCore Runtime agent, register it as a credential (`agentcore add credential --name NovaAct --api-key ...`) and retrieve it with `@requires_api_key(provider_name="NovaAct")`. Do not put it in runtime env vars. See `agents-connect` Path D.

## Path C — Playwright for scripted automation

Use when the steps are fixed and you want deterministic behavior (logins, scrapes, automated tests).

```python
import asyncio
from bedrock_agentcore.tools.browser_client import browser_session
from playwright.async_api import async_playwright

async def scrape_title(url: str, region: str = "us-west-2") -> str:
    async with async_playwright() as pw:
        with browser_session(region) as client:
            ws_url, headers = client.generate_ws_headers()
            browser = await pw.chromium.connect_over_cdp(ws_url, headers=headers)
            context = browser.contexts[0]
            page = context.pages[0]
            try:
                await page.goto(url)
                return await page.title()
            finally:
                await page.close()
                await browser.close()

print(asyncio.run(scrape_title("https://example.com")))
```

Install: `pip install bedrock-agentcore playwright`

Sync variant (`sync_playwright`) is also supported — pick based on whether your agent code is async.

## Observability

Browser is observable by default:

- **Live view** — watch a running session in real time from the AWS console (Built-in tools → Browser → your session → "View live session"). You can take over control from the automation interactively.
- **CloudWatch logs** — `/aws/bedrock-agentcore/browser/*`
- **Metrics** — in `AWS/BedrockAgentCore` namespace

**Session recording** (DOM, clicks, console logs, network) is opt-in per browser. To enable:

1. Create a **custom browser** (not `aws.browser.v1`) with recording configured
2. Give its execution role `s3:PutObject` on your recording bucket
3. Recordings land in your S3 bucket and replay in the AWS console

The managed `aws.browser.v1` resource does **not** record. Use custom browsers when you need audit trails.

## Session lifecycle — always close

```python
# Right — context manager
with browser_session(region) as client:
    ws_url, headers = client.generate_ws_headers()
    ...

# Also right — explicit try/finally
client = BrowserClient(region=region)
client.start()
try:
    ...
finally:
    client.stop()

# Wrong — leaked session
client = BrowserClient(region=region)
client.start()
...  # if this raises, the session sits idle until its 15-minute timeout
```

Sessions hold a microVM. Leaked sessions cost money until they time out. The context manager is non-negotiable for production.

## VPC mode

If your agent runs in VPC mode, the Browser tool can also run in VPC. See [`vpc.md`](vpc.md) for the subnet + security group pattern (the same service-linked role covers Browser ENIs). Browser in VPC requires a NAT gateway for public-internet sites — public subnets don't give Browser internet access.

## Common failures

**"Access denied" starting a session:** IAM is missing `StartBrowserSession` on the browser resource ARN. Check `aws sts get-caller-identity` matches the identity you attached the policy to.

**"Model access denied" from a Strands agent:** The browser tool itself is fine, but the agent's model isn't enabled. Go to Bedrock console → Model access → enable your model in the region.

**Nova Act errors about API key:** The key is US-amazon.com-accounts only at launch. If you're outside the US or using a work account, you can't use Nova Act yet — fall back to Playwright or Strands.

**Browser session times out mid-task:** Default is 15 minutes of idle time. Pass `sessionTimeoutSeconds` to `StartBrowserSession` (max 28800 = 8 hours). Don't use this to cover up agents that are slow — fix the agent or chunk the work.

**Live view doesn't show your session:** Live view requires `ConnectBrowserLiveViewStream` IAM permission. The session also has to be `Ready`, not `Starting` or `Stopping`.

## Output

- Which framework fits (Strands vs Nova Act vs Playwright)
- Working code with session lifecycle handled
- IAM policy scoped to the browser resource
- Observability setup if needed (live view, recording)

## Quality criteria

- Browser sessions are always wrapped in a context manager or try/finally — never leaked
- IAM is scoped to `browser/*` in the account, not `Resource: "*"`
- Nova Act API keys and other secrets use `agentcore add credential` + `@requires_api_key`, not env vars
- The code handles the case where the agent runs outside AgentCore Runtime (no `.env.local`, no credential provider) — typically by reading a local secret for development and the credential provider for production
