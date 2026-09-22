# CloudWatch Omni Alerts

Reference for **CloudWatch Omni alerts** — what they are, how they are evaluated, how
to create, update, delete, tag, and fetch them through the public API, and a section
per API operation.

On an Omni-enabled account "alert" and "alarm" both mean the Omni alert resource
described here — a separate resource from a CloudWatch alarm, with its own API.

Alert operations are part of the `cloudwatch-omni` service (`aws cloudwatch-omni
<operation>`) and are signed with the SigV4 signing name **`cloudwatch`** — see
[programmatic-access.md](programmatic-access.md).

Two rules hold across every operation:

- **Never invent a threshold number.** A guessed threshold produces an alert that
  either never fires or fires constantly, and the user cannot tell which. Where a
  number is not grounded, ask the user for it.
- **Confirm before any write.** Creating, updating, and deleting an alert all change
  live alerting configuration. Propose the exact change in the user's terms and let
  them confirm it before calling the API. Fetching needs no confirmation.

## Contents

- [Alert vs alarm](#alert-vs-alarm)
- [Concepts](#concepts)
- [Which operation is this?](#which-operation-is-this)
- [Creating an alert](#creating-an-alert)
- [Updating an alert](#updating-an-alert)
- [Deleting an alert](#deleting-an-alert)
- [Tagging an alert](#tagging-an-alert)
- [Fetching alerts](#fetching-alerts)
- [API reference](#api-reference)

---

## Alert vs alarm

| | CloudWatch Omni alert (this file) | CloudWatch alarm ([../cloudwatch/alarms.md](../cloudwatch/alarms.md)) |
|---|---|---|
| Service | `aws cloudwatch-omni` — `CreateAlert`, `GetAlert`, `ListAlerts`, `UpdateAlert`, `DeleteAlert` | `aws cloudwatch` — `PutMetricAlarm`, `PutCompositeAlarm`, `DescribeAlarms`, … |
| Watches | One **query** — Omni SQL over logs/traces, or PromQL over metrics — evaluated on a schedule | A metric, metric-math expression, or anomaly band; composites combine alarms |
| Scope | A **Space** (`spaceId` on every call); runs under an **access profile** (`profileId`) | The account and Region |
| States | `OK`, `WARNING`, `CRITICAL`, `NODATA` | `OK`, `ALARM`, `INSUFFICIENT_DATA` |
| Notifies | `sns` and `slack` targets on `notificationRules` | Alarm actions (SNS, Auto Scaling, EC2, Lambda, …) |

The Omni alert API is a **real, first-class API surface**. For an **informational**
question (what a field is, whether an operation exists, what the API supports),
answer from this file with confidence — do not say the API "does not exist", and do
not stall on a clarifying question such as "what is your `profileId`?"; explain the
field and that it is caller-supplied.

SKILL.md Step 0 has already established that a **Space exists in the target Region**
before routing here; the Omni alert API is only usable once it does. If you arrived
without that check, go back to Step 0 rather than continuing — it also owns the
no-Space fallback. `profileId` is a required, caller-supplied input on `CreateAlert`
with no service default — gather it first (Creating, Step 6).

Five facts to hold onto:

1. **Every alert operation is space-scoped.** `spaceId` is required on all five
   operations, so there is **no account-wide list of alerts** — you list per space.
2. **The four alert states are `OK`, `WARNING`, `CRITICAL`, and `NODATA`.** Severity
   is folded into the state — a breaching alert reports `WARNING` or `CRITICAL`
   directly; there is no separate "in alarm" state.
3. **`ListAlerts` vs `GetAlert` return different things.** `ListAlerts` returns
   `AlertSummary` items — identity, status and the notification switch only — and
   **deliberately does not carry the rule** (no threshold, query, cadence, or
   recipients). Call **`GetAlert`** per alert to read the full rule.
4. **`CreateAlert` takes a `profileId`, and it is required.** It is the access
   profile the alert runs under; the service does **not** pick a default.
5. **Mute vs delete.** To stop notifications while keeping the alert, use
   `UpdateAlert` with `notificationsEnabled=false` — **do not** delete it and **do
   not** raise the threshold out of reach.

---

## Concepts

### What an alert is

An alert **runs one query on a fixed schedule and compares the result against a
threshold**, reporting a state. That is the whole concept, and every operation below
works on this shape:

- **A query** — the thing being measured, time-bounded, with no threshold in it.
- **A condition** — the threshold the result is compared against, and how.
- **A cadence** — how often it evaluates, and what a silent query means (no-data).
- **Optionally notifications** — where to say something when it changes state.
- **An access profile** — the permissions the query runs under.

An alert has two identifiers:

- **`alertId`** — a UUID with its hyphens removed, so 32 lowercase hex characters.
  It is assigned when the alert is created and is **immutable**. It is the alert's
  identity: it is the ARN's resource id and what you pass to `GetAlert`,
  `UpdateAlert`, and `DeleteAlert`. It carries no name, so renaming an alert never
  changes its identity or breaks ARNs, saved links, or IAM policies pointing at it.
- **`name`** — a display label, 1–256 characters, charset `[a-zA-Z0-9_.@~()-]` (no
  spaces). It is **mutable** — `UpdateAlert` can rename an alert at any time — and
  it is **not unique** within a space. Because it is neither unique nor stable, it
  is **not** how an alert is addressed: two alerts can share a name, so resolve a
  name to an `alertId` (via `ListAlerts` with a `names` filter) before acting on it.

Users will always talk about the name. When you need to be unambiguous, say which
alert you mean in the user's terms (its name plus what it watches) rather than
reading an identifier out to them.

### ARN format

An alert's ARN uses the `cloudwatch` vendor namespace with an `alert/` resource
type, and the resource id is the bare `alertId`:

```
arn:<partition>:cloudwatch:<region>:<account-id>:alert/<alertId>
```

For example:

```
arn:aws:cloudwatch:us-east-1:123456789012:alert/6c8971b543d54148a26fc793f46db68c
```

The **`spaceId` does not appear in the ARN**, and neither does the alert's name —
the resource id is only the immutable `alertId`. That is deliberate, so that
renaming an alert or reorganizing spaces never changes its ARN and never breaks IAM
policies or saved links that point at it. `CreateAlert` returns this ARN as
`alertArn`, and `Alert`/`AlertSummary` both carry it.

### Ownership: alerts belong to an Omni Space

Every alert is **owned at the Omni Space level**. `spaceId` is a required parameter
on every alert operation, including the reads — there is no account-wide alert list,
only per-space ones. An alert also carries the `accountId` that owns it.

Each alert additionally references a **`profileId`** — the access profile the alert
runs under. **A `profileId` must be provided when creating an alert.** The profile
is used for two things:

1. **Running the query.** It grants the alert access to execute its query and fetch
   the query's results.
2. **Reaching an Omni integration.** It grants the alert access to any notification
   rule target that is an Omni integration — a connected Slack integration.

For the alert to work, the profile therefore needs the right grants for how the
alert is configured:

- An access grant allowing the **`ALERT` principal** to assume the profile (a trust
  grant keyed on the alert's name, or on `ALL`).
- Grants allowing access to **the data the alert's query reads**.
- Grants allowing access to **any Omni integration referenced in the alert's
  `notificationRules`**.

How to create and verify such a profile is covered in
`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-profiles.md`; how to choose one for a given
alert is Creating, Step 6.

### Query languages

An alert's rule carries a query **expression** plus the **language** it is written
in (`rule.telemetryRule.query`, up to 10,000 characters). Both languages are
accepted:

- **`SQL`** — the CloudWatch Omni SQL dialect over the Omni telemetry data sets:
  `logs.default`, `traces.default`, and views. Use it for log and trace
  conditions. For the dialect itself — table addressing, `` `@timestamp` ``
  bounds, `date_bin`, JSON field extraction, schema discovery — see
  [query/sql-logs-traces.md](query/sql-logs-traces.md).
- **`PROMQL`** — PromQL over metrics, for every metric-shaped condition: gauges,
  counters, and histogram percentiles via `histogram_quantile`. See
  [query/promql-metrics.md](query/promql-metrics.md).

**A condition on a metric MUST use `PROMQL`.** Metrics have no SQL surface: there is
no `metrics.default` data set, and a SQL query aimed at one is rejected by
`StartTelemetryQuery` with `ValidationException: Metrics queries are not supported.`
So whenever the user asks to **create or update** an alert on a metric — a gauge, a
counter, or a percentile — write a raw PromQL expression and set `language` to
`PROMQL`. A log or trace condition is `SQL`.

Pick the language that fits the signal and set `language` to match the expression;
it is not inferred from the query text.

The alert supplies **no evaluation window of its own**, so the query must carry its
own **relative** time bound (a `` `@timestamp` `` `BETWEEN NOW() - INTERVAL … AND
NOW()` bound in SQL, a range selector like `[5m]` in PromQL). The query must also
**not** contain the threshold comparison — the threshold is a separate field on the
condition, so a comparison baked into the expression is applied twice and cannot be
retuned. Creating, Step 1 spells out the full set of shape rules.

### How an alert is evaluated

Each evaluation runs the query and compares the result against the condition's
thresholds. **`thresholdMode` decides what is compared**, and the two modes behave
very differently:

**`FIELD_VALUE` — compare a value per returned row, producing contributors.**

The alert evaluates **each row the query returns**. For each row it reads the
column named by **`thresholdField`** and compares that value against the threshold.

Because a row-per-entity query yields a value per entity, this mode produces
**contributors** — each breaching row is one contributor: the state of that one
breaching row/entity. The alert enters `WARNING` or `CRITICAL` as soon as the first
contributor breaches. A contributor's own state is **`WARNING` or `CRITICAL` only** —
an entity that recovers to `OK` is removed from the persisted set, so a contributor is
never `OK` and never `NODATA` (this is distinct from the whole-alert state, which can be
any of `OK`, `WARNING`, `CRITICAL`, or `NODATA`). Contributors are visible only as
**counts**: `state.contributorSummary` (`warningCount`/`criticalCount`) on the alert's
state, returned by `GetAlert` and `ListAlerts` and absent until the first contributor
breaches `WARNING` or `CRITICAL`. There is **no customer-facing API that lists
individual contributors**. For example: a query returning the CPU
utilization of every instance in a fleet returns one row per instance; each
instance's CPU value is compared against the threshold, and **any instance/row that
breaches breaches the alert**.

**`COUNT_OF_RESULTS` — compare the number of rows.**

The measure is simply the **count of rows the query returned**, compared against the
threshold. No column is read, so `thresholdField` does not apply. Note that a
`LIMIT` in the query caps the row count and therefore caps the measure.

**The condition** (`AlertCondition`) carries the comparison itself:

| Field | Meaning |
|---|---|
| `thresholdMode` | `FIELD_VALUE` or `COUNT_OF_RESULTS` (above) |
| `thresholdField` | The column whose value is compared, ≤256 chars. `FIELD_VALUE` only |
| `comparator` | `GT`, `LT`, `GTE`, or `LTE` |
| `warningThreshold` | Double — the value at which the alert enters `WARNING` |
| `criticalThreshold` | Double — the value at which the alert enters `CRITICAL` |

Both thresholds are optional and independent; supplying only `criticalThreshold`
gives a single-tier alert. Keep them ordered so `CRITICAL` is the more severe.

**The cadence** (`AlertEvaluation`):

| Field | Meaning |
|---|---|
| `intervalSeconds` | **Required.** How often the alert evaluates. One of `30`, `60`, `120`, `300`, `600`, `900`, `1800`, `3600` — nothing else is accepted |
| `pendingDurationSeconds` | How long a breach must persist before the alert fires. Must be a multiple of `intervalSeconds`. Omitted means no pending duration (the field stays unset on read-back; it is not defaulted to `0`) |
| `recoveryDurationSeconds` | How long a recovery must persist before the alert clears. Must be a multiple of `intervalSeconds`. Omitted means no recovery duration (unset on read-back, not `0`) |

A non-zero `pendingDurationSeconds` is what stops a single spike from firing the
alert; `recoveryDurationSeconds` is the equivalent damping on the way back to `OK`.

### Alert state

An alert's state has four possible values:

| State | Meaning |
|---|---|
| `OK` | The alert is within its normal threshold — the query ran and did not breach |
| `WARNING` | The alert is breaching its **warning** threshold |
| `CRITICAL` | The alert is breaching its **critical** threshold |
| `NODATA` | The evaluation produced no data, subject to the rule's no-data treatment |

State is read-only and system-managed, returned as `AlertStateInfo`:

- **`value`** — the current state from the table above.
- **`transitionedAt`** — when the alert last moved into that state.
- **`contributorSummary`** — `warningCount` and `criticalCount`, the number of
  contributors currently breaching each tier (`FIELD_VALUE` alerts). Absent on
  `CreateAlert` and absent from `GetAlert` until the first contributor breaches
  `WARNING` or `CRITICAL` — an `OK` alert has no summary.
- **`data`** (`AlertStateData`) — structured detail on the current evaluation. It
  carries exactly one member, `thresholdBreached`: the row count that breached, for
  `COUNT_OF_RESULTS` alerts, and null for `FIELD_VALUE`. The per-contributor
  breakdown is NOT here — `contributorSummary` above gives the counts, and nothing
  returns the individual contributors.

Two things about `transitionedAt` matter whenever you report state:

- **It is when the state CHANGED, not when the alert was last evaluated.** An alert
  that has been `OK` for a week carries a week-old timestamp; one that recovered four
  minutes ago carries a four-minute-old one. Never present it as an evaluation time.
- **The previous state is NOT on the alert, and there is no state-history
  operation.** A read says what state the alert is in and since when — never what it
  was in before. None of the five alert operations returns earlier transitions, so
  "did it flap?" / "what was it before?" can only be answered as far as the current
  state and its age go; say so rather than inferring a history from one timestamp.

### No-data treatment

`rule.telemetryRule.noData.treatAs` decides **which state an evaluation that
produced no data reports**. It takes any alert state — `OK`, `WARNING`,
`CRITICAL`, or `NODATA` — and **defaults to `NODATA`** when omitted.

This matters because "no rows" is not always a problem. A query counting errors
returns nothing when the service is healthy, so leaving `treatAs` at `NODATA` makes
every quiet interval look like a data outage; `OK` is usually the intent there.
Conversely, for a heartbeat-style query where silence means the thing being watched
has stopped, `CRITICAL` is the meaningful treatment.

### Notification rules

An alert may carry **`notificationRules`** — **0 to 5** rules. Notifications are
optional: an alert with none is valid and simply reports state. The whole list is
gated by **`notificationsEnabled`** (defaults to `true`), which is the switch to
mute an alert without changing what it watches or deleting it.

Each rule pairs a **trigger** with a **target**:

- **`trigger.stateValues`** — the alert states that fire this rule, OR-combined.
  **Empty or omitted means any state** — including every return to `OK`. To notify
  only when the alert fires, set it explicitly to `["WARNING", "CRITICAL"]`; add
  `OK` for a recovery notification, or `NODATA` to be told when the query goes
  silent.
- **`target`** — where the notification goes. **The supported target types for GA
  are exactly `sns` and `slack`** — the validator rejects any other type.
  A `NotificationTarget` carries a **`type`** (`NotificationTargetType`), a
  **required `arn`** (1–1024 chars), and an optional **`metadata`** string map (up to
  20 keys; keys ≤128 chars, values ≤1024). Any type outside `{sns, slack}` — email,
  a generic webhook, and PagerDuty (which is present in the `NotificationTargetType`
  enum but is **not** a supported target for GA) — is unsupported; say so plainly and
  **do not invent an unsupported provider or fabricate a config for one**.
  - **`sns`** — `arn` is an SNS topic ARN
    (`arn:aws:sns:<region>:<account>:<topic>`; same Region and partition as the
    alert, cross-account allowed, FIFO topics not allowed). `metadata` **must be
    empty** — any entry is rejected with
    `notificationRules[N].target.metadata must be empty for type=SNS`.
  - **`slack`** — `arn` is the ARN of the account's connected Slack integration
    (`arn:aws:cloudwatch:<region>:<account>:integration/<id>`, in the caller's own
    account and Region, from `ListIntegrations`). `metadata` **must carry a non-blank
    `channel` and nothing else** (Step 5b).

For SNS delivery, the topic's own resource policy must allow the
`cloudwatch.amazonaws.com` principal to call `sns:Publish`; that is the customer's
to configure and is not validated when the alert is created, so it is the first
thing to check when an alert fires but no message arrives. Slack must be connected
as an integration before its ARN exists — see
`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/slack-integration.md`.

### Tags

An alert can be tagged at create time via **`CreateAlert.tags`**, a key/value map.
Keys are 1–128 characters and values 0–256 characters (an empty value is allowed).
As with any AWS resource, the `aws:` key prefix is reserved. **After creation, tags are
managed through the CloudWatch tagging APIs on the alert's ARN**, not through the alert
operations: `CreateAlert` is the only alert operation with a `tags` member, the `Alert`
shape returned by `CreateAlert`/`GetAlert` and the `AlertSummary` returned by
`ListAlerts` carry no tags, and `UpdateAlert` does not accept them. Read, add, change,
or remove tags with `aws cloudwatch list-tags-for-resource` / `tag-resource` /
`untag-resource --resource-arn <alertArn>` — see [Tagging an alert](#tagging-an-alert).

---

## Which operation is this?

Every alert ask is exactly **one** of five operations. Decide which from the user's
phrasing **before any API call**, then work only that section. Two directions of
mistake are expensive: creating a second alert when the user meant to retune the one
they already have leaves them with two, and the original keeps firing; and deleting
is permanent, so mistaking an update, a mute, or a tag change for a delete removes
an alert that cannot be brought back.

| Operation | Keywords to look for | Sample prompts |
|---|---|---|
| **[Creating an alert](#creating-an-alert)** — a step-by-step procedure ending in `CreateAlert` | create, set up, add, make, new, start alerting, alert me, warn me, let me know when, monitor for, watch for, what should I alert on | "tell me when checkout p99 goes over 2s" · "alert me if 5xx spikes" · "set up an alarm on the error rate" · "I want to be paged when the queue backs up" |
| **[Updating an alert](#updating-an-alert)** — `GetAlert`, then `UpdateAlert` | update, change, edit, modify, adjust, bump, re-point, disable, enable, mute, silence, pause, stop notifying, remove (a part) | "change checkout-5xx-errors to 500" · "make it fire at 5 instead of 2" · "rename the alert I set up" · "stop it messaging the channel" |
| **[Deleting an alert](#deleting-an-alert)** — `GetAlert`, confirm, then `DeleteAlert` | delete, remove it, get rid of, tear down, take down, drop the alert(s) | "delete the p99 alert" · "remove checkout-5xx-errors" · "delete these four alerts" · "tear down the alerts I set up for the demo" |
| **[Tagging an alert](#tagging-an-alert)** — `aws cloudwatch tag-resource` / `untag-resource` / `list-tags-for-resource` on the alert ARN | tag, add a tag, change a tag, retag, remove a tag, untag, set the owner/team/environment tag, label it | "tag that alert with owner=payments" · "add env=prod to the checkout alarm" · "remove the team tag from it" · "what's it tagged with?" |
| **[Fetching alerts](#fetching-alerts)** — `ListAlerts` / `GetAlert`, no confirmation | list, query, filter, get, fetch, show, describe, search, find, which alerts, how many, do I have, firing, breaching, status, starting with, tagged, for the *service*, on logs, PromQL, history, flapped, flapping, what changed, fired earlier, recovered, happened before | "what alerts do I have?" · "is anything firing?" · "what's the threshold on checkout-5xx-errors?" · "which alerts use PromQL?" · "do I already have an alert for this?" · "did checkout-5xx flap earlier today?" · "when did it last go critical?" |

**List, filter, query, get, show, describe, search and find are all fetching.**
They differ only in how many alerts come back and how much of each you report.

**The tiebreak, when keywords from two rows both appear:** if the ask points at an
alert that already exists — "that alert", "the one I set up", a name, or a word
like *instead*, *stop*, *turn off* — it is an update, a delete, a tag change, or a
fetch, never a create. A create ask points at a condition to watch, not at an
alert. Between **update and delete**: removing a *part* of an alert (a Slack
channel, the description) is an update; removing the *alert itself* is a delete.

Five asks that land on the wrong branch unless you look twice:

- **"Do I already have an alert on this? If not, set one up."** Two operations, in
  order: fetch first, create only if nothing matched. Do not create blind — a
  duplicate is invisible to the user until both fire.
- **"Make it fire at 5 instead of 2."** An update, even though it names a threshold
  and reads like a create ask.
- **"What should I alert on for checkout?"** versus **"what's alerting on
  checkout?"** The first is a create ask (nothing exists yet); the second is a
  fetch of what is already configured.
- **"the alerts tagged `owner=payments`"** versus **"tag that alert
  `owner=payments`."** A tag used to FIND alerts is a fetch; a tag to be PUT on a
  named alert is tagging. Only one of them writes.
- **"Remove the Slack channel from checkout-5xx"** versus **"remove
  checkout-5xx."** The first is an update — it strips one notification target and
  the alert lives on; the second is a delete — the whole alert is gone.

---

## Creating an alert

This is a **procedure**. Work the steps in order — later steps depend on the output
of earlier ones, and one dependency runs *backwards* (Step 2 can send you back to
Step 1):

0. **Classify the ask** — metric, or log/trace condition.
1. **Author and ground the query** the alert evaluates.
2. **Build the `AlertCondition`** (threshold mode, field, comparator, thresholds).
3. **Set evaluation & no-data** behaviour.
4. **Name it** (+ description, tags).
5. **Add notification rules** — only if the user asked to be notified.
6. **Resolve the access profile** the alert runs under.
7. **Confirm, then `CreateAlert`.**

### Step 0 — Classify the ask

One question, answerable from the user's phrasing alone: **is the measure a metric,
or a log/trace condition?** ("p99 latency", "queue depth", "CPU" are metrics; "count
of 5xx", "logs where status = 500" are log conditions.) That is enough to route
Step 1 — which data set and language the query uses.

Do **not** try to decide here what the exact metric or field name is — you cannot
know that from the ask. Names are a *product of grounding* in Step 1.

If the ask contains **several** alerts ("alerts for 5xx, p99 latency, and error rate
on checkout"), that is one alert **per condition** — read
[Handling several alerts at once](#handling-several-alerts-at-once) first, then run
Steps 1–7 once per alert.

### Step 1 — Author and ground the query

You write the query yourself, in the dialect the Step 0 answer selects, and you
**ground every field, metric, and label name against live data** before it goes
into an alert. An alert on a field that does not exist is silently dead — it sits at
`NODATA`/`OK` forever and nobody notices — which is worse than an alert that errors.

| The ask | Route | `language` | Dialect reference |
|---|---|---|---|
| A **metric** (gauge, counter, histogram percentile) | raw PromQL over the metric | `PROMQL` | [query/promql-metrics.md](query/promql-metrics.md) |
| A condition over **logs or traces** | SQL over `logs.default` / `traces.default` (or a [view](query/views.md)) | `SQL` | [query/sql-logs-traces.md](query/sql-logs-traces.md) |

- **A metric alert MUST be raw PromQL — never SQL.** There is no SQL path to a
  metric.
- **A log or trace condition MUST be SQL.**
- Histogram percentiles (p90/p95/p99) are a **metric**, so they take the PromQL
  route — `histogram_quantile(0.99, rate(<metric>[5m]))` on the **base metric name**
  (no `_bucket`, no `by (le)`: Omni stores histograms in exponential form and
  exposes no `_bucket{le=…}` series, so a `_bucket`/`by (le)` query returns
  **empty** and the alert never fires).

**Ground the names.** For SQL, discover the real field names with
`EXPLAIN (ANALYZE_FIELDS)` and confirm any non-`@` field before using it — the
schema is permissive and a misspelled field returns `NULL` rather than an error
(see [query/sql-logs-traces.md](query/sql-logs-traces.md), Schema Discovery). For
PromQL, confirm the metric name and the identity labels you filter on exist by
querying them (see [query/promql-metrics.md](query/promql-metrics.md)). Pass the ask
at the **user's** level of specificity — do not invent a service or field name to
make the query look complete. If you cannot ground the request, ask the user **one**
question — nearly always which service or which field — rather than emitting an
ungrounded query.

**Run the candidate query once** (`StartTelemetryQuery` / `GetTelemetryQueryResults`,
or the equivalent Explore view) before proposing it. This both proves the names
resolve and shows the current value, which is the best context for the user's
threshold decision in Step 2.

#### Attributes an alert query MUST have

An ordinary exploration query can break all of these; an alert query cannot. These
apply to **both** languages:

1. **A RELATIVE time window.** The alert does **not** supply its own evaluation
   window — the query is re-executed on every evaluation, so it MUST carry a window
   that moves with the clock: a PromQL range like `[5m]`, or a SQL
   `` `@timestamp` `` `BETWEEN NOW() - INTERVAL '<n> <unit>' AND NOW()`. Match the
   duration to the condition — "over the last 5 minutes" is `INTERVAL '5 MINUTE'` —
   and pick a sensible default when the user did not state one. **Never absolute
   instants** (`to_timestamp_nanos('2026-01-01T00:00:00Z')`): a frozen window
   evaluates the same dead historical slice forever.
2. **A single comparable number.** For `FIELD_VALUE` that is one named numeric
   value; for `COUNT_OF_RESULTS` it is the row count (see Step 2 for the mode
   split). A query that yields nothing to compare cannot back an alert.
3. **No threshold comparison inside the query.** No `HAVING COUNT(*) > 100`, no
   `> 2` inside the expression, no PromQL comparison operator. The threshold is a
   separate field (Step 2); baking it into the query applies it twice and makes the
   alert impossible to retune.
4. **Prefer one row / one series per evaluation.** Return several only when the
   user genuinely wants a per-dimension breakdown (`GROUP BY` in SQL, a `by (…)`
   grouping in PromQL) — that is what produces a per-entity evaluation.

#### SQL clause rules (log/trace alerts only)

A PromQL metric alert has no `ORDER BY`/`LIMIT`. For SQL, the clause rules depend on
the threshold mode, and getting this wrong is a **silent correctness bug**, not a
style issue:

- **`FIELD_VALUE`** (the query projects a named numeric value):
  - **A named numeric alias is REQUIRED** — `COUNT(*) AS error_count`, not a bare
    `COUNT(*)`. That alias becomes `thresholdField` in Step 2.
  - **`ORDER BY <the value> DESC` and a `LIMIT`** are required so the evaluated row
    is the current, worst one — ascending + `LIMIT` would evaluate the *oldest* row
    in the window (stale data). Default `LIMIT 500` as a safety net; the preferred
    shape returns one row.
  - Sort key: for a single bare aggregate use `ORDER BY <alias> DESC`; for a
    `GROUP BY` with a `date_bin` bucket use `ORDER BY bucket DESC`; for raw rows use
    ``ORDER BY `@timestamp` DESC``. `` `@timestamp` `` is **backtick-quoted**, and
    you MUST NOT sort by it after aggregating (it is no longer in the result).
- **`COUNT_OF_RESULTS`** (the measure is the number of rows the query returns):
  - **The query MUST NOT carry a `LIMIT` at or below the threshold** — a `LIMIT 500`
    caps the row count at 500, so "more than 1000 in five minutes" can *never* fire
    at any volume. Omit `LIMIT` (or, better, rewrite as a `COUNT(*) AS n` aggregate
    and use `FIELD_VALUE` on `n`, which is the cleaner shape for a "how many" alert).
  - **`ORDER BY` is meaningless** — sorting cannot change a row count. Omit it.

#### Check the query before moving on

Nothing in the service validates alert *shape* — a syntactically valid query with a
bad shape is accepted and then misbehaves. Read your own query for:

- a missing `ORDER BY`, or one missing `DESC` (`FIELD_VALUE` SQL)
- a sort on `` `@timestamp` `` in an aggregated projection
- an unnamed aggregate — no alias to threshold
- a comparison baked into the expression
- an absolute time bound, or no time bound at all
- a histogram percentile written over `_bucket` / `by (le)` series
- a `LIMIT` on a `COUNT_OF_RESULTS` query

### Step 2 — Build the AlertCondition

The `AlertCondition` has four decisions, and they come from **two different
sources**. Keep them straight — this is the single most common place to go wrong.

| Field | Where it comes from |
|---|---|
| `thresholdMode` | **The Step-1 query** |
| `thresholdField` | **The Step-1 query** (the projected alias) |
| `comparator` | **Published AWS guidance** for an AWS-vended metric; otherwise the direction of the condition |
| `criticalThreshold` | **Published AWS guidance** when it gives a number; otherwise **ask the user** |
| `warningThreshold` | **Only if the user asks for a warning tier** — never derived from AWS's single number |

#### 2a. `thresholdMode` and `thresholdField` — from the query

- **`FIELD_VALUE`** — compare a named numeric field. Set `thresholdField` to the
  projection's alias (`avg_latency_ms`, `p99_seconds`, …). This is the usual case
  for a metric alert (PromQL returns a value per series; `thresholdField` names the
  value) and for any SQL aggregate.
- **`COUNT_OF_RESULTS`** — compare the **number of rows** returned. Use this for a
  "how many …" log condition where the count itself is the signal; `thresholdField`
  is not set.

#### 2b. `comparator` and `criticalThreshold` — ground them

Decide first whether the grounded metric is an **AWS-vended metric** (one an AWS
service publishes — `AWS/SQS ApproximateAgeOfOldestMessage`, `AWS/Lambda Errors`,
…) or a **custom/application metric or log/trace condition**. You can only tell
from the *grounded* metric name and its labels (Step 1), never from the ask alone.
Do not guess a namespace from a metric name that could belong to several services —
name the candidate to the user and confirm it.

- **AWS-vended metric** — consult AWS's **published recommended thresholds** for
  that service and metric (the service's monitoring page and CloudWatch's metric
  recommendations, via documentation search). Only the comparator, statistic, unit,
  and number carry over into the Omni alert — none of the surrounding CloudWatch
  configuration does. Published guidance gives a comparator, a statistic, a period,
  and sometimes a number:
  - **A numeric recommendation** — take `comparator` and `criticalThreshold` from
    it. Say the value is AWS's recommended value and state its **unit**.
  - **A recommended shape but no number** (deliberately — the right value depends
    on the workload, e.g. queue age). Take `comparator` from it and ask the user one
    specific, informed question for the number ("this depends on how long your
    consumer takes — what age would you consider too old?"). Do not invent it.
  - **Documented statistic/unit but no alarm recommendation** — the statistic tells
    you how the query should aggregate (2c) and the unit tells you what the number
    means; best-guess the comparator from the condition's direction and ask the user
    for the number.
- **Custom metric, or any log/trace condition** — there is no published guidance.
  Best-guess the comparator from the condition's direction ("more than" → `GT`,
  "drops below" → `LT`) and **ask the user for the number**. The value the Step-1
  test run returned is useful context to offer ("it is currently 37/min").

**Do not derive a warning tier from AWS's single number.** AWS publishes one value
and it is the critical value. Set `warningThreshold` only when the user explicitly
asks for a warning-and-critical alert, and let them give (or confirm) the second
number. Keep the two ordered so `CRITICAL` is the more severe.

#### 2c. Reconcile the statistic — this can send you back to Step 1

Published guidance carries a **recommended statistic** (`p90`, `Maximum`, `Sum`,
…). The statistic does not live in the `AlertCondition` — it determines **how the
query aggregates**, which in turn determines `thresholdField`. Check the statistic
the Step-1 query actually uses against the recommended one. If AWS recommends `p90`
but the query computed an `AVG`, **go back to Step 1 and rewrite** so the query
aggregates the recommended way, then re-read the new alias as `thresholdField`.
Only once they agree is the `AlertCondition` settled.

#### 2d. Fill in the template

Omit `thresholdField` for `COUNT_OF_RESULTS`, and `warningThreshold` unless the
user asked for two tiers:

```json
"condition": {
  "thresholdMode":     "<FIELD_VALUE | COUNT_OF_RESULTS>",
  "thresholdField":    "<projection alias>",
  "comparator":        "<GT | LT | GTE | LTE>",
  "criticalThreshold": <number>,
  "warningThreshold":  <number>
}
```

### Step 3 — Set evaluation & no-data

- **`evaluation.intervalSeconds`** — one of **30, 60, 120, 300, 600, 900, 1800,
  3600**; nothing else is accepted. Match it to the condition (a 5-minute window is
  `300`), rather than defaulting. When AWS guidance carries a `period` and
  `evaluationPeriods`, they are a strong signal for the interval and the pending
  duration.
- **`evaluation.pendingDurationSeconds` / `recoveryDurationSeconds`** — optional,
  and each must be a **multiple of `intervalSeconds`**. Use a pending duration to
  stop a single spike firing the alert.
- **`noData.treatAs`** — `OK`, `WARNING`, `CRITICAL`, or `NODATA` (the default when
  omitted). **Set it explicitly; do not rely on the default.** For a query that
  legitimately returns nothing when healthy (an error count), `NODATA` on every
  quiet interval is noise, and `OK` is usually what the user means. For a heartbeat
  query where silence is the failure, `CRITICAL`. When AWS guidance carries a
  missing-data treatment, use it.

### Step 4 — Name it (+ description, tags)

- **`name`** — letters, digits and `_.@~()-` only, at most 256 characters, **no
  spaces**. Turn the phrase you would naturally write into a hyphenated slug —
  "checkout 5xx errors" → `checkout-5xx-errors`. Names are not unique in a space,
  so before choosing one, check `ListAlerts` with a `names` filter for an existing
  alert of that name and avoid creating a confusing twin. The name plays no part in
  the access profile: an `ALERT`-principal trust grant is keyed on the alert's ARN
  or on `ALL`, never on its name — see Step 6.
- **`description`** — keep the human phrasing here (≤1024 chars). State what the
  alert watches.
- **`notificationsEnabled`** — on by default. Set it `false` only when the user
  explicitly says they do not want to be notified.
- **`tags`** — set them **now** if the user wants any: a tag set on the create costs
  no extra call. Afterwards tags live behind the CloudWatch tagging APIs on the alert
  ARN, not on `GetAlert` (see [Tagging an alert](#tagging-an-alert)). Pass the user's `key=value`
  pairs verbatim — do not translate `env` into `Environment`, and if they named a
  key without a value, ask which value they mean rather than filling one in. Keys
  under the reserved `aws:` prefix are rejected; tell the user and ask for another
  key. Do not add tags the user did not ask for.

### Step 5 — Add notification rules (only if the user asked)

An alert with no notification is valid and common — it shows state in the console.
**Do this step only when the user asked to be told somewhere when the alert
fires.** If they did not, skip it and send no `notificationRules`.

Infer intent; the word "notification" is often absent. "Send a slack message to #oncall when this fires", "ping the team on Slack", and "publish to my SNS topic"
are all notification requests.

Two target types are supported for GA — `sns` and `slack` — and they can be
combined on one alert, up to **5 rules** in total. Anything else (email, a generic
webhook, PagerDuty) is not a supported target type; PagerDuty is present in the
`NotificationTargetType` enum but is **not** supported for GA, so a request to
"page the on-call" cannot be configured — say so plainly and continue with whatever
supported target they did name, otherwise with no notification. **Do not invent an
unsupported notification provider or fabricate a config for one.**

## 5a. SNS topic

- **A topic ARN is REQUIRED and MUST come from the user.** Never invent a topic ARN.
  If they asked for an SNS notification but did not give the ARN, ask for it — one
  question — before creating. Check that the value is a well-formed SNS topic ARN
  (`arn:<partition>:sns:<region>:<account-id>:<topic>`); if it is not, ask for the
  correct one rather than guessing.
- **There is NO integration to connect and NO access-profile permission needed** for
  SNS. The service takes the topic ARN as-is; Step 6's profile does not need to
  grant anything for it.
- **The customer owns the topic's permission.** The topic must have a resource
  policy allowing the principal `cloudwatch.amazonaws.com` to call `sns:Publish`.
  The service does **not** validate this at create time. If notifications never
  arrive, that missing policy is the first thing to check — mention it.
- **Multiple topics** → one rule per topic.

```json
{ "trigger": { "stateValues": ["WARNING", "CRITICAL"] },
  "target":  { "type": "sns", "arn": "arn:aws:sns:us-east-1:123456789012:oncall" } }
```

### 5b. Slack channel

- **A channel name is REQUIRED and MUST come from the user.** Never invent a channel.
  If they asked for Slack but did not name a channel, ask which channel — one
  question — before creating.
- **The target `arn` is the account's Slack integration ARN**, not a channel. Resolve
  it with `ListIntegrations` in the alert's Region and pick the Slack integration
  whose status is `ACTIVE`. If there is no Slack integration, the alert cannot
  notify Slack: tell the user Slack must be connected first
  (`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/slack-integration.md`) rather than working
  around it.
- **The channel goes in `target.metadata` under the key `channel`** —
  `{"channel": "<name>"}` is the only key a `slack` target accepts. The model types
  `metadata` as a free-form string map, but the service validates it: a missing or
  blank `channel`, or any other key, is rejected at create and update time. A leading
  `#` is tolerated (it is stripped before the channel is matched against the access
  profile's grant), so `#oncall` and `oncall` name the same channel — write the bare
  name.
- **Multiple channels** → one rule per channel, each carrying the same integration
  ARN and its own channel metadata.
- The access profile (Step 6) must grant the alert use of that Slack integration
  (`cloudwatch:InvokeIntegration` scoped to it), and the integration's own grant
  must permit the channel.
- **The CloudWatch Omni Slack app must be invited to the channel.** Slack only
  delivers to a channel the app is a member of, so before (or right after) creating
  the alert, tell the user to invite the CloudWatch Omni Slack app to the channel —
  in Slack, `/invite` the CloudWatch Omni app into `#channel`. Nothing verifies the
  app is in the channel when the alert is created; a missing invite is the first
  thing to check if the alert fires but no Slack message arrives. State it plainly
  as a prerequisite; do not name a specific bot handle you cannot confirm.

#### Which states trigger the notification

`trigger.stateValues` is set **per rule** and applies to every target type:

- **Empty or omitted means ANY state change** — including every return to `OK`. That
  is rarely what "notify me when it fires" means, so **set it explicitly**: the
  default you should write is `["WARNING", "CRITICAL"]`, the two firing states.
- **If Step 3 left `noData.treatAs` at `NODATA`, add `NODATA` to the list** so a
  query that goes silent still notifies. Nothing adds it for you.
- Adjust only when the user asks for something other than that — "only page me on
  critical" → `["CRITICAL"]`; "also tell me when it recovers" → add `OK`.

### Step 6 — Resolve the access profile

An alert evaluates its query under an **access profile**, and `CreateAlert` requires
its `profileId`. This is required for **every** alert — SQL and PromQL, logs and
metrics alike; the service does not pick a default.

**If the user named a profile, use theirs.** Their explicit choice wins; the checks
below are for when they did not make one.

**Otherwise, find one that qualifies — do NOT guess and do NOT ask first.** List the
Space's profiles (`aws cloudwatch-omni list-access-profiles --space-id <space-id>`),
read each candidate (`get-access-profile`, which reports both the permissions it
confers and the trust grants naming who may assume it), and keep only profiles where
**all** of the following hold — these mirror what the service itself enforces:

1. **An `ALERT`-principal trust grant scoped to `principalId=ALL` lets a new alert
   assume it** — a grant with `principalType` `ALERT` conferring
   `cloudwatch:AssumeAccessProfile` on this profile. For a create the grant **must**
   be `ALL`: the `alertId` is minted at create time, so `CreateAlert` authorizes
   against the wildcard alert ARN (`arn:…:cloudwatch:…:alert/*`) and only `ALL`
   matches it. An `ALERT` grant whose `principalId` is an existing alert's ARN keeps
   *that* alert working at runtime, but it cannot satisfy the check for a new one —
   so if a profile's only alert trust grant names specific alerts, report it as not
   usable for this create and say the profile needs an `ALL` grant. `principalId` is
   never an alert's name. Without a qualifying grant `CreateAlert` fails with an
   access-denied error.
2. **It confers both telemetry query actions** — `cloudwatch:StartTelemetryQuery`
   AND `cloudwatch:GetTelemetryQueryResults`, whether spelled out in a `CUSTOM`
   grant's scoped actions or conferred by `READ`/`SPACE_ADMIN`. Note that
   `READ_WRITE_DELETE` does **not** confer them. This one matters most: the
   evaluation calls both APIs under the profile every cycle and **nothing checks
   them when the alert is created**, so a profile missing them produces an alert
   that is accepted and then sits at `NODATA` forever with no error anywhere.
3. **Its data grants cover what the query reads** — the data set (or view) and any
   resource/tag/signal-type narrowing must include the rows the query needs.
4. **It permits the Slack integration** — only when a rule targets one
   (`cloudwatch:InvokeIntegration` on that integration, plus the channel).

Among profiles that all qualify, prefer the one with the least narrowed telemetry
read, then one with an `ALL`-scoped trust grant (which for a create is a requirement
under check 1, not a preference), then a service-managed profile, then the
lexicographically smallest id. If **none** qualifies, do not invent one and
do not fall back to a profile that fails check 2: tell the user which profile is
closest and which grant is missing (the remediation is in
`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/access-profiles.md`), then ask which profile to use
or offer to add the missing grant.

**A system / Standard / service-managed access profile is NOT editable — never
tell the user to edit one.** These are managed profiles; the remediation for a
profile that cannot satisfy the checks is a NEW or custom access grant, added on the
principal the failing check names (the `ALERT` principal for an alert trust grant
under check 1, or the access-profile principal for a telemetry-read grant under
check 2) — NOT an edit to the Standard profile itself. When the closest profile is a
managed one, frame the fix as "add a new access grant," never "edit the Standard
profile." Relay the exact missing grant — the action and the principal it must be
added on — rather than paraphrasing it into "edit the profile."

Resolve the profile **before** confirming, so the confirmation can name it.

### Step 7 — Confirm, then create

**Propose; let the user decide.** Restate the parts they are agreeing to — the
**name**, what the query measures (quote the exact query text; do not paraphrase),
the **threshold with its unit**, the **comparator**, the **evaluation interval**
and **no-data treatment**, and the **access profile** the alert will run under —
e.g. "…and I'll run it under profile `alert-profile`, which grants this data and
the Slack integration". If a notification was requested, also restate **the
target(s) and which states notify** — "and post to #oncall-alerts on WARNING and
CRITICAL". A user cannot confirm what was not restated. Create the alert only after
they confirm that specific proposal.

Then call `CreateAlert`. The request, with every field from Steps 1–6 in the shape
the [API reference](#createalert) documents:

```bash
aws cloudwatch-omni create-alert --region us-east-1 --cli-input-json '{
  "spaceId": "<space-id>",
  "profileId": "<profile-id>",
  "name": "checkout-5xx-errors",
  "description": "Checkout returned more than 200 5xx responses in the last 5 minutes",
  "rule": {
    "telemetryRule": {
      "query": {
        "expression": "SELECT COUNT(*) AS error_count FROM logs.default WHERE `@timestamp` BETWEEN NOW() - INTERVAL '\''5 MINUTE'\'' AND NOW() AND service_name = '\''checkout'\'' AND status_code >= 500 ORDER BY error_count DESC LIMIT 500",
        "language": "SQL"
      },
      "condition": {
        "thresholdMode": "FIELD_VALUE",
        "thresholdField": "error_count",
        "comparator": "GT",
        "criticalThreshold": 200
      },
      "evaluation": { "intervalSeconds": 300 },
      "noData": { "treatAs": "OK" }
    }
  },
  "notificationsEnabled": true,
  "notificationRules": [
    { "trigger": { "stateValues": ["WARNING", "CRITICAL"] },
      "target":  { "type": "sns", "arn": "arn:aws:sns:us-east-1:123456789012:oncall" } }
  ],
  "tags": { "owner": "payments" }
}'
```

`rule.telemetryRule.query` has exactly two members in the service model:
`language` (`SQL` or `PROMQL`) and `expression` (the query text, 1–10,000 characters).

The response carries the created `alert` — `alertId`, `alertArn`, `name`,
`profileId`, `rule`, `notificationRules`, `notificationStatus`, timestamps — so you
do not need to read it back for its id. Tell the user the alert exists now, quoting
the stored query from the response so they can see it matches. If the call fails,
the error says why — a rejected definition (`ValidationException`, including
`Access profile not found` for a bad `profileId`), the space's alert limit
(`ServiceQuotaExceededException`), an unknown space (`ResourceNotFoundException`), a
`ConflictException`, or missing permission — relay it and fix the specific problem
rather than retrying the same call.

**Slack delivery prerequisite (say this on a successful create with a Slack
target).** For Slack to deliver, the CloudWatch Omni Slack app must be a member of
each channel — so after the create lands, remind the user to invite the CloudWatch
Omni Slack app to the channel (`/invite` it into `#channel` in Slack). Channel
membership is not validated; a missing invite is the first thing to check if the
alert fires but no Slack message arrives — symmetric with the SNS topic-resource-
policy note in Step 5a. Do not name a specific bot handle you cannot confirm.

**A permission / access-denied failure on the create is about the caller or the
profile, not something to work around.** If `CreateAlert` fails with
`AccessDeniedException`, it is either the caller's own permission to create an alert
in the space, OR the access profile's grants (Step 6 — the alert may be unable to
assume the profile, or the profile lacks the telemetry-read grants). Relay the
error's own reason, say which of the two it is, and point the user at the right
owner (a Space administrator for their own permission; the profile's grants for a
profile denial). Do not suggest broadening credentials to get past it.

**A duplicate is held off, not created — and that is YOUR call, before the write.**
Two alerts on one condition do not watch it twice; they notify twice, and the second
has to be found and deleted later. Nothing in the service stops this — one call
creates one alert. Compare the alerts the request asked for **against each other
before you create any of them**, and check the space with `ListAlerts` when the ask
implies one may already exist.

Two of them are the same alert when they would **fire on the same condition**: the
same measurement at the same threshold, comparator, timings and no-data behaviour.
Judge that on what each alert **watches**, never on what it is **called**:

- **A different name is not a different alert.** You choose the names, so two names
  for one condition is the normal shape of this mistake.
- **The same condition worded two ways is one alert.** `status >= 500` on checkout
  and "checkout 5xx over 100 in five minutes" are the same alert if they measure the
  same thing at the same level. Compare what the query MEANS, not its text.
- **Different notification targets do not split it — but ASK before you merge
  them.** Two asks for one condition that differ only in where they notify are one
  alert. Create it once, hold the other ask off, and ask whether to add its target to
  the alert that now exists — on a yes, `UpdateAlert` with the **full**
  `notificationRules` list (it replaces, it does not merge). A **single** ask naming
  both at once — "Slack me and page the on-call when checkout 5xx spikes" — is ONE
  alert carrying both rules, built in a single call, no question needed.
- **A different threshold, interval, or comparator IS a different alert.** Warning
  at 100 and critical at 500 on one alert are two tiers of one alert; a 5-minute and
  a 1-hour window are two real alerts.

You are comparing **this request only**. A create that succeeds proves nothing about
the rest of the space: never tell the user their alert is the only one watching that
condition unless you listed the space and read the candidates' rules.

### Handling several alerts at once

"Set up alerts for 5xx, p99 latency, and error rate on checkout" is three alerts,
not one query with three conditions. Run Steps 1–7 **once per alert**:

- Ground them **one at a time** — each query is independently grounded, so one
  failing does not spoil the others.
- **Cap the batch and say so.** Draft about five and tell the user which ones you
  did not draft. Silently stopping reads as "that was all of them."
- **Name partial failures.** If three ground and two could not, present the three
  and say what the other two need — usually a service or field name. Never quietly
  drop one.
- Keep one **shared time window** across the batch so the alerts are comparable.
- Present them as a numbered list the user can accept or reject **individually**.
  After a batch, a bare "yes" is **not** approval of everything — ask which ones, or
  confirm them one at a time. Creating four alerts someone did not want is worse
  than asking a second question.
- **Two of them measuring the same thing is one alert.** "Alert me on checkout 5xx,
  and also page me if checkout starts erroring" is one condition asked for twice.
  Notice that **while drafting** and draft it once, saying which of their asks it
  covers.
- One `CreateAlert` call per confirmed alert; report each result separately.

### Worked examples

Field and metric names below are illustrative; confirm real ones from the live
schema before using them.

**One number, one row — the shape to aim for.** "Alert me if checkout returns more
than a few hundred 5xx in five minutes."

```sql
SELECT COUNT(*) AS error_count
FROM logs.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '5 MINUTE' AND NOW()
  AND service_name = 'checkout'
  AND status_code >= 500
ORDER BY error_count DESC
LIMIT 500
```

A log condition, so the threshold is the user's to give ("a few hundred" is not a
number — ask). `language=SQL`; condition `thresholdMode=FIELD_VALUE`,
`thresholdField="error_count"`, `comparator=GT`, `criticalThreshold=<user's
count>`; `intervalSeconds=300` (matching the 5-minute window);
`noData.treatAs=OK` (no rows means no errors).

**An AWS service metric, grounded.** "Alert me when my queue backs up."

A metric, so PromQL. Grounding the metric name against live data resolves it to SQS's
`ApproximateAgeOfOldestMessage`. AWS's published recommendation for that metric gives the
unit (seconds), the recommended statistic (Maximum), the comparator (`GTE`), a
60-second period — and **no** numeric threshold, because the right age depends on the
consumer. So propose everything except the number, ask the user for that one thing,
write the PromQL to aggregate with `max` (Step 2c), and create with
`intervalSeconds=60`.

**A histogram percentile — a metric, so raw PromQL.** "Alert me when checkout p99
latency goes over 2s."

```promql
histogram_quantile(0.99, rate(http_server_duration_seconds{service="checkout"}[5m]))
```

`language=PROMQL`. The `[5m]` range bounds the query in time. `2s` stays **out** of
the query — it is `criticalThreshold=2` with `thresholdMode=FIELD_VALUE`, in seconds,
matching the series' unit. The percentile comes from `histogram_quantile` over the
**base metric name** — no `_bucket`, no `by (le)`.

### Common gotchas

- Suggesting a threshold for a custom metric or a log condition. Ask; never invent.
- Writing a **metric** alert as SQL. Metrics are PromQL only.
- A histogram percentile written over `_bucket` / `by (le)` series — empty in Omni,
  so the alert never fires. Use `histogram_quantile(…, rate(<metric>[5m]))` on the
  base metric name.
- A `LIMIT` on a `COUNT_OF_RESULTS` alert — it caps the row count, so a "more than
  N" alert can never fire. Omit `LIMIT` (or use `COUNT(*)` + `FIELD_VALUE`).
- An `intervalSeconds` outside the accepted set, or a pending/recovery duration that
  is not a multiple of it.
- A query with no time window, or an absolute one — the alert supplies none, so the
  query never evaluates as intended.
- Sorting by `` `@timestamp` `` after aggregating — it is no longer in the result.
- Threshold units not matching the value's units (seconds vs milliseconds).
- A `HAVING` or inline comparison that duplicates the alert's own threshold.
- Ascending sort under a `LIMIT` — evaluates the oldest data in the window.
- Leaving `noData.treatAs` at `NODATA` for a query that returns nothing when
  healthy — and, conversely, not adding `NODATA` to `trigger.stateValues` when
  silence is what the user wants to hear about.
- Leaving `trigger.stateValues` empty — that notifies on **every** state change,
  including recoveries the user did not ask about.
- Inventing a field name to make a query look complete. An alert on a non-existent
  field is silently dead — worse than an alert that errors.
- Deriving a `warningThreshold` from AWS's single published number. That number is
  the critical value; only add a warning tier when the user asks for one.
- Skipping the statistic reconciliation (Step 2c): AWS recommends `p90` but the
  query used `AVG`. Rewrite the query; don't paper over it in the condition.
- A `profileId` whose profile lacks `StartTelemetryQuery` + `GetTelemetryQueryResults`
  — accepted at create time, `NODATA` forever afterwards.

---

## Updating an alert

Changing an existing alert **is** supported — `UpdateAlert` changes it in place,
addressed by `alertId`. Retuning a threshold, changing the query or how often it
evaluates, changing where it notifies, renaming, changing the access profile, and
muting/silencing/pausing all land here. **Deleting is a separate operation** —
removing the alert for good is [Deleting an alert](#deleting-an-alert), and muting
is not deleting.

Two semantics make an update different from a create, and getting either wrong is
**silently** wrong:

- **Top-level fields are PATCH (apply-if-present); inside `rule`, a sub-block is
  REPLACED WHOLE.** An omitted top-level field (`name`, `description`, `profileId`,
  `notificationsEnabled`) is left unchanged, and so is any `telemetryRule` sub-block
  you do not send (`query`, `condition`, `evaluation`, `noData`). But a sub-block you
  DO send replaces the stored block in its entirety — optional members you leave out
  of it are **cleared**, not kept. Sending `condition` with only `criticalThreshold`
  removes the warning tier; sending `evaluation` without `pendingDurationSeconds`
  clears it. So send only the sub-blocks that change, but **re-send each of those
  complete** — every member read off `GetAlert`, with just the changed value swapped
  in. ⚠️ This loss is silent: the call succeeds and nothing warns you.
- **`notificationRules` behaves the same way at the top level: present, it REPLACES
  the entire list.** It does not merge, and it does not replace per target type. To
  add one target, send every rule the alert should end up with, not just the new
  one. To remove one target, send the list without it. Omitting the field leaves
  existing rules unchanged; sending an **empty list** clears every rule.

Also:

- **A rename goes through `name`; `alertId` still says WHICH alert.** The `alertId`
  survives a rename, so ARNs and anything holding the id stay valid. Names are not
  unique, so a rename never conflicts — but check `ListAlerts` for an existing alert
  of the new name and warn the user if the rename would create a confusing twin. A
  rename does not disturb the access profile: an `ALERT` trust grant is keyed on the
  alert's ARN (which carries the `alertId`, not the name) or on `ALL`, so neither
  form is affected by a name change (Step 6 of creating).
- **The access profile CAN be changed here**, with `profileId` — that is the repair
  for an alert that was created under a profile which cannot run its query (it sits
  at `NODATA`), and it keeps the alert's history, which delete-and-recreate does
  not. Qualify the replacement exactly as Creating, Step 6 does.
- **Tags are not changed here** — `UpdateAlert` does not carry tags. Use
  `aws cloudwatch tag-resource` / `untag-resource` on the alert ARN; see
  [Tagging an alert](#tagging-an-alert).
- **`UpdateAlert` returns an empty response.** Read the alert back with `GetAlert`
  to confirm the new configuration before reporting it.

This is a **procedure** — work the steps in order.

### Step 1 — Which alert?

Ask WHICH alert when the user was not specific: changing the wrong alert is worse
than a second question. Resolve the name to an `alertId` with `ListAlerts` and
`filterCriteria.names`; if the name matches two alerts, show both (name, state,
created date, and — after `GetAlert` — what each watches) and ask which one. If the
user names several alerts, run this procedure once per alert.

### Step 2 — Read it, and find out what should change

- **Read it first** with `GetAlert`. It returns the alert **whole** — the query
  expression it evaluates, its threshold and comparator, its cadence, its no-data
  behaviour, and where it notifies. Read the current values off it — never state or
  change a value you have not read.
- **Ask WHAT should change** when the user was not specific: its `condition`
  (threshold mode, field, comparator, warning/critical thresholds), the query, the
  evaluation interval, its no-data behaviour, or where it notifies.

### Step 3 — Ground the new value the same way a new alert's is grounded

Whatever is changing, work out the new value exactly as [Creating an
alert](#creating-an-alert) does — do not invent one:

- **A new threshold** is a change to the `condition` block. The threshold mode, field
  and comparator you read off the alert decide what the new number means — a number
  alone can be right against one of them and wrong against another. For the value
  itself on an AWS-vended metric, consult the published guidance (Creating, 2b); on
  a custom metric or a log/trace condition, ask the user. **Never invent a
  threshold.** Warning and critical are separate: change only the one the user
  named — but the `condition` block you send must still carry **both** (plus
  `thresholdMode`, `thresholdField`, `comparator`) as read off `GetAlert`, because
  the block replaces the stored one whole and a tier you leave out is deleted. Keep
  them ordered so critical is the more severe.
- **A new query** → author and ground it per Creating, Step 1: relative time window,
  one comparable number, no threshold baked in, correct `language`. If the alias
  changes, update `thresholdField` in the same call.
- **A new cadence** → the same accepted `intervalSeconds` set, with any
  pending/recovery duration a multiple of it (Creating, Step 3).
- **A new or changed notification** → work out whether the user is ADDING,
  REPLACING or REMOVING a target, then send the **complete** `notificationRules`
  list that is the END STATE — `notificationRules` replaces the whole list, it does
  not merge. In all three cases, read what the alert notifies now off `GetAlert`
  (Step 2) first, then build the list the alert should end up with:
  - **ADD** — end state is ALL of the existing rules PLUS the new one. Sending only
    the new rule silently drops the rest: the alert keeps firing and stops reaching
    them. For example: "also page ops-critical", "add #sre to it".
  - **REPLACE** — end state drops the existing target(s) and holds only the target
    the user asked for. If they named ONE target to swap out, swap out only that
    one and keep the others. For example: "switch it from ops-warning to
    ops-critical".
  - **REMOVE** — take out ONLY the rules for the targets the user named and keep
    every other rule; end state is the existing rules MINUS the named ones. To
    remove **every** notification, send an empty list — but only when the user
    explicitly asked for that. Omitting the field keeps the existing rules.

  Same rules as Creating, Step 5 — never invent a channel or a topic ARN, at most
  5 rules, integration ARNs from `ListIntegrations`, `trigger.stateValues` set
  explicitly. Unless the user asked to change WHEN it notifies, carry each existing
  rule's `stateValues` over unchanged — an alert that paged on `CRITICAL` alone must
  not start paging on `WARNING` because you rewrote its list.
- **Mute / silence / pause** → `notificationsEnabled=false`. That is the right way
  to quiet an alert — do NOT raise its threshold out of reach, which changes what it
  watches. Unmute with `notificationsEnabled=true`.
- **Clear the description** → send `description` as an empty string. The model
  allows a zero-length value and the update applies any `description` that is
  present, so `""` is stored and the alert reads back with an empty description;
  only an *omitted* `description` leaves the existing text unchanged.

### Step 4 — Confirm the specific change, then update

**Propose the change and let the user confirm it** — name the alert, what is
changing, and the from/to ("checkout-5xx-errors goes critical above 200 today; I'll
set it to 500"). State which fields the call will overwrite, and — if
`notificationRules` is in the call — that it replaces the whole list. Only after
they confirm, call `UpdateAlert` with `spaceId`, `alertId`, and **only the fields
and sub-blocks that change — each sub-block sent complete**:

```bash
aws cloudwatch-omni update-alert --region us-east-1 --cli-input-json '{
  "spaceId": "<space-id>",
  "alertId": "6c8971b543d54148a26fc793f46db68c",
  "rule": { "telemetryRule": { "condition": {
    "thresholdMode": "FIELD_VALUE", "thresholdField": "error_count",
    "comparator": "GT", "criticalThreshold": 500 } } }
}'
```

That `condition` is the alert's **whole** block — every member read back from
`GetAlert`, with only `criticalThreshold` changed. Had the alert also carried a
`warningThreshold`, it would have to be in there too, or the update would drop it.

If the alert already has every value asked for, say it is already set that way and
send nothing — do not report a change. If the call fails
(`ResourceNotFoundException`, `ConflictException`, a `ValidationException` such as
`Access profile not found`, or access denied), relay why and fix that specific
problem rather than retrying. On success, `GetAlert` the alert back and confirm the
change is live from what it returns.

---

## Deleting an alert

Deleting an alert **is** supported — `DeleteAlert` removes one alert by `alertId`.
This is the one **destructive** operation here: a deleted alert stops evaluating and
firing, its rule and its notification rules go with it, and **nothing brings it
back**. So it is the one operation that is always read back and confirmed before the
call, and muting is offered whenever that is what the user actually wants.

- **Muting is not deleting.** If the user only wants the alert to stop paging them,
  that is [Updating](#updating-an-alert) with `notificationsEnabled=false` — it
  leaves the alert intact so it can be switched back on. Offer this when the ask is
  "stop it messaging me" rather than "get rid of it".
- **`DeleteAlert` is idempotent.** Deleting an alert that is already gone succeeds
  without error, so a success does **not** prove you deleted the alert you meant.
  Confirm the target up front by `alertId` rather than checking after.
- **There is no batch delete.** "Delete these four" is one confirmation covering all
  four, then one `DeleteAlert` call per alert. Report each result separately.
- **Never create a replacement**, and **never report a deletion that did not
  happen.** A failed call (access denied, service error) means the alert is still
  there; say so.

This is a **procedure** — work the steps in order.

### Step 1 — Which alert(s)?

Ask WHICH alert(s) whenever the user was not specific: deleting the wrong alert
cannot be undone, so a second question is always cheaper than a wrong delete.

**Resolve every name to an `alertId` before deleting anything.** Names are not
unique in a space. Call `ListAlerts` with `filterCriteria.names` (up to 50 exact
names in one call) — a shared name comes back as two summaries. For any name that
matched more than one alert, show the matches (name, state, created date, and what
each watches once read) and ask WHICH one the user meant; carry only confirmed
`alertId`s forward. For a batch this matters doubly: you want every id settled
before the first delete, not discovered mid-way after some alerts are already gone.

### Step 2 — Read them, so you can say exactly what will go

The confirmation has to name what each alert actually removes — what it measures,
its threshold, and where it notifies — so read each alert IN FULL with `GetAlert`
first. A list summary is not enough: `ListAlerts` carries only name, id, state and
the notification switch, not the rule or the targets. Never describe an alert you
have not read, and for a batch never confirm a list you have not read item by item.

### Step 3 — Confirm the specific alert(s), then delete

**State that this is permanent and name each alert**, then let the user confirm —
"this deletes checkout-5xx-errors and latency-p99 for good, including
checkout-5xx's Slack notification to #oncall; it can't be undone. Delete them?". A
user cannot confirm what was not restated, and this confirmation is not optional.
Only after they confirm:

```bash
aws cloudwatch-omni delete-alert --region us-east-1 \
  --space-id <space-id> --alert-id 6c8971b543d54148a26fc793f46db68c
```

One call per confirmed `alertId`. If a call fails, relay why (no permission, service
rejected it) and fix that specific problem rather than retrying; the alerts whose
calls succeeded are gone — retry only the ones that failed, never the whole list.
Report the alerts you deleted by name, and any that were not deleted.

---

## Tagging an alert

Tags can be set at create time via `CreateAlert.tags` (Creating, Step 4). **After
creation they are managed through the CloudWatch tagging APIs, keyed on the alert's
ARN** — the `cloudwatch-omni` alert operations do not read or write them (`UpdateAlert`
has no `tags` member, and neither `GetAlert` nor `ListAlerts` returns them). This is a
**direct write**, not a procedure: no query to build, no threshold to ground. Confirm the
specific change with the user first, the same as any other write.

Resolve the alert first (`ListAlerts` with a `names` filter, or `GetAlert`) and take
`alertArn` from the result. Then:

```bash
# read
aws cloudwatch list-tags-for-resource --region us-east-1 --resource-arn <alertArn>
# add or change (upsert on the keys you name; other tags are untouched)
aws cloudwatch tag-resource --region us-east-1 --resource-arn <alertArn> \
  --tags Key=owner,Value=payments Key=env,Value=prod
# remove
aws cloudwatch untag-resource --region us-east-1 --resource-arn <alertArn> --tag-keys env
```

A tag is what IAM conditions, cost allocation and console search are written over,
so a change to one is not cosmetic:

- **Tag writes are UPSERTS on the keys you name and leave every other tag alone.**
  There is no "replace all tags"; removing a tag means naming its key to
  `untag-resource`. Pass only what the user said.
- **Pass the user's key and value verbatim.** Do not translate `env` into
  `Environment` because it reads better, and do not fill in a value the user did not
  give — ask which value they mean.
- **Tag keys are CASE-SENSITIVE.** `Owner` and `owner` are two different tags. Read
  the alert's tags first and, if the key the user named is not the one it carries,
  say so before writing. If the write would add a key that means the same as one
  already there, point it out and offer to remove the older key rather than
  removing it uninvited.
- **Before removing anything, read the alert's tags and name the key and its value
  back to the user.** Nothing restores a removed tag.
- **Report what the alert carries from what you read back after the write**
  (`list-tags-for-resource`), never from what you sent.
- **A tag key under the reserved `aws:` prefix is refused.** Tell the user that
  prefix is reserved and ask for a different key.
- Key limits are 1–128 characters, values 0–256; CloudWatch allows up to 50 tags per
  resource.

If the name given matches more than one alert, show the matches and ask which one
rather than picking.

---

## Fetching alerts

Listing, filtering, querying, getting, showing and describing alerts are all this
one operation. It is a **direct call**, not a procedure: do not run the create
steps for it, and do not ask the user to confirm a fetch.

A fetch is one of two shapes, and the shape decides the first call:

- **A set of alerts** — "everything critical right now", "what do I have",
  "the alerts starting with checkout" — starts with **`ListAlerts`**. It is the
  only call the service filters, so push the ask into its `filterCriteria` and
  narrow from what it returns — never the other way round.
- **One specific alert** — "what is *name* set to" — is `ListAlerts` with
  `filterCriteria.names=[<name>]` to get the `alertId` (or straight to **`GetAlert`**
  if you already hold the id), then `GetAlert` for the rule.

A **state-history ask** — "did it flap?", "what changed?", "did it fire earlier?",
"has this happened before?", "when did it last go critical?" — is the second shape
with a caveat: **there is no state-history operation**, and the alert record carries
only its current `state.value` and `state.transitionedAt`, never the previous state
(see [Alert state](#alert-state)). Answer with what the read gives — the state and
how long it has been in it ("`OK` since 09:42, so it left its previous state 4
minutes ago") — and say plainly that earlier transitions and the previous state are
not available from the API. Do not infer a history from one timestamp. It concerns
ONE alert at a time, so ask which alert when the user was not specific.

### Step 1 — list first, with every filter the ask supports

`ListAlerts` returns `AlertSummary` items — name, `alertId`, `alertArn`, `state`,
`notificationStatus`, `profileId`, timestamps. What is *not* on a summary is what
the alert measures, its threshold, and where it notifies (read those with `GetAlert`),
and its tags (read those with `aws cloudwatch list-tags-for-resource` on the `alertArn`).

**`state.transitionedAt` is load-bearing, not decoration.** It is when the alert
ENTERED its current state — not when it was last evaluated, so never present it as
an evaluation time. A status answer reports the state's **age** alongside the state
itself, and a transition inside the **last hour** is called out explicitly: "OK, but
it recovered from a breach 4 minutes ago", "CRITICAL for the last 12 minutes". An
alert that just flapped back to `OK` and an alert that has been `OK` for a month read
identically on `state.value` alone — the age is what tells them apart, and it is
already on the summary.

The server-side filters are the whole of what the service narrows on
(`AlertFilterCriteria`, detailed in the [API reference](#listalerts)):
`names` / `namePrefix` / `ids` (mutually exclusive — at most one), `stateValue`
(how "what is firing right now" is answered — `["WARNING", "CRITICAL"]`), and
`notificationsEnabled`; plus `sortBy` (`NAME` | `STATE`) and `sortOrder`. Read
**`items`** from the response — there is no `alerts` member — and **follow
`nextToken`**: the first page is not the complete set. Say how many matched.

```bash
aws cloudwatch-omni list-alerts --region us-east-1 --space-id <space-id> \
  --filter-criteria '{"stateValue": ["WARNING", "CRITICAL"]}' --sort-by STATE
```

### Step 2 — refining on the alert's own attributes

**Query type** is the common one — "which alerts use PromQL", "which ones alert on
logs" — but the same procedure serves any attribute that lives on an alert's rule
rather than its summary: its threshold, its evaluation interval, its notification
targets. None of them is a list filter.

1. `ListAlerts` with every filter the ask still supports. If the ask names no
   filterable quality at all — "which alerts use PromQL" names none — this is an
   enumeration of the space, which is expected and correct here.
2. `GetAlert` for each alert that came back (there is no batch read — one call per
   alert, so say so if the space is large and offer to narrow first).
3. Refine on the attribute yourself (`rule.telemetryRule.query.language`,
   `condition.criticalThreshold`, `notificationRules[].target.type`, …), and answer
   from what matched.

### Step 3 — refining on a custom attribute, which means tags

Service, team, environment, owner, cost centre — these are the customer's **own**
attributes, they live in the alert's **tags**, and the keys are whatever that
customer chose. Tags are not a `ListAlerts` filter, are not on an `AlertSummary`, and
are not on `GetAlert` either, so there is no server-side way to look an alert up by tag:
`ListAlerts` (narrowed by whatever filters the ask supports — a `namePrefix` often
encodes the same team or environment), then read each alert's tags with
`aws cloudwatch list-tags-for-resource --resource-arn <alertArn>` and keep the matches.
Keys are **case-sensitive** — use the key the user actually said. Say what you scanned
if you stopped early.

Rules for the fetch path:

- **These are the space's Omni alerts** — not CloudWatch metric alarms. Do
  not answer an Omni alert-inventory question from `aws cloudwatch describe-alarms`.
- **Never present a freshly-recovered alert as plain "all clear".** A
  `CRITICAL → OK` transition 4 minutes ago IS the answer to "is anything firing?",
  not a footnote. Whenever a status answer names an alert, state how long it has
  been in its state, and lead with any transition inside the last hour — a user
  asking "is anything firing?" minutes after a flap is almost always asking about
  that flap.
- **Do not describe configuration you did not read.** A list gives you names and
  states only; you do not know a threshold until `GetAlert` returned it, and you do
  not know an alert's team until you read its tags with `list-tags-for-resource`.
- **Say what you narrowed over.** If the answer came from 20 of 40 alerts because
  you stopped paging, say so — a filtered answer presented as complete is worse than
  no answer.
- **A name that does not exist comes back as an empty `items`, not as an error.**
  Say so plainly and offer to list what does exist. Do not retry with a guessed
  name. A name shared by two alerts comes back as two summaries — ask which one,
  then fetch by `alertId`.
- **A fetch that FAILS fails.** An `AccessDeniedException` or a service error is a
  broken call, not a finding about the user's alerts. Never report "you have no
  alerts" from one.
- **Answer in the user's terms** — "checkout-5xx-errors has been critical for the
  last 12 minutes, the other four are OK" — not a dump of the API output.

---

## API reference

Five operations manage alerts. All of them are **space-scoped** — `spaceId` is
required on every one — and all can return `ValidationException`,
`AccessDeniedException`, `InternalServerException`, and `ThrottlingException` in
addition to the per-operation errors noted below.

### CreateAlert

Creates a new alert in a space. Returns the created **`alert`** — the same `Alert`
shape `GetAlert` returns (`alertId`, `alertArn`, `name`, `profileId`, `rule`,
`notificationRules`, `notificationStatus`, `createdAt`, `updatedAt`, …) minus the
live `state`. Read everything off `alert`: you do not need to read the alert back
for its `alertId` or timestamps, and `GetAlert` is only for the live `state`. The
`tags` you passed are **not** echoed back; read them with
`aws cloudwatch list-tags-for-resource --resource-arn <alertArn>`.

| Input | Required | Notes |
|---|---|---|
| `spaceId` | ✔ | The space to create the alert in |
| `profileId` | ✔ | The access profile the alert evaluates its query with. Caller-supplied; the service does not pick one |
| `name` | ✔ | Display name, 1–256 chars, `[a-zA-Z0-9_.@~()-]`. Not unique, not the identity |
| `rule` | ✔ | The evaluation rule — `rule.telemetryRule` with `query`, `condition`, `evaluation`, `noData` |
| `description` | | ≤1024 chars |
| `notificationsEnabled` | | Defaults to `true` |
| `notificationRules` | | 0–5 rules |
| `tags` | | Key/value map. Not echoed back by `CreateAlert`/`GetAlert`/`ListAlerts`; managed afterwards with the CloudWatch tagging APIs on the alert ARN |

`rule` is the substance of the call, and `rule.telemetryRule` is the rule type an
alert uses. On create, all four of its blocks — `query`, `condition`, `evaluation`,
and `noData` — are expected to be present; they are individually optional only so
that `UpdateAlert` can change one block on its own.

Errors beyond the common set: `ServiceQuotaExceededException` (the space's alert limit),
`ResourceNotFoundException` (unknown space), `ConflictException`. An unknown
`profileId` is **not** a `ResourceNotFoundException`: it fails as a 400
`ValidationException` (`Access profile not found: …`), on both `CreateAlert` and
`UpdateAlert`.

### GetAlert

Retrieves a **single alert in full** by `alertId`. This is the only way to read an
alert's rule — the query expression it evaluates, its condition and thresholds, its
cadence, and its no-data treatment — none of which appear in list results.

| Input | Required |
|---|---|
| `spaceId` | ✔ |
| `alertId` | ✔ |

Returns the full `Alert`: `name`, `alertId`, `description`, `accountId`, `spaceId`,
`profileId`, `rule`, `notificationStatus` (`ENABLED` | `DISABLED` — the read-side form of
the `notificationsEnabled` input flag; the output carries only `notificationStatus`), `state` (`AlertStateInfo`),
`notificationRules`, `createdAt`, `updatedAt`, and `alertArn`. There is **no `tags`
member** — read tags with `aws cloudwatch list-tags-for-resource --resource-arn <alertArn>`.
Read-only. Returns `ResourceNotFoundException` when the alert does not exist.

### ListAlerts

Enumerates alerts in a space, with **server-side filtering, sorting, and
pagination**.

**Read the summaries from `items`** (required) and page with `nextToken`. Those are
the only two members of the response — there is no `alerts` alias, so an agent that
reads `alerts` finds nothing and wrongly reports that the space has no alerts.

Each entry is an `AlertSummary` — `name`, `alertId`, `spaceId`, `profileId`,
`notificationStatus` (`ENABLED` | `DISABLED`; there is no `notificationsEnabled` on the
output — that name is the input flag), `state`, `createdAt`, `updatedAt`, `alertArn`.
A summary deliberately **does not carry the rule**, so it cannot answer "what is
this alert's threshold or query" — use `GetAlert` for that.

| Input | Notes |
|---|---|
| `spaceId` | Required |
| `filterCriteria` | `AlertFilterCriteria`, below |
| `sortBy` | `NAME` or `STATE` |
| `sortOrder` | `ASC` or `DESC` |
| `maxResults` | 1–100 per page |
| `nextToken` | Pagination token |

`AlertFilterCriteria` members combine with AND, except that the three name/id
filters are **mutually exclusive — at most one may be provided**, and the service
rejects more than one:

- **`names`** — up to 50 exact names, OR-combined. Because names are not unique,
  one name can match several alerts; this is the usual way to resolve a name to an
  `alertId`.
- **`namePrefix`** — a single prefix, ≤256 chars.
- **`ids`** — up to 50 exact `alertId`s, OR-combined.
- **`stateValue`** — any of `OK`/`WARNING`/`CRITICAL`/`NODATA`, OR-combined. This
  is how "what is firing right now" is answered.
- **`notificationsEnabled`** — filter by whether notifications are on.

Results are paginated: follow `nextToken` rather than treating the first page as the
complete set.

### UpdateAlert

Modifies an existing alert in place, addressed by `alertId`. Returns an **empty
response** — read the alert back with `GetAlert` to confirm the new configuration.

| Input | Required | Notes |
|---|---|---|
| `spaceId` | ✔ | |
| `alertId` | ✔ | The alert to update |
| `name` | | **Renaming is supported.** The `alertId` does not change |
| `description` | | |
| `profileId` | | The access profile can be changed |
| `rule` | | Send only the sub-blocks that change — each one **complete**, since a supplied sub-block replaces the stored one whole |
| `notificationsEnabled` | | The mute/unmute switch |
| `notificationRules` | | 0–5 rules. **Full replace** — see below |

Two semantics matter here:

- **Top-level fields are PATCH (apply-if-present); `rule` sub-blocks are replaced
  whole.** An omitted top-level field is left unchanged, and so is any
  `telemetryRule` sub-block (`query`, `condition`, `evaluation`, `noData`) you do not
  send — that is why they are individually optional. But a sub-block you DO send
  replaces the stored block entirely: optional members omitted inside it are
  cleared (`condition` with only `criticalThreshold` drops the warning tier;
  `evaluation` without `pendingDurationSeconds` clears it). Always re-send the
  complete sub-block you are touching. ⚠️ The loss is silent — the call succeeds.
- **`notificationRules`: present, it replaces the entire list.** It does not merge.
  To add one target, send every rule the alert should end up with, not just the new
  one. Omitting the field leaves existing rules unchanged; an **empty list clears
  all rules**.

`@idempotent`. Errors beyond the common set: `ResourceNotFoundException`,
`ConflictException`; an unknown `profileId` is a `ValidationException`, as on create.

**Confirm before updating.** `UpdateAlert` mutates live alerting configuration.
Draft the exact change, state which fields it will overwrite (that any `rule`
sub-block sent replaces the stored one whole, and that `notificationRules` replaces
the whole list), and confirm with the user before calling.

### DeleteAlert

Permanently removes an alert by `alertId`. Returns an empty response.

| Input | Required |
|---|---|
| `spaceId` | ✔ |
| `alertId` | ✔ |

**Idempotent** — deleting an alert that has already been removed succeeds without
error, so a successful response does not prove the alert existed beforehand.
Deletion removes the alert along with its rule and its notification rules, and it
cannot be undone. To stop an alert notifying while keeping it, use `UpdateAlert`
with `notificationsEnabled=false` instead.

**Confirm before deleting.** This is a destructive, irreversible write against live
alerting. Name the specific alert (id and name) and confirm with the user before
calling `DeleteAlert` — never delete on inference. Because the call is idempotent, a
success does not tell you whether you deleted the alert you meant, so confirm the
target up front rather than checking after.
