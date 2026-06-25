# Elasticsearch / OpenSearch Migration Report Template

You MUST use this structure exactly when emitting the final Elasticsearch-to-OpenSearch (or OpenSearch-upgrade) migration report. It mirrors [solr-report-template.md](solr-report-template.md) section-for-section so both source families produce the same detailed shape — only the source-specific columns differ. Draft every section from the embedded tables in [source-elasticsearch.md](../references/source-elasticsearch.md) / [source-opensearch.md](../references/source-opensearch.md); tag version-volatile values `[verify]` and resolve them in the Step 8 batch.

## Required sections

```markdown
# Elasticsearch → Amazon OpenSearch Migration Assessment

**Generated:** <ISO 8601 timestamp>
**Source:** Elasticsearch <version>, <distribution: Elastic | OSS>, <license: ELv2/SSPL flag>, <node count> nodes, <index count> indexes
**Target:** Amazon OpenSearch Service in <region>
**Stakeholder:** <Search Relevance Engineer | DevOps / Platform Engineer | Business Stakeholder>

## 1. Executive Summary

- Migration complexity: **Low | Medium | High** (with one-line justification)
- Top 3 items to flag: <bulleted, one line each — frame items with a known remediation as **migration specifics** (the path already handles them); reserve **risk** framing for items with no clean fix, capacity-plan implications, or target-choice constraints>
- Recommended target: <OpenSearch Service | OpenSearch Serverless NextGen> — one-sentence reason
- Recommended path: <from the ES version-family table in source-elasticsearch.md>

## 2. Schema / Mapping

| ES field | ES type | OpenSearch field | OpenSearch type | Notes |
|---|---|---|---|---|

You MUST include the full OpenSearch index template (mappings + settings) as a code block — use [elasticsearch-index-template-skeleton.md](elasticsearch-index-template-skeleton.md).
You MUST call out any `_type`/multi-type flattening, `fielddata:true` strip, `dense_vector`→`knn_vector`, `flattened`→`flat_object`, runtime-field pre-compute, or `_source:false` index that required action.

## 3. Query / API Translation

For each representative query or API call the user provided (or a representative set you inferred):

### Q<n>: <one-line description>
- **Elasticsearch:** `<original query / API>`
- **OpenSearch:**
  ```json
  { ... }
  ```

- **Notes:** ES Query DSL is largely identical in OpenSearch; flag the deltas — `retriever`/`rrf` → hybrid query + normalization-processor, ELSER `text_expansion` → `neural_sparse`, scripted/runtime fields, `_type` in endpoints, X-Pack-only query clauses.

## 4. Plugins, Auth & Operations

- Plugins: map `_cat/plugins` output (Open Distro `opendistro-*` → `opensearch-*` rename cheat-sheet in [compatibility-rubric.md](../references/compatibility-rubric.md) §4). Supported-plugin list on managed AOS is `[verify]`.
- ILM → ISM (rewrite policies — HIGH); Watcher → Alerting (rebuild monitors — HIGH).
- Auth backends (basic / SAML / OIDC / Kerberos / LDAP / IAM-SigV4 / mTLS): map roles + role-mappings to OpenSearch Security.

## 5. Sizing Recommendation

| Tier | Instance type | Count | Storage | Notes |
|---|---|---|---|---|
| Hot | | | | |
| UltraWarm | | | | (omit if not used) |
| Cold | | | | (omit if not used) |

- Primary shards: `<n>` (from the shard-sizing formula in [sizing.md](../references/sizing.md))
- Replicas: `<n>`
- JVM heap: Amazon OpenSearch Service auto-sets heap by instance class — record the service-managed value; `[verify]` the per-instance recommendation
- Index management policy: `<ISM JSON or summary>`

## 6. Feature Gap Register

You MUST use the canonical 8-column shape from [elasticsearch-gap-register.md](elasticsearch-gap-register.md):

| # | Feature | Elasticsearch behavior | OpenSearch alternative | Severity | Lane | Effort | Owner action |
|---|---------|------------------------|------------------------|----------|------|--------|--------------|

Required entries: every ES feature you flagged in steps 3, 4, and 6. Severity values come from [compatibility-rubric.md](../references/compatibility-rubric.md).

## 7. Security Configuration

See [`references/security.md`](../references/security.md) for the canonical recommendations (FGAC, encryption, VPC patterns, audit logs, compliance posture). You MUST confirm in the report that each control is in place. You MUST NOT duplicate the full text here.

## 8. Migration Plan

Use phasing as a sequencing concept (assess → provision → PoC → schema/query rebuild → reindex → dual-write → cutover → decommission); do NOT include calendar duration, engineer-week effort, or owner-role columns as required outputs. Timeline and resourcing are intentionally excluded from the suite.

| Phase | Goal | Tooling | Exit criterion |
|---|---|---|---|
| Assess | Confirm gaps and finalize target topology | this report | sign-off |
| Provision | Stand up domain + IaC + security + tooling | CloudFormation / Migration Assistant for Amazon OpenSearch Service on EKS | target reachable |
| PoC + spike | Prove the weakest readiness dimension (required if YELLOW) | sample restore | approach confirmed |
| Schema + query rebuild | Audit Migration Assistant for Amazon OpenSearch Service mappings; rebuild ILM→ISM / Watcher→Alerting / runtime fields | Migration Assistant for Amazon OpenSearch Service metadata + OpenSearch DSL | top-N parity ≥ 95% |
| Reindex | Move data | <Snapshot/Restore if ES ≤ 7.10.2; else Migration Assistant for Amazon OpenSearch Service Historical Data Migration; OpenSearch source: in-place blue/green or snapshot> | parity sample passes |
| Dual-write / Replay | Validate live traffic on both | <Migration Assistant for Amazon OpenSearch Service Live Traffic Migration for zero-downtime; else dual-write> | error rate within SLO |
| Cutover | Flip read traffic | client config | rollback rehearsed |
| Decommission | Retire source | — | data retained per policy |

**Commitment:** readiness-tier gated — GREEN = committable; YELLOW = after the PoC/spike; RED = spike duration only.

## 9. Sizing Inputs for AWS Pricing Calculator

- Compute inputs: <instance type, count, region — plug into <https://calculator.aws>>
- Storage inputs: <total GB, storage type (gp3 / OR1 / UltraWarm / Cold)>
- Cost-saving levers: <UltraWarm threshold, ISM rollover, instance right-sizing, RI/Serverless NextGen>

> You MUST plug these values into the [AWS Pricing Calculator](https://calculator.aws) for an authoritative dollar figure that reflects your account's RI / Savings Plan / EDP discounts. This skill MUST NOT estimate dollars because pricing changes monthly and account-specific discount math is unverifiable by an LLM.

## 10. Open Questions

You MUST confirm these items with the user before locking the plan.

## 11. References / Citations

The single canonical provenance record. List every `[verify]`-resolved claim's source URL with a retrieval timestamp, plus the reference files consulted for stable-core facts. For the retrieval recipe see [`knowledge-retrieval.md`](../references/assessment-knowledge-retrieval.md).

```

## Constraints

- You MUST emit every section above, in order.
- You MUST omit a section's body only if explicitly inapplicable (e.g. no UltraWarm tier). You MUST keep the heading and write "Not applicable: <reason>".
- You MUST save the file as `elasticsearch-to-opensearch-migration-report.md` (or `opensearch-upgrade-migration-report.md` for OS sources) unless the user specifies a different name.
- You MUST NOT invent numbers because fabricated figures mislead sizing and cost decisions. Every cost or sizing figure MUST trace to inputs from the user or to a cited reference.
- For OpenSearch-upgrade sources, retitle to "OpenSearch <from> → <to> Upgrade Assessment", drive section 2/3 from [source-opensearch.md](../references/source-opensearch.md) breaking-changes, and make section 8 the in-place blue/green sequence (stepping-stone via OS 2.19 for 1.x→3.x).
