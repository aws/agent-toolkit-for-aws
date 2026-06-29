# Migration capability — assessment workflow

This file is the **entry point** for the `migration` capability. It owns the workflow for producing a migration assessment from Apache Solr (6.x–9.x), Elasticsearch (1.x–8.x), or self-managed OpenSearch (in-place upgrades 1.3 → 2.19 → 3.x) to Amazon OpenSearch Service or Serverless. It also indexes the rest of the migration capability content.

## When to use this capability

`SKILL.md` routes here when the user is **migrating** to AOS / AOSS. Concrete triggers:

- Phrases: *"migrate from X"*, *"move off Solr"*, *"ES → OpenSearch"*, *"Migration Assistant for Amazon OpenSearch Service"*, *"Historical Data Migration"*, *"Live Traffic Migration"*, *"Capture and Replay"*, *"refactor my schema.xml"*, *"should I migrate?"*, *"what's the path?"*, *"high-level overview"*
- Pasted artifacts: `schema.xml`, `solrconfig.xml`, `_cat/indices`, `_cluster/health`, `_nodes/stats`, version strings (*"ES 7.10"*, *"OS 1.3"*, *"Solr 8.11"*), vendor names (*"Elastic Cloud"*, *"Amazon OpenSearch"*)
- Stakeholder intake: *"what do you need from me"*, *"before we go deeper"*, *"starting to look at migrating"*

## All migration files (capability index)

After loading this entry, you can discover every migration-capability file from this list. There are NO other migration files outside `references/assessment-*.md`.

| File | Purpose |
|---|---|
| `assessment-workflow.md` (this file) | Workflow + intake + compatibility scan + path selection + sizing handoff + readiness |
| `assessment-gotchas.md` | Production gotcha catalog. Each entry carries a `Category:` tag (TRUE_BLOCKER / MIGRATION_SPECIFIC / OPERATIONAL_CONSIDERATION / COST_TCO / CLARIFICATION) that determines whether it surfaces under Migration specifics or Risks/blockers. Cite by number (`#1`–`#N`). |
| `assessment-knowledge-retrieval.md` | Topic → tool → URL recipe for batched verification |
| `assessment-shape-full-assessment.md` | Shape recipe: 9-section FULL_ASSESSMENT |
| `assessment-shape-overview.md` | Shape recipe: OVERVIEW_REQUEST (3–4 phases + 1 URL + next step) |
| `assessment-shape-focused-operational.md` | Shape recipe: FOCUSED_OPERATIONAL runbook |
| `assessment-shape-translation.md` | Shape recipe: drop-in DSL translation |
| `assessment-shape-schema-conversion.md` | Shape recipe: field-by-field mapping |
| `assessment-shape-sizing-only.md` | Shape recipe: instance class + count + storage |
| `assessment-shape-comparative-decision.md` | Shape recipe: pick + comparison table + decision driver |
| `assessment-shape-anti-pattern-pushback.md` | Shape recipe: refusal + right-tool recommendation |

Cross-cutting refs you may also load: `sizing.md`, `vector-knn.md`, `observability.md`, `security.md`, `personas.md`, `assessment-gotchas.md`.

## Step 0a: detect the response shape

Once in this capability, classify the prompt into ONE of the 8 shapes. State the detected shape in your first sentence (e.g., *"Detected shape: FULL_ASSESSMENT — Solr 8.11 with `schema.xml` paste."*).

| Shape | Detect from | Output expectations |
|---|---|---|
| **FULL_ASSESSMENT** | Rich prompt with workload context, cluster sizing, asks for migration plan / "produce an assessment" / pasted `schema.xml` + `_cat/indices` + traffic numbers | 9 sections (Executive Summary / Source / Target / Migration Path / Sizing / Readiness / Risks / **Next Steps** / Citations) |
| **OVERVIEW_REQUEST** | "What's the path?" / "high-level overview" / "walk me through it" / business-stakeholder framing without artifacts | 3–4 named phases + 1 inline URL + clear next step. NOT a 6-question intake. |
| **FOCUSED_OPERATIONAL** | "Cheapest path", "<100 GB", "quickest way", "smallest reindex window", a specific operational ask | Concrete runbook with `reindex.remote.allowlist` or equivalent; no full report scaffold |
| **TRANSLATION_TASK** | "Translate this Solr query" / "convert this DSL" / "what's the OpenSearch equivalent of X" | Drop-in JSON / code with caveats inline |
| **SCHEMA_CONVERSION** | User pasted `schema.xml`, ES mapping, or asks "map these fields" | Field-by-field mapping, gap register, brief migration path callout |
| **SIZING_ONLY** | "What instance class?" / "size this cluster" / a workload spec but no migration | Instance + count + storage formula derivation |
| **COMPARATIVE_DECISION** | "Managed vs Serverless?" / "should we A or B?" / "FAISS or Lucene?" / **"how do you reconcile these constraints?"** / **prompt names ≥3 simultaneous hard constraints** (e.g., zero-downtime + zero-data-loss + no-third-party-tooling + EU residency) | Pick-one + comparison table + decision driver. **Constraint-trilemma sub-shape** when ≥3 constraints are named — see § 2.5 of the recipe. |
| **ANTI_PATTERN_PUSHBACK** | Wrong-fit migration (e.g. Postgres + transactional + small dataset; ID-only lookups; sub-GB exact-match workload framed as a search migration) | REFUSE to size; recommend right tool; list future-fit triggers that would make OpenSearch correct later |

After choosing a shape, load `references/assessment-shape-<shape>.md` for the recipe.

## Always-true migration facts

These facts are stable-core for the AWS OpenSearch / Migration Assistant for Amazon OpenSearch Service ecosystem and do not need per-claim verification.

**ES → OpenSearch fork rules:**

- ES ≤ 7.10.2 (pre-fork): Snapshot/Restore directly into Amazon OpenSearch is supported.
- ES ≥ 7.11 (post-fork ELv2/SSPL — includes 7.11–7.17 and all 8.x): Snapshot/Restore is **NOT** supported into Amazon OpenSearch. Use Migration Assistant for Amazon OpenSearch Service Historical Data Migration, or `_reindex` from remote for small datasets.
- ES 1.x / 2.x / 5.x / 6.x: Migration Assistant for Amazon OpenSearch Service Historical Data Migration is the **primary** path (multi-major hop required). Historical Data Migration supports source ES versions all the way back to 1.0.

