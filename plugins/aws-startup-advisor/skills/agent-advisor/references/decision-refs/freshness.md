# Volatile Facts & Freshness

**Outbound-query rule (applies to every channel below — MCP, WebFetch, or CLI):**
freshness lookups carry ONLY public service, feature, model, or region names (e.g.
"AgentCore session cap", "Lambda MicroVMs launch TPS"). Never include user code,
file contents, prompts, architecture details, or anything else from the workspace
or the run directory in an outbound request — the answer never depends on it.

## Fields to verify at runtime via the AWS MCP Server

- AgentCore microVMs session cap (currently 8h) and Instances session cap (currently 14d)
- AgentCore microVMs compute cap (2 vCPU / 8 GB; Instances lifts it via EC2 choice)
- AgentCore / AgentCore Instances / Lambda MicroVMs region availability (Instances
  launched 2026-08 in a limited region set)
- AWS Agent Registry region availability when Registry is selected, independently of runtime
  (`registry_regions` in `references/runtimes/agentcore.json`; see the procedure below)
- Lambda MicroVMs launch TPS (5, not adjustable)
- FedRAMP certification status for AgentCore and Lambda MicroVMs
- Any Bedrock model price (defer to the `gcp-to-aws` pricing cache; never hardcode here)

## Temporal (design.md — Freshness, temporal units only)

Volatile facts to re-verify when the Temporal branch generates a plan. The AWS MCP Server
does not cover Temporal-side facts; each fact below names its actual verification
channel. Whatever cannot be verified this run stays cached and the footer must say so.

