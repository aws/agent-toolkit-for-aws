# Shape recipe: FULL_ASSESSMENT

> Loaded by `SKILL.md` Step 0 when the prompt is rich enough to warrant a structured assessment report.

## What this shape is

A full migration / adoption assessment with 9 named sections, a numeric readiness score (0–100, GREEN/YELLOW/RED), inline math derivations, ≥3 timestamped citations, ≥2 named gotchas, and a Next Steps handoff (concrete pointers to other skills, CLI commands, AWS docs, and the Pricing Calculator). Output is the longest of any shape in this skill — typically 800–2,000 words depending on artifact density. The customer is asking for something they could hand to a director, an architect, or a steering committee; not a one-liner.

This shape **does not** include Timeline & Resourcing (engineer-weeks, calendar weeks, or "phase 1 = 2 weeks"). That section was removed from the suite — see NOT REQUIRED below. Cost estimates are also omitted; route to <https://calculator.aws>.

## When to dispatch here (detection signals)

Pick this shape when ≥2 of the following are true. If only ONE is true, prefer a more focused shape (`focused-operational`, `schema-conversion`, `sizing-only`).

**Strong signals (any one is sufficient):**

- Phrases: *"produce an assessment"*, *"give me a full assessment"*, *"complete migration plan"*, *"end-to-end report"*, *"write up a recommendation"*, *"prepare a doc for my director / architect / VP"*.
- Customer pasted ≥2 substantial artifacts: `schema.xml` + `solrconfig.xml`, `_cat/indices` + `_cluster/health` + `_nodes/stats`, or any combination of ≥40 lines of structured config.
- Customer specifies workload context AND constraints AND a goal in the same prompt (e.g., *"30 indexes, 4 TB, 8k QPS peak, GDPR, must finish before Q3, recommend the path"*).

**Weaker signals (need a second one):**

- Mention of source engine + version + region + scale numbers (docs / GB / QPS).
- Multiple personas implied (*"for our DevOps and search-relevance teams"*).
- Mention of compliance, SLA, or audit context (HIPAA, PCI, SOC2, FedRAMP, GDPR, multi-region DR).
- Explicit ask for a readiness score, risk register, or gap analysis.

**Counter-signals (do NOT dispatch here):**

- Question fits in one sentence with no artifacts → `overview` or `focused-operational`.
- Single artifact, single ask (e.g., *"map this schema"*) → `schema-conversion`.
- Pure A-vs-B decision → `comparative-decision`.
- Wrong-fit migration (Postgres + transactional + small) → `anti-pattern-pushback`.

## Required output template

Begin with the report title (`# Migration Assessment: <name>`), then a single fenced **metadata header** showing the generated time and skill version, then the 9 sections.

### Header (mandatory — placed immediately after title, before §1)

Call the `current_time` tool (returns ISO 8601 UTC) and read the skill version from the `version:` field in `SKILL.md` frontmatter. Emit:

```
> Generated: 2026-06-02T16:45:30Z | Skill: amazon-opensearch-service v1
```

If the `current_time` tool is unavailable, fall back to a placeholder `<UTC ISO 8601>` and call this out — never invent a timestamp.

### 9 sections

Produce these 9 sections, in this order, with these names. Each section header is a level-2 heading (`##`).

### 1. Executive Summary (3–5 bullets, ~80 words)

