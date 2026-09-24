# CloudWatch Omni concepts, and Omni vs. CloudWatch

CloudWatch Omni — the product surface behind **CloudWatch Application Observability**
and **CloudWatch Agent Observability** — is an AI-native observability experience. A
customer investigates their systems by asking questions in conversation, over one
correlated store of logs, traces, and metrics, rather than by assembling queries and
dashboards by hand.

This file is orientation, not procedure. It exists so an agent can (a) understand Omni
vocabulary and (b) tell whether a customer's ask is a CloudWatch Omni feature or a
CloudWatch feature — the two coexist in the same account, and choosing wrongly
sends the agent confidently down the wrong path. Every procedure lives in a sibling
reference, linked from each section and indexed at the end.

> **Always state these, in any answer drawn from this file:**
>
> - Omni is a **separate service** alongside CloudWatch, not a replacement for
>   it. Log groups, metric namespaces, alarms, and dashboards keep working unchanged.
> - The setup order is **Domain, then Space, then grants, then telemetry in, then
>   instrumentation**.
> - Access Profiles are **conditional**, needed only when async workloads (alerts,
>   integrations) are involved. Name that condition, do not omit it.
> - Say, in these words or close to them, that **instrumentation or forwarding started
>   before a Space exists appears to succeed while delivering telemetry nowhere the
>   customer can see**. Never describe the setup order without this warning.
> - A **knowledge question** about Omni is answered directly. Only a request that must
>   **act on a Space** is gated behind the probe in
>   [How to tell which one the customer means](#how-to-tell-which-one-the-customer-means).

## Contents

- [What CloudWatch Omni is](#what-cloudwatch-omni-is)
- [Glossary](#glossary)
- [Omni vs. CloudWatch: feature equivalence](#omni-vs-cloudwatch-feature-equivalence)
- [How to tell which one the customer means](#how-to-tell-which-one-the-customer-means)
- [Setting Omni up from nothing](#setting-omni-up-from-nothing)
- [Files in this folder](#files-in-this-folder)

## What CloudWatch Omni is

**A separate service with its own control plane.** CloudWatch answers under
`aws cloudwatch`, `aws logs`, `aws xray`, and friends. Omni answers under
`aws cloudwatchomni`: endpoint prefix `cloudwatch-omni`, regional endpoint
`cloudwatch-omni.<region>.api.aws`, SigV4 signing name `cloudwatch`. The shared
signing name is the only thing the two have in common at the wire level — a CloudWatch
or X-Ray client cannot reach a Space, an Omni alert, a view, or an Omni
dashboard at any version, and `aws cloudwatch <omni-operation>` always fails. The
wire protocol is Smithy RPC v2 CBOR (`rpcv2Cbor`) — calls POST to
`/service/CloudWatchOmniFrontend/operation/<Op>` with CBOR bodies — so a caller needs
an AWS SDK or CLI that carries the `cloudwatchomni` model; a hand-rolled
JSON-over-SigV4 client cannot call it. The
API, CLI/SDK, CloudFormation, and coding-agent paths are covered once, in
[programmatic-access.md](programmatic-access.md); do not restate them here.

**Its own data model.** Everything in Omni hangs off a **Space**, which is the unit
of tenancy, access, and querying. The Space stores no telemetry of its own: it reads
the account's CloudWatch **Dataset** — one per account per Region,
`arn:aws:cloudwatch:<region>:<account>:dataset/default`, a CloudWatch resource that
exists whether or not a Space does. Through a Space the customer works with:

- the **Dataset** — the correlated store that queries run against, owned by
  CloudWatch and read by the Space;
- **SQL over logs and traces** (`logs.default`, `traces.default`) and **PromQL over
  metrics** — two query languages, one per signal shape, see
  [query/sql-logs-traces.md](query/sql-logs-traces.md) and
  [query/promql-metrics.md](query/promql-metrics.md);
- **views** (named, reusable SQL), **alerts** (SQL or PromQL rules with
  OK/WARNING/CRITICAL/NODATA states), and **dashboards** (a JSON `panels[]` body on a
  fixed grid);
- a **context graph** relating the services, resources, and deployments the telemetry
  describes;
- for AI agents, **evaluation** of traces against evaluators, with stored scores that
  are themselves queryable.

**What it is NOT.** Omni does not replace CloudWatch Logs log groups, metric
namespaces, metric/composite/anomaly alarms, CloudWatch dashboards, Log Insights, X-Ray,
Application Signals, Synthetics, or CloudTrail. All of those keep working exactly as
before, are configured through their own APIs, and are documented under
[`../cloudwatch/`](../cloudwatch/). In fact a Space's data *is* CloudWatch data:
telemetry lands in CloudWatch first (through the standard per-signal OTLP endpoints,
the usual agents and SDKs); OTel metrics land in the Dataset natively, and a dataset
integration copies logs and traces into it. Omni is a second way to work with that data, not a migration away from it.

**Two experiences, one platform.** *Application Observability* is APM, distributed
tracing, and log analysis for services. *Agent Observability* is the same platform
applied to LLM/AI-agent workloads — GenAI spans, sessions, tool calls, and quality
evaluation. They share the Space, the Dataset, the SQL dialect, alerts, and
dashboards; they differ in what the telemetry contains and in the agent-specific
instrumentation and evaluation references.

## Glossary

One or two sentences each. The right-hand column is the reference that owns the
topic — read it before acting; do not act from this table alone.

| Term | What it is | Owning reference |
|---|---|---|
| **Domain** | The identity boundary. Carries the authorization provider (IAM or IAM Identity Center) and owns the endpoint URL customers reach Omni through — the endpoint derives from the Domain's name, so the name is not cosmetic. One per account, or one shared across an AWS Organization. | `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/spaces-and-domains.md`, `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/org-domains.md` |
| **Space** | The access boundary over the account's Dataset, in exactly one account and one Region, created under a Domain; it holds no telemetry of its own. **At most one per account per Region** — separate Regions mean separate Spaces and separate grants. | `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/spaces-and-domains.md` |
| **Dataset** | The account's CloudWatch store that queries run against — one per Region, `arn:aws:cloudwatch:<region>:<account>:dataset/default`, a CloudWatch resource rather than part of a Space. OTel metrics land in it natively (queried with PromQL); logs and traces reach it when a **dataset integration** copies the account's log groups — including `aws/spans` — into it. Creating a Space does not make data appear; a Space only reads what is already there. | `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/data-forwarding-and-centralization.md` |
| **Access grant** | Attaches one principal — person or group in Identity Center, IAM role or user, or async workload — to one Space at a permission level (`READ`, `READ_WRITE_DELETE`, `SPACE_ADMIN`, `CUSTOM`). How people and profiles reach data *through Omni*: an Identity Center user, console session, or Access Profile with no matching grant can read nothing in the Space, including its creator. A direct IAM caller in the owning account is the exception — with no matching grant it falls through to its own IAM policy (see [programmatic-access.md](programmatic-access.md)). Grants bound the Omni plane only; source log groups stay readable under their own IAM. | `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-grants.md` |
| **Access Profile** | A named boundary for **async workloads** — an alert running an investigation, an integration calling another system — that act with no person in the loop. Carries no permissions of its own; grants supply them (what the profile may do, and who may assume it). An alert's `profileId` names one. | `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-profiles.md` |
| **View** | A named, stored SQL query referenced as a table — `FROM view.<name>` — so common query logic is reused instead of repeated. | [query/views.md](query/views.md) |
| **Alert** (vs. **alarm**) | Omni's rule-based notification: a SQL or PromQL rule evaluated on a schedule, with `OK`/`WARNING`/`CRITICAL`/`NODATA` states, contributors, and notification rules. A completely separate resource from a CloudWatch **alarm** (metric + threshold, `OK`/`ALARM`/`INSUFFICIENT_DATA`, SNS actions). The word the customer uses is the first clue. | [alerts.md](alerts.md); CloudWatch: [../cloudwatch/alarms.md](../cloudwatch/alarms.md) |
| **Dashboard (Omni)** | A JSON `panels[]` body on a fixed 60-column grid, most panels charting Omni SQL or PromQL. Distinct from a CloudWatch dashboard (a `widgets[]` body managed by `PutDashboard`). | [dashboards.md](dashboards.md); CloudWatch: [../cloudwatch/dashboards.md](../cloudwatch/dashboards.md) |
| **Context graph** | The graph Omni builds from a Space's telemetry relating services, resources, deployments, and the signals about them, used to correlate across logs, traces, and metrics during an investigation. The CloudWatch counterpart in spirit is the Application Signals service map. | [context-graph.md](context-graph.md) |
| **Insight / anomaly** | An automatically detected deviation in a Space's telemetry, surfaced with the signals that contribute to it, for the customer to investigate conversationally. Distinct from a CloudWatch **anomaly-detection alarm**, which fits a band to one metric and alarms when it leaves the band. | [context-graph.md](context-graph.md) (investigating from an insight or anomaly); CloudWatch: [../cloudwatch/alarms.md](../cloudwatch/alarms.md) |
| **Evaluator / evaluation** | Agent Observability's quality mechanism: an **evaluator** (built-in, third-party, or custom) scores an agent's traces or sessions; an **evaluation** runs one or more evaluators either on demand or continuously (online). Scores are stored as telemetry and read back with SQL. Evaluation **datasets** hold versioned examples built from traces. | [agent-evaluation.md](agent-evaluation.md) |
| **Agent Observability** | The Omni experience for LLM/AI-agent workloads — GenAI spans from ADOT or OpenInference instrumentation, sessions, tool calls, and evaluation — on the same Space and query surface as Application Observability. | `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md`, [query/sql-logs-traces.md](query/sql-logs-traces.md) |
| **Integration** | An account-level connection to an external system (today: Slack) that Spaces are separately granted permission to use, and that alerts can notify through. | `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/slack-integration.md` |

## Omni vs. CloudWatch: feature equivalence

Most customer needs have an answer on both sides. Use this table to name the pair,
then use [the next section](#how-to-tell-which-one-the-customer-means) to decide
which side the customer is on. A dash means the capability exists on one side only —
do not improvise an equivalent on the other.

| Customer need | CloudWatch | CloudWatch Omni | How to tell which they mean |
|---|---|---|---|
| Query logs | Logs Insights — pipe syntax over log groups — [../cloudwatch/log-insights.md](../cloudwatch/log-insights.md) | SQL over `logs.default` — [query/sql-logs-traces.md](query/sql-logs-traces.md) | `fields`/`filter`/`stats`, a log group name → CloudWatch. `SELECT … FROM logs.default`, a Space, `@timestamp`/`@record` → Omni. |
| Query traces | X-Ray / Transaction Search, trace IDs and segments — [../cloudwatch/tracing.md](../cloudwatch/tracing.md) | SQL over `traces.default` — [query/sql-logs-traces.md](query/sql-logs-traces.md); enabling Transaction Search (account-level, per Region) is a prerequisite for Omni traces | X-Ray console, `get-trace-summaries`, sampling rules → CloudWatch. `traces.default`, spans queried in SQL, a Space → Omni. |
| Query metrics | Namespaces, dimensions, `GetMetricData`, metric math — [../cloudwatch/metrics.md](../cloudwatch/metrics.md) | PromQL over the Space's metrics — [query/promql-metrics.md](query/promql-metrics.md) | Namespace/dimension/statistic vocabulary → CloudWatch. PromQL selectors, labels, `rate()`/`histogram_quantile()` → Omni. Metrics have **no SQL surface** in Omni. |
| Notify on a condition | **Alarm** — metric, composite, anomaly detection — [../cloudwatch/alarms.md](../cloudwatch/alarms.md) | **Alert** — SQL or PromQL rule, `profileId`, contributors — [alerts.md](alerts.md) | "CloudWatch alarm", "metric alarm", "composite alarm", "anomaly alarm", "PromQL alarm", `ALARM`/`INSUFFICIENT_DATA`, an SNS alarm action → CloudWatch. `WARNING`/`CRITICAL`/`NODATA`, `profileId`, an alert ARN, `ListAlerts` → Omni. A bare "alarm" or "alert" with no other product signal is ambiguous — probe for a Space (step 3 below). Do not redirect an Omni alert question to alarms. |
| Reusable saved queries | Logs Insights saved queries — [../cloudwatch/log-insights.md](../cloudwatch/log-insights.md) | **Views** (`FROM view.<name>`) — [query/views.md](query/views.md) | "View" as a table you query from → Omni. |
| Dashboards | `widgets[]` body, `PutDashboard`, cross-account/Region — [../cloudwatch/dashboards.md](../cloudwatch/dashboards.md) | `panels[]` body on a 60-column grid — [dashboards.md](dashboards.md) | Widgets, metric-widget JSON, sharing → CloudWatch. Panels, a Space, SQL/PromQL panel queries → Omni. |
| Instrument / onboard a service | Application Signals via ADOT + ServiceEvents — [../cloudwatch/application-signals-onboarding.md](../cloudwatch/application-signals-onboarding.md), per-platform guides under [../cloudwatch/appsignals-guides/](../cloudwatch/appsignals-guides/) | Plain ADOT SDK + a collector, exporting toward a Space — `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/instrumentation/instrumentation.md`, `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/instrumentation/collector.md`, per-platform `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/instrumentation/<platform>-<language>.md` | Names Application Signals, ServiceEvents, the `amazon-cloudwatch-observability` add-on, or the service map → CloudWatch. Names a Space, Omni, or "Application Observability" → Omni. Names neither → probe `list-spaces` in the target Region: a Space → the Omni path; no Space → the CloudWatch path. |
| Instrument an AI agent | — (X-Ray sees generic spans only) | ADOT or OpenInference for LangChain, LangGraph, Strands, CrewAI, OpenAI Agents, Vercel AI — `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md` | Any agent-framework instrumentation request is Omni. |
| Access control | IAM policies on log groups, metric namespaces, X-Ray — no dedicated reference | Access grants and Access Profiles on a Space — `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-grants.md`, `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-profiles.md` | "Who can see the Space", a permission level, a `profileId` → Omni. An IAM policy on `logs:*`/`cloudwatch:*` actions → CloudWatch. A grant does not restrict the source log groups. |
| Debug a live service with breakpoints / snapshots | **Dynamic Instrumentation** — [../cloudwatch/dynamic-instrumentation.md](../cloudwatch/dynamic-instrumentation.md) | — | CloudWatch only. Route there even if the customer is otherwise an Omni user. |
| Synthetic monitoring / canaries | **Synthetics** — [../cloudwatch/synthetics.md](../cloudwatch/synthetics.md) | — | CloudWatch only. |
| Who changed what, when (API auditing) | **CloudTrail** — [../cloudwatch/cloudtrail.md](../cloudwatch/cloudtrail.md) | — | CloudWatch only. |
| Service topology / dependencies | Application Signals **service map** — [../cloudwatch/application-signals-onboarding.md](../cloudwatch/application-signals-onboarding.md) | **Context graph** — [context-graph.md](context-graph.md) | "Service map", SLOs, Application Signals → CloudWatch. "Context graph", entity relationships inside a Space → Omni. |
| Evaluate an AI agent's quality | — | Evaluators, on-demand and online evaluation, datasets — [agent-evaluation.md](agent-evaluation.md) | Omni only. |
| Telemetry from Azure | CloudWatch agent on an Azure VM / AKS lands it in CloudWatch — `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/azure-ingestion/azure-ingestion.md` | …then forwarded into the Dataset — `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/data-forwarding-and-centralization.md` | The same path serves both; Omni adds the forwarding step. Azure *resource* logs (the VPC-flow-log analogue) are not available either way. |
| Chat notifications | SNS-driven; no dedicated reference | **Slack integration** — `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/slack-integration.md` | "Connect Slack to the Space", an alert notifying `slack` → Omni. |
| General "it's broken" troubleshooting | [../cloudwatch/troubleshooting.md](../cloudwatch/troubleshooting.md) | The sibling reference for the failing piece (ingestion, forwarding, grants, alerts) | Decide the side first, then troubleshoot on that side. |

## How to tell which one the customer means

Natural wording — "set up an alert for high latency", "build a dashboard", "query my
logs" — does not say which product the customer has in mind. Decide in this order.

1. **A knowledge or how-to question needs no probe.** "What is an Omni alert", "how
   do I call Omni from code", "does Omni have an SDK", "what is a Space" — answer from
   the Omni references directly. Do NOT gate the answer behind an account check and do
   NOT divert it to CloudWatch. Whether a capability exists in the product is
   not a fact about this account. [programmatic-access.md](programmatic-access.md) in
   particular is **never** gated.

2. **The customer's own words are the strongest signal.** "Omni", "Application
   Observability", "Agent Observability", a `spaceId`, a `profileId`, an alert ARN,
   `logs.default`, `FROM view.` — take that as Omni. "CloudWatch alarm", "metric alarm",
   "composite alarm", "anomaly alarm", "PromQL alarm", "log group", "namespace",
   "Log Insights", "X-Ray", "Application Signals", "ServiceEvents", "Dynamic
   Instrumentation", "canary", "CloudTrail" — take that as CloudWatch. A bare "alarm"
   or "alert" with no other product signal is ambiguous — go to step 3 and probe.

3. **A request that must ACT on a Space is probed first.** Creating, reading, or
   querying an Omni alert, dashboard, or view, or running Omni SQL against live data,
   requires a Space to exist in the target Region. Check before acting rather than
   guess:

   ```bash
   aws cloudwatchomni list-domains
   aws cloudwatchomni list-spaces --region <target-region>
   ```

   - **A Domain and a Space exist in the target Region** → Omni is enabled; use the
     Omni column of the table above.
   - **No Space in that Region** → serve the same need from the CloudWatch column
     instead (alert → [../cloudwatch/alarms.md](../cloudwatch/alarms.md), dashboard →
     [../cloudwatch/dashboards.md](../cloudwatch/dashboards.md), query →
     [../cloudwatch/log-insights.md](../cloudwatch/log-insights.md), metrics →
     [../cloudwatch/metrics.md](../cloudwatch/metrics.md)). If the customer explicitly
     asked for Omni, say the Space does not exist yet and offer the
     [setup sequence](#setting-omni-up-from-nothing) rather than silently switching
     products.
   - **The probe itself errors** with "not yet supported", an unknown service, or an
     endpoint that does not resolve → the CLI/SDK in use predates Omni's service
     model. That is **not** evidence that Omni is disabled or that no Space exists,
     and must not be reported as "Omni is unavailable". Fall back to the customer's
     own signal (step 2) and read
     [programmatic-access.md](programmatic-access.md) for the client-version
     explanation.

4. **Only if all of that is inconclusive, ask** — and frame the choice as *CloudWatch
   Omni (a Space, SQL/PromQL, alerts) versus CloudWatch (log groups, metric
   alarms, Log Insights)*, not as a difference in interaction style. Having asked,
   **stop and wait**. Do not also give the Omni setup sequence in the same reply; that
   is the same as assuming Omni and wastes the question.

**Constraints:**

- A Space is **one per account per Region**. You MUST probe the Region the request
  targets, not the default one. An Omni query against the wrong Region returns an
  empty result that is easily misread as "no data".
- If the customer already has a working Space and is asking about queries,
  dashboards, or alerts, you MUST NOT restart setup — go to the reference for that task.
- If the request names Application Signals, ServiceEvents, Dynamic Instrumentation,
  Synthetics, or CloudTrail, you MUST route to the CloudWatch reference. Those are
  CloudWatch-only and have no Omni equivalent to substitute.
- You MUST NOT answer an Omni programmatic question with the CloudWatch or
  X-Ray CLI/SDK, and you MUST NOT conclude from a failed probe that Omni has no API.

## Setting Omni up from nothing

### How the pieces connect

The relationships matter more than the definitions, because each determines
something a customer will otherwise get wrong.

- A **Domain contains Spaces**. The Domain decides who can authenticate; the Space
  decides who reads the account's Dataset in its Region. Deleting a Domain requires
  deleting its Spaces first.
- A **Space is per account and per Region**. This is the single most common source of
  surprise: access that works in one Region appears broken in another, because a
  different Region means a different Space and therefore different grants.
- **Grants attach principals to a Space**, not to a Domain. Domain-wide
  administration exists only for organization Domains, and it is `ADMIN` over every
  Space in the Domain.
- An **Access Profile sits between a workload and a Space**. The workload gets a grant
  that lets it assume the profile; the profile gets grants describing what it may do.
  Both are required, and missing either produces a different failure.
- **Telemetry reaches the Dataset, not the Space directly**, and it reaches the
  Dataset by way of CloudWatch. Setting up a Space does not make data appear;
  ingestion and forwarding are separate steps. The Dataset is CloudWatch's, so both
  work with no Space in the account — but nothing in Omni can read the result until a
  Space exists.

### Setup order

Working from nothing, the sequence is (first-time setup is owned by the
`setting-up-cloudwatch-observability` skill):

1. **Domain** — account-scoped (`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/spaces-and-domains.md`)
   or shared across an AWS Organization (`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/org-domains.md`).
2. **Space** — under the Domain, in the Region the customer wants. Same two files.
3. **Access grants** — so people can reach the Space.
   `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-grants.md`.
4. **Telemetry in** — two halves, and most customers starting from nothing need both:
   - *Getting telemetry into CloudWatch.* Deploy a collector so an instrumented
     workload has somewhere to export to
     (`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/instrumentation/collector.md` and the
     per-platform `collector-*.md`). The collector exports straight to
     CloudWatch's own per-signal OTLP endpoints.
     For traces, enabling Transaction Search (account-level, per Region) is a prerequisite
     before they reach Omni.
   - *Getting it from CloudWatch into the Dataset.* Create the dataset integration so
     logs and traces (including `aws/spans`) are copied into the Dataset the Space
     reads, including any log groups the customer already had
     (`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/data-forwarding-and-centralization.md`).
     Metrics are not forwarded: customer OTel metrics land in the Dataset natively, and
     AWS-vended CloudWatch metrics get there through OTel enrichment
     (`aws observabilityadmin start-telemetry-enrichment`, then
     `aws cloudwatch start-otel-enrichment`).
5. **Instrumentation** — so applications and agents emit telemetry in the first
   place. `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/instrumentation/instrumentation.md` for
   services (per-platform × language files alongside it);
   `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md`
   for AI agents.

Two things are **conditional** rather than sequential:

- **Access Profiles** — only when async workloads are involved: an alert (every alert
  runs under a `profileId`) or an integration.
  `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-profiles.md`.
- **Slack** — only if the customer wants alerts or investigations to reach a Slack
  workspace. `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/slack-integration.md`.

**Constraints:**

- You MUST establish where in this sequence the customer already is before starting
  anything. Most requests join partway through, and re-running an earlier step
  conflicts rather than being idempotent (one Domain per account; one Space per
  account per Region).
- You SHOULD create the Space before instrumentation or forwarding. Neither
  technically requires one — both write to the account's CloudWatch Dataset and
  succeed without a Space — but nothing in Omni can read the result until a Space
  exists, so a customer who checks Omni first sees an empty product and reads it as a
  failure.
- You SHOULD tell the customer the whole sequence when they are starting from
  nothing, so a working Space with no telemetry in it does not read as a failure.
- You MUST NOT confuse Omni instrumentation with Application Signals onboarding. Omni
  instrumentation is the plain ADOT SDK plus a collector; the
  `amazon-cloudwatch-observability` add-on, ServiceEvents, and port 4316 belong to the
  CloudWatch path under [`../cloudwatch/`](../cloudwatch/).

## Files in this folder

| File | One line |
|---|---|
| [concepts.md](concepts.md) | This file — vocabulary, Omni vs. CloudWatch, how to tell them apart, the setup arc |
| [programmatic-access.md](programmatic-access.md) | The public SigV4 API, CLI/SDK (and why an unsupported-service error is a client-version issue), CloudFormation/CDK, coding-agent skills; never gated by a Space probe |
| [alerts.md](alerts.md) | Omni alerts — SQL/PromQL rules, `profileId`, FIELD_VALUE vs. COUNT_OF_RESULTS, OK/WARNING/CRITICAL/NODATA, notification rules, the alert APIs |
| [dashboards.md](dashboards.md) | Omni dashboards — the `panels[]` JSON body, panel types, visualizations, the 60-column grid, archetype templates |
| [context-graph.md](context-graph.md) | The context graph — entities and relationships Omni builds from a Space's telemetry |
| [agent-evaluation.md](agent-evaluation.md) | Agent quality — evaluator discovery, on-demand and online evaluation, custom evaluators, reading stored scores back |
| [query/sql-logs-traces.md](query/sql-logs-traces.md) | The SQL dialect over `logs.default` / `traces.default` — addressing, system fields, schema discovery, functions, TABLESAMPLE |
| [query/promql-metrics.md](query/promql-metrics.md) | PromQL over a Space's metrics — SQL vs. PromQL decision, discovering names and labels, Omni's `@`-labels and `__name__` matcher, per-service metric catalog, reading an empty result |
| [query/views.md](query/views.md) | Views — named SQL referenced as `FROM view.<name>`; create/update/delete/list, naming rules, composition |
| `setting-up-cloudwatch-observability` skill | First-time setup lives there, not here: Domains and Spaces, org-wide Domains, access grants and Access Profiles, forwarding into the Dataset, Slack, Azure ingestion, and instrumenting applications (`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/instrumentation/`) and AI agents (`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/omni-agents-instrumentation/`). |
