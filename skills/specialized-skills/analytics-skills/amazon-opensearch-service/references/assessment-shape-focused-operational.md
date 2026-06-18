# Case shape — FOCUSED_OPERATIONAL

A targeted "what command do I run?" answer for a small, well-bounded migration where the customer has already decided to move and just wants the runbook. Output is a **decision rule + concrete steps + one central gotcha**, nothing more. No assessment, no readiness, no risk register.

---

## When to dispatch here

Use FOCUSED_OPERATIONAL when the customer's question is **bounded by a clear operational threshold** and the answer is a sequence of commands, not a strategy. The agent should pick this shape — over FULL_ASSESSMENT or TRANSLATION_TASK — when ALL three are true:

1. **Size is small or stated as "tiny"** — under ~100 GB total or "a few indexes" or "one index"
2. **Decision criteria is explicit in the question** — "cheapest", "quickest", "simplest", "minimum-downtime"
3. **Source/target pair is obvious** — version is given or trivially inferable, target is clearly Amazon OpenSearch Service Managed (not Serverless deliberation)

If the customer is debating Managed vs Serverless, asking about cost trade-offs, or has 500+ GB / multi-cluster scope — that is FULL_ASSESSMENT, not this shape.

### Detection signals

**Keywords that trigger this shape:**

- "cheapest path" / "cheapest way" / "minimum cost"
- "quickest migration" / "fastest way" / "in a weekend" / "in 2 hours"
- "simplest" / "easiest" / "just want to move it"
- "small index" / "<100 GB" / "tiny dataset" / "one index"
- "what command do I run" / "give me the runbook"

**Artifacts that trigger this shape:**

- Single index size mentioned, under 100 GB
- Single ES/OS source version (e.g. "ES 7.17") + clear target ("AOS")
- A concrete maintenance window stated ("2 hour window", "Saturday night")
- No mention of multiple environments, regions, or compliance scope

**Anti-signals (route elsewhere instead):**

- "Should we migrate?" → FULL_ASSESSMENT
- "How do I translate this query?" → TRANSLATION_TASK
- "What's wrong with this approach?" → ANTI_PATTERN_PUSHBACK
- Pasted `schema.xml` → SCHEMA_CONVERSION

---

## Required output template

Produce these sections, in this order, and **nothing else**:

### 1. Decision rule (one sentence)

State the **single threshold** from the skill that drives the chosen path. Format:

> **Rule:** `<size threshold> <source/version constraint>` → `<chosen path>`

Examples:

- **Rule:** `<100 GB and ES ≥ 7.11` → `_reindex from remote (PRIMARY)` — see `references/assessment-gotchas.md` #2.
- **Rule:** `<100 GB and ES ≤ 7.10` → `S3 snapshot + restore` is viable, but `_reindex from remote` is still simpler.
- **Rule:** `<100 GB and Solr any version` → `document-level export + _bulk` — Solr has no snapshot path to OpenSearch ever.

### 2. Runbook steps (numbered, copy-pasteable)

4–8 numbered steps. Each step is **one action** with a concrete command or click-path. Pre-create destination index, configure allowlist, run, validate. Example structure:

```
1. Pre-create destination index with target mappings/settings
2. Add source endpoint to reindex.remote.allowlist on the AOS domain
3. POST _reindex with remote.host pointing at source
4. Poll _tasks for the reindex task ID until completion
5. Validate doc count: GET <dest>/_count vs source count
6. (Optional) Update aliases / cut over reads
```

### 3. One central gotcha (one short paragraph)

The single most likely failure mode for this exact path. Cite the gotcha number from `references/assessment-gotchas.md`. Examples:

