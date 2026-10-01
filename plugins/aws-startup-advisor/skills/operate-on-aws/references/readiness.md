# Readiness — know where the user stands before you ask them for anything

Run this early, in DETECT. It takes seconds and it decides everything after it.

The point is not to gate the user. It is the opposite: **most intents need far less than full AWS access,
and asking someone to authenticate before answering a question they could have had answered for free is
the fastest way to lose them.**

## Preflight

Three commands. All read-only, all free, all fast.

```bash
aws --version                  # is the CLI there, and new enough
aws sts get-caller-identity    # are there credentials, whose, still valid
aws configure get region       # which region they default to
```

Do not run `aws billing get-credits` here. It is only needed for DISCLOSE, and running it before you know
you need it wastes a call and can produce a confusing error before you have context to explain it.

## Classify

Match on the **error signature**, not just success or failure. These states need different help and the
difference matters.

| State | Signature | What it means |
|---|---|---|
| **R0 — no CLI** | `aws: command not found` | Nothing AWS-shaped is installed |
| **R1 — CLI too old** | `aws --version` < 2.35.23 | Fine for most things; `billing get-credits` will not exist |
| **R2 — no credentials** | `Unable to locate credentials` | Normal for someone evaluating. **Not an error.** |
| **R3 — expired** | `ExpiredToken`, `security token … is expired`, `SSO session … has expired` | They *had* access minutes or hours ago |
| **R4 — valid** | account ID returned | Ready for anything except billing reads |
| **R5 — billing readable** | `get-credits` returns | Full disclosure possible |

**R3 is the one worth separating.** Expired SSO is a ten-second fix — `aws sso login --profile <name>` —
and treating it like R2 sends someone down a setup path they finished last week. Read the profile from
`AWS_PROFILE` or `aws configure list` and hand them the exact command, not generic advice.

## Which sign-in method — because the fix differs

R3 "expired" is not one thing. Detect the mechanism before offering a remedy, or you will tell someone on
static keys to run `aws sso login`.

```bash
aws configure list                                   # TYPE column shows the resolved source
aws configure get sso_session   --profile <p>        # modern SSO  → returns a session name
aws configure get sso_start_url --profile <p>        # legacy SSO  → returns a URL
aws configure get aws_access_key_id --profile <p>    # static keys → AKIA…
aws configure get role_arn      --profile <p>        # assumed role
aws configure get credential_process --profile <p>   # external provider
```

| Mechanism | Expiry behaviour | The fix |
|---|---|---|
| **SSO — `sso_session`** (modern) | Expires, typically hours | `aws sso login --profile <p>` |
| **SSO — `sso_start_url`** (legacy) | Same | `aws sso login --profile <p>` |
| **Static keys** (`AKIA…`) | **Do not expire.** An error means deactivated, deleted, or wrong | New keys in the IAM console. **Never suggest `aws sso login`** |
| **Assumed role** (`role_arn` + `source_profile`) | Expires with the source | Refresh the *source* profile, by its own mechanism |
| **`credential_process`** | Depends on the external tool | Point at that tool; do not guess at it |

Getting this wrong is worse than saying nothing. `aws sso login` to someone on static keys produces a
confusing error and sends them looking in the wrong place.

## Several profiles is the normal case

Founders routinely have five or six, spanning accounts and regions.

```bash
aws configure list-profiles
aws configure get region --profile <p>
```

`default` is a default, not a choice. If more than one profile exists, name what you are about to use and
which account it points at, and let them redirect in one word. The cost of picking wrong is an agent
investigating the wrong environment.

## Two things specific to the AWS Startup Advisor IDE extension

Only relevant if the user also has the extension installed.

**The extension and the CLI do not accept the same profiles.** Startup Advisor's sign-in supports IAM
Identity Center with a `sso_start_url`, a CLI profile, or manually-entered keys. Profiles using the modern
**`sso_session`** form appear in its dropdown and fail when selected. The AWS CLI handles both forms
without trouble.

So a founder can have working credentials here while the extension's panel shows nothing — and the reverse.
If they say the panel is empty but the preflight succeeded, that is the likely cause, and it is not
something they did wrong. Say so; do not send them round the setup again.

The marker is `aws configure get sso_session --profile <name>` returning a value.

**Startup Advisor's SSO sign-in writes to the shared CLI cache** at `~/.aws/sso/cache/`. If a founder
signed into the extension with Identity Center, a matching CLI profile may already resolve without them
doing anything. Worth checking before asking them to authenticate again.