- Source restatement (engine + version + scale) — first sentence.
- Recommended target shape (Managed vs Serverless NextGen vs Classic) + recommended migration tool.
- Readiness score with tier: e.g., **`74/100 — YELLOW`**.
- One named risk-blocker or top migration specific (cite gotcha # if applicable).
- Pricing handoff line: *"plug sizing into <https://calculator.aws> for monthly cost"*.

### 2. Source

A 4–8-row table: engine, version, post-fork status, total docs, total GB, index count, plugin/custom-lib count, fork-rule applicability. Mark UNKNOWN explicitly — do NOT invent values. If artifact density is rich, include a collapsible JSON fingerprint.

### 3. Target

Recommended deployment: Managed Multi-AZ-with-Standby / Managed Multi-AZ / Serverless NextGen / Serverless Classic. State the **decision driver** (e.g., *"Multi-AZ-with-Standby because 99.95% SLA was named"*, *"Serverless NextGen because <100 GB vector workload with bursty traffic"*). Name the engine version target (OS 2.19 or OS 3.x) and the upgrade-path implication.

### 4. Migration Path

Frame the migration around the **3 components** (see `references/assessment-workflow.md` § "Components of a migration"):

1. **Historical Data Migration** — required unless greenfield.
2. **Live Traffic Migration** — required only when the read-only window cannot cover the time HDM takes.
3. **Application Code Rewrite** — required for Solr → OpenSearch, X-Pack ports, language-binding swaps.

For each component the customer needs, pick **ONE primary strategy in bold** with a one-sentence reason, then a ranked table over the candidate strategies for that component:

| Strategy | Score (0–10) | Pros | Cons |
|---|---|---|---|

Apply the always-true rules from `assessment-workflow.md` (post-fork lockout, Migration Assistant for Amazon OpenSearch Service Solr-target restrictions, `_source: false` HDM-only, etc.). For ES ≥ 7.11 sources <100 GB with ≥30 min cutover window, the primary HDM strategy **must** be `_reindex` from remote — Migration Assistant for Amazon OpenSearch Service Historical Data Migration is overkill at that scale.

### 5. Sizing

**Show math inline.** Do not produce a single point estimate without a derivation chain. Example formula:

```
storage_gb_per_node = (raw_gb × (1 + replicas) × (1 + overhead_0.15) × (1 + headroom_0.25)) / data_node_count
```

Required outputs:

- **Compute**: `<N>× <instance_class>` for data nodes (e.g., `6× r7g.2xlarge.search`) — Graviton r7g/r8g default.
- **Cluster managers**: `3× <instance>` for ≥6 data nodes (e.g., `3× m7g.large.search`).
- **Storage**: GB per node + storage type (gp3 vs io2 vs Instance Store).
- **Shards**: shard count derivation (target shard size 10–50 GB).
- **JVM heap implication**: 50% RAM, capped at 32 GB. Cite OS 2.17+ shard-cap rule (gotcha #4) if shards/node trends >800.

If inputs are UNKNOWN, present 2–3 tiered bands (small / medium / large) — never invent a single point estimate.

### 6. Readiness

Numeric score 0–100, weighted breakdown across these 7 dimensions:

| Dimension | Weight |
|---|---|
| Compatibility | 25% |
| Operational readiness | 15% |
| Sizing fitness | 15% |
| Data movement complexity | 15% |
| Cutover complexity | 10% |
| Sizing-input completeness | 10% |
| Stakeholder alignment | 10% |

Tier rule:

- **GREEN ≥80** — proceed; surface top items to flag in §7 (split across Migration specifics and Risks/blockers).
- **YELLOW 60–79** — run a PoC + spike on the lowest-scoring dimension before committing.
- **RED <60** — do not commit; weakest dimension first.

### 7. Risks & migration specifics

Two-table section. Citations into `references/assessment-gotchas.md` are by gotcha number (e.g., *"#2 — ES ≥ 7.11 snapshot/restore lockout"*). For Solr sources, prefer #1, #11, #12. For ES sources, prefer #2, #3. For vector workloads, prefer #7, #10.

**Migration specifics** — items with a known, well-trodden remediation. Frame these as *"this is how the migration handles X"*, not as risks. The prescribed fix is part of the path, not a hazard. Each row: gotcha number, one-line spec, the remediation in concrete terms (config change, transformer flag, alternate tool). Most #11–#13 type items, and most "Solr → OpenSearch refactor" semantics items, belong here.

**Risks / blockers** — items that genuinely constrain the migration: no known fix, capacity-plan implications, irreversible target choices, or dependencies on customer action that can fail late. Each row: gotcha number, severity (HIGH / MEDIUM), what breaks if unaddressed, decision needed. #1 (Solr→OS document-level), #3 (Lucene 8→10 segment wall), #16 (uw.medium k-NN), and any "no equivalent on Serverless" items typically belong here.

Include ≥2 named gotchas across the two tables. Always reflect workload-specific trade-offs the customer mentioned in the prompt — do NOT recycle a generic list. If a gotcha has a clean remediation that the migration plan already includes, it belongs in **Migration specifics**, not **Risks**.

### 8. Next Steps

Concrete handoffs the customer can take to ACT on this assessment. Required if a migration path is recommended. Each next step MUST be one of:

1. **Other AWS skill / capability** to load when their next question lands in that domain. Mark with the `aws-` prefix when applicable. Examples:
   - *"For the post-migration sizing PoC, load `amazon-opensearch-service` shape `SIZING_ONLY` with measured peak QPS."*
   - *"For deploying Migration Assistant for Amazon OpenSearch Service on EKS, route to the `aws-eks` skill."*
   - *"For VPC + KMS-CMK setup, route to the `aws-security` skill."*
   - *"For Bedrock Titan embeddings on the RAG side-pipeline, route to `amazon-bedrock` (capability: knowledge-bases-setup)."*
2. **Concrete AWS / OpenSearch CLI commands** the customer should run next. Examples:
   - *"Run `aws opensearch describe-domain-config --domain-name <name>` to confirm the source target region."*
   - *"Pull Migration Assistant for Amazon OpenSearch Service prerequisites with `kubectl apply -f https://raw.githubusercontent.com/opensearch-project/opensearch-migrations/main/...`."*
   - *"Run `GET /_cat/plugins?v` on the source cluster to inventory plugins for the gap register."*
3. **AWS docs links** to the canonical procedure for the chosen path (NOT for general background — those go in Citations). Examples:
   - *"Migration Assistant for Amazon OpenSearch Service — solution implementation: https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/solution-overview.html"*
   - *"Cluster sizing best practices: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html"*
4. **AWS Pricing Calculator** with the specific sizing inputs you derived. State *"plug instance class + count + storage from §5 into <https://calculator.aws>"* — not generic.
5. **MCP / agent commands** — if the user is operating an agent harness, surface relevant commands (e.g., *"call the AWS MCP `aws___get_regional_availability` tool to verify `r7g.2xlarge.search` in `us-west-2`"*).

Format:

```
| # | Action | Pointer |
|---|---|---|
| 1 | Stand up Migration Assistant for Amazon OpenSearch Service on EKS | https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/solution-overview.html |
| 2 | Run sizing PoC | Load `amazon-opensearch-service` shape SIZING_ONLY with measured peak QPS |
| 3 | Plug sizing into Pricing Calculator | https://calculator.aws (use 6× r7g.2xlarge.search, 3× m7g.large.search, gp3 300 GB) |
| 4 | Provision security stack | Route to `aws-security` skill |
| 5 | Inventory source plugins | `GET /_cat/plugins?v` on source |
```

5–7 rows is typical. Each pointer is either a skill name, a CLI command in backticks, or a full URL. Generic "talk to your DevOps team" or "do testing" entries do NOT count — point at a specific resource.

### 9. Citations

≥3 entries. Each entry must include:

- **Source URL** (full).
- **Retrieval timestamp** (UTC, ISO-8601 — `2026-06-02T14:32Z`).
- **One-sentence claim summary** (what version-volatile fact you used it for).

Required URLs (pick the ≥3 you actually used): the AWS best-practices page for sizing math, the AWS upgrade-path page, the Migration Assistant for Amazon OpenSearch Service doc when Migration Assistant for Amazon OpenSearch Service is recommended, the Serverless NextGen comparison page when relevant, and `https://calculator.aws` for the cost handoff.

## NOT REQUIRED — explicitly omit

- **Timeline & Resourcing — REMOVED FROM SUITE.** Do NOT produce a "Phase 1 = 2 weeks" table, "engineer-weeks" estimates, "critical path = …" lines, or any calendar-based commitment. If you find yourself reaching for words like *"timeline"*, *"engineer-weeks"*, *"resourcing"*, *"calendar"*, *"weeks of effort"*, **STOP** and delete the section. The customer will plan timeline using their own program-management practices.
- **Dollar / cost estimates.** No `$X/month`, `~$1,500`, `≈ $40k/year`. Hard route to <https://calculator.aws>.
- **A 6-question business intake.** This shape assumes the customer already gave you the artifacts. If you find yourself wanting to ask 6 questions, the shape was probably misdetected — re-route to `overview`.
- **Per-claim inline citations.** Citations are batched in section 9.
- **Tool narration ("I will now check…", "Let me load…").** First sentence must restate source/version/scale.

## Worked exemplar (~330 words)

> **Detected shape: FULL_ASSESSMENT** — pasted `schema.xml`, `solrconfig.xml`, and traffic numbers; explicit *"prepare a doc for our architect"*.
>
> ## Migration Assessment: Acme Search Platform
>
> > Generated: 2026-06-02T16:45:30Z | Skill: amazon-opensearch-service v1
>
> You're on Apache Solr 8.11 SolrCloud, 3 collections, ~120 M docs, ~600 GB on disk, ~2.5k QPS sustained / 8k peak, target Amazon OpenSearch Service in `us-west-2` for a Search Relevance Engineer + DevOps audience — here's the assessment.
>
> **Executive Summary.** Recommend **Managed OpenSearch 2.19 Multi-AZ-with-Standby**, migrated via **Migration Assistant for Amazon OpenSearch Service Solr backfill (Historical Data Migration)** — Solr → OS is document-level only (gotcha #1), and at 600 GB the single-shot `_reindex` path is too slow. Readiness **72/100 — YELLOW**. Top blocker: 4 custom plugin JARs in `<lib>` directives need port. Plug sizing below into <https://calculator.aws>.
>
> **Source.** Solr 8.11 · 3 collections · 120 M docs · 600 GB · `<uniqueKey>doc_id</uniqueKey>` · 4 custom JARs · `q.op=AND` · 2 `<copyField>` · NMSLIB-equivalent: N/A.
>
> **Target.** Managed OpenSearch **2.19** Multi-AZ-with-Standby (the named 99.95% SLA forces Standby; OS 2.19 chosen because OS 3.x requires reindex of any pre-2.x indexes — already moot on a refactor migration, so 2.19 is the conservative landing). Upgrade to OS 3.x is in-scope post-cutover.
>
> **Migration Path.** **Migration Assistant for Amazon OpenSearch Service Historical Data Migration — primary** (backfill the 600 GB), with **Migration Assistant for Amazon OpenSearch Service Live Traffic Migration** for the cutover window. `_reindex` from remote scored 4/10 (Solr is not a remote source). Snapshot/Restore scored 0 (no Solr→OS snapshot path).
>
> **Sizing.** `(600 × 2 × 1.15 × 1.25) / 6 = 287.5 GB/node` → 6× `r7g.2xlarge.search` + 3× `m7g.large.search` cluster managers, gp3 300 GB/node. 18 primary shards × 1 replica ≈ 33 GB/shard (in target band). JVM 32 GB heap → shard cap 2,000/node (gotcha #4).
>
> **Readiness.** Compatibility 18/25 (custom JARs −5, `q.op` −2). Operational 12/15. Sizing 14/15. Data movement 9/15 (Solr is document-level only — no segment-level path). Cutover 7/10. Sizing-input 6/10 (no peak ingest rate). Stakeholder 6/10. **Total 72/100 — YELLOW.**
>
> **Migration specifics.** #11 — if the source `solrconfig.xml` sets `q.op=AND`, set `default_operator: AND` on every translated `query_string` handler. #12 — Migration Assistant's metadata transformer strips `fielddata` from text fields automatically and adds the `.keyword` subfield.
>
> **Risks / blockers.** #1 Solr→OS is document-level, not segment-level (HIGH) — the 600 GB backfill goes via Migration Assistant Historical Data Migration, no snapshot path exists. Custom JARs require port to the OS plugin API (HIGH) — not supported on Serverless NextGen, so this constrains the target.
>
> **Next Steps.** (1) Deploy Migration Assistant for Amazon OpenSearch Service on EKS — <https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/solution-overview.html>. (2) Port 4 custom JARs to OS plugin API. (3) Run sizing PoC — load `amazon-opensearch-service` shape `SIZING_ONLY` with measured peak ingest rate. (4) Plug 6× `r7g.2xlarge.search` + gp3 300 GB into <https://calculator.aws>. (5) `GET /_cat/plugins?v` on source to complete plugin inventory.
>
> **Citations.** 3 URLs with retrieval timestamps follow.

## Pre-emit checklist (specific to this shape)

Tick each before sending. If any box is unchecked, fix or restart.

- [ ] **Metadata header** present immediately after title: `> Generated: <ISO 8601 timestamp> | Skill: amazon-opensearch-service v<N>` — timestamp pulled from `current_time` tool, version from `SKILL.md` frontmatter.
- [ ] First sentence (after the header) restates **source engine + version + scale + target region + persona**.
- [ ] All **9 section headers** present, in order, named exactly as in this recipe.
- [ ] Numeric **readiness score (0–100)** + **GREEN/YELLOW/RED tier**.
- [ ] **Math derivation** shown inline in Sizing — no naked single-point estimates without a formula.
- [ ] **Graviton current-gen** instances (r7g/r8g, m7g/m8g) — older families only with explicit justification.
- [ ] **Migration Path** names the required components (Historical Data Migration / Live Traffic Migration / Application Code Rewrite — only those that apply), and for each, picks ONE primary strategy in bold + a ranked table of candidate strategies.
- [ ] **≥2 named gotchas** cited by number across §7 (Migration specifics + Risks/blockers; e.g., `#2`, `#11`).
- [ ] **≥3 citations** in section 9, each with URL + UTC timestamp + claim summary.
- [ ] Customer-specific trade-offs in §7 (not a generic recycled list).
- [ ] Items with a known fix routed to **Migration specifics**, not lumped under **Risks/blockers**.
- [ ] **Next Steps section (§8)** present with 5–7 concrete pointers — each pointer is a skill name, a CLI command, an AWS docs URL, or `https://calculator.aws` with derived inputs. No generic "talk to your team" entries.
- [ ] **NO Timeline & Resourcing** section, no `engineer-weeks`, no `calendar weeks`, no `Phase 1 = X weeks`.
- [ ] **NO dollar estimates**; pricing handoff line points at <https://calculator.aws>.
- [ ] **No marketing tone** ("seamless", "robust", "best-in-class", "production-hardened").
- [ ] UNKNOWN inputs marked explicitly OR presented as tiered bands — no invented numbers.
- [ ] **If the target is OS 3.x crossing from any 1.x or 2.x source:** the **Risks/blockers** half of §7 MUST cite (a) the **Lucene segment wall** — *"Lucene 10 cannot read Lucene 8 segments — segment format is forward-only, so every pre-2.x index must be reindexed before reaching 3.x"* — AND (b) **at least one named OS 3.x breaking change** beyond the segment wall: JDK 21 minimum runtime, Security Manager → Java agent migration for plugins, NMSLIB engine removal (forces reindex into FAISS), or renamed k-NN settings. Both items are required when crossing the 3.x boundary. (Plain transformer-handled items go in **Migration specifics**.)
- [ ] **If the response recommends an AOS in-place upgrade:** the mechanism is named **blue/green** (the literal word) at least once. Do NOT describe it as a "long minor-version chain" or invent step-by-step minor hops (e.g., 2.5 → 2.7 → 2.9 → 2.11 → 2.19). AOS supports multi-version blue/green jumps within 2.x and within 3.x; the only mandatory waypoints are **1.3** (for sources < 1.3) and **2.19** (for any 1.x/2.x → 3.x crossing). State the ACTUAL hops the customer needs (typically two: source → 2.19 → 3.x, or source → 2.19 if already 1.3+), not a fake per-minor chain.
- [ ] **If the response recommends migration steps inline (FULL_ASSESSMENT shape):** name the migration tool / strategy by its proper name in §4 — Migration Assistant for Amazon OpenSearch Service Historical Data Migration, Snapshot/Restore, `_reindex` from remote, OSI, in-place blue/green, etc. Do NOT punt with *"see the migration capability"* or *"follow `assessment-workflow.md`"* — those references are for YOUR own routing, not for the user. The user receives a self-contained Migration Path section.
- [ ] **If the prompt named ≥3 simultaneous hard constraints** (e.g., zero-downtime + zero-data-loss + no-third-party-tooling + EU residency, or any 3+ from the constraint-trilemma list in `assessment-shape-comparative-decision.md` § 2.5): the **Executive Summary AND § 4 Migration Path** MUST explicitly name the constraint conflict and recommend a relaxation. Phrasing template: *"At `<scale>`, constraints {X, Y, Z} are mutually inconsistent without compromise. Recommend relaxing `<constraint>` by `<quantified trade-off>` — this converts the problem to `<tractable shape>` and Migration Assistant `<strategy>` applies cleanly."* Do NOT silently claim a single tool path satisfies all named constraints simultaneously — the response will fail if it asserts an impossible feasibility. If the proposed path uses dual-write, also include the dual-write reconciliation rule (*"application-layer dual-write authored by your team is customer code, not third-party tooling"*).
