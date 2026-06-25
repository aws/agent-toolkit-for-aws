# Elasticsearch Gap Register Skeleton

Use this table verbatim in section **6. Feature Gap Register** of [report-template](report-template.md) (or the ES rendering in [elasticsearch-report-template](elasticsearch-report-template.md)) for Elasticsearch **and** OpenSearch-upgrade sources. Add one row per finding surfaced by Steps 3, 4, and 6 of the workflow. Severity + Lane vocabulary comes from the canonical rubric in [compatibility-rubric](../references/compatibility-rubric.md).

Draft the rows directly from the embedded *ES → OpenSearch always-flag table* in [source-elasticsearch.md](../references/source-elasticsearch.md) (stable-core, no retrieval). Tag only the version-volatile "which OpenSearch minor reaches parity" detail `[verify]` and resolve it in the Step 8 batch.

| # | Feature | Elasticsearch behavior | OpenSearch alternative | Severity | Lane | Effort | Owner action |
|---|---------|------------------------|------------------------|----------|------|--------|--------------|
| 1 | *e.g. ILM* | Index Lifecycle Management policies (`_ilm/policy`) | **ISM** (`_plugins/_ism/policies`) — policy JSON does NOT import | HIGH | risk-blocker | M | Rewrite policies as ISM; re-attach to indexes per [source-elasticsearch](../references/source-elasticsearch.md). |
| 2 | *e.g. Watcher* | X-Pack Watcher rules | OpenSearch **Alerting** monitors | HIGH | risk-blocker | M | Rebuild monitors + destinations; smoke-test triggers. |
| 3 | *e.g. Runtime fields* | Schema-on-read `runtime` mappings | No equivalent | HIGH | risk-blocker | M | Pre-compute via ingest pipeline or `scripted_field`; reindex. |
| 4 | *e.g. Fleet / Elastic Agent* | X-Pack ingest + endpoint management | No equivalent | BLOCKING | risk-blocker | L | Re-architect ingest on Data Prepper / OSI / Fluent Bit / OTel. |
| 5 | *e.g. ELSER `text_expansion`* | Elastic learned sparse retrieval | `neural_sparse` query | HIGH | risk-blocker | L | Re-host a sparse model; rewrite queries; validate relevance. |
| 6 | *e.g. `dense_vector`* | Dense vector field + kNN | `knn_vector` (engine per `references/vector-knn.md`) | MEDIUM | migration-specific | M | Pick engine; reindex; verify recall vs source. |
| 7 | *e.g. `_type` / multi-type mappings* | ES 6.x multi-type or 7.x `_doc` placeholder | Types removed in OS 1.0 | MEDIUM | migration-specific | S | Migration Assistant metadata transformer flattens templates (nugget #9) automatically. |
| 8 | *e.g. `fielddata: true` (ES 1.x/2.x text)* | In-memory fielddata for sort/agg | `.keyword` subfield + `doc_values` | BLOCKING | migration-specific | S | Migration Assistant metadata transformer strips `fielddata` and adds the `.keyword` subfield (nugget #8) automatically. |
| 9 | *e.g. `_source: {enabled:false}`* | `_source` not stored on the index | Forces **Migration Assistant for Amazon OpenSearch Service Historical Data Migration only** | HIGH | risk-blocker | S | Use Migration Assistant for Amazon OpenSearch Service Historical Data Migration (nugget #22); re-enable `_source` on target. |
| 10 | *e.g. ES 8 `retriever` / `rrf`* | Native reciprocal-rank fusion | Hybrid query + normalization-processor | HIGH | risk-blocker | M | Rebuild as hybrid search pipeline; benchmark ranking. |

## Severity + Lane vocabulary

Severity values MUST come from the canonical rubric in [compatibility-rubric.md](../references/compatibility-rubric.md) §1 — BLOCKING / HIGH / MEDIUM / LOW only. Lane values MUST come from §2 of the same file — `migration-specific` (the migration plan already includes the remediation) or `risk-blocker` (the customer must act). Only `risk-blocker` rows deduct from the Compatibility readiness weight.

## Effort tiers

- **S** — small; isolated change, mechanical translation or config update.
- **M** — medium; touches multiple components or requires re-indexing.
- **L** — large; usually requires design review, custom code, or behavior validation.

(Effort is intentionally abstract — the suite excludes calendar/engineer-week estimates.)

## Constraints

- You MUST keep the column order exactly as shown because downstream tooling parses the table by column position. (Same locked shape as [solr-gap-register.md](solr-gap-register.md) — only the "behavior" column label changes from Solr to Elasticsearch.)
- You MUST NOT remove a row to "simplify" the report because every flagged finding belongs in the register, even LOW-level, and removed rows hide findings.
- You MUST use the BLOCKING / HIGH / MEDIUM / LOW vocabulary in the Severity column. You MUST NOT use the legacy Breaking / Warning / Info labels.
- You MUST use the `migration-specific` / `risk-blocker` vocabulary in the Lane column. The Lane is what the FULL_ASSESSMENT §7 split routes by, and what the readiness scoring uses to decide if a row deducts from Compatibility (only `risk-blocker` rows deduct).
- You MUST link every row's "OpenSearch alternative" cell to the relevant reference file when one exists.
- For OpenSearch-upgrade sources, draw the rows from [source-opensearch.md](../references/source-opensearch.md) breaking-changes (e.g. JDK 21 minimum, NMSLIB deprecation, removed k-NN index settings, WLM rename) instead of the X-Pack rows.