**Solr → OpenSearch is a refactor, not a lift-and-shift:**

- Schema, queries, configs all need translation. Document-level migration only — there is NO segment/snapshot path between Solr and OpenSearch.
- Migration Assistant for Amazon OpenSearch Service **does** support Solr backfill (and Live Traffic Migration). Do NOT tell a customer the service is Elasticsearch-only. For target restrictions and source/target eligibility, see § "Source / target rules" below.
- Solr `<uniqueKey>` → bind to `_id` on `_bulk`/`index` AND map as `keyword`.
- Solr `<copyField source="A" dest="B"/>` → `"copy_to": "B"` in OpenSearch mapping.
- Solr `mm` syntax passes UNCHANGED as `minimum_should_match`.
- eDisMax `qf field^boost` → `multi_match` `type: best_fields` with the same boosts.
- Solr `q.op=AND` → set `default_operator: AND` on `query_string` (OpenSearch defaults to OR — top cause of result divergence).

**OpenSearch in-place upgrade rules:**

- The mechanism is called **blue/green upgrade** (`aws opensearch start-domain-upgrade --target-version OpenSearch_<x.y>`). Name it explicitly when recommending an in-place upgrade — do not hand-wave with "upgrade in place" or describe it as "a long minor-version chain." AOS spins up a green cluster at the target version, syncs, and cuts over.
- AOS supports **multi-version jumps** within 2.x and within 3.x via blue/green — you do NOT need to step every minor version (e.g., 2.5 → 2.7 → 2.9 → 2.11 → 2.19 is wrong; 2.5 → 2.19 in one blue/green is correct). The only mandatory waypoint is **2.19 when crossing into 3.x**. Source < 1.3 needs a 1.x → 1.3 hop first because only 1.3 can upgrade to 2.x.
- The 1.3 → 2.19 → 3.x mandatory waypoints are about the engine version, not Lucene segments. Pre-2.x indexes carry Lucene 8 segments; OS 3.x runs Lucene 10. Lucene's segment format is forward-only — Lucene 10 cannot read Lucene 8, so any pre-2.0 index destined for 3.x MUST be reindexed (typically on a 2.x intermediate) before the 3.x hop.
- In-place blue/green upgrades are free for managed customers.

**Source / target rules:**

- The Solr-target restriction is **architectural**: Migration Assistant for Amazon OpenSearch Service Solr migrations (both Historical Data Migration backfill and Live Traffic Migration live cutover) target **OpenSearch 3.x or Amazon OpenSearch Serverless ONLY** — never OS 1.x/2.x. The legacy "Solr is RFS-only / not supported by Capture & Replay" wording is OUTDATED.
- Migration Assistant for Amazon OpenSearch Service **3.0** deploys to Amazon EKS (Kubernetes). Earlier versions used ECS — plan EKS prereqs.

> **Source / target version support is canonical at the AWS docs page** — do NOT replicate version cells in this skill. Cite **<https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/source-and-target-versions.html>** when version-range questions come up. ES 8.x is supported by both Historical Data Migration and Live Traffic Migration (confirmed); the documented page is the source of truth for the current floor and ceiling on each mode.

## Components of a migration

Every migration to Amazon OpenSearch Service decomposes into up to **three independent components**. Pick which apply for *this* customer; not all migrations need all three.

| Component | What it covers | When you need it |
|---|---|---|
| **1. Historical Data Migration** | Move the existing data corpus (documents, indexes, mappings) from source to target. | Almost always — unless the customer is starting greenfield with no historical data. |
| **2. Live Traffic Migration** | Replicate live writes during cutover so the target stays in sync until you flip readers/writers. | Only when the maintenance window the customer can grant is shorter than the time Historical Data Migration takes for this dataset. Skip when the window comfortably covers HDM duration, or for batch / read-heavy workloads. |
| **3. Application Code Rewrite** | Update the application's client code, query DSL, schema, configs, and language-specific bindings to match OpenSearch idioms. | Required for **Solr → OpenSearch** (different APIs entirely) and for **major-version rewrites** (Lucene segment wall, X-Pack feature port, etc.). Skipped on like-for-like ES → AOS where the wire-protocol overlap is sufficient. |

Strategy selection happens *per component* — see the three sections below.

### 1. Historical Data Migration — strategies

Source/target version eligibility for each tool: **<https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/source-and-target-versions.html>** (canonical; do not replicate version cells in this skill).

| Tool | What it does | Notes |
|---|---|---|
| **Migration Assistant for Amazon OpenSearch Service Historical Data Migration** | Managed backfill / historical-data migration into AOS or AOSS. | Solr → OS 1.x/2.x is NOT supported (target must be OS 3.x or Serverless). |
| **Snapshot/Restore (direct)** | One-shot snapshot from a self-managed source restored on AOS. | BLOCKED for ES ≥ 7.11 (post-fork license). |
| **`_reindex` from remote** | Native OpenSearch API; reindexes from a remote cluster. | **PRIMARY for <100 GB ES ≥ 7.11 with ≥30 min cutover window.** |
| **OSI (OpenSearch Ingestion)** | Managed Data Prepper pipelines (good when paired with Application Code Rewrite that emits to OSI). | NOT for Solr sources. |
| **In-place blue/green upgrade** | AWS-managed engine version step (use for OS-self-managed → AOS-managed at the same engine version). | Free for managed customers. |

**Primary-tool selection rules:**

- ES ≥ 7.11 sources **<100 GB** with a **≥30-minute** maintenance window → **`_reindex` from remote**.
- ES ≥ 7.11 sources **>500 GB**, multi-index complex, or unreachable from target → **Migration Assistant for Amazon OpenSearch Service Historical Data Migration**.
- ES ≤ 7.10.2 (pre-fork) with a maintenance window → **Snapshot/Restore**.
- Solr (any version) → **Migration Assistant for Amazon OpenSearch Service Historical Data Migration** (Solr is document-level only; no segment path; target must be OS 3.x or Serverless).
- OS 1.3+ → OS 2.19/3.x at the same self-managed → AOS-managed boundary → **in-place blue/green**.

### 2. Live Traffic Migration — strategies

