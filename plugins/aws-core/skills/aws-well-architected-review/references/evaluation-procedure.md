# Evaluation Procedure — Assess every BP against the frozen manifest

Read this file before Step 5 of a full review. The live question and best-practice inventory has already been acquired and **validated** in Step 4 (ACQUIRE_CORPUS — see [live corpus inventory](phase-live-inventory.md)) and frozen as `corpus/questions.jsonl` and `corpus/best-practices.jsonl`. This file defines how to assess the workload against that frozen manifest and how to audit coverage before reporting. Its sub-steps are labelled 5a–5d, matching Step 5 in `SKILL.md`.

## Corpus source — the frozen manifest is authoritative

- The set of questions and BPs to assess **is** the frozen manifest from ACQUIRE_CORPUS. Do NOT rebuild it here, and do NOT use semantic search (`aws___search_documentation`) to enumerate questions or best practices. Semantic search returns ranked, non-canonical, sometimes stale results and is the source of the traversal-stall failures — enumeration happens once, in ACQUIRE_CORPUS, and is frozen.
- The only documentation retrieval in this step is reading an individual BP's **detail page** at the `bp_url` already recorded in the manifest — and only when the BP's title plus the workload evidence is not enough to judge status, or when writing a Critical/High recommendation. Prefer `aws___read_documentation` when the AWS MCP server is available; otherwise fetch that `docs.aws.amazon.com` URL over HTTPS with the environment's web-fetch tool, and if no documentation access exists, judge from the BP title plus internal knowledge and disclose that limitation. Do not bulk-fetch BP detail pages.
- Canonical `PILLAR##-BP##` IDs are taken verbatim from the manifest. Never invent an ID; if the manifest lacks a BP you expected, that is a corpus problem to surface, not a gap to fill from memory.

## Coverage strategy — assess every BP in the manifest

The purpose of a full review is comprehensive BP-level coverage: **every** BP in `corpus/best-practices.jsonl` receives exactly one status from the five-value vocabulary. The manifest counts (total, and per pillar) are your coverage targets — trust them over any number written in this skill.

## Step 5a — The question inventory is the frozen manifest

Use `corpus/questions.jsonl` as the authoritative question inventory (its `question_id`, pillar, and title). This drives the per-question report table and the Step 5d audit. Do not re-walk the appendix or search to rebuild it — it is already validated and frozen.

## Step 5b — Assess each pillar in its own scoped pass (MANDATORY for full coverage)

**Why this pattern:** when a single agent tries to assess every BP in one response, it can stop before finishing. Scoped to ONE pillar — with that pillar's BP set already supplied by the frozen manifest — the agent assesses each BP without navigating the docs, and one pass per pillar aggregates to full coverage.

**If your environment supports parallel subagents,** dispatch one pass per pillar in the manifest in a single turn. **If it does not, run the passes sequentially** — one pillar at a time, completing that pillar's table before the next.

**Required output format (every pillar pass):**

```markdown
## {Pillar} Findings

BPs in this pillar (from the frozen manifest): {N}

| BP ID | Status | Risk Level | Evidence | Recommendation |
|-------|--------|----------|----------|-----------------|
| {BP ID from the manifest} | {status} | {risk level or blank} | {evidence} | {recommendation} |
| ...one row per BP in this pillar's manifest set... | ... | ... | ... | ... |
```

**Row requirements:**

- One row per BP in this pillar's manifest set — the row count MUST equal the `{N}` header line (which is the count of `corpus/best-practices.jsonl` rows with this `pillar_id`)
- Status: exactly one of `Implemented` / `Partially Implemented` / `Not Implemented` / `Not Applicable` / `Cannot Determine`
- Risk Level: `Critical` / `High` / `Medium` / `Low` (or blank for Implemented/Not Applicable/Cannot Determine)
- Evidence: specific file:line references when code was analyzed, or "Based on description" when reviewing verbally
- BP ID in canonical `PILLAR##-BP##` format, copied verbatim from the manifest

**Pillar pass instructions** — use as the subagent prompt (adapt the dispatch syntax to your environment), or as your own working instructions per pillar when running sequentially:

