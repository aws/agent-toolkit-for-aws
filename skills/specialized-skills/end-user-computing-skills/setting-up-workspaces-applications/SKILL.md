---
name: setting-up-workspaces-applications
description: Provisions Amazon WorkSpaces Applications (AppStream 2.0) environments, from images and image builders to fleets and stacks, through a guided flow, for an AI agent or for human users. Covers turning a described workflow into configuration (instance type, ALWAYS_ON vs ON_DEMAND, scaling, session timeouts, OS and licensing), custom images (image builder and Image Assistant, with an agent doing the installs through image builder agent access), AgentAccessConfig on stacks and image builders, the screenshot S3 bucket, user-pool access for people, creating, updating and tearing down fleets and stacks with auto scaling, the GnuCash sample desktop, and provisioning errors. Routes SAML/SSO, domain join, entitlements, and Elastic and multi-session fleets to the docs. Use when a user wants to set up a desktop for an agent or for people, try the sample, plan or size the infrastructure, or turn on agent access. Not for connecting an agent to a desktop or image builder; see the amazon-workspaces-agent-access skill.
version: 1
---

# Setting Up Amazon WorkSpaces Applications

Guided provisioning for Amazon WorkSpaces Applications (AppStream 2.0) environments: turn a described workflow into a running fleet + stack without the user learning WorkSpaces taxonomy. This is the **setup** skill: everything about creating and configuring images, image builders, fleets, stacks and their agent access settings. The `amazon-workspaces-agent-access` skill is the **use** skill: connecting an agent to a desktop or an image builder and driving it.

## First questions — who is it for, and does it stay simple?

First check the AWS credentials, as in rule 1 of the Execution model. Then determine three things. If the user's opening message already answers some of them, or other questions in the flow, don't ask them again: follow "Users who give details up front" in onboarding-flow.md.

1. **Agent or human users?** Ask "Who will use this desktop?" with the options "An AI agent" (the agent works on the desktop on its own, and you can watch it) and "People" (your users sign in and work on it themselves). Label it "An AI agent (default)", not "(Recommended)", and end its description with the reason "Default, because this guide is built for setting up a desktop for an AI agent first.", and keep service terms such as user pool or streaming out of the question. If the request already says who the desktop is for, skip the question and say in one line what you took from the request, for example "You said this is for your AI agent, so I'll set it up for an agent." Never mention question numbers or that a question was answered or skipped. Both are supported by the guided flow — the answer branches access method, stack config, and defaults (see the persona notes in the references).
2. **(Agents) Own workflow or a sample?** For an agent, ask this next (question 1b of [onboarding-flow.md](references/onboarding-flow.md)), unless the request already describes their own setup. A request that names any of the configuration, such as instance sizes, counts, fleet type or applications, describes their own setup, so skip the question and don't mention the sample. Ask it exactly like this, in this order, with nothing added to either option label:

   ```
   Do you have a workflow ready that you'd like to test, or would you like to use a sample? You can design a cloud desktop around your own workflow, or set up our sample in your AWS account.

   Our sample is a cloud desktop with GnuCash, a free, open source accounting app, where your agent runs three accounting workflows:
   - Create invoices from customer purchase orders
   - Create registered customers from a customer list CSV
   - Review customer refund requests and apply credits

   1) Use a sample application and workflow
   2) Use my own application and workflow
   ```

   If they pick 1, follow [sample-workflows.md](references/sample-workflows.md).
