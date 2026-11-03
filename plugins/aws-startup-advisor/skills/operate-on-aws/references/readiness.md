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

**Optional discovery never blocks.** Billing, credits, historical usage, and trial checks are optional
discovery. Use current credentials if available; never request added billing permissions or a sign-in
solely for these checks. Failure does not block the combined approval or provisioning. AWS credentials and
IAM writes required for the actual approved setup remain mandatory. Do not equate inability to list an
existing Agent Space with proof that none exists; resolve duplicate risk safely when creation is attempted.

State tells you what is *possible*. Intent tells you what they *want*. Never ask for more access than the
intent requires.

| They want | R2 no credentials | R3 expired | R4 valid | R5 + billing |
|---|---|---|---|---|
| **"What does this cost?"** | Answer fully. List pricing. **Ask for nothing.** | Answer fully | Answer fully | Answer with *their* balance and coverage |
| **"Is this for me?"** | Scan the codebase, assess, advise | same | same, richer | same, plus their balance and coverage |
| **"Review my PR"** | Explain the path; repo connection needs console access | Offer the refresh, then continue | Connected: review. Not set up: ask first | Connected: review. Not set up: ask first |
| **"Set it up"** | Show the combined notice and ask first; after a Yes, walk the credential setup — it is genuinely the prerequisite | Ask first; after a Yes, `aws sso login`, then continue | Ask, then proceed on Yes | Ask, then proceed on Yes |
| **"Production is down"** | **Help with the incident directly.** Say the agent needs AWS access and offer it as a follow-up | Offer the ten-second refresh, then help | Connected: investigate. Not set up: help, and ask before setup | Connected: investigate. Not set up: help, and ask before setup |
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

## Can this sign-in do setup?

The R0–R5 ladder answers "do they have working credentials". Setup needs a second question the ladder does
not ask: **can this sign-in do every setup step?** The two come apart constantly. Ask it in ACCESS, before
the setup question, and never fail halfway through setup with a half-created role.

| Sign-in | Typically | Why |
|---|---|---|
| Static keys on a founder's own account | can | usually an admin user |
| **IAM Identity Center permission set** | **often cannot** | permission sets are scoped; read-only and power-user sets have no `iam:CreateRole` |
| `role_arn` assume-role profile | depends | inherits the target role's policy |
| `credential_process` | depends | whatever the external process returns |

### What setup needs

These are the calls SET UP and CONNECT make (`references/connecting.md`), and nothing else:

| Step | Actions |
|---|---|
| Create the access role and its one inline permission | `iam:CreateRole`, `iam:GetRole`, `iam:PutRolePolicy` |
| Attach `AIDevOpsAgentAccessPolicy` to it | `iam:AttachRolePolicy` |
| Let DevOps Agent use the role | `iam:PassRole` |
| DevOps Agent's own service-linked role, created with the first Agent Space | `iam:CreateServiceLinkedRole` |
| Find and create the Agent Space, and connect the AWS account | `aidevops:ListAgentSpaces`, `aidevops:GetAgentSpace`, `aidevops:CreateAgentSpace`, `aidevops:AssociateService`, `aidevops:ListAssociations` |
| Tag the space as created by AWS Startup Advisor (optional: without it the space is created untagged) | `aidevops:TagResource` |
| Read back what is already done, when checking again after a fix | `iam:ListAttachedRolePolicies`, `iam:GetRolePolicy`, `aidevops:ListTagsForResource` |

### Check, read-only

**The caller ARN must be normalised first.** `SimulatePrincipalPolicy` takes an *IAM* ARN, and
`get-caller-identity` returns an *STS session* ARN for anyone using SSO or assume-role — which is exactly
the population this check exists for. Passing it straight through fails with `InvalidInput: Invalid ARN
provided`. Verified.

