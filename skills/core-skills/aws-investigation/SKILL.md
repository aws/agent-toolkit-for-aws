---
name: aws-investigation
description: >-
  Investigates what is happening in an AWS account from evidence already recorded there. Not for
  capturing new data from running code (snapshots of function arguments on a live service,
  Dynamic Instrumentation), questions answered from the CloudWatch Omni context graph or
  Application Signals service map, or building or changing infrastructure. Covers reading
  deployment records instead of the newest stored version (completed AppConfig deployments, the
  version an alias points to, a stack's current template), following a request through every
  service's own logs (exact per-layer fields, unique failed requests in an alarm's breach window,
  failure boundary per event), and answering questions from the account's data (exact counts and
  breakdowns, coverage of the requested range, exact filters and joins, the rule behind failed or
  unmatched records, verbatim values). Use to triage an alarm, error spike or failed request, trace
  a request across services, or count, break down, extract or join records.
metadata:
  version: "1"
---

# AWS Investigation

An investigation answers a question about what an AWS account is doing, and every claim in the
answer must come from something you read: a deployed artifact, a service's own log record, or a
query result. Inference from names, descriptions, the newest stored version or one service's view
of another is a lead, never evidence.

## Pick the reference

Read the reference that matches the question before you start; most investigations need more than
one.

| The question is about | Read |
|---|---|
| What a deployed system currently does, serves or executes: live configuration, feature flags, parameters, which code runs, reproducing a code path's query, or a first data route that is blocked | [references/deployed-artifacts.md](references/deployed-artifacts.md) |
| A request, alarm or incident that spans several services: tracing one request, counting failed requests, deciding where an event was lost | [references/multi-service-logs.md](references/multi-service-logs.md) |
| Facts in the account's data: finding where data lives, exact counts and breakdowns, filtering, joining or exporting records, the rules behind failed or unmatched records | [references/data-investigation.md](references/data-investigation.md) |
| Whether a finding is complete and a root cause holds: searching every region and scope, paginating before counting, coverage of a date range, one entity vs the whole affected population, consistency of the root cause, whether a runbook fixes the cause, answering the user's own question | [references/completeness-and-root-cause.md](references/completeness-and-root-cause.md) |

## Rules for every investigation

1. **Explore before you give up.** Assume the credentials are the intended environment. Treat
   unfamiliar or internal terms (service nicknames, airport-code regions such as PDX = us-west-2,
   IAD = us-east-1) as search hints: list resources, log groups and data stores in the likely
   regions and search for the identifiers in the request before saying something cannot be done.
2. **Separate evidence from inference.** Keep a short provenance note per claim
   (`claim <- artifact, record or query`). Label anything you did not read as a hypothesis or
   **UNVERIFIED**, with the routes you tried.
3. **Count exactly.** Use aggregate queries run in the engine, scoped to exactly what was asked, and
   report unique entities separately from raw records.
4. **Quote, don't paraphrase.** Give identifiers, field values, error codes and messages exactly as
   the source produced them, including `null` and empty values.
5. **Finish the task.** Produce every requested artifact (files, tables, plans), and state the
   assumptions you made in the final answer.

## Closing checklist

Before submitting your analysis:

1. Have you searched all relevant regions and scopes?
2. Have you paginated through all results, and said which part of the requested range has data?
3. Have you verified the scope of failures (entity-specific vs fleet-wide, the whole affected
   population)?
4. Does your root cause fit all the facts you found?
5. Have you labelled every mechanism you could not confirm as unverified, and reported a
   missing component as a defect only if it was meant to exist?
6. Did your claims about live configuration come from the deployed artifact, not the latest
   stored version ([deployed-artifacts.md](references/deployed-artifacts.md))?
7. For a request that crosses services, did you read each service's own logs and place the
   failure boundary per event ([multi-service-logs.md](references/multi-service-logs.md))?
8. Have you answered the user's specific question directly?
9. Before you finish, have you reread your conclusion against each piece of evidence you
   collected and removed any statement that contradicts it?
10. Have you removed any contradictions between your findings and recommendations, and checked
    each runbook option against the confirmed cause?
