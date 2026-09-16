# Report Template — Full Well-Architected Review

Produce the final report with this exact structure. Do not drop sections. The Coverage audit (defined in the evaluation procedure reference) goes immediately before the Executive Summary.

```markdown
# Well-Architected Review: {Workload Name}

> **Classification: CONFIDENTIAL** — This report contains sensitive infrastructure details and unremediated security findings. Restrict distribution to authorized personnel. Do not post to broadly visible channels or ticketing systems without explicit approval.

## Coverage Audit
{Coverage audit output from Step 5d — see the evaluation procedure reference}

## Executive Summary
- **Date**: {date}
- **Workload**: {name}
- **Business Criticality**: {level}
- **Lens Applied**: {lens or "General"}
- **Packages Analyzed**: {list}
- **Questions Assessed**: {n}/{n per live documentation}
- **Findings**: {X} Critical, {Y} High, {Z} Medium, {W} Low
- **Overall Maturity**: {1-5} — {one-line justification}

## Architecture Overview
{PlantUML diagram}
{Brief description of architecture, key services, data flows}

## Pillar Scorecard
| Pillar | Score (1-5) | Questions Assessed | Key Strength | Key Gap |
|--------|-------------|-------------------|--------------|---------|
| {pillar from live inventory} | {score} | {n}/{n} | {strength} | {gap} |
| ...one row per discovered pillar... | ... | ... | ... | ... |

{Denominators come from the Step 5a question inventory — use the live counts derived from the appendix pages}

## Per-Question Assessment
| ID | Question | Status | Risk Level | Key Evidence |
|----|----------|--------|------------|--------------|
| {question ID from live inventory} | {question} | {status} | {risk or Not Applicable} | {evidence} |
| ...one row per discovered question... | ... | ... | ... | ... |

{Complete this table for every question in the Step 5a inventory — use the live count from the appendix; do not truncate}

## Full BP Ledger (MANDATORY)

**This section MUST list every BP citation produced by every pillar pass.** Concatenate every pillar table here, sorted by pillar then BP ID. Do NOT filter, cluster, or paraphrase. Every row surfaced by each pass must appear in the ledger. Target row count: one row per BP evaluated across all pillars — matching the summed per-pillar documentation counts from Step 5b.

This section is where recall reaches the user: skipping or truncating it collapses a full-inventory review down to whatever the assembler compresses to. **Do not skip this section.**

| BP ID | Pillar | Status | Risk Level | Evidence | Recommendation |
|-------|--------|--------|----------|----------|-----------------|
| {BP ID from live inventory} | {pillar} | {status} | {risk level or blank} | {evidence} | {recommendation} |
| ...one row per discovered BP... | ... | ... | ... | ... | ... |

{After writing this table, count the rows and confirm the count matches the sum of the pillar-pass rows. If not, you dropped citations — go back and add them.}

## Lens Findings (only if a lens was applied)
{Lens-specific best-practice evaluation, separate from the core findings above. Omit this section entirely for a General review.}

## Critical and High Risk Findings
{For each: ID, pillar, title, description, evidence (file:line), impact assessment, recommendation, effort, AWS services. This section EXPANDS on rows in the Full BP Ledger — it does NOT replace them.}

## Medium Risk Findings
{Same format, condensed. Also references ledger rows.}

## Low Risk Findings
{Summary table: ID | Pillar | Title | Recommendation. Also references ledger rows.}

## Cross-Pillar Trade-offs
{Conflicts between pillars and recommended resolution}

## Prioritize Improvements — Eisenhower Matrix

Not all findings should be addressed at once. Focus on a selected number of issues that make the most business impact and are easiest to implement. Then iterate.

Classify each finding by **importance** (business value) and **effort** (time, complexity, headcount):

        HIGH IMPORTANCE
             │
   ┌─────────┼─────────┐
   │  DO     │  PLAN   │
   │  FIRST  │         │
   │         │         │
───┼─────────┼─────────┼───
   │         │         │
   │DELEGATE │  DEFER  │
   │         │         │
   └─────────┼─────────┘
             │
        LOW IMPORTANCE
   LOW EFFORT    HIGH EFFORT

| Quadrant | Action | Findings |
|----------|--------|----------|
| **Do First** (High Importance, Low Effort) | Implement immediately | {finding IDs} |
| **Plan** (High Importance, High Effort) | Schedule in roadmap, break into phases | {finding IDs} |
| **Delegate** (Low Importance, Low Effort) | Batch together, assign to available team member | {finding IDs} |
| **Defer** (Low Importance, High Effort) | Revisit in next iteration | {finding IDs} |

### Solution Characteristics

For each solution in "Do First" and "Plan":
- **SMART goal**: Specific, Measurable, Achievable, Relevant, Time-bound
- **Owner**: Identify who is responsible
- **Simple over complex**: Choose the simplest solution unless complexity is a non-negotiable requirement
- **Two-way door decisions**: Solutions should be extensible and evolve over time — avoid static solutions that cannot adapt
- **Pattern-based**: Target solutions that can be codified, reused, and re-shared (reference AWS Architecture Center)

## Prioritized Remediation Plan

### Quick Wins (< 1 week) — "Do First" quadrant
| Finding | Action | SMART Goal | Owner Suggestion | Effort |
|---------|--------|-----------|-----------------|--------|
{Config changes, enabling features, adding tags/alarms — simple, high-impact}

### Foundation (1-4 weeks) — "Plan" quadrant
| Finding | Action | Phases | Effort | Dependencies |
|---------|--------|--------|--------|--------------|
{Multi-AZ, CI/CD improvements, monitoring, caching — phased approach}

### Strategic (1-3 months) — "Plan" quadrant (complex)
| Finding | Action | Phases | Effort | Dependencies |
|---------|--------|--------|--------|--------------|
{DR, re-architecture, compliance programs — two-way door design}

### Delegate (batch & assign) — "Delegate" quadrant
| Finding | Action | Owner Suggestion | Effort |
|---------|--------|-----------------|--------|
{Low-importance, low-effort fixes — batch together and assign to an available team member}

### Deferred — Revisit Next Iteration
{Findings in the "Defer" quadrant with brief justification for deferral}

## Next Steps
{Top 5 concrete actions from the "Do First" quadrant — the team should start this week}
```
