# Recipe — `SIZING_ONLY`

> Concrete instance class + node count + storage formula. Not a migration plan, not a full assessment, not a 9-section report. The user wants to know **what to provision** and **why** in as few words as possible.

## When to dispatch here

Use this recipe when the user asks one of:

- "What instance class should I use for X GB of data / Y QPS?"
- "We have N nodes of `r5.4xlarge` on self-managed — what's the AOS equivalent?"
- "Size this cluster for 200 GB of logs / 50M vectors at dim 768."
- "How many `r7g.large.search` do I need for 80 GB indexed?"
- "What's the right node count for `<workload>`?"

The hallmark: there is a workload to size, but **no migration question**, **no schema paste**, **no 'should I use OpenSearch'** framing. The user already chose AOS — they want a baseline today.

## Detection signals

| Signal | Example |
|---|---|
| Capacity ask without migration verbs | "size for", "provision for", "what should I run" |
| Specific scalar inputs | data volume in GB/TB, doc count, QPS, vector count + dim |
| Source cluster spec they want mapped | "we run 6 × `r5.2xlarge` today" |
| No `schema.xml`, no ES mapping, no "translate this query", no traffic-and-readiness mix | — |
| Vector-search collection sizing without ingestion-pipeline questions | "50M × 768 vectors" |

If the user pastes an `_cat/indices`, traffic numbers, AND asks for a migration plan → that is `FULL_ASSESSMENT`, **not** `SIZING_ONLY`. If they ask "Managed vs Serverless" → `COMPARATIVE_DECISION`. If they ask "should I even use OpenSearch for 200 MB of Postgres rows" → `ANTI_PATTERN_PUSHBACK`.

## Required output template

Produce **exactly** these four blocks. No headings beyond what is shown — keep the response tight.

### 1. Detected shape line (one sentence)

> *Detected shape: SIZING_ONLY — baseline for `<source_size>` `<workload_type>` on Amazon OpenSearch Service.*

### 2. Baseline (one sentence + bullets)

Lead with a single concrete recommendation:

> *Run **3 × `r7g.large.search`** data nodes + **3 × `m7g.large.search`** dedicated cluster managers across **3 AZs**, **1 replica**, EBS gp3 sized to **`<storage_number> GiB per data node`**.*

Then 3-5 bullets with numeric justification — instance choice rationale, replica setting, cluster-manager sizing rationale, storage rounding, AZ count.

### 3. Storage math (inline derivation)

ALWAYS show the formula and substitute numbers, even when inputs are estimated:

```
min_storage = source × (1 + replicas) × 1.45
            = 80 GiB × (1 + 1) × 1.45
            = 232 GiB total cluster storage
            ≈ 78 GiB per data node (3 nodes), round to 100 GiB gp3
```

If source data is unknown, present the **tiered band** instead (see below) — never invent a single number.

### 4. References (one line, max ~3 URLs)