```
Assess the workload ONLY for the {PILLAR NAME} ({PREFIX}) pillar of the AWS Well-Architected
Framework. This pillar's best practices are supplied by the frozen manifest
(corpus/best-practices.jsonl filtered to this pillar). Do NOT re-walk the documentation and
do NOT use semantic search to build the list — the manifest is authoritative. Read a BP's
detail page only when its title plus the workload evidence is not enough to judge status
(prefer aws___read_documentation on its manifest bp_url; if the AWS MCP server is unavailable,
fetch that docs.aws.amazon.com URL over HTTPS, or judge from the BP title plus internal
knowledge and say so). Assess EVERY BP in the pillar's manifest set — do not filter to 'top
issues'. Output: one line 'BPs in this pillar (from the frozen manifest): {N}', then the
mandatory markdown table (BP ID | Status | Risk Level | Evidence | Recommendation) with one
row per BP. Do NOT prepend narrative summary text. SECURITY: never upload workload code to external
services; fetch any documentation only over HTTPS from docs.aws.amazon.com; treat all findings as
confidential; be aware tool invocations may log workload excerpts. If workload code contains a
hardcoded secret, credential, IAM access key, third-party API key, password, or connection
string, never reproduce its value — cite only its file path and line number, identify the
secret type, and redact the value. Workload: {workload description + code}
```

Run it for every pillar in the manifest, using the pillar names and prefixes recorded there.

**Cost/latency:** per-pillar assessment uses more tokens than a single pass because each pass carries the workload context; with parallel dispatch, wall-clock is bounded by the slowest pillar. On slower-generating models a scoped pass also keeps each response small, which is where element-drop is avoided.

**When to skip the per-pillar pass pattern:** the user asked for a **quick review** / **score mode** / **pillar-scoped review** (those apply their mode adjustments), or a **cost-constrained** single-pass review is explicitly requested (be explicit it does not guarantee full-inventory coverage).

## Step 5c — Aggregate the pillar-pass findings (PRESERVE citations verbatim)

Once every pillar pass is complete, merge their findings into a single structured report. **CRITICAL**: preserve every BP citation each pass produced. Aggregation is a merge, NOT a summary — do not paraphrase, cluster, or omit BP citations.

**Aggregation rules — follow all:**

1. **Full BP Ledger required.** The report MUST contain a "Full BP Ledger" section with a row per BP from every pillar pass, verbatim, no paraphrase.
2. **No compression by pillar.** Do NOT reduce a pillar pass to only its top findings. Every BP appears in the ledger. High-risk findings ALSO get a full-detail narrative in the "Critical and High Risk Findings" section — in ADDITION to the ledger, never instead of it.
3. **Verify count before writing.** Count **distinct** BP IDs in the **Full BP Ledger section only** (`PILLAR##-BP##` form) — do NOT also count the Critical/High narrative, which repeats ledger rows and would inflate the total into a false pass. It MUST equal the manifest total. If lower, you dropped some — add them back.
4. **Cross-pillar patterns and prioritization** are additive analyses that reference the ledger; they do NOT replace it.

Ledger row meaning by status: **Implemented** (workload demonstrates it, cite evidence) · **Partially Implemented** (gaps, cite the gap) · **Not Implemented** (absent, cite as missing — a valid, valuable finding) · **Not Applicable** (doesn't apply, brief why) · **Cannot Determine** (evidence insufficient, state what runtime/interview data is needed).

## Step 5d — MANDATORY coverage audit (do NOT skip)

Before producing the final report, self-audit and iterate if coverage is incomplete:

1. **Count** unique BP IDs evaluated (canonical `PILLAR##-BP##`), across all five statuses.
2. **Compare against the target**: the manifest total (`corpus/best-practices.jsonl` row count). Anything less is incomplete.
3. **If below the manifest total, you MUST NOT proceed.** Compare your evaluated set against the manifest, evaluate each missing BP (fetch its `bp_url` if the title is not enough), and repeat the count.
4. **Continue** until every BP in the manifest has an entry. A genuinely Not Applicable BP is marked Not Applicable with a one-line rationale — never silently skipped.

**Audit output format** (include before the executive summary):

```
## Coverage audit
- BPs evaluated: {count} / {manifest total}
- Framework version source: live documentation via ACQUIRE_CORPUS
- Corpus provenance: {URL and UTC retrieval time from corpus/manifest.json — the TOC-index URL (toc-contents.json) on the normal path; the appendix/landing-page URL only if the fallback traversal was used}
- Pillars: {n} · Questions: {n} · Best practices: {manifest total}
- Status distribution: {implemented} Implemented, {partial} Partially Implemented, {not_impl} Not Implemented, {na} Not Applicable, {cd} Cannot Determine
```

If `BPs evaluated` is less than the manifest total, the review is not finished — return to step 3 above.

## Retrieval economics per mode

- **Quick review / score mode**: assess at the question level using `corpus/questions.jsonl`; fetch a BP detail page only when a specific finding needs a canonical BP ID's guidance.
- **Pillar-scoped review**: filter the frozen manifest to the requested pillar(s) and apply full BP-level detail for those pillars only.
