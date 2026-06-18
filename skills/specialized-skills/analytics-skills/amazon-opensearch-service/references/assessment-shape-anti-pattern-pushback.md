---
case_shape: ANTI_PATTERN_PUSHBACK
purpose: Refuse to size or design an OpenSearch deployment when the source workload is fundamentally wrong-fit for OpenSearch. Redirect the user to the correct technology with a concrete, copy-pasteable alternative.
when_to_use: The user is asking for migration sizing, topology, or schema design for a workload whose primary requirements (ACID, foreign keys, hierarchical integrity, audit immutability, exact-match relational lookups, sub-million-row scale) are better served by the existing relational store or a different system entirely. OpenSearch is being applied as a generic "database upgrade" rather than as a search/analytics engine.
do_not_use_when: The workload has a real search/analytics shape and the user just has gaps in their plan — that is FULL_ASSESSMENT or READINESS_GAP territory. Wrong-fit pushback is for migrations that should not happen at all, not migrations that are merely under-planned.
---

# Recipe: ANTI_PATTERN_PUSHBACK

## 1. Detection signals

Dispatch here when the intake matches **two or more** of the following:

- **Source is OLTP/relational** with strong ACID requirements: Postgres, MySQL, Oracle, SQL Server holding the system of record.
- **Domain is transactional, not search**: HR records, payroll, billing, ledger, inventory of record, identity/auth, order state machine, audit log of record.
- **Cardinality is small**: < ~10M rows total, < ~1k writes/sec, < ~100 QPS read.
- **Access pattern is exact-match or relational join**: lookup-by-id, parent/child traversal (manager → reports), foreign-key joins, point updates by primary key.
- **Stated motivation is non-search**: "we want it faster", "we want it more scalable", "we want JSON flexibility", "the team likes Elasticsearch", "we're consolidating on OpenSearch", "search is a nice side benefit".
- **Required guarantees OpenSearch cannot provide**: multi-document transactions, foreign-key cascade, unique constraints across documents, immutable audit trail, strict referential integrity, RDBMS-style row locking.

If only **one** signal is present and the rest of the workload looks like real search/analytics, do NOT dispatch here — handle as FULL_ASSESSMENT or READINESS_GAP and surface the concern as a risk in the Risks section instead.

## 2. Required output template

Produce these sections in order. No others.

### Section A — Verdict (one paragraph, ≤ 4 sentences)
State plainly that this is the wrong target. Name the source system, the workload type, and the one-line reason (e.g., "this is an OLTP HR database, not a search workload").

### Section B — Verbatim refusal to size
Include **exactly** this sentence, verbatim, as its own paragraph:

> I'm not going to spec instance types or shard counts because recommending a topology for a migration that shouldn't happen lends false confidence to the wrong path.

Do not paraphrase. Do not soften. Do not append "but here's a rough idea anyway".

### Section C — Workload-fit reasoning (≥ 2 reasons)
A bulleted list, each bullet naming a specific OpenSearch limitation against a specific requirement of THIS workload. Pull from: ACID/multi-doc transactions, foreign-key & referential integrity, manager/reports hierarchy traversal, audit immutability, unique constraints, scale economics at small cardinality, eventual-consistency on refresh interval.

### Section D — Positive alternative (Postgres recipe)
Concrete, copy-pasteable DDL using `pg_trgm` + `tsvector` + `GIN`. The user must be able to paste it into psql and have working fuzzy + full-text search on their existing Postgres without leaving the relational store.

### Section E — Future-fit triggers
Bulleted list of **specific, measurable** conditions that would flip the recommendation. Not vague ("if you grow"). Concrete: "if employee record count exceeds ~50M and you add free-text resume search across all historical records", "if you add log-analytics retention requirements > 90 days at > 1TB/day", etc.

## 3. NOT REQUIRED — explicitly omit

The following sections **must not appear** in this shape's output:

- **Sizing of any kind** — no instance types, no shard counts, no replica counts, no EBS sizing, no data-node-vs-cluster-manager tables, no "rough order of magnitude" numbers. None.
- **Migration path** — no logstash JDBC plan, no DMS plan, no reindex plan, no _bulk recipe.
- **Readiness assessment** — no readiness score, no gap analysis, no "you're 70% ready".
- **Timeline & Resourcing — removed from suite.** Do not produce engineer-weeks, sprint estimates, headcount, or a calendar plan. This section has been deleted from the entire skill.
- **Citations section** — this shape is a refusal/redirect, not a researched recommendation. The Postgres recipe is well-known reference material; do not pad with citations.
- **Customer-specific trade-offs** — no "if your team has more Postgres skill vs. OS skill" weighing. The pushback is about workload fit, not team skill.
- **Persona block / stakeholder analysis** — irrelevant to a refusal.

## 4. FORBIDDEN HEDGES

The following phrases (and any close paraphrase) are **prohibited**. Producing OpenSearch sizing or topology under any of these framings counts as an **ANTI-PATTERN VIOLATION** and the response must be regenerated:

- "Option B" / "Option 2" / "Plan B" / "Alternative path"
- "If you insist..."
- "Search-only sidecar" / "search-only mirror" / "read-only search replica on OS"
- "If you do go this path, here's what it would look like..."
- "For completeness, here is what sizing would look like..."
- "I still want to give you something useful, so..."
- "Here's a rough estimate just in case..."
- "If leadership has already decided..."

