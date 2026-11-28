# Report Decision Core (canonical, cloud-agnostic)

## What this file is

This is the **canonical decision core** for every migration report the plugin
renders: the single source of truth for verdict, cost, timeline, risk, and
assumption rendering, and the prose side of the contract that
`$PLUGIN_ROOT/scripts/validate-migration-report.py` (the shared validator)
checks by machine. It is vendored byte-for-byte into each migration skill; the
skill's own `report-decision-core.md` (the **skill layer**) loads this copy
first and then supplies the values written here as `⟨parameter⟩` — the source
cloud's name, its cost keys, its service tables, its call-to-action copy. Read
nothing outside the skill you are running: the skill layer plus this vendored
copy are the only two files the decision core needs.

Where this file and the shared validator disagree, the validator wins — report
the discrepancy rather than working around it.

## Modes

The decision core renders in one of three modes. The content rules are
identical in all of them; the mode decides which sections exist and what
surrounds them.

| Mode         | Output                                                                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **decision** | Standalone `decision-report.html` + `DECISION.md` at the post-Estimate Decision gate — decision core only, no appendices, CTA footer                                 |
| **full**     | The executive-summary block of `migration-report.html` after Generate, followed by the appendices                                                                    |
| **ai_only**  | `migration-report.html` for a run with no infrastructure track (no design, infra estimate, or Terraform) — decision core + assumptions + risks + the AI appendices |

Which of these modes a skill uses, and which of its phase files load the core
in each mode, is ⟨modes_used⟩ / ⟨loaders⟩ — supplied by the skill layer.

**Never patch one output into the other.** When Execute runs after a Decide
run, `migration-report.html` is rendered **fresh from the artifacts** — do not
extend, edit, or splice `decision-report.html`. All data needed for any output
lives in the JSON artifacts.

## Section model and stable IDs

Every rendered section is `<section id="…">` with one of the stable IDs below.
The shared validator checks the per-mode required set, that every TOC link
resolves to a rendered section, and that every required section has a TOC
link.

**Required in `full` mode** (`REQUIRED_SECTION_IDS`): `decision-summary`,
`exec-assumptions`, `exec-services`, `exec-costs`, `exec-timeline`,
`exec-risks`, `appendix-services`, `appendix-costs`, `appendix-steps`,
`appendix-artifacts`.

**Required in `decision` mode** (`DECISION_REQUIRED_SECTION_IDS`):
`decision-summary`, `exec-assumptions`, `exec-services`, `exec-costs`,
`exec-timeline`, `exec-risks`, `decision-cta`. Decision mode forbids every
`appendix-*` section — no Generate artifacts exist yet.

**Required in `ai_only` mode** (`AI_ONLY_REQUIRED_SECTION_IDS`):
`decision-summary`, `exec-assumptions`, `exec-risks`, `appendix-ai`,
`appendix-artifacts`, `appendix-config`, `appendix-glossary`. An AI-only run
cannot populate the infrastructure sections (`exec-services`, `exec-costs`,
`appendix-services`, `appendix-costs`, `appendix-steps`) and must not stub
them.

**Conditional sections** (`OPTIONAL_SECTION_IDS`) render only when their
trigger holds, and join the TOC only when rendered:

| ID                      | Trigger                                                                                                     |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- |
| `exec-share`            | an estimation artifact exists for the run (see § Share With Your CFO)                                       |
| `exec-tco`              | both an infrastructure estimate and an AI estimate exist                                                    |
| `exec-architecture`     | the design artifact has clusters (required in `full` mode; render it in `decision` mode too)                |
| `exec-security-teaser`  | `projected_costs.breakdown` carries a `security_baseline` entry                                             |
| `exec-optimization`     | any estimation artifact has a non-empty `optimization_opportunities[]`                                      |
| `what-if-scenarios`     | `$MIGRATION_DIR/scenarios/index.json` lists two or more scenarios                                           |
| `appendix-ai`           | an AI track exists (`full` / `ai_only`)                                                                     |
| `appendix-config`       | `preferences.json` exists (`full` / `ai_only`; required in `ai_only`)                                       |
| `appendix-security`     | a security baseline was designed (`full`)                                                                   |
| `appendix-security-gap` | a source-cloud security posture exists to gap-compare (`full`)                                              |
| `appendix-assumptions`  | `full` mode, when the skill renders assumptions, exclusions, and validation as an appendix                  |
| `appendix-optimization` | `full` mode and `optimization_opportunities[]` non-empty (the line-level table; see § Cost Optimization)    |
| `appendix-glossary`     | `full` / `ai_only` (required in `ai_only`; the default `full` contract also requires it — see glossary rule) |

