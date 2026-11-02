# Phase 3 — MSK Express Load-Test Simulation

Deploy a complete MSK Express load-testing environment in the customer's AWS
account so they can validate Express performance before cutover. The simulation is
**optional** and is the final phase of the skill. Declining at any decision point
ends the skill — there is no subsequent phase.

You orchestrate the conversation and run AWS CLI commands (CloudFormation, SSM,
EC2). The AWS MCP server is recommended for executing these commands but is not
required — the skill works with plain AWS CLI as well. Two deterministic
artifacts do the rest — never hand-compute or hand-edit them:

- [`scripts/simulation_load_test_config.py`](../scripts/simulation_load_test_config.py) — sizing math,
  template rendering, and guardrail validation (`compute`, `render`, and
  `validate` actions).
- [`assets/simulation-stack.yaml`](../assets/simulation-stack.yaml) — a **static**
  parameterized CloudFormation template. It is the internal source: never edit it,
  and never hand the customer its install path. There are two deploy paths:
  - **You deploy it (customer consents):** deploy in one `create-stack` straight
    from this source template, passing the compute-derived `--parameters`. No render.
  - **Customer deploys it themselves (self-guided):** `render` reads this template
    internally and writes a **filled local copy** (the customer's sizing and the
    computed fleet baked in as parameter `Default`s) to the customer's working
    directory; the customer deploys from that local copy with no `--parameters`.
  To resize, redeploy with new parameters (or re-render, on the self-guided path).

## Never expose the skill source path

The customer must never see, depend on, or be told to `cd` into the skill install
directory. You (the agent) run the scripts and — on the consented path — the
`create-stack` from wherever the skill lives, but **nothing you hand the customer**
(a file to keep, a self-guided command, teardown) may name a skill-package path
(anything under the skill directory — `assets/…`, `scripts/…`, or the symlinked
`~/.claude/skills/…`). On the self-guided path, the only template path the customer
sees is the **local rendered artifact** in their working directory (the absolute
`output_path` that `render` reports). The customer should never see or depend on
where the skill is installed.

## Contents

