# Sizing — full math, instance families, and operational thresholds

The summary version (default starting point + key knobs) is in `SKILL.md`. This file owns the full formulas, instance-family details, JVM/heap mechanics, k-NN memory math, OCU model, and edge-case tuning.

## Storage formula

```
min_storage = source_data × (1 + replicas) × (1 + indexing_overhead) / (1 - linux_reserved) / (1 - aos_overhead)
```

Defaults (from AWS `bp-storage.html`):

- `linux_reserved = 0.05` (Linux reserves 5% of file system for root)
- `aos_overhead = 0.20` capped at 20 GiB/instance (AOS reserves 20% up to 20 GiB)
- `indexing_overhead ≈ 0.10` (the index up to 10% of source data)

**Simplified rule**: `min_storage ≈ source_data × (1 + replicas) × 1.45`.

For >1 PB workloads, see `petabyte-scale.html`: 100 GiB shards on `OR1.16xlarge.search` / `i3.16xlarge.search`.

## Shard math

Source: `bp-sharding.html` and `bp.html`.

| Workload | Target shard size |
|---|---|
| Search workloads | 10–30 GiB |
| Logs / write-heavy | 30–50 GiB |
| Petabyte-scale on i3.16xl / OR1 | up to 100 GiB |

**Formulas:**

- `primary_shards = (source + room_to_grow) × 1.1 / desired_shard_size`, rounded up to multiple of data-node count
- `shards_per_node ≤ 25 × GiB_heap` — e.g., 32 GiB heap = max 800 shards/node
- `shard_to_cpu ≈ 1.5 vCPU / shard` (initial scale point)

**Per-node shard cap evolution:**

- ES 7.x and OS ≤ 2.15: 1000 shards/node
- OS ≥ 2.17: 1000 shards per 16 GiB JVM heap, up to 4000 shards/node max
- Multi-AZ-with-Standby: 1000 shards/node always (regardless of OS version)
- Cluster-wide cap (Multi-AZ-with-Standby): 75,000 shards total

## JVM heap

| Rule | Value | Source |
|---|---|---|
| Heap size | 50% of RAM, capped at 32 GiB | `auto-tune.html`, `cloudwatch-alarms.html` |
| Customer-tunable? | NO — set automatically per instance class | AWS doc |
| Compressed-oops ceiling | 32 GiB JVM limit | JVM behavior |
| Pressure write-block trigger | JVMMemoryPressure > 92% for 30 min | `handling-errors.html` |
| Pressure write-block release | JVMMemoryPressure ≤ 88% for 5 min | `handling-errors.html` |
| Steady-state target | < 80% | `bp.html` |

**Why 32 GiB ceiling:** Above ~32 GiB, JVM disables compressed object pointers (compressed oops), and pointer overhead doubles, eroding any RAM gains.

**Beyond 32 GiB RAM:** scale horizontally (more nodes), not vertically. The service supports up to 64 GiB RAM single-instance, then enforces horizontal scaling.

## Operational thresholds

- **Refresh interval**: default 1s. Recommend 30s+ for write-heavy workloads. (`bp.html`)
- **Bulk request size**: 3–5 MiB starting point. (`bp.html`)
- **Disk watermarks**: 85% / 90% / 95% (low / high / flood) — defaults per Elasticsearch / OpenSearch; index goes read-only at flood. See gotcha #18 for the read-only-block consequence and recovery.
  - More granular: cluster blocks writes when free storage drops below 20% OR 20 GiB (whichever is greater).
- **EBS burst balance**: notification when GP2 burst < 70%, follow-up at < 20%.
- **UltraWarm cost-effective threshold**: ~2.5 TiB hot data. (`bp.html`)
- **Snapshot retention**: AOS automated snapshots kept 14 days (hourly, up to 336). Manual snapshots bill against your S3 bucket at standard rates plus PUT costs.

## Topology defaults

> Terminology: this skill uses **cluster manager** (the modern OpenSearch name; formerly "master node" in pre-2.x ES / OS). AWS APIs and CLI flags retain the legacy spelling — e.g., `--dedicated-master-enabled`, `DedicatedMasterCount` in `aws opensearch create-domain` — and are quoted verbatim where they appear. Prose uses "cluster manager".