```bash
CALLER=$(aws sts get-caller-identity --query Arn --output text)
ACCT=$(aws sts get-caller-identity --query Account --output text)

# arn:aws:sts::<acct>:assumed-role/<RoleName>/<session>  ->  arn:aws:iam::<acct>:role/<RoleName>
PRINCIPAL=$(printf '%s' "$CALLER" | sed -E "s#arn:aws:sts::[0-9]+:assumed-role/([^/]+)/.*#arn:aws:iam::${ACCT}:role/\1#")

# The values the setup-only policy's conditions test (below). Pass all three on both IAM calls: without
# them a sign-in that has that policy still reads as implicitDeny, and the simulator lists any key a policy
# tests but the call left out as missing, even for an action the key does not apply to.
CTX=(
  ContextKeyName=iam:PolicyARN,ContextKeyValues=arn:aws:iam::aws:policy/AIDevOpsAgentAccessPolicy,ContextKeyType=string
  ContextKeyName=iam:PassedToService,ContextKeyValues=aidevops.amazonaws.com,ContextKeyType=string
  ContextKeyName=iam:AWSServiceName,ContextKeyValues=aidevops.amazonaws.com,ContextKeyType=string
)
Q='EvaluationResults[].{Action:EvalActionName,Decision:EvalDecision,Missing:MissingContextValues}'

# The Region setup will use, and the space: its id once it exists, otherwise any space in this account
# and Region (a policy that names specific spaces then reads as implicitDeny: unknown, not denied).
REGION="<region>"
SPACE="arn:aws:aidevops:${REGION}:${ACCT}:agentspace/${SPACE_ID:-*}"

# Separate calls, so each action is checked against the resource it really touches.
aws iam simulate-principal-policy --policy-source-arn "$PRINCIPAL" \
  --action-names iam:CreateRole iam:GetRole iam:PutRolePolicy iam:AttachRolePolicy iam:PassRole \
  --resource-arns "arn:aws:iam::${ACCT}:role/DevOpsAgentRole-AgentSpace" \
  --context-entries "${CTX[@]}" --query "$Q" --output json

aws iam simulate-principal-policy --policy-source-arn "$PRINCIPAL" \
  --action-names iam:CreateServiceLinkedRole \
  --resource-arns "arn:aws:iam::${ACCT}:role/aws-service-role/aidevops.amazonaws.com/AWSServiceRoleForAIDevOps" \
  --context-entries "${CTX[@]}" --query "$Q" --output json

aws iam simulate-principal-policy --policy-source-arn "$PRINCIPAL" \
  --action-names aidevops:ListAgentSpaces aidevops:CreateAgentSpace \
  --query "$Q" --output json

aws iam simulate-principal-policy --policy-source-arn "$PRINCIPAL" \
  --action-names aidevops:GetAgentSpace aidevops:TagResource aidevops:AssociateService aidevops:ListAssociations \
  --resource-arns "$SPACE" --query "$Q" --output json
```

Observed for a scoped permission set with `aidevops:*` but no IAM write (trimmed):

```
iam:CreateRole              implicitDeny
iam:AttachRolePolicy        implicitDeny
aidevops:CreateAgentSpace   allowed
```

That is the diagnosis to act on: **they can use DevOps Agent, they just cannot do the one-time IAM
setup.** Those are different problems with different fixes, and conflating them sends a founder to the
wrong place.

- **Every action `allowed`** → nothing to tell them. Continue to the setup question.
- **`implicitDeny` with a `Missing` key that starts with `aws:`, `iam:` or `aidevops:`** → unknown for
  that action, not denied: one of their own policies tests a condition this check cannot supply (for example
  `aws:MultiFactorAuthPresent`). Treat it like a check that cannot run. Ignore missing keys for other
  services: AWS's `ReadOnlyAccess` tests `s3express:SessionMode`, which lists it as missing on every result
  without affecting these actions.
- **A space action (`GetAgentSpace`, `AssociateService`, `ListAssociations`) not `allowed` before the space
  exists** → unknown: the check could only name any space, and their policy may name the one setup creates.
  Handle a denial when it happens (below).
- **`aidevops:TagResource` not `allowed`** → nothing to tell them: tagging is optional, and setup creates the
  space without the tag (`references/connecting.md`). Never stop or ask for permissions over it.
- **The check itself is denied** (many scoped sign-ins cannot call `SimulatePrincipalPolicy`) → that is
  unknown, not a failure. Continue, and handle a denial when it happens (below).
- **Anything else** (`explicitDeny`, or `implicitDeny` with no such key missing) → tell them, in plain English,
  before the setup question:

> "Your AWS sign-in can't finish DevOps Agent setup: it isn't allowed to create the access role
> DevOps Agent uses. Only setup needs this, once."

Name what is missing in words first, then the action names. Never report a generic "permissions problem".

**Attempt-and-handle is the reliable fallback** when the check cannot run. The denial is unambiguous and
names the action and resource:

```
An error occurred (AccessDenied) when calling the CreateRole operation:
User: arn:aws:sts::<acct>:assumed-role/<Role>/<session> is not authorized to
perform: iam:CreateRole on resource: arn:aws:iam::<acct>:role/DevOpsAgentRole-AgentSpace
```

Parse the action out of that, say which one was denied, and offer the same fix.

### The fix: a setup-only policy, not administrator access

