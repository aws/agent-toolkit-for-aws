# Usage interpretation playbook

This file is loaded on demand by the `estimating-aws-workload-costs` skill. SKILL.md
carries the rules the model must follow; this file carries the detail.

## Contents

- [Scope](#scope)
- [Input and output](#input-and-output)
- [Source taxonomy](#source-taxonomy)
- [Fixed AWS facts](#fixed-aws-facts)
- [Duty cycle and rate conversion](#duty-cycle-and-rate-conversion)
- [Low, mid, high rule](#low-mid-high-rule)
- [Picking the question set](#picking-the-question-set)
- [When to ask versus when to assume](#when-to-ask-versus-when-to-assume)
- [Phrasing](#phrasing)
- [Bouncing back to the SCUTO list](#bouncing-back-to-the-scuto-list)
- [Unresolved lines](#unresolved-lines)
- [What the final report shows](#what-the-final-report-shows)

## Scope

The usage-interpretation step runs on the SCUTO list (billing-code
tuples the customer's workload will incur) that the previous step has
derived from the user's architecture description. The customer confirms
the services in plain words, never the SCUTO lines themselves. For every
line in that list, this step decides a monthly usage
amount, a low/mid/high range, and a source tag.

What this step does:

- Picks the smallest set of questions the user needs to answer.
- Fills each line's amount from the user's answers, works it out from
  them, or reasons it from the description and the user's answers, and marks
  it unknown when there is no honest basis.
- Produces three sets of amounts (low, mid, high) so that pricing can turn
  each set into a priced estimate.

What this step does not do:

- Does not identify SCUTOs. SCUTO identification is a separate step
  outside this file; by the time this step runs, the SCUTO list is
  set.
- Does not add or remove SCUTOs. A design change requested by the user
  bounces back to the SCUTO list step.
- Does not look up rates, apply tiered pricing, or produce dollar amounts.
  That is done by the pricing step.

## Input and output

Input it reads from the previous step:

```
{
  "region": "us-east-1",
  "scutoList": [
    {
      "lineId": "L1",
      "serviceCode": "AWSLambda",
      "usageType": "USE1-Lambda-GB-Second",
      "operation": "",
      "unit": "GB-Second",
      "origin": "primary" | "secondary-required" | "secondary-optional-accepted",
      "customerStated": { "memoryMb": 512 },
      "derivedFrom": "the Lambda doing PDF extraction"
    }
  ]
}
```

- `customerStated` carries facts the user already put in the request that
  bear on this line. Treat those as `CUSTOMER_STATED` quantities without
  asking again.
- `origin` is informational. Required secondary lines are priced whatever
  the answer; accepted-optional lines were already agreed to. Do not treat any of
  them differently when filling quantities.
- `derivedFrom` is a short label naming the architecture element that
  produced this SCUTO line. Passed through to the final report so each
  priced line can be traced back to the user's description.

Output to the pricing step:

```
{
  "scutoAmounts": [
    {
      "lineId": "L1",
      "serviceCode": "AWSLambda",
      "usageType": "USE1-Lambda-GB-Second",
      "operation": "",
      "low": 1000000,
      "mid": 5000000,
      "high": 20000000,
      "unit": "GB-Second",
      "source": "ASSUMED",
      "assumption": "Stated 40 req/s peak × 50% average duty cycle (assumed) × 730h × 300ms (assumed) @ 512MB (stated)"
    }
  ]
}
```

- Every line in the input appears in the output. A line that cannot be
  filled still appears, with `source: UNKNOWN` and no `low/mid/high`.
- The SCUTO identifiers (`serviceCode`, `usageType`, `operation`) are
  carried through from the input so the pricing step can build its API
  payload directly without re-joining on `lineId`.
- `assumption` is required on every line that is not `UNKNOWN`.

## Source taxonomy

Every amount is tagged with where it came from, so the customer can tell
which numbers are theirs and which ones to check.

| Source | When to apply | Customer reads it as | Example |
| --- | --- | --- | --- |
| `CUSTOMER_STATED` | A direct answer, or a fact already stated in the request. | "Your number." | "1M requests/month", "512 MB memory". |
| `DERIVED` | Worked out only from facts the user gave and the fixed AWS facts below. Nothing in it is your own value. | "Worked out from your numbers; check the math." | "47,000 req/s, steady 24/7" → 47,000 × 3,600 × 730. |
| `ASSUMED` | At least one input is your own value, reasoned from the description and the user's answers because the user didn't give it. | "Our assumption; check the input it names." | "Stated 3 tasks × 730 h × 2 GB of memory per task (assumed)". |
| `UNKNOWN` | No honest basis to pick a quantity. | "Not estimated, not in the total." | A completely novel service with no comparable workload. |

### Composition rule for the source tag

An amount for a billing line is often **composed** of several inputs,
each with its own provenance. For example, the amount for
`USE1-Lambda-GB-Second` is `requests × duration_seconds × memory_GB` —
three inputs. The customer may have stated the request count and the
memory, and you may have reasoned the duration.

**The line's source tag is its weakest input's**, from weakest to strongest:

1. `UNKNOWN` — if any required input cannot be filled.
2. `ASSUMED` — if any input is your own value.
3. `DERIVED` — if every input is stated or a fixed AWS fact, and the amount
   is worked out from them. A range the user gives ("hundreds of TB", "a few
   thousand") is stated: Low and High are its ends and Mid sits inside it.
4. `CUSTOMER_STATED` — the user gave the amount itself.

The `assumption` field on the output row names **every input and its
origin** (stated or assumed), so the customer can see which specific value
to correct. The source tag is a one-token summary; the assumption text is
the full story.

## Fixed AWS facts

These are billing conventions, not assumptions, so using them keeps a line
`DERIVED`:

| Fact | Value |
|---|---|
| Hours in a month | 730 for a steady-state month (8,760 h a year ÷ 12); for a month the user names, that month's hours (720 for September) |
| Days in a month | 30.4 for a steady-state month (730 h ÷ 24); for a month the user names, that month's days |
| Data sizes | binary: 1 KB = 1,024 bytes, 1 MB = 1,024 KB, 1 GB = 1,024 MB (2^30 bytes), 1 TB = 1,024 GB |
| An always-on resource | the month's hours (730 h for a steady-state month) |
| A resource that bills per AZ, such as a NAT gateway or an interface endpoint | the month's hours × the AZ count |

A service's documented metering rule, such as one DynamoDB read unit per
started 4 KB, is a fixed fact too. A choice the user didn't make, such as
an item size or a duty cycle, is not. When you aren't sure of a metering
rule on a large line, check it in the AWS documentation and name the page in
the assumption.

## Duty cycle and rate conversion

Rate conversion is the error-prone source. Reduce the risk by stating the
duty-cycle assumption explicitly on every rate-derived line (the fraction
of time the stated rate holds), and by offering a follow-up question to
tighten it when the duty cycle is a dominant range-driver.

The formula depends on the rate kind:

| Rate the user gave | Monthly amount | Default duty cycle: Low / Mid / High |
| --- | --- | --- |
| "N requests/second at peak" (or /hour) | `peak × duty_cycle × 3600 × the month's hours` (730 for a steady-state month) | 24h apps: 0.3 / 0.4 / 0.5. Business-hours apps: 0.1 / 0.15 / 0.2. |
| "N orders/day" | `daily_rate × active_days` | B2C/consumer: the month's days (30.4 for a steady-state month). B2B/weekdays-only: the month's working days (22 for a steady-state month). If the description doesn't say which, the month's days, and say so. |
| "N events/day during business hours" | `daily_rate × the month's working days` (22 for a steady-state month) | Working-days baked in; cross-check if the user implies 24/7. |
| "X TB stored, growing P%/month" | `X × (1 + P/100) ^ months_from_now` | Compounding, not a flat rate. One-month estimate: month-1 value. Longer: compounded. |
| "N users concurrent" | `concurrent × active_hours_per_user × days_per_month` | Convert using an active-session-duration assumption. |

Every rate-derived output row's `assumption` field carries the explicit
duty cycle used and whether the user gave it (e.g. "40 req/s peak × 50%
average duty cycle (assumed) × 730h/month"). A duty cycle the user gave,
such as "steady, 24/7", keeps the line `DERIVED`; one you chose makes it
`ASSUMED`.

When the user gave no duty cycle, Mid uses the Mid duty cycle from the table,
and Low and High use its Low and High values. Use these exact values unless
the description fixes one (such as "only during US business hours"), so that
runs given the same answers produce the same amounts. When the duty cycle is
a dominant range-driver, add a follow-up question like "What portion of the
day is this at peak?" so the next round tightens the band.

## Low, mid, high rule

| Source | Low | Mid | High |
| --- | --- | --- | --- |
| `CUSTOMER_STATED` | = Mid | the stated value | = Mid |
| `DERIVED` | the stated inputs' low end (= Mid when they are exact) | worked out from the stated inputs | the stated inputs' high end (= Mid when they are exact) |
| `ASSUMED` | the low end of what the description and the user's answers still allow | your reasoned value | the high end of what the description and the user's answers still allow |
| `UNKNOWN` | — | — | — |

A line gets exactly one source tag, by the composition rule above.

**The band says how sure the amount is.** For an `ASSUMED` line, set Low
and High from the assumed inputs: what values could they take, given what
the user said? A choice the user accepts, such as an instance size for a new
service, doesn't swing month to month, so its band can be narrow; say in the
assumption what you assumed ("assumed db.r7g.large; override if you want a
different class"). A volume you reasoned without any stated anchor is
uncertain, so its band is wide. Bedrock token sizes the user can't describe
are the exception: they take `genai-must-ask.md`'s sizes and band, so every
run sizes the same unknown the same way.

**Impact belongs to the workload, not to the dimension.** Log volume per
request, re-indexing frequency, chunks per query and session storage are
usually low-impact, but any of them can drive a service's cost: on a
high-traffic service, log volume can be the largest line. Judge impact on the
amounts you just filled, using step 4 of §When to ask versus when to
assume, which also says how to size one the user can't answer.

**A setting the user runs but can't recall is not an accepted choice.**
The narrow band above is for a choice the user accepts, such as an
instance size for a new service. When the user says a setting exists and
doesn't know its value, such as a trace sampling rate, a log group's
retention or the dimensions on custom metrics, put Mid at the AWS default
and let Low and High span the values the description and the user's answers
still allow. If nothing narrows it, High is the setting's documented
maximum (tracing every request, retention that never expires). Say in the
assumption that the band is this wide because the setting is unknown.

**Check an assumed value against the shares the user gives.** When the user
gives how a total splits, such as "the metrics log group is 80% of our log
ingestion, WAF logs 13%", size the part whose unit size you know best and
derive the total from its share. Then work out the per-unit size the total
implies for every other part. If an implied size is far outside what that
kind of item usually is, such as a WAF log record well under the few KB one
usually takes, the assumed value that set the total is wrong: re-derive the
total from the better-known part instead of keeping it, and say which part
anchors it. Carry the first total as Low when the two disagree.

## Picking the question set

Follow this order:

1. **Group lines by shared root facts.** Traffic volume ("daily requests"
   or "monthly users") drives many lines across many services. Ask it
   once in customer-natural terms, apply the answer to every line it
   touches.
2. **Write at most one question per line where the amount is uncertain
   *and* would meaningfully affect the total**. Phrase it in customer-natural terms. Attach a short "why" so
   the user can judge how much to invest in answering. The host model decides which
   lines meet this bar using pricing knowledge of the services involved;
   no pricing API call is made at this step.
3. **Mandatory additions.** Any dominant Bedrock-touching line's row
   triggers the GenAI must-ask list in `genai-must-ask.md`. Those
   questions are not negotiable. A design that writes logs at volume
   triggers the log volume question in `cloudwatch-questions.md`, unless
   the description or an answer already gives the volume.
4. **Mandatory addition for contradictions.** When two statements in the
   input disagree (e.g. "40 req/s at lunchtime" with "2 TB of PDFs
   growing 10%/month" implying a different scale), rank the contradiction
   first.
5. **Cap at four numbered questions per turn and eight per round, mandatory
   ones included.** Ask the eight over at most two turns, the highest-impact
   four first.
   Mandatory questions from steps 3 (GenAI must-ask) and 4
   (contradiction-resolving) always make the cut, so they take the first
   places and the cost-lever questions fill the rest. Ask one model's
   must-ask parameters as one numbered question with a sub-point each, and
   the rate type in a sentence. A line that doesn't make the cut takes an
   assumed value. More than eight numbered questions is unusable, and asking
   more rarely makes the estimate closer.

After every answer, re-fill the amounts, re-render the estimate, and drop
any question that targeted a line that is now `CUSTOMER_STATED`.

## When to ask versus when to assume

For each SCUTO line without a `customerStated` value, walk this decision
tree. Stop at the first branch that applies.

1. **Is the line Bedrock-touching AND on the GenAI must-ask list?**
   → ASK, in the user's terms, as `genai-must-ask.md` says. Mark
   `UNKNOWN` only when the user can't give the model or the number of
   calls; a size they can't describe takes that file's sizes. The
   model itself is asked in the SCUTO list step, not here.

2. **Is the dimension a configuration dimension** (instance size, memory,
   IOPS, retention) that neither the description nor the user's answers give?
   → `ASSUMED`. Reason the value from the description and the user's
   answers, using the service's own default where the design doesn't call
   for another, and name it in the row's assumption so the user can
   correct it. When the default sets a large line and you aren't sure of
   it, check it in the AWS documentation.
   A documented default is still `ASSUMED`: the assumption is that this
   workload keeps it.

3. **Is the dimension a scale dimension derivable from root facts the
   customer stated** (traffic volume, users, items)?
   → Derive. Tag `DERIVED` when every input is stated or a fixed AWS
   fact, and `ASSUMED` when the derivation needs a value of your own,
   such as a duty cycle the user didn't give. Show the derivation in the
   row's assumption.

4. **Is the dimension a HIGH-impact scale dimension** (drives >20% of
   the service's cost for this workload)?
   → ASK. Phrase in customer-natural terms. If the user declines, reason
   a value from the description and the user's answers and tag it
   `ASSUMED`, with a band wide enough to show the uncertainty the user
   chose not to resolve.

5. **Otherwise** (a low-impact scale dimension that neither the
   description nor the user's answers give), reason a value from them and
   comparable workloads.
   → If a reasonable estimate is possible, tag it `ASSUMED` and name the
   value and its basis in the assumption.
   → If no honest basis exists, mark `UNKNOWN` and surface it in the
   footer.

**Never stretch a stated count with an assumed factor.** When the user
gives a count and the line bills per unit of size or copies (DynamoDB
writes per KB, logs per destination), apply a factor only if the user
gave it. A count read off a metric may already be in billed units, as
`ConsumedWriteCapacityUnits` is, so ask which it is before multiplying.
If the user can't say, keep Mid at the stated count and carry the factor
in High.

**A count the user gives for a path beats one you derive for it.** When the
user gives a volume for one path, such as "a few tens of millions of lookups",
size that path's lines from it, not from a larger total elsewhere in the
description times a factor you chose. If the two disagree, ask: it is a
contradiction, and it ranks first.

**Never lower an amount with a saving the user didn't state.** A cache hit
rate (DAX, ElastiCache, CloudFront), batching or compression that the user
didn't give is not a reason to shrink a line. When the user names a cache but
not its hit rate, put Mid at a 50% hit rate, Low at 90% and High at 0%, and say
so in the assumption. Apply a hit rate only to the reads the user says go
through the cache: a reader that calls the table directly is not cached. When
the cache's own nodes are a top-three line, ask for its hit rate.

**DynamoDB writes multiply.** An item write also writes each global secondary
index the item projects into, and bills one write unit per started KB of the
item. When DynamoDB is a large line, ask for the item size and the number of
GSIs. If the user doesn't know, keep Mid at one write unit per write, and
carry two GSIs and 4 KB items in High.

**DynamoDB reads come from more than the described flow.** A read bills one
read unit per started 4 KB when strongly consistent, half that when eventually
consistent, and twice that in a transaction. When reads are a large line, ask
whether they are strongly consistent; if the user doesn't know, keep Mid at
eventually consistent and carry strongly consistent in High. A table can also
be read by jobs or services the description doesn't show, such as other
teams' batch jobs. For a running table, ask whether anything outside the
described flow reads or writes it, and how its read and write units compare,
which the table's monitoring shows. If the user says reads far exceed what the
flow explains but can't say by how much, keep Mid at the flow's reads and
carry ten times them in High, and say so in the assumption.

**A global table bills each write in every replica region.** Every item
write, wherever it is made, counts as replicated write units in each replica
region, the one written to included, at the item's write units per write.
Index writes stay ordinary write units, also in each region. Size each region's
storage and point-in-time recovery at the full table size, and its
`<from>-<to>-AWS-Out-Bytes` line at the bytes written each month. Adding a
replica is also charged once, as a restore of the table's size in the new
region (`<region>-RestoreDataSize-Bytes`). The estimate is monthly, so leave
that line out unless the user asks for the month the replica is added, and
tell the user it is a one-time charge per GB of the table.

**A Standard workflow bills every state it enters.** When Step Functions
Standard is a large line, ask how many steps one run goes through, counting
choices, waits, parallel branches and retries, instead of counting the steps
the description names: a description lists the calls that matter, not every
state. Size transitions per run as the steps the user gives. If the user
can't say, Mid is twice the described steps and High three times.

**A running workload bills what it has stored.** If the description
doesn't say whether the workload runs today, ask. For one that does, a
storage line (objects in S3, stored log data, backups) bills what has
accumulated, not one month's growth: ask how much each store holds now.
If the user doesn't know, derive it from the monthly growth and how long
the store has been growing, and ask for that age.

Stored CloudWatch log data bills compressed, so a month of ingestion adds
far less than its ingested GB to the store. Size stored log data as monthly
ingestion × a tenth (Low a twentieth, High a fifth) × the months it has
accumulated, which is the store's age capped at the log groups' retention.
Long or never-expiring retention doesn't make the store old: when the user
can't give the age, Mid is 12 months, Low 6 and High the retention or 36,
whichever is shorter. Never size stored logs at the full ingested volume
times the months.

**A corrected line is re-tagged.** When the user later gives a value you
had assumed, the line takes the tag its inputs now earn: `CUSTOMER_STATED`
for the amount itself, `DERIVED` when every input is now stated.

## Phrasing

Questions go to a customer, not to a billing analyst. Keep them in the
user's terms.

| Avoid | Use |
| --- | --- |
| "What's your `USE1-Requests-Tier1` volume?" | "Roughly how many requests per day?" |
| "What read-vs-write ratio does your DynamoDB table have?" | "For your table, is it mostly reads, mostly writes, or roughly balanced?" |
| "What's the Multi-AZ cross-AZ transfer in GB?" | (don't ask — derive from the Multi-AZ decision upstream) |

Group related dimensions in one question when a single answer gives you
both ("How many users, and how many actions per user per day?") instead of
splitting into two.

## Bouncing back to the SCUTO list

A user answer that implies the SCUTO list itself should change is a
SCUTO list problem, not a usage problem. Examples:

- "We don't actually need Multi-AZ" — the cross-AZ transfer line should
  drop.
- "Use VPC endpoints instead of a NAT Gateway" — the NAT Gateway line
  should drop and interface endpoints should appear.
- "Turn off the KMS customer-managed key" — the KMS requests line should
  drop.
- "Add CloudTrail data events" — a new optional line should appear.
- "Use Nova Lite instead of Nova Pro": Nova Pro's lines should drop and
  Nova Lite's should appear.

The skill runs inside one LLM conversation, not a step-function
orchestrator. There is no field to populate and no signal to emit. When
you recognize a design change in a user answer:

1. Pause Q&A. Do not fill any more quantities.
2. Re-run the SCUTO list step with the updated design intent. Present
   the revised services table to the user, as that step says for a
   re-run.
3. Wait for the user to confirm, decline, or iterate on the revised
   design.
4. Resume Q&A on the revised SCUTO list. Quantities you had filled for
   lines that are still in the list carry forward; quantities for lines
   that were dropped are discarded.

## Unresolved lines

A line receives source `UNKNOWN` when:

- The service is novel enough that the model has no reasonable basis for
  a scale amount.
- The user cannot answer and an assumed value would produce a range so wide
  the figure is not useful.
- The dimension is the model or the number of calls for a GenAI line, and
  the user can't give it. A call size they can't describe takes its default
  from `references/genai-must-ask.md`.

An `UNKNOWN` line is listed in the report footer as having no usage
amount, and is not added to the total.

## What the final report shows

The report script renders the report, not this step. For the usage
step, every output row must carry enough information for the report to work:

- `source`, so `UNKNOWN` lines are left unpriced and listed in the footer.
- `assumption`, saved with the line's usage and cost in `cost-estimate-priced.json`.
- Low, mid, and high for every row that is not `UNKNOWN`.

The customer-facing report shows the cost per
service at Low, Mid and High; each line's assumption and source are saved in
`cost-estimate-priced.json`, where the customer reads them, so write
assumptions in plain words.

Nothing else is this step's problem.