- **Cluster managers**: exactly 3 dedicated, in 3 AZs. Quorum requires odd count; 3 is the minimum that survives single-node failure. NEVER use 1, 2, 4, or 5.
- **Cluster manager sizing** (OS 2.17+):
  - 8 GiB cluster manager → up to 30 nodes / 15K shards
  - 32 GiB cluster manager → up to 120 nodes / 60K shards
  - 256 GiB cluster manager → up to 1002 nodes / 500K shards
- **Cluster managers required** when ≥ 3 data nodes OR ≥ 10 indexes.
- **Data nodes**: ≥ 2 minimum. Multi-AZ-with-Standby uses multiples of 3, with 2 replicas.
- **AZs**: 3 for prod (Multi-AZ; Multi-AZ-with-Standby is "available at no extra cost").
- **Replicas**: 1 default; 2 for high-availability search workloads; 0 only for ephemeral logs.

## Instance family selection (current generation)

**Default rule:** Graviton r-family (`r7g`/`r8g`) for memory-bound search, m-family (`m7g`/`m8g`) for cluster managers; OR1/OR2 for write-heavy logs only (write-once read-rare profile). Pick previous-gen (`r6g`/`r6gd`) only with explicit justification — existing RIs, specific compatibility need.

For the current list of supported instance types, EBS+Instance-Store profiles, regional availability, and the full denylist of families incompatible with VPC encryption-at-rest, see [supported-instance-types.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html). Do NOT replicate that list here — it changes quarterly.

**Stable architectural notes (sizing-relevant):**

- OR1/OR2/OM2/OI2 migration is **irreversible**; min refresh interval 10s; bulk size 10 MB recommended.
- Burstable (`t3.*`) is dev-only — CPU credits exhaust under sustained load.

**Common Graviton search-instance specs** (canonical RAM/vCPU; do NOT rederive — these are fixed):

| Instance | vCPU | RAM (GiB) | EBS bandwidth |
|---|---|---|---|
| `r7g.large.search` | 2 | 16 | up to 5 Gbps |
| `r7g.xlarge.search` | 4 | 32 | up to 5 Gbps |
| `r7g.2xlarge.search` | 8 | **64** | up to 10 Gbps |
| `r7g.4xlarge.search` | 16 | **128** | up to 12 Gbps |
| `r7g.8xlarge.search` | 32 | **256** | 12 Gbps |
| `r7g.12xlarge.search` | 48 | 384 | 20 Gbps |
| `m7g.medium.search` | 1 | 4 | up to 12.5 Gbps |
| `m7g.large.search` | 2 | 8 | up to 12.5 Gbps |
| `m7g.xlarge.search` | 4 | 16 | up to 12.5 Gbps |

When deriving cluster topology, look up the RAM from this table — do NOT estimate it (`r7g.2xlarge.search` has **64 GiB RAM**, not 16; `r7g.4xlarge.search` has 128 GiB, not 32). For instance families not listed (OR1, OR2, im4gn, etc.) verify against [supported-instance-types.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html).

### UltraWarm tier

- **`uw.medium` cannot host k-NN graphs** (lacks RAM headroom); use `ultrawarm1.large` for k-NN-on-warm.
- Read-only; promote to hot for writes. Storage charge: primary shards only (no replica overhead). Recommended max shard size: 50 GiB. Requires dedicated cluster manager nodes.
- For current SKUs and capacity per instance, see [ultrawarm.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ultrawarm.html).

## k-NN memory math

For FAISS HNSW float vectors with `m=16`:

```
bytes_per_vector ≈ 1.1 × (4 × dim + 8 × m)
total_memory ≈ bytes_per_vector × num_vectors × (1 + replicas)
```

### Quick reference

| Vectors | Dim | Memory (replicas=1) | Notes |
|---|---|---|---|
| 1M | 384 | ~3.5 GB | Small workload |
| 1M | 768 | ~6.7 GB | BERT-class |
| 10M | 768 | ~67 GB | Multi-node |
| 100M | 768 | ~670 GB | Multi-node + maybe PQ |
| 1M | 1536 | ~13.4 GB | OpenAI ada-002 |
| 10M | 1536 | ~134 GB | Multi-node |

**Native-index circuit breaker**: default 50% of non-heap RAM. Verify against current `knn-index/` doc for the exact percentage.

**Engine impact:**