3. **Does the setup stay simple?** The guided flow covers the get-started/POC shape: Always-On or On-Demand single-session fleet, agent access (agents) or user-pool access (humans), standard networking. If the conversation surfaces any of the following, route that part to the official documentation instead of guessing: **SAML 2.0 / SSO federation and Active Directory domain join** ([Setting Up SAML](https://docs.aws.amazon.com/appstream2/latest/developerguide/external-identity-providers-setting-up-saml.html), [Active Directory tutorial](https://docs.aws.amazon.com/appstream2/latest/developerguide/active-directory-directory-setup.html)), **application entitlements**, **Elastic fleets / app blocks**, **[multi-session fleets](https://docs.aws.amazon.com/appstream2/latest/developerguide/multi-session-recs.html)**, **Google Drive / OneDrive storage connectors**, **PrivateLink streaming endpoints**, **branding / embedded streaming**, and **GPU fleets for human setups** (capacity must be reserved first). Note the API rule that reinforces this split: user-pool users cannot be assigned to stacks whose fleets are domain-joined.

## Core principles

- **Recommend, don't interrogate.** Derive configuration from the workflow description; never make the user set a raw value. Propose, explain why, let them override. When you do ask, ask **one question at a time** — wait for the answer before the next, and never end a message with a stacked list of questions.
- **No WorkSpaces jargon in questions** unless the user uses it first. Ask about the workflow ("how many agents run at once?"), not the infrastructure ("fleet max capacity"). A user who says "fleet" and "xlarge" gets those words back.
- **Never ask what the user already told you.** Map their opening details onto the flow, skip those questions, and ask only what's left.
- **Number every fixed set of answers**, including yes/no confirmations for the plan and for deletes ("1) Yes, create it  2) Change something  3) Not now"), so the user can reply with just a number. Format and rules are in onboarding-flow.md.
- **Recommendations are heuristic starting points**, derived from the described workflow — not validated sizing. Say so. Almost every setting is changeable later; call out the few that aren't (resource `Name` is immutable; GPU vs non-GPU family affects image compatibility).
- **No cost estimates.** Do not compute dollar figures, per-choice cost deltas, or savings estimates. State qualitative tradeoffs ("Always-On bills all running instances even when idle; On-Demand bills while streaming plus a small hourly fee for stopped provisioned instances") and documented licensing facts, and link the [pricing page](https://aws.amazon.com/workspaces/applications/pricing/) for current rates.
- **Resolve, don't ask.** When a value is discoverable from the account or derivable from the conversation — the VPC and subnets (describe calls), the agent UserId (generate from the environment name), internet access (implied by the workflow's destinations) — resolve it yourself and present it in the plan as a chosen default, clearly labeled. The single plan confirmation is where the user changes anything ("I picked your default VPC and subnets in two AZs — say the word if you want different ones"). Never end the flow with a list of open questions. Ask up front only for what is genuinely unknowable and blocking (e.g. the account has no VPC at all, or domain join is required), one thing at a time, with a plain-language explanation of why it's needed.

## Key facts agents get wrong (load the reference before acting)

These are a summary. When you answer a question instead of running the flow, read the reference the routing table names for it first, and give the specifics it lists.

- **`StreamView` defaults to `APP`.** Agent desktops need the full desktop — explicitly set `StreamView: DESKTOP` on `CreateFleet`.
- **`DisconnectTimeoutInSeconds: 0` is rejected.** The accepted range is 60–36000, so 60 is the effective minimum. (`IdleDisconnectTimeoutInSeconds` does accept 0, meaning never disconnect for idle; otherwise 60–36000.) **`MaxUserDurationInSeconds` must exceed the idle timeout** — when the run cap is short (≤ 900s), set idle to 0 and let the cap be the sole guardrail.
- **`ScreenResolution` (agent stacks and image builders only) is the literal string `W_1280xH_720`** — not a `{Width, Height}` object, and the only value the API accepts. It's a field of `AgentAccessConfig`, so it sets the agent's capture resolution; human desktops don't use it (their display is negotiated by the streaming client).
- **Agent access constrains the fleet:** Windows Server platform, `ALWAYS_ON` or `ON_DEMAND` only — Elastic and multi-session fleets are not supported, and VPC endpoints are not supported for agent access.
- **Name Windows Server versions from `describe-images --type PUBLIC`, never from memory.** Its list includes Windows Server 2025, which is easy to leave out. Windows 11 isn't a public base image: it runs only from the customer's own licensed image on dedicated hardware ([bring your own license](https://docs.aws.amazon.com/appstream2/latest/developerguide/byol-windows-images.html)), which this guided setup doesn't cover. When a user needs Windows 11, say so and offer the newest Windows Server base image or a different workflow.
- **Windows Server fleets bill a monthly per-user RDS SAL fee** for each unique user or agent UserId; Linux fleets don't, but they can't take agent access. Bringing your own RDS CALs through Microsoft License Mobility can waive the fee (fleet-stack-recommendations.md).
- **`COMPUTER_INPUT` requires `COMPUTER_VISION`** also ENABLED in `AgentAccessConfig`.
- **Image builders take their own `AgentAccessConfig`.** Set it on `create-image-builder`, or change it with `update-image-builder`, which runs only while the builder is `STOPPED`. Only Windows builders that aren't domain-joined accept it. (details: agent-access-config.md)
- **The `S3BucketArn` bucket must be in the same account and Region** as the stack or builder, and its policy must let `appstream.amazonaws.com` run `s3:ListBucket`, or the create or update call rejects it. `S3BucketArn` is accepted only when `ScreenshotsUploadEnabled` or `ReplaySessionEnabled` is `true`. The managed MCP service uploads the screenshots with the connecting agent's credentials, so the agent's IAM identity needs `s3:PutObject` on the bucket's `agentaccess/screenshots/` prefix. (details: agent-access-config.md)
- **Scaling is not a `CreateFleet` field.** `CreateFleet` sets initial `ComputeCapacity`; min/max and policies are Application Auto Scaling applied separately (see create-workspace.md).
- **No idempotency tokens.** AppStream create operations take no client token — retries must key on the unique resource `Name` and converge on `ResourceAlreadyExistsException`.
- **1 instance = 1 concurrent session** on single-session fleets, and **one active session per `UserId` per fleet** — N concurrent agents need N distinct UserIds, and each unique UserId (or human user) incurs the monthly per-user fee on Windows Server fleets, so reuse the same UserIds from run to run. A person watching an agent's session connects with that agent's UserId.
- **Domain-joined fleets are SAML-only and out of this guided flow** — they can't use streaming URLs or user pools (an API rule), and agent sessions on them additionally require certificate-based auth. Route to the docs.
- **Session scripts live on the image** for Always-On/On-Demand fleets — the `SessionScriptS3Location` API field is Elastic-only (and Elastic doesn't support agent access).
- **No tool copies a file from the user's machine to a desktop or image builder.** An installer that's only on their machine goes to an S3 bucket in their account first, and the image builder reads it with an IAM role set when the builder is created (image-setup.md).
- **Office, Visio and Project can be licensed through AWS** on images for people (`SoftwaresToInstall` on `create-image-builder`), so no installer is needed. Every user of a fleet built from that image is billed for them monthly, whether or not they use them. They can't be used for unattended agent work (fleet-stack-recommendations.md).
- **Each instance type has its own quota per Region**, shared by all the account's fleets of that type. Read it (`service-quotas`, service code `appstream2`) before planning capacity, and never plan more than it allows (fleet-stack-recommendations.md).
- **The streaming user (`PhotonUser`) is not a local administrator**, so an installer that asks for elevation fails inside a session. Software the agent sets up at runtime has to be unpacked into the user profile instead of installed.

## Routing

| User need | Read |
|-----------|------|
| Guide a user from a described workflow to a recommended configuration — the adaptive question flow and its output (the environment summary) | [onboarding-flow.md](references/onboarding-flow.md) |
| Set up the pre-built sample instead of a described workflow — the environment, the plan, rebuilding the sample book and uploading the setup scripts and data that unpack GnuCash and LibreOffice without admin rights — and remove the sample afterwards | [sample-workflows.md](references/sample-workflows.md) |
| After setup, connect an agent and run work on the desktop (optional) | Continue with the `amazon-workspaces-agent-access` skill. This skill doesn't depend on it. |
| The answers→configuration mapping — fleet type (Always-On default, On-Demand as the cost swap), scaling, instance and storage sizing, OS and licensing, session timeouts, default agent-access policy set | [fleet-stack-recommendations.md](references/fleet-stack-recommendations.md) |
| Turn on or change agent access on a stack or an image builder (`AgentAccessConfig` fields, `update-stack`, `update-image-builder`), including Replay Session recording and the computer use interface, and the screenshot bucket: what each answer to the screenshot question needs, creating a new bucket or using an existing one, its policy | [agent-access-config.md](references/agent-access-config.md) |
| Get an image with the workflow's applications — pick a public base image, or launch an image builder where an agent (through image builder agent access) or the user installs the apps, then capture the image with Image Assistant; where installers come from (a download link, or S3 for a file only on the user's machine); license-included Office, Visio and Project; MCP servers for tool forwarding, session scripts and image patching | [image-setup.md](references/image-setup.md) |
| Plan who connects — agent UserId strategy (sessions, observer, per-user billing) or human user-pool users (create, associate, welcome email) | [user-access.md](references/user-access.md) |
| Create, update, or tear down the environment, or finish a partial one — one WorkSpace-level verb orchestrating `CreateFleet` → `CreateStack` (with `AgentAccessConfig`) → `AssociateFleet` → start → auto scaling, with a plan-first review step | [create-workspace.md](references/create-workspace.md) |
| Debug a provisioning failure — `ResourceAlreadyExistsException`, `LimitExceededException` (quotas), insufficient capacity, fleet stuck starting, no usable VPC | [troubleshooting.md](references/troubleshooting.md) |

## Execution model

The only executable code this skill ships is two PowerShell scripts for the sample, [setup-sample.ps1](scripts/setup-sample.ps1) and [stage-sample-data.ps1](scripts/stage-sample-data.ps1). They run on the sample desktop, not on the user's machine (sample-workflows.md). The sample's data files are text in `assets/`. You (the agent) compose and run the AWS CLI/SDK calls yourself, following the sequences in the references. This keeps the skill correct against the live API on whatever CLI/SDK version the user has: if a call is rejected (an unknown field on an older SDK, a constraint violation), read the error, adapt per troubleshooting.md, and continue — do not abandon the sequence. The AWS MCP server is recommended for running these calls (sandboxed execution and audit logging), but it isn't required: every step uses standard AWS CLI syntax.

Three rules when executing:

1. **Plan first, digestibly.** Before any mutating call, present a short plain-language plan — what will be created (fleet, stack, association, auto scaling), in which account/region, on which network, and when billing starts, with a link to the [pricing page](https://aws.amazon.com/workspaces/applications/pricing/) — plus the defaults chosen. Keep it to a screenful; don't print the CLI commands in the plan (the client surfaces each command at execution time anyway). Get explicit confirmation before executing. Nothing is created or billed until the user approves. The plan asks one question, whether to go ahead, so settle every other open choice (an installer source, a bucket name, a size) before showing it, never inside it. Only the plan's yes option, or a reply that plainly approves the whole plan ("go ahead", "yes, build it"), is approval. A reply that answers anything else is not, even when it starts with "yes": act on what it says, show the plan again if that changed it, and ask again. The go-ahead has no default or recommended option, so a reply that hands the choice back ("use your recommendation", "whatever you think") or an empty reply isn't a yes either: ask again, however many times it comes. Finishing a partial setup gets the same full plan and go-ahead as a new one. After any change, show the whole updated plan again, every section as it was first shown and never "everything else stays the same", with the same numbered go-ahead options. A reply that pairs "yes" with anything else (a source, a size, a question) isn't approval either: apply what it says, show the plan again and ask again. The account in the plan is the one the AWS credentials already configured in the environment resolve to (the default profile, or `AWS_PROFILE` when it is set). Do not switch to another profile on your own. Check them before the first question of the flow with one read-only `aws sts get-caller-identity`. If it fails, ask nothing else: say the AWS credentials aren't working and that nothing was changed. If `aws configure list-profiles` lists profiles, ask which one to use. Otherwise say how to set them up (`aws configure`, or `aws configure sso` for IAM Identity Center) and stop.
2. **Converge, don't fail.** Create operations take no idempotency token — on `ResourceAlreadyExistsException`, describe the resource and continue; back off on `ConcurrentModificationException`.
3. **One step at a time, announced.** Don't chain the whole sequence into one shell invocation. Before each step, tell the user in one line what you're about to do and how long it typically takes ("Step 2 of 5: creating the stack with agent access — a few seconds", "starting the fleet — this takes a few minutes"). Run the step, report the result, then move on. For long transitions (fleet → RUNNING), poll with one short `describe-*` call every 15 seconds and report state each time ("fleet is STARTING... now RUNNING with 1 instance available") so nothing ever looks frozen. Never wait longer between polls, even when the transition takes minutes: a longer wait only delays noticing that it finished, and the user sees nothing in between.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference or running a script:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference or script
  via `retrieve_skill` with the `file` parameter (e.g.
  `file="references/sample-workflows.md"` or `file="scripts/setup-sample.ps1"`), and
  use the returned content. Do NOT `file_read` these paths
  locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/setting-up-workspaces-applications/` or
  `~/.claude/skills/setting-up-workspaces-applications/`): Read and run files from the local skill
  directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts, including the environment summary, are always read from and
written to the user's working directory. Never fetch or write customer data through `retrieve_skill`.

## Mutation safety

Creating, updating, or tearing down an environment is **mutating and billable**. Default to read-only (recommend, summarize, plan); gate every create/update/delete behind explicit user confirmation of the reviewed plan, with IAM as the authoritative control. Use the plan-first step in create-workspace.md: a digestible summary of what gets created and when billing starts.

**Deletion gets its own, stricter confirmation.** Before any delete, show exactly what will be destroyed — each resource by name, type, region, and account ("this will permanently delete fleet `email-distiller` and stack `email-distiller` in us-west-2, account 1234...") — state plainly that these are real resources and deletion is not undoable, and wait for an explicit yes to that specific list. A general request like "clean up" or "tear it down" is the start of this exchange, not the confirmation. Never fold a delete into a batch of other commands.

## Security Considerations

- **Least privilege for the control plane.** Creating fleets and stacks and enabling agent access are powerful actions — scope IAM permissions to the specific `appstream` actions the flow performs, and prefer IAM roles over long-lived users.
- **Enable only the agent-access capabilities the workflow needs.** `COMPUTER_INPUT` requires `COMPUTER_VISION`; enable `FORWARD_MCP_TOOLS` only when the user has their own MCP servers on the image (image-setup.md). Default `UserControlMode: VIEW_STOP` so a human can observe and stop the agent (if an older installed CLI/SDK rejects the field client-side, upgrade it — see troubleshooting.md).
- **Screenshots and Replay Session recordings can capture sensitive data.** Keep the bucket private, encrypted at rest and TLS-only, grant the service principal only `s3:ListBucket`, recommend S3 server access logging, and limit who can read it. A recording shows the whole session, typed input included, and `KmsKeyArn` doesn't encrypt what lands in the bucket, so the bucket's default encryption is what protects it (agent-access-config.md).
- **An agent on an image builder works as an administrator, and what it leaves behind ships in the image.** Turn on builder agent access only for the build, install only from sources the user names, and clean up before capture (image-setup.md). Which Windows accounts the agent may use is controlled by the agent's IAM policy, set up with the `amazon-workspaces-agent-access` skill.
- **The environment summary may contain workflow detail** (applications, backend hostnames) — treat it as customer data and write it only to the user's working directory.
- **Redact secrets and personal data before sharing.** Before you collect or share logs, configuration, the environment summary or support-case material, remove API keys, credentials, tokens in URLs (streaming URLs included) and customer PII.
- **Never fabricate infrastructure facts.** Use only the instance types, platforms, and fields documented in the reference files, which mirror the [CreateFleet](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateFleet.html) and [CreateStack](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateStack.html) API references; confirm regional availability against the documentation when precision matters.

**Note:** Instance-type availability, platform versions, and quotas change. When precision matters, confirm against the [CreateFleet API reference](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateFleet.html) and the [Agent Access documentation](https://docs.aws.amazon.com/appstream2/latest/developerguide/agent-access-mcp-server.html).