Grant exactly the actions above, scoped to the roles setup creates and the one managed policy it attaches.
Never suggest `AdministratorAccess`, `IAMFullAccess` or a wildcard to get past a denial.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateTheDevOpsAgentRole",
      "Effect": "Allow",
      "Action": ["iam:CreateRole", "iam:GetRole", "iam:PutRolePolicy"],
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/DevOpsAgentRole-*"
    },
    {
      "Sid": "ReadBackTheDevOpsAgentRole",
      "Effect": "Allow",
      "Action": ["iam:ListAttachedRolePolicies", "iam:GetRolePolicy"],
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/DevOpsAgentRole-*"
    },
    {
      "Sid": "AttachOnlyTheDevOpsAgentPolicy",
      "Effect": "Allow",
      "Action": "iam:AttachRolePolicy",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/DevOpsAgentRole-*",
      "Condition": { "ArnEquals": { "iam:PolicyARN": "arn:aws:iam::aws:policy/AIDevOpsAgentAccessPolicy" } }
    },
    {
      "Sid": "PassTheRoleToDevOpsAgent",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/DevOpsAgentRole-*",
      "Condition": { "StringEquals": { "iam:PassedToService": "aidevops.amazonaws.com" } }
    },
    {
      "Sid": "DevOpsAgentServiceLinkedRole",
      "Effect": "Allow",
      "Action": "iam:CreateServiceLinkedRole",
      "Resource": "*",
      "Condition": { "StringEquals": { "iam:AWSServiceName": "aidevops.amazonaws.com" } }
    },
    {
      "Sid": "SetUpDevOpsAgent",
      "Effect": "Allow",
      "Action": [
        "aidevops:ListAgentSpaces", "aidevops:GetAgentSpace", "aidevops:CreateAgentSpace",
        "aidevops:TagResource", "aidevops:AssociateService", "aidevops:ListAssociations",
        "aidevops:ListTagsForResource"
      ],
      "Resource": "*"
    }
  ]
}
```

Who can add it depends on the sign-in, and **nothing is added without the user's explicit Yes** — the
setup question covers it when it is part of setup (SKILL.md CONFIRM):

- **They have another sign-in with IAM rights for this AWS account** (an admin profile, often the person
  who opened the account): add it with that profile as an inline policy named
  `AWSStartupAdvisorDevOpsAgentSetup`, on the IAM user (`put-user-policy`) or role (`put-role-policy`) the
  normal sign-in uses. Then run the check again with the normal sign-in.
- **IAM Identity Center** (`AWSReservedSSO_*` roles): the role cannot be edited directly. The policy goes
  into the permission set as an inline policy, by someone who manages Identity Center. That is the
  administrator note below.
- **No one at hand with IAM rights**: give them the administrator note and stop. Do not ask the setup
  question until the check passes.

The policy is only for setup. Once setup is done they can remove it; using DevOps Agent afterwards does not
need it.

### The note for their AWS administrator

Do **not** route them to the console — a console cannot grant permissions the sign-in does not have. Give
them this to send, filled in, with the policy above:

> "I'm setting up AWS DevOps Agent in AWS account `<ACCOUNT_ID>` for incident investigation. My sign-in
> `<CALLER ARN>` can't create the access role it needs. Could you add the attached setup-only policy to it
> (for IAM Identity Center, as an inline policy on my permission set)? It allows only the setup steps:
> creating the `DevOpsAgentRole-*` role with AWS's `AIDevOpsAgentAccessPolicy`, and creating the DevOps
> Agent workspace. It isn't administrator access, and it can be removed once setup is done."

If they would rather the administrator create the role, offer the shorter alternative: role name
`DevOpsAgentRole-AgentSpace`, the trust policy and the inline `AllowCreateServiceLinkedRoles` permission in
`connecting.md`, and the managed policy `arn:aws:iam::aws:policy/AIDevOpsAgentAccessPolicy` — about two
minutes. Ask them to also let the normal
sign-in read the role (`iam:GetRole`, `iam:ListAttachedRolePolicies` and `iam:GetRolePolicy` on
`DevOpsAgentRole-*`), so the check can confirm it is complete. Once it exists, they send you the role ARN and
you do the rest. That is verified: a scoped sign-in with `aidevops:*` can create the Agent
Space and connect the AWS account. Only the IAM role needs someone else.

### Checking again after a fix

When they come back, check again before the first write. Do not rerun the whole check: an administrator
may have done part of setup, and a sign-in that is not allowed to repeat a finished step would fail it for
nothing. First find out what is already done, read-only:

| Already done? | Read-only check | If done, drop |
|---|---|---|
| The access role exists | `aws iam get-role --role-name DevOpsAgentRole-AgentSpace` | `iam:CreateRole` |
| `AIDevOpsAgentAccessPolicy` is attached | `aws iam list-attached-role-policies --role-name DevOpsAgentRole-AgentSpace` | `iam:AttachRolePolicy` |
| The inline permission is there | `aws iam get-role-policy --role-name DevOpsAgentRole-AgentSpace --policy-name AllowCreateServiceLinkedRoles` | `iam:PutRolePolicy` |
| The service-linked role exists | `aws iam get-role --role-name AWSServiceRoleForAIDevOps` | `iam:CreateServiceLinkedRole` |
| The Agent Space exists | `aws devops-agent list-agent-spaces --region <region>`: the one tagged `CreatedBy=aws-startup-advisor` (`list-tags-for-resource`), or the one they already had | `aidevops:CreateAgentSpace`, `aidevops:TagResource` |
| The AWS account is connected | `aws devops-agent list-associations --agent-space-id <id> --region <region>` shows an `aws` association | `aidevops:AssociateService`, `iam:PassRole` |

A read that is denied or fails is unknown. For the role's two policies, settle it before checking, because
a sign-in that cannot read them usually cannot write them either, and would be told to fix a role that is
already complete:

1. If a sign-in with IAM rights is at hand (the administrator profile that made the fix), run the same read
   with it and use what it shows.
2. If the administrator created the role themselves (the shorter alternative above) and said it has the
   managed policy and the inline permission, count both as done.
3. Otherwise keep the step. A policy that is really missing still needs setup.

Then run the check above with only the actions for the steps left, and `SPACE_ID` set to the space's id once
it exists. If an administrator created the role with the managed policy, that is `iam:PassRole` and the
`aidevops` actions still to do, not `iam:CreateRole` or `iam:AttachRolePolicy`. Tagging is never a step left:
a space that exists untagged stays untagged.

The same rules apply. If `SimulatePrincipalPolicy` itself is denied, that is unknown: continue, and stop
only on an actual `AccessDenied` from a setup call. Continue from the first step not done; never repeat
one that is.

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

You can just look — this is not something to ask about. Check **every** region DevOps Agent runs in, the
user's region first if it is one of them, and keep a failed lookup separate from an empty one:

```bash
supported="us-east-1 us-east-2 us-west-2 ca-central-1 sa-east-1 ap-south-1 ap-southeast-1 \
           ap-southeast-2 ap-northeast-1 ap-northeast-2 eu-central-1 eu-west-1 eu-west-2 eu-west-3 eu-north-1"