- ES 7.11+ snapshot prohibition (gotcha #2)
- Solr is document-level only (gotcha #1)
- Lucene 8→10 wall if also crossing OS 3.0 (gotcha #3)

### 4. References footer (one line)

A single line pointing to deeper material. Format:

> *Deeper: see `references/assessment-workflow.md` § Path scoring; `references/assessment-gotchas.md` #2 for the snapshot block.*

---

## NOT REQUIRED — explicitly OMIT

This shape **must not** include any of these. If you find yourself writing them, you have picked the wrong shape — escalate to FULL_ASSESSMENT.

- **Timeline & Resourcing — REMOVED FROM THE ENTIRE SUITE.** No "engineer-weeks", no "Week 1 / Week 2", no resourcing estimates anywhere. Stop if you start typing this.
- **Executive summary** — there is no exec audience for a runbook
- **Source fingerprint JSON** — the size + version are already in the rule
- **Target shape selection (Managed vs Serverless vs Classic)** — already implied by the decision rule
- **Sizing tables** — the customer is moving a small dataset; default a single `r7g.large.search` × 2 or whatever they have
- **Readiness scoring (7-dim, GREEN/YELLOW/RED)** — irrelevant at this scope
- **Risk register / compatibility scan beyond the one gotcha**
- **Citations section** — the one-line References footer replaces it
- **Math derivations** — only the threshold rule, no shard arithmetic, no IOPS, no heap math
- **Customer-specific trade-off discussion** — they already chose; don't re-litigate

**The 9 sections of FULL_ASSESSMENT are NOT used here.** This shape produces 4 sections (Rule, Runbook, Gotcha, References), full stop.

---

## Worked exemplar — 50 GB ES 7.17, 2-hour window

> **Customer:** "I have a 50 GB index on ES 7.17 (self-managed EC2). Need to move it to Amazon OpenSearch Service in us-east-1 with a 2-hour maintenance window this Saturday. Cheapest/quickest path?"

**Response:**

**Rule:** `<100 GB and ES ≥ 7.11` → **`_reindex from remote`** is the primary path. Snapshot/restore is not available — see `references/assessment-gotchas.md` #2.

**Runbook:**

1. **Pre-create the destination index** on the target domain with mappings and settings copied from source. The remote `_reindex` does NOT carry mappings — only `_source`. Pull source mappings via `GET <src>/<index>/_mapping` and PUT them on the destination.
2. **Add the source endpoint to the domain's `reindex.remote.allowlist`** via Console → Domain → Cluster settings (or the `UpdateDomainConfig` API). Format: `host:port` (e.g. `10.0.5.20:9200`). Apply — wait for the blue/green to finish (~15 min).
3. **Run the reindex** asynchronously. **Auth — prefer SigV4** when the source endpoint is IAM-capable: sign the `_reindex` POST with `awscurl` (or a SigV4 proxy) so no long-lived static credentials traverse the request body. If the source requires basic auth (legacy self-managed cluster), retrieve username/password from **AWS Secrets Manager at runtime** (`aws secretsmanager get-secret-value --secret-id <reindex-source-creds>`) and inject them as ephemeral inputs — do NOT hard-code credentials in scripts, IaC, or runbooks.

   ```
   POST _reindex?wait_for_completion=false&slices=auto
   {
     "source": {
       "remote": {
         "host": "https://10.0.5.20:9200"
         // SigV4 (preferred): omit username/password; sign the POST itself.
         // Basic-auth fallback (only when source is not IAM-capable): pull from Secrets Manager, inject here.
         // "username": "${SECRET_USERNAME}", "password": "${SECRET_PASSWORD}"
       },
       "index": "products",
       "size": 1000
     },
     "dest": {"index": "products"}
   }
   ```

   Capture the returned `task` id.
4. **Poll progress:** `GET _tasks/<task_id>` until `completed: true`. For 50 GB at typical throughput, expect 20–60 minutes — well within the 2-hour window.
5. **Validate doc counts:** `GET <src>/products/_count` vs `GET <dest>/products/_count`. They must match. Spot-check a few `_id`s.
6. **Cut over reads** by repointing the application or aliasing.

**Central gotcha — ES 7.11+ snapshot prohibition (gotcha #2).** See `references/assessment-gotchas.md` #2 for the failure mode and reasoning. The `_reindex from remote` path is the supported workaround at this size. If the dataset were larger (>100 GB) you would graduate to Migration Assistant for Amazon OpenSearch Service Historical Data Migration instead — but at 50 GB, `_reindex` is simpler.

*Deeper: see `references/assessment-workflow.md` § Path scoring; `references/assessment-gotchas.md` #2 for the snapshot block.*

---

## Pre-emit checklist (shape-specific — tick before sending)

- [ ] **Decision rule is one line** with an explicit threshold (e.g. `<100 GB`, `ES ≥ 7.11`, `Solr any`)
- [ ] **Runbook is 4–8 numbered steps**, each with a concrete command or click-path
- [ ] **Pre-create destination is step 1 or 2** (never assume mappings carry over on `_reindex from remote`)
- [ ] **Allowlist / network config is an explicit step** (most common runbook omission)
- [ ] **Validation step exists** (doc count, spot check, or `_cat/indices`)
- [ ] **Exactly ONE gotcha cited**, by number from `references/assessment-gotchas.md`
- [ ] **References footer is ONE line** pointing to deeper material
- [ ] **No "Timeline" section**, no "Week 1", no engineer-weeks. (REMOVED FROM SUITE.)
- [ ] **No exec summary, no readiness, no risk register, no sizing table, no fingerprint JSON**
- [ ] **No sentence longer than ~30 words** — operational tone, not consultative
- [ ] **No customer trade-off re-litigation** — they chose, you execute
- [ ] **Total length under ~500 words** — if longer, you've drifted into FULL_ASSESSMENT territory
- [ ] **First sentence states the rule**, not a restatement of the customer's question
- [ ] **If Solr source:** path is document-level export + `_bulk` (gotcha #1), never snapshot
- [ ] **If crossing OS 3.0 (target is 3.x from any 1.x or 2.x source):** central gotcha section MUST include BOTH (a) the Lucene segment wall — phrase it as *"Lucene 10 cannot read Lucene 8 segments — segment format is forward-only, so every pre-2.x index must be reindexed before the cluster reaches 3.x"* — AND (b) **at least one named OS 3.x breaking change** beyond the Lucene wall: JDK 21 minimum runtime, Security Manager → Java agent migration for plugins, NMSLIB engine removal (k-NN must reindex into FAISS first), or renamed k-NN settings. One sentence each is sufficient. Without both items the response will be marked incomplete on any 1.x→3.x or 2.x→3.x crossing.
