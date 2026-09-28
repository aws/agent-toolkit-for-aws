# Migration fixtures

Also see:

- `heroku-workshop/` — Heroku what-if workshop seed + arm64 reprice snapshot + `check_expected_workshop.py`
- `heroku-nonweb-scaling/` — Heroku Design seed + golden output for the Horizontal Non-Web Capacity Guard (`eco`/`basic` worker at `quantity: 2` → Fargate) + `check_expected_nonweb_scaling.py`
- `gcp-workshop/` — GCP what-if workshop seed + graviton reprice + `check_expected_workshop.py`

## Migration report reference fixture

`migration-report-reference.html` is a **structural reference** for the comprehensive `migration-report.html` output. It was derived from SF Beach migration artifacts (`0611-0606`) and uses canonical section IDs checked by `scripts/validate-migration-report.py`.

**Do not copy dollar figures** into customer reports unless they match the current `$MIGRATION_DIR` estimation artifacts.

## Validate (full contract)

```bash
python3 scripts/validate-migration-report.py \
  fixtures/migration-report-reference.html \
  --estimation-infra fixtures/estimation-infra-reference.json \
  --estimation-ai fixtures/estimation-ai-reference.json
```

`estimation-*-reference.json` are trimmed snapshots aligned with the HTML fixture. Together they exercise security-baseline cross-checks, the security teaser, the verdict banner, combined AWS monthly run-rate (`exec-tco`, legacy ID), and the dedicated Cost Optimization sections (`exec-optimization` / `appendix-optimization`) required when `optimization_opportunities[]` is non-empty.

## Regression stub

`migration-report-stub.html` is the inverse fixture: a deliberately non-compliant report (numbered headings, a bare `Rubric:` trace, stub appendices, no security teaser, no verdict). It **must fail** the validator — that is the point, so you can confirm the "bad report" path is still detected:

```bash
python3 scripts/validate-migration-report.py fixtures/migration-report-stub.html
# expected: non-zero exit with the failures listed
```

Do not "fix" it.

## Readability conventions enforced by the validator

The fixture is also the worked example for the readability rules the validator now enforces (not just documents):

- **No numeric "Section N" headings.** Customer-facing `<h2>`/`<h3>` headings use plain titles (e.g. "Estimated AWS Monthly Run Rate", not "Section 1 — …"). The table of contents carries structure: executive sections in an ordered list, appendices in a separate lettered list to avoid double-numbering.
- **No internal scoring trace.** Per-cluster mapping rationale lives in a collapsible `<details class="why">` ("Why this mapping?") block, never a bare `Rubric:` line.
- **Security teaser up top, full detail in the appendix.** `exec-security-teaser` carries a 2–3 line summary; the full control table and gap analysis are `appendix-security` / `appendix-security-gap`.
- **Consistent money formatting** (whole-dollar monthly figures; cents only where sub-dollar precision matters) and **expanded acronyms** (bordered two-column glossary table in the assumptions section).
- **Accessible tables and diagram**: `<caption>` + `scope="col"` on tables; the ASCII architecture diagram is wrapped in a `<figure role="img">` with an `aria-label` text alternative and a `<figcaption>`.
- **Configuration provenance (`appendix-config`).** Four-column table: Question/assumption, Your choice, Source, Design consequence — populated from `preferences.json` `prompt` and `design_consequence` fields (see `references/shared/schema-preferences.md`).
- **Ordered action lists.** `Key decisions ahead` and `Next steps` in `decision-summary` use `<ol>`, not `<ul>`.

## Section IDs are stable anchors, not placement hints

A few sections carry `appendix-` IDs but render in the executive flow by design — most notably `appendix-assumptions` (exclusions and pricing confidence are exec-relevant). IDs are stable validator/TOC anchors; **do not rename them to match position**. `appendix-security` and `appendix-security-gap` do render in the appendix in this revision, so their IDs now also match placement.

## What REPORT_OK means

`REPORT_OK | structure=complete` means required sections, TOC links, appendix depth, readability rules, and artifact-driven cloud-service run-rate checks passed. It does **not** verify that every dollar figure in the HTML matches the JSON — verify numerics manually or in a future accuracy gate before executive sign-off.