| Tool | What it does | Notes |
|---|---|---|
| **Migration Assistant for Amazon OpenSearch Service Live Traffic Migration** | Captures source writes (Capture Proxy in front of source) and replays them onto the target until clocks sync. Pair with Historical Data Migration for full historical + live. | Same Solr-target restriction (OS 3.x / Serverless only). |
| **Application-layer dual-write** | Customer's application code writes to both source and target during cutover. NOT a third-party tool — it's customer code under customer change control. | Useful when the customer rejects "third-party tooling" but still needs zero downtime. |
| **Read-only window** | Pause writes for the duration of Historical Data Migration; cut over once HDM completes. The read-only window IS however long HDM takes for this dataset (gated by source size, network bandwidth, ingest worker count). | Cheapest. Default whenever the maintenance window comfortably covers the estimated HDM duration. |

**Skip Live Traffic Migration entirely when:** the customer's maintenance window covers the time Historical Data Migration takes for this dataset, OR the workload is batch / read-heavy with no live-write SLA. Estimate HDM duration up-front (cluster size, bandwidth, parallelism) and validate it fits the budget before committing to skip Live Traffic Migration.

### 3. Application Code Rewrite — strategies

Code rewrites cover schema (`schema.xml` → OpenSearch mappings), query DSL (eDisMax → `multi_match`/`bool`, ES X-Pack → OpenSearch native plugins), language-binding swaps (`solrj` → `opensearch-java`, `elasticsearch-py` → `opensearch-py`), and ingest-pipeline conversion.

| Strategy | What it does | When to recommend |
|---|---|---|
| **Agentic tools** (e.g. Amazon Q Developer Agent for code transformation, Claude / Cursor with appropriate prompts) | Iterative LLM-driven rewrite of the customer's application source. Low ceremony; works well for small-to-medium codebases and language-binding swaps. | Default for one-off / small-team rewrites where the customer can review diffs case-by-case. |
| **AWS Transform Custom** | AWS-managed bulk code transformation pipeline. Migration Assistant for Amazon OpenSearch Service ships with an **example `solrj` → `opensearch-java` transformation** that customers can use as the starting template, then extend for their own bindings. | Best fit for large codebases, regulated rewrites where the transformation pipeline must be auditable, or when the customer already has an AWS Transform deployment for other languages. |
| **Manual rewrite** | Engineer-driven port. The customer's own team writes the new code. | Only when the codebase is small AND the team needs the cycles to internalize OpenSearch's mental model — pedagogical, not efficient. |

**Trigger**: Any time the source is **Solr** OR uses **ES X-Pack-only features** (ELSER, Watcher, Canvas, ES SQL with non-portable functions) OR has client code in a language whose `opensearch-*` client has API differences (notably `solrj` ↔ `opensearch-java`, ES Painless scripts ↔ OpenSearch Painless), Application Code Rewrite is required and must appear as its own line in the migration plan.

**Skip Application Code Rewrite when:** ES → AOS at the same major engine version with no X-Pack dependencies, the existing `elasticsearch-*` client is wire-compatible with the target OpenSearch version (test the version-compatibility matrix before assuming), and the customer keeps their existing schema.

## Sizing-related universal rules (apply when this capability sizes a target)

- **Current-generation instances.** Default to Graviton (`r7g`/`r8g` for memory-optimized; `m7g`/`m8g` for cluster managers). `r6g`/`r6gd` only with explicit justification (existing RIs, specific compatibility need).
- **Input honesty.** When sizing on UNKNOWN inputs, lead with `[BLOCKER — need input]` OR present 2–3 tiered bands (small/medium/large workload assumption). Never present a single point estimate built on invented numbers.

## Cross-capability handoff

If the user prompt spans capabilities — for example *"migrate from Solr AND set up RAG on the new domain"* — produce the migration response and close with a one-line handoff:

- For **search** (vector / RAG / semantic / hybrid): see [`search-semantic-search-guide.md`](search-semantic-search-guide.md).
- For **provisioning** (provision / upgrade / monitor): see [`provisioning-reference.md`](provisioning-reference.md).
- For **log-analytics** on the new domain: see [`log-analytics-guide.md`](log-analytics-guide.md).
- For **trace-analytics** on the new domain: see [`trace-analytics-trace-queries.md`](trace-analytics-trace-queries.md).

## Workflow at a glance

```
0. ANTI_PATTERN_GUARD → halt + pushback if wrong-fit migration
1. IDENTIFY → first sentence restates source/version/region/persona
2. FINGERPRINT → JSON shape from artifacts; mark UNKNOWN for missing
3. COMPATIBILITY SCAN → gap register with severity (BLOCKING / HIGH / MEDIUM / LOW)
4. TARGET SHAPE → Managed (default) vs Serverless NextGen vs Classic
5. MIGRATION PATH → for each component the customer needs (Historical Data Migration, Live Traffic Migration, Application Code Rewrite — not all are required), pick a primary strategy from the per-component tables in § "Components of a migration". Skip components that don't apply to this workload.
6. SIZING → instance class + node count + storage + shards (mandatory ONLY when Step 0 anti-pattern guard does not trigger)
7. READINESS → 7-dimension 0-100 score; tier GREEN/YELLOW/RED
8. RENDER → templates in assets/; required sections in order
9. VERIFY → batched pass for [verify] markers; only resolve in ONE pass
```

**Speed contract.** Steps 3–7 draft directly from this file's tables (stable-core). Tag every version-volatile value with `[verify]`. Resolve all `[verify]` markers in ONE batched pass at Step 9 — never do per-claim retrieval.

---

## Step 0: ANTI_PATTERN_GUARD

Before doing anything else, check whether this is a wrong-fit migration:

- Workload is exact-match + small (<10K records) + transactional + relational integrity (foreign keys, hierarchy, audit logs)
- Common anti-patterns: Postgres HR DB, simple key-value cache, transactional payment ledger, audit log with regulatory immutability

If TRUE: HALT this workflow. Dispatch to references/assessment-shape-anti-pattern-pushback.md.

The recipe says: REFUSE to provide OpenSearch sizing. Verbatim refusal template:
"I'm not going to spec instance types or shard counts because recommending a topology for a migration that shouldn't happen lends false confidence to the wrong path."

