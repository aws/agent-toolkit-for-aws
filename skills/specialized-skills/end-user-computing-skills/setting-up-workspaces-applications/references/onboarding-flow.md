# Guided Onboarding — from a described workflow to a recommended configuration

The adaptive question flow for setting up an agent's environment. Ask in natural language, recommend from the answers, and let the user override anything. The deliverable is a **recommended configuration plus an environment summary** — provisioning happens only in create-workspace.md, after explicit confirmation.

Behavior rules (they restate SKILL.md's core principles as they apply here):

- **Adaptive, not a form.** Earlier answers decide which follow-ups to ask. Any question can be skipped — use the stated default and note it in the summary.
- **One question at a time.** Ask, wait for the answer, then ask the next — never send several questions in one message, and never end a message with a stacked list of things you still need. Each answer may make later questions unnecessary; batching throws that away and overwhelms the user.
- **Resolve, don't ask.** Anything discoverable or derivable gets a default you choose and label, not a question: discover the VPC/subnets/security group from the account, generate the agent UserId from the environment name, infer internet access from what the workflow connects to. The user changes any of it at the plan confirmation. Do not end the flow with a batch of open questions — that overwhelms exactly the users this skill exists for.
- **Translate, don't teach.** "How many agents run this workflow at the same time?" — not "what is your fleet's max capacity?"
- **Number every fixed set of answers.** When a question has a small set of sensible answers (agent vs human, app choices, view preference, yes/no confirmations), list them as numbered options in plain text, one per line, so the user can reply with just the number:

  ```
  Who will use this desktop?
  1) An AI agent (default): the agent works on the desktop on its own, and you can watch it. Default, because this guide is built for setting up a desktop for an AI agent first.
  2) People: your users sign in and work on it themselves
  ```

  Don't add a "reply with a number" line; the numbers are enough. Use 2–4 options, each with a one-line plain-language consequence. When a question has a default, list it first, add " (default)" to its label, never "(Recommended)", and end its description with a one-line reason. The sample question and questions that start billing, delete something or pick what the agent runs (the plan confirmation, the sample workflow pick and the cleanup question) have no default. Treat a bare number ("1", "2)") as picking that option, and still accept a free-text answer that doesn't match any option. Don't use the client's option-picker tool: the numbered text is the format everywhere. One question at a time, never a batch. Keep truly open-ended prompts (like "describe the workflow") free-form.
- **No answer is not the default.** Some clients return a question with no answer after a few minutes. Then never pick the default or any other option for the user: end your turn with one line saying you'll wait for their answer, and continue when they reply.
- **Skip what the request already answers.** Follow "Users who give details up front" below.
- **Frame every recommendation as a starting point** the user (or their IT admin) can change later based on real usage.
- **No dollar figures** — qualitative tradeoffs and documented licensing facts only; link the [pricing page](https://aws.amazon.com/workspaces/applications/pricing/) for rates.

## Users who give details up front

Some users, often technical ones, open with most of the setup already decided ("I want 2 xlarge desktops with agent access, Windows Server 2022, in us-east-1"). Don't make them walk the questionnaire. Before asking anything:

1. **Map what they said onto the question flow below.** Each question is answered (they stated it), implied (it follows directly from what they stated), or still open. Examples:
   - "agent access", "for my agent", "computer use" → agent path (Q1)
   - "xlarge", "2xlarge" with no family → `stream.standard.<size>`; "compute", "memory", or "GPU" with a size → that family (Q7)
   - "2 instances", "10 agents at once", "20 users" → concurrency and max capacity (Q6)
   - "always-on", "on-demand" → fleet type (Q5)
   - Named apps → the application list (Q3); a named OS → the platform
   - "full desktop" or "app only" → stream view; timeouts, VPC or subnet IDs, region, or a name → use them as given
   - "my own MCP servers" or "tool forwarding" → `FORWARD_MCP_TOOLS` (Q9)
   - "save screenshots", "screenshot bucket", or a bucket name → screenshot storage (Q10)
   - "have the agent install the apps" or "I'll install them myself" → who installs (Q3)
2. **Confirm in one line, then continue.** For example: "Got it: an AI agent, 2 concurrent sessions on stream.standard.xlarge, agent access on." Then go straight to the next open question. Don't announce that you're skipping questions, and never mention question numbers ("the first question", "now for the second"). Name any implied readings in that line ("xlarge as stream.standard.xlarge") so they can correct them.
3. **Skip answered and implied questions; ask only the open ones**, one at a time, in the usual order. Skip the sample question when they've described their own setup, which any stated configuration does, and don't mention the sample. Skip the free-form workflow description when they've already said what goes on the desktop. Once the apps are known, don't ask follow-up questions about the workflow's details (where its data lives, what each app is for, how big its files are) or about network access: size from the apps and the number of agents, and list the rest under "defaults chosen for you". If the applications are still unknown, ask for them directly ("Which applications need to be on the desktop?").
4. **Use their values as given.** They override the recommendations; don't re-argue them. The one exception is a value the API or agent access rejects (a Linux platform or multi-session with agent access, `DisconnectTimeoutInSeconds: 0`, a GPU family with no quota). Say so in one line and offer the nearest valid value.
5. **Fill everything else with the usual defaults**, listed under "defaults chosen for you" as normal. If nothing is open, go straight to the plan.
6. **Match their vocabulary.** If they say "fleet" and "stack", use those words back. The plain-language rule is for users who don't.

Everything after the questions is unchanged: one plan, one explicit yes, and nothing is created before it.

## Question flow

1. **Agent or human users?** Ask it as worded in SKILL.md (First questions). Branches the questions below: agent-only steps are marked (A), human-only (H). If the conversation surfaces complex-enterprise needs (SAML/SSO, domain join, Elastic/multi-session, GPU-for-humans), route that part to the docs per SKILL.md's gate — don't guess.
1b. **(A) Own workflow or sample?** Ask it exactly as worded in SKILL.md (First questions): the question, the sample description with its three workflows, then the options **1) Use a sample application and workflow** and **2) Use my own application and workflow**, in that order, with no label on either. Skip it when the request already describes their own setup. On **1**, follow [sample-workflows.md](references/sample-workflows.md): the sample path skips the next two questions and uses a pre-built application, data set, and workflow, and the user picks which workflow to run once the desktop is ready. On **2**, continue with question 2 below. There is only one sample, so don't ask which one.