> *References: [`bp-instances`](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html#bp-instances) · [`bp-sharding`](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html#bp-sharding) · <https://calculator.aws>.*

That's it. No other sections.

## Match-source rule (CRITICAL)

When the user names their existing self-managed/EC2 cluster, **match the source profile** instead of falling back to a greenfield baseline:

- 6 × `r5.2xlarge` self-managed → recommend 6 × `r7g.2xlarge.search` (Graviton equivalent), not "3 × `r7g.large` is our default."
- 4 × `m5.xlarge` self-managed → recommend 4 × `m7g.xlarge.search`.
- The customer has already proven their working set fits that RAM-to-data ratio. Downsize only if you can show the source was over-provisioned (e.g., JVMMemoryPressure consistently <40%).

Only fall back to "3 × `r7g.large.search`" greenfield baseline when the source size is **<100 GB AND** the user provided no source cluster.

## Tiered band sizing (UNKNOWN inputs)

When source size is not specified, do NOT guess. Present three bands and ask the user to confirm:

| Band | Source data | Suggested baseline | Notes |
|---|---|---|---|
| Small | <100 GiB | 3 × `r7g.large.search` data + 3 × `m7g.large.search` cluster manager, 1 replica, gp3 100 GiB/node | Smallest prod-credible footprint |
| Medium | 100–500 GiB | 3 × `r7g.xlarge.search` data + 3 × `m7g.large.search` cluster manager, 1 replica, gp3 sized via formula | Most common SMB workload |
| Large | >500 GiB | 6+ × `r7g.2xlarge.search` data + 3 × `m7g.large.search` cluster manager, OR1 if write-heavy logs | Consider OR1/UltraWarm tiering |

Always close the tiered version with: *"Confirm source size and I will collapse to one recommendation."*

## NOT REQUIRED — explicitly OMIT

Do NOT produce any of the following in a `SIZING_ONLY` answer:

- **Timeline & Resourcing — REMOVED FROM SUITE.** Never write "engineer-weeks", "Phase 1 / Phase 2", "T+0 / T+30 days", or any sequencing language.
- Executive Summary, Source Inventory, Target Topology, Migration Path, Readiness Checklist, Risk Register, Citations section, Open Questions.
- Migration verbs: "cutover", "Historical Data Migration", "snapshot", "_reindex from remote", "Migration Assistant for Amazon OpenSearch Service".
- Customer-specific trade-off narrative ("if your team prefers...", "if you have RIs in...").
- Cost discussion beyond the calculator.aws link. Never write "$X/month".
- JVM heap tuning advice (heap is service-managed; mention only in passing if the user asks).
- Schema conversion, query DSL examples, FGAC setup.
- Long instance-family compendium — pick one family and move on.

If the user asks for any of the above, route them: *"That's outside SIZING_ONLY — for migration path see FULL_ASSESSMENT, for cost open https://calculator.aws."*

## Worked exemplar (~250 words)

**User asks:** *"We have 80 GB of product-search data on a self-managed Elasticsearch 7.10 cluster running 4 × `r5.xlarge`. What should we run on AOS?"*

**Response:**

*Detected shape: SIZING_ONLY — baseline for 80 GiB product-search workload on Amazon OpenSearch Service, sized to match an existing 4 × `r5.xlarge` source.*

Run **4 × `r7g.xlarge.search`** data nodes + **3 × `m7g.large.search`** dedicated cluster managers across **3 AZs**, **1 replica**, EBS gp3 at **80 GiB per data node**.

- **Match-source:** the existing 4 × `r5.xlarge` already proves the working set fits that RAM-to-data ratio; mapping to Graviton (`r7g.xlarge.search`) preserves the profile and gains ~20% price/perf.
- **Master nodes:** required because data-node count ≥ 3; `m7g.large.search` × 3 covers up to 30 nodes / 15K shards on OS 2.17+ — well above this footprint.
- **Replicas = 1** (one primary copy + one replica); 3 AZs gives plain **Multi-AZ** (99.9% SLA). Multi-AZ-with-Standby (99.99% SLA) is NOT enabled here — it requires a multiple-of-3 data-node count and ≥ 2 replicas (see gotcha #19); this 4-node / 1-replica layout does not qualify. Re-shape to 3 (or 6) data nodes with 2 replicas if Standby is required.
- **Shards:** for a search workload, target 10–30 GiB per shard. 80 GiB / 20 GiB → 4 primary shards, aligned to data-node count. Final layout: 4 primary × 2 (1 replica) = 8 shards across 4 nodes.
- **Heap is service-managed** — sized automatically at 50% of RAM, capped at 32 GiB. Not a customer knob.

```
min_storage = source × (1 + replicas) × 1.45
            = 80 GiB × (1 + 1) × 1.45
            = 232 GiB cluster total
            ≈ 58 GiB per data node (4 nodes); round to 80 GiB gp3
```

*References: [`bp-instances`](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html#bp-instances) · [`bp-sharding`](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html#bp-sharding) · <https://calculator.aws>.*

## Pre-emit checklist (specific to SIZING_ONLY)

Tick every box before sending. If any box is unticked, fix the response — don't ship it.

- [ ] **First sentence is the shape declaration**, not a greeting, not a restatement of the question.
- [ ] **Baseline is one sentence** with instance class + count + AZ count + replica count + storage number.
- [ ] **Storage formula is shown with numbers substituted**, not just stated abstractly. Even if source size is a band, at least one band has the math worked.
- [ ] **Match-source rule applied** when user named their current cluster — Graviton equivalent of their current family at the same size, not a greenfield default.
- [ ] **Tiered bands used** (and only used) when source size is genuinely unknown.
- [ ] **Cluster managers explicitly addressed** — present when ≥3 data nodes or ≥10 indexes; called out as `m7g.large.search` × 3 (or larger per the cluster-manager-sizing table in `sizing.md`).
- [ ] **Current-generation Graviton** by default (`r7g`/`r8g` family). `r6g` only with explicit user justification.
- [ ] **No dollar figures.** Single calculator.aws link is the only cost reference.
- [ ] **No Timeline & Resourcing.** No "engineer-weeks", no phased rollout, no "T+N days".
- [ ] **No migration content.** No Historical Data Migration, snapshot, `_reindex.remote`, Migration Assistant for Amazon OpenSearch Service.
- [ ] **No 9-section scaffold.** No Executive Summary, no Risk Register, no Readiness Checklist.
- [ ] **References footer is one line** with at most three URLs (bp-instances, bp-sharding, calculator.aws).
- [ ] **Heap mentioned (if at all) as service-managed**, never as a customer-tunable knob.
- [ ] **Total response ≤ ~300 words** unless tiered bands forced expansion. If you wrote more, you drifted into FULL_ASSESSMENT — trim back.