FORBIDDEN HEDGES (never use): "Option B", "if you insist", "search-only sidecar", "if you do go this path", "for completeness".

Recommend the right tool (e.g. Postgres pg_trgm + tsvector + GIN) with concrete DDL recipe. Name future-fit triggers that WOULD change the answer.

---

## Step 1 — Identify

Restate in first sentence: source engine + version + target region + persona. Examples:

- *"You're on Apache Solr 8.11 SolrCloud, target Amazon OpenSearch Service us-east-1, DevOps / Platform Engineer — here's the assessment."*
- *"ES 7.17 on Elastic Cloud → Amazon OpenSearch Service us-west-2, Search Relevance Engineer persona — here's the path."*
- *"OS 1.3 with NMSLIB k-NN → OpenSearch 3.x — here's the upgrade plan."*

**Persona detection:**

| Cue | Persona |
|---|---|
| "I'm a product manager" / "I'm a director" / "I'm a TPM" / "I'm in product" | **Business Stakeholder** — six business questions |
| Explicit "what do you need from me" + no technical artifact + no migration question | **Business Stakeholder** |
| "What's the path?" / "high-level overview" / "what's involved?" | **Overview request** — produce 2–4 phase substantive overview, NOT business intake |
| Pastes `schema.xml`, `_cat/*`, query DSL, sizing spec | **Search Relevance Engineer** OR **DevOps / Platform Engineer** |
| Mentions latency, sizing, instance types, JVM, sharding | **DevOps / Platform Engineer** |
| Mentions BM25, query relevance, custom analyzers, ELSER, eDisMax | **Search Relevance Engineer** |
| Mixed signals | Pick most technical voice; add 1-page exec header |

---

## Step 2 — Fingerprint

For technical personas, capture this JSON from whatever artifacts the customer pasted. Mark missing fields UNKNOWN. Don't run a multi-prompt interview.

```json
{
  "source_engine": "elasticsearch | opensearch | solr",
  "version": "7.10.2",
  "summary": {
    "node_count": 6,
    "index_count": 120,
    "total_docs": 3200000000,
    "total_gb": 8000,
    "plugin_count": 7,
    "health_status": "green",
    "ilm_used": false,
    "watcher_used": false,
    "runtime_fields_used": false,
    "source_disabled": false,
    "post_fork": false,
    "dih_used": false,
    "velocity_response_writer": false,
    "xslt_response_writer": false,
    "custom_lib_count": 0
  },
  "indices": [
    {"name": "logs-2024-11", "docs": 50000000, "store_size": "120gb", "primary": 6, "replica": 1}
  ],
  "plugins": [
    {"node": "ip-10-0-1-12", "component": "analysis-icu", "version": "7.10.2"}
  ],
  "files_provided": ["_cat/indices.json", "_cluster/health.json", "_nodes/stats.json"]
}
```

For **Solr**, build from `schema.xml`, `solrconfig.xml`, and intake answers.

For **Business Stakeholder** persona, run the six-question intake first (see § Business Stakeholder intake).

### Business Stakeholder intake

**Six business questions only** — frame in business terms, no technical artifacts:

1. **Use case** — what is the search system powering today? E-commerce? Internal documents? Support knowledge base? Log analytics? Security/SIEM?
2. **Users** — internal employees vs external customers? Approximate user count (DAU and total)?
3. **Criticality / SLA** — Tier-1 customer-facing, important-but-not-critical, best-effort? Any explicit availability SLA (99.9%, 99.95%)? RPO/RTO?
4. **Traffic** — peak QPS and sustained QPS? If unknown, give user count + usage pattern; we'll estimate.
5. **Index updates** — how many docs added/updated per day? Streaming (continuous) or bulk (nightly batch)? 12–24 month growth projection?
6. **Document size** — average size in KB, or one-line description of what a typical document looks like?

**You MUST NOT ask a Business Stakeholder for:** `schema.xml`, `solrconfig.xml`, `_cat/indices` JSON, shard/replica counts, plugin lists, instance types, JVM heap sizes, query DSL, custom analyzers, eDisMax syntax, version preferences, budget figures, auth-backend specifics. Asking any of those FAILS the Business Stakeholder branch.

After the six are answered, translate them into a technical fingerprint internally and proceed to the compatibility scan.

---

## Step 3 — Compatibility scan / gap register

Emit one gap-register entry per finding:

```json
{
  "id": "ES_RUNTIME_FIELDS",
  "feature": "Elasticsearch runtime fields",
  "severity": "BLOCKING|HIGH|MEDIUM|LOW",
  "lane": "migration-specific|risk-blocker",
  "category": "schema|query|auth|ops|dashboards|plugin|version|sizing",
  "description": "...",
  "workaround": "...",
  "citation_url": "..."
}
```

### Severity + Lane rubric

Every gap-register entry MUST carry both a **Severity** and a **Lane**. Severity is the magnitude of the behavioral impact; Lane is the framing for the customer (does the migration plan already handle it, or does the customer need to act?). Canonical vocabulary lives in [`compatibility-rubric.md`](compatibility-rubric.md); the abbreviated copy is below.

| Severity | Meaning |
|---|---|
| **BLOCKING** | No workaround in OpenSearch; customer must rearchitect, accept feature loss, or stop |
| **HIGH** | Major behavioral difference or required rewrite — affects code or queries |
| **MEDIUM** | Configuration / mapping difference handled at migration time |
| **LOW** | Cosmetic / negligible (terminology rename, metric name change) |

| Lane | When to use |
|---|---|
| **migration-specific** | The migration plan already includes a documented remediation (transformer flag, sanitizer, default override) that the path applies on the customer's behalf. Frame as *"this is how the migration handles X"*. |
| **risk-blocker** | The item genuinely constrains the migration: no known fix, capacity-plan implications, irreversible target choices, or customer action required to land. |

The Severity × Lane combination determines whether the row deducts from the Compatibility readiness weight (see [`readiness-rubric.md`](readiness-rubric.md) — only `risk-blocker`-lane rows deduct).

### Always-flag list (apply on every assessment)

**Elasticsearch sources** (canonical X-Pack → OpenSearch plugin/feature map; do not duplicate elsewhere — link to this section):