The refusal is the deliverable. The Postgres recipe is the deliverable. There is no third deliverable that quietly re-introduces OpenSearch sizing.

## 5. Worked exemplar (HR DB on Postgres → OpenSearch)

> **Verdict.** This is a Postgres-backed HR system of record — ~200k employee rows, manager→reports hierarchy, payroll integration, immutable audit trail. It is an OLTP relational workload, not a search workload. OpenSearch is the wrong target.
>
> I'm not going to spec instance types or shard counts because recommending a topology for a migration that shouldn't happen lends false confidence to the wrong path.
>
> **Why OpenSearch is wrong-fit here:**
>
> - **No ACID across documents.** Payroll changes that update an employee, their compensation record, and the audit row must commit atomically. OpenSearch refresh is near-real-time per shard, with no multi-document transaction.
> - **No foreign-key integrity.** The manager→reports hierarchy and the employee→department→cost-center chains rely on referential integrity. OpenSearch joins are limited (parent-child within a single index, denormalized nested), and cascade behavior is application-coded.
> - **No unique constraints.** Employee ID, SSN, email uniqueness is enforced by Postgres today. OpenSearch will let two `_bulk` requests insert duplicates and you will not find out until reconciliation.
> - **Audit immutability is harder, not easier.** OpenSearch documents are mutable by `_id`. Postgres + append-only audit table + role-based revoke is a stronger guarantee than anything you'd build on top of OpenSearch.
> - **Scale economics.** 200k rows on a `db.t4g.medium` is a rounding error. The smallest reasonable OpenSearch domain (3 dedicated cluster managers + 2 data nodes) costs more per month than the entire current Postgres footprint, for worse guarantees.
>
> **What to do instead — keep it in Postgres.** If the real ask is "find an employee by partial name / fuzzy match / full-text on job title", `pg_trgm` + `tsvector` + `GIN` solves it in the database you already have:
>
> ```sql
> CREATE EXTENSION IF NOT EXISTS pg_trgm;
>
> ALTER TABLE employee
>   ADD COLUMN search_tsv tsvector
>   GENERATED ALWAYS AS (
>     setweight(to_tsvector('english', coalesce(full_name,'')),  'A') ||
>     setweight(to_tsvector('english', coalesce(job_title,'')),  'B') ||
>     setweight(to_tsvector('english', coalesce(department,'')), 'C')
>   ) STORED;
>
> CREATE INDEX employee_search_tsv_gin ON employee USING GIN (search_tsv);
> CREATE INDEX employee_name_trgm      ON employee USING GIN (full_name gin_trgm_ops);
>
> -- fuzzy + full-text in one query:
> SELECT id, full_name, job_title
> FROM   employee
> WHERE  search_tsv @@ plainto_tsquery('english', :q)
>    OR  full_name % :q
> ORDER  BY ts_rank(search_tsv, plainto_tsquery('english', :q)) DESC
> LIMIT  25;
> ```
>
> **Triggers that would change this recommendation:**
>
> - Employee/contractor record count exceeds ~50M and you add free-text search across resumes/CVs/interview notes spanning > 5 years of history.
> - You take on log-analytics or observability retention at > 1 TB/day.
> - You add semantic / vector search over policy documents or knowledge-base articles at > 1M docs.
> - You need cross-tenant federated search across many independent HR systems with > 50 sources.
>
> Until one of those is real, the right move is `CREATE EXTENSION pg_trgm;` not `aws opensearch create-domain`.

## 6. Pre-emit checklist (this shape only)

Tick every box before sending. If any box is unchecked, the response is wrong-shape and must be regenerated.

- [ ] Verdict paragraph names the source system, workload type, and one-line reason.
- [ ] **Verbatim refusal sentence is present, exact, and unmodified.**
- [ ] At least 2 workload-fit reasons, each tied to a specific OpenSearch limitation against a specific requirement of THIS user's workload (not generic).
- [ ] Postgres alternative includes runnable DDL with `pg_trgm`, `tsvector`, and `GIN` (all three).
- [ ] Future-fit triggers are concrete and measurable (numbers, named features) — no vague "if you grow".
- [ ] **No instance types appear anywhere in the response.** (grep mentally for `m6g`, `r6g`, `t3`, `data.`, `master.` / `cluster-manager.`, `.search`.)
- [ ] **No shard/replica counts appear anywhere.** (grep for "shard", "replica", "primary", "AZ".)
- [ ] **No Migration Path, Readiness, Timeline & Resourcing, or Citations section.** (Timeline & Resourcing is removed from the entire suite — do not reintroduce.)
- [ ] **No FORBIDDEN HEDGE phrases.** (grep for "Option B", "if you insist", "sidecar", "for completeness", "if you do go this path", "Plan B", "Option 2".)
- [ ] The Postgres recipe is presented as **the** alternative, not as one of two options.
- [ ] No persona block, no stakeholder analysis, no team-skill weighing.
- [ ] Total length is shorter than a FULL_ASSESSMENT — refusal should not pad.
