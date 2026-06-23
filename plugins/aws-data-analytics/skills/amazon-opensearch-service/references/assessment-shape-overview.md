# Shape recipe: OVERVIEW_REQUEST

## What this shape is

**OVERVIEW_REQUEST** is the response shape for "what's the path?" questions — the user wants a high-altitude tour of the migration journey, not a forensic 9-section assessment and not a technical intake form. They want to leave the response knowing **what phases happen, in what order, what the named tool is, and what the next concrete step is**.

This is the most-mis-shaped ask in the suite. The two failure modes to avoid:

1. **Bloat.** Producing a full FULL_ASSESSMENT (Executive Summary / Source / Target / Migration Path / Sizing / Readiness / Risks / Citations) when the user pasted no artifacts and asked one sentence. The response feels generic because every section has to invent its inputs.
2. **Intake stall.** Replying with a 6-question Business Stakeholder intake when the user actually wanted *substance*. "What's the path?" is a substantive request — answer it. Save intake questions for explicit Business Stakeholder framing ("I'm a director, what do you need from me?").

OVERVIEW_REQUEST sits between those two failure modes: a real, named, sequenced phase walk-through that any persona can read and act on, with one inline doc URL and one named gotcha so the user knows which rock to look under first.

## Detection signals

Trigger this shape when the prompt matches any of these without pasted artifacts:

- **Phase phrases:** "what's the path?", "high-level overview", "walk me through it", "what's involved?", "how does this work end to end", "give me the migration overview"
- **Generic source mention with no specifics:** "moving off Solr", "thinking about migrating from Elasticsearch", "we're on ES 7.x and want to look at OpenSearch" with no `schema.xml`, no `_cat/indices`, no doc count, no QPS
- **Stakeholder framing without intake invitation:** "what does it take to migrate?", "what's the journey?"

If the user pasted a `schema.xml`, `_cat/indices` output, doc counts, traffic numbers, or asked a specific operational question ("cheapest path", "smallest reindex window") — switch shape. SCHEMA_CONVERSION, FULL_ASSESSMENT, or FOCUSED_OPERATIONAL is correct, not OVERVIEW_REQUEST.

If the user explicitly says "I'm a product manager / director / TPM" AND asks "what do you need from me?", switch to the Business Stakeholder six-question intake — that's a different output and lives outside the case-shape suite.

## Required output template

The response must contain, in order:

### 1. Source restatement (1–2 sentences, mandatory)

Restate what the user said: source engine, version (or "version unspecified"), target. Example:

> Solr 8.11 SolrCloud → Amazon OpenSearch Service. Here's the path at a glance — four phases, primary tool is Migration Assistant for Amazon OpenSearch Service Historical Data Migration.

### 2. Three to four named, sequenced phases

Each phase needs:

- **A name** (Discovery / Schema & Query Translation / Backfill / Cutover, or similar — see exemplar)
- **One paragraph (1–3 sentences)** of what happens in it
- **The named tool** if one applies in that phase (`_reindex.remote`, Migration Assistant for Amazon OpenSearch Service Historical Data Migration, Migration Assistant for Amazon OpenSearch Service Live Traffic Migration, OSI, in-place blue/green)

Three phases is the floor. Four is typical. Five+ means you're drifting into FULL_ASSESSMENT — stop.

### 3. One named migration specific or risk

Pick the single highest-impact item for this source engine and call it out by name. Frame it as a **migration specific** when the item has a clean, prescribed remediation that the migration plan already includes (`q.op=AND` translation, `fielddata` strip, etc.) — *"this is how the migration handles X"*. Frame it as a **risk** only when there is no known fix, when it constrains the target choice, or when it gates capacity / decisions late in the path (Lucene 8 → 10 segment wall, custom JARs not supported on Serverless NextGen, etc.). Examples:

- Solr → OpenSearch (migration specific): `q.op=AND` operator divergence — when the source `solrconfig.xml` sets `q.op=AND`, OpenSearch's `query_string` defaults to OR, so set `default_operator: AND` on every translated handler (top cause of result divergence in Solr migrations).
- Cite ONE relevant gotcha by number from `assessment-gotchas.md` (see #2 fork rule, #3 Lucene segment wall, #10 NMSLIB removal, #32 OS 1.x version trap).

**Special rule — when the target is OS 3.x crossing from any 1.x or 2.x source:** the named gotcha MUST be the **Lucene 8 → 10 segment wall** — phrase it as *"Lucene 10 cannot read Lucene 8 segments — segment format is forward-only, so every pre-2.x index must be reindexed before reaching 3.x"*. Add a one-line tail naming **at least one other OS 3.x breaking change**: JDK 21 minimum runtime, Security Manager → Java agent plugin migration, NMSLIB removal (forces FAISS reindex), or renamed k-NN settings. A 2-sentence callout is sufficient — but both items are required on 1.x→3.x or 2.x→3.x crossings.

### 4. One inline AWS doc URL

A single link in the body, near the closing sentence — NOT a Citations section. Pick the canonical entry point for the migration tool you named:

- Migration Assistant for Amazon OpenSearch Service (any source): `https://docs.aws.amazon.com/opensearch-service/latest/developerguide/migration-assistant.html`
- `_reindex` from remote: `https://docs.aws.amazon.com/opensearch-service/latest/developerguide/remote-reindex.html`
- In-place upgrade: `https://docs.aws.amazon.com/opensearch-service/latest/developerguide/version-migration.html`

### 5. Clear next step

End with one sentence telling the user the most useful concrete thing they can do next: typically *share the artifact that lets us go from generic to specific*. Examples:

- "Share your `schema.xml` and a `_cat/indices?v` dump and I'll produce a field-by-field mapping plus sizing."
- "Spin up Migration Assistant for Amazon OpenSearch Service on a non-prod target and run Historical Data Migration against a single low-stakes index first."
- "Confirm your ES version (`GET /` against the cluster) — the path forks hard at 7.11."

## NOT REQUIRED — explicitly omit

Do **not** include the following in an OVERVIEW_REQUEST response:

- **Timeline & Resourcing** — *removed from the suite entirely*. No "8–12 engineer-weeks", no "Phase 1: 2 weeks", no resourcing language anywhere.
- **9-section structure** (Source / Target / Migration Path / Sizing / Readiness / Risks / Timeline / Citations / Executive Summary). That's FULL_ASSESSMENT.
- **Readiness score** (the 0–100 / GREEN-YELLOW-RED tier). Save for FULL_ASSESSMENT.
- **Citations section.** One inline URL is the rule — no References block.
- **Sizing math** (instance class, shard count, storage formulas). Save for SIZING_ONLY or FULL_ASSESSMENT.
- **Math derivations** (heap math, segment math, watermark calculations).
- **Customer-specific trade-offs.** Without artifacts you don't have the inputs — stay path-generic. *Don't* invent "your 6-node cluster will need…".
- **Six-question Business Stakeholder intake.** That's a different shape.
- **Gap register tables** (BLOCKING / HIGH / MEDIUM / LOW). FULL_ASSESSMENT only.

## Worked exemplar — Solr 8.11 → Amazon OpenSearch

**Prompt:** *"We're running SolrCloud 8.11 and starting to look at moving to Amazon OpenSearch. What's the path?"*

**Response:**

> Detected shape: OVERVIEW_REQUEST. Solr 8.11 SolrCloud → Amazon OpenSearch Service — four named phases, primary tool is **Migration Assistant for Amazon OpenSearch Service Historical Data Migration (Migration Assistant for Amazon OpenSearch Service Historical Data Migration)**. Solr → OpenSearch is a refactor, not a lift-and-shift: schema, queries, and configs all need translation. There is no segment-level path between Solr and OpenSearch.
>
> **Phase 1 — Discovery & schema translation.** Inventory your collections, `schema.xml`, `solrconfig.xml`, and the queries your application sends. Translate `<field>` definitions into an OpenSearch mapping (`StrField` → `keyword`, `TextField` → `text` with the matching analyzer, `<copyField>` → `"copy_to"`, `<uniqueKey>` → bind to `_id` on `_bulk` and map as `keyword`). This is design work — no data moves yet.
>
> **Phase 2 — Query translation & shadow validation.** Convert eDisMax/standard handlers to OpenSearch DSL: `qf field^boost` → `multi_match type: best_fields`, `mm` passes UNCHANGED as `minimum_should_match`. Stand up an empty target domain and replay a representative query set against both engines. Compare top-K results before any cutover plan is locked in.
>
> **Phase 3 — Backfill with Migration Assistant for Amazon OpenSearch Service Historical Data Migration, cut over with Migration Assistant for Amazon OpenSearch Service Live Traffic Migration.** Solr → OpenSearch: target must be OS 3.x or Serverless (architectural rule). Tool eligibility per current Migration Assistant for Amazon OpenSearch Service versions: [source-and-target-versions](https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/source-and-target-versions.html). Take a Solr backup to S3, point Migration Assistant for Amazon OpenSearch Service at the snapshot for Historical Data Migration, then enable Live Traffic Migration for the cutover window.
>
> **Phase 4 — Cutover & decommission.** Final delta backfill (rerun Historical Data Migration over the most recent shard of changes), DNS/app-config flip to the OpenSearch endpoint, monitor for 1–2 release cycles, then retire the Solr cluster.
>
> **Top migration note:** Many Solr deployments configure `q.op=AND` (Solr's own default is OR, but the AND override is common in production). OpenSearch's `query_string` defaults to OR. If your source uses `q.op=AND`, set `default_operator: AND` on every translated query handler — otherwise relevance regresses dramatically. This is the #1 cause of result divergence in Solr → OpenSearch migrations. See the Migration Assistant for Amazon OpenSearch Service docs at <https://docs.aws.amazon.com/opensearch-service/latest/developerguide/migration-assistant.html>.
>
> **Next step:** share your `schema.xml` and a sample of the queries your app issues (top 10 by volume is enough). With those I can produce a field-by-field mapping and a query-translation reference so Phases 1 and 2 are fully concrete.

That's ~340 words and hits every required slot: source restated, four named phases with the tool, one gotcha named, one inline URL, one concrete next step. No timeline. No sizing math. No citations section. No 9-section scaffold.

## Pre-emit checklist (OVERVIEW_REQUEST-specific)

Tick every box before sending. If any fails, revise — do not ship.

- [ ] First sentence restates source engine + version (or "version unspecified") + target.
- [ ] Detected shape stated explicitly (`Detected shape: OVERVIEW_REQUEST.`).
- [ ] Exactly 3 or 4 named phases (not 2, not 5+). Each has a noun-phrase name, not just "Step 1".
- [ ] Each phase names the tool used in it (or explicitly says "design work, no data moves").
- [ ] Exactly one named gotcha appears, sourced from the always-true facts in `SKILL.md`.
- [ ] Exactly one inline AWS doc URL — and there is **NO Citations section**.
- [ ] Final paragraph ends with a concrete next step (typically: ask for the artifact that unlocks the next shape).
- [ ] **NO Timeline & Resourcing.** Search the response for "week", "month", "engineer-week", "sprint", "timeline", "resourcing" — if any appear, delete them.
- [ ] **NO sizing math.** Search for instance class names (`r7g`, `m7g`), shard counts, GB/heap math — if any appear, you've drifted into SIZING_ONLY.
- [ ] **NO readiness score / tier color.** Search for "GREEN", "YELLOW", "RED", "/100" — delete if present.
- [ ] **NO 9-section scaffold.** If your response has headings like "Executive Summary" / "Risks" / "Citations" — you're in the wrong shape; delete or switch to FULL_ASSESSMENT.
- [ ] No dollar figures anywhere (universal rule).
- [ ] No marketing words: "seamless", "robust", "best-in-class", "production-hardened", "enterprise-grade".
- [ ] Total length 200–500 words. If you're over 600, you've drifted toward FULL_ASSESSMENT — trim.
