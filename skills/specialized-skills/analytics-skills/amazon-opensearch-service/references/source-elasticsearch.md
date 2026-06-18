# Elasticsearch Source Reference

Stable-core facts about Elasticsearch as a migration source to Amazon OpenSearch Service.
Version-volatile details (exact OpenSearch minor that reaches parity, current MA version support floor/ceiling)
MUST be tagged `[verify]` and resolved against live docs in Step 8 of the workflow.

---

## ES version-family table

Use this to populate §1 "Recommended path" and §8 "Migration Plan" in the report.

| ES version family | Fork status | Snapshot/Restore into AOS | Primary HDM strategy | Notes |
|---|---|---|---|---|
| ES 1.x / 2.x / 5.x | Pre-fork | NOT recommended (multi-major hop) | Migration Assistant Historical Data Migration | MA HDM supports source ES back to 1.0; multi-major hops require MA |
| ES 6.x | Pre-fork | Supported (pre-fork) | Snapshot/Restore OR MA HDM | Snapshot/Restore is the simpler path; MA HDM preferred for large/complex |
| ES ≤ 7.10.2 | Pre-fork | Supported | Snapshot/Restore (maintenance window) OR MA HDM | Snapshot/Restore is the simplest path while license boundary allows |
| ES ≥ 7.11 (7.11–7.17, 8.x) | Post-fork ELv2/SSPL | **BLOCKED** (license lockout) | MA HDM (large/complex) or `_reindex` from remote (small, ≥30 min window) | Snapshot/Restore is architecturally blocked post-fork |

> Source/target version eligibility for each MA mode: see [Migration Assistant source-and-target versions](https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/source-and-target-versions.html) `[verify]`.

---

## ES → OpenSearch always-flag table

Every row below MUST be evaluated for every ES source migration. Copy confirmed findings into the
gap register ([elasticsearch-gap-register.md](../assets/elasticsearch-gap-register.md)). Severity + Lane vocabulary
from [compatibility-rubric.md](compatibility-rubric.md).

| Feature | Elasticsearch behavior | OpenSearch alternative | Severity | Lane | Notes |
|---|---|---|---|---|---|
| Index Lifecycle Management (`_ilm/policy`) | ILM policy JSON | **ISM** (`_plugins/_ism/policies`) — policy JSON does NOT import | HIGH | risk-blocker | Rebuild each ILM policy as ISM; common patterns: rollover, force_merge, warm/cold, delete |
| X-Pack Watcher | Rule-based alerting | OpenSearch **Alerting** monitors + destinations | HIGH | risk-blocker | Rebuild monitors; smoke-test trigger conditions |
| Runtime fields (schema-on-read) | `runtime` mapping type | No equivalent | HIGH | risk-blocker | Pre-compute via ingest pipeline or scripted_field; reindex |
| Fleet / Elastic Agent | X-Pack ingest + endpoint management | No equivalent on AOS | BLOCKING | risk-blocker | Re-architect ingest on Data Prepper / OSI / Fluent Bit / OTel Collector |
| ELSER `text_expansion` | Elastic learned sparse retrieval (proprietary) | `neural_sparse` query + SageMaker-hosted sparse encoder | HIGH | risk-blocker | ELSER does not run on AOS; use neural_sparse or hybrid BM25+dense |
| `dense_vector` field | Dense vector + kNN | `knn_vector` (engine selection: see [vector-knn.md](vector-knn.md)) | MEDIUM | migration-specific | Pick engine (FAISS/Lucene/NMSLIB); reindex; validate recall |
| `_type` / multi-type mappings | ES 6.x multi-type or 7.x `_doc` placeholder | Types removed in OS 1.0; `_doc` placeholder OKs in 7.x but blows up `_reindex` | MEDIUM | migration-specific | MA metadata transformer flattens templates automatically |
| `fielddata: true` on text (ES 1.x/2.x) | In-memory fielddata for sort/agg | `.keyword` subfield + `doc_values` | BLOCKING | migration-specific | OOM risk on first aggregation; MA transformer strips fielddata and adds `.keyword` automatically |
| `_source: {enabled: false}` | `_source` not stored | Forces MA Historical Data Migration only — Snapshot/Restore cannot reconstruct | HIGH | risk-blocker | Use MA HDM; re-enable `_source` on target index |
| ES 8 `retriever` / `rrf` | Native reciprocal-rank fusion | Hybrid query + normalization-processor pipeline | HIGH | risk-blocker | Rebuild as hybrid search pipeline; benchmark ranking parity |
| Snapshot from ES ≥ 7.11 | Snapshot archive | **BLOCKED** — ELv2/SSPL license lockout into AOS | BLOCKING | risk-blocker | Use MA HDM or `_reindex` from remote |
| Open Distro plugin names (`opendistro-*`) | `opendistro-*` plugin namespace | `opensearch-*` rename | LOW | migration-specific | Plugin namespace rename is mechanical; validate config files |

---

## ES field/mapping → OpenSearch table

Use as the audit checklist for §2 Schema/Mapping in the report and for [elasticsearch-index-template-skeleton.md](../assets/elasticsearch-index-template-skeleton.md).

| ES construct | OpenSearch equivalent | Action |
|---|---|---|
| `type: text` with `fielddata: true` | `type: text` + `.keyword` subfield | Strip fielddata; add keyword subfield |
| `type: flattened` | `type: flat_object` | Rename type |
| `type: dense_vector` | `type: knn_vector` | Change type + add engine/method parameters |
| `type: runtime` (runtime fields) | No equivalent | Pre-compute via ingest pipeline |
| Multi-type index (`_type`) | Single-type; `_type` removed | MA metadata transformer flattens automatically |
| `_source: {enabled: false}` | Supported but blocks Snapshot/Restore | Re-enable on target or use MA HDM |
| `index_patterns` (index template) | `index_patterns` (identical) | No change |
| `_ilm` lifecycle hooks in index settings | ISM policy attachment | Rewrite ILM → ISM; re-attach |

---

## ES API → OpenSearch API cheat-sheet

| ES API | OpenSearch API | Notes |
|---|---|---|
| `GET /_ilm/policy` | `GET /_plugins/_ism/policies` | JSON format differs; rebuild required |
| `GET /_watcher/watch` | `GET /_plugins/_alerting/monitors` | Rebuild required |
| `GET /_xpack` | Not applicable | No X-Pack on AOS |
| `GET /_eql/search` | `GET /_plugins/ppl` | Use PPL for log analytics; EQL not available |
| `GET /_async_search` | `GET /_plugins/_asynchronous_search` | Semantics match; endpoint differs |
| `GET /_text_expansion` (ELSER) | `GET /_plugins/ml` (neural_sparse) | Model hosting required on AOS side |

---

## Always-true rules for ES sources

- **Post-fork snapshot lockout is architectural** — do NOT recommend Snapshot/Restore for ES ≥ 7.11 under any circumstance.
- **MA HDM vs `_reindex` threshold** — prefer `_reindex` from remote for post-fork ES when dataset is small and a ≥30 min maintenance window is available. MA HDM becomes primary for large/complex datasets or when source→target network reachability is not possible.
- **ILM → ISM is always a risk-blocker** — there is no automated ILM import tool; every policy must be rebuilt.
- **ELSER is proprietary** — do not promise ELSER functionality on AOS.
- **`fielddata: true` OOM risk** — flag on every ES 1.x/2.x source even if MA handles it automatically.
