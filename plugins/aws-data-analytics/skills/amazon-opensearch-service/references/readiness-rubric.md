# Readiness rubric

Canonical 7-dimension scoring for the FULL_ASSESSMENT readiness score (0–100, GREEN/YELLOW/RED). Cited from [`assessment-shape-full-assessment.md` §6](assessment-shape-full-assessment.md), [`assessment-workflow.md` §Step 7](assessment-workflow.md), and the various report templates in `assets/`.

## Tiers

- **GREEN ≥ 80** — proceed; surface top items to flag in §7.
- **YELLOW 60–79** — PoC + spike on weakest dimension before committing.
- **RED < 60** — do not commit; revisit weakest dimension first.

## Dimensions and weights

| Dimension | Weight | What it captures |
|---|---|---|
| Compatibility | 25 | Number/severity of **`risk-blocker`-lane** gap-register entries (see [`compatibility-rubric.md` §2](compatibility-rubric.md). `migration-specific`-lane entries do **NOT** deduct from this dimension because the migration plan already includes the remediation.) |
| Operational readiness | 15 | Team familiarity with OpenSearch, on-call coverage. |
| Sizing fitness | 15 | Confidence in instance class + count for projected workload. |
| Data-movement complexity | 15 | Volume, transformations, cutover style. |
| Cutover complexity | 10 | Downtime tolerance, dual-write feasibility, rollback plan. |
| Sizing-input completeness | 10 | How much sizing input the customer provided. |
| Stakeholder alignment | 10 | Sign-off from product/security/infra. |

## Scoring rules

1. **`migration-specific` lane is presentation, not a deduction.** A row with a clean transformer/config remediation that the migration plan already includes does not lower the Compatibility dimension. It is surfaced in §7 *Migration specifics* of the assessment so the customer knows what the path handles, but it is not scored as a gap.
2. **`risk-blocker` lane drives the Compatibility deduction.** Each BLOCKING/HIGH risk-blocker row deducts; MEDIUM and LOW risk-blocker rows deduct less. Use the Severity table in [`compatibility-rubric.md` §1](compatibility-rubric.md) to weight.
3. **Cite ≥1 gotcha by number** from [`assessment-gotchas.md`](assessment-gotchas.md) when scoring Compatibility — many gotchas are not in any AWS doc and missing them is the most common readiness gap. Whether the gotcha contributes to the deduction depends on its `Category:` tag (TRUE_BLOCKER / MIGRATION_SPECIFIC / OPERATIONAL_CONSIDERATION / COST_TCO / CLARIFICATION) — only TRUE_BLOCKER and MIGRATION_SPECIFIC-with-customer-action items deduct from Compatibility.
4. **Tier override: any BLOCKING `risk-blocker` row caps the readiness tier at YELLOW** regardless of total score, until the customer commits to the remediation path. This applies to Lucene segment wall (gotcha #3), ES ≥ 7.11 snapshot lockout (#2), Solr→OS document-level (#1), and similar.

## Worked example

A Solr 8.11 → OS 2.19 migration with: `q.op=AND` (HIGH, migration-specific), `fielddata` strip (BLOCKING, migration-specific), 4 custom JARs needing port (HIGH, risk-blocker), Solr→OS document-level (BLOCKING, risk-blocker), and full operational/cutover/stakeholder readiness:

- Compatibility: 25 − 8 (one BLOCKING risk-blocker) − 3 (one HIGH risk-blocker) = **14/25**
- Other dimensions full = **65/75**
- Total = **79/100 — YELLOW**, tier capped at YELLOW by the BLOCKING risk-blocker rule.

The two `migration-specific` items (`q.op=AND`, `fielddata`) are surfaced in §7 *Migration specifics* but do **not** affect the Compatibility score, because they are part of the migration plan, not gaps in it.