**Public Temporal documentation:** use WebFetch (or the host's web-reading tool) to
read the official pages below directly. These lookups require no Temporal account,
MCP connection, or authentication prompt. Temporal documents this access method at
`https://docs.temporal.io/with-ai.md`.

Use the official access guidance above and `https://docs.temporal.io/llms.txt` to
discover current documentation pages. The feature URLs below are current entry points,
not permanent identifiers. Prefer Markdown; if an entry point moves, returns 404, or
cannot be read, try the HTML page or rediscover the feature page through the index.
A missing page does not establish that a feature was removed. An index entry is only
a discovery result: fetch the linked feature page and observe the fact before marking
it verified. If web access is unavailable, rediscovery or retrieval fails, or the page
does not establish the fact, continue with the cached value and its original snapshot
date, marked unverified. Do not pause the flow to install a server or request a login.

Only a fact actually fetched and observed this run counts as verified. Record each
Temporal result in `design.json.volatile_facts` with `source: "web"` and its source URL
and verification date, or `source: "cached"` and its original snapshot date, so Generate
can report the evidence accurately.

**Verifiable this run (attempt these):**

- **Marketplace listing + commercial terms** — fetch
  `https://aws.amazon.com/marketplace/pp/prodview-xx2x66m6fp2lo` (public page, no auth).
  Confirm: listing resolves (not 404/redirect to search), product name still
  "Temporal Cloud (Pay-as-you-Go)", the $0.01/action pricing dimension, free trial.
  (The Marketplace Catalog API cannot do this — it is seller-scoped; the public page is
  the only buyer-side channel used here; Temporal platform documentation does not verify
  AWS Marketplace terms.)
- **Feature statuses** (Serverless Workers, Workflow Streams, External Payload Storage,
  Worker Versioning) — use these current entry points, rediscovering through the official
  index above when needed:
  - Serverless Workers on AWS Lambda: `https://docs.temporal.io/serverless-workers/aws-lambda.md`
  - Workflow Streams: `https://docs.temporal.io/workflow-streams.md`
  - External Payload Storage: `https://docs.temporal.io/external-storage.md`
  - Worker Versioning: `https://docs.temporal.io/worker-versioning.md`

  CAUTION for Serverless Workers: the docs label has moved before without a GA announcement (it read "Available"
  in 2026-07 while the feature was still pre-release; it reads "Public Preview" as of
  2026-08) — a docs label alone does NOT upgrade it to
  GA — keep the Public Preview label until the user shows GA evidence (e.g. a GA
  announcement post).

**Not verifiable (always cached):**

- $1,000 credits / SCMP / Vendor Insights details beyond what the listing page shows.
- "No official cross-cluster history migration tool" — absence is unprovable by lookup;
  restate as of the last-verified date.

The anti-fabrication rule below applies unchanged: only facts actually fetched and
observed this run may be listed as verified.

## Procedure

1. Identify the volatile facts to check: for the main skill, the `volatile_facts` entries
   (`verify_via_mcp: true`) from the winning runtime's profile JSON; for **add-capabilities**
   (which has no winning runtime profile), the "Hard limits" facts in the relevant service card
   (agentcore.md) instead.
   Check Registry facts only when `registry` is selected. In the main skill, include
   `registry_regions` from `references/runtimes/agentcore.json` even if the winning runtime is
   ECS, EKS, Lambda, or another runtime. In add-capabilities, use the Registry Hard limits entry.
2. Attempt an AWS MCP Server lookup for each.
3. On success (the MCP call returned a value THIS run), use the fresh value and list the field as
   verified.
4. On failure OR if you did not call the MCP at all (unavailable, skipped), use the cached
   `value` and list the field as fallen-back.

**Anti-fabrication rule (do not skip):** Never claim verification you did not perform,
whether via the AWS MCP Server or public web. A fact may appear in its channel's verified
list ONLY if you actually made that channel's lookup this run and observed evidence for
the fact. A skipped, unavailable, failed, or inconclusive lookup goes in the cached/unverified
list with the original snapshot date. If a channel was not called, its verified list is
empty; successful verification via the other channel remains valid.

## AWS Agent Registry availability

Apply this check whenever Registry is selected, regardless of the agent's runtime:

1. Identify the intended Registry deployment Region. Use the user's stated Region; ask if it
   is missing, unknown, `multi`, or `global`. Do not silently choose a Region.
2. Refresh Registry availability via the AWS MCP Server using the procedure above. A Runtime
   availability result cannot verify Registry. Keep the observed source and verification date
   with the result; on failure retain the cached snapshot date and mark availability unconfirmed.
3. If this run confirms availability in the intended Region, proceed. If unavailable, ask the
   user to omit Registry or explicitly choose a supported Region after considering data
   residency. Do not silently move Registry or change the compute runtime.
4. If availability cannot be verified, keep Registry conditional and include an availability
   warning; do not present it as available or ready to deploy. Ask whether to omit Registry or
   leave the recommendation as a draft pending verification. Do not complete Design or
   add-capabilities while a selected Registry's intended Region remains unavailable or unverified.

The main flow records the result in `design.json.volatile_facts.registry_regions` and appends
any warning, with the affected unit and Region, to `warnings` and `region_availability_note`.
The add-capabilities branch records the Region, verification result, and any unresolved warning
in `capabilities-recommendation.md`. Only a lookup observed this run counts as verified.

## Freshness footer template (append to every recommendation doc)

List only facts actually verified this run under their observed channel. Use `none`
for an empty list; omit the public-web sentence when no Temporal units exist.

> _Generated `<DATE>`. Facts verified via AWS MCP Server: `<list or none>`.
> Facts verified via public web (Temporal docs / AWS Marketplace): `<facts with source URLs
> and verification dates, or none>`. Cached values used (not verified this run):
> `<facts with original snapshot dates, or none>`. Limits and pricing change —
> verify against the official sources before committing._

If neither channel verified any facts, say that all facts are cached values. An unavailable
AWS MCP Server does not make successfully web-verified Temporal facts cached.

The footer is a summary, not the only place a date belongs. A cached number quoted in the body —
a service limit, a scaling ceiling, a price anchor — carries its own snapshot date at the point of
use, so a reader who reads one section is not relying on a footer they may never reach.

## Pre-scoring verification contract

Before scoring, inspect every matching runtime hard constraint marked `verification_required`. Do not place verification records in `seed.json` or `answers.json`: those files are reusable workload input and cannot prove that a lookup happened in this run.

After this run observes a verification result, write `$RUN_DIR/current-run-verifications.json` using `scripts/schemas/current-run-verifications.json`:

```json
{
  "artifact_type": "agent-advisor.current-run-verifications",
  "schema_version": 1,
  "run_id": "<the $RUN_DIR directory name>",
  "verifications": {
    "<verification_key>": {
      "status": "verified",
      "source": "https://docs.aws.amazon.com/...",
      "value": "<canonical observed value>"
    }
  }
}
```

The artifact is run-materialized evidence: write it only after this run actually observes the source, and validate it before scoring. `score_units.py` verifies that its `run_id` matches the directory containing `answers.json`; absent or invalid evidence is ignored only by leaving the result provisional, while a mismatched artifact is a hard error. A verified record must use a public AWS documentation URL that exactly matches a constraint's `verification_sources`, and its `value` must exactly match that constraint's `verification_expected_value`. Otherwise omit the verified record or record `not_verified`/`failed`.

One verification key represents exactly one service claim. Do not use CPU/memory evidence to certify GPU support, or a general service page to certify an unobserved limit. A changed observed value is evidence that the static profile needs review, not permission to apply the old elimination.

Cached profile values, a prior run, and unobserved documentation are useful context but are not current-run verification. They cannot hard-eliminate a runtime and cannot support final pricing, availability, quota, or I/O-wait billing claims. The scorer therefore emits deferred verification requirements (including the exact expected value) and a `provisional` recommendation until valid run-materialized evidence is supplied. This procedure is mandatory before any final recommendation or release decision.