mine=<their-region>
case " $supported " in
  *" $mine "*) regions="$mine ${supported/$mine/}" ;;   # theirs first, if DevOps Agent runs there
  *)           regions="$supported" ;;                 # otherwise skip it: no space can live there
esac
for r in $(echo "$regions"); do   # works in bash and zsh
  if out=$(aws devops-agent list-agent-spaces --region "$r" --query 'agentSpaces[].name' --output json 2>&1); then
    flat=$(echo "$out" | tr -d '\n')
    if [ "$flat" = "[]" ]; then echo "$r: empty"; else echo "$r: FOUND $flat"; fi
  else
    echo "$r: UNKNOWN — $(echo "$out" | tr -d '\n')"
  fi
done
```

The list is the regions in
[Supported Regions](https://docs.aws.amazon.com/devopsagent/latest/userguide/about-aws-devops-agent-supported-regions.html)
(15 as of October 2026). AWS adds regions over time, so check that page if a region seems missing. One region is never enough: an empty answer from one says
nothing about the others, and the founder's default region is often not where their space was created.
A default region DevOps Agent does not run in is skipped, not checked — a space there is impossible, and
a space in a supported region still monitors workloads in every region.

Read the result in this order. `FOUND` is decided by whether the list has entries, not by what the
spaces are called, so a space with any name — even `none` — is found:

- **`FOUND` in any region** — say where and use it: *"You already have an Agent Space, `<name>`, in
  us-east-1 — I'll use that one."* See the release-review exception below.
- **Any region `UNKNOWN`** — do not conclude there is no space. The error is the readiness state for that
  region (expired, denied, throttled, unreachable). This does **not** hold back the approval question:
  ask it anyway. Before creating anything, retry, check the intended region and any locally configured
  space, or use a known space ID. Creating a space while a region is unknown is how a founder ends up with
  two — if it stays unresolved, say what is unknown and offer a targeted next step.
- **`empty` in every region, with no `UNKNOWN`** — there is no Agent Space. Creating one is a single call
  (`references/connecting.md`).

**Release review runs only in `us-east-1` during preview.** Investigations, prevention evaluations and
chat work in every supported region, so reuse the space wherever it is for those. For a release review,
reuse it only if it is in `us-east-1`. If it is elsewhere, say so, explain that release review needs a
space in `us-east-1`, and let the founder decide whether to add one there — that second space is a
deliberate choice, not a duplicate.

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
