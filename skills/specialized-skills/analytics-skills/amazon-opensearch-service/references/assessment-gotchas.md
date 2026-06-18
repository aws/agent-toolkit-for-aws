# Gotchas — production failure modes

The traps experienced practitioners hit on Amazon OpenSearch. Each one is a real failure mode that silently breaks plans. Cite by number when the profile matches.

Each entry carries a `**Category:**` tag that determines which lane it surfaces under in the FULL_ASSESSMENT §7 split (and which assets it deducts from in [`readiness-rubric.md`](readiness-rubric.md)):

| Category | Meaning | Lane in §7 |
|---|---|---|
| `TRUE_BLOCKER` | No clean fix; constrains target choice or forces rearchitecture. Deducts from Compatibility weight. | Risks/blockers |
| `MIGRATION_SPECIFIC` | The migration plan already includes a documented remediation (transformer, sanitizer, config override). Does not deduct unless customer action is required. | Migration specifics |
| `OPERATIONAL_CONSIDERATION` | Default-behavior thing to know about; affects sizing or operations rather than correctness. | Risks/blockers (when actionable) or Migration specifics (when path-handled). Use judgment. |
| `COST_TCO` | Pricing/billing trap that affects TCO model accuracy but doesn't block the migration. | Migration specifics — reframe the TCO model. |
| `CLARIFICATION` | The gotcha is "the customer's claim is wrong / ambiguous"; resolution is pre-work, not a remediation. | Surface as a question, not in either §7 lane. |

## 1. Solr → OpenSearch is document-level, NOT segment-level

**Category:** TRUE_BLOCKER

There is NO snapshot path between Solr and OpenSearch — different codecs, schema layouts. Schema, queries, configs all need translation.

**Detect:** "lift and shift Solr to OpenSearch", "snapshot Solr"
**Fix:** State explicitly that this is a refactor migration. Use Migration Assistant for Amazon OpenSearch Service Solr backfill (Historical Data Migration) or document-level export+bulk for small datasets.

## 2. ES ≥ 7.11 snapshot/restore is NOT supported on AOS

**Category:** TRUE_BLOCKER

ES 7.11+ relicensed to ELv2/SSPL (Jan 2021). Snapshot/Restore from those versions to Amazon OpenSearch Service is NOT supported.

**Detect:** ES version ≥ 7.11 in source fingerprint; customer plans snapshot path
**Fix:** Use Migration Assistant for Amazon OpenSearch Service Historical Data Migration, or `_reindex` from remote for small datasets (<100 GB).

## 3. Lucene 8 → 10 segment-format wall at OS 3.0

**Category:** TRUE_BLOCKER

OS 3.x ships Lucene 10. Pre-2.x indexes carry Lucene 8 segments. Lucene's segment format is forward-only — Lucene-10 cannot read Lucene-8.

**Detect:** OS 1.x source upgrading to OS 3.x; ES 7.10 indexes; any pre-OS 2.0 indexes
**Fix:** Reindex affected indexes before upgrading to OS 3.x. Applies to hot, UltraWarm, and cold storage.

## 4. Per-node shard cap

**Category:** OPERATIONAL_CONSIDERATION

