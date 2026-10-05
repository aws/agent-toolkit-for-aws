---
name: aws-observability
description: >-
  Builds, configures, debugs, and optimizes AWS observability - operator-symptom questions and detecting Omni
  vs classic CloudWatch. CloudWatch on an already-reporting service: Log Insights, metric/composite/anomaly
  alarms, custom metrics/EMF, dashboards, X-Ray/ADOT tracing, canaries, CloudTrail, Dynamic Instrumentation
  (live breakpoints/snapshots), the Application Signals service map, and fleet health views. CloudWatch Omni
  on an existing Space: SQL over logs and traces, PromQL over metrics, Omni dashboards, Omni alerts, context
  graph for root cause, programmatic/IaC access (API/SDK/CLI/CloudFormation), driving Omni from a coding agent
  or skills, and evaluating AI agent quality from traces - on-demand and online scoring of live traffic,
  readback, custom evaluators. For first-time setup - creating an Omni Space, granting access, ingestion, or
  ADOT instrumentation for Application Signals (ServiceEvents, CI/CD metadata) or Omni - use
  setting-up-cloudwatch-observability. Not for app logging or threat detection.

metadata:
  version: "7"
---

# AWS Observability

## Overview

Domain expertise for AWS observability across metrics, logs, and traces, for **two
products** that share the CloudWatch name but are separate services with separate
control planes, data models, and APIs:

| | CloudWatch | CloudWatch Omni |
|---|---|---|
| **What it is** | Log groups, metric namespaces, alarms, Log Insights, X-Ray, Application Signals | Application Observability / Agent Observability. A **Space** per account per Region is the access boundary over the account's CloudWatch **Dataset** (OpenTelemetry logs, traces, and metrics); the Dataset is a CloudWatch resource the Space reads, not something the Space contains |
| **Control plane** | `aws cloudwatch`, `aws logs`, `aws xray`, `aws application-signals` | `aws cloudwatchomni` (endpoint prefix `cloudwatch-omni`, signing name `cloudwatch`) |
| **Query** | Log Insights query language; GetMetricData | SQL over `logs.default` / `traces.default`; PromQL over metrics; named views |
| **Notify** | Alarms (metric, composite, anomaly) | **Alerts** (SQL/PromQL rule, contributors, OK/WARNING/CRITICAL/NODATA) |
| **Topology** | Application Signals service map | **Context graph** (GetContextGraph) |
| **Access** | IAM only | Domain → Space → **access grants** and **access profiles** (set up in `setting-up-cloudwatch-observability`) |
| **Only here** | Dynamic Instrumentation, Synthetics canaries, CloudTrail auditing, EMF | Agent-quality evaluation, views, context graph |
| **First-time setup** | Application Signals onboarding — ADOT auto-instrumentation, the `amazon-cloudwatch-observability` add-on, ServiceEvents, CI/CD metadata | Domain → Space → grants → telemetry in → plain-ADOT instrumentation |
| **References** | `references/cloudwatch/` | `references/cloudwatch-omni/` |

**This skill covers *using* both products, never setting either one up.** Both first-time
setup paths above live in **`setting-up-cloudwatch-observability`** (same two-folder split);
route there rather than describing an onboarding procedure from memory.

Enabling Omni does not replace CloudWatch; log groups, metrics, and alarms keep
working, and most customers use both.

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) — enables
running CLI commands, querying CloudWatch, and validating configurations directly. All
guidance also works with standard AWS CLI access.

**Note:** Reference files contain specific runtime versions, quota values, and feature
matrices that may change. When precision matters (e.g. deploying to production, choosing a
runtime, or checking a quota), confirm values against current AWS documentation rather
than relying solely on the values in these files.

## Scope guard — is this an observability request?

This skill owns the scope decision for every request routed to it, and this section is
its sole home.