A skill whose required set differs in **shape** from the default declares a
profile — see § Declared skill exceptions. ⟨required_ids⟩ (the default sets
above, or the profile's sets) is supplied by the skill layer.

### Appendix lettering (full mode)

Appendix letters are stable: the letter is part of the `<h2>` heading and of
the TOC label, and it does **not** shift when a conditional appendix is absent
(a run with no AI track has no Appendix D and still labels its artifact catalog
Appendix E). The shared validator checks section IDs, not these letters; the plugin's contract test pins the lettering table, so a skill keeps the labels exactly as written here.

| Section ID              | Visible heading prefix                               |
| ----------------------- | ---------------------------------------------------- |
| `appendix-services`     | Appendix A — Service Recommendations                 |
| `appendix-accounting`   | Appendix A.1 — Generation Accounting (skill add-on slot) |
| `appendix-costs`        | Appendix B — Cost Estimates                          |
| `appendix-optimization` | Appendix B.1 — Savings Plans and Reserved Instances  |
| `appendix-steps`        | Appendix C — Migration Steps and Rollback            |
| `appendix-ai`           | Appendix D — AI Migration                            |
| `appendix-artifacts`    | Appendix E — Generated Artifacts Catalog             |
| `appendix-config`       | Appendix F — Your Configuration                      |
| `appendix-security`     | Appendix G — Security Capabilities                   |
| `appendix-security-gap` | Appendix H — Security Gap Analysis                   |
| `appendix-assumptions`  | Appendix I — Assumptions, Exclusions, and Validation |
| `appendix-glossary`     | Appendix J — Glossary                                |

The appendix block opens with a `<div class="appendix-header">` divider
between the last executive section and Appendix A. A skill that adds its own
appendix uses a dotted slot (as A.1 does) so the shared letters never move.

**`appendix-config` provenance columns:** when rendered, the table's `<thead>`
must carry a "Question" (or "Assumption") column from `preferences.prompt`, a
"Your choice" column, a "Source" column (user answer / extracted / default),
and a "Design consequence" column from `preferences.design_consequence`, with
at least two rows.

**Glossary rule:** `appendix-glossary` renders its terms as
`<table class="glossary-table">` with "Term" and "Meaning" column headers and
at least three rows.

**Appendix depth floors:** `appendix-costs` needs at least three content
blocks (tables or paragraphs), `appendix-services` and `appendix-steps` at
least two. A section that only says "see `estimation-infra.json`" or lists
`aws-design.json` is a stub and fails.

## Decision-mode contract

- **Artifacts available:** discovery + `preferences.json` + `aws-design*.json` + `estimation-*.json` (+ `migration-preview.json`, `scenarios/` when present, when the skill emits them). `generation-*.json` and `terraform/` do NOT exist. Sections that prefer Generate artifacts carry an inline **_Decision mode:_** override next to the full-mode rule (decision-summary item 4, the architecture diagram, the cost footnote, the security teaser, timeline, risks) — **those inline overrides are the authoritative decision-mode law**; when a section has no override, its rule applies unchanged in both modes.
- **HTML shell:** same `<head>` (charset, viewport, inline CSS) and CSS specification as the full report, title "⟨source_cloud⟩ to AWS Migration Assessment — Decision Report". Body contains ONLY the `executive-summary` div with the exec sections and TOC (TOC links only to sections present; `nav.toc` carries `id="toc"` and every section `<h2>` ends with the `↑ contents` toplink per the nav-aids CSS spec). Opening order follows the hero-is-the-thesis rule: `decision-summary` first, TOC after it. Required section IDs are the `decision` set from § Section model (or the skill's declared profile set), plus the conditional sections per their triggers.
- **CTA footer (required, after the last section):** `<section id="decision-cta">` — "**Ready to execute?** Say "⟨decision_cta_text⟩" and I'll produce …" naming what the execution pack contains, from this same analysis. Plus one fixed line: "This decision report was generated without execution artifacts; the full migration report replaces it if you proceed." The quoted say-this sentence and the artifact list are ⟨decision_cta_text⟩ — supplied by the skill layer.
- **`DECISION.md` (required twin):** same content as the HTML, as plain Markdown (Slack/GitHub-friendly): verdict headline, cost table, migrate-if/stay-if lists, timeline shape, top risks, assumptions, CTA line. No HTML tags. A skill that adds parts declares them in its layer (⟨decision_md_extras⟩).
- **Footer:** the "draft for review" disclaimer (see § Draft footer) applies to `decision-report.html` as well as to the full report.
- All content rules below apply unchanged: baseline-quality badge + not-comparable rule, cost labeling ("Est."), readability (no artifact filenames in exec sections, no "Section N" headings, ordered action lists), startup-credits wording rules.

### Validation

Run the shared validator before presenting any report, in every mode:

```sh
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" <report.html> --mode <decision|full|ai_only> --migration-dir "$MIGRATION_DIR" [--estimation-infra <path>] [--estimation-ai <path>] [--aws-design <path>] [--profile <name>]
```

- `REPORT_OK` on stdout and exit 0 means the contract holds. `REPORT_FAIL` with exit 1 lists every failing rule — fix the report and re-run; never present, rename-around, or skip a failing report. Any other exit code is a tooling error (missing file, bad flag), not a contract result.
- Pass the estimation (and design) files when they exist so the cost-anchor, share, security-teaser, and Cost Optimization gates can fire. Use absolute paths.
- `--migration-dir` is required on a real run — the validator reads `scenarios/index.json` from it, and the what-if column check only fires when that index lists two or more scenarios; omit it only when validating a checked-in fixture.
- `--profile <name>` is passed only by a skill that declared a profile (§ Declared skill exceptions).
- The skill-specific invocation — which artifact flags the skill has, whether it passes `--profile`, and any skill-local add-on validator that must also print `REPORT_OK` — is ⟨validator_invocation⟩, supplied by the skill layer. The shared validator is required: a skill-only install without `$PLUGIN_ROOT/scripts/validate-migration-report.py` fails closed at Generate.

---

## Opening order and executive summary

The executive summary is the first thing visible when opening the report. Design it to fit approximately 1–2 printed pages.

**Header:** "⟨source_cloud⟩ to AWS Migration Assessment" with subtitle "Executive Summary" and the generation date in ISO 8601 (`YYYY-MM-DD`).

**Table of contents (required — placed AFTER the decision summary, never before it):** Linked `<nav class="toc" id="toc" aria-label="Table of contents">` listing all executive sections and appendix sections present in this report. **Every `href="#section-id"` MUST match a `<section id="section-id">` on the page exactly** (same string, including hyphens). Omit TOC links only for sections not rendered.

**The hero is the thesis (opening order):** the reader's first screenful is the decision, not navigation. Page order: title line → `decision-summary` (verdict headline + hero metrics) → TOC → remaining sections. An 18-link menu between the title and the verdict makes the reader scroll past chrome to learn the answer; the document's thesis — "Go, with conditions · $X/mo · phased, long pole: database cutover" — must be visible before any menu.

**Target length:** approximately 2–4 printed pages for executive summary. _Full mode only:_ **Do NOT truncate appendices** to fit page count — appendices may be long.

**Anti-stub rule (mandatory; the appendix clauses apply in full mode only):** every rendered section MUST carry real artifact data as HTML tables and prose. **Forbidden:** sections that only say "see `estimation-infra.json`" or list JSON filenames without numeric costs, service mappings, or migration phases. The skill layer names a reference fixture to compare against (⟨reference_fixture⟩).

**Executive vocabulary (validator-enforced):** inside `decision-summary`, `exec-share`, `exec-tco`, `exec-services`, `exec-costs`, `exec-architecture`, `exec-security-teaser`, `exec-optimization`, `what-if-scenarios`, `exec-timeline`, and `exec-risks`, never print an artifact filename (`*.json`) or a Terraform resource address (`aws_x.y`). Those are build vocabulary and belong in the appendices.

## Decision summary (`decision-summary`, REQUIRED)

Pull from the infrastructure estimate (`estimation-infra.json`) → `recommendation` block. Fallback chain if `recommendation` is absent:

1. `estimation-infra.json` → `financial_summary.recommendation` (string) — use as `path_label`; synthesize `migrate_if` / `stay_if` from the skill's documented prose defaults (⟨fallback_chain⟩).
2. Any further fallback the skill has (for example a pre-Estimate preview artifact that carries complexity and timeline only, labeled "Full recommendation requires Estimate phase") is ⟨fallback_chain⟩ — supplied by the skill layer.

Content when `recommendation` block exists:

1. **Verdict (typography-first — the verdict is the thesis of this section):** When `recommendation.outcome` exists (v2 artifacts), render `outcome_label` as the section's **headline statement** in large display type (e.g. `<p class="verdict-headline">Go, with conditions</p>`), followed by one labeled metadata line in body type: "Execution shape: [path_label] · Complexity: [complexity]". The hierarchy encodes the real relationship — the decision is the headline; how and how-hard are attributes of it. Do **not** render the verdict as a row of colored pill badges (`badge-verdict-*`): structure should carry the information, and meaning must never depend on color alone (a muted color accent on the headline is fine; the words carry the verdict). When `outcome` is absent (pre-extension artifacts, or artifacts that carry `path` instead), the same treatment applies with `path_label` as the headline. When `conditional_go`: render `conditions[]` as a short checklist directly under the metadata line. When `defer_for_evidence`: lead with what IS established ("AWS can host this stack; AWS-side estimate $X–$Y/mo" + the designed-slice mapping), then the named missing evidence and how to obtain it — do not show a savings headline as if the decision were made, and do not present defer as "no answer."
   1a. **Recommendation callout (required):** Render the one-sentence
   recommendation narrative directly below the headline/meta as
   `<div class="verdict">…</div>`. For `go`, `conditional_go`, and
   migrate-path legacy outcomes, use the green positive callout treatment
   defined by the shared CSS. For `stay` or `defer_for_evidence`, use the
   warning/neutral variant instead — never use green to imply approval. The
   explicit recommendation words remain required; color is only a scanning
   aid.
   1a. **Per-track disposition line (required when `recommendation.track_outcomes` exists):** one line under the verdict metadata, plain names, one clause per track — e.g. "By track: Compute + database: **go**. AI text: **go**. AI image: **conditional** — keeps the current provider via the adapter until the quality eval passes; does not gate the rest. Analytics: **deferred** — specialist track, parallel." Render the track note verbatim. **Never render a track-scoped condition as a whole-stack stay reason**: the Stay-if list holds only entries the artifact scoped to the whole stack; track-prefixed conditions render in the conditions checklist and the track line. Omit silently for single-track or pre-extension artifacts.
   1b. **Confidence pointer:** one line under the verdict block — `Confidence: [confidence] — full basis in <a href="#exec-assumptions">What This Assessment Rests On</a>.` Where the confidence value comes from is ⟨confidence_source⟩ (supplied by the skill layer). The full assumptions panel lives at the **end** of the executive summary (see § What this assessment rests on), not here.
2. **Complexity:** "Simple", "Moderate", "Complex" (or the skill's tier names) as a colored badge whose words carry the meaning. Which artifact field holds it is ⟨complexity_source⟩ — supplied by the skill layer.
3. **Cost headline:** `estimation-infra.json` → the **Balanced** AWS estimate (`cost_comparison.option_b_balanced` / `projected_costs.aws_monthly_balanced`) vs the current ⟨source_cloud⟩ baseline at ⟨current_monthly_path⟩ (legacy comparison keys, when the skill has them, are part of that parameter). When the skill emits a pre-Estimate preview artifact: do NOT use its `cost_preview` when the estimation artifact exists (preview is superseded). If only preview exists **and** `cost_preview.quote_suppressed` is true: do **not** render a dollar headline or "Early estimate (±30%)" — render "AWS monthly cost withheld at Discover — authored Terraform sizes exceed preview defaults. Run Estimate after Clarify." If only preview exists and the quote was **not** suppressed: show labeled "Early estimate (±30%) — full analysis not yet run."
4. **Timeline:** week counts are never rendered in either mode — the plugin has no calibrated duration data. Timeline is **shape + stage order + duration drivers**. _Full mode:_ approach + the binding duration driver from the generation plan's `migration_plan.duration_drivers[]` (e.g. "Phased, in dependency order — long pole: database cutover"). _Decision mode:_ the path-shape phrasing from ⟨duration_driver_source⟩ (a preview `duration_hint` or the complexity tier's driver summary, as the skill layer names it); label it "**if you execute**". **Legacy artifacts:** when an old artifact carries `total_weeks` or `timeline_hint` week ranges, render only with the visible label "Legacy planning heuristic (uncalibrated): N weeks" — never bare. In neither mode use `recommendation.next_steps` as timeline — those are action items, not duration.
5. **Migrate if / Stay entirely if:** from `recommendation.migrate_if` and `recommendation.stay_if`. Render as two compact lists. The customer-facing second heading is **"Stay entirely if"** so a track-scoped hold (for example, keeping image generation on the current provider) cannot be mistaken for a recommendation to abandon the whole migration. The `stay_if` list contains whole-stack reasons only. For deferred analytics (⟨deferred_analytics_example⟩): **do not** frame specialist engagement as a reason to stay on ⟨source_cloud⟩ unless the user must cut over analytics in the **same window** as app infra. Prefer migrate-if bullets that mention parallel specialist planning. When track-scoped caveats exist, add one muted sentence after the lists explaining which track can remain on the source platform without blocking the rest.
6. **Key decisions ahead:** **ordered list** (`<ol class="compact">`), not bullets. Each item is one concrete decision the reader must make next. Where the items come from is ⟨key_decisions_source⟩ — supplied by the skill layer.
   6b. **What would flip this (v2 artifacts):** from `recommendation.would_flip_if[]` when present — a heading whose text contains "What would flip this" followed by a list that renders **every** entry, immediately after Migrate if / Stay entirely if. Skip silently when the field is absent.
7. **Next steps (optional):** from `recommendation.next_steps` — **ordered list** (`<ol class="compact">`) of actionable steps separate from timeline. Numbered sequence implies priority order; keep `Migrate if` / `Stay entirely if` as unordered lists. When generated artifacts contain fill-in placeholders, the FIRST next step MUST state execution readiness: "Fill in the [N] account-specific values (emails, account ID, image URI — ⟨fill_in_checklist_name⟩) — nothing can be applied until then." The report is the decision document; this line is the bridge from decision to execution.

**Metric hierarchy (required whenever `recommendation` exists):** the reader should not have to rank the numbers themselves. The one or two **primary** decision metrics — the combined (or single-track) AWS run rate, and the migration shape (approach + binding driver, e.g. "Phased · long pole: database cutover") — render first with `.metric-hero` treatment (larger value, accent border). At least one `.metric-hero` card is required whenever `recommendation` exists — the validator fails a decision summary with none. Supporting metrics (per-track costs, savings percentages) follow as standard cards, max ~5 total. Never render a week count or effort-hours as a metric card.

Source: estimation artifact `recommendation`, the skill's pre-Estimate preview when it has one, design artifact.

## Share With Your CFO (`exec-share`, REQUIRED whenever an estimation artifact exists for the run)

Render immediately after the TOC. This is a copy-ready, one-paragraph decision
brief derived only from values already shown in the decision summary:

- verdict and confidence;
- estimated AWS monthly run rate (combined when comparable, otherwise the
  available track estimate with its scope);
- source baseline only when it is comparable, otherwise say that actual
  ⟨source_cloud⟩ billing must be confirmed;
- migration shape and binding duration driver;
- at most three conditions or evidence gaps.

Use `<div class="share-card"><p>…</p></div>` with exactly one substantive
paragraph (at least 20 words) and a short lead-in ("The one-paragraph version,
ready to forward:"). Do not add JavaScript, a copy button, editable controls,
or new calculations. The paragraph must stand alone when pasted into email or
a planning document. Label every modeled amount as estimated and preserve the
same comparability caveats as the cost section. In decision mode, omit
Generate-only facts. Add `exec-share` to the TOC only when rendered. The
validator requires this section whenever `--estimation-infra` or
`--estimation-ai` is passed.

## Deferred services and startup credits

**Deferred services flag:** If ANY resource in the design artifact has `aws_service == "Deferred — specialist engagement"`, add a prominent callout inside `decision-summary`:

> ⚠️ **Specialist engagement required:** [service name] does not have an automated AWS mapping from this plugin. Engage your AWS account team and/or a data analytics migration partner to evaluate the best AWS analytics path. This does **not** block phased migration of other services; exclude [service name] from the combined estimated AWS monthly run rate until the target architecture is defined.

A skill with a service-specific next step for a deferred service renders it directly under this callout as a declared add-on in its layer. Never block or delay the report on it.

**Startup credits callout (decision summary / verdict):** the status value lives at ⟨activate_status_path⟩ and the exact copy per status is ⟨activate_copy⟩ — both supplied by the skill layer. The semantics are fixed:

| Status               | Verdict / metric copy                                                                                                                                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `eligible_founders`  | May state Founders-tier eligibility and link `STARTUP_PROGRAMS.md`                                                                                                                                                                 |
| `eligible_portfolio` | May state Portfolio credits and the Org ID requirement                                                                                                                                                                             |
| `has_credits`        | Note existing credits; no "apply for" language                                                                                                                                                                                     |
| `unknown`            | **Neutral only:** e.g. "Review AWS Activate tiers in `STARTUP_PROGRAMS.md` — funding stage not confirmed in Clarify." **Do not** write "Eligible Founders tier", "your status: eligible_*", or dollar amounts tied to a specific tier in the verdict |

**Sidebar callout box:** Show the 💡 Activate callout when the status is **not** `unknown`, **or** when `unknown` but you use the neutral wording above (optional). When `unknown`, do **not** imply a confirmed tier. **The Activate item is ALWAYS this callout, never a metric card** — it is a call-to-action with a link, not a measurement, and rendering it in the metric grid gives it false equivalence with the run-rate and timeline figures. The clickable apply link goes inside the callout. A skill that has no startup-program question and no status field declares the omission in its layer and renders no callout.

Do **not** infer Activate tier from the spend fields (⟨spend_fields⟩) in the report or in `estimation-*.json` ROI bullets.

**Apply link (required):** Whenever the report or `STARTUP_PROGRAMS.md` mentions AWS Activate credits, include at least one clickable link to the official apply page: `<a href="https://aws.amazon.com/startups/credits/">AWS Activate credits</a>` (HTML report) or `[AWS Activate credits](https://aws.amazon.com/startups/credits/)` (Markdown). Place it in the decision-summary verdict, a callout, and/or the Next steps ordered list — not only in the appendix artifact catalog. The validator requires the link inside `decision-summary` whenever Activate is mentioned there.

## Estimated AWS Monthly Run Rate (`exec-tco`, REQUIRED when both an infrastructure estimate AND an AI estimate exist)

`exec-tco` is a legacy structural ID retained for validator compatibility; the
customer-facing heading MUST NOT say "TCO" or "Total Cost of Ownership." This
assessment models recurring cloud-service charges, not staffing, operations,
support, migration labor, or other ownership costs.

Show the combined estimated AWS monthly cloud-service run rate **excluding**
deferred services:

| Row            | ⟨source_cloud⟩                                           | AWS Balanced                                | Notes                                                              |
| -------------- | -------------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------ |
| Infrastructure | ⟨current_monthly_path⟩                                   | `projected_costs.aws_monthly_balanced`      | From infra estimate                                                |
| AI / ML        | ⟨ai_spend_key⟩ or AI band midpoint                       | `cost_comparison.projected_bedrock_monthly` | From AI estimate                                                   |
| **Combined**   | sum only when all source baselines are comparable        | sum                                         | No overall Δ/% if any source baseline is partial or not comparable |

If `estimation-ai.json` → `optimized_projection` exists, footnote the optimized AI path separately.
Add one sentence: "This is an estimated cloud-service run rate, not total cost
of ownership." When the infrastructure baseline is inventory-derived or
standing-charges-only, show "Not comparable" in the combined ⟨source_cloud⟩
cell and never sum it with a user-stated AI midpoint.

If `estimation-ai.json` → `optimization_opportunities` contains a
`provisioned_throughput` entry, add one footnote: "Provisioned Throughput
(a Bedrock-specific commitment option) uses no-commit, 1-month, or 6-month
terms — not the 1-year/3-year Reserved Instance or Savings Plan terms shown
elsewhere in this report." This is the first place a reader sees the combined
run rate — do not rely on the full report's appendix alone to make this
distinction.

A skill with no AI track declares in its layer that `exec-tco` is never rendered.

Source: `estimation-infra.json`, `estimation-ai.json`

## Current Stack Overview (`exec-services`)

- Count of ⟨source_cloud⟩ services detected from the design artifact, filtered the way the skill layer specifies (⟨stack_overview_filter⟩ — e.g. primary classification only, excluding secondary/supporting resources such as default network rules).
- List each service with its type (e.g. "[managed container service] (compute)", "[managed database] (database)").
- Source: design artifact (filtered)

## Recommended AWS Architecture

- Table with columns: ⟨source_cloud⟩ Service, AWS Service, **How we chose this**
- **How we chose this** values use the plugin's user-facing mapping vocabulary — **Standard pairing** (`deterministic`), **Tailored to your setup** (`inferred`), **Estimated from billing only** (`billing_inferred`). Show the **bold phrase** in the table; JSON value optional in a tooltip or footnote for technical readers only. Where that vocabulary is defined for the skill is ⟨how_we_chose_vocabulary_ref⟩.
- One row per mapped service
- If any service has `human_expertise_required: true`, mark it with a warning indicator and footnote: "Specialist guidance recommended — contact your AWS account team". A skill with a service-specific next step (see § Deferred services) ends the footnote with a pointer to it.
- Source: design artifact

### Architecture diagram (`exec-architecture`, REQUIRED in full mode when the design artifact has clusters)

ASCII or structured diagram showing: users → load balancer → compute → database/storage/AI; security baseline box; deferred services called out. Wrap a diagram in `<figure role="img" aria-label="…">` with a `<figcaption>` (see § Accessibility).

_Full mode:_ include **migration cluster order** from the generation plan (`generation-infra.json` → `migration_plan.cluster_order`). Source: `aws-design.json`, `generation-infra.json`. The validator requires this section in full mode whenever `aws-design.json` has clusters.

_Decision mode:_ render the diagram from `aws-design.json` clusters only — **omit cluster order** (`generation-infra.json` does not exist yet). The validator does not require it in decision mode; render it anyway when clusters exist. Source: `aws-design.json`.

## Cost Comparison (`exec-costs`)

- Side-by-side display: Current ⟨source_cloud⟩ Monthly vs Estimated AWS Monthly (**Balanced** tier — the right-sized figure the generated Terraform implements, and the default scenario for comparing to ⟨source_cloud⟩)
- **Baseline-quality badge (required):** label the ⟨source_cloud⟩ figure using `current_costs.source` and the skill's display-label table (⟨baseline_label_table⟩ — e.g. "Measured from your ⟨source_cloud⟩ billing (±5%)" / "Estimated from resource configs (±20–30%, standing charges only)" / "Your stated spend band from Clarify" / "Your stated figure (unverified)"). **Never** place an inventory-only ⟨source_cloud⟩ figure beside a user spend band without the explicit not-comparable line — they measure different things.
- Percent change (savings or increase)
- Render supported savings values with the green `.savings` class and supported
  increases with `.increase`. Never color a percentage as savings when the
  ⟨source_cloud⟩ and AWS baselines are not comparable; use an absolute
  estimated-cost card plus the not-comparable note instead.
- **Cost labeling rule:** All dollar figures in cost tables and metrics MUST be labeled as estimated monthly costs. Use column headers like "Est. Monthly AWS" or "Estimated Monthly" — never present figures as exact amounts.
- **Whole dollars (validator-enforced):** monthly-scale figures (two dollars or more) render to the nearest whole dollar — `$1,415/mo`, `$113`; cents appear only on totals below two dollars, such as `$0.40`, and on per-unit rates with an explicit unit suffix such as `/hr` or `per GB`. The validator rounds both the rendered figure and the JSON value the same way before comparing them.
- **Cost-figure anchors (machine-checkable, both modes).** Wrap the Balanced AWS
  monthly figure and the current ⟨source_cloud⟩ monthly figure inside `exec-costs`
  with a `data-cost-key` attribute, so the shared validator can confirm the
  rendered dollars match the estimate. The four anchor keys are:
  `aws_monthly_balanced` (value = `projected_costs.aws_monthly_balanced`),
  `aws_monthly_premium` (`projected_costs.aws_monthly_premium`),
  `aws_monthly_optimized` (`projected_costs.aws_monthly_optimized`), and
  `current_monthly`. The validator resolves `current_monthly` from one
  candidate JSON path per source cloud; **the skill layer names the path it
  uses** (⟨current_monthly_path⟩). Example:
  `<strong data-cost-key="aws_monthly_balanced">$155</strong>`. The attribute is
  not reader-visible text. **The two required anchors — `aws_monthly_balanced`
  and `current_monthly` — are mandatory whenever their JSON value exists and
  `exec-costs` is rendered, in decision mode as well as full mode** — a missing
  required anchor is a validator FAIL, not a skip. `aws_monthly_premium` and
  `aws_monthly_optimized` are optional (skipped when absent) unless the skill
  layer requires them. The anchor must sit inside `exec-costs` itself; a figure
  repeated elsewhere in the decision summary (e.g. a hero metric) does not
  satisfy this rule.
- **Not-comparable rendering:** the mandatory not-comparable warning is NOT collapsible and does not sit as a paragraph between the heading and the numbers — attach it to the ⟨source_cloud⟩ figure itself: a `.chip-warn` pill ("⚠ not comparable") on the metric card plus the one-line explanation in its `<small>` (what the figure measures, what the stated band measures, "do not read a savings %").
- **How to read cost tiers (required when infra estimation with three tiers exists; rendered as a `<details class="reading-guide">` immediately AFTER the tier table — data first, explanation adjacent):** The three AWS monthly figures are **estimated monthly costs** for the **same** mapped architecture (same services in `aws-design.json`), not three different generated Terraform stacks. **Order = highest → middle → lowest** monthly estimate in this model. Use **Balanced** as the **primary** row vs ⟨source_cloud⟩. **The tier rule is plugin-wide and every skill applies it identically:**
  - **Balanced** = the **right-sized** figure for the design (equal to like-for-like when no utilization data exists), priced at on-demand rates. The generated Terraform implements Balanced.
  - **Premium** = Balanced **plus the resilience uplift**: the Multi-AZ / HA uplift on each line whose HA handling allows it (a `multiplier_x2` not yet applied, or a single-AZ rate that has a cached Multi-AZ variant). Lines already Multi-AZ, baked-in Multi-AZ, or intrinsically Multi-AZ get no uplift. No generation or instance-family skew. When no line qualifies, Premium equals Balanced — say so in the row.
  - **Optimized** = Balanced **with a commitment discount applied only to the RI/SP-eligible subtotal** (per the shared `ri-sp-eligibility.md`), at the tier rates in the shared `commitment-discount-ranges.json` (vendored into every skill at `references/vendored/estimate/`; Compute Savings Plan 0.30, Database Savings Plan 0.20 — the shared 1-year no-upfront tier rates; a service AWS caps lower, such as Lambda duration at 0.12, uses its `service_caps` entry in that file); the ineligible subtotal is unchanged. **A provisioned database or cache line takes the Database Savings Plan only when its recorded instance class is Generation 7 or newer** (the integer in the family token: `db.t4g` is 4, `db.m6g` is 6, `cache.t3` is 3, `db.r7g` is 7), and ElastiCache only when it is Valkey (AWS Savings Plans FAQ, read 2026-11-27); a line with no recorded class is ineligible, never assumed. Serverless offerings and DynamoDB / Keyspaces throughput are not generation-gated. State the rate(s), both subtotals, and for every ineligible database or cache line why it is ineligible and that a Generation 7+ class would qualify, in the estimate artifact (`_optimized_basis`).
  - **Estimates written before this rule (no tier basis):** when `projected_costs._premium_basis` or `projected_costs._optimized_basis` is absent from `estimation-infra.json`, the reading guide must say the Premium and Optimized figures were produced under the earlier tier definitions, recommend re-running Estimate, and must NOT restate the derivations above as if they applied to those figures.
  - **When two or three tier figures are equal, say why where the reader sees them** — one sentence in that tier's table row (subtitle or "what differs" cell) AND one sentence in this reading guide. Premium = Balanced: _"Premium equals Balanced because every line that can take a resilience uplift is already multi-AZ in this design; there is no higher-availability variant to price."_ Optimized = Balanced: _"Optimized equals Balanced because none of the priced lines is eligible for a commitment discount, so there is no commitment scenario to price."_ Never leave equal figures unexplained, and never pad a tier with an artificial delta to avoid the equality.
  - Spot pricing, S3 Infrequent Access / Intelligent-Tiering, and every other consumption-model or storage-class assumption are **never** part of a tier — they are `optimization_opportunities[]` rows (incremental post-migration items).
  - Tier names are **pricing scenarios for the same design, never different builds**.
  ⟨tier_semantics⟩ is the skill layer's **declaration of which artifact keys hold each tier** (and any per-line fields) — a mapping, not a redefinition; a layer never changes what a tier means. When `terraform/` is present, it implements **one** infrastructure baseline aligned with the **Balanced** cost scenario (see `terraform/README.md` and `migration_summary` output).
- If 3 tiers available: show **Premium**, **Balanced**, and **Optimized** with **short subtitles** (second line or subtext under each label; the subtitle text is ⟨tier_subtitles⟩, default below), plus a **"vs Balanced, for this stack" column** from `projected_costs.scenario_deltas` when present — the itemized differences are the decision content (a reader must be able to answer "what would I buy at Premium / give up at Optimized?" from the table alone). Premium cells name the uplifted lines and the rate applied (e.g. "RDS Multi-AZ instead of single-AZ (+$12/mo)"); Optimized cells name the commitment, the rate and the eligible line (e.g. "1-year no-upfront Compute Savings Plan on Fargate at 30%, the mid-point of 20–40% (−$7/mo)"). Spot, storage-class and other consumption-model rows belong in `exec-optimization`, never in a tier cell. Balanced's cell is "— anchor; matches generated Terraform" (full mode) or "— anchor" (decision mode). When `scenario_deltas` is absent (pre-extension artifacts), omit the column — do not invent deltas. Do NOT expand the generic tier definitions to compensate; the reading-guide `<details>` already covers same-architecture semantics:
  - **Premium** — _Balanced plus the Multi-AZ / HA uplift_
  - **Balanced** — _Right-sized design at on-demand rates; compare ⟨source_cloud⟩ to this row first_
  - **Optimized** — _Balanced with a commitment discount on RI/SP-eligible lines_
- **Footnote (required):** _All figures are estimated monthly costs based on AWS pricing data at time of analysis._ Then, _full mode:_ _Only one Terraform configuration is generated (Balanced-aligned, right-sized baseline). Premium and Optimized are pricing scenarios for the same design — the resilience uplift and the commitment discount in `estimation-infra.json` — not different builds; adjust IaC yourself if you want the Premium posture in production._ _Decision mode:_ _If you generate the execution pack, its Terraform will align with the Balanced scenario; Premium and Optimized are pricing scenarios for the same design (resilience uplift / commitment discount), not different builds._
- **Only include "⟨source_cloud⟩ data transfer egress (est.)" when the infra estimation artifact has `migration_cost_considerations.billing_data_available === true`.** Never present human one-time migration costs. If `false` or only non-infra estimates exist, footnote: "⟨source_cloud⟩ data transfer egress estimates require billing data and the infra estimate path." Inert when the skill's estimate has no such field.
- If observability entry exists in `projected_costs.breakdown` (tolerant lookup: array where `service` contains "Observability" OR object where key contains `observability` or `cloudwatch`) AND the entry's `note` field mentions ⟨source_cloud⟩ free tiers:

> **Observability cost note:** [Pull the `note` field verbatim]

- Source: estimation artifact

## What-if scenarios (`what-if-scenarios`, OPTIONAL)

Render **only when** `$MIGRATION_DIR/scenarios/index.json` exists and
`scenarios[]` has **≥ 2** entries (baseline + at least one workshop variant).
Omit entirely when workshop was declined or never entered.

1. Load `scenarios/index.json`. For each entry (baseline first, then by
   `created_at`), read the manifest at `entry.manifest`.
2. HTML table with the workshop compare columns:

| Scenario | Region | HA | Compute | Arch | Premium $/mo | Balanced $/mo | Optimized $/mo | Complexity |
| -------- | ------ | -- | ------- | ---- | ------------ | ------------- | -------------- | ---------- |

Resolve knobs from each scenario's preferences copy (or
`preferences_subset` / `estimation_summary` on the manifest): Region ←
`design_constraints.target_region.value`; HA ←
`design_constraints.availability.value`; Compute ←
`design_constraints.kubernetes.value` when present; Arch ←
`design_constraints.cpu_architecture.value`. Costs and complexity ←
`estimation_summary`.
3. Mark the active row (`scenario_id == index.active_scenario_id`) with
`class="active-scenario"` or an "(active)" label.
4. Under the table: active vs baseline knob deltas (plain language); any
`graviton_note` / `region_note`;
remind that discovery inventory is frozen
and generated Terraform matches the **active** scenario only.
`estimation_summary.calculator_url` is always `null` — render no "open in AWS
Pricing Calculator" link.
5. TOC: link `#what-if-scenarios` only when rendered. Place this section in the
executive flow immediately after `exec-costs` (before security teaser /
timeline). When `exec-optimization` is also rendered, place it after
`exec-costs` and before `what-if-scenarios`.

## Cost Optimization (`exec-optimization`, REQUIRED when any `estimation-*.json` has a non-empty `optimization_opportunities[]`)

This is a **standalone executive section**. A table buried only under
Appendix B / `appendix-costs` does **not** satisfy the gate — that is how
Savings Plans and Reserved Instances were dropped from generated reports.

Place immediately after `exec-costs` (and before `what-if-scenarios` /
`exec-architecture` / security teaser). Add `#exec-optimization` to the TOC
when rendered.

Render two things:

1. **Posture comparison table** (Balanced on-demand vs applicable commitments
   vs Optimized as a floor). Columns such as: Posture, Est. monthly, vs
   Balanced, What you commit to. Savings Plans and Reserved Instances are
   incremental to the **Balanced on-demand** baseline. **Do not** add those
   savings on top of the Optimized tier — Optimized already includes the
   commitment rows at their mid-point rate (and nothing else: Spot and
   storage-class rows are opportunities, not tier inputs). State that caveat
   in the section when Optimized is shown. The Optimized tier is a **pricing
   scenario** for the reader's comparison, not a commitment recommendation:
   it may show a Compute Savings Plan in dollars, while the Cost Optimization
   section still recommends a Compute Savings Plan only in percent until a
   30–90 day AWS usage baseline exists (`ri-sp-eligibility.md` caveat 1). Database Savings Plans and RDS Reserved
   Instances are mutually exclusive on the same database workload.
2. **Which commitment fits** — a short list from the opportunity rows
   (Compute Savings Plans, Database Savings Plans, Reserved Instances /
   reserved capacity / reserved nodes, plus non-commitment rows such as
   Fargate Spot or S3 Intelligent-Tiering when present).

_Full mode:_ the line-level opportunity table (Optimization, Target,
Monthly savings / Est. savings, Commitment, Effort) lives in a dedicated
`<section id="appendix-optimization">` immediately after `appendix-costs`.
`exec-optimization` links down to it. Do not leave that table as an `<h3>`
inside `appendix-costs`.

_Decision mode:_ there are no appendices. Include the opportunity-table
columns in `exec-optimization` itself (or a compact version of the same
rows). Do **not** emit `appendix-optimization`.

Source: `estimation-infra.json` / `estimation-ai.json` →
`optimization_opportunities`. Eligibility of which commitment product
applies is documented in the skill's RI/SP eligibility reference
(⟨ri_sp_eligibility_ref⟩).

## Security & Cost Guardrails (`exec-security-teaser` — teaser; full table in Appendix G)

**Required when** the infra estimate's `projected_costs.breakdown` carries a `security_baseline` entry; the section must name GuardDuty or show the baseline's component dollar figures (validator rule). Show top controls as a compact teaser:

| Control                        | What it does for you                                               | Monthly cost                         |
| ------------------------------ | ------------------------------------------------------------------ | ------------------------------------ |
| GuardDuty                      | Detects compromised credentials and crypto mining within minutes   | ~$2–25/mo                            |
| CloudTrail                     | Immutable audit log of every API call — required for SOC 2         | ~$0.50–3/mo                          |
| Budget alerts                  | Email when spend exceeds threshold — catches runaway resources     | $0                                   |
| Bedrock cost anomaly detection | Alerts within ~24h if AI spend spikes unexpectedly (AI track only) | $0 (Cost Explorer anomaly detection) |

The fourth row is **conditional** — only render when `$MIGRATION_DIR/ai-migration/bedrock_monitoring.tf` exists on disk, or `$MIGRATION_DIR/ai-migration/setup_bedrock.sh` exists and contains the step `== 6. Bedrock budget and cost anomaly monitor` (written by bedrock-migration-assessment's Generate). Do NOT render based on `generation-ai.json` alone.

_Full mode:_ > See Appendix G for full security and cost guardrails table with ⟨source_cloud⟩ equivalents.

_Decision mode:_ > The full control-by-control table is included if you generate the execution pack.

If `preferences.json` contains compliance values (`soc2`, `pci`, `hipaa`, `fedramp`):

> **Compliance note:** Your declared compliance requirement ([standard]) triggers additional controls (AWS Config + Security Hub) at ~$3–25/mo. _(Full mode: append "See Appendix G.")_

**Do NOT include step-by-step enablement** — that belongs in `terraform/README.md` and `MIGRATION_GUIDE.md`.

Inert for a skill whose estimate has no `security_baseline` entry.

Source: static content + `preferences.json` compliance values

## Operational Changes (conditional rows only)

Only render rows for service types PRESENT in the design artifact. Do not show rows for services not in the migration.

Columns: ⟨source_cloud⟩ Service · AWS Service · What stays the same · What's new. The rows — one per source-service → AWS-service pair the skill maps, with what stays the same and what is new — are ⟨service_mapping_table⟩, supplied by the skill layer. A skill that declares no table renders no Operational Changes section.

**Conditional rendering:** Check the design artifact for each source-type / `aws_service` pair. Only include rows where the ⟨source_cloud⟩ source type exists in the design. If a service category has no match, skip that row entirely.

Source: static template filtered by design artifact service types

## Timeline (`exec-timeline`)

Timeline is **shape + stage order + duration drivers**. No week counts, no
effort hours, in either mode.

- _Full mode:_ migration approach (phased/fast-track/conservative), the ordered
  stage sequence (no week column — order is the information; where the
  sequence comes from is ⟨stage_sequence_source⟩), `duration_drivers[]`
  with the binding driver first, and the operational time policies (watch
  periods, observation windows — these are policy, keep them). **No
  implementation-effort hours** — uncalibrated staffing-shaped numbers get
  pasted into budgets; if a legacy artifact carries hour fields, drop them
  (do not render even with a label). Source: generation plan.
- _Decision mode:_ the same rules as decision-summary item 4 (path-shape
  phrasing from ⟨duration_driver_source⟩, labeled "if you execute"; legacy
  week values only with the "Legacy planning heuristic (uncalibrated)" label),
  plus the migration approach from `recommendation.path_label`. **Omit
  engineering effort hours** — they don't exist before Generate and are never
  estimated. Source: ⟨duration_driver_source⟩ / estimation artifact.

## Top Risks (`exec-risks`)

- Up to 3 highest-severity risks (a skill layer may widen the count)
- Table columns: Risk · **Impact** · **Likelihood** · Mitigation — impact and likelihood are separate badge columns (`.badge-impact-critical` / `.badge-impact-high`, `.badge-like-low` / `.badge-like-medium`), never combined into one prose string like "Critical impact (low probability)" — a risk matrix is scanned, not read. The validator requires the table and requires `exec-risks` to come before `exec-assumptions`.
- _Full mode source:_ generation plan `risk_assessment` (preferred).
- _Decision mode source_ (in order; **never leave `exec-risks` empty** when any of these exist): (1) risk/condition items in `estimation-infra.json` → `recommendation` (`conditions[]`, `would_flip_if[]`); (2) deferred-specialist rows from the design artifact; (3) material defaulted assumptions with cost or HA impact from `preferences.json` (e.g. availability defaulted — "~2x database cost swing; confirm before cutover sizing"). A skill with further sources (generation warnings, deferred tracks) lists them as ⟨risk_sources⟩. Invent nothing beyond these artifacts.

## What this assessment rests on (`exec-assumptions`, REQUIRED)

> Rendered heading is a plain title — e.g. `<h2>What This Assessment Rests On</h2>` with `<section id="exec-assumptions">`. Never render a literal "Section 8" heading (validator readability rule).

Placed at the **end of the executive summary** — after Top Risks, immediately before the appendices — where assumption and validation sections conventionally sit in a migration report. The decision summary links here via the confidence pointer (item 1b). Three parts, all read from existing artifacts — invent nothing:

1. **Assumptions applied by default** — table of every constraint in `preferences.json` the skill marks as defaulted (⟨defaulted_constraint_fields⟩ — e.g. `chosen_by: "default"`): Setting (plain name), Assumed value, and the constraint's `design_consequence` verbatim. When no constraint was defaulted, render one line: "All inputs were confirmed by you or extracted from your [source — ⟨extracted_from_wording⟩, e.g. Terraform/billing] — nothing was assumed."
2. **Confidence** — one line from ⟨confidence_source⟩ with a plain-language gloss: high — "inputs measured or confirmed"; medium — "some material inputs assumed"; low — "key inputs missing or stale". When v2 `decision_basis` exists, render its three lists (measured / assumed / unknown) as compact columns instead of the single line.
3. **Pricing provenance** — from the estimation artifact (⟨provenance_fields⟩): `pricing_source` + cache date + `accuracy_confidence` band, matching the wording the Estimate chat summary already uses (e.g. "Estimates based on cached AWS pricing (2026-03-07), accuracy ±5–10%").

TOC: link `#exec-assumptions` in the executive list. The anti-stub rule applies: this section must render actual settings and consequences, never "see preferences.json".

Source: `preferences.json`, `estimation-infra.json` (falls back to `estimation-ai.json` accuracy fields for AI-only runs)

## Readability, currency, CSS, and accessibility contract

**Readability (validator-enforced, `READABILITY_PATTERNS`):** the report fails on any of these in rendered text:

1. "TCO" or "Total Cost of Ownership" — use "estimated AWS monthly run rate".
2. "Rubric:" — an internal scoring trace; drop it or gate it behind a `<details>` "Why this mapping?" block.
3. An effort-hours range (e.g. "N–M engineering hours") — the plugin has no calibrated effort data.
4. A bare week-range estimate — durations are uncalibrated; drop it, or label a legacy value "Legacy planning heuristic (uncalibrated): …".
5. A literal "Section 0" anywhere in the text.
6. A numbered "Section N —" heading — let the table of contents carry structure.
7. The intensifiers "very", "significantly", "extremely", "vastly" — quantify from artifact data instead ("-32% ($497/mo lower)").
8. Slash-format dates (N/N/YYYY) — ISO `YYYY-MM-DD` only.

Do not use color as the only status carrier anywhere; badges and callouts carry their meaning in words.

**Currency:** whole dollars on monthly-scale figures (see § Cost Comparison → Whole dollars).

**CSS contract (`VISUAL_CONTRACT_CHECKS`, both modes):** the inline stylesheet must define, as capabilities rather than exact values: a contrasting `body` background; a `.report` or `.container` shell with `max-width`; `section` as bordered surface cards (background, border, border-radius); `.metrics` as a CSS grid with `grid-template-columns`; `.metric` with a bordered card treatment; `.verdict` with a distinct background + border callout; `.savings` with a color; an `.appendix-header` rule; a `:focus-visible` rule; a `@media (max-width: 700px)` breakpoint; and a `@media print` block. The `.appendix-header` **rule** must be present in the stylesheet in decision mode as well as full mode (the shell is shared); the `.appendix-header` **element** is rendered only in full mode.

**Accessibility (validator-enforced):** `<html lang="en">` (or another valid language tag); exactly one `<h1>`; every `<table>` has a `<caption>`; every `<th>` carries `scope="col"` or `scope="row"`; every `<figure>` declares `role="img"` and a non-empty `aria-label` and contains a `<figcaption>`. Also give images a non-empty `alt` (good practice; not machine-checked).

## Draft footer (both modes)

The footer of `migration-report.html` and of `decision-report.html` contains the phrase "draft for review" and tells the reader to validate estimates before making decisions. The validator checks the phrase in every mode.

## Skill layer must supply

The skill layer (`report-decision-core.md` inside the skill's own references, the file that loaded this one) supplies a value for every parameter below. A parameter the skill does not use is declared "n/a" or "none" with a one-line reason — never left silent.

| Parameter                                                                         | What it is                                                                                                                                                                     |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ⟨source_cloud⟩                                                                    | The source platform's display name used in titles, table headers, and copy                                                                                                     |
| ⟨modes_used⟩ / ⟨loaders⟩                                                          | Which modes the skill renders and which of its phase files load the core in each                                                                                               |
| ⟨required_ids⟩                                                                    | The default per-mode required-ID sets, or the sets of the skill's declared `--profile`                                                                                         |
| ⟨current_monthly_path⟩                                                            | The JSON path the validator resolves `data-cost-key="current_monthly"` from (one candidate per source cloud)                                                                   |
| ⟨ai_spend_key⟩                                                                    | The current AI-spend key for the `exec-tco` AI row, or "none" when the skill has no AI track                                                                                    |
| ⟨baseline_label_table⟩                                                            | `current_costs.source` value → baseline-quality label text                                                                                                                     |
| ⟨service_mapping_table⟩                                                           | Operational Changes rows (source service → AWS service → what stays the same → what's new), or "none declared"                                                                  |
| ⟨activate_status_path⟩ / ⟨activate_copy⟩                                          | Where the startup-program status lives and the exact copy per status, or a declared omission                                                                                   |
| ⟨decision_cta_text⟩ / ⟨decision_md_extras⟩                                        | The quoted say-this sentence and artifact list for `decision-cta`; any extra `DECISION.md` parts                                                                                |
| ⟨validator_invocation⟩                                                            | The exact shared-validator command(s) for the skill (artifact flags, `--profile` when declared) and any skill-local add-on validator                                            |
| ⟨tier_subtitles⟩ / ⟨tier_semantics⟩                                               | Subtitle text (defaults in § Cost Comparison) and the artifact keys holding each tier; a layer declares the mapping only and never redefines a tier                            |
| ⟨complexity_source⟩                                                               | Artifact field for the complexity badge                                                                                                                                         |
| ⟨confidence_source⟩                                                               | Artifact field for the confidence pointer and gloss                                                                                                                             |
| ⟨key_decisions_source⟩                                                            | Where "Key decisions ahead" items come from                                                                                                                                     |
| ⟨duration_driver_source⟩ / ⟨stage_sequence_source⟩                                | Where decision-mode path-shape phrasing and the full-mode stage sequence come from                                                                                              |
| ⟨defaulted_constraint_fields⟩ / ⟨extracted_from_wording⟩                          | How a defaulted `preferences.json` constraint is marked; the "extracted from your …" wording                                                                                     |
| ⟨provenance_fields⟩                                                               | The estimation artifact's pricing-provenance fields                                                                                                                             |
| ⟨fallback_chain⟩                                                                  | What to render when `recommendation` is absent beyond `financial_summary.recommendation`                                                                                        |
| ⟨stack_overview_filter⟩                                                           | How the Current Stack Overview filters and names source services                                                                                                               |
| ⟨how_we_chose_vocabulary_ref⟩                                                     | Where the mapping-confidence vocabulary is defined for the skill                                                                                                                 |
| ⟨ri_sp_eligibility_ref⟩                                                           | The skill's RI/SP eligibility reference                                                                                                                                         |
| ⟨reference_fixture⟩                                                               | A checked-in report the agent compares against for the anti-stub rule                                                                                                           |
| ⟨deferred_analytics_example⟩                                                      | The source platform's deferred analytics service named in the Stay-if guidance, or "none"                                                                                       |
| ⟨spend_fields⟩                                                                    | The spend fields that must never be used to infer an Activate tier                                                                                                              |
| ⟨risk_sources⟩                                                                    | Any decision-mode risk sources beyond the three canonical ones                                                                                                                  |
| ⟨fill_in_checklist_name⟩                                                          | How the first next step names the fill-in checklist (e.g. "checklist in MIGRATION_GUIDE.md")                                                                                   |

Beyond parameters, the skill layer carries the skill's own **declared add-ons** (sections or rules that exist only for that source platform) and **declared omissions** (canonical sections the skill never renders, each with its reason). Nothing in the skill layer may contradict a rule here except through § Declared skill exceptions.

## Declared skill exceptions

The default contract above is the shape every report follows. A skill whose report differs in **shape** — a different required-section set per mode, or a check it cannot satisfy yet — declares that divergence in two places that must agree:

1. In its skill layer, under a "Declared exceptions" heading: every section the default requires that the skill does not render, every check it switches off, and a one-line reason for each.
2. In `SKILL_PROFILES` inside `$PLUGIN_ROOT/scripts/validate-migration-report.py`, as a named profile with `required_sections` per mode, `not_required` (section ID → reason), and `skip` (check name → reason). The skill passes `--profile <name>` on every validator run.

Rules:

- No silent divergence. A skill without a profile follows the default sets exactly; a skill with a profile lists every `not_required` and `skip` entry in its layer with the validator's reason.
- Vocabulary-only differences (a differently named section, a missing heading phrase, different table columns) are declared exceptions pending a content follow-up that converges the skill on the default contract — they are not a second contract.
- Add-ons never need a profile: a skill may require **more** than the default (extra sections, extra anchors, a skill-local validator) and declares those in its layer.
- Where this file and the validator disagree, the validator wins; list the discrepancy in the change that fixes one of them.
