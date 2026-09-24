# CloudWatch Omni concepts and where to start

CloudWatch Application Observability — also called Omni — is an AI-native
observability app. A customer investigates their systems by asking questions in
conversation rather than by assembling queries and dashboards by hand.

This file is orientation, not procedure. It explains what the pieces are, how they
connect, what order they get set up in, and how to tell an Omni request apart from a
CloudWatch one. Every procedure lives in a sibling reference, linked below.

> **Always state these, in any answer drawn from this file:**
>
> - The setup order is Domain, then Space, then grants, then telemetry in, then
>   instrumentation.
> - Access Profiles are **conditional**, needed only when async workloads (alerts,
>   integrations, agents) are involved. Name that condition, do not omit it.
> - Say, in these words or close to them, that **instrumentation or forwarding started
>   before a Space exists appears to succeed while delivering telemetry nowhere the
>   customer can see**. Never describe the setup order without this warning.
> - If the request names neither product ("add observability to my API"), **ask
>   which one they mean**, framed CloudWatch Omni versus CloudWatch, and explain the
>   **setup-versus-use** boundary in the same message so they can choose — then
>   **stop**. Do not assume Omni, and do not assume CloudWatch.

## Contents

- [The concepts](#the-concepts)
- [How the pieces connect](#how-the-pieces-connect)
- [Setup order](#setup-order)
- [Is this the right skill](#is-this-the-right-skill)
- [Additional resources](#additional-resources)

## The concepts

**Domain** — the identity boundary. A Domain carries the authorization provider,
either IAM or IAM Identity Center, and owns the endpoint URL customers reach Omni
through. The endpoint derives from the Domain's name, which is why the name is not
cosmetic. An account has at most one Domain; an AWS Organization can instead have one
Domain shared by every member account.

**Space** — the access boundary over the account's CloudWatch Dataset. A Space lives
in exactly one account and one Region, is created under a Domain, and holds no
telemetry of its own. An account has at most one Space per
Region, so a customer wanting telemetry separated across Regions gets a Space in
each. Whether those Spaces may sit in a Region other than the Domain's depends on
the Domain's authorization provider: an **IAM-only Domain** allows it; an **Identity
Center Domain** requires each Space in the Domain's own Region, and a customer who
needs Identity Center together with Spaces in several Regions uses the org-scoped
Domain instead (`references/cloudwatch-omni/spaces-and-domains.md`, Region rules).

**Access grant** — attaches a principal to one Space at a permission level. The
principal can be a person or group in Identity Center, an IAM role or user, or an
async workload. Grants are the only way anyone reaches a Space's telemetry *through Omni*: a Space
with no grants is readable by nobody through Omni, including the account that created it. A grant never
spans Spaces, Regions, or accounts. Grants bound the Omni plane only — where a Space's data came
from CloudWatch log groups, those groups stay readable through the native CloudWatch Logs APIs
under separate IAM, so a grant is not by itself a way to keep a principal away from that data
(see `access-grants.md`).

**Access Profile** — a named boundary for **async workloads**: an alert running an
investigation, an integration calling another system, an agent evaluating traces.
These act without a person in the loop to approve what they do, so the profile
limits what Omni may do on the customer's behalf. A profile carries no permissions
itself — grants supply them.

**Dataset** — the account's CloudWatch store that queries run against: one per
Region, `arn:aws:cloudwatch:<region>:<account>:dataset/default`, a CloudWatch
resource the Space reads rather than part of the Space. OTel metrics land in it
natively; logs and traces reach it when a dataset integration copies the account's
log groups — including `aws/spans` — into it. A customer starting from nothing
usually needs both telemetry flowing into CloudWatch and that integration.

## How the pieces connect

The relationships matter more than the definitions, because each of them determines
something a customer will otherwise get wrong.

- A **Domain contains Spaces**. The Domain decides who can authenticate; the Space
  decides who reads the account's Dataset in its Region. Deleting a Domain requires
  deleting its Spaces first.
- A **Space is per account and per Region**. This is the single most common source of
  surprise: access that works in one Region appears broken in another, because a
  different Region means a different Space and therefore different grants. Whether a
  Space may be in a different Region from its Domain is decided by the Domain's
  provider — allowed under IAM-only, not under an account-scoped Identity Center
  Domain (see the Space concept above).
- **Grants attach principals to a Space**, not to a Domain. Domain-wide
  administration exists, but only for organization Domains, and it is `ADMIN` over
  every Space in the Domain.
- An **Access Profile sits between a workload and a Space**. The workload gets a
  grant that lets it assume the profile; the profile gets grants describing what it
  may do. Both are required, and missing either produces a different failure.
- **Telemetry reaches the Dataset, not the Space directly.** Setting up a Space does
  not make data appear. Ingestion or forwarding is a separate step, and because the
  Dataset is CloudWatch's, both work with no Space in the account — but nothing in
  Omni can read the result until a Space exists.

## Setup order

Working from nothing, the sequence is:

1. **Domain** — account-scoped, or shared across an organization. See
   `references/cloudwatch-omni/spaces-and-domains.md` or `references/cloudwatch-omni/org-domains.md`.
2. **Space** — under the Domain, in the Region the customer wants. Covered in the
   same two files.
3. **Access grants** — so people can reach the Space. See
   `references/cloudwatch-omni/access-grants.md`.
4. **Telemetry in** — get telemetry into CloudWatch through the standard per-signal
   OTLP endpoints (deploy a collector that exports to them — see
   `references/cloudwatch-omni/instrumentation/collector.md`), and create the dataset integration
   so logs and traces are copied into the Dataset
   (`references/cloudwatch-omni/data-forwarding-and-centralization.md`). A customer
   starting from nothing needs both halves. If
   traces are part of it, **Transaction Search must be enabled in that Region first** —
   Omni reads spans from the `aws/spans` log group, and without it traces never arrive
   while everything else looks healthy (account-level, per Region).
5. **Instrumentation** — so applications and agents emit telemetry in the first
   place. See `references/cloudwatch-omni/instrumentation/instrumentation.md` for applications and
   `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md` for AI
   agents.

Two things are conditional rather than sequential:

- **Access Profiles** — only when async workloads are involved. See
  `references/cloudwatch-omni/access-profiles.md`.

**Constraints:**

- You MUST establish where in this sequence the customer already is before starting
  anything. Most requests join partway through, and re-running an earlier step
  conflicts rather than being idempotent.
- You SHOULD create the Space before instrumentation or forwarding. Neither
  technically requires one — both write to the account's CloudWatch Dataset and
  succeed without a Space — but nothing in Omni can read the result until a Space
  exists, so a customer who checks Omni first sees an empty product and reads it as a
  failure.
- You SHOULD tell the customer the whole sequence when they are starting from
  nothing, so a working Space with no telemetry in it does not read as a failure.

## Is this the right skill

Two skills cover CloudWatch, and choosing wrongly is worse than any mistake inside a
procedure — the agent proceeds confidently down the wrong path.

**This skill** is for setting Omni up: Domains, Spaces, grants, Access Profiles,
ingestion, forwarding, instrumentation, and connecting Slack.

**`aws-observability`** is for CloudWatch — Log Insights, metrics, alarms,
dashboards, X-Ray, CloudTrail, Application Signals, synthetics — and also for
day-to-day *use* of Omni once it is set up: writing queries, building dashboards,
and configuring alerts.

Between the two skills the split is **setup versus use, for Omni**; everything
CloudWatch — setup (Application Signals, Dynamic Instrumentation) as much as use — lives
in `aws-observability`:

| The customer wants | Skill |
|---|---|
| To create or configure a Domain, Space, grant, or profile | This skill |
| To get telemetry flowing into Omni for the first time | This skill |
| To instrument an application or agent for Omni | This skill |
| To query telemetry, build a dashboard, or set up an alert in Omni | `aws-observability` |
| Anything about Application Signals, X-Ray, synthetics, or CloudWatch alarms | `aws-observability` |
| To investigate a live problem | `aws-observability` |

**Constraints:**

- You MUST decide which skill applies before doing anything else. A request that
  names neither product — "add observability to my API", "how should I begin monitoring my workload" —
  is ambiguous, and you MUST NOT resolve it by assumption in either direction: not
  Omni because this skill is loaded, and not CloudWatch because Omni was not named.
  Which product a customer wants to *set up* is their intent; the account's current
  state does not answer it (a customer with an Omni Space may still want a CloudWatch
  alarm, and one without may be here to create their first Space), so a `list-spaces`
  probe is not a substitute for asking. Probe only when the customer has already
  named a concrete instrumentation/collector task (see the routing rules in
  `SKILL.md`), not for a general "add monitoring" request.
- When you ask, you MUST frame the choice as **product versus product**:
  **CloudWatch Omni** (Application/Agent Observability — Spaces, Domains, a Dataset)
  versus **CloudWatch** (log groups, alarms, Log Insights, Application Signals). That
  is the framing `aws-observability` → `references/cloudwatch-omni/concepts.md` uses,
  so the customer hears one question whichever skill asks it. Do not describe it only
  as a difference in interaction style.
- In the same message, you MUST explain the boundary as **setup versus use**, so the
  customer can place their own request: creating or configuring a Domain, Space,
  grant, or Access Profile, getting telemetry flowing into Omni for the first time,
  and instrumenting an application or agent for Omni are first-time Omni setup (this
  skill); querying telemetry, building dashboards, and configuring alerts are
  day-to-day use, and belong — with anything about Application Signals, X-Ray,
  synthetics, or CloudWatch alarms — to `aws-observability`. Naming the table above
  in prose is enough; do not start any of it.
- Having asked, you MUST then **stop and wait**. Do NOT go on to give the Omni setup
  sequence, or begin Domain or Space creation, in the same reply; that is the same as
  assuming Omni and it wastes the question.
- If the customer **did** name Omni, Application Observability, Agent Observability,
  a Space, or a Domain, it is Omni — continue here for a setup step, or route to
  `aws-observability` for use. If they named a CloudWatch feature (log group, alarm,
  Log Insights, Application Signals, X-Ray, synthetics), route to `aws-observability`.
- If the customer already has a working Space and is asking about queries,
  dashboards, or alerts, you MUST stop and route to `aws-observability`.
- If the request names Application Signals, ServiceEvents, or Dynamic
  Instrumentation, you MUST stop and route to `aws-observability`. Those are CloudWatch
  features and are not part of Omni setup.

## Additional resources

- `references/cloudwatch-omni/spaces-and-domains.md` — creating an account-scoped Domain and a Space
- `references/cloudwatch-omni/org-domains.md` — a Domain shared across an AWS Organization
- `references/cloudwatch-omni/access-grants.md` — giving principals access to a Space
- `references/cloudwatch-omni/access-profiles.md` — bounding what an async workload may do
- `references/cloudwatch-omni/instrumentation/collector.md` — deploying a collector that exports to
  CloudWatch's OTLP endpoints
- `references/cloudwatch-omni/data-forwarding-and-centralization.md` — forwarding telemetry already
  in CloudWatch into the Dataset
- `references/cloudwatch-omni/instrumentation/instrumentation.md` — instrumenting applications
- `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md` —
  instrumenting AI agents
