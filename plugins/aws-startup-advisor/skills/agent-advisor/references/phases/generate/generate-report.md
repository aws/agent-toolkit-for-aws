---
_fragment: generate-report
_of_phase: generate
_contributes:
  - recommendation-report.html
---

# Generate Phase: HTML Recommendation Report (v3)

> Loaded by `generate.md` after Steps 3–5 complete (diagram written, recommendation.md
> written, scaffold written, mini-brief printed, gates set). Execute ALL steps in order.

## Overview

Generate a single self-contained HTML file (`$RUN_DIR/recommendation-report.html`) that
presents the agent architecture recommendation in **v3 document style** — a consulting-grade
report that mirrors the structure of recommendation.md. The file uses inline CSS and a
CDN-loaded Mermaid.js for the diagram — no other external dependencies. Users can open it in
any browser and use "Print to PDF" if needed.

**Before writing the HTML:** load the shared shell (`references/report-shell.md`) — inline
its CSS block at the `{{ SHARED_SHELL_CSS ... }}` marker and its SRI-pinned mermaid@10.9.3
script tag at the `{{ SHARED_SHELL_MERMAID_TAG ... }}` marker in `<head>`. The remaining
rules in the `<style>` block below are this report's OWN content CSS. The v3 shell defines
`.help-strip`; render the help CTA using that component (text + inline button), not the
3-card form from report-help-banner.md — **but ONLY when `report-help-banner.md`'s
`banner_status` reads `LIVE`. It currently reads `SUPPRESSED` (support page not launched), so
render NO help CTA at all** (skip the `.help-strip` block in the body below). When it flips to
LIVE, substitute `{{ HELP_URL }}` with the single-source destination URL from
`references/report-help-banner.md` — never hardcode it here.

**Non-blocking:** if HTML generation fails for any reason, log a warning, do NOT fail the
Generate phase, and continue. The recommendation.md is the authoritative document.

## Step R0 — Gather data

Read all available sources. Mark each as present or absent — absent fields use the fallback
rules below.

