# Incident runbook — serverless startup stack

For the shape most early-stage AWS startups actually run: **Lambda or ECS Fargate, API Gateway, DynamoDB
or Aurora Serverless, often Amazon Bedrock**, in a single account, with no dedicated operations engineer.

Generic operations guidance is not much use at this size. The patterns below are the ones this stack
actually produces.

## Before you investigate

An investigation costs roughly $2.50–$4.00 and takes 5–8 minutes. Spend thirty seconds first:

1. **Get the symptom precisely.** "The API is down" and "checkout returns 502 since 14:10" lead to very
   different investigations. Ask what changed and when they first saw it.
2. **Check for a recent deploy.** In this stack the answer is a recent deploy more often than not. If one
   landed within the window, say so — it may resolve without an investigation at all.
3. **Get the time window.** Narrow beats wide; a vague window makes for a vague finding.

If the symptom is already explained by an obvious recent change, say so and let the user decide whether to
spend the investigation. Do not spend their credits to confirm something you can both already see.

## Patterns worth naming

Recognisable failure shapes for this stack. Use them to sharpen the question you hand to the agent, not to
skip the investigation.

**Lambda throttling.** Concurrent executions hitting the account limit. Presents as intermittent 502s
under load, not a clean outage. Ask whether traffic changed.

**Cold start plus timeout.** A downstream call slowed, so functions that used to finish inside the timeout
now do not. Presents as errors that correlate with traffic troughs — the opposite of what people expect.

**DynamoDB throttling on a hot partition.** One key taking disproportionate traffic. Presents as partial
failure: most requests fine, one customer or tenant broken.

**Bedrock rate limits.** Model invocations hitting per-model TPM/RPM quotas. Presents as AI features
degrading while everything else is healthy. Often the fastest-growing surface in an AI-native startup and
the least monitored.

**IAM permission drift.** A recent infrastructure change narrowed a role. Presents as a single code path
failing with `AccessDenied` while the rest of the service is fine.

**Aurora Serverless scaling lag.** Capacity ramping behind a traffic spike. Presents as elevated latency
resolving on its own — which is why it often goes uninvestigated until it recurs.

## Handing off to the agent

Give it the symptom, the affected service, the time window, and any recent deploy. Then let it work — do
not narrate a running investigation with guesses. Guesses stated while an investigation is in flight tend
to become the user's conclusion regardless of what the agent finds.

## Reporting back

- Lead with the root cause in one sentence.
- Show the reasoning, not just the verdict. A founder with no SRE is also learning their system; the
  reasoning is half the value.
- Surface the proposed fix **for approval**. Never apply it.
- Name what would have caught this earlier — an alarm, a dashboard, a release-readiness review. This is
  where an incident becomes an improvement instead of just an outage.

## After the incident

If this is their first investigation, tell them what it cost. Concretely, from the actual duration. It
builds the habit of knowing, and it means the first bill is never a surprise.

If they have a recurring class of incident, release-readiness review on pull requests catches a
meaningful share of them before they ship — and it works without production traffic.
