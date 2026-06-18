---
case_shape: COMPARATIVE_DECISION
shape_family: decision
one_liner: "User is choosing between two (or a small N of) concrete options and wants a pick, not an essay."
when_to_dispatch: "Question contains 'A or B', 'should we use X vs Y', 'managed vs serverless', 'NextGen vs Classic', 'OR1 vs gp3', 'k-NN engine: faiss vs lucene vs nmslib', or any framing where the user has narrowed the universe to ~2-4 named alternatives and wants a recommendation."
forbidden_sections:

- "Timeline & Resourcing"
- "Engineer-weeks estimate"
- "Project plan / phases"
- "Readiness scorecard (full)"
- "Sizing math derivation (unless it IS the decision driver)"

---

# Recipe: COMPARATIVE_DECISION

## 1. What this shape is

A **comparative-decision** response answers a binary or small-N choice with an
explicit pick, a side-by-side table, and one load-bearing reason. It is the
shortest of the decision shapes — the user is not asking for an assessment, a
plan, or a tutorial. They have already reduced the search space and want a
ruling.

Treat this as a one-screen artifact. The reader should be able to skim the
pick, scan the table, and stop. Anyone who needs more depth will follow up.

## 2. Detection signals

Dispatch to this shape when the user prompt contains any of:

- The literal token `vs`, `versus`, `or`, separating two named options
  ("Managed vs Serverless", "OR1 or gp3", "faiss vs lucene")
- "Should we use ...", "Which is better for ...", "Pick one"
- Two or three concrete AWS/OpenSearch SKU names
  (Domain, Serverless, NextGen, Classic, OR1, gp3, t3.small.search,
  faiss/lucene/nmslib, BM25 vs neural, hybrid vs pure-vector)
- A request that names a specific workload bound (vector count, QPS, GB/day)
  and asks which option fits
- Implicit comparisons: "do we even need Serverless for this?" — the second
  option is the user's current/default platform

Do **not** dispatch here when:

- The user asks "what should we do?" with no named options → FULL_ASSESSMENT
- The user asks "how do I migrate from X to Y?" → MIGRATION_PATH
- The user asks "is X a good idea?" with one option only and red flags →
  ANTI_PATTERN_PUSHBACK

## 2.5 Over-constrained variant — the constraint trilemma

When the prompt names **3+ hard constraints** (e.g., zero downtime, zero data loss, no third-party tooling, EU residency, fixed budget, fixed deadline) and asks "how do you reconcile these?" — the user is asking for a **feasibility ruling**, NOT a SKU pick. Before the Pick (§3.1), insert a **Constraint feasibility** block:

> _**Feasibility:** at \<scale\>, constraints **{X, Y, Z}** are mutually inconsistent without compromise. The path that satisfies any 2 of these forces a relaxation of the 3rd._

Then in §3.1 Pick, recommend the **relaxation**, not just the SKU:

> **Pick: relax \<constraint\> by \<quantified trade-off\>** (e.g., "accept a 15-30 min read-only cutover window"), which converts the problem to \<tractable shape\> — then \<tool/path\> applies cleanly.

In the §3.2 comparison table, add a **Relaxation** column showing what each option costs you (which constraint it forces to bend). Decision driver (§3.3) names the conflict explicitly: "this option wins because it minimizes the relaxation needed on the load-bearing constraint."

**Common conflict patterns to flag:**

- _zero downtime + zero data loss + no third-party tooling at multi-TB scale_ — pick any two; the third forces a third-party CDC tool, an outage window, or accepted lag.
- _EU residency + global low-latency reads_ — pick one; cross-region replicas violate residency, in-region reads sacrifice latency outside EU.
- _fixed budget + fixed deadline + new compliance scope_ — pick two; new scope without budget or time relief is a red flag.

**Dual-write reconciliation rule.** If your pick proposes dual-write to the source and target during cutover, **state plainly** that application-layer dual-write written by the customer's own engineering team is **customer code**, NOT third-party tooling. Otherwise the response appears to violate a "no third-party tooling" constraint when it actually doesn't. Phrase: _"Dual-write here is customer code in your existing services — it is not a third-party tool, agent, or vendor product."_

**Failure modes to avoid (tested against this rubric):**

