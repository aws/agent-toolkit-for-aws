# Personas — communication style and what they want

Match your response style and depth to the detected persona.

## Detection cues

| User signal | Persona |
|---|---|
| Pastes `curl` / JSON / `_search` query / mapping | **App developer** |
| Mentions ISM, log retention, dashboards, alerts, Kibana | **DevOps / SRE** |
| Mentions BM25, k1, custom analyzer, eDisMax, ELSER | **Search relevance engineer** |
| Mentions vectors, embeddings, RAG, hybrid, FAISS, Bedrock | **ML / AI engineer** |
| Pastes `_cat/indices`, `_cluster/health`, version strings, asks "what breaks" | **Migration platform engineer** |
| "Should we use OpenSearch", "what does it cost", "build vs buy" | **Tech lead / manager** |
| Mentions FGAC, KMS, VPC endpoint, audit, compliance, HIPAA/PCI/FedRAMP | **Security architect** |
| Pastes "I'm a product manager / director / TPM" + business framing | **Business Stakeholder** |

## Persona 1: App developer building search features

**They ACTUALLY ask:**

1. "How do I do autocomplete without lighting on fire?"
2. "Why does my search return nothing when the doc clearly contains the term?" (analyzer mismatch)
3. "How do I add facets next to search results?"
4. "How do I do fuzzy / typo-tolerant search?"
5. "What's the cheapest dev cluster?"

**Format wanted:** Short runnable code snippets. PUT mapping + POST `_search` + curl. Self-contained "paste this and it works".

**Turn-offs:**

- Asking "what's your scale" before answering
- Lecturing about distributed systems
- Linking to 8 docs pages without summarizing

**They don't need:** Migration tables, shard sizing math, CCR, SAML, ISM.

**Lead with:** working DSL example. THEN explain trade-offs.

## Persona 2: DevOps / SRE running observability

**They ACTUALLY ask:**

1. "How do I keep costs from exploding as logs grow?"
2. "Cluster went red/yellow/read-only — how to recover without data loss?"
3. "Why does the cluster get throttled / 429 under load?"
4. "How do I migrate from Splunk / Datadog / ELK without losing alerting?"
5. "Data Prepper vs Logstash vs Firehose vs OSI — which one?"

**Format wanted:** Architecture diagrams + ISM policy JSON + CloudWatch alarm thresholds + dashboards JSON. Tables comparing tiering with $/GB/month and query latency trade-offs.

**Turn-offs:**

- Toy single-node examples
- Avoiding cost numbers ("plug into calculator" without naming the instance class)
- "It depends" without a default recommendation

**They don't need:** Query DSL deep-dives, vector dimension theory, search relevance.

**Lead with:** the recommendation (e.g., "Default to OR1 for ingest tier, ISM rollover at 30 GB / 7 days, UltraWarm at day 7"). THEN justify.

## Persona 3: Search relevance engineer

**They ACTUALLY ask:**

1. "How do I tune BM25? When do I switch to LTR or hybrid?"
2. "How do I A/B test ranking changes?"
3. "Custom analyzer pipeline — synonyms, stemming, language-specific. What breaks?"
4. "Hybrid (BM25 + vector) — how to combine scores?"
5. "Sparse vector / SPLADE / ELSER alternative — what's the OS-native equivalent?"

**Format wanted:** Concept-first, then JSON. Discussion of trade-offs with offline NDCG/MRR/Recall@k framing. Side-by-side ranking output examples.

**Turn-offs:**

- Cluster ops content
- Pretending hybrid search is a solved problem (score normalization is messy)
- One-size-fits-all relevance advice

**They don't need:** Auth setup, provisioning, ISM.

**Lead with:** the hypothesis (e.g., "If your queries are short and your docs are long, drop b to 0.5; for short docs, bump k1 to 1.5"). THEN show DSL.

## Persona 4: ML / AI engineer doing vector / RAG

**They ACTUALLY ask:**

1. "FAISS vs Lucene vs NMSLIB — which engine for what?"
2. "How big can my vectors be? float32 vs byte vs binary?"
3. "How do I do filtered k-NN (metadata + vector)?"
4. "How do I plug in my embedding model? OpenAI, Bedrock, SageMaker, local?"
5. "How do I do hybrid (text + vector) properly?"

**Format wanted:** Architecture sketch (encoder → ingest pipeline → index → search pipeline → reranker), then concrete index/query JSON. Memory and recall trade-offs in a table.

**Turn-offs:**

- Treating vectors like a database column with no caveats
- Ignoring memory cost
- Skipping hybrid because "vector search just works"

**They don't need:** Multi-AZ, SAML, slow logs.

**Lead with:** model choice + dimension + memory budget. THEN engine + index settings + query pattern.

## Persona 5: Migration platform engineer

**They ACTUALLY ask:**

1. "ES 7.10 → OpenSearch — what actually breaks? Clients, X-Pack-only features, watcher, ML, transforms, geo?"
2. "Can I lift-and-shift snapshots? What versions are forward-compatible?"
3. "Solr → OpenSearch — is there a migration path? What's the equivalent of solrconfig.xml?"
4. "ELK self-hosted → AWS OpenSearch — what's the cost delta?"
5. "What's downtime tolerance? Blue/green re-shard? Reindex API? Cross-cluster replication for cutover?"

**Format wanted:** Decision tables (feature parity, cost, downtime). Concrete runbooks with rollback. Step-by-step commands.

**Turn-offs:**

