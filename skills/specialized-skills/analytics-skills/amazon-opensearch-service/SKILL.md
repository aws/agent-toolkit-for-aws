---
name: amazon-opensearch-service
description: Amazon OpenSearch Service and Serverless across five capabilities — migration (Solr/ES/self-managed OpenSearch into AOS/AOSS, schema/query translation, sizing, cutover); provisioning (domain + AOSS lifecycle, upgrades, storage tiers, FGAC, monitoring); search (vector / semantic / hybrid / RAG with Bedrock connectors); log-analytics (PPL, OSI ingestion, anomaly detection, OpenSearch Dashboards, Splunk/Datadog alternatives); trace-analytics (OTel spans, service maps, Data Prepper). Triggers on OpenSearch, AOS, AOSS, Elasticsearch, ELK, Solr, Lucene, vector / k-NN / semantic / hybrid / neural search, RAG, ELSER, log analytics, observability, Kibana, OSI, OCU, PPL, trace analytics, BM25, eDisMax, schema.xml, ILM, ISM, FAISS, HNSW, Migration Assistant for Amazon OpenSearch Service, Historical Data Migration, Live Traffic Migration, UltraWarm, OR1, Splunk/Datadog alternative, moving off Solr. Picks ONE capability per ask, names instance class + count + shard math, ships query DSL examples.
version: 1
---

# Amazon OpenSearch Service — the unified skill

This skill answers anything about Amazon OpenSearch Service or Serverless across five capabilities. **Step 0 below routes the question to ONE capability** and points at that capability's entry-point reference. Everything else — when to dispatch, sub-references, capability-specific facts, cross-capability links — lives in the entry-point reference for that capability.

> **AWS MCP server is recommended, not required.** Capability references show standard AWS CLI commands as the primary syntax (e.g., `aws opensearch describe-domain`, `aws opensearchserverless create-collection`). Where the AWS MCP server is available, its `call_aws` tool offers a streamlined alternative — but every operation in this skill MUST work via the AWS CLI alone. Data-plane HTTP calls against AOS / AOSS use `awscurl` for SigV4-signed requests; this works in both contexts.

## Step 0: detect the capability — first thing you do

Pick **one** of the five capabilities below. State the detected capability in your first sentence (e.g., *"Detected capability: SEARCH — semantic search setup with Bedrock embeddings."*). Then load the entry-point reference; that file describes when to dispatch, indexes the rest of the capability's files, and routes you to the next step.

| Capability | Entry-point reference |
|---|---|
| **migration** — Solr / Elasticsearch / self-managed OpenSearch into AOS or AOSS. Schema/query translation, sizing, cutover. | [`references/assessment-workflow.md`](references/assessment-workflow.md) |
| **provisioning** — Provisioning and managing AOS domains and AOSS collections. Lifecycle, upgrades, storage tiers, FGAC, monitoring. | [`references/provisioning-reference.md`](references/provisioning-reference.md) |
| **search** — Vector / semantic / hybrid / sparse / dense / RAG retrieval. Bedrock connectors, FAISS HNSW vs Lucene. | [`references/search-semantic-search-guide.md`](references/search-semantic-search-guide.md) |
| **log-analytics** — Log search, observability, PPL, OSI ingestion, anomaly detection, OpenSearch Dashboards. Splunk/Datadog/ELK alternatives. | [`references/log-analytics-guide.md`](references/log-analytics-guide.md) |
| **trace-analytics** — Distributed traces with OpenTelemetry. Span queries, service maps, Data Prepper. | [`references/trace-analytics-trace-queries.md`](references/trace-analytics-trace-queries.md) |

If a prompt spans capabilities (e.g., *"migrate from Solr AND set up RAG on the new domain"*), pick the dominant capability for the response and close with a one-line handoff to the other capability's entry-point ref.

## Universal rules (apply to ALL capabilities)

These rules apply to every response, regardless of capability. Capability-specific rules (sizing math, shape detection, Migration Assistant for Amazon OpenSearch Service capability matrix, k-NN engine selection) live in the entry-point references, not here.

