# Compatibility rubric

Canonical Severity + Lane vocabulary for the **Feature Gap Register** in
[`report-template.md`](../assets/report-template.md), [`elasticsearch-report-template.md`](../assets/elasticsearch-report-template.md),
[`solr-report-template.md`](../assets/solr-report-template.md), and the §7 split in [`assessment-shape-full-assessment.md`](assessment-shape-full-assessment.md).

Every gap-register row MUST carry both a **Severity** and a **Lane**. The Lane is what determines whether the row is a *risk/blocker* (something that genuinely constrains the migration) or a *migration specific* (something the migration plan already handles via a documented remediation). Severity is the magnitude of the behavioral impact; Lane is the framing for the customer.

## §1. Severity vocabulary (BLOCKING / HIGH / MEDIUM / LOW)

| Severity | Meaning |
|---|---|
| **BLOCKING** | No workaround in OpenSearch; customer must rearchitect, accept feature loss, or stop. |
| **HIGH** | Major behavioral difference or required rewrite — affects code or queries. |
| **MEDIUM** | Configuration / mapping difference handled at migration time. |
| **LOW** | Cosmetic / negligible (terminology rename, metric name change). |

You MUST use this four-tier vocabulary verbatim in every Severity column. You MUST NOT use the legacy *Breaking / Warning / Info* labels — the canonical rubric is BLOCKING / HIGH / MEDIUM / LOW only, and mixed labels confuse downstream consumers.

## §2. Lane vocabulary (`migration-specific` / `risk-blocker`)

| Lane | When to use |
|---|---|
| **migration-specific** | The item has a well-trodden, prescribed remediation that the migration plan *already includes*: a transformer flag, a config rewrite, an SDK/plugin substitution, a metadata-migration sanitizer, or a one-line behavior toggle. Frame these to the customer as *"this is how the migration handles X"* — not as a hazard. Most MEDIUM items, and HIGH items where the documented Migration Assistant for Amazon OpenSearch Service transformer (or equivalent) handles the conversion automatically, route here. |
| **risk-blocker** | The item genuinely constrains the migration: no known fix, capacity-plan implications, irreversible target choices, customer-action dependencies that can fail late, or "no equivalent on Serverless". BLOCKING is *almost always* this lane. HIGH items without a documented remediation also live here. |

Routing rule: if the migration plan already includes the fix and applies it on the customer's behalf (transformer, sanitizer, default override), the row is `migration-specific`. If the customer must make a decision, accept feature loss, or rearchitect to land it, the row is `risk-blocker`.

## §3. Combining Severity + Lane

| Severity \ Lane | migration-specific | risk-blocker |
|---|---|---|
| **BLOCKING** | (rare — only when an automatic remediation exists for an otherwise-blocking item) | **typical** — most BLOCKING items |
| **HIGH** | typical when transformer-handled | typical when manual rewrite |
| **MEDIUM** | **typical** | uncommon |
| **LOW** | typical | uncommon |

Examples grounded in the always-flag list at [`assessment-workflow.md` §3](assessment-workflow.md#step-3--compatibility-scan--gap-register):

| Feature | Severity | Lane | Why |
|---|---|---|---|
| `q.op=AND` | HIGH | `migration-specific` | One-line `default_operator: AND` rewrite; documented; transformer applies it. |
| `fielddata: true` on text | BLOCKING | `migration-specific` | OOM risk if untouched, but Migration Assistant for Amazon OpenSearch Service's metadata transformer strips it automatically and adds the `.keyword` subfield. |
| Snapshot from ES ≥ 7.11 | BLOCKING | `risk-blocker` | License lockout — no snapshot path exists; customer must change tools (Migration Assistant Historical Data Migration / `_reindex`). |
| `_type` placeholder (ES 7) | HIGH | `migration-specific` | Migration Assistant metadata transformer flattens automatically. |
| Custom Java JARs in `<lib>` | HIGH | `risk-blocker` | Manual port to OS plugin API; not supported on Serverless NextGen — constrains target choice. |
| NMSLIB engine on OS source crossing to OS 3.x | HIGH | `risk-blocker` | Engine removed; reindex into FAISS required before crossing 3.x. |
| `<copyField>` | LOW | `migration-specific` | One-line `copy_to` mapping change; trivial. |
| Cross-Cluster Search (CCS) | HIGH | `risk-blocker` | Not supported on Serverless; partial on Managed — constrains target. |

## §4. Plugin rename cheat-sheet

The Open Distro → OpenSearch plugin rename is mostly mechanical but is cited often enough to warrant a single canonical lookup.

| Open Distro plugin | OpenSearch plugin | Notes |
|---|---|---|
| `opendistro-anomaly-detection` | `opensearch-anomaly-detection` | Drop-in. |
| `opendistro-alerting` | `opensearch-alerting` | API contract preserved; Watcher rewrite is a separate task. |
| `opendistro-asynchronous-search` | `opensearch-asynchronous-search` | Drop-in. |
| `opendistro-index-management` | `opensearch-index-management` | ISM policies; ILM JSON does NOT import. |
| `opendistro-job-scheduler` | `opensearch-job-scheduler` | Drop-in. |
| `opendistro-knn` | `opensearch-knn` | Engine selection rules in [`vector-knn.md`](vector-knn.md). |
| `opendistro-observability` | `opensearch-observability` | Drop-in. |
| `opendistro-performance-analyzer` | `opensearch-performance-analyzer` | Drop-in. |
| `opendistro-reports-scheduler` | `opensearch-reports-scheduler` | Drop-in. |
| `opendistro-security` | `opensearch-security` | Config schema preserved; backend wiring may differ on Managed. |
| `opendistro-security-advanced-modules` | `opensearch-security` | Folded into `opensearch-security`. |
| `opendistro-sql` | `opensearch-sql` | Drop-in; verify edge cases. |

The supported-plugin list on managed AOS is `[verify]` against [supported-plugins.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/aos-supported-plugins.html) — the plugin catalog drifts.