- ❌ Claiming a single path "simultaneously satisfies" all 3+ constraints when it cannot — the rubric will fail you for not surfacing the conflict.
- ❌ Picking a path that requires dual-write under a "no third-party tooling" constraint without the reconciliation rule above.
- ❌ Treating the prompt as "which AWS SKU?" instead of "which constraint do we relax?" — these prompts are about **trade-offs**, not about Managed vs Serverless.

## 3. Required output template

Produce **exactly** these sections, in this order:

### 3.1 Pick (1-2 sentences)
> **Pick: `<option>`.** `<one-line load-bearing reason>`.
> _Caveat (only if needed): `<single qualifier, e.g. "switch to <other> if <threshold>">`._

The caveat goes **after** the pick, never before. No "it depends". No "both
are valid". Pick one.

### 3.2 Comparison table
A markdown table with 4-7 rows. Columns are the options. Rows are the
dimensions that actually moved the decision. Typical rows:

| Dimension | Option A | Option B |
|---|---|---|
| Pricing model | ... | ... |
| Min commit | ... | ... |
| Max scale tested | ... | ... |
| Vector engine support | ... | ... |
| Operational burden | ... | ... |
| Irreversible? | ... | ... |

Skip any dimension that is identical between options — it is not a decision
driver.

### 3.3 Decision driver (1 sentence)
Name the single fact that pushed the pick. Example:
> _Decision driver: 100M vectors at 384 dims = ~150 GB raw, which exceeds the
> Serverless single-shard ceiling and forces sharded NextGen anyway._

### 3.4 Irreversibility callout (when applicable)
If the choice locks the customer in, say so plainly. Triggers:

- **NextGen vs Classic Serverless collection** — chosen at create time, cannot
  be flipped
- **OR1 instance family** — backed by S3, switching back to gp3-instance
  storage requires a new domain or blue/green
- **In-place engine upgrade** — 2.x → 3.x cannot be rolled back without snapshot restore
- **Domain → Serverless** — no in-place path, requires reindex/snapshot+restore

Format:
> _Irreversible: `<what is locked>`. To change later: `<real path, e.g. "blue/green to a new domain">`._

### 3.5 Inline doc URL
Exactly **one** AWS docs link, inline next to the most contested claim. Not a
bibliography. Example:
> ...Serverless NextGen vector collections support up to 6 dimensions of
> filter pushdown ([docs](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html)).

## 4. NOT REQUIRED — explicitly omit

Do NOT include any of the following in a comparative-decision response:

- **Timeline & Resourcing** — removed from the suite, do not add it
- Engineer-weeks, sprint count, "phase 1 / phase 2"
- Full readiness scorecard (that is FULL_ASSESSMENT's job)
- Sizing math derivation, unless the math IS the decision driver (then keep
  it to one line)
- Customer-specific trade-offs ("if your team has Kotlin expertise...") — you
  do not know the team
- Migration runbook / step-by-step ("first snapshot, then...")
- Dollar cost projections of any kind (this is a HARD universal constraint — see SKILL.md). Direct cost questions to <https://calculator.aws>; comparative-decision tables MAY name relative cost SHAPES (e.g., "OCU floor vs sized-to-peak compute") but MUST NOT include dollar figures.
- Risk register, mitigation plan, rollback playbook
- Glossary, "what is OpenSearch" preamble
- More than one doc URL
- Bullet lists of "pros and cons" for each option separately — that is what
  the table is for

If you find yourself writing "Phase 1: Migration — 3 engineer-weeks", stop.
Wrong shape.

## 5. Worked exemplar

**Prompt:** "We have 100M FAISS vectors at 384 dimensions, ~50 QPS read,
mostly cosine similarity with a tenant_id filter. Should we use OpenSearch
Serverless VECTORSEARCH NextGen or a managed Domain?"

**Response:**

> **Pick: OpenSearch Serverless VECTORSEARCH NextGen collection.** At 100M /
> 384-dim with a single high-cardinality filter, NextGen's
> disk-optimized vector engine and per-OCU billing match the workload shape
> better than a provisioned Domain.
> _Caveat: switch to a Domain with OR1 if you need sub-50 ms p99 with hybrid
> BM25+vector — Serverless tail latency is higher under mixed load._
>
> | Dimension | Serverless VECTORSEARCH NextGen | Managed Domain (OR1) |
> |---|---|---|
> | Pricing model | Per-OCU, scale-to-floor | Per-instance-hour, 24/7 |
> | Min spend (shape, not $) | 2 OCU search + 2 OCU index, 24/7 floor — plug into <https://calculator.aws> | 3x r6gd.large.search (instance-hour) — plug into <https://calculator.aws> |
> | 100M @ 384-dim feasible? | Yes, NextGen disk-tier vector engine | Yes, but needs ~300 GB RAM hot |
> | Filter pushdown | Up to 6 fields, including high-cardinality | Native via k-NN plugin |
> | Ops burden | Zero shard tuning | Shard plan, JVM, snapshots |
> | Engine lock | NextGen vs Classic chosen at create | OR1 family chosen at create |
> | Irreversible? | Yes — collection type fixed | Yes — instance family fixed |
>
> _Decision driver: 100M vectors @ 384 dim ≈ 150 GB raw + graph overhead;
> Serverless NextGen's S3-backed vector engine reads this from disk without
> sizing a 300+ GB RAM Domain, and the tenant_id filter is exactly the
> high-cardinality case NextGen optimized for ([docs](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html))._
>
> _Irreversible: NextGen vs Classic is set at collection-create and cannot be
> flipped. To change later: create a new collection and reindex._

That is the entire response. ~210 words including the table. No timeline, no
phases, no readiness checklist.

## 6. Pre-emit checklist (shape-specific)

Before sending, tick every box:

- [ ] **Pick is explicit** — one named option, in bold, in the first sentence
- [ ] **Caveat is after the pick** (or absent) — never "it depends" before the pick
- [ ] **Comparison table has ≥4 rows and ≤7 rows** — every row is a decision driver
- [ ] **No identical-value rows** in the table (those are not deciders)
- [ ] **Decision driver named** in one sentence, identifying the load-bearing fact
- [ ] **Irreversibility called out** if the choice has a one-way door
      (NextGen-vs-Classic, OR1, in-place upgrade, Domain↔Serverless)
- [ ] **Exactly one inline doc URL**, placed next to the most contested claim
- [ ] **Zero of the forbidden sections** present (Timeline, engineer-weeks,
      readiness scorecard, full sizing derivation, migration runbook)
- [ ] **Total length under ~400 words** (excluding the table)
- [ ] **No "pros/cons" bullet lists per option** — the table replaces those
- [ ] **No glossary or preamble** — go straight to the pick
- [ ] **If the prompt names ≥3 hard constraints** (e.g., zero downtime + zero data loss + no third-party tooling + EU residency, or any 3+ from §2.5's trilemma list): the response MUST include the §2.5 **Constraint feasibility** block **before** the §3.1 Pick. The block names which constraints are mutually inconsistent, identifies which one is being relaxed, and quantifies the trade. **Do not** silently pick a path and present it as satisfying all constraints — the response will fail if it claims simultaneous satisfaction of an impossible set. If the pick involves dual-write, also tick the dual-write reconciliation rule (§2.5).
- [ ] **If the customer's source is NOT already on AOS** (Solr, ES self-managed, OS self-managed, ES on EC2, etc.), the response MUST name the migration mechanism inline — Snapshot/Restore (pre-fork ES ≤ 7.10.2), Migration Assistant for Amazon OpenSearch Service Historical Data Migration, `_reindex` from remote, OSI, or in-place blue/green — and tie the choice to the source version where relevant (e.g., "7.10.2 is pre-fork, before the 7.11 ELv2 snapshot wall, so Snapshot/Restore is the path"). Do NOT punt with _"see the migration capability"_ or _"follow `assessment-workflow.md`"_ — the response is self-contained for the user.
- [ ] **If the source is ES with index lifecycle policies (ILM):** call out the **ILM → ISM rewrite** explicitly. ILM JSON does NOT port to OpenSearch (gotcha #29). Either name "ILM-to-ISM rewrite" as a migration step or include a one-line ISM policy phrase showing the rewrite is acknowledged.
- [ ] **If recommending an in-place upgrade:** name the mechanism **blue/green** explicitly. Do NOT invent a per-minor-version chain (e.g., 2.5 → 2.7 → 2.9 → 2.11 → 2.19). AOS supports multi-version blue/green jumps within 2.x and within 3.x; the only mandatory waypoint is **2.19** when crossing into 3.x (and **1.3** for sources < 1.3). State the actual hops, not a fake chain.

If any box is unticked, fix it before emitting. If you cannot tick "Pick is
explicit" because the answer genuinely depends on a missing fact, ask one
clarifying question instead of producing a hedged comparison.