- **Lucene engine**: lighter, integrates fully with OpenSearch query DSL, best for filtered queries
- **FAISS HNSW**: standard recall/latency trade-off, `m=16` typical
- **FAISS HNSW + PQ**: trade recall for ~4–32× memory savings
- **FAISS HNSW + scalar quantization (16-bit)**: 2× memory savings, minimal recall loss
- **FAISS IVF + PQ**: best for batch-rebuild workloads (e.g., nightly index)
- **`mode: "on_disk"`**: graphs paged from disk; lower memory pressure, higher latency

### k-NN UltraWarm constraints

- **NEVER use `uw.medium` for in-memory k-NN engines** — instance lacks RAM headroom for k-NN graphs
- Size so cumulative graph size of actively-searched shards ≤ `knn.memory.circuit_breaker.limit × 61 GiB` per `uw.large`
- k-NN indexes can migrate to UltraWarm/cold from OS 2.17+
- k-NN indexes do NOT force-merge to single segment during UltraWarm migration (keeps default 20 segments to avoid OOM)

### OS 3.0 vector improvements

OS 3.0 introduces GPU-accelerated index build, derived-source vectors (reduced storage + faster cold start), concurrent segment search default-on for k-NN, and star-tree indexing for aggregations. For sizing impact, treat these as memory/storage reductions — verify under load with OpenSearch Benchmark; do not rely on vendor multiplier claims for capacity planning.

## Serverless OCU sizing

### OCU model

- **1 OCU** = 6 GiB RAM + matching vCPU + ~120 GiB ephemeral storage
- Billing: per-second granularity, hourly rate
- Indexing OCUs scale separately from search OCUs

### Floors (NextGen and Classic)

| Configuration | Indexing floor | Search floor | Total billed |
|---|---|---|---|
| Redundancy ON (production default) | 1 OCU (0.5 × 2) | 1 OCU (0.5 × 2) | 4 × 0.5 OCU |
| Redundancy OFF (dev/test) | 0.5 OCU × 2 | 0.5 OCU × 2 | 2 × 0.5 OCU per workload type |

### Caps

For current OCU defaults and account-level caps, see [serverless-scaling.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html).

### Performance rules of thumb (skill IP — verify under load)

- 1 indexing OCU ≈ 100–200 MB/s sustained ingest
- 1 search OCU ≈ 50–200 simple QPS, 10–50 complex aggregations/sec

### Critical Vector Search caveat

Vector Search collections **CANNOT share OCUs** with Search or TimeSeries collections — even with the same KMS key. Adding one vector collection roughly **doubles** the idle floor. Project both floors via `https://calculator.aws`.

If vector is exploratory, prefer running k-NN on existing Managed cluster instead of provisioning a separate Serverless Vector collection.

## OpenSearch Ingestion (OSI) sizing

- 1 OSI OCU = 6 GiB RAM + corresponding vCPU
- Pricing: pay for OCUs allocated, regardless of data flow
- Provisions Data Prepper 2.x (auto-upgraded within the 2.x line)
- **Persistent buffering steals OCUs from your declared max**: 1:1 buffer-to-compute ratio. Raise `max_units` accordingly.
- Common sources: OTel Collector, Fluent Bit, S3, Kinesis, MSK
- All requests Sig v4 signed with `osis:Ingest` IAM permission

## Cross-AZ data transfer

- **Within an AOS cluster**: FREE (cluster manager / replica replication does NOT bill)
- **Between your VPC and AOS endpoint**: billed at standard regional rates
- **NAT Gateway** for plugins/Bedrock/external sources: $0.045/hr/AZ + $0.045/GB processed — use VPC endpoints for S3, Bedrock, STS to avoid

## EBS storage (gp3 vs gp2)

- gp3 is the default; ~9.6% cheaper than gp2
- gp3 decouples IOPS from volume size; provisioned IOPS billed separately
- **AOS-managed gp3 list price differs from raw EBS gp3** — TCO calculators reusing raw EBS rate underestimate. Plug into `https://calculator.aws`.

## Validate before cutover

Run **OpenSearch Benchmark** against the target cluster before cutover. The `big5` workload is the standard search benchmark. The `compare` mode produces a baseline-vs-contender diff.

## Manual snapshot S3 cost

- Automated snapshots: stored in AOS-preconfigured S3 bucket, NO additional charge, kept 14 days
- Manual / custom-retention / cross-region snapshots: stored in YOUR S3 bucket at standard S3 rates plus PUT charges

Sizing model addition: `data_size × retention_days / 30 × $/GB-mo` plus PUT cost.
