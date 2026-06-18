# Migration Report Template

You MUST use this structure exactly when emitting the final Solr-to-OpenSearch migration report.

## Required sections

```markdown
# Solr → Amazon OpenSearch Migration Assessment

**Generated:** <ISO 8601 timestamp>
**Source:** Apache Solr <version>, <SolrCloud | standalone>, <num collections>
**Target:** Amazon OpenSearch Service in <region>
**Stakeholder:** <Search Relevance Engineer | DevOps / Platform Engineer | Business Stakeholder>

## 1. Executive Summary

- Migration complexity: **Low | Medium | High** (with one-line justification)
- Top 3 items to flag: <bulleted, one line each — frame items with a known remediation as **migration specifics** (the path already handles them); reserve **risk** framing for items with no clean fix, capacity-plan implications, or target-choice constraints>
- Recommended target: <OpenSearch Service | OpenSearch Serverless NextGen> — one-sentence reason

## 2. Schema Mapping

| Solr field | Solr type | OpenSearch field | OpenSearch type | Notes |
|---|---|---|---|---|

You MUST include the full OpenSearch index template (mappings + settings) as a code block.
You MUST call out any `copyField`, `dynamicField`, or analyzer chain that required restructuring.

## 3. Query Translation

For each representative Solr query the user provided:

### Q<n>: <one-line description>
- **Solr:** `<original query>`
- **OpenSearch DSL:**
  ```json
  { ... }
  ```

- **Notes:** translation rules applied; any feature with no direct equivalent flagged here.

## 4. Analyzer & Synonyms

- Custom analyzers ported: `<count>`
- Synonyms: `<file or inline>` — managed via `<synonym graph filter | search-time | index-time>`
- Language stack: `<list>`

## 5. Sizing Recommendation

| Tier | Instance type | Count | Storage | Notes |
|---|---|---|---|---|
| Hot | | | | |
| UltraWarm | | | | (omit if not used) |
| Cold | | | | (omit if not used) |

- Primary shards: `<n>`
- Replicas: `<n>`
- JVM heap: `<GB>` (Amazon OpenSearch Service auto-sets heap based on instance class — record the service-managed value rather than capping manually)
- Index management policy: `<ISM JSON or summary>`

## 6. Feature Gap Register

You MUST use the canonical 8-column shape from [solr-gap-register.md](solr-gap-register.md):

| # | Feature | Solr behavior | OpenSearch alternative | Severity | Lane | Effort | Owner action |
|---|---------|---------------|------------------------|----------|------|--------|--------------|

Required entries: every Solr feature you flagged in steps 3, 4, and 6 of the workflow. Severity + Lane values come from [`compatibility-rubric.md`](../references/compatibility-rubric.md).

## 7. Security Configuration

See [`references/security.md`](../references/security.md) for the canonical recommendations (auth, authorization, transport, encryption at rest, network, audit, throttling, secrets, alarms). You MUST confirm in the report that each control is in place. You MUST NOT duplicate the full text here because divergent copies will drift out of sync with the canonical source.

## 8. Migration Plan

Phase plan describing the migration approach (e.g. assess → provision → PoC → schema + query rebuild → reindex → dual-write → cutover → decommission). Use phasing as a sequencing concept; do NOT include calendar duration, engineer-week effort, or owner-role columns as required outputs. Timeline and resourcing are intentionally excluded from the suite.

| Phase | Goal | Tooling | Exit criterion |
|---|---|---|---|
| Assess | Confirm gaps and finalize target topology | this report | sign-off |
| Provision | Stand up domain + IaC + security + tooling | CloudFormation / Migration Assistant for Amazon OpenSearch Service on EKS | target reachable |
| PoC + spike | Prove the weakest readiness dimension (required if YELLOW) | sample restore | approach confirmed |
| Schema + query rebuild | Review Migration Assistant for Amazon OpenSearch Service mappings; re-implement query layer + relevance | Migration Assistant for Amazon OpenSearch Service metadata + OpenSearch DSL | top-N parity ≥ 95% |
| Reindex | Move data | OpenSearch Migration Assistant for Amazon OpenSearch Service Solr backfill (Historical Data Migration) | parity sample passes |
| Dual-write / delta-close | Validate live traffic on both | application changes | error rate within SLO |
| Cutover | Flip read traffic | client config | rollback rehearsed |
| Decommission | Retire Solr | — | data retained per policy |

**Commitment:** readiness-tier gated — GREEN = committable; YELLOW = after the PoC/spike; RED = spike only.

## 9. Sizing Inputs for AWS Pricing Calculator

- Compute inputs: <instance type, count, region — plug into <https://calculator.aws>>
- Storage inputs: <total GB, storage type (gp3 / OR1 / UltraWarm / Cold)>
- Cost-saving levers: <UltraWarm threshold, ISM rollover, instance right-sizing>

> You MUST plug these values into the [AWS Pricing Calculator](https://calculator.aws) for an authoritative dollar figure that reflects your account's RI / Savings Plan / EDP discounts. This skill MUST NOT estimate dollars because pricing changes monthly and account-specific discount math is unverifiable by an LLM.

## 10. Open Questions

You MUST confirm these items with the user before locking the plan.

## 11. References

You MUST cite every reference file consulted plus any AWS docs fetched live. For the canonical retrieval recipe (tool → URL, with browser/CLI fallbacks), see [`knowledge-retrieval.md`](../references/assessment-knowledge-retrieval.md).

```

## Constraints

- You MUST emit every section above, in order.
- You MUST omit a section's body only if explicitly inapplicable (e.g. no UltraWarm tier). You MUST keep the heading and write "Not applicable: <reason>".
- You MUST save the file as `solr-to-opensearch-migration-report.md` unless the user specifies a different name.
- You MUST NOT invent numbers because fabricated figures mislead sizing and cost decisions. Every cost or sizing figure MUST trace to inputs from the user or to a cited reference.