**If a request is NOT about AWS observability with CloudWatch or CloudWatch Omni
(weather, trivia, general chit-chat, non-observability coding), decline it in one
sentence: state plainly that it is out of scope, never fabricate an answer, and never
claim a false capability limitation (no "no internet access", no "no weather data") —
the reason is simply that it is out of scope. Then redirect by naming what this skill
does cover: querying CloudWatch and CloudWatch Omni logs, traces, and metrics, building
dashboards, configuring alerts, investigating a service, or agent evaluation.**

Do **not** attempt the off-topic task, and do **not** call a tool or run a query in
pursuit of it. Keep it brief: no lecture, no long refusal.

## Step 0 — CloudWatch or CloudWatch Omni?

Decide this before routing. The natural wording ("set up an alert for high latency",
"build a dashboard", "query my logs") does not say which product the customer means.

1. **The customer names the product** — "Omni", "Application Observability", "Agent
   Observability", a Space, Domain, Dataset, access grant, `spaceId`, `cloudwatch-omni`,
   Omni SQL, PromQL, views, context graph, evaluators, agent evaluation / scoring traces /
   online or continuous evaluation / `gen_ai.evaluation`, and OTel span vocabulary
   (`traces.default`, `logs.default`, spans, `durationNano`, `status.code`, resource
   attributes, `service.name`) → **Omni**. "Log Insights", "log group", "metric
   namespace", "CloudWatch alarm", "metric alarm", "composite alarm", "anomaly alarm",
   "X-Ray", "Application Signals", "canary", "CloudTrail", "Dynamic Instrumentation" →
   **CloudWatch**. A "log group" named inside an agent-evaluation request is the
   online-evaluation data source to verify, not a CloudWatch signal. A bare "alarm" (or "alert") with no other product
   signal is ambiguous — fall through to rule 3 and probe: a Space → Omni alert
   ([alerts.md](references/cloudwatch-omni/alerts.md)); no Space → CloudWatch alarm
   ([cloudwatch/alarms.md](references/cloudwatch/alarms.md)). Exception: a "PromQL
   **alarm**" is a CloudWatch alarm on OTel metrics
   ([cloudwatch/alarms.md](references/cloudwatch/alarms.md)) — "alarm" wins over "PromQL".
2. **Knowledge or how-to question** ("what is an Omni alert", "does Omni have an API",
   "how do alerts differ from alarms") → answer from the reference files directly. Do
   **not** probe the account, and do not divert to the other product. Whether a
   capability exists is a fact about the product, not the account.
   [concepts.md](references/cloudwatch-omni/concepts.md) carries the full feature-equivalence matrix.
2a. **Authoring / how-to alert request** — "create / set up / write an Omni alert that
   fires when X", "how should I alert on Y" — with no Space or Region supplied and no
   go-ahead to actually create it, is a **HOW-TO** request. Deliver the authoring guidance
   (the alert row of "Must-state checklists" below, then
   [alerts.md](references/cloudwatch-omni/alerts.md)) **FIRST**, from the reference files. Do
   **NOT** stall on a Region/Space clarifying question and do **NOT** fall back to a
   CloudWatch alarm for a request that explicitly says "Omni alert". Probe the account only
   once the user supplies a Space/Region or asks you to create it.
2b. **A telemetry object is already in the prompt** — the user pastes, or the UI passes as
   context, a span, trace, log record, or query result and asks what it means, what errors
   it has, or how long it took. This is **not** a live-data request: do not probe the
   account, run a query, or ask the user to fetch it again. Read it in place per the
   "Reading a span or trace you already have" section of
   [query/sql-logs-traces.md](references/cloudwatch-omni/query/sql-logs-traces.md) and
   state every item in its must-state list.