| Feature | Severity | Lane | OpenSearch equivalent |
|---|---|---|---|
| ES Runtime fields | HIGH | risk-blocker | Partial: derived fields (OS 2.15+) — limited functionality |
| X-Pack ILM | MEDIUM | risk-blocker | ISM — JSON does NOT import; rebuild policy |
| X-Pack Watcher | HIGH | risk-blocker | Alerting plugin — rewrite all monitors |
| X-Pack ML jobs / anomaly detection | HIGH | risk-blocker | Anomaly Detection plugin — different API; rewrite |
| ELSER (Elastic Learned Sparse Encoder) | HIGH | risk-blocker | Use `neural_sparse` query with SageMaker-hosted model |
| ES SQL | HIGH | migration-specific | OpenSearch SQL plugin — most queries work; verify edge cases |
| Cross-Cluster Replication (CCR) | MEDIUM | risk-blocker | CCR plugin available on Managed (not Serverless) |
| Cross-Cluster Search (CCS) | HIGH | risk-blocker | Not supported on Serverless; partial on Managed |
| Painless inline scripts | MEDIUM | risk-blocker | Supported on Managed (not Serverless) |
| `_type` (multi-type) | HIGH (ES 5.x/6.x) | migration-specific | Removed in OS 1.0; Migration Assistant metadata transformer flattens before reindex |
| ES `_parent` (5.x) | HIGH | risk-blocker | Replaced by `join` field type — schema redesign |
| `fielddata: true` on text (ES 1.x/2.x) | BLOCKING | migration-specific | OOM risk if untouched, but Migration Assistant metadata transformer strips it and adds `.keyword` subfield automatically |
| Field-level encryption | LOW | migration-specific | Field masking via FGAC |
| Authentication: native realm / file realm | MEDIUM | migration-specific | Internal user database via FGAC |
| Authentication: LDAP / AD | MEDIUM | migration-specific | Supported via FGAC backend |
| Authentication: SAML | MEDIUM | migration-specific | Supported via Cognito or direct SAML |
| Snapshot from ES ≥ 7.11 | BLOCKING | risk-blocker | ELv2/SSPL license lockout — no snapshot path; use Migration Assistant Historical Data Migration or `_reindex` |

**Solr sources:**