2. **Describe the workflow / use case** (free-form). Seeds everything: applications, OS, sizing, schedule. No jargon required from the user.
3. **Applications needed.** Suggest from the description (e.g. "Excel report" → spreadsheet software), let the user confirm and add. Surface licensing implications inline — Microsoft 365 apps require a customer-procured license eligible for unattended use for agent setups; see [fleet-stack-recommendations.md § OS & licensing](references/fleet-stack-recommendations.md). The application list becomes the image-requirements section of the summary. If any application isn't on the public base image, a custom image is needed. For people, Office, Visio and Project can be licensed through AWS instead of installed from the user's own copy. Offer that when they name one, with its monthly charge for every user of the fleet (image-setup.md, License-included applications). For each other application that isn't on the base image, ask where its installer comes from, as in image-setup.md (Installer sources). For agents, ask next who installs the applications, exactly like this:

   ```
   Who should install the applications on the image?
   1) An AI agent (default): it connects to an image builder, installs and tests each app, and you can watch it. Default, because it saves you the manual installs.
   2) Me: I install them in a browser session, from steps you write for me
   ```

   What each answer means for the build is in [image-setup.md](references/image-setup.md). For people, the user installs, so don't ask.
4. **Contextual follow-ups** driven by the description — e.g. typical file sizes (→ memory sizing), external systems the workflow must reach such as a database host or web mail (→ internet-access and security-group defaults). Skippable.
5. **Fleet type — defaulted, not asked.** Default `ALWAYS_ON` (instant sessions, simplest first experience) and list it under "defaults chosen for you" with the billing tradeoff. Offer `ON_DEMAND` as a swap only when the description clearly implies scheduled/batch runs with idle gaps, or the user raises cost — see [fleet-stack-recommendations.md § Fleet type & scaling](references/fleet-stack-recommendations.md). Warm-capacity and scaling values follow from the same section; no separate question.
6. **Concurrency.** "How many agents run at the same time?" / "How many people stream at peak?" → max capacity (1 instance = 1 concurrent session). Warn that undersizing produces insufficient-capacity errors at peak. If the answer isn't a whole number ("a few"), ask again for one. Once the instance type is known, read its quota as in [fleet-stack-recommendations.md § Fleet type & scaling](references/fleet-stack-recommendations.md). If the answer is above it, plan the quota instead and say why in one line, with how to ask for more.
7. **Instance and storage.** Recommend from the workflow profile; default storage 200 GB (root volume configurable 200–500 GB). Allow manual override; warn if the override looks undersized for the described workload.
8. **Session timeouts.** Apply the persona defaults (see [fleet-stack-recommendations.md § Session timeouts](references/fleet-stack-recommendations.md)). For agents, don't ask how long a run takes — new users can't know before they've tested one. Default the run cap (`MaxUserDurationInSeconds`) to 14400 (4 hours): generous on purpose, because a run killed at the cap terminates mid-task, while the idle timeout (15 min of no input) is what actually catches stuck agents. If the workflow description clearly implies longer (e.g. an all-day batch), scale the cap up to ~4× the implied duration. List it under "defaults chosen for you" with the note "we'll right-size this after your first runs" — it's changeable anytime with `UpdateFleet`.
9. **(A) Your own MCP tools?** "Does your agent need tools from your own MCP servers available on the desktop (e.g. filesystem, internal APIs)?" If yes → set `FORWARD_MCP_TOOLS: ENABLED` in the agent-access defaults and add the servers and their manifest to the image requirements ([image-setup.md](references/image-setup.md), MCP servers for tool forwarding). If no or unsure → leave DISABLED (it can be enabled later with a stack update).
10. **(A) Save the agent's screenshots?** Ask it whenever the request hasn't answered it, including for users who gave details up front. It's a question, never a silent default. Fill in `<account>` from `aws sts get-caller-identity` and `<region>` from the Region the user named or, if they didn't name one, the Region the CLI resolves to (`aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text`, which also sees `AWS_REGION`). Don't guess a Region: if none resolves, ask which one to use. Then ask it exactly like this:

    ```
    Do you want to save the screenshots your agent takes? They go to an S3 bucket in your account, so you can check the agent's work later.

    1) Create a new bucket (default): workspaces-agent-screenshots-<account>-<region>, or send a different name. Default, because it keeps a record of the agent's work.
    2) Use a bucket I already have
    3) Don't save screenshots
    ```

    What the answer puts in the plan:
    - **1:** the bucket and its policy, listed as the first thing created, because the stack names the bucket.
    - **2:** the change to their bucket's policy. Check the bucket before writing the plan.
    - **1 or 2:** what the agent's IAM identity needs to save screenshots: `s3:PutObject` on `arn:aws:s3:::<bucket>/agentaccess/screenshots/*`, plus `kms:GenerateDataKey` if the bucket uses a customer managed KMS key.

    For the existing-bucket checks, the policy and the create commands, read the screenshot storage section of [agent-access-config.md](references/agent-access-config.md). The answer sets `S3BucketArn` and `ScreenshotsUploadEnabled` on the stack and, when an agent builds the image, on the image builder.