2c. **A query request whose live result is empty or unreachable** ("show me the slowest
   spans", "which traces failed") is still answered with the **methodology** — the exact
   query and the field rules that make it correct (see the must-state callouts in
   [query/sql-logs-traces.md](references/cloudwatch-omni/query/sql-logs-traces.md)). Zero
   rows, a wrong-Region Space, or an unreachable endpoint is reported as a finding
   alongside the query, never as the whole answer.
3. **Request that must act on live data, and the wording is ambiguous** (not a Step 0.5
   content question, which is answered from the catalog) → probe the target Region first:

   ```
   aws cloudwatchomni list-domains
   aws cloudwatchomni list-spaces --region <target-region> --query "items[?region=='<target-region>']"  # account-global; filter to the Region
   ```

   - `list-spaces` is **account-global** (the `--region` flag only selects the endpoint), so filter its result to the target Region as shown rather than reading a non-empty list as proof; a Space is one per account per Region. See `references/cloudwatch-omni/concepts.md` for the full Region-probe rationale.
   - A Domain and a Space in that Region (a non-empty filtered list) → **Omni**.
   - No Space in that Region (an empty filtered list) → **CloudWatch**: alarms → [cloudwatch/alarms.md](references/cloudwatch/alarms.md),
     dashboards → [cloudwatch/dashboards.md](references/cloudwatch/dashboards.md), queries →
     [cloudwatch/log-insights.md](references/cloudwatch/log-insights.md), metrics →
     [cloudwatch/metrics.md](references/cloudwatch/metrics.md). If the customer explicitly asked
     for Omni and has no Space, that is a first-time setup — see step 4.
   - The probe itself errors ("not yet supported", unknown service, endpoint does not
     resolve) → the CLI/SDK model in use lacks `cloudwatchomni`. That is **not** evidence
     Omni is absent and must not be reported as "Omni is unavailable". The customer's
     installed AWS CLI/SDK most likely predates the service. If the request carried
     **any** Omni signal, give the customer the upgrade command to run (AWS CLI v2
     reinstall or `brew upgrade awscli`; `pip install -U boto3 botocore`) and have them
     re-run `aws cloudwatchomni list-domains` — exact steps in
     [programmatic-access.md](references/cloudwatch-omni/programmatic-access.md). **Never
     run a package-manager upgrade or installer on the host yourself** (`brew`, `pip
     install -U`, `.pkg`/MSI); it mutates the customer's machine beyond the request and
     can break unrelated tooling — hand over the command and continue with the guidance.
     Never substitute a CloudWatch or X-Ray command for an Omni request. If the request
     carried **no** Omni signal, do not block on the upgrade. When you are already going
     back to the customer for missing inputs (for example an alert's threshold and
     period), ask which product they want in that same question: say the Space probe could
     not run on this CLI, describe both options, and build neither until they answer. When
     the request is fully specified or says not to ask, proceed on the CloudWatch path (the
     pre-Omni default) and mention the upgrade only in passing.
   - Still inconclusive → ask the customer.
4. **First-time setup, on EITHER product** → **STOP and route to the
   `setting-up-cloudwatch-observability` skill.** This skill covers a service or Space that
   already reports and holds no onboarding procedure for either product, so there is nothing
   here to fall back on: not Omni setup (creating a Domain or Space, granting access,
   ingestion, forwarding, Slack, instrumenting an app or AI agent for a Space) and not
   CloudWatch setup (**onboarding a service to Application Signals** — ADOT
   auto-instrumentation, the `amazon-cloudwatch-observability` add-on, monitored service,
   ServiceEvents, CI/CD metadata, the per-platform enablement guides). Any
   instrumentation / ADOT / collector request is a setup request either way; the setup skill
   owns the product decision too, so hand the whole request over rather than probing
   `list-spaces` yourself. Application Signals **once it is reporting** — service map,
   alarms on its metrics, Dynamic Instrumentation debugging — belongs here.

**Under-specified alert requests:** When an alert or alarm request names what to watch (a
symptom or a service) but not the inputs it needs — the threshold value and the evaluation
period — ask for those rather than inventing them. Notifications are optional (per
alerts.md), so ask for a notification destination only if the user wants to be notified.
This holds on both paths (an Omni alert or a CloudWatch alarm).

**Under-specified dashboard requests:** When a dashboard request names what to show but not
which metrics, panels, or layout, ground those against the data and confirm the panel set
rather than inventing panels; a dashboard has no threshold, period, or notification. For ANY
dashboard authoring/save request, also open [dashboards.md](references/cloudwatch-omni/dashboards.md)
and surface its "Facts you MUST surface when building or saving an Omni dashboard" checklist
(see "Must-state checklists" below). Which signals or panels a named resource
type needs is a Step 0.5 catalog question, not a dashboards-file question.

### Step 0.5 — Service-health investigation (routing)

A large share of real questions are phrased as an operator symptom, not as a tool: "is my
`<service>` throttled / slow / erroring / unhealthy," "which of my `<service>`s are
`<symptom>`," "what's the health of my `<service>`," "what does `<service>` depend on and
which is broken," "what signals / what should be on a dashboard or view for `<service>`."
These are **observability-data questions — answer them from the telemetry surface, not
from the resource's control plane**, and answer with the *methodology* (the correct
signals, aggregation, scoping, and caveats) even when you also pull live numbers and even
when no matching resource exists in the account.