- [Flow](#flow)
- [Confirm the target account](#confirm-the-target-account)
- [Single simulation per account](#single-simulation-per-account)
- [Constrained choices](#constrained-choices)
- [Communicating with the customer](#communicating-with-the-customer)
- [Sizing inputs](#sizing-inputs)
- [Install the Kafka client](#install-the-kafka-client)
- [Env computation](#env-computation)
- [Render the local template](#render-the-local-template)
- [Throughput & fleet reference](#throughput--fleet-reference)
- [Deploy](#deploy)
- [Test templates](#test-templates)
- [Guardrails](#guardrails)
- [Triggering a test](#triggering-a-test)
- [Teardown](#teardown)
- [Off-trail handling](#off-trail-handling)

## Flow

1. Introduce the simulation and what it does; ask consent. **No → end the skill.**
   Mention that only **one simulation can exist per account at a time** (to avoid
   duplicate test costs).
2. Gather the target AWS region. Then **confirm the AWS account** (see
   [Confirm the target account](#confirm-the-target-account)): run
   `aws sts get-caller-identity`, show the account id + role, and ask the customer to
   confirm it is the account they intend to deploy into. **Do not run any
   create/deploy/delete action until the customer confirms the account.** If they say
   it is the wrong account, stop and let them switch credentials first.
3. **Check for an existing simulation** (see [Single simulation per account](#single-simulation-per-account)).
   Only one may exist per account/region. If one already exists, tell the customer
   and ask whether to **reuse** it (present its dashboard, then **verify the Kafka
   client** before tests — see below) or **delete and redeploy** (tear it down and
   wait, then continue). If none exists, continue.
   - On **reuse**, a simulation that is `CREATE_COMPLETE` does **not** guarantee a
     working Kafka client — the client is installed as a post-deploy step, so a
     reused simulation may have an empty `/opt/kafka` (e.g. install never ran, or ran
     against a different client). Before offering tests, run `ValidateClient` (see
     [Install the Kafka client](#install-the-kafka-client)). If it **passes**, go to
     the test options at step 8. If it **fails** with a "client not installed/working"
     (or version) error, run the install + validate loop (have the customer install a
     Kafka client themselves — a `kafkaUrl` + `kafkaSha512` they provide; you may point
     them to Apache in words but don't source the URL or run it yourself — then re-run
     `ValidateClient` until it passes)
     — then go to step 8. Do **not** present test options until
     `ValidateClient` passes.
4. Ask the customer for cluster sizing (see [Sizing inputs](#sizing-inputs)) —
   `instance_type`, `broker_count`, and `kafka_version` + mode. Offer only
   supported choices (see [Constrained choices](#constrained-choices)). Mention
   once, in passing, that the skill's assessment phase (Phase 2) inventories their
   source cluster and produces a sizing/pricing workbook to help pick the right
   Express size — so if they have not run it and want a data-driven
   recommendation, they can run the assessment first. Do not block on it; proceed
   with whatever sizing they give.
5. Run `simulation_load_test_config.py compute` → derive fleet + CloudFormation parameters.
   Do **not** render yet — render is only for the self-guided path below.
   (The stack downloads no Kafka client; the client is installed after deploy — see
   [Install the Kafka client](#install-the-kafka-client).)
6. Present the stack resource list and **inform there will be extra cost** and it
   takes ~1 hour. Ask the customer to confirm deployment.
   - **Yes (you deploy) →** go to step 7. Deploy in **one** `create-stack` command
     from the static source template, passing the compute-derived values as
     `--parameters` (see [Deploy](#deploy)). Do **not** render a local template on
     this path — passing parameters to the source template is the single deploy step.
   - **No (self-guided) →** *now* run `simulation_load_test_config.py render` (see
     [Render the local template](#render-the-local-template)) to write a filled,
     ready-to-deploy template to the customer's working directory, then hand them the
     self-guided `create-stack` command that deploys from **that local file** (no
     `--parameters` needed — sizing is baked in) plus the install/validate/test
     commands. End the skill. Rendering exists so the customer who deploys themselves
     gets a single self-contained file rather than a long parameterized command
     pointing at a path they don't control.
7. Deploy the stack with one `create-stack` (source template + `--parameters` from
   compute); wait for `CREATE_COMPLETE`. Then **install and validate the Kafka client**
   (see [Install the Kafka client](#install-the-kafka-client)): install the Kafka
   client on the fleet (the `kafkaUrl` comes from the customer — you don't source the
   URL), then run `ValidateClient` and loop
   until it passes. Then create the topics via the
   `CreateTopicsCommand` output. Once that
   is done, present the CloudWatch dashboard to the customer **once** —
   both the `DashboardUrl` and the `DashboardArn` stack outputs — and tell them this
   is where every test's metrics will appear.
8. Present the two test options (below). **Before the options, state the deployed
   cluster's ingress capacity** so the customer can pick a sensible throughput:
   its **sustained** ingress (the recommended ceiling, no degradation up to here)
   and its **maximum** ingress (the hard quota — MSK throttles beyond it). Both come
   from the `compute` output (`cluster_sustained_ingress_mbps` and
   `cluster_max_ingress_mbps`); never hand-compute them.
9. Fill the chosen template with computed defaults + bounds; ask for edits.
10. Run `simulation_load_test_config.py validate`. **REJECT → show errors, loop back to 9.**
    **PASS →** surface any warnings as one sentence each and continue.
11. Trigger the test via SSM and confirm it started, and name the metric(s) it
    emits. The dashboard was already shared at deploy — point the customer back to it
    rather than re-posting the URL each run. **Tell the customer that after the
    producers stop, the consumers keep reading and adaptively drain until the
    consumer-lag metric returns to ~0 (capped at `maxDrainMinutes`, default 20) —
    so the run takes a little longer than `duration_minutes` to fully settle, and
    that trailing drain is expected.**
12. Ask the customer which of these they want next:
    - **Keep the stack running and finish** — leave the simulation in place and end
      the skill. Remind them it keeps incurring cost until they tear it down, and
      give them the teardown command for later.
    - **Run another test** → go to 8.
    - **Tear down the stack** → [Teardown](#teardown), then end the skill.

## Confirm the target account

Before the first AWS action that creates, deploys, modifies, or deletes anything,
confirm you are operating in the account the customer intends:

```bash
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json
```

Show the customer the **account id** and **role/identity**, and ask them to confirm
it is the correct account for this simulation. Do **not** proceed past this point until
they explicitly confirm. If it is the wrong account, stop — ask them to switch
credentials (profile / refreshed session) and re-run the check. Re-confirm whenever
credentials are refreshed mid-session, since the identity may have changed.

## Single simulation per account

To avoid paying for duplicate load-test infrastructure, **only one simulation may exist
per account/region at a time**. The stack name is fixed (`msk-express-simulation`), so a
second `create-stack` fails with `AlreadyExistsException`. Always check before
deploying, and tell the customer up front that only one simulation is allowed at a time:

```bash
aws cloudformation describe-stacks --stack-name msk-express-simulation \
  --region <region> --query 'Stacks[0].StackStatus' --output text 2>/dev/null
```

- **No stack** (command errors / empty) — proceed with a fresh deployment.
- **`CREATE_COMPLETE`** — a healthy simulation already exists. Inform the customer (and
  that only one is allowed), then ask which they want:
  - **Reuse it** — read `DashboardUrl` + `DashboardArn` (and `FleetSummary`) from
    `describe-stacks --query 'Stacks[0].Outputs'` and present the dashboard. No new
    deploy, no new cost. **Then verify the Kafka client before offering tests:** a
    `CREATE_COMPLETE` stack does not imply an installed client (it is a post-deploy
    step and may never have run, or ran against a different client), so run
    `ValidateClient` (see [Install the Kafka client](#install-the-kafka-client)).
    If it passes, go to the test options. If it fails, run the install + validate
    loop (`InstallKafkaClient` with a Kafka client URL, then
    `ValidateClient` until it passes) first. Do not offer tests until it passes.
  - **Delete and redeploy** — `delete-stack` + `wait stack-delete-complete`, then
    continue with sizing + deploy.
- **Any other state** (`ROLLBACK_COMPLETE`, `*_FAILED`, `*_IN_PROGRESS`) — it cannot
  be reused. If it is settled in a failed/rollback state, delete and redeploy; if an
  operation is still in progress, wait for it to finish before deciding.

## Constrained choices

When asking the customer to choose cluster parameters, offer **only the supported
values** as an explicit list. The question UI always appends its own "Other"
free-form option that cannot be suppressed — so do not rely on the prompt to
constrain input. Instead, treat any free-form value as untrusted and run it
through `simulation_load_test_config.py compute` (which rejects unsupported `instance_type`,
`broker_count`, and `kafka_version` locally) before deploying. Never deploy a
value the script rejected — an unsupported value otherwise only fails later at
`create-stack`.

**Picker cap.** The `AskUserQuestion` tool hard-limits each question to 4
options (plus the auto-appended "Other") and silently drops the rest. There are
**7 supported `instance_type` values**, more than the picker can show. You may
still use the picker, but the **question text MUST enumerate all 7 instance
types** (with their specs) so the customer can see every option even when some are
not rendered as buttons — instruct them to use "Other" to pick a type that is
not shown as a button. Never present `instance_type` in a way that names fewer
than all 7 types. `broker_count` and `kafka_version` have ≤ 4 options each and
fit the picker directly.

- **instance_type** — exactly these Express types (no others), always present
  all seven:
  `express.m7g.large`, `express.m7g.xlarge`, `express.m7g.2xlarge`,
  `express.m7g.4xlarge`, `express.m7g.8xlarge`, `express.m7g.12xlarge`,
  `express.m7g.16xlarge`.
- **broker_count** — a multiple of 3, ≥ 3 (Express is always a 3-AZ topology).
- **kafka_version + metadata mode** — present as one combined list (mode is implied
  by the choice). Express supports **only 3.6, 3.8, 3.9**. On Express **3.9 is
  KRaft-only** and **KRaft is not available below 3.9**, so the only valid combos
  are these three:

  | Choice | Mode | CloudFormation `KafkaVersion` |
  |---|---|---|
  | 3.9 (KRaft) — recommended | KRaft | `3.9.x.kraft` |
  | 3.8 (ZooKeeper) | ZooKeeper | `3.8.x` |
  | 3.6 (ZooKeeper) | ZooKeeper | `3.6.0` |

  Do **not** offer **3.9 in ZooKeeper mode** — it is not a supported Express
  combination and only fails later at `create-stack`. KRaft is not available below
  3.9; 3.7 and 4.0 are not Express versions at all. Do not offer any of these.

Treat the official AWS MSK Express documentation as the source of truth for the
supported instance types and versions. If you can access AWS documentation, verify
these values against it — especially if a value here is rejected at `create-stack`.
If that documentation is not accessible, this list is a trustworthy source to use.

## Communicating with the customer

Speak to the customer in plain, outward-facing language. Do **not** expose internal
or process framing — no "per the v1 flow", "the skill says", "I won't interpret
results because…", version numbers of this workflow, step numbers, or references to
these instructions. Just do the right thing.

Frame the simulation as a way to see MSK Express perform on the customer's own
workload — a confidence-building demonstration, not a safeguard. MSK Express is
production-ready; present the simulation as confirming expected performance on their
specific workload, and avoid phrasing that implies doubt about Express (e.g. "just to
be safe before committing" or "in case Express can't keep up"). Let the results speak
for themselves.

When presenting test results: point the customer to the dashboard already shared at
deploy and name the metric(s) the test emits, and let them read it. If they ask what
the numbers mean, you may describe what each metric represents, but do not assert a
pass/fail verdict — phrase it as something they evaluate against their own targets.

When you preview or list the upcoming steps, keep each to a short phrase (e.g.
*Install the Kafka client on the fleet*) — do not inline the install options or other
details; cover those at the step itself.

## Sizing inputs

Always ask the customer for the sizing directly — `instance_type`, `broker_count`,
and a `kafka_version` + metadata mode — offering only the supported values listed
in [Constrained choices](#constrained-choices). Do not look for a local
assessment file; the assessment now hands the customer a sizing/pricing workbook
rather than writing a JSON artifact this skill can read.

When you ask, briefly note that the skill's assessment phase (Phase 2) inventories
their source cluster and produces that sizing/pricing workbook, so if they have
not run it and want a data-driven Express size recommendation, they can run the
assessment first. Keep it to a sentence and do not block on it — if they already
have a size in mind (from the workbook or otherwise), take it and proceed.

Validate: `instance_type` must be one of the supported Express types; `broker_count`
≥ 3 and a multiple of 3; the version/mode must be one of the three supported
combinations. Map the customer's version + mode choice to the exact CloudFormation
`KafkaVersion` string from the table. 3.9
is always KRaft on Express (`3.9.x.kraft`); reject a request for 3.9 in ZooKeeper
mode.

## Install the Kafka client

The Kafka client is installed after the stack is created, then validated before any
test. At `CREATE_COMPLETE` the fleet has Java, an empty `/opt/kafka`, and a
`client.properties` with the IAM/TLS settings Express requires; this step installs
the client itself. Two SSM documents handle it:

- **`InstallKafkaClient`** — installs the Kafka client from `kafkaUrl` (passed at
  invocation, verified against the customer-provided `kafkaSha512`), plus the
  `aws-msk-iam-auth` jar (required for IAM auth) from its AWS-owned source (installed
  automatically — no parameter).
- **`ValidateClient`** — confirms the client runs, its version is `>=` the cluster's
  Kafka version, and it can authenticate and list topics on the cluster.

### Step 1 — install

Install the Kafka client on the fleet. The tarball URL is the runtime parameter
`kafkaUrl`, and **it comes from the customer** — they pick a source they trust and
give you the URL; you plug it in. Help *in words*: the Apache Software Foundation
publishes Kafka — point them to a source they trust (their org's approved software
channel, their package manager, or the official Apache distribution on an
`apache.org` domain) and away from third-party mirrors or search-result links. **Do
not fabricate, guess, or web-search a URL and present it as authoritative** — you may
fill in a URL the customer provides. The customer also gives the tarball's
**SHA-512** (`kafkaSha512`); the install verifies it before use (copy the value Apache
publishes, lowercased/no spaces, or compute `sha512sum <file>.tgz`). The
`aws-msk-iam-auth` jar installs automatically from its AWS-owned source (no parameter).

If the customer asks you to pick the URL or run the install for them, don't flatly
refuse — briefly explain you can't vouch for a specific link on their behalf, then
help: confirm the version, name Apache as the publisher, point to an official channel
by description, and show them how to get the checksum.

**Pre-flight before invoking:** confirm the customer-provided `kafkaUrl` starts with
`https://` (reject and ask for an HTTPS URL otherwise) — catch this before the
`send-command`, not as a failed run. The install document re-checks the scheme as a
backstop (e.g. for the self-guided path where the customer runs the command directly).

```bash
# Single-quote --parameters: a URL with a ?/& query string would otherwise be
# glob-expanded by the shell (e.g. zsh: "no matches found").
aws ssm send-command --document-name msk-express-simulation-InstallKafkaClient \
  --targets Key=tag:simulation:role,Values=producer,consumer \
  --parameters 'kafkaUrl=<kafka-client-tarball-url>,kafkaSha512=<sha512>' \
  --region <region>
```

Wait for it to succeed, then validate.

### Step 2 — validate

After install, run `ValidateClient` and loop until it passes:

```bash
aws ssm send-command --document-name msk-express-simulation-ValidateClient \
  --targets Key=tag:simulation:role,Values=producer,consumer --region <region>
```

- **PASS** → proceed to topic creation + tests.
- **FAIL** → show the error (version too low, or cannot authenticate/connect). Help
  the customer fix or re-install the Kafka client by re-running the install command
  with a different `kafkaUrl` + `kafkaSha512` they provide. Re-run
  `ValidateClient` until it passes.

The test documents also carry a lightweight client check, so a test never runs
against a fleet with no client.

### If a test hits a client-related error

If a test fails with a client-related error, the cause may be the Kafka client that
was installed. Have the customer re-install with a different client (a `kafkaUrl` +
`kafkaSha512` they provide — you don't source the URL) and re-run the test.

## Env computation

```bash
uv run scripts/simulation_load_test_config.py compute --instance-type <type> --broker-count <N> --kafka-version <ver>
```

Always pass `--kafka-version` with the CloudFormation `KafkaVersion` string you intend to
deploy. The question UI always appends an "Other" free-form option to every
choice prompt, which a customer can use to enter an unsupported `instance_type`,
`broker_count`, or version. `compute` rejects all three locally (non-zero exit
with an `error` message) so a free-form value fails here in seconds rather than
~40 min into `create-stack`. On rejection, re-present the supported choices
(`supported_kafka_versions` is in the output) and do not deploy.

Returns cluster capacity, the **auto-sized** client fleet, and each test's
defaults/bounds. Map the output to CloudFormation parameters:

| CloudFormation parameter | From compute output |
|---|---|
| InstanceType / BrokerCount / KafkaVersion | sizing inputs |
| ClientInstanceType | `fleet_instance_type` |
| ProducerCount | `fleet_producer_count` |
| ConsumerCount | `fleet_consumer_count` |

The fleet is sized to ~1.5× the cluster's **maximum** ingress quota (its throttle
ceiling), so it can drive the cluster all the way to its limit and is never the
bottleneck. The customer cannot change fleet size; to change cluster sizing, redeploy.

## Render the local template

**Self-guided path only.** Render exclusively when the customer **declines** to let
you deploy (flow step 6, "No"). If they consent, skip render entirely and deploy in
one `create-stack` with `--parameters` (see [Deploy](#deploy)).

On the self-guided path, render a local, ready-to-deploy copy of the template with the
sizing and computed fleet baked in as parameter `Default`s. This is what the
customer downloads and deploys from — never the skill's source template.

Pass `--output` as an **absolute path under the customer's working directory** (not
the skill directory). `render` resolves whatever you pass to an absolute path —
a relative path resolves against the current working directory, which is ambiguous
and could land the file inside the skill package — so anchor it explicitly with
`$(pwd)`:

```bash
uv run scripts/simulation_load_test_config.py render \
  --instance-type <type> --broker-count <N> --kafka-version <ver> \
  --output "$(pwd)/migrate-to-msk-skill-artifacts/simulation/simulation-stack.yaml"
```

After the customer deploys the rendered template, they install + validate the Kafka
client exactly like the consented path (via the `InstallKafkaClient` /
`ValidateClient` SSM documents — see [Install the Kafka client](#install-the-kafka-client)).
Nothing client-related is baked into the rendered template.

`render` re-runs the same sizing math as `compute` (so it rejects an unsupported
`instance_type`, `broker_count`, or `kafka_version` the same way, before writing
anything), reads the static source template internally, and bakes these parameters
as `Default`s — so a plain `create-stack` with no `--parameters` deploys the
customer's exact sizing:

| Baked parameter | Value |
|---|---|
| InstanceType / BrokerCount / KafkaVersion | sizing inputs |
| ClientInstanceType | `fleet_instance_type` |
| ProducerCount | `fleet_producer_count` |
| ConsumerCount | `fleet_consumer_count` |

`render` returns the **resolved absolute** `output_path` (and a ready-to-run
`deploy_command` that points at it). Use that absolute path verbatim — it is the
**only** template path you ever show the customer. Tell them where it was saved so
they have the exact artifact being deployed. `render` refuses to write inside the
skill package, so if you accidentally point `--output` there it errors instead of
leaking the artifact into the install directory.

## Throughput & fleet reference

These tables are the source of the numbers `simulation_load_test_config.py` computes from. They
are reference only — the script is authoritative; do not hand-compute from them. The figures
reflect published Express performance characteristics. If you can access AWS documentation, treat
the official AWS MSK Express documentation as the source of truth and validate against it; if that
documentation is not accessible, these values are a trustworthy source to use.

### Express per-broker throughput throttle limits (MB/s)

`sustained` = recommended threshold (no degradation up to here). `max` = hard quota
(MSK throttles read/write traffic beyond it). Cluster totals = per-broker × broker
count. The sizing math uses **ingress**; egress is listed for reference (it can bind
first when many consumer groups read the stream).

| Instance | Ingress sustained | Ingress max | Egress sustained | Egress max |
|---|---|---|---|---|
| express.m7g.large | 15.6 | 23.4 | 31.2 | 58.5 |
| express.m7g.xlarge | 31.2 | 46.8 | 62.5 | 117 |
| express.m7g.2xlarge | 62.5 | 93.7 | 125 | 234.2 |
| express.m7g.4xlarge | 124.9 | 187.5 | 249.8 | 468.7 |
| express.m7g.8xlarge | 250 | 375 | 500 | 937.5 |
| express.m7g.12xlarge | 375 | 562.5 | 750 | 1406.2 |
| express.m7g.16xlarge | 500 | 750 | 1000 | 1875 |

### Client fleet sizing

The fleet runs `kafka-producer-perf-test` / `kafka-e2e-latency` — network- and
CPU-bound. All clusters use a fixed fleet instance type (`c5.2xlarge`); only the
count scales: `fleet_producer_count = max(2, ceil(cluster_max_ingress × 1.5 /
400))`, and the same count of consumers.

- **Instance type:** `c5.2xlarge` (10 Gbps sustained baseline, no burst credits)
- **Per-instance throughput target:** 400 MB/s (conservative for Kafka with TLS + acks=all)
- **Why c5.2xlarge:** stable non-burstable network; smaller c5 sizes have burstable
  baselines unsuitable for sustained load generation.

## Deploy

There are two deploy commands depending on which path the customer chose at flow
step 6. Both create the same stack; they differ only in where the template comes
from and whether sizing is passed as parameters or baked in.

### Consented path — you deploy (no render)

Deploy in **one** `create-stack` straight from the static source template, passing
the compute-derived values as `--parameters`. This is the single deploy step; do
not render on this path.

```bash
aws cloudformation create-stack --stack-name msk-express-simulation \
  --template-body file://<skill>/assets/simulation-stack.yaml \
  --parameters ParameterKey=InstanceType,ParameterValue=<type> \
    ParameterKey=BrokerCount,ParameterValue=<N> \
    ParameterKey=KafkaVersion,ParameterValue=<ver> \
    ParameterKey=ClientInstanceType,ParameterValue=<fleet_instance_type> \
    ParameterKey=ProducerCount,ParameterValue=<fleet_producer_count> \
    ParameterKey=ConsumerCount,ParameterValue=<fleet_consumer_count> \
  --capabilities CAPABILITY_IAM --region <region>

aws cloudformation wait stack-create-complete --stack-name msk-express-simulation --region <region>
```

The stack downloads no Kafka client — install it after `CREATE_COMPLETE` (see
[Install the Kafka client](#install-the-kafka-client)).

`<skill>/assets/simulation-stack.yaml` is the install path — you (the agent) use it
here, but never surface it to the customer. The customer consented to you deploying,
so they never need the template path on this path; you run the command on their
behalf.

### Self-guided path — customer deploys (render first)

Only on the self-guided path. After [rendering](#render-the-local-template) the
filled local template, hand them this command using the absolute `output_path`
`render` reported (its `deploy_command` field is exactly this, minus the region).
Sizing is baked into the parameter `Default`s, so no `--parameters` are needed:

```bash
aws cloudformation create-stack --stack-name msk-express-simulation \
  --template-body file://<absolute-output_path-from-render> \
  --capabilities CAPABILITY_IAM --region <region>

aws cloudformation wait stack-create-complete --stack-name msk-express-simulation --region <region>
```

On this path the customer only ever sees the local rendered artifact path, never the
skill's source template path.

The fleet ASGs gate `CREATE_COMPLETE` on a `cfn-signal` from each instance's
UserData, so reaching `CREATE_COMPLETE` means the fleet finished bootstrapping
(Java + dirs + `client.properties`). The **Kafka client is not installed yet** —
that's the post-deploy step ([Install the Kafka client](#install-the-kafka-client)).
As a belt-and-suspenders check before the first SSM command, confirm the producer
instances pass their EC2 status checks — the SSM agent reports `Online` before an
instance is through boot, and a command issued too early is silently `Terminated`
with no output.

> **Shell-safe instance-ID handling (do not skip).** `--output text` returns
> instance IDs **tab-separated on one line**. Do **not** capture them in a plain
> variable and pass it unquoted to `--instance-ids` (`... --instance-ids
> $PRODUCERS`): the session shell is often **zsh**, which — unlike bash — does
> **not** word-split unquoted parameter expansions, so every ID is passed as a
> single malformed argument and the call fails with
> `InvalidInstanceID.Malformed`. Pipe the IDs through `xargs` instead, which
> splits on whitespace in **any** shell. This same rule applies anywhere you feed
> a list of IDs to a CLI flag (e.g. the `send-command --instance-ids` calls when
> [triggering a test](#triggering-a-test)) — never rely on the shell to split a
> captured variable.

```bash
aws ec2 describe-instances --region <region> \
  --filters Name=tag:simulation:role,Values=producer Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].InstanceId' --output text \
  | tr '\t' '\n' \
  | xargs aws ec2 wait instance-status-ok --region <region> --instance-ids
```

**Before creating topics, install and validate the Kafka client** (see
[Install the Kafka client](#install-the-kafka-client)): install the Kafka client on
the fleet (the `kafkaUrl` comes from the customer — you don't source the URL), then
run `ValidateClient` and loop until it
passes. The test documents fail fast without a working client, so install +
validation must succeed first.

Then create the test topics (cluster must be ACTIVE first) using the `CreateTopicsCommand`
stack output. It creates one topic per test (`<base>-e2e`, `<base>-restart`) plus the
e2e probe topic, so each test's traffic stays isolated.

## Test templates

Present exactly these two. Show the **Description** and **User Configuration**
sections only. Fill defaults/bounds from the `compute` output for the deployed
cluster (the values below are for the 12× express.m7g.4xlarge default).

Lead in with the deployed cluster's **ingress capacity** so the customer can
choose a throughput with the right context — its **sustained** ingress
(`cluster_sustained_ingress_mbps`, the recommended ceiling with no degradation)
and its **maximum** ingress (`cluster_max_ingress_mbps`, the hard quota beyond
which MSK throttles). Phrase it plainly, e.g. *"This cluster sustains up to
**X MB/s** ingress and is throttled at a hard maximum of **Y MB/s** — pick a test
throughput with those in mind."* Take both numbers straight from the `compute`
output; do not hand-compute them.

### 1. End-to-End Latency

**Description:** Measures produce-to-consume round-trip latency under a steady
load. Producers drive the target throughput while one producer samples end-to-end
latency; the value is emitted as the `MSKSimulation/E2ELatencyMs` custom metric.
Consumers drain the topic (consumer group `simulation-e2e`) so the consume path is
exercised too — watch BytesOut and consumer lag on the dashboard alongside latency.

**User Configuration:**

| Parameter | Default | Range |
|---|---|---|
| throughput_mbps | 10 | 1 – fleet_max_mbps |
| duration_minutes | 10 | 5 – 120 |
| num_producers | 1 | 1 – fleet_producer_count |
| num_consumers | 1 | 1 – fleet_consumer_count |

### 2. Broker Restart Under Load

**Description:** Sustains target throughput, then reboots one broker mid-test to
observe failover behavior and recovery. Producers emit `MSKSimulation/ProduceLatencyMs`
over the window, and consumers read the topic (consumer group `simulation-restart`) so
the consume path is exercised too. The dashboard's ActiveControllerCount, per-cluster
BytesIn/BytesOut, and consumer lag show the dip and recovery on both sides.

**User Configuration:**

| Parameter | Default | Range |
|---|---|---|
| target_throughput_mbps | default_target_throughput | 1 – fleet_max_mbps |
| duration_minutes | 15 | 10 – 120 |
| reboot_at_minute | 5 | 2 – (duration_minutes − 2) |
| num_producers | fleet_producer_count | 1 – fleet_producer_count |

## Guardrails

Always validate before triggering:

```bash
uv run scripts/simulation_load_test_config.py validate --test <e2e_latency|broker_restart> \
  --config '<json>' --instance-type <type> --broker-count <N>
```

Two severity levels:

- **REJECT** (`decision: REJECT`, exit 1) — value exceeds a physical fleet limit
  or is an invalid timing (e.g. `reboot_at_minute` not inside the run). Show the
  error and loop back to let the customer change the value.
- **WARN** (`warnings: [...]`, still `PASS`) — value exceeds a cluster best
  practice (e.g. above cluster max ingress, or too few producers to sustain the
  rate). Surface as **one sentence** at trigger time and continue.

## Triggering a test

Select which fleet instances participate by passing their instance IDs to
`send-command`. Per-instance throughput = total ÷ number of producers targeted.
Set `leadInstanceId` to the **first** targeted producer (it samples latency /
reboots the broker). For **E2E Latency**, `num_producers` / `num_consumers` set how
many of each you target. For **Broker Restart**, target the chosen `num_producers`
producers and all
consumers — consumers drain the topic for read-health monitoring. Each test uses
its **own** load topic (E2E -> `<base>-e2e`, Broker Restart -> `<base>-restart`),
so the two tests are fully isolated -- an idle test's consumer group never
accumulates phantom lag from the other test writing to a shared topic. On top of
that, each run **resets its consumer group's offset to its topic's latest** at
start, so every run begins at ~0 lag (ignoring any leftover from a prior run of the
same test) and its consumer-lag / BytesOut reflect only its own traffic. After the
producers stop, the consumer keeps reading and **adaptively drains**: it polls the
group's lag and runs until the lag reaches ~0 (caught up) or `maxDrainMinutes`
(default 20) elapses, whichever first — then exits. Without this tail the consumer
would stop with the producers and `MaxOffsetLag` would freeze at its peak (a stale
flat line that wrongly looks like the cluster can't keep up). The adaptive drain
self-tunes to any cluster size / rate and exits early once caught up (no idle
waste); raise `maxDrainMinutes` only if a very large backlog needs more than 20 min.

**Tell the customer at trigger time:** after the producers stop, the consumers keep
reading until the dashboard's consumer-lag drains back to ~0 — so the run takes a
little longer than `duration_minutes` to fully settle, and that trailing drain is
expected, not a problem.

```bash
# E2E Latency (targets both roles; the doc branches on the simulation:role IMDS tag)
aws ssm send-command --document-name msk-express-simulation-RunE2ELatency \
  --instance-ids <producer-ids...> <consumer-ids...> \
  --parameters perInstanceThroughputMbps=<total/num_producers>,durationMinutes=<d>,leadInstanceId=<first-producer-id> \
  --region <region>

# Broker Restart (targets both roles; producers load + reboot, consumers read + drain)
# After producers stop, consumers adaptively drain until lag ~0 (capped at maxDrainMinutes,
# default 20). Only pass maxDrainMinutes to override the cap; the default is usually fine.
aws ssm send-command --document-name msk-express-simulation-RunBrokerRestartTest \
  --instance-ids <producer-ids...> <consumer-ids...> \
  --parameters perInstanceThroughputMbps=<total/num_producers>,durationMinutes=<d>,rebootAtMinute=<m>,leadInstanceId=<first-producer-id> \
  --region <region>
```

The dashboard URL + ARN were already shared once at `CREATE_COMPLETE`; point the
customer back to that dashboard for results rather than re-posting it each run.

## Teardown

```bash
aws cloudformation delete-stack --stack-name msk-express-simulation --region <region>
```

## Off-trail handling

- **Asks to change cluster sizing after deploy** — not supported in place. Offer
  to tear down and redeploy with new sizing.
- **Asks for a third/custom test type** — only the two vended tests are available;
  offer those instead.
- **Asks to edit the template / infra** — the source template is static and the
  rendered local copy only carries baked sizing; decline hand-edits and offer to
  re-render + redeploy with different sizing instead.
- **Asks what the results mean** — present the dashboard and explain what the
  metrics represent, but do not assert a pass/fail verdict; the customer evaluates
  the numbers against their own targets.
- **Asks to deploy a second/another simulation while one exists** — only one simulation is
  allowed per account at a time; offer to reuse the existing one or delete it and
  redeploy (see [Single simulation per account](#single-simulation-per-account)).
- **Asks where the Kafka client comes from** — the Kafka client is installed
  post-deploy via `InstallKafkaClient` from a `kafkaUrl` the customer provides (you
  may point them to Apache in words, but don't fabricate a URL). The `aws-msk-iam-auth`
  jar is installed automatically from its AWS-owned source. See [Install the Kafka client](#install-the-kafka-client).
- **Reuses an existing simulation** — a `CREATE_COMPLETE` stack does not guarantee a
  working Kafka client (install is a post-deploy step that may never have run). After
  presenting the dashboard, run `ValidateClient` before offering tests; if it fails,
  run the `InstallKafkaClient` + `ValidateClient` loop until it passes. See
  [Install the Kafka client](#install-the-kafka-client).
- **A test fails with a "Kafka client not installed/working" error** — install the
  client via `InstallKafkaClient`, run `ValidateClient` until it passes, then retry
  the test.
- **A test hits a client-related error** — it may be the installed Kafka client;
  have the customer re-install with a different client (a `kafkaUrl` + `kafkaSha512`
  they provide — you don't source the URL) and re-run the test. See [Install the Kafka client](#install-the-kafka-client).
- **Wants to skip the simulation** — the simulation is the last phase, so end the skill.