- **Report header (every multi-section response).** Begin every multi-section response with a single fenced metadata block: `> Generated: <ISO 8601 timestamp> | Skill: amazon-opensearch-service v<N>`. Get the time by calling the `current_time` tool (returns ISO 8601 in UTC). Read the skill version from this file's frontmatter `version:` field. For one-line answers (terse FOCUSED_OPERATIONAL replies, anti-pattern refusals) the header is optional; for any multi-section deliverable it is REQUIRED. Place it immediately after the report title and before the first `##` heading.
- **No dollar estimates** (HARD CONSTRAINT). Never produce `$X/month`, `~$1,500`, or any dollar figure. Route every cost question to <https://calculator.aws> and stop. If a sub-reference contains dollar figures, treat them as informational context only and do NOT pass them through to the user.
- **No credential leakage** (HARD CONSTRAINT). Never include master usernames, KMS key ARNs, VPC endpoint URLs, instance IPs, or account IDs in generated output.
- **Pick one** for every A-vs-B decision. Name a primary recommendation in one line with a one-sentence reason. A *"go with B if..."* caveat is allowed AFTER the primary; never lead with conditional-only guidance.
- **Source restatement.** The first 2–3 sentences must restate the source (engine + version + scale) when known, or restate the customer's question in concrete terms. The very first text the user sees must NOT be tool narration, meta-commentary, the report title, or simply restating the question verbatim.
- **No marketing tone.** Do NOT use *"seamless"*, *"robust"*, *"best-in-class"*, *"production-hardened"*, *"enterprise-grade"*, *"world-class"*, *"cleanly"*, *"elegant"*. Do NOT stack 3+ vague hedges (*"typically"*, *"generally"*, *"usually"*, *"in most cases"*) in a single recommendation — be specific about when it does and does not apply.
- **Cross-capability handoff.** When a user prompt spans capabilities (e.g., *"migrate from Solr AND set up RAG on the new domain"*), pick the dominant capability for the response, then close with a one-line handoff: *"For \<other capability\>, see [`references/<other-capability>-<entry>.md`](...)."*

## Cross-cutting references (used across multiple capabilities)

These references are not capability-prefixed because they apply across capabilities. Capability entry-point references load them when relevant; SKILL.md never loads them directly.

- [`references/sizing.md`](references/sizing.md) — sizing math, instance family details, OR1 trade-offs, watermarks, JVM heap rules.
- [`references/vector-knn.md`](references/vector-knn.md) — k-NN engines, memory math, RAG ingestion patterns, ELSER alternatives.
- [`references/observability.md`](references/observability.md) — log analytics patterns, ISM, UltraWarm/Cold tiering, Splunk/Datadog migration playbooks.
- [`references/security.md`](references/security.md) — FGAC, encryption, VPC patterns, audit logs, compliance posture.
- [`references/personas.md`](references/personas.md) — communication style per persona.
- [`references/assessment-gotchas.md`](references/assessment-gotchas.md) — production gotcha catalog (cite by number in Migration specifics or Risks/blockers tables; each gotcha carries a `Category:` tag that determines its lane).
- [`references/assessment-knowledge-retrieval.md`](references/assessment-knowledge-retrieval.md) — topic → tool → URL recipe for batched verification.

Assets (`assets/`): report templates for FULL_ASSESSMENT renderings (Solr-source, ES-source, executive summary).

## What this skill does NOT do

- **Estimate dollar costs.** Pricing changes monthly and account-specific (RI, Savings Plan, EDP) discount math is outside this skill's reliable scope. Use <https://calculator.aws>.
- **Move data.** Use Migration Assistant for Amazon OpenSearch Service (Historical Data Migration for backfill, Live Traffic Migration for live cutover).
- **Build embedding models.** Use Amazon Bedrock or SageMaker.
- **Replace Splunk SPL or Datadog APM 1:1.** Some queries / detectors / dashboards need rewriting.
- **Tune relevance for a specific catalog.** Use OpenSearch Benchmark `big5` workload + your own judgment list.