Route by the symptom, then **open the reference and surface every applicable item in its
"facts you MUST surface" checklist** — the checklist is the output contract, and it lives
in the reference file, not here:

- A **metric symptom about one AWS service** (throttling, latency, error rate, restarts,
  saturation, "what signals should it get", which signals or panels a named resource type
  needs on a dashboard or view) → [query/promql-metrics.md](references/cloudwatch-omni/query/promql-metrics.md).
  Open its **"Service-health question — facts you MUST surface"** section and surface every
  applicable item. Dashboard or view wording does not send this to either dashboards file
  (neither carries the signal facts) nor to rule 3's probe — it is a content question.
- **"What does `<service>` depend on / what's broken downstream" / blast radius / who is
  affected / which direction do I walk the graph / what do `CALLS`, `ACCESSES`, `RUNS_ON`
  mean** → [context-graph.md](references/cloudwatch-omni/context-graph.md). Open its
  **"Dependency / blast-radius question — facts you MUST surface"** section and surface
  every applicable item. A slowness or error symptom phrased in terms of the graph,
  dependencies, or edge types routes here, not to the metric bullet above.
- **Individual slow or failing spans / traces** ("slowest spans for `<service>`", "which
  traces failed") are trace **SQL**, not a metric aggregate →
  [query/sql-logs-traces.md](references/cloudwatch-omni/query/sql-logs-traces.md). Open its
  **"Span Duration"** and **"Finding failed spans"** sections and state every item in their
  must-state callouts — a request about a service's latency or error *rate* (an aggregate
  signal) is the PromQL bullet above instead.

### Must-state checklists — the output contract

Three Omni tasks carry a checklist the **answer text** must carry, not just the plan. Open the
reference and surface every item relevant to the request; the reference holds the per-item
detail and is the source of truth, so do not restate it here.

| Task | Open | Section to surface |
|---|---|---|
| Authoring or advising on an Omni **alert** | [alerts.md](references/cloudwatch-omni/alerts.md) | "Facts you MUST surface when authoring an alert" |
| Scoring traces, choosing an evaluator, reading stored scores, online/continuous evaluation, evaluation datasets | [agent-evaluation.md](references/cloudwatch-omni/agent-evaluation.md) | every **"tell the user ALL of this"** callout |
| Authoring, saving, reading back, or debugging an Omni **dashboard** | [dashboards.md](references/cloudwatch-omni/dashboards.md) | "Facts you MUST surface when building or saving an Omni dashboard" |

## Routing — CloudWatch (`references/cloudwatch/`)