## Route by intent, not by state

State tells you what is *possible*. Intent tells you what they *want*. Never ask for more access than the
intent requires.

| They want | R2 no credentials | R3 expired | R4 valid | R5 + billing |
|---|---|---|---|---|
| **"What does this cost?"** | Answer fully. List pricing. **Ask for nothing.** | Answer fully | Answer fully | Answer with *their* balance and coverage |
| **"Is this for me?"** | Scan the codebase, assess, advise | same | same, richer | same, plus affordability arithmetic |
| **"Review my PR"** | Explain the path; repo connection needs console access | Offer the refresh, then continue | Proceed | Proceed |
| **"Set it up"** | Walk the credential setup first — it is genuinely the prerequisite | `aws sso login`, then continue | Proceed | Proceed |
| **"Production is down"** | **Help with the incident directly.** Say the agent needs AWS access and offer it as a follow-up | Offer the ten-second refresh, then proceed | Proceed | Proceed |
| **"Turn it off"** | Cannot act. Give them the console path | Refresh, then act | Act | Act |

Two rows carry most of the value.

**"What does this cost?" at R2.** They can have a complete answer with zero authentication. If you make
someone sign in to hear a price, you have told them what kind of product this is.

**"Production is down" at R2.** Do not open a setup flow at someone whose site is down. Help with what is
in front of you, and raise the agent afterwards — when it is a decision rather than an obstacle.

## Say what you found, briefly

One line, so they know why you are asking for whatever comes next:

> "I can see an AWS session for account ending 2340 in us-east-1 — I'll use that unless your workload is
> somewhere else."

Mask the account to the last four. The full identifier adds nothing for the reader and gets copied into
places it should not be.

At R2, say what you cannot see rather than what they must do:

> "I can't see an AWS account from here, so I can't show you your own numbers — but I can tell you what
> this costs and whether it fits."

## R4 is not enough — can they *create the role*?

The R0–R5 ladder answers "do they have working credentials". Setup needs a second question the ladder does
not ask: **can this identity create an IAM role?** The two come apart constantly.

| Sign-in | Typically | Why |
|---|---|---|
| Static keys on a founder's own account | can | usually an admin user |
| **IAM Identity Center permission set** | **often cannot** | permission sets are scoped; read-only and power-user sets have no `iam:CreateRole` |
| `role_arn` assume-role profile | depends | inherits the target role's policy |
| `credential_process` | depends | whatever the external process returns |

Check before promising, rather than failing halfway through setup with a half-created role.

**The caller ARN must be normalised first.** `SimulatePrincipalPolicy` takes an *IAM* ARN, and
`get-caller-identity` returns an *STS session* ARN for anyone using SSO or assume-role — which is exactly
the population this check exists for. Passing it straight through fails with `InvalidInput: Invalid ARN
provided`. Verified.

```bash
CALLER=$(aws sts get-caller-identity --query Arn --output text)
ACCT=$(aws sts get-caller-identity --query Account --output text)

# arn:aws:sts::<acct>:assumed-role/<RoleName>/<session>  ->  arn:aws:iam::<acct>:role/<RoleName>
PRINCIPAL=$(printf '%s' "$CALLER" | sed -E "s#arn:aws:sts::[0-9]+:assumed-role/([^/]+)/.*#arn:aws:iam::${ACCT}:role/\1#")

aws iam simulate-principal-policy --policy-source-arn "$PRINCIPAL" \
  --action-names iam:CreateRole iam:AttachRolePolicy aidevops:CreateAgentSpace \
  --query 'EvaluationResults[].{Action:EvalActionName,Decision:EvalDecision}' --output table
```

Observed output for a scoped permission set with `aidevops:*` but no IAM write:

```
|  iam:CreateRole            |  implicitDeny  |
|  iam:AttachRolePolicy      |  implicitDeny  |
|  aidevops:CreateAgentSpace |  allowed       |
```

That is the diagnosis to act on: **they can use DevOps Agent, they just cannot do the one-time IAM
setup.** Those are different problems with different fixes, and conflating them sends a founder to the
wrong place.

**Attempt-and-handle is the reliable fallback**, and often the only option — many scoped identities cannot
call `SimulatePrincipalPolicy` either. The denial is unambiguous and names the action and resource:

```
An error occurred (AccessDenied) when calling the CreateRole operation:
User: arn:aws:sts::<acct>:assumed-role/<Role>/<session> is not authorized to
perform: iam:CreateRole on resource: arn:aws:iam::<acct>:role/DevOpsAgentRole-AgentSpace
```

Parse the action out of that and say which one was denied. Never report a generic "permissions problem".

### What to say when they cannot create the role

Do **not** route them to the console — a console cannot grant permissions the identity does not have.
Give them something forwardable instead:

> "Your credentials are fine — you just don't have IAM write access on this account, which is normal on
> an Identity Center permission set. Someone with IAM rights needs to create one role, once. Send them
> this: role name `DevOpsAgentRole-AgentSpace`, the trust policy in `connecting.md`, and the managed
> policy `arn:aws:iam::aws:policy/AIDevOpsAgentAccessPolicy`. It takes about two minutes. Once it exists,
> send me the role ARN and I'll do the rest — you already have the permissions for that part."

That last clause matters and is verified: a scoped identity with `aidevops:*` can create the Agent Space
and associate the account. Only the IAM role needs someone else.

## R2 in the IDE: Startup Advisor sign-in is a real credential path

If the user is in an IDE with the AWS Startup Advisor extension and you hit **R2 (no credentials)** or
**R3 (expired)**, offer this before any CLI instructions. It is usually the fastest route, and it is more
than a coincidence of caching.

Signing in to the panel with **IAM Identity Center** does three things:

1. Runs the full SSO device flow, including account and role selection.
2. **Writes a named profile into `~/.aws/config`.**
3. Stores the token through the standard AWS SDK token provider, which uses `~/.aws/sso/cache/` — the same
   location the AWS CLI reads.

So afterwards there is a **working, authenticated CLI profile** that did not exist before. That is the
credential this skill needs.

> "Quickest path: sign in to the AWS Startup Advisor panel in your IDE. It creates an AWS profile and
> signs it in, so the CLI — and everything I need to do here — can use it straight away. Then tell me the
> profile name and I'll pick it up."

**Ask which profile, or detect it.** The panel creates a *named* profile; it does not necessarily become
the default. If `aws sts get-caller-identity` still fails afterwards, the profile exists but is not
selected:

```bash
aws configure list-profiles
AWS_PROFILE=<name> aws sts get-caller-identity      # confirm, then keep using it
```

Two limits, so do not oversell it:

- **Only the Identity Center path creates anything.** Signing in with a static profile is *selecting* a
  profile already on disk — nothing new is created, and if the CLI could not authenticate before, it still
  cannot.
- **Do not assume they have the extension.** Offer this when you can see you are in a supported IDE, or
  when they mention it. Otherwise give the normal remediation.

**Never make it a precondition.** It is the fastest path, not a gate — the cost conversation still happens
without any credentials at all.

> **Tested 2026-08-13, in two halves.**
>
> *Cached token → CLI: verified.* On a machine with SSO profiles and a populated `~/.aws/sso/cache/`,
> `AWS_PROFILE=<name> aws sts get-caller-identity` authenticated immediately, no `aws sso login`. So once a
> profile exists and its token is cached, this skill has working credentials. That is the half the guidance
> above depends on.
>
> *Panel → profile: not yet exercised end to end.* If `aws sts get-caller-identity` still fails after a
> panel sign-in, fall back to `aws sso login --profile <name>`.

## Detecting whether an Agent Space exists

You can just look — this is not something to ask about:

```bash
aws devops-agent list-agent-spaces --region <region>
```

Empty list means none, and creating one is a single call (`references/connecting.md`).
`AccessDeniedException` means an IAM gap on `aidevops:*`, which is a different conversation from "not set
up" — say which action was denied.

## What you cannot detect, and must therefore ask

Be honest about the edges rather than guessing:

- **Whether they are signed into the AWS console.** Only needed now for minting a bearer token; Agent
  Space creation does not require it. Ask at the point it matters, not before.
- **Whether the AWS Startup Advisor extension is signed in.** A different surface, invisible from here —
  but worth knowing about, because for SSO users it is a shortcut. See above.
- **Whether the credentials point at the right account.** `get-caller-identity` gives you *an* account, not
  confirmation it is the one their workload runs in. If a founder mentions multiple accounts or
  environments, confirm before connecting — an agent investigating the wrong environment is worse than one
  that has not started.

## Re-check, do not remember

Sessions expire mid-conversation. If something fails partway through with an expired-token signature, that
is R3 arriving late — offer the refresh and resume, rather than restarting the flow or reporting a fault.