11. **(H) Who gets access?** Collect the user list (email addresses) for user-pool creation — see [user-access.md](references/user-access.md). After that answer, ask **(H) App or desktop view?** as its own question — see the persona notes in fleet-stack-recommendations.md.
12. **Name.** Generate a readable default (e.g. `invoice-reconciliation`). Explain: the resource `Name` is immutable; the `DisplayName` is changeable.
13. **Defaults applied silently** (all changeable later): for agents, the agent-access policy set (vision + input, `UserControlMode: VIEW_STOP`), `StreamView: DESKTOP` (must be set explicitly — the API default is `APP`), application settings persistence off. For humans: no `AgentAccessConfig`, the chosen stream view, persistence off for the POC shape. See [fleet-stack-recommendations.md](references/fleet-stack-recommendations.md).

## Output: the environment summary

End the flow by rendering a single markdown summary the user can review, and paste to whoever provisions or builds the image:

- **Configuration table** — every recommended value with a one-line rationale ("ON_DEMAND: runs unattended at night, tolerates startup latency").
- **Image requirements** — OS/platform, the application list with licensing notes, who installs them (an agent or the user), and (if forwarding was requested) the MCP servers to install.
- **Licensing notes** — documented facts only (RDS SAL on Windows Server; Microsoft 365 unattended licensing), with the pricing page linked for rates.
- **Defaults chosen for you** — values the flow resolved on the user's behalf, each with what was picked and a plain-language "change it if you want": the discovered VPC/subnets/security group, the generated agent UserId (with the per-UserId monthly fee noted), internet access on or off based on the workflow's destinations, and, if the user chose a screenshot bucket, the permissions the agent's IAM identity will need for it. A non-technical user can accept the whole section with one "looks good"; a technical user can override any single line.
- **Blocking items** — only things that genuinely cannot be defaulted and prevent provisioning (the account has no VPC at all; domain join is required). Most runs should have none. If one exists, explain it in plain language and what resolving it takes — never present it as a bare TODO.

If the user confirms the plan (defaults accepted or adjusted) and no blocking items remain, continue to [create-workspace.md](references/create-workspace.md). The summary is planning output — producing it provisions nothing.

## Boundaries

- **Image setup:** the summary's application list feeds [image-setup.md](references/image-setup.md), which launches the builder. An agent connected to the builder through agent access does the installs and capture, or the user does them in a browser session from steps you write. For trials or standard apps, a public base image skips this entirely.
- **Enterprise network and identity** (VPC/subnet/security-group creation, Active Directory) are owned by the account's admin — the flow discovers and defaults to existing network resources (see create-workspace.md) and treats their complete absence as a blocking item, never creating network infrastructure itself.
- **Connecting to and driving the desktop** — the `amazon-workspaces-agent-access` skill.