| User need | Action |
|-----------|--------|
| Enabling/onboarding a service to Application Signals (auto-instrumentation, the `amazon-cloudwatch-observability` add-on, monitored service), propagating ServiceEvents git/deployment metadata through CI/CD, or the per-platform × per-language enablement steps | **STOP** — this is first-time CloudWatch setup and no reference here covers it. Route to the **`setting-up-cloudwatch-observability`** skill |
| Writing Log Insights queries (pipe-delimited syntax: fields, filter, stats, sort, parse, display) | Read [log-insights.md](references/cloudwatch/log-insights.md) |
| Configuring alarms (metric, composite, anomaly) | Read [alarms.md](references/cloudwatch/alarms.md). For an Omni **alert**, see the Omni table |
| Publishing custom metrics or using EMF | Read [metrics.md](references/cloudwatch/metrics.md) |
| X-Ray / ADOT tracing **behaviour** — X-Ray-SDK-vs-ADOT choice, trace and segment structure, annotations vs metadata, sampling rules, collector pipeline config, X-Ray→OTel migration traps | Read [tracing.md](references/cloudwatch/tracing.md). Onboarding an un-instrumented service is the setup skill's job (see the first row) |
| Building CloudWatch dashboards (widget mechanics; which signals a given AWS service needs is Step 0.5) | Read [dashboards.md](references/cloudwatch/dashboards.md) |
| Debugging observability issues | Read [troubleshooting.md](references/cloudwatch/troubleshooting.md) — starts with the 5 most common fixes |
| Debugging canary failures | Read [synthetics.md](references/cloudwatch/synthetics.md) — see Common failures table |
| CloudTrail operational auditing | Read [cloudtrail.md](references/cloudwatch/cloudtrail.md) |
| Setting up Lambda monitoring with CDK | Use [alarm-template.ts](assets/cloudwatch/alarm-template.ts) as a starting point |
| Creating synthetic canaries | Read [synthetics.md](references/cloudwatch/synthetics.md) |
| Configuring ADOT collector | Use [otel-config.yaml](assets/cloudwatch/otel-config.yaml) as a starting point |
| Debugging a running service with breakpoints/snapshots — Dynamic Instrumentation (**modifies live services and captures live data**) | Read [dynamic-instrumentation.md](references/cloudwatch/dynamic-instrumentation.md) in full before acting. Confirm with the user before any create/delete, and narrate before significant actions: observation → hypothesis → proposed action → expected result. Source inspection alone identifies hypotheses, not confirmed root causes; keep suspected causes tentative until runtime evidence confirms them. |

## Routing — CloudWatch Omni (`references/cloudwatch-omni/`)

Rows that **act on live Space data** assume Step 0 found a Space. Knowledge questions are
answered from the file directly.

