# Review Modes — Mode Selection, Trigger Phrases, and Output Formats

Determine the review mode from the user's request before starting the evaluation.

## Full review

Default when the user says "WA review", "full review", "comprehensive":

- Evaluate every framework question in the frozen manifest produced by `ACQUIRE_CORPUS` (see [phase-live-inventory.md](phase-live-inventory.md)) — the enumeration is acquired and frozen once; do NOT re-fetch or rebuild the question/BP list during assessment
- Assess each pillar against its frozen-manifest BP set using the per-pillar pass pattern (see the evaluation procedure reference)
- Cite the specific canonical BP IDs from the frozen manifest in findings

## Quick review

When the user says "quick review", "high-level", "summary", or is time-constrained:

- Evaluate all framework questions at the QUESTION level only (do not fetch individual BP pages)
- Use the live Step 5a question inventory to assess each question based on what you find in the code
- Flag obvious gaps but do not exhaustively check every BP
- Faster, less detailed, still covers all pillars
- Prefix the output with the same `> **Classification: CONFIDENTIAL** — …` banner the full report template and score mode use — a quick review still surfaces sensitive infrastructure detail and unremediated findings

## Pillar-scoped review

When the user asks for one or more specific pillars by name or by the documented scope of their questions:

- Evaluate ONLY the questions for the requested pillars
- Derive the requested pillars' questions and best practices from the frozen manifest (the `ACQUIRE_CORPUS` output), filtered by `pillar_id` — do NOT re-walk the documentation or use semantic search to re-enumerate them (that reintroduces the traversal-stall path the frozen-manifest redesign removed). Read an individual BP's detail page at its manifest `bp_url` only when the BP's title plus the workload evidence is insufficient to judge status; prefer `aws___read_documentation`, otherwise an HTTPS fetch of that `docs.aws.amazon.com` URL, otherwise internal knowledge with disclosure
- Apply full-review BP-level detail for those pillars
- Skip all other pillars entirely — do not comment on them unless a critical cross-pillar issue is obvious
- Produce a pillar-focused report whose scorecard categories come from the requested pillars' live question inventory
- Prefix the output with the same `> **Classification: CONFIDENTIAL** — …` banner the full report template and score mode use — a pillar-scoped review still surfaces sensitive infrastructure detail and unremediated findings

After building the Step 5a inventory, map the user's phrasing to the discovered pillar names based on each pillar's live documented scope, questions, and keywords. If the request could map to multiple pillars, ask the user to confirm the intended scope.

## Score mode

When the user asks for "score", "grade", "scorecard", "matrix", or "just give me a number":

- Analyze the codebase at the provided path, or the architecture description when no code/IaC is available
- Run a quick-scan pass across all framework questions (no BP pages fetched)
- Produce ONLY a structured scorecard + filtered findings — no full narrative report
- Respect the findings filter:
  - "critical only" → show only Critical findings
  - "critical and high" → show Critical + High
  - "all" (default if unspecified) → show Critical + High + Medium + Low

Output format:

```markdown
## WA Score: {workload_name}

> **Classification: CONFIDENTIAL** — Contains security findings and unremediated gaps. Restrict distribution to authorized personnel; do not post to broadly visible channels without approval.

**Overall: {X.X}/5**

| Pillar | Score | Critical | High | Medium | Low |
|--------|-------|----------|------|--------|-----|
| {pillar from live inventory} | {1-5} | {n} | {n} | {n} | {n} |
| ...one row per discovered pillar... | ... | ... | ... | ... | ... |

### Findings ({filter} and above)
| # | Pillar | Risk Level | Finding | Evidence |
|---|--------|----------|---------|----------|
| 1 | {pillar} | {Critical/High/...} | {one-line finding} | {file:line, or "Based on description"} |
...

### Summary
{1-2 sentence takeaway: overall posture + single most impactful action}
```

Trigger phrases: "score my app", "WA scorecard", "grade this", "give me a score matrix", "how does my architecture score"

## When the mode is unclear

Ask:

> Would you like a **full review** (deep BP-level analysis per question — thorough but longer), a **pillar-scoped review** (full BP-level detail for only the pillars you name), a **quick review** (question-level assessment — faster), or a **score** (just the scorecard + top findings)?
