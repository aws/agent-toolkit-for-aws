# Migration fixtures

Also see:

- `ai-migration-matrix/` — 14 target-only representative contract snapshots for infrastructure-only, AI-only, and combined migration modes. Under Option A, each run has zero or one infrastructure source; polycloud or multiple simultaneous infrastructure sources are deferred. Any one supported infrastructure source composes independently with many AI sources and optional gateways. `ai_sources[]` retains provider/service provenance, families, and exact normalized `models[]`; `model_evidence` distinguishes observed models from an explicitly empty not-observed set without fake IDs. One OpenRouter gateway can retain multiple structured provider/service/family/exact-model associations, while `upstream_evidence: unresolved` makes unknown upstreams explicit. Synthetic positive tests cover GCP, Azure, and Heroku composition; Heroku with direct Google/Gemini, OpenAI/GPT, and Anthropic/Claude; and one multi-provider, multi-family, multi-model OpenRouter scenario without Cartesian fixture directories. `expected-matrix.json` records represented contract coverage, not a versioned runtime capability catalog: free-form schema validity does not imply an implemented adapter or route. This is contract/test/documentation coverage only and changes no runtime behavior. Combined cases use one `.phase-status.json` and a separate fail-closed `integration-validation.json` cross-track verdict.
- `ai-workload-profiles/` — 4 representative target-only `ai-workload-profile.json` observation fixtures (not a Cartesian matrix): AI-only multi-direct-provider (Anthropic + Google/Vertex, no gateway); OpenAI direct plus Azure OpenAI with distinct `source_service` provenance; a multi-upstream OpenRouter gateway carrying Anthropic (two exact Claude models), Google, and OpenAI simultaneously; and an unresolved/not-yet-identified OpenRouter gateway with an explicit empty upstream set. Each source retains the raw/observed model string in `model_observations[]` alongside the exact normalized `models[]` entry, with a deterministic `provenance`/`confidence` evidence vocabulary. `test_ai_workload_profile_contracts.py` proves every fixture's normalized `ai_sources[]`/`gateways[]` projects exactly into `ai-migration-scenario.schema.json`'s semantics (`test_ai_migration_matrix_contracts.py`), and exercises negative mutations (duplicate identity, a model dropped under a resolved upstream, a fabricated `unknown` ID, OpenRouter named as a direct provider, an empty upstream on an observed gateway, an invented upstream on an unresolved gateway) rather than separate fixture directories per negative. Schema validity here does not imply an implemented detector, adapter, route, model mapping, or runtime support — no producer of this artifact exists yet.
- `aws-design-ai/` — 2 representative target-only `aws-design-ai.json` design fixtures, nested as `<case>/aws-design-ai.json` so `lint:artifacts` discovers them (unlike a flat layout, which #415's own review flagged as invisible to the lint): `multi-provider-direct` (one Anthropic-sourced and one OpenAI-sourced `design_blocks[]` entry in a single design, no gateway) and `openrouter-gateway-multi-upstream` (one OpenRouter gateway fronting Anthropic — two exact Claude models — and OpenAI simultaneously, with a 3-tier routing strategy). `metadata.ai_sources[]`/`metadata.gateways[]` replace the retired single-scalar `metadata.ai_source` field this contract previously carried; `test_aws_design_ai_contracts.py` proves both fixtures project exactly into `ai-workload-profile.schema.json`'s semantics (`test_ai_workload_profile_contracts.py`, #415's own oracle), and exercises negative mutations — the retired single-scalar `ai_source` shape (with and without a `both`-style multi-provider implication), duplicate source identity, OpenRouter named as a direct provider, a dropped model under a resolved gateway upstream, a `design_blocks[]` row without exactly one target, and a fabricated `unknown` model ID. Schema validity here does not imply an implemented detector, adapter, route, model mapping, or runtime support, and does not claim either skill's current `design-ai.md` emits this shape — no producer has been repointed to this canonical contract in this change.
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