| User need | Action |
|-----------|--------|
| **Concepts.** What Omni is, what a Domain / Space / Dataset / grant / profile / view / alert / context graph is, whether a feature is Omni or CloudWatch, where setup starts | Read [concepts.md](references/cloudwatch-omni/concepts.md) |
| **Query logs or traces** — SQL (`SELECT … FROM logs.default / traces.default / default`), field access, schema discovery, slowest / failed spans (`durationNano`, `status.code`), TABLESAMPLE | Read [query/sql-logs-traces.md](references/cloudwatch-omni/query/sql-logs-traces.md). For slowest or failed spans, state every item in its "Span Duration" / "Finding failed spans" must-state callouts, even when the live result is empty |
| **A span, trace, or log record supplied in the prompt** — "I have this span open, what errors are in it", a pasted telemetry object | Read the **"Reading a span or trace you already have"** section of [query/sql-logs-traces.md](references/cloudwatch-omni/query/sql-logs-traces.md). Answer from the object's own fields; do not probe, query, or ask the user to fetch it |
| **Query metrics** — PromQL, which metric answers which symptom per AWS service, why a metric is missing, gauge vs counter | Read [query/promql-metrics.md](references/cloudwatch-omni/query/promql-metrics.md). Metrics are PromQL, never SQL |
| **Views** — create, manage, or query named reusable SQL (`FROM view.<name>`) | Read [query/views.md](references/cloudwatch-omni/query/views.md) |
| **Dashboards in Omni** — compose, ground panel queries, author `panels[]`, lay out the grid, the API save semantics (an unknown root- or panel-level key, a missing `type`/`layout`, or a bad variant is REJECTED at save with a 400 ValidationException; a bad enum VALUE, `x+w>60`, or an unknown key inside `config` saves 200 and fails or is ignored at render; validate before save), fix an empty or blank panel, the `*OmniDashboard` APIs | Read [dashboards.md](references/cloudwatch-omni/dashboards.md) |
| **Alerts in Omni** — any mention of an Omni **alert**, `CreateAlert` / `GetAlert` / `ListAlerts` / `UpdateAlert` / `DeleteAlert`, a `profileId`, an alert ARN, or how alerts differ from alarms; create, tune, tag, list, delete; notifications | Read [alerts.md](references/cloudwatch-omni/alerts.md). The alert API is real and first-class — do NOT redirect to CloudWatch alarms. For CloudWatch alarms when Omni is not enabled, read [cloudwatch/alarms.md](references/cloudwatch/alarms.md) |
| **Context graph** — why is service X slow or failing, what depends on it, upstream/downstream, which direction to walk, edge types `CALLS` / `ACCESSES` / `RUNS_ON`, blast radius, walking from an insight or anomaly to a root cause, `GetContextGraph` | Read [context-graph.md](references/cloudwatch-omni/context-graph.md) and state every applicable item in its "facts you MUST surface" section |
| **Agent evaluation** — score traces on demand, choose an evaluator, read back stored `gen_ai.evaluation.*` scores ("which evaluators are doing worst", "which online evaluators are unhealthy / underperforming"), build datasets from traces, set up online evaluation, author a custom evaluator, audit whether an agent's traces are flowing | Read [agent-evaluation.md](references/cloudwatch-omni/agent-evaluation.md) and state every applicable item in its "tell the user ALL of this" callouts |
| **Programmatic access** — "is there an API or SDK for Omni", calling Omni from code, CI, IaC, or an AI coding agent | Read [programmatic-access.md](references/cloudwatch-omni/programmatic-access.md). Omni has a real public SigV4 API; never answer that it has none, never substitute the CloudWatch or X-Ray CLI/SDK, and answer without probing for a Space |
| **Who has access to a Space**, granting or revoking access, access profiles, creating a Space or Domain, ingestion, forwarding, Slack, Azure, instrumenting an app or AI agent — and, on the CloudWatch side, onboarding a service to Application Signals | Route to the **`setting-up-cloudwatch-observability`** skill. If it is not installed locally, load it with the AWS MCP `retrieve_skill` tool (`skill_name: setting-up-cloudwatch-observability`; pass `file` for a reference it cites) |
| Spans multiple areas | Read the most specific reference first, then consult others as needed |

## Files

### `references/cloudwatch/`

| File | Content |
|------|---------|
| [alarms.md](references/cloudwatch/alarms.md) | Metric, composite, anomaly detection alarms — configuration, constraints, recommended defaults |
| [log-insights.md](references/cloudwatch/log-insights.md) | Complete query syntax, commands, functions, known issues, reusable query library |
| [metrics.md](references/cloudwatch/metrics.md) | Custom metrics, EMF spec, metric filters, high-resolution, retention |
| [tracing.md](references/cloudwatch/tracing.md) | X-Ray → ADOT migration, sampling rules, annotations vs metadata, collector config |
| [dashboards.md](references/cloudwatch/dashboards.md) | Widget types, cross-account/region, dynamic labels, sharing |
| [troubleshooting.md](references/cloudwatch/troubleshooting.md) | Error → cause → fix for all observability services |
| [cloudtrail.md](references/cloudwatch/cloudtrail.md) | Operational auditing, event types, S3+Athena queries |
| [synthetics.md](references/cloudwatch/synthetics.md) | Canary runtime/blueprint constraints, VPC networking, common failures |
| [dynamic-instrumentation.md](references/cloudwatch/dynamic-instrumentation.md) | Dynamic Instrumentation debugging loop — breakpoints/probes on live code, snapshot capture + correlation analysis, create/delete gating, snapshot PII handling. Runs via `scripts/cloudwatch/di_instrumentation.py` + `scripts/cloudwatch/di_snapshots.py`; details in `dynamic-instrumentation/` |
| [alarm-template.ts](assets/cloudwatch/alarm-template.ts) | Best-practice CDK Lambda monitoring (alarms + dashboard) |
| [otel-config.yaml](assets/cloudwatch/otel-config.yaml) | ADOT collector config for X-Ray traces + CloudWatch EMF metrics |