**Detect:** shard count > 800/node trending up.
**Fix:** see [`sizing.md` §Topology defaults](sizing.md) for current cluster-manager + shard-cap values; source of truth is [bp.html#bp-sharding](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html#bp-sharding). Architectural rule: Multi-AZ-with-Standby clusters cap at 1000/node regardless of OS version.

## 5. Cold storage is NOT directly queryable

**Category:** OPERATIONAL_CONSIDERATION

Cold storage holds detached indexes — must reattach to UltraWarm before querying. Migration is one index at a time, queue depth 100. Watch `WarmToColdMigrationQueueSize`.

**Detect:** "occasional queries on archived data"
**Fix:** Accept warm-up latency (minutes-to-hours), keep data in UltraWarm permanently, or use S3+Athena for true on-demand archives.

## 6. Serverless redundancy adds an OCU floor

**Category:** COST_TCO

Architectural rule: Redundancy ON adds an idle OCU floor (separate indexing + search minimums billed continuously).

**Detect:** Bursty/low-volume customer thinking "I'll only pay for what I use"
**Fix:** For current OCU minimums, see [`sizing.md` §OCU model](sizing.md) and [serverless-scaling.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html). For tiny non-prod workloads, consider small Managed `t3.medium.search`. NEVER `t2.*` or `t3.small.search` in prod.

## 7. Vector Search collections cannot share OCUs with Search/TimeSeries

**Category:** COST_TCO

Architectural rule: a vector search collection can't share OCUs with search and time series collections, even with same KMS key. Adding one vector collection adds a separate idle floor.

**Detect:** Mixed keyword + vector workload; user assumes one bill
**Fix:** For current OCU minimums, see [`sizing.md` §OCU model](sizing.md) and [serverless-scaling.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html). If vector is exploratory, run k-NN on existing Managed cluster instead.

## 8. Serverless ignores most user-supplied index settings

**Category:** MIGRATION_SPECIFIC

Number of shards, intervals, refresh interval are NOT modifiable on Serverless. `index.translog.*` and `index.routing.allocation.*` are dropped. Cannot restore a snapshot to Serverless directly.

**Detect:** Plan involves restoring an existing snapshot to Serverless
**Fix:** Use Migration Assistant for Amazon OpenSearch Service's metadata-migration Serverless sanitizer, or hand-strip settings before bulk. Re-validate post-load with `GET <idx>/_settings`.

## 9. NextGen TIME_SERIES does NOT exist

**Category:** TRUE_BLOCKER

NextGen Serverless supports only **Search and Vector Search** types. TIME_SERIES is **Classic-only**.

**Detect:** Customer wants time-series collection AND mentions "NextGen"
**Fix:** Use Classic for TIME_SERIES; or use Managed Domain with ISM-managed time-series indexes (often a better fit at scale).

## 10. NMSLIB removed in OS 3.0

**Category:** TRUE_BLOCKER

**Detect:** source uses NMSLIB engine, target is OS 3.x.
**Fix:** reindex into FAISS HNSW or FAISS IVF before the 3.x upgrade. Engine matrix and reindex recipe live in [`vector-knn.md`](vector-knn.md); source of truth for current engines is [knn.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/knn.html).

## 11. `q.op=AND` divergence (Solr → OpenSearch)

**Category:** MIGRATION_SPECIFIC

Solr defaults `q.op=OR`; if user sets `AND`, OpenSearch defaults must explicitly match. OpenSearch's default operator on `query_string` is `OR`.

**Detect:** Solr source with `<q.op>AND</q.op>` or eDisMax with `q.op=AND` in `solrconfig.xml`
**Fix:** Set `default_operator: AND` on `query_string`, OR `operator: AND` on `match`. Most common cause of result divergence.

## 12. `fielddata: true` on text fields will OOM data nodes

**Category:** MIGRATION_SPECIFIC

Pre-ES 2.0, text fields used in-memory `fielddata` for sort/agg. ES 1.x mappings still carry `"fielddata": true` and will OOM AOS data nodes on first aggregation.

**Detect:** Source = ES 1.x or 2.x; mapping JSON contains `fielddata`
**Fix:** Strip `fielddata`. Add a `.keyword` subfield: `"title": {"type":"text", "fields": {"keyword": {"type":"keyword"}}}`. Migration Assistant for Amazon OpenSearch Service transformer does this automatically; hand-rolled `_reindex` MUST do it explicitly.

## 13. ES 7 → OS 1 `_type` removal

**Category:** MIGRATION_SPECIFIC

ES 7 still allows the placeholder type `_doc`; OS 1.0 removed types entirely. Templates with `"_doc": {...}` blow up `_reindex`/`_bulk` with `[mapper_parsing_exception] unsupported parameters: [_doc]`.

**Detect:** ES 7 source with index templates
**Fix:** Migration Assistant for Amazon OpenSearch Service metadata transformer, OR pre-flatten with `jq 'del(.mappings._doc) | .mappings = .mappings._doc' template.json`.

## 14. NAT Gateway charges silently inflate VPC OpenSearch bills

**Category:** COST_TCO

A private cluster fetching plugins, Bedrock embeddings, IDP metadata, or external knowledge sources accumulates NAT-Gateway charges. NAT Gateway charges per [VPC pricing](https://aws.amazon.com/vpc/pricing/).

**Detect:** Private VPC cluster with external integrations
**Fix:** Use VPC endpoints for S3, Bedrock, STS, OpenSearch Service. Project residual NAT egress per [VPC pricing](https://aws.amazon.com/vpc/pricing/).

## 15. Manual snapshots bill against YOUR S3 bucket

**Category:** COST_TCO

AOS automated snapshots: kept 14 days (hourly, up to 336), no additional charge, in AOS-preconfigured bucket. Manual snapshots: stored in YOUR S3 bucket at standard S3 rates plus PUT charges.

**Detect:** Compliance retention > 14 days; cross-region snapshot requirements
**Fix:** Add S3 line to sizing model: `data_size × retention_days / 30 × $/GB-mo` plus PUT cost.

## 16. UltraWarm `uw.medium` cannot host k-NN indexes

**Category:** TRUE_BLOCKER

The instance lacks RAM headroom to hold k-NN graphs.

**Detect:** k-NN indexes scheduled for UltraWarm migration on uw.medium
**Fix:** Use `ultrawarm1.large.search` instead. For current UltraWarm RAM-per-instance figures and circuit-breaker sizing, see [ultrawarm.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ultrawarm.html).

## 17. OR1 trades RAM-bound aggregations for indexing throughput

**Category:** OPERATIONAL_CONSIDERATION

OR1 stores segments in S3 with local NVMe cache. ~2× r6g indexing throughput, replica=1 sufficient (S3 durable). Loses to r-family on cache-miss aggregations and k-NN graphs (RAM-bound).

**Detect:** k-NN, large-cardinality aggs, or cache-miss-sensitive workloads on OR1
**Fix:** Use OR1 only when `peak_indexing × avg_doc_size > 50 GB/day/node`. Use one replica unless durability model demands more. **Migration to OR1 is irreversible.**

## 18. Cluster goes read-only at flood-stage watermark (95%)

**Category:** OPERATIONAL_CONSIDERATION

When any node hits 95% disk, AOS applies `index.blocks.read_only_allow_delete: true` to all indexes with shards on that node. Releases automatically when below high (90%).

**Detect:** Cluster size near 90%; observability indexes growing fast
**Fix:** Alert on `FreeStorageSpace < 25 GB` or storage > 80%. Add storage / shrink shards / move data to UltraWarm BEFORE this hits.

## 19. Multi-AZ ≠ Multi-AZ with Standby

**Category:** CLARIFICATION

Multi-AZ: 99.9% SLA. Multi-AZ with Standby: 99.99% SLA. Standby pre-positions one zone as inactive, sub-minute failover. Standby requirements: 3 AZs, 3 dedicated cluster managers, 3 (or multiple of 3) data nodes, ≥2 replicas, Auto-Tune ON, GP3 storage.

**Detect:** Customer expects "no downtime ever" without Standby
**Fix:** Recommend Multi-AZ-with-Standby for tier-1 production. Standby is "available at no extra cost" but applies caps on per-shard size and total cluster shard count. For current Standby caps, see [managedomains-multiaz.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/managedomains-multiaz.html).

## 20. Logstash default distro license check rejects OpenSearch

**Category:** MIGRATION_SPECIFIC

Default Logstash distro has Elastic license check that rejects OpenSearch. Two workarounds:

**Detect:** Customer using Logstash with new Amazon OpenSearch destination
**Fix:** Use OSS distro of Logstash (Apache 2.0) OR `logstash-output-opensearch` plugin. Better: switch to OpenSearch Ingestion (managed Data Prepper) or Fluent Bit.

## 21. Cross-AZ data transfer is FREE within AOS clusters

**Category:** COST_TCO

Self-managed Elasticsearch on EC2 across AZs pays cross-AZ data-transfer at the standard regional rate for primary→replica replication. Amazon OpenSearch Service does NOT bill for intra-cluster cross-AZ replication.

**Detect:** Customer's current TCO model includes a cross-AZ line item for self-managed ES replication
**Fix:** Call this out as a savings the migration unlocks. Cross-AZ data transfer between **customer-owned resources** (e.g., app tier ↔ AOS endpoint, or NAT Gateway egress) is still billed normally.

## 22. AOS-managed gp3 storage is priced separately from raw EBS gp3

**Category:** COST_TCO

The exact AOS-managed gp3 list price (volume + baseline IOPS + service overhead) is published on the AOS pricing page, NOT the raw EBS rate. TCO calculators reusing raw EBS underestimate.

**Detect:** Customer-built TCO calculator uses raw EBS rates
**Fix:** Plug AOS-managed gp3 rate from `https://calculator.aws` into customer's TCO model. RI / Savings Plan / EDP discounts apply only there.

## 23. Cluster manager sizing scales with cluster size

**Category:** OPERATIONAL_CONSIDERATION

Architectural rule: 3 dedicated cluster managers (formerly "master node"), odd quorum. NEVER 1, 2, 4, or 5.

**Detect:** Cluster scaling beyond 30 nodes; shard count growth
**Fix:** For current cluster-manager sizing (heap-to-nodes / shard tier), see [`sizing.md` §Topology defaults](sizing.md).

## 24. Migration from Managed → Serverless requires reindex

**Category:** MIGRATION_SPECIFIC

There is NO automatic migration from Managed Domain to Serverless. Must reindex.

**Detect:** Customer wants "easy switch" from Managed to Serverless
**Fix:** Plan a reindex migration. Use Migration Assistant for Amazon OpenSearch Service or `_reindex` from remote. Validate sizing on Serverless before cutover.

## 25. Authentication complexity is the #1 setup blocker

**Category:** OPERATIONAL_CONSIDERATION

Forum data: 60%+ of new-user issues are auth-related. FGAC + IAM + Cognito + SAML + master-user combinations have many failure modes.

**Detect:** Any auth question; first-time AOS user
**Fix:** See [`security.md`](security.md) for the FGAC + IAM + Cognito + SAML decision tree. Common pattern:

- Internal users only → IAM SigV4 from app
- External / human users → Cognito user pool + FGAC mapped to Cognito groups
- Enterprise SSO → SAML to FGAC backend role mapping

## 26. ELSER is proprietary to Elastic — not on Amazon OpenSearch

**Category:** TRUE_BLOCKER

Don't promise ELSER on AOS. Use neural sparse search with SageMaker-hosted SPLADE/equivalent, or dense vectors via Bedrock Titan / Cohere.

**Detect:** Customer asks for ELSER on AOS
**Fix:** Recommend `neural_sparse` query with SageMaker-hosted sparse encoder, OR hybrid (BM25 + dense vectors). Most ELSER use cases work fine with hybrid.

## 27. Painless scripts not supported on Serverless

**Category:** TRUE_BLOCKER

Inline scripts work on Managed but not Serverless. If customer relies on `script_score`, `script_fields`, or update-by-script, they need Managed.

**Detect:** Customer mentions Painless / `script_score` / scripted fields with Serverless target
**Fix:** Move to Managed, OR rewrite scripted logic into ingest pipeline / search pipeline / function_score.

## 28. ES Runtime fields have only partial parity in OpenSearch

**Category:** TRUE_BLOCKER

OpenSearch added "derived fields" in 2.15 — limited functionality compared to ES Runtime fields. Not full parity.

**Detect:** ES source heavily uses Runtime fields; OS target
**Fix:** For each Runtime field, decide: (a) pre-compute at ingest, (b) use derived fields if simple, or (c) move logic to query-time scripted fields (Managed only).

## 29. ILM JSON does NOT import as ISM

**Category:** MIGRATION_SPECIFIC

Elasticsearch ILM and OpenSearch ISM are conceptually similar but JSON formats differ. Must rebuild policies.

**Detect:** Customer has many ILM policies and assumes they "just work" on OS
**Fix:** Translate each ILM policy to ISM. Common patterns: rollover, force_merge, warm/cold migration, delete. AWS-specific ISM operations: `warm_migration`, `cold_migration`, `cold_delete`.

## 30. AOS automated snapshots are NOT a backup strategy

**Category:** OPERATIONAL_CONSIDERATION

See #15 (canonical) — automated snapshots are kept only 14 days and are not a DR strategy.

**Detect:** Customer plans to "use automated snapshots for DR"
**Fix:** See #15. Set up manual snapshots to your own S3 bucket with appropriate retention; build a cross-region snapshot strategy if DR is in scope.

## 31. FAISS HNSW IS supported on Serverless Vector Search

**Category:** CLARIFICATION

Architectural rule: FAISS HNSW is the underlying engine on BOTH Serverless Vector Search collection types (NextGen and Classic). The difference is configurability, not support. Saying 'FAISS HNSW is unavailable on Serverless' is WRONG.

For the per-config breakdown of NextGen vs Classic Vector Search (which engines/parameters each surfaces, what pins a workload to Managed Domain), see [`vector-knn.md`](vector-knn.md).

**Detect:** Customer claims FAISS HNSW is unavailable on Serverless; vector workload routing decision
**Fix:** Affirm FAISS HNSW availability on both Serverless Vector Search variants. Use [`vector-knn.md`](vector-knn.md) to decide whether the workload pins to Managed Domain.

## 32. OS 1.x version line

**Category:** CLARIFICATION

There is **NO OS 1.7 GA release**. OS 1.x had GA releases up through 1.3. For the current canonical version list, see [version-migration.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/version-migration.html).

If a customer says 'OS 1.7' they likely mean:

- Elasticsearch 1.7 (different product, pre-fork era), OR
- Misremembered OS 1.3 (the latest 1.x), OR
- Confusion with a 2.x or 3.x version

Clarify before proceeding with upgrade plan.

**Detect:** Customer cites "OS 1.7" or any OS 1.x version above 1.3
**Fix:** Confirm the actual source version (ES 1.7 vs OS 1.3 vs OS 2.x/3.x) before scoping the upgrade. The Lucene-segment-format wall (#3) and other version-specific gotchas hinge on knowing the true source.
