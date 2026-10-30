# Connecting to AWS DevOps Agent over MCP

Run this **only after** the user has said Yes to the combined cost-and-access question (SKILL.md, CONFIRM).

**Mandatory prerequisite:** the user has explicitly answered Yes to the single combined cost-and-account-access
approval for the intended AWS account. A cost notice alone, a previous unrelated request, or a lack of
objection does not satisfy this requirement. If approval is missing, do not perform setup writes.

**Standard monitoring setup only.** Do not enable the Agent Space's Directed Actions preference
(`elevatedActionsEnabled`), create or register an elevated remediation role (`agentElevatedRoleArn`),
attach `AIDevOpsAgentActionsPolicy`, or broaden the monitoring role. New spaces keep Directed Actions at
the AWS default (disabled); a reused space keeps whatever it already has. If the account in use is not the
one the user approved, confirm the target before writing.

## Assume they are starting from nothing

**Almost every startup reaching this point has no Agent Space and has never heard the term.** Treat that
as the default path, not the exception.

An Agent Space is the workspace that scopes an environment, its connections, and its permissions. One has
to exist before anything can run. **Never ask the user whether they have one, or which region theirs is
in** — the question is meaningless to someone encountering the concept for the first time, and it makes
them feel behind before they have started.

Introduce it as a step you are doing, not a prerequisite they failed to meet:

> "DevOps Agent needs a workspace in your **AWS account** before it can do anything — AWS calls it an
> **Agent Space**. It's the boundary: the agent can only see and act inside what that workspace is scoped
> to, its permissions live there, and it's the one place you revoke them. I'll walk you through creating
> one."

**Always give the reason, not just the instruction.** "You need to create an Agent Space" is a chore.
"This is the boundary that decides what the agent can touch, and the switch that turns it off" is a
control the founder is being handed. Someone about to let an autonomous agent into their production
account should want that boundary to exist — say why it is in their interest, not merely that it is
mandatory.

Three things that phrasing is doing deliberately:

- **"your AWS account", not "your account".** In a coding agent, "your account" could mean GitHub, the
  agent vendor, or AWS. Say which.
- **Both names.** Lead with "workspace" so the concept lands, then give the real term — because every
  label in the console says *Agent Space*, and a founder searching for "workspace" will not find it.
- **The scope *is* the reason.** Do not pitch an Agent Space as a feature — it is a container, and
  container benefits read as filler. Explain what it *bounds*, because that is both the honest answer to
  "why do I need this" and a control the user keeps. A founder about to let an autonomous agent into their
  production account wants to hear where the edges are, and that it is theirs to move.

If they ask whether they need more than one: one is enough to start. Separate Agent Spaces are how you
keep environments apart — production from staging — and that is worth doing later, not now. Do not turn
this into a configuration exercise before they have seen the thing work.

### Creating it

**Create it for them. Do not send them to the console.**

```bash
aws devops-agent create-agent-space --name "<name>" --region <region> --tags CreatedBy=aws-startup-advisor
```

`name` is the only required argument. Always add the `CreatedBy=aws-startup-advisor` tag (pass it the same
way to the MCP `create_agent_space` tool): it records on the space itself that AWS Startup Advisor created
it. If the call is denied only for tagging (`aidevops:TagResource`), create the space without `--tags`
rather than stopping; the tag is a record, not a requirement. The CLI service is **`devops-agent`** — note that the *endpoint* and
IAM signing name are `aidevops`, which is why searching for an `aidevops` command group finds nothing.
Verified against AWS CLI 2.36.16: 62 operations, including `create-agent-space`, `list-agent-spaces`,
`associate-service` and `get-account-usage`.

Check first, since the founder may already have one:

```bash
aws devops-agent list-agent-spaces --region <region>
```

If either call returns `AccessDeniedException`, it is an IAM permission gap on `aidevops:*`, not a missing
capability — say that, and say which action was denied. The console remains the fallback for a founder
whose credentials cannot be widened, not the default path.

### Picking a region

Do not ask "which region." Ask what they can answer, or better, work it out and offer it.

Detection ladder, first hit wins:

```bash
# 1. Infrastructure-as-code in the workspace — the strongest signal, since it is
#    where the workload actually runs
grep -rE 'region|AWS_REGION' --include=*.tf --include=cdk.json --include=samconfig.toml .

# 2. Explicit environment override
echo "${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

# 3. Active profile
aws configure get region
```

Then offer it as a decision already made, reversible in one word:

> "I'll set this up in us-east-1 — that's where your CDK stack deploys. Say the word if your production
> workload runs somewhere else."

The Agent Space should live where the **workload** runs, because that is what the agent investigates. That
is usually but not always the CLI default — profiles on one machine routinely span regions. It must also
be a region where DevOps Agent is available; check the supported list before committing to one. If an
Agent Space already exists, its region wins over all of the above — find it first (`references/readiness.md`).
The exception is release review, which runs only in `us-east-1` during preview.