**Not here, by design:** Application Signals onboarding (the enablement procedure, the
ServiceEvents CI/CD chain, the 16 per-platform guides) is first-time setup and lives in
**`setting-up-cloudwatch-observability`**. Do not reconstruct it here from memory; route.

### `references/cloudwatch-omni/`

| File | Content |
|------|---------|
| [concepts.md](references/cloudwatch-omni/concepts.md) | What Omni is and is not; glossary (Domain, Space, Dataset, grant, profile, view, alert, dashboard, context graph, evaluator); Omni-vs-CloudWatch feature-equivalence matrix; how to tell which product the customer means; the setup sequence and where it lives |
| [context-graph.md](references/cloudwatch-omni/context-graph.md) | The service/resource topology Omni builds from traces and metrics; `GetContextGraph` request/response and CLI; reading upstream vs downstream and blast radius; walking from an insight or anomaly hop-by-hop to a root cause, then pivoting to queries |
| [programmatic-access.md](references/cloudwatch-omni/programmatic-access.md) | The public SigV4 API (`cloudwatch-omni` endpoint prefix, `cloudwatch` signing name), how access grants authorize a programmatic caller, CLI/SDK access (and why an unsupported-service error is a client-version issue), CloudFormation/CDK, AI coding agents, and the wrong answers to avoid |
| [query/sql-logs-traces.md](references/cloudwatch-omni/query/sql-logs-traces.md) | SQL over logs and traces — table addressing, required time range, system fields, field access and quoting, schema discovery, supported operations, functions, common patterns (including `durationNano` span duration), constraints, TABLESAMPLE |
| [query/promql-metrics.md](references/cloudwatch-omni/query/promql-metrics.md) | Metrics in Omni are PromQL — what is queryable (OTLP, span RED, OTel-enriched vended metrics) and what is not, label conventions, `__name__` matcher, rate() on counters, per-AWS-service metric catalog with derived formulas and dimension traps |
| [query/views.md](references/cloudwatch-omni/query/views.md) | Named SQL views: CreateView / UpdateView / DeleteView / ListViews, `FROM view.<name>`, naming and definition rules, composition patterns |
| [dashboards.md](references/cloudwatch-omni/dashboards.md) | Omni dashboards — composition recipes, grounding panel queries, the `panels[]` body and panel types, visualizations, the 60-column grid, the API save semantics (unknown root/panel keys are rejected 400; unknown keys inside `config` save 200 and are ignored at render; validate before save), troubleshooting empty/blank panels, the Create/Get/List/Update/DeleteOmniDashboard APIs, archetype templates |
| [alerts.md](references/cloudwatch-omni/alerts.md) | Omni alerts — alert vs alarm, evaluation (FIELD_VALUE / COUNT_OF_RESULTS, contributors), states and no-data treatment, notification rules, step-by-step create / update / delete / tag / fetch, and the alert APIs |
| [agent-evaluation.md](references/cloudwatch-omni/agent-evaluation.md) | Agent-quality evaluation on OTel traces — instrumentation health audit, evaluator selection, on-demand scoring, online evaluation, custom evaluators, datasets from traces, and reading back stored `gen_ai.evaluation.*` scores (retrieval plan + SQL mechanics). Uses `scripts/cloudwatch-omni/evaluate_traces.py` and `scripts/cloudwatch-omni/capture_dataset_from_traces.py` |