| Feature | Severity | Lane | OpenSearch equivalent |
|---|---|---|---|
| `<uniqueKey>` field | MEDIUM | migration-specific | Map as `keyword` AND bind to `_id` on every `_bulk`/`index` |
| `<copyField source="A" dest="B"/>` | LOW | migration-specific | `"copy_to": "B"` on field A in mapping |
| `_version_` field | LOW | migration-specific | OMIT — OpenSearch has its own `_version` |
| Deprecated/removed Solr field types (Trie*, etc.) | HIGH | migration-specific | For the full Solr 7/8/9 deprecation list, see assessment-shape-schema-conversion.md §Section D — Gap register. |
| `solr.CurrencyField` | HIGH | migration-specific | Denormalize: `price_amount` (`scaled_float`) + `price_currency` (`keyword`) + `price_base` numeric |
| `solr.EnumField` / `EnumFieldType` | MEDIUM | migration-specific | Denormalize: `<name>` (`keyword`) + `<name>_rank` (`integer`) |
| `solr.ICUCollationField` | LOW | migration-specific | `icu_collation_keyword` — `analysis-icu` plugin pre-installed on AOS |
| Solr ≤ 5.x TF-IDF default similarity | HIGH | risk-blocker | OpenSearch defaults BM25 — relevance tuning required |
| eDisMax `qf field^boost` | LOW | migration-specific | `multi_match` `type: best_fields` with same boosts |
| eDisMax `pf` (phrase boost) | MEDIUM | risk-blocker | `should` + `multi_match type:phrase` — behavioral approximation; A/B against Solr |
| eDisMax `tie` | LOW | migration-specific | `tie_breaker` on `multi_match type: best_fields` |
| Solr `mm` (e.g. `2<-25%`) | LOW | migration-specific | `minimum_should_match` — same syntax, passes UNCHANGED |
| Solr `q.op=AND` | HIGH | migration-specific | `default_operator: AND` on `query_string` (when source `solrconfig.xml` overrides Solr's OR default to AND; OpenSearch defaults to OR — top divergence cause) |
| Removed Solr handlers/writers (DIH, Velocity, XSLT, etc.) | HIGH | risk-blocker | For the full Solr 7/8/9 deprecation list, see assessment-shape-schema-conversion.md §Section D — Gap register. |
| Custom `analyzers` (Java JARs) | HIGH | risk-blocker | Audit Migration Assistant for Amazon OpenSearch Service's auto-translation; rare cases need transformer override |
| `<dynamicField>` regex patterns | MEDIUM | migration-specific | Migration Assistant for Amazon OpenSearch Service usually auto-translates; audit edge cases |
| `<requestHandler class="solr.SearchHandler">` | LOW | migration-specific | Translate to `_search` endpoint with `default_field` and `default_operator` from `solrconfig.xml` |

**OpenSearch in-place upgrade:**

- The upgrade chain is OS 1.0–1.2 → 1.3 → 2.19 → 3.x. The 1.3-and-2.19 mandatory hops are policy (won't change); each minor inside that chain is a moving target. For the current per-version hop matrix, see [version-migration.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/version-migration.html).

### Lucene segment-format wall (root cause for pre-2.x reindex)

OS 1.3 indexes ship Lucene 8 segments. OS 3.x ships Lucene 10. Lucene's segment format is **forward-only** — Lucene 10 cannot read Lucene 8. Any pre-OS-2.0 index destined for OS 3.x MUST be reindexed before reaching 3.x.

Parallel cause: NMSLIB k-NN engine was REMOVED in OS 3.0 (deprecated in 2.19). Pre-existing NMSLIB indexes must reindex into FAISS before reaching 3.x.

### OS 3.x breaking changes

- JDK 21 minimum (was JDK 17 in 2.x)
- Security Manager → Java agent
- Removed k-NN settings: knn.algo_param.ef_construction (legacy), several others
- Lucene 10 baseline (segment format wall — see above)
- NMSLIB engine removed
- Default search.allow_expensive_queries = false (more strict)

### Stable-core ES → OS facts (drafted directly)

- **ES 7.10.2** is the engine fork point. ES 1.0 GA was Feb 2014; OS 1.0 GA was July 2021.
- ES 7.0 removed `_type` placeholder; OS 1.0 removed types entirely (placeholder `_doc` blows up `_reindex`).
- ES 7.11+ relicensed to ELv2/SSPL (Jan 2021) — Snapshot/Restore from those versions is NOT supported into Amazon OpenSearch Service.
- ES 5.x/6.x cannot one-hop snapshot/restore into modern OpenSearch (Lucene segment versions and snapshot format are incompatible).

### Stable-core Solr → OS facts

- Solr → OpenSearch is **document-level**, NOT segment-level. There is NO snapshot path between the two engines.
- Solr stored="false" fields can ONLY be recovered via Migration Assistant for Amazon OpenSearch Service Historical Data Migration (reads source Lucene segments).
- Lucene 10 (OS 3.x) cannot read Lucene 8 (pre-OS 2.0) — segment format is forward-only.

---

## Step 4 — Target shape

Default to **Managed Domain** when ambiguous. Re-evaluate Serverless after stable traffic.

### Managed-only requirements

If ANY of these is needed, the answer is Managed:

- SIEM / Security Analytics plugin
- Custom plugins (Java JARs, custom analyzers, custom processors)
- Lucene k-NN engine, FAISS IVF, FAISS PQ
- Cross-Cluster Replication (CCR) or Cross-Cluster Search (CCS)
- UltraWarm / Cold tiering
- Manual snapshots
- Inline scripts (Painless)
- T-class burstable instances (only available on Managed)
- User-tunable sharding
- Predictable steady-state (RI savings opportunity)
- Very small clusters (≤ 2 OCU steady-state — Managed is cheaper)

### Serverless eligibility

Serverless is a fit when ALL of these hold:

- Workload is full-text search, time-series logs (Classic only), or vector (NextGen or Classic)
- Bursty traffic (10×+ swings) or zero-ops preference
- No custom plugins, no CCR/CCS, no manual snapshots, no inline scripts
- Vector workload uses simplified API (NextGen) OR FAISS HNSW only (Classic)

### NextGen vs Classic Serverless (CRITICAL distinction)

**NextGen collections:**

- Support **Search and Vector Search** types only (no TIME_SERIES on NextGen)
- **Vector Search uses simplified API** — system auto-picks engine and configuration
- **Custom document IDs supported**
- **32x compression by default**
- **GPU index build acceleration** available
- 10s refresh interval

**Classic collections:**

- Support **Search, Vector Search, AND TIME_SERIES**
- Vector Search requires explicit `engine: faiss` (Lucene/IVF/PQ NOT supported on Classic)
- TIME_SERIES and VECTORSEARCH **reject custom `_id` PUT/upsert** (Classic only — NextGen vector accepts custom IDs)
- 60s refresh interval for vector Classic; 10s for search Classic

**OCU model:**

- 1 OCU = 6 GiB RAM + matching vCPU + ~120 GiB ephemeral storage
- Redundancy ON: minimum 1 indexing OCU (0.5 × 2) + 1 search OCU (0.5 × 2) — billed even idle
- Redundancy OFF: minimum 0.5 OCU × 2 for first collection
- Default max: 10 OCUs each indexing/search; up to 1700 each on request

### Tiebreaker rules

- Vector + simplified API + custom IDs needed → Serverless NextGen Vector
- Vector + IVF/PQ/Lucene needed → Managed
- Logs > 2.5 TiB hot → time-series Classic Serverless OR Managed UltraWarm (compare cost)
- Mixed keyword + vector (Classic) → ⚠️ **Vector Search collections cannot share OCUs with Search/TimeSeries collections** — doubles idle floor
- Otherwise → Managed default; re-evaluate after stable traffic

---

## Step 5 — Migration path (per-component selection)

For each of the three components, decide whether it applies and which strategy fits. Skip components that don't apply. See § "Components of a migration" above for the strategy menu under each.

| Component | Required when… | Skip when… |
|---|---|---|
| **Historical Data Migration** | The customer has existing data they want preserved on the target (almost always). | Greenfield; no historical data; or full re-emit from the system of record is faster than migrating. |
| **Live Traffic Migration** | The maintenance window the customer can grant is shorter than the time Historical Data Migration will take, AND the workload has live writes during cutover. | The maintenance window comfortably covers the duration of Historical Data Migration (the read-only window IS however long HDM takes for this dataset) — pause writes, run HDM, cut over. Also skip when workload is read-heavy / batch with no live-write SLA. |
| **Application Code Rewrite** | Source is **Solr** (different APIs); ES uses **X-Pack-only features** (ELSER, Watcher, ES SQL with non-portable functions); language-binding swap required (`solrj` → `opensearch-java`); major Lucene segment-format wall (OS 3.x). | ES → AOS at the same major engine version, no X-Pack, schema preserved, existing `elasticsearch-*` client wire-compatible. |

Once you've decided which components apply, pick the primary strategy under each from the per-component tables in § "Components of a migration". Common combinations:

| Customer profile | Components in plan |
|---|---|
| Solr → AOS (any size) | Historical Data Migration + (optional) Live Traffic Migration + Application Code Rewrite |
| Pre-fork ES → AOS, maintenance window OK | Historical Data Migration only (Snapshot/Restore strategy) |
| Post-fork ES (≥ 7.11) <100 GB, 30-min window | Historical Data Migration only (`_reindex` from remote strategy) |
| Post-fork ES, large or multi-index, zero-downtime | Historical Data Migration + Live Traffic Migration (both via Migration Assistant for Amazon OpenSearch Service) |
| ES with X-Pack-only features | Historical Data Migration + Application Code Rewrite (replace X-Pack code-paths) |
| OS self-managed → AOS, same engine | Historical Data Migration only (in-place blue/green strategy) |
| Greenfield (new app, no source) | None of the above — go to the **provisioning** capability instead. |

### Historical Data Migration — quick strategy lookup

This is a fast lookup over the strategies in § "Components of a migration → Historical Data Migration". Pick by source profile.

| Source / Scenario | Strategy | Notes |
|---|---|---|
| **Solr** (any volume) | **Migration Assistant for Amazon OpenSearch Service Historical Data Migration → OS 3.x or Serverless** | Required for `stored="false"` fields; target restriction is architectural (no OS 1.x / 2.x for Solr) |
| **Solr, all `stored="true"`, small dataset, easy re-emit** | Solr `/export` + `_bulk` (manual) | Cheap; auditing required to confirm no `stored="false"` |
| **Multi-major ES backfill** (pre-7.x) | Migration Assistant for Amazon OpenSearch Service Historical Data Migration | Multi-major hop only practical here |
| **Pre-fork ES (≤ 7.10.2)** | Snapshot/Restore | Pre-fork — simplest path while license boundary allows it |
| **Post-fork ES (≥ 7.11), small dataset, ≥ 30 min window** | **`_reindex` from remote (PRIMARY)** | Snapshot/Restore BLOCKED post-fork; HDM overkill at small scale |
| **Post-fork ES (≥ 7.11), large or multi-index complex** | Migration Assistant for Amazon OpenSearch Service Historical Data Migration | Snapshot/Restore BLOCKED post-fork |
| **OS in-place upgrade** | Blue/green upgrade | Free; mandatory 2.19 hop for 1.3 → 3.x |
| **OS self-managed → AOS** | Migration Assistant for Amazon OpenSearch Service preferred | Same engine; Migration Assistant for Amazon OpenSearch Service streamlines |
| **Cross-cloud / cross-account** | Migration Assistant for Amazon OpenSearch Service OR OSI with SigV4 auth | |
| **GovCloud** | Migration Assistant for Amazon OpenSearch Service Historical Data Migration | Verify current shard-size cap against live docs (`[verify]`) |

### Live Traffic Migration — quick strategy lookup

| Workload profile | Strategy |
|---|---|
| **Pre-fork ES (≤ 7.10.2), zero-downtime** | Migration Assistant for Amazon OpenSearch Service Live Traffic Migration paired with Historical Data Migration (Snapshot/Restore for the bulk) |
| **Post-fork ES (≥ 7.11), zero-downtime** | Migration Assistant for Amazon OpenSearch Service Live Traffic Migration paired with Historical Data Migration |
| **Solr, zero-downtime** | Migration Assistant for Amazon OpenSearch Service Live Traffic Migration paired with Historical Data Migration |
| **Continuous replication post-cutover** | Live Traffic Migration or CCR (CCR if both ends are AOS) |
| **High-throughput live writes** | OSI fan-out OR staged migration; Live Traffic Migration is fine for typical sustained throughput |
| **Customer rejects "third-party tooling"** | Application-layer dual-write (customer code; not third-party) |
| **Maintenance window long enough to cover Historical Data Migration** | Skip Live Traffic Migration entirely — pause writes, run Historical Data Migration, cut over. The read-only window IS however long Historical Data Migration takes for this dataset. Estimate that duration up-front (gated by source size, network bandwidth, ingest worker count) and validate it fits the customer's maintenance budget. |

> *Source/target version eligibility for each tool: see [Migration Assistant for Amazon OpenSearch Service source-and-target versions](https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/source-and-target-versions.html).* The ES 7.11 fork point is **architectural** (license boundary — Snapshot/Restore is blocked into AOS post-fork) and stays inline.

### Always-true rules (across components)

These hold regardless of which component you're picking a strategy for:

- **Solr sources**: Historical Data Migration via Migration Assistant for Amazon OpenSearch Service is the PRIMARY HDM strategy regardless of volume — required for `stored="false"` fields. Recommend non-Migration Assistant alternatives only when (a) every needed field is `stored="true"`, (b) easy re-emit from system of record, AND (c) dataset is small. Flag the trade-off.
- **`_source: false` indexes**: Migration Assistant for Amazon OpenSearch Service Historical Data Migration is the ONLY supported HDM path — verify `_source` status before recommending anything else.
- **Post-fork ES (≥ 7.11)**: do NOT recommend Snapshot/Restore for HDM — the license fork is architectural; use Migration Assistant for Amazon OpenSearch Service Historical Data Migration or `_reindex` from remote.
- **Multi-major ES backfill** (pre-7.x → modern OS): Migration Assistant for Amazon OpenSearch Service Historical Data Migration is the only practical multi-major path; pair with Live Traffic Migration when zero-downtime is required.
- **Target = Serverless**: Migration Assistant for Amazon OpenSearch Service Live Traffic Migration is supported but document IDs are preserved only on `SEARCH` collection types (TIMESERIES and VECTORSEARCH Classic use server-generated IDs unless using NextGen vector with custom-ID support).
- **Post-fork ES (≥ 7.11) at small scale with usable maintenance window**: `_reindex` from remote is the PRIMARY HDM strategy — Migration Assistant for Amazon OpenSearch Service Historical Data Migration becomes primary only when the dataset is large, multi-index/complex, OR source→target network reachability is impossible.

---

## Step 6 — Sizing

**Sizing is mandatory ONLY when Step 0 anti-pattern guard does not trigger.** When Step 0 halts the workflow, do NOT produce a sizing recommendation — providing topology for a migration that shouldn't happen lends false confidence to the wrong path.

See [`references/sizing.md`](sizing.md) for the full math. Quick rules for migration-assessment sizing:

- **Match-source rule** (when source sizing is provided): stay close to source RAM (8–16 GB per data node) unless workload signals (peak QPS, retention, page-cache headroom) justify uplift. Recommending 4× source RAM without explicit signal-based justification is a sizing miss.
- **Default starting point** (no source sizing provided): `3 × r7g.large.search` (8 GB heap each) + `3 × m7g.large.search` cluster managers + `gp3 200 GiB`. Multi-AZ.
- **Storage formula:** `source_data × (1 + replicas) × 1.45`.
- **Shard size:** 10–30 GiB for search, 30–50 GiB for write-heavy/logs.
- **Primary shards:** `(source + growth) × 1.1 / desired_shard_size`, rounded up to multiple of data-node count.
- **Cluster manager and per-node shard caps:** see [sizing.md §Topology defaults](sizing.md). Source of truth: [bp.html#bp-sharding](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html#bp-sharding).

Output **mandatory** for technical persona (when Step 0 does not trigger): instance class + node count + storage + shard count. Pointing at the Pricing Calculator without naming the instance is incomplete.

### Sizing under UNKNOWNs

When source metrics are UNKNOWN (data volume, peak QPS, doc count), use ONE of two patterns — never single point-estimate on assumed value:

Pattern A — [BLOCKER — need input]:

```
[BLOCKER — need source data volume to size]
Cannot recommend instance class until source size is known.
SHARE: total docs, total GB, peak QPS, retention.
```

Pattern B — Tiered bands keyed to unknown variable:

```
| Source size | Recommended | Reason |
|---|---|---|
| <100 GB | 3 × m7g.large.search | Match-source for tiny |
| 100–500 GB | 6 × r7g.large.search | Standard mid-tier |
| >500 GB | 9 × r7g.2xlarge.search | Headroom for growth |
```

---

## Step 7 — Readiness score

Canonical scoring rules and worked example live in [`readiness-rubric.md`](readiness-rubric.md). The abbreviated form:

Score across 7 dimensions (0–100 total). Tier:

- **GREEN ≥ 80** — proceed; surface top items to flag in §7 (split across Migration specifics and Risks/blockers)
- **YELLOW 60–79** — PoC + spike on weakest dimension before committing
- **RED < 60** — do not commit; revisit weakest dimension first

Tier override: any BLOCKING `risk-blocker`-lane row caps the readiness tier at YELLOW until the customer commits to the remediation path.

| Dimension | Weight | What it captures |
|---|---|---|
| Compatibility | 25 | Number/severity of **`risk-blocker`-lane** gap-register entries. `migration-specific`-lane entries do NOT deduct because the migration plan already handles them. |
| Operational readiness | 15 | Team familiarity with OpenSearch, on-call coverage |
| Sizing fitness | 15 | Confidence in instance class + count for projected workload |
| Data-movement complexity | 15 | Volume, transformations, cutover style |
| Cutover complexity | 10 | Downtime tolerance, dual-write feasibility, rollback plan |
| Sizing-input completeness | 10 | How much sizing input the customer provided |
| Stakeholder alignment | 10 | Sign-off from product/security/infra |

You MUST cross-reference at least 1 gotcha from [`assessment-gotchas.md`](assessment-gotchas.md) by number — many gotchas are not in any AWS doc and missing them is the most common readiness gap. Whether the gotcha contributes to the Compatibility deduction depends on its `Category:` tag (only `TRUE_BLOCKER` and customer-action `MIGRATION_SPECIFIC` items deduct).

---

## Step 8 — Render report

Templates in `assets/`:

- `report-template.md` → `MIGRATION_ASSESSMENT.md` (full assessment, source-agnostic)
- `executive-summary-template.md` → `EXECUTIVE_SUMMARY.md` (Business Stakeholder)
- `tech-deepdive-template.md` → `TECHNICAL_DEEP_DIVE.md` (Search Relevance Engineer / DevOps)
- Solr-specific: `solr-report-template.md`, `solr-index-template-skeleton.md`, `solr-gap-register.md`
- ES-specific: `elasticsearch-report-template.md`, `elasticsearch-index-template-skeleton.md`, `elasticsearch-gap-register.md`

**Required sections (in this order):**

1. Executive Summary
2. Source
3. Target
4. Migration Path
5. Sizing
6. Readiness
7. Risks
8. Next Steps
9. Citations

---

## Step 9 — Verify (batched)

Collect every `[verify]` marker into one list. Resolve in ONE batch:

1. **Gather** all `[verify]` markers (feature-parity rows, plugin-support, current instance families + regional availability, NextGen/Migration Assistant for Amazon OpenSearch Service capability rows, per-version k-NN default engine, exact per-version limits)
2. **Retrieve** in as few calls as possible: one AWS-docs sweep, one OpenSearch-project sweep, one regional-availability call. Run independent retrievals concurrently.
3. **Resolve** each tag: replace with confirmed value + add source URL + retrieval timestamp to Citations.

**Pre-delivery checklist** (reproduce in response, tick each):

```
- [ ] All 9 required sections emitted, in order
- [ ] Every [verify] marker resolved
- [ ] Citations section: ≥ 3 unique URLs with retrieval timestamp
- [ ] https://calculator.aws surfaced for cost handoff
- [ ] ≥ 1 gotcha from assessment-gotchas.md cross-referenced
- [ ] Target shape default = MANAGED unless workload justifies Serverless
- [ ] Each required component (Historical Data Migration / Live Traffic Migration / Application Code Rewrite) has a primary strategy named
- [ ] Persona-correct depth
- [ ] No embedded credentials/endpoints/master usernames
- [ ] Security section cites references/security.md and confirms each control
- [ ] Step 0 anti-pattern guard evaluated; if triggered, NO sizing emitted
```

If any box can't be ticked, fix the gap before responding.

---

## Always-true rule reminders (already in SKILL.md — repeated here for context)

- ES 7.10.2 is the engine fork point. ES ≥ 7.11 (post-fork) snapshot is NOT supported into AOS.
- Solr → OpenSearch is document-level, NOT segment-level — refactor, not lift-and-shift.
- OS 1.3 → 2.19 → 3.x. (1.0–1.2 need 1.3 hop first.)
- Lucene 8 → 10 wall: pre-2.x indexes must reindex before reaching OS 3.x.
- `q.op=AND` divergence — when the source `solrconfig.xml` sets `q.op=AND` (a common production override; Solr's own default is OR), OpenSearch defaults to OR. Set `default_operator: AND` on `query_string`.
- Solr `mm` syntax — passes UNCHANGED as `minimum_should_match`.
- NMSLIB engine REMOVED in OS 3.0+ (was deprecated in 2.19). FAISS default since 2.18.
- Migration Assistant for Amazon OpenSearch Service Solr backfill targets only OS 3.x or Serverless.
- Migration Assistant for Amazon OpenSearch Service 3.0 deploys to Amazon EKS.
- NextGen Vector simplified API (no engine/mode); supports custom doc IDs.
- Classic Serverless Vector requires `engine: faiss`; rejects custom `_id` on TIMESERIES/VECTORSEARCH.
- Vector Search collections cannot share OCUs with Search/TimeSeries — doubles idle floor.
- Default to current Graviton families: `r7g`/`r8g` for memory-optimized; `m7g`/`m8g` for cluster managers.
- T-class for prod data nodes is forbidden (CPU credits exhaust).