| Variable                      | Source                                                                                                                                                                                                                                                                                                                                                                                                      | Fallback                           |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `UNITS`                       | `design.json.units` (array: id, workload_class, verdict, deployment_model, agentcore_services, model_recommendation, rationale, key_change) + `design.json.platform` + per-unit estimate rows from `estimate.json.units` if it exists; `answers.json.primary_unit`                                                                                                                                          | []                                 |
| `PLATFORM`                    | `design.json.platform` (mode: consolidated/split; if split: runtime/interconnect)                                                                                                                                                                                                                                                                                                                           | null                               |
| `PLATFORM_DECISION`           | `confirm.json.platform_decision` (mode, platform, offer{superset, sacrifices[]}) — §1.1 only when platform_decision.offer ≠ null                                                                                                                                                                                                                                                                            | null                               |
| `TEMPORAL_UNITS_PRESENT`      | true if ANY `design.json.units[].workload_class == "temporal_worker_poll"` (the `temporal` block has no `units` field — key on the unit list)                                                                                                                                                                                                                                                               | false                              |
| `TEMPORAL_WAY`                | `design.json.temporal.way` (cloud / self_hosted / no_change)                                                                                                                                                                                                                                                                                                                                                | null                               |
| `TEMPORAL_COST_TABLE`         | from estimate.md (Polling tier, Execution tier, Temporal Cloud actions, What it replaces)                                                                                                                                                                                                                                                                                                                   | []                                 |
| `TEMPORAL_COST`               | the system-level orchestration cost band for the §-cost roll-up row: from `estimate.json` — the Temporal Cloud orchestration assumption band (actions/mo × $0.01) when `TEMPORAL_WAY == "cloud"`; else `"see §5 commercials"` (self_hosted has no dollar line)                                                                                                                                              | "see §5 commercials"               |
| `TEMPORAL_COST_SUMMARY`       | the label cell paired with `TEMPORAL_COST` in the cost-summary table: e.g. "Temporal Cloud orchestration (system-level: all Activities)" when Way = cloud; "Temporal orchestration (self-hosted — no AWS charge)" otherwise                                                                                                                                                                                 | "Temporal orchestration"           |
| `COST_DOMINANT_NOTE`          | one clause naming the dominant tier from the ACTUAL `estimate.json` bands, not a fixed assumption: usually "model tokens dominate most lines", but "the polling fleet dominates" or "compute and model tokens are comparable" when the numbers say so                                                                                                                                                       | "model tokens dominate most lines" |
| `TEMPORAL_RUNBOOK_STEPS`      | The selected cutover runbook steps from recommendation.md §3c                                                                                                                                                                                                                                                                                                                                               | []                                 |
| `SERVERLESS_WORKERS_IN_TIER1` | true if any task queue's Tier 1 choice is `serverless_workers`                                                                                                                                                                                                                                                                                                                                              | false                              |
| `CONTEXT_SIGNALS`             | `context-signals.json.units` (array: id, workload_class, trigger, coupling, evidence)                                                                                                                                                                                                                                                                                                                       | []                                 |
| `PROVENANCE`                  | LAYERED, not top-level: `answers.json.system.provenance` for system dims + `answers.json.units[<id>].provenance` for per-unit dims (each maps dim → "detected"/"asked"/"inherited"/"adapter"/"interview"). For a given (dim, scope) look up the matching layer                                                                                                                                              | {}                                 |
| `ANSWERS`                     | `answers.json.answers` (the primary unit's fully-merged dims — legacy mirror only)                                                                                                                                                                                                                                                                                                                          | {}                                 |
| `ANSWER_LAYERS`               | the LAYERED answer document from the full `answers.json`: `.system` (system dims + provenance) and `.units` (map of unit_id → per-unit dims + provenance). This is the source the §2 Assessment-inputs table enumerates — NOT `ANSWERS`, which is only the primary merge                                                                                                                                    | {system:{}, units:{}}              |
| `SCORING_RESULT`              | `scoring-result.json` (units{} keyed by unit ID, each with scores{}, eliminations, winner)                                                                                                                                                                                                                                                                                                                  | null                               |
| `ESTIMATE`                    | `estimate.json` (units{} with per-unit breakdown{compute, model_tokens, other} + monthly_magnitude_usd; total_monthly_magnitude_usd; total_compute/total_model/total_other; drivers[] with {unit, driver, effect, lever}; assumptions[])                                                                                                                                                                    | null                               |
| `VOLATILE_FACTS`              | `design.json.volatile_facts` (runtime_session_caps, runtime_regional_availability, pricing_date, etc.)                                                                                                                                                                                                                                                                                                      | {}                                 |
| `DIAGRAM_MERMAID`             | Extract the fenced ```mermaid block from `diagram.md`                                                                                                                                                                                                                                                                                                                                                       | null                               |
| `DIAGRAM_ASCII`               | Extract the ASCII block inside `<details>` from `diagram.md`                                                                                                                                                                                                                                                                                                                                                | null                               |
| `RUN_DATE`                    | From `design.json` or current date                                                                                                                                                                                                                                                                                                                                                                          | "2026"                             |
| `RUN_ID`                      | From `design.json` or run directory name                                                                                                                                                                                                                                                                                                                                                                    | "draft"                            |
| `ENTRY_POINT`                 | `answers.json.entry_point` OR `context-signals.json.units[].trigger` (for the primary unit)                                                                                                                                                                                                                                                                                                                 | "build"                            |
| `REGION`                      | `answers.json.answers.region`                                                                                                                                                                                                                                                                                                                                                                               | "us-east-1"                        |
| `RECOMMENDATION_MD_PATH`      | `$RUN_DIR/recommendation.md`                                                                                                                                                                                                                                                                                                                                                                                | —                                  |
| `SCAFFOLD_EXISTS`             | true if `$RUN_DIR/scaffold/` directory exists and is non-empty                                                                                                                                                                                                                                                                                                                                              | false                              |
| `SYSTEM_NAME`                 | `answers.json.system.name` or the repo/app name, if known                                                                                                                                                                                                                                                                                                                                                   | "Agent Platform"                   |
| `PRIMARY_UNIT`                | `answers.json.primary_unit` (the unit id chosen as primary in Clarify) — used to tag the "· primary unit" label in §3                                                                                                                                                                                                                                                                                       | null                               |
| `unit.runner_up_runtime`      | NOT a global scalar — derived INSIDE the §3 per-unit loop for each agent_session unit: the highest-scoring runtime in THAT unit's `SCORING_RESULT.units[unit.id].scores` EXCLUDING `unit.verdict` (filter out the winner first, then take the top of the rest — never just "2nd sorted", else a co_recommend winner picked from a tie could show as its own runner-up). Each unit has its own; never shared | null (omit the Runner-up row)      |
| `unit.runner_up_score`        | that runner-up runtime's score from the SAME `SCORING_RESULT.units[unit.id].scores` map                                                                                                                                                                                                                                                                                                                     | null                               |

## Step R1 — Section spec

The v3 report mirrors the reference HTML structure (report-v3-reference-multi-agent.html)
exactly:

- **doc-head** (kicker/title/meta: run ID, date, entry point, region, status)
- **.help-strip** (inline CTA: text + button)
- **§1 Summary** (lede paragraph + workloads table: Workload/What it is/Recommended
  target/Basis/Est. monthly; **§1.1 Platform decision** ONLY when `PLATFORM_DECISION.offer ≠
  null`)
- **§2 Assessment inputs** (Dimension/Value/Scope/Source — Source from `PROVENANCE`)
- **§3 Workload recommendations** (one `.unit-sec` per unit: **scored form** = score bars
  titled "Runtime comparison for this agent" + eliminated note + "Why X" bullets + item table
  [model/services/runner-up/key change]; **rule-based form** = decision table with rule-cite
  - considered-and-rejected; each unit with a non-null `model_recommendation` additionally
    gets the **"Why this model" card** — rationale visible, full model/migration detail in a
    collapsed `<details>`, all values from `unit.model_recommendation`)
- **§4 Target architecture** (figure w/ per-unit entry points from `trigger` + figcap; **4.1
  component detail** table [Entry point from trigger / Compute / Model access / Supporting
  services]; **4.2 Security & networking** table [from the runtime cards' Serving & security
  notes]; **4.3 Scaling & limits** [volatile_facts + service cards, "verify current"];
  pipelines note)
- **[§5 Temporal migration]** — CONDITIONAL (only when `TEMPORAL_UNITS_PRESENT`): scope
  callout, layer table w/ Public Preview flag, runbook w/ preconditions callout + ordered steps,
  Bedrock follow-up note. Per the temporal reference (report-v3-reference-temporal.html).
- **§Cost** (5.1 breakdown table from `estimate.json.units[].breakdown`; 5.2 assumptions
  list; 5.3 "What moves the number" from `drivers[]`) — section number is 5 if temporal
  absent, 6 if present.
- **§Next steps** (ordered, per-unit poc paths) — section number is 6 or 7.
- **§Generated artifacts** (table w/ relative dl links) — section number is 7 or 8.
- **doc-foot** (freshness statement from volatile_facts; "draft for review")

**Dynamic numbering:** when the Temporal section is absent, cost is §5, next steps §6,
artifacts §7. When the Temporal section is present, cost is §6, next steps §7, artifacts §8.

**Single-unit collapse:** when `UNITS.length === 1`, the report renders exactly one §3
subsection (the single unit's card), NO §1.1 (platform decision is N/A), and the summary
table still lists the one unit. Everything else (§2, §4, cost, next steps, artifacts)
renders identically.

## Step R2 — Write the HTML file

Write `$RUN_DIR/recommendation-report.html` with the following structure. Every `{{ }}` is a
substitution from Step R0/R1. Do not output placeholder text — if a value is absent, hide
that element entirely (use `display:none` or omit the HTML block).

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AWS Migration Recommendation</title>
<!-- SRI-pinned mermaid@10.9.3 script tag — inline it VERBATIM from the shared shell
     (references/report-shell.md), same tag/integrity hash used by every report with a diagram. -->
{{ SHARED_SHELL_MERMAID_TAG from references/report-shell.md }}
<style>
  /* ── Shared chrome ── load references/report-shell.md and inline its CSS block
     HERE (chart tokens, reset & base, .page layout, .doc-head family, h2/h3 + .no,
     table/th/td, .lede/.note, .rule-cite/.pre-flag, .scores/.score-row, .callout,
     .unit-sec family, .figure/.figcap, .help-strip, .feat-grid, .timeline, .doc-foot).
     Single-sourced there so this report and the temporal report share identical chrome —
     do not restate those rules here. ── */
  {{ SHARED_SHELL_CSS from references/report-shell.md }}

  /* ── Content CSS (this report's own rules) ── */
  /* Unit card scored-form subsection scores — inherited from the shell's .scores */
  .elim-label { font-size: 11px; color: #ef4444; font-style: italic; margin-top: -6px;
                margin-bottom: 6px; }

  /* "Why this model" card (per model-bearing unit; detail collapsed by default) */
  .model-why { border: 1px solid var(--rule); margin-top: 14px; }
  .model-why-head { padding: 9px 14px; background: var(--soft); border-bottom: 1px solid var(--rule);
                    font-size: 12px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.4px; color: var(--muted); }
  .model-why-body { padding: 11px 14px 12px; font-size: 13.5px; }
  .model-why-body > p { margin: 0 0 8px; }
  .model-why details > summary { cursor: pointer; font-size: 12.5px; font-weight: 600; color: #1a56db; }
  .model-why details p.em { margin: 12px 0 4px; font-weight: 600; }
  .model-why .mark { font-size: 11px; font-weight: 600; text-transform: uppercase;
                     letter-spacing: 0.4px; color: var(--muted); white-space: nowrap; }
  .model-why .mark-block { color: #b42318; }

  /* Alternatives grid */
  .alt-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
              gap: 12px; margin-top: 12px; }
  .alt { background: var(--soft); border: 1px solid var(--rule);
         border-left: 3px solid var(--chart-muted); border-radius: 8px;
         padding: 12px 16px; }
  .alt-name { font-size: 14px; font-weight: 700; color: var(--ink); }
  .alt-reason { font-size: 13px; color: var(--muted); margin-top: 2px; }

  /* Services grid */
  .services-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                   gap: 16px; margin-top: 14px; }
  .service-card { background: var(--soft); border-radius: 8px; padding: 16px 18px;
                  border: 1px solid var(--rule); }
  .service-card.addon-card { border-top: 3px solid #C77700; }
  .service-card .svc-name { font-size: 14px; font-weight: 700; color: var(--ink);
                             margin-bottom: 4px; }
  .service-card .svc-badge { font-size: 11px; font-weight: 600; border-radius: 4px;
                              padding: 2px 8px; display: inline-block; margin-bottom: 8px; }
  .badge-free  { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
  .badge-addon { background: #fff7ed; color: #c2410c; border: 1px solid #fed7aa; }
  .service-card .svc-desc { font-size: 13px; color: var(--muted); line-height: 1.5; }

  /* Cost card */
  .cost-card { border: 1px solid var(--rule); border-radius: 8px; padding: 20px 24px;
               background: var(--soft); margin-top: 12px; }
  .cost-band { font-size: 28px; font-weight: 700; color: var(--ink); }
  .cost-label { font-size: 13px; color: var(--muted); }
  .cost-note  { font-size: 13px; color: var(--muted); margin-top: 10px;
                padding-top: 10px; border-top: 1px solid var(--rule); }
  .assumption-list { list-style: disc; padding-left: 18px; font-size: 13px;
                     color: var(--muted); margin-top: 8px; }

  /* Artifact links */
  .artifact-row { display: flex; gap: 10px; align-items: baseline; font-size: 13px;
                  color: var(--muted); margin-bottom: 10px; }
  .artifact-row:last-child { margin-bottom: 0; }

  /* Print */
  @media print {
    body { background: #fff; }
    .bar-fill.winner { background: var(--chart-accent) !important; -webkit-print-color-adjust: exact; }
  }
</style>
</head>
<body>

<!-- ═══ DOCUMENT HEADER ═══ -->
<div class="page">

<div class="doc-head">
  <div class="doc-kicker">AWS Migration Assessment · agent-advisor</div>
  <div class="doc-title">Migration Recommendation: {{ SYSTEM_NAME or "Agent Platform" }}</div>
  <div class="doc-meta">
    <span>Run <b>{{ RUN_ID }}</b></span><span>Date <b>{{ RUN_DATE }}</b></span>
    <span>Entry point <b>{{ ENTRY_POINT }}</b></span><span>Region <b>{{ REGION }}</b></span>
    <span>Status <b>draft for review</b></span>
  </div>
</div>

<!-- ═══ HELP STRIP — GATED on report-help-banner.md `banner_status`. It currently reads
     SUPPRESSED (support page not launched): OMIT this whole block — render NOTHING here, no
     .help-strip, no link. When it flips to LIVE, render the strip below and substitute
     {{ HELP_URL }} with the single-source destination URL from report-help-banner.md (do NOT
     hardcode the URL here; that file is the one place it is maintained):
<div class="help-strip">
  <div class="txt"><b>Need help getting to AWS?</b> &nbsp;Install the AI agent for hands-on
  guidance, talk with an AWS expert, or work with a certified AWS Partner.</div>
  <a class="btn" href="{{ HELP_URL }}" target="_blank" rel="noopener">Explore your options</a>
</div>
     ═══ -->

<!-- ═══ 1. SUMMARY ═══ -->
<h2><span class="no">1.</span>Summary</h2>
<p class="lede">{{ EXEC_LEAD from recommendation.md §1 — 1–2 plain-language sentences }}</p>

<table>
  <thead><tr><th>{{ IF UNITS.length > 1 }}Agent / Workload{{ ELSE }}Workload{{ END IF }}</th><th>What it is</th><th>Recommended target</th><th>Basis</th><th>Est. monthly</th></tr></thead>
  <tbody>
    {{ FOR EACH (unit, index) IN UNITS }}
    <tr><td class="em">{{ unit.id }}</td><td>{{ unit.description from context-signals or answers }}</td>
        <td class="target">{{ unit.effective_runtime }}{{ IF unit.effective_runtime !== unit.verdict }} <span class="muted">(consolidated; best-fit alone: {{ unit.verdict }})</span>{{ END IF }}</td><td>{{ IF unit.workload_class === "agent_session" }}scored {{ SCORING_RESULT.units[unit.id].scores[unit.verdict] }} — §3.{{ index }}{{ ELSE }}{{ unit.rationale }} — §3.{{ index }}{{ END IF }}</td><td>{{ unit.monthly_magnitude_usd or "—" }}</td></tr>
    {{ END FOR }}
    {{ IF TEMPORAL_UNITS_PRESENT }}
    <tr><td class="em">— orchestration</td><td>Temporal Workflows ({{ TEMPORAL_WAY === "cloud" ? "self-hosted today" : "current state" }})</td>
        <td class="target">{{ TEMPORAL_WAY === "cloud" ? "Temporal Cloud" : (TEMPORAL_WAY === "self_hosted" ? "Self-hosted (no change)" : "no change") }}</td><td>{{ TEMPORAL_WAY === "cloud" ? "user decision — §5" : "§5" }}</td><td>{{ TEMPORAL_COST or "see §5 commercials" }}</td></tr>
    {{ END IF }}
  </tbody>
</table>
<p class="note">{{ IF UNITS.length > 1 }}Platform decision: {{ PLATFORM.mode }}{{ IF PLATFORM.mode === "split" }} — each workload on its optimal runtime{{ END IF }}. {{ END IF }}Total estimate {{ ESTIMATE.total_monthly_magnitude_usd or "TBD" }}/month, order-of-magnitude.</p>

{{ IF PLATFORM_DECISION.offer !== null }}
<h3>1.1&nbsp; Platform decision</h3>
<div class="callout"><b>{{ PLATFORM_DECISION.mode === "split" ? "Split confirmed" : "Consolidated" }}.</b> {{ PLATFORM_DECISION.mode === "consolidated" ? "Consolidated onto " + PLATFORM_DECISION.offer.superset + " — trade-offs: " + JOIN(PLATFORM_DECISION.offer.sacrifices, "; ") : "Each workload runs on its own optimal runtime; the consolidation offer (" + PLATFORM_DECISION.offer.superset + ") was declined to avoid: " + JOIN(PLATFORM_DECISION.offer.sacrifices, "; ") }}</div>
{{ END IF }}

<!-- ═══ 2. ASSESSMENT INPUTS ═══ -->
<h2><span class="no">2.</span>Assessment inputs</h2>
<table>
  <thead><tr><th>Dimension</th><th>Value</th><th>Scope</th><th>Source</th></tr></thead>
  <tbody>
    <!-- Enumerate the actual answer dimensions from ANSWER_LAYERS (the layered answers.json): the
         system dims (ANSWER_LAYERS.system) with scope "system", then each unit's dims
         (ANSWER_LAYERS.units[id]), EXCLUDING the "provenance" key in each layer (it's metadata,
         not a dimension). Source comes from the matching provenance layer. NOTE: use
         ANSWER_LAYERS, not ANSWERS — ANSWERS is only the primary unit's merged dims. -->
    {{ FOR EACH (dim, value) IN ANSWER_LAYERS.system EXCEPT "provenance" }}
    <tr><td>{{ dim }}</td><td>{{ value }}</td><td>system</td><td>{{ ANSWER_LAYERS.system.provenance[dim] or "detected" }}</td></tr>
    {{ END FOR }}
    {{ FOR EACH unit_id IN ANSWER_LAYERS.units }}
    {{ FOR EACH (dim, value) IN ANSWER_LAYERS.units[unit_id] EXCEPT "provenance", "workload_class" }}
    <tr><td>{{ dim }}</td><td>{{ value }}</td><td>{{ unit_id }}</td><td>{{ ANSWER_LAYERS.units[unit_id].provenance[dim] or "detected" }}</td></tr>
    {{ END FOR }}
    {{ END FOR }}
  </tbody>
</table>

<!-- ═══ 3. WORKLOAD RECOMMENDATIONS ═══ -->
<h2><span class="no">3.</span>{{ IF UNITS.length > 1 }}Workload recommendations{{ ELSE }}Recommendation{{ END IF }}</h2>

{{ FOR EACH (unit, index) IN UNITS }}
<div class="unit-sec">
  <div class="unit-sec-head">
    <div><span class="us-name">{{ IF UNITS.length > 1 }}3.{{ index }}&nbsp; {{ END IF }}{{ unit.id }}</span><span class="us-kind">{{ unit.workload_class }} · {{ IF unit.workload_class === "agent_session" }}scored{{ ELSE }}rule-based{{ END IF }}{{ IF unit.id === PRIMARY_UNIT }} · primary unit{{ END IF }}</span></div>
    <div class="us-target">→ {{ unit.verdict }}{{ IF unit.deployment_model }} ({{ unit.deployment_model }}){{ END IF }}</div>
  </div>
  <div class="unit-sec-body">
    <p>{{ unit.description from context-signals.evidence or answers }}{{ IF unit.workload_class === "agent_session" }}. Runtime comparison for this agent:{{ END IF }}</p>
    {{ IF unit.workload_class === "agent_session" }}
    <!-- SCORED FORM — `pct` is NOT in scoring.json (scores is a plain {runtime: score} map).
         Derive it here as the bar width, normalized to the unit's own top score:
         pct = ROUND(100 × score / MAX(SCORING_RESULT.units[unit.id].scores.values)), so the
         winner's bar is full-width and the rest scale relative to it. -->
    <div class="scores">
      {{ FOR EACH (runtime, score) IN SCORING_RESULT.units[unit.id].scores SORTED DESC }}
      {{ LET pct = ROUND(100 * score / MAX(SCORING_RESULT.units[unit.id].scores.values)) }}
      <div class="score-row">
        <div class="score-name {{ IF runtime === unit.verdict }}winner{{ END IF }}">
          {{ RUNTIME_DISPLAY_NAME(runtime) }}
        </div>
        <div class="bar-track">
          <div class="bar-fill {{ IF runtime === unit.verdict }}winner{{ END IF }}"
               style="width:{{ pct }}%"></div>
        </div>
        <div class="score-val {{ IF runtime === unit.verdict }}winner{{ END IF }}">{{ score }}</div>
      </div>
      {{ END FOR }}
    </div>
    {{ IF NOT EMPTY(SCORING_RESULT.units[unit.id].eliminated) }}
    <p class="elim-label">{{ FOR EACH (runtime, reason) IN SCORING_RESULT.units[unit.id].eliminated }}{{ runtime }} was eliminated before scoring: {{ reason }}.{{ END FOR }}</p>
    {{ END IF }}
    <h3>Why {{ unit.verdict }}</h3>
    <ul class="plain">
      {{ TOP_3_WHY_BULLETS from recommendation.md §3.{index} "wins because" }}
    </ul>
    <table>
      <thead><tr><th>Item</th><th>Recommendation</th><th>Notes</th></tr></thead>
      <tbody>
        <tr><td>Bedrock model</td><td class="em">{{ unit.model_recommendation.model_identity.display_name }}</td><td>{{ unit.model_recommendation.reasoning }}</td></tr>
        <tr><td>API path</td><td>{{ unit.model_recommendation.api_path }}</td><td>Path ID: {{ unit.model_recommendation.model }}</td></tr>
        <tr><td>Account verification</td><td>{{ unit.model_recommendation.live_verification.status OR "not_run" }}</td><td>{{ IF unit.model_recommendation.live_verification.status === "passed" }}Invocation ID verified{{ ELSE }}Runnable access not yet established{{ END IF }}</td></tr>
        <tr><td>Migration gates</td><td>{{ COMMA_JOIN(CODES(unit.model_recommendation.blocks)) OR "None" }}</td><td>{{ unit.model_recommendation.evaluation.mode }} evaluation; {{ unit.model_recommendation.rollout.strategy }} rollout</td></tr>
        {{ IF unit.agentcore_services }}
        <tr><td>AgentCore services</td><td>{{ COMMA_JOIN(unit.agentcore_services) }}</td><td>{{ service notes }}</td></tr>
        {{ END IF }}
        {{ IF unit.runner_up_runtime }}<tr><td>Runner-up</td><td>{{ unit.runner_up_runtime }} ({{ unit.runner_up_score }})</td><td>{{ runner-up reason }}</td></tr>{{ END IF }}
        <tr><td>Key change</td><td>{{ unit.key_change }}</td><td>{{ additional notes }}</td></tr>
      </tbody>
    </table>
    {{ ELSE }}
    <!-- RULE-BASED FORM — non-agent units are decided by a workload-classes rule, not scored,
         so the basis is the unit's `rationale` (which carries the rule cite, e.g.
         "W2: batch → AWS Batch"); there is no per-runtime rejection map for these. -->
    <table>
      <thead><tr><th>Decision</th><th>Basis</th></tr></thead>
      <tbody>
        <tr><td>{{ unit.effective_runtime }}{{ IF unit.effective_runtime !== unit.verdict }} (consolidated; best-fit alone: {{ unit.verdict }}){{ END IF }}</td>
            <td>{{ unit.rationale }}</td></tr>
      </tbody>
    </table>
    <p class="note">Key change: {{ unit.key_change }}</p>
    {{ END IF }}
    {{ IF unit.model_recommendation }}
    <!-- "WHY THIS MODEL" CARD — every value below renders from unit.model_recommendation
         (design.json's verbatim copy of the Model Recommend engine output). Never invent or
         summarize these values from memory; if a field is null/empty, omit that element.
         The detail block is collapsed by default so model detail never dominates the card.
         {{ LET mr = unit.model_recommendation }} -->
    <div class="model-why">
      <div class="model-why-head">Why this model</div>
      <div class="model-why-body">
        <p>{{ mr.reasoning }}</p>
        <details>
          <summary>Full model &amp; migration detail</summary>
          <p class="note" style="margin-top:8px"><strong>Identities:</strong> logical <code>{{ mr.model_identity.model_key }}</code> · path ID <code>{{ mr.model_identity.path_model_id }}</code> · invocation <code>{{ mr.invocation_model_id OR "unresolved" }}</code> · catalog verified {{ mr.verification.catalog_verified_at }} · limits: {{ mr.model_identity.context_window }} — probe in target account.<br>
            <strong>Compatibility:</strong> native {{ COMMA_JOIN(mr.compatibility.native, each wrapped in <code>) OR "—" }} · portable {{ COMMA_JOIN(mr.compatibility.portable, each wrapped in <code>) OR "—" }} · rearchitecture {{ COMMA_JOIN(mr.compatibility.rearchitecture, each wrapped in <code>) OR "—" }}</p>
          {{ IF NOT EMPTY(mr.migration_deltas) }}
          <p class="em">Migration changes</p>
          <table><tbody>
            {{ FOR EACH delta IN mr.migration_deltas }}
            <tr><td><span class="mark">{{ delta.category }}</span></td><td>{{ delta.description }}</td></tr>
            {{ END FOR }}
          </tbody></table>
          {{ END IF }}
          {{ IF NOT EMPTY(mr.blocks) OR NOT EMPTY(mr.tuning) }}
          <p class="em">Findings</p>
          <table><tbody>
            {{ FOR EACH b IN mr.blocks }}
            <tr><td><span class="mark mark-block">blocks</span></td><td>{{ b.message }} <em>Fix: {{ b.remediation }}</em></td></tr>
            {{ END FOR }}
            {{ FOR EACH t IN mr.tuning }}
            <tr><td><span class="mark">tune</span></td><td>{{ t.message }} <em>{{ t.remediation }}</em></td></tr>
            {{ END FOR }}
          </tbody></table>
          {{ END IF }}
          {{ IF NOT EMPTY(mr.additional_targets) }}
          <p class="em">Separate-modality targets</p>
          <table><tbody>
            {{ FOR EACH t IN mr.additional_targets }}
            <tr><td><code>{{ t.capability }}</code></td><td><span class="mark">{{ t.status }}</span></td><td>{{ t.service }}</td></tr>
            {{ END FOR }}
          </tbody></table>
          {{ END IF }}
          <p class="note"><strong>Evaluation:</strong> {{ mr.evaluation.mode }} — {{ mr.evaluation.gates.length }} gates, e.g. &ldquo;{{ ONE representative gate quoted VERBATIM from mr.evaluation.gates }}&rdquo; ·
            <strong>Rollout:</strong> {{ mr.rollout.strategy }} ({{ mr.rollout.gate }}) · <strong>Verification:</strong> {{ mr.verification.probe_status }}/{{ mr.verification.availability_claim }} — probe the exact (model, path) before implementation.</p>
        </details>
      </div>
    </div>
    {{ END IF }}
  </div>
</div>
{{ END FOR }}

<!-- ═══ 4. TARGET ARCHITECTURE ═══ -->
<h2><span class="no">4.</span>Target architecture</h2>
<div class="figure">
<pre class="mermaid">{{ DIAGRAM_MERMAID }}</pre>
<div class="figcap">Figure 1 — {{ DIAGRAM_CAPTION from diagram.md }}</div>
</div>

<h3>4.1&nbsp; Component detail</h3>
<table>
  <thead><tr><th>{{ IF UNITS.length > 1 }}Agent / Workload{{ ELSE }}Workload{{ END IF }}</th><th>Entry point</th><th>Compute</th><th>Model access</th><th>Supporting services</th></tr></thead>
  <tbody>
    {{ FOR EACH unit IN UNITS }}
    <tr><td class="em">{{ unit.id }}</td><td>{{ unit.trigger_text from context-signals }}</td>
        <td>{{ unit.compute_text from verdict + runtime cards }}</td>
        <td>{{ unit.model_access_text }}</td>
        <td>{{ unit.supporting_services_text }}</td></tr>
    {{ END FOR }}
  </tbody>
</table>

<h3>4.2&nbsp; Security &amp; networking</h3>
<table>
  <thead><tr><th>Concern</th><th>Design</th></tr></thead>
  <tbody>
    <tr><td>IAM</td><td>{{ IAM_DESIGN from runtime cards' Serving & security }}</td></tr>
    <tr><td>Network</td><td>{{ NETWORK_DESIGN }}</td></tr>
    <tr><td>Content safety</td><td>{{ CONTENT_SAFETY_DESIGN }}</td></tr>
    {{ IF ANY_UNIT_NEEDS_ISOLATION }}
    <tr><td>Untrusted input isolation</td><td>{{ ISOLATION_DESIGN }}</td></tr>
    {{ END IF }}
    <tr><td>Secrets</td><td>{{ SECRETS_DESIGN }}</td></tr>
  </tbody>
</table>

<h3>4.3&nbsp; Scaling behavior &amp; service limits</h3>
<table>
  <thead><tr><th>{{ IF UNITS.length > 1 }}Agent / Workload{{ ELSE }}Workload{{ END IF }}</th><th>Scales by</th><th>Relevant limits (verify current)</th></tr></thead>
  <tbody>
    {{ FOR EACH unit IN UNITS }}
    <tr><td class="em">{{ unit.id }}</td><td>{{ unit.scaling_behavior from runtime cards }}</td>
        <td>{{ unit.service_limits from VOLATILE_FACTS + service cards }}</td></tr>
    {{ END FOR }}
  </tbody>
</table>
<p class="note">{{ DEPLOYMENT_TOPOLOGY_NOTE if multi-runtime split }}</p>

<!-- ═══ 5. TEMPORAL MIGRATION (conditional) ═══ -->
{{ IF TEMPORAL_UNITS_PRESENT }}
<h2><span class="no">5.</span>Temporal migration</h2>
<div class="callout"><b>Scope.</b> Workflow orchestration code is not rewritten. This migration
moves the Workers and the work they execute; there is no Step Functions translation.</div>
<table>
  <thead><tr><th>Layer</th><th>Decision</th><th>Basis</th></tr></thead>
  <tbody>
    <tr><td>Server</td><td>{{ TEMPORAL_SERVER_DECISION }}</td><td>{{ TEMPORAL_SERVER_BASIS }}</td></tr>
    <tr><td>Polling tier</td><td>{{ TEMPORAL_POLLING_DECISION }}{{ IF SERVERLESS_WORKERS_IN_TIER1 }} <span class="pre-flag">Public Preview</span>{{ END IF }}</td>
        <td>{{ TEMPORAL_POLLING_BASIS }}</td></tr>
    <tr><td>Execution tier</td><td>{{ TEMPORAL_EXECUTION_SUMMARY }}</td>
        <td>{{ TEMPORAL_EXECUTION_BASIS }}</td></tr>
  </tbody>
</table>

<h3>Cutover runbook — {{ TEMPORAL_RUNBOOK_NAME }}</h3>
<div class="callout warn"><b>Preconditions (not optional).</b> {{ TEMPORAL_PRECONDITIONS }}</div>
<ol class="steps">
  {{ FOR EACH (index, step) IN TEMPORAL_RUNBOOK_STEPS }}
  <li><b>{{ step.title }}.</b> {{ step.body }}</li>
  {{ END FOR }}
</ol>
<p class="note"><b>Bedrock follow-up.</b> {{ TEMPORAL_BEDROCK_FOLLOWUP }}</p>
{{ END IF }}

<!-- ═══ COST SUMMARY ═══ -->
<h2><span class="no">{{ TEMPORAL_UNITS_PRESENT ? "6" : "5" }}.</span>Cost summary</h2>
<p>Order-of-magnitude estimates from the assessed volumes; {{ COST_DOMINANT_NOTE }}.
All figures assume {{ REGION }} on-demand pricing (cached {{ VOLATILE_FACTS.pricing_date }}).</p>

<h3>{{ TEMPORAL_UNITS_PRESENT ? "6.1" : "5.1" }}&nbsp; Per-{{ UNITS.length > 1 ? "unit" : "workload" }} breakdown</h3>
<table>
  <thead><tr><th>{{ IF UNITS.length > 1 }}Agent / Workload{{ ELSE }}Workload{{ END IF }}</th><th>Compute</th><th>Model tokens</th><th>Other</th><th>Subtotal /mo</th></tr></thead>
  <tbody>
    {{ FOR EACH unit IN UNITS }}
    <tr><td class="em">{{ unit.id }}</td>
        <td>{{ unit.breakdown.compute }}</td>
        <td>{{ unit.breakdown.model_tokens or "—" }}</td>
        <td>{{ unit.breakdown.other }}</td><td class="em">{{ unit.monthly_magnitude_usd }}</td></tr>
    {{ END FOR }}
    {{ IF TEMPORAL_UNITS_PRESENT }}
    <tr><td colspan="4">{{ TEMPORAL_COST_SUMMARY }}</td><td class="em">{{ TEMPORAL_COST }}</td></tr>
    {{ END IF }}
    <tr><td class="em">Total</td><td>{{ ESTIMATE.total_compute }}</td><td class="em">{{ ESTIMATE.total_model }}</td><td>{{ ESTIMATE.total_other }}</td><td class="em">{{ ESTIMATE.total_monthly_magnitude_usd }}</td></tr>
  </tbody>
</table>

<h3>{{ TEMPORAL_UNITS_PRESENT ? "6.2" : "5.2" }}&nbsp; Assumptions</h3>
<ul class="plain">
  {{ FOR EACH a IN ESTIMATE.assumptions }}
  <li>{{ a }}</li>
  {{ END FOR }}
</ul>

<h3>{{ TEMPORAL_UNITS_PRESENT ? "6.3" : "5.3" }}&nbsp; What moves the number</h3>
<table>
  <thead><tr><th>Driver</th><th>Effect</th><th>Lever</th></tr></thead>
  <tbody>
    {{ FOR EACH driver IN ESTIMATE.drivers }}
    <tr><td>{{ driver.driver }}</td><td>{{ driver.effect }}</td>
        <td>{{ driver.lever }}</td></tr>
    {{ END FOR }}
  </tbody>
</table>
<p class="note">Not included: one-time engineering effort (policy: never presented as dollar
figures). For migration entry points, precise TCO comparison and current-spend delta are produced by the migration plugins (see the llm-to-bedrock or gcp-to-aws run for model-by-model
pricing deltas); this estimate shows target-state run cost only. {{ IF ESTIMATE === null }}Estimate may be absent if the phase failed, or for add_capabilities which bypasses Estimate.{{ END IF }}</p>

<!-- ═══ NEXT STEPS ═══ -->
<h2><span class="no">{{ TEMPORAL_UNITS_PRESENT ? "7" : "6" }}.</span>Next steps</h2>
<ol class="steps">
  {{ FOR EACH (index, step) IN NEXT_STEPS }}
  <li><b>{{ step.title }}</b> — {{ step.body }}{{ IF step.path }} (<code>{{ step.path }}</code>){{ END IF }}.</li>
  {{ END FOR }}
</ol>

<!-- ═══ GENERATED ARTIFACTS ═══ -->
<h2><span class="no">{{ TEMPORAL_UNITS_PRESENT ? "8" : "7" }}.</span>Generated artifacts</h2>
<table>
  <thead><tr><th>File</th><th>Contents</th></tr></thead>
  <tbody>
    <tr><td><a class="dl-link" href="recommendation.md" download>recommendation.md</a></td><td>full document{{ IF UNITS.length > 1 }} incl. system topology{{ END IF }}{{ IF TEMPORAL_UNITS_PRESENT }} (§3b){{ END IF }}{{ IF TEMPORAL_UNITS_PRESENT }} and Temporal (§3c) sections{{ END IF }}</td></tr>
    <tr><td><a class="dl-link" href="design.json" download>design.json</a></td><td>units[], platform decision{{ IF PLATFORM.mode === "split" }} (split){{ END IF }}, per-{{ UNITS.length > 1 ? "unit" : "workload" }} verdicts{{ IF TEMPORAL_UNITS_PRESENT }}; Temporal block (Way, per-queue rules){{ END IF }}</td></tr>
    <tr><td><a class="dl-link" href="diagram.md" download>diagram.md</a></td><td>architecture diagram source</td></tr>
    <tr><td><a class="dl-link" href="estimate.json" download>estimate.json</a></td><td>per-{{ UNITS.length > 1 ? "unit" : "workload" }} magnitudes and total</td></tr>
    {{ IF SCAFFOLD_EXISTS }}
    {{ FOR EACH file IN scaffold/ }}
    <tr><td><a class="dl-link" href="scaffold/{{ file }}" download>scaffold/{{ file }}</a></td><td>{{ file_purpose from scaffold metadata }}</td></tr>
    {{ END FOR }}
    {{ END IF }}
  </tbody>
</table>

<!-- ═══ DOCUMENT FOOTER ═══ -->
<div class="doc-foot">
  {{ VOLATILE_FACTS_TEXT from recommendation.md Section 12 freshness footer }}
  &nbsp;·&nbsp; This report is a draft for review.{{ IF UNITS.length > 1 }} <b>Multi-unit system ({{ UNITS.length }} {{ PLATFORM.mode === "split" ? "independent" : "consolidated" }} workload{{ UNITS.length > 1 ? "s" : "" }}).</b>{{ END IF }}
</div>

</div><!-- .page -->

<script>
mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
// Fallback: if Mermaid fails to render, show ASCII
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    var diagrams = document.querySelectorAll('.mermaid');
    diagrams.forEach(function(el) {
      if (!el.querySelector('svg')) {
        console.warn('Mermaid diagram failed to render, consider ASCII fallback');
      }
    });
  }, 2000);
});
</script>
</body>
</html>
```

**CSS/HTML cross-check (do this before writing the file):** every class used in the
template HTML must be defined — either by the shell block or by the content CSS above —
and every content-CSS rule must have HTML that uses it. No orphans in either direction.

**Postcondition:** The "Workload recommendations" section (§3) contains one `.unit-sec` card
per unit. When `UNITS.length === 1`, §1.1 is omitted and the summary table lists the single
unit. When `TEMPORAL_UNITS_PRESENT === false`, the Temporal section is omitted and sections
renumber accordingly (cost is §5, not §6).

## Step R3 — Open in browser

After writing the file, open it immediately:

```bash
open "$RUN_DIR/recommendation-report.html"
```

On Linux: `xdg-open "$RUN_DIR/recommendation-report.html"`

If the command fails (no GUI environment), output the path:

```
Recommendation report ready — open in your browser:
file://{{ RUN_DIR }}/recommendation-report.html
```

## Step R4 — Report completion

Output to the parent `generate.md`:

```
Recommendation report written to {{ RUN_DIR }}/recommendation-report.html
```

Do NOT update `.phase-status.json` — the parent `generate.md` handles phase completion.
