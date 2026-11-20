# Review Modes — Mode Selection, Trigger Phrases, and Output Formats

Determine the review mode from the user's request before starting the evaluation. A limit the user states for the session (a time, or "only SEC01 and SEC02 this session") is neither a mode nor a scope: a requested full review stays full, with every manifest BP in `N`, and the limit only shortens the run, which then ends with the PARTIAL report ([bounded execution](bounded-execution.md)). In every mode the report opens with the Coverage Audit, which always carries the run line and the `Review Integrity:` line ([report template](../assets/report-template.md)).

## Full review

Default when the user says "WA review", "full review", "comprehensive":

- Evaluate every framework question in the frozen manifest produced by `ACQUIRE_CORPUS` (see [phase-live-inventory.md](phase-live-inventory.md)) — the enumeration is acquired and frozen once; do NOT re-fetch or rebuild the question/BP list during assessment
- Read the detail page of **every** BP in the frozen manifest before assigning its status — mandatory, not optional. Shard the BPs by question (at most 5 per shard) and work through the shards one at a time, or in parallel when subagents are available, with the shard files, the row self-check, the progress file and the fixed-size spot-check described in the evaluation procedure reference. A complete report requires a self-checked ledger row for every in-scope BP and a passing spot-check; a run that cannot finish delivers a bounded PARTIAL report with exact coverage (see [bounded execution](bounded-execution.md))
- Cite the specific canonical BP IDs from the frozen manifest in findings

## Quick review

Only when the user's words explicitly request it ("quick review", "high-level", "summary"). Never downgrade a full or pillar-scoped review to quick mode because of the agent's own effort, context, or time budget, or because the user seems time-constrained; if the request is ambiguous, ask (see below):

- Evaluate all framework questions at the QUESTION level only (do not fetch individual BP pages; no ledger or read-gate applies)
- Disclose in the Coverage Audit that BP bodies were not read: `BP pages read: 0 / {manifest BP total} in scope (quick mode: judged from question titles and workload evidence; BP bodies were not read)`
- Use the Step 4 frozen manifest (the question lines of `corpus/inventory/<pillar_id>.md`) to assess each question based on what you find in the code
- Flag obvious gaps but do not exhaustively check every BP
- Faster, less detailed, still covers all pillars
- Prefix the output with the same `> **Classification: CONFIDENTIAL** — …` banner the full report template uses — a quick review still surfaces sensitive infrastructure detail and unremediated findings

## Pillar-scoped review

When the user asks for a review of one or more specific pillars, by name or by the documented scope of their questions (not when a full review names a pillar or questions only as this session's limit):

- Evaluate ONLY the questions for the requested pillars
- Derive the requested pillars' questions and best practices from the frozen manifest (the `ACQUIRE_CORPUS` output), filtered by `pillar_id` — do NOT re-walk the documentation or use semantic search to re-enumerate them (that reintroduces the traversal-stall path the frozen-manifest redesign removed)
- Apply the full-review read procedure to those pillars: read every in-scope BP's detail page at its manifest URL (`aws___read_documentation`, otherwise, after a real error from it or when the session has no such reader, an HTTPS fetch of that `docs.aws.amazon.com` URL) via per-question shards, with the same ledger rows, row self-check, and spot-check. The in-scope count `N` is the BP count for the requested pillars
- Skip all other pillars entirely — do not comment on them unless a critical cross-pillar issue is obvious
- Produce a pillar-focused report whose scorecard categories come from the requested pillars' live question inventory
- Prefix the output with the same `> **Classification: CONFIDENTIAL** — …` banner the full report template uses — a pillar-scoped review still surfaces sensitive infrastructure detail and unremediated findings

After building the Step 4 frozen manifest, map the user's phrasing to the discovered pillar names based on each pillar's live documented scope, questions, and keywords. If the request could map to multiple pillars, ask the user to confirm the intended scope.

## When the mode is unclear

Ask:

> Would you like a **full review** (reads every BP page, deep BP-level analysis per question — thorough but longer), a **pillar-scoped review** (full BP-level detail for only the pillars you name), or a **quick review** (question-level assessment — faster)?