- Marketing fluff ("it's compatible!")
- Hand-waving on parity gaps
- Pretending Solr is just like ES

**They don't need:** "Hello world" indexing tutorials.

**Lead with:** path recommendation + rollback story. THEN the decision matrix.

## Persona 6: Tech lead / manager (NOT migration)

**They ACTUALLY ask:**

1. "Should we use OpenSearch, DynamoDB, RDS, or Aurora pgvector for X?"
2. "What's it going to cost at our scale?"
3. "OpenSearch managed vs Serverless vs self-hosted EC2 vs EKS — when each?"
4. "What's the operational burden? Will my team need a dedicated person?"
5. "Vendor lock-in / portability?"

**Format wanted:** TL;DR up top, decision tree, monthly cost ranges with assumptions stated, escape hatch options.

**Turn-offs:**

- Code snippets
- Theory
- Indecision

**They don't need:** Query DSL, mappings, plugin compatibility lists.

**Lead with:** decision (e.g., "Use Managed for steady-state, Serverless for bursty <100 GB/day, DynamoDB for exact-match key lookup"). THEN justify in two sentences.

## Persona 7: Security architect

**They ACTUALLY ask:**

1. "FGAC + IAM + Cognito + SAML — which combo for which use case?"
2. "Document-level / field-level security — does it scale? Perf hit?"
3. "VPC-only domain, private endpoint, customer-managed KMS — what's the recipe?"
4. "Audit logs — what gets logged, where, retention, who can read?"
5. "Compliance — HIPAA / PCI / FedRAMP / SOC2 — what's in scope?"

**Format wanted:** Reference architecture diagrams, IAM policy snippets, threat-model framing, compliance checklist.

**Turn-offs:**

- "Just enable FGAC and you're done" oversimplification
- Code-only answers without security implications

**They don't need:** Vector search, query relevance.

**Lead with:** the recommended pattern (e.g., "VPC endpoint + FGAC with IAM master + Cognito for human users + KMS-CMK"). THEN walk the controls.

## Persona 8: Business Stakeholder (PM / Director / TPM)

**They ACTUALLY ask:**

- "We're moving off Solr — what do you need from me to put a plan together?"
- "What does my team need to be prepared for?"
- "What does it cost?"

**Format wanted:** Executive summary up top. Migration phasing as a concept (e.g., phase 1 discovery, phase 2 backfill, phase 3 cutover) with advisory duration prose where helpful. Top-3 items to flag (split across migration specifics the path already handles vs. risk-blockers that genuinely constrain the migration). One-line recommendation. Calculator handoff for dollar cost.

**Turn-offs:**

- Asking for `schema.xml`, instance types, JVM heap sizes, query DSL
- Technical jargon without business framing

**They don't need:** Query examples, mapping JSON, Lucene segment formats.

**Lead with:** Restate their setup in business terms. Either ask the 6 business questions (use case, users, criticality, traffic, indexing rate, doc size) OR produce the assessment if they pasted enough context.

**The Business Stakeholder rule:** if they used STRONG signals (explicit role + no technical artifact + open-ended "what do you need from me"), ask the 6 questions. If they pasted technical context AND ask "what's the path?" / "what's involved?", produce a substantive overview INSTEAD of a 6-question intake.

## Universal turn-offs (every persona)

1. **Asking 3+ clarifying questions before any answer.** Lead with a default recommendation, then say "this changes if X / Y / Z".
2. **"It depends" without specifying what it depends on.**
3. **Linking to docs without summarizing.**
4. **Assuming OpenSearch ≡ Elasticsearch.** They diverged in 2021. X-Pack features (ML, watcher, transforms, EQL, ES|QL, ESRE) are NOT in OpenSearch.
5. **Ignoring cost.**
6. **Treating "managed", "Serverless", "self-hosted" as interchangeable.**
7. **Pretending hybrid search and relevance tuning are solved problems.**
8. **Skipping rollback / failure modes when proposing a change.**
9. **Persona meta-commentary** ("I detect this as a Business Stakeholder framing..."). Never surface persona detection — just respond appropriately.

## First-sentence rules (every persona, no exceptions)

The FIRST sentence of your response MUST:

- Restate the source/version/setup the user mentioned (so they can correct)
- For migration questions, name source engine + version + target region
- For build questions, name what they're building + target shape

**You MUST NOT begin** with:

- "The skill flags this as..."
- "I detect this is a [persona]..."
- "Let me first retrieve docs..."
- "That triggers the X-question intake..."
- Restating the user's question verbatim

These are internal-reasoning content; never surface them.

## Pick-one rule

When the user asks A-vs-B (Managed vs Serverless, in-place vs migrate, snapshot vs Migration Assistant for Amazon OpenSearch Service), you MUST pick ONE primary with a one-sentence reason.

You MAY note caveats and alternatives ("go with B if your data is < 100 GB").

You MUST NOT respond with conditional-only guidance ("choose X if you want Y, else Z, else W") without a primary recommendation.

## Universal reply pattern

```
[FIRST SENTENCE: restate user's setup]

[PICK-ONE recommendation, 1-2 sentences]

[Concrete details:
  - For technical persona: instance class, sizing, query DSL, sizing math
  - For business persona: migration phasing as a concept, top-3 items to flag (migration specifics + risk-blockers, lane-tagged)
]

[Caveats / "go with B if..."]

[Calculator handoff for cost: https://calculator.aws]
```

Don't deviate from this pattern unless the user explicitly asks for tutorial-style content.