## Endpoint

```
https://connect.aidevops.{region}.api.aws/mcp     POST
```

Client timeout must be **at least 120 seconds**. Initial responses take 5–30 seconds and investigations
run 5–8 minutes; a default 30-second timeout will appear to fail while the agent is working normally.

## Auth — prefer SigV4

**SigV4 (preferred).** Uses the AWS credentials the user already has. Nothing new is minted, nothing
expires in 60 days, nothing needs storing.

```json
{
  "mcpServers": {
    "aws-devops-agent": {
      "command": "uvx",
      "timeout": 120000,
      "args": [
        "mcp-proxy-for-aws@latest",
        "https://connect.aidevops.{region}.api.aws/mcp",
        "--service", "aidevops",
        "--region", "{region}"
      ]
    }
  }
}
```

Requires `uvx` (Python) on the machine — check with `uvx --version` before recommending this path. If it
is missing, either install `uv` or fall back to a bearer token. Do not silently write a config that cannot
run.

**On `@latest`:** this is AWS's published configuration, reproduced as documented. It means the proxy code
executed on the machine can change without notice. If the user's environment has a policy on unpinned
dependencies, pin a known version instead — the endpoint and arguments are unchanged.

SigV4 also supports multiple Agent Spaces from one client by passing `agent_space_id` per tool call.

**Bearer token (fallback).** Use when the user has no working AWS credentials in the environment, or no
`uvx`.

```json
{
  "mcpServers": {
    "aws-devops-agent": {
      "url": "https://connect.aidevops.{region}.api.aws/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

Tokens do **not** require the console. The MCP server exposes `create_access_token`, `list_access_tokens`,
`rotate_access_token` and `revoke_access_token`, and the CLI has the equivalents — so a token can be minted
from the same place everything else happens. The web app (Settings → Access Tokens) remains an option, not
a requirement.

Prefer SigV4 anyway: nothing is minted, nothing expires, nothing needs storing.

When advising on token settings:

- **Scope** — `read` unless the user needs to send messages or manage tasks. Do not default to `operate`.
- **Client type** — `human` for IDE and CLI use.
- **Expiry** — 1 to 60 days. Shorter is better; tell them it will need rotating.
- **IP allowlist** — offer it. It costs nothing and meaningfully limits a leaked token.

Never write a token into a file the user might commit. Environment variable or secrets manager only, and
say which you used.

## How the plugin was installed changes what exists

Two install paths. They do not leave the machine in the same state.

| Path | Registers the plugin's MCP servers | Registers DevOps Agent |
|---|---|---|
| `/plugin install aws-startup-advisor@agent-toolkit-for-aws` (after `/plugin marketplace add aws/agent-toolkit-for-aws`) | yes (`aws-mcp`) | **no** |
| `npx skills add aws/agent-toolkit-for-aws/plugins/aws-startup-advisor/skills …` | **no** — skills only | **no** |

**Neither path registers the DevOps Agent server.** This plugin does not declare it, because the endpoint is
region-specific and the auth is per-user. So do not assume it is present just because this skill is. Check
first — including for an `aws-devops-agent` server from the `aws-agents-for-devsecops` plugin — and register
it if absent.

If a Claude Code user installed via `npx`, mentioning a marketplace install is worth one line: it fixes the
same gap for `aws-mcp`, which the other skills in this plugin use.

If a user is on a marketplace copy and something described here is missing, check the plugin version before
debugging further — mirrored listings can trail the source repository.

## Connecting an AWS account is the real setup step — not the Agent Space

Creating the Agent Space is one call and it **auto-creates the service-linked role**
`AWSServiceRoleForAIDevOps` (trusting `aidevops.amazonaws.com`) in the same second. Nothing to do there.

Pointing the agent at an account is the step that needs work. `AssociateService` with `configuration.aws`
requires:

| Field | |
|---|---|
| `accountId` | the account to monitor |
| `accountType` | `monitor` |
| **`assumableRoleArn`** | **an IAM role the customer must create**, which DevOps Agent assumes to read telemetry |

**AWS documents this end to end** — see the
[CLI onboarding guide](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-cli-onboarding-guide.html).
**Never invent the trust policy.** Use exactly this, substituting the account and region:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "aidevops.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "<ACCOUNT_ID>" },
      "ArnLike": { "aws:SourceArn": "arn:aws:aidevops:<REGION>:<ACCOUNT_ID>:agentspace/*" }
    }
  }]
}
```

The `aws:SourceAccount` / `aws:SourceArn` conditions are **confused-deputy prevention** — they stop any
other account's Agent Space assuming the role. Do not drop them.

Then attach the AWS-managed policy and one inline permission:

```bash
aws iam create-role --role-name DevOpsAgentRole-AgentSpace \
  --assume-role-policy-document file://trust.json

aws iam attach-role-policy --role-name DevOpsAgentRole-AgentSpace \
  --policy-arn arn:aws:iam::aws:policy/AIDevOpsAgentAccessPolicy

# inline: lets the agent create the Resource Explorer service-linked role
aws iam put-role-policy --role-name DevOpsAgentRole-AgentSpace \
  --policy-name AllowCreateServiceLinkedRoles --policy-document file://slr.json

aws devops-agent associate-service --agent-space-id <AGENT_SPACE_ID> \
  --service-id aws \
  --configuration '{"aws":{"assumableRoleArn":"<ROLE_ARN>","accountId":"<ACCOUNT_ID>","accountType":"monitor"}}' \
  --region <REGION>
```

`--service-id` is the literal string **`aws`**. A successful association returns `status: "valid"`.

**None of this runs before the Yes** — the access part of the combined notice (SKILL.md Phase 2.5 and
CONFIRM) is what the user approved. The role grants an AWS service read access across the account, plus
starting CloudTrail queries and creating AWS Support cases — the broadest permission in the flow and the
one the founder is least likely to have thought about.

This is also where onboarding effort actually sits — not the Agent Space, which is a single call.

## Verified end to end, 2026-08-13

Run against a real account with nothing pre-existing, using ordinary AWS credentials and no console at any
point:

| Step | Result |
|---|---|
| `aws devops-agent list-agent-spaces` | `{"agentSpaces": []}` |
| `aws devops-agent create-agent-space --name …` | created immediately; returned `agentSpaceId`, no pending state |
| MCP `initialize` over SigV4 | HTTP 200 — `aws-devops-agent-remote` 1.0.0, protocol `2025-06-18` |
| MCP `tools/list` | 200 — **34 tools** |
| MCP `tools/call list_agent_spaces` | 200 — returned the space just created |

No `Mcp-Session-Id` header is issued, so no session threading is needed. `create_agent_space` is itself one
of the 34 tools, which means the entire setup can happen inside one conversation in the founder's agent —
no CLI, no console.

Not run: `chat` or `investigate`, because those bill.

## Verify before declaring success

Make one authenticated call that starts no agent work — MCP `tools/list`, or `tools/call
list_agent_spaces` — and confirm a real response. Do not use `chat` or `investigate` to verify: both are
billed agent usage, so a user who only asked for setup would pay for a check they did not ask for. Run
those only for an operational request. Do not tell the user they are connected on the basis of a
written config file.

| Symptom | Cause | Fix |
|---|---|---|
| HTTP 401 | Token invalid or expired | Rotate in the web app |
| Request times out | Client timeout below 120 s | Raise it |
| Connection refused | Wrong region or malformed URL | Check against the Agent Space's region |
| `uvx` not found | SigV4 path without `uv` installed | Install `uv`, or use a bearer token |

## Reporting the new Agent Space

AWS Startup Advisor's usage telemetry records the new space's `agentSpaceId` (an opaque id, nothing else),
and only with the user's consent. Do this **after** setup is confirmed above, never before or alongside the
setup approval, and never let it block or delay setup. If Python or the bundled runtime is unavailable, or
any step fails, skip it. Substitute this skill's absolute directory in each command.

1. Check the host and consent:

   ```sh
   python3 "<absolute-skill-root>/references/vendored/telemetry/devops_agent_cli.py" status
   ```

   If `consentStatus` is `OPT_OUT`, stop.

2. If `needsNotice` is `true` and the notice has not already been raised in this session, run the bundled
   notice, relay its output VERBATIM (including its question), and end that turn. `needsNotice` is also
   true when an earlier acknowledgement was to a notice that did not name the Agent Space ID:

   ```sh
   python3 "<absolute-skill-root>/references/vendored/telemetry/consent/cli.py" show
   ```

   After the user replies, run `consent/accept.py` only for an explicit acknowledgement, or
   `consent/opt_out.py` for an explicit opt-out. If they ignore it or move on, record nothing and do not
   raise it again this session. Telemetry consent does not authorize anything else.

3. Report the space with the `agentSpaceId` you verified above. Run this only for the space this skill just
   created, never one found or created another way; it sends nothing unless consent covers it:

   ```sh
   python3 "<absolute-skill-root>/references/vendored/telemetry/devops_agent_cli.py" space-created --agent-space-id <agentSpaceId>
   ```

## Also worth knowing

There is an existing official Claude Code integration — the `aws-agents-for-devsecops` plugin, which
brings both AWS DevOps Agent and AWS Security Agent. If a user already has it, do not build a second
connection. Use theirs and skip to OPERATE.

Every remote-server call is recorded in CloudTrail under `aidevops.amazonaws.com` in the account hosting
the Agent Space. Mention this if the user asks about auditability — it is a genuine advantage over
third-party tooling.
