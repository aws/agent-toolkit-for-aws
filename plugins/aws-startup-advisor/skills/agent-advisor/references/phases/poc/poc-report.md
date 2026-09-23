---
_fragment: poc-report
_of_phase: poc
_contributes:
  - poc/poc-report.html
---

# POC sub-step: Build the HTML POC report

> Loaded by poc.md Step 4.5 after the POC files are written (Step 3) — for BOTH modes.
> Produces `$RUN_DIR/poc/poc-report.html` and opens it in the browser. Non-blocking: if
> generation fails, log a warning and continue; the files themselves are the deliverable.

## Overview

A single self-contained HTML file summarizing the POC: what was generated, what changed from
the original app, how to deploy it, the deployment architecture, and what still needs
verifying. Uses the **v3 document shell** (same visual system as recommendation-report.html):
inline CSS from `references/report-shell.md` + SRI-pinned Mermaid — no other external
dependencies. The report sits in `$RUN_DIR/poc/`, so artifact download links are relative to
that dir.

**Before writing the HTML:** load the shared shell (`references/report-shell.md`) — inline
its CSS block and its SRI-pinned mermaid@10.9.3 script tag. The v3 shell defines
`.help-strip`, `.doc-head`, `.timeline`, `.feat-grid`, `.callout`, document tables, and all
other shared components. The help CTA is GATED on `report-help-banner.md`'s `banner_status`:
it currently reads `SUPPRESSED` (support page not launched), so render NO help strip. Only when
it flips to `LIVE` do you substitute `{{ HELP_URL }}` with the single-source destination URL
from `references/report-help-banner.md` — never hardcode it here.

## Step P0 — Gather data

| Variable           | Source                                                                                                                                                     |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POC_FILES`        | the files actually written under `$RUN_DIR/poc/` (walk the dir; EXCLUDE `__pycache__/`, `*.pyc`, and the report itself)                                    |
| `DEPLOYMENT_MODEL` | `confirm.json.deployment_model` (primary unit; per-unit in `UNITS[].deployment_model` for a multi-unit POC)                                                |
| `UNITS`            | `design.json.units[]` — one POC per unit; each carries `id`, `effective_runtime`, and `model_recommendation` (null for a model-less non-agent unit)        |
| `MODEL_DISPLAY`    | resolved Bedrock model PER UNIT (Step 2 of poc.md) — `null`/omitted for a unit whose `model_recommendation` is null; never a single global model           |
| `PLAN_BACKED`      | true if this POC came from a migration plan (3-F / 3-H plan-backed)                                                                                        |
| `CHANGES`          | when plan-backed: `aws-design-ai.json.ai_architecture.code_migration.files_to_modify[].changes[]` and `before_after_example` — the applied migration edits |
| `SOURCE_MODEL`     | when plan-backed: the source model replaced (from the plan)                                                                                                |
| `MODE`             | Mode A (deliverables) or Mode B (assisted build) from Gate 2b                                                                                              |
| `DEPLOY_STEPS`     | the staged steps from `$RUN_DIR/plan.md`                                                                                                                   |
| `DIAGRAM_MERMAID`  | compose a POC-deployment diagram (see Step P2)                                                                                                             |
| `TODOS`            | every `TODO: verify` / deferred / drift note left in the generated files + plan.md                                                                         |
| `LEDGER`           | Mode B only: `$RUN_DIR/poc/created-resources.json` (deployed resources)                                                                                    |
| `RUN_ID`           | from `.phase-status.json`                                                                                                                                  |

## Step P1 — File purpose map

For each file in `POC_FILES`, write a one-line purpose. Multi-unit layout: when
`poc/<unit-id>/` directories exist, list files nested per unit. Single-unit layout
collapses flat (no unit subdirs). Infer from the filename/role:

- `app/app.py` → "Migrated app (original UI/handler; local-dev only after migration)"
- `app/core.py` → "Shared LLM logic — used by both the UI and the entrypoint server"
- `app/agentcore_app.py` → "AgentCore Runtime entrypoint server (/invocations + /ping)"
- `app/pyproject.toml` / `requirements.txt` → "Dependencies (provider swap applied)"
- `Dockerfile` → "Container image for AgentCore Runtime"
- `deploy.sh` → "One-command deploy (creates real AWS resources)"
- `README.md` → "Runbook"
- `harness.json` → "Declarative Harness agent definition (the deploy artifact)"
- otherwise → infer a short purpose from the file's first comment/docstring.

## Step P2 — POC deployment diagram

Compose a `flowchart TD` Mermaid block showing the POC's RUNTIME shape (what actually runs
after `deploy.sh`), using the same topology discipline as build-diagram.md. **Render one node per
unit in `UNITS`, each on ITS OWN `effective_runtime`, NOT hardcoded to AgentCore and NOT a single
global runtime/model** — the POC now supports agentcore / ecs / eks / lambda / batch / fargate /
serverless_workers, and a MIXED or Temporal system has several units on different runtimes. For a
single-unit POC this collapses to one node.

- Per unit, primary flow (solid): the runtime the POC actually deploys for THAT unit
  (AgentCore Runtime, an ECS/Fargate task, an EKS Deployment, a Lambda function, an AWS Batch
  job, or a Temporal worker) → Bedrock model (that unit's own `MODEL_DISPLAY`) **only when THAT
  unit's `model_recommendation` is non-null**. A model-less non-agent unit renders its runtime
  node with NO Bedrock node or invoke edge — never attach the primary unit's model to a secondary
  unit's runtime. User → runtime for agent/service units; a Temporal worker's flow is Temporal
  Server → worker. Every unit's deployment is shown — a secondary unit is never omitted.
- Session memory (solid to a store node) if the app has it.
- Enabled AgentCore services as a dotted-attached subgraph (from `confirm.json`) — AgentCore
  units only.
- For plan-backed framework POCs: annotate the original UI (e.g. "Chainlit UI — local dev
  only") as a dashed node OFF the production path.
  Include an ASCII fallback in a `<details>` block, same as build-diagram.md.

## Step P3 — Write `$RUN_DIR/poc/poc-report.html`

Use the **v3 document shell** (same structure as recommendation-report.html). The report
follows this structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Deployable POC</title>
<!-- SRI-pinned mermaid@10.9.3 script tag — inline it VERBATIM from the shared shell
     (references/report-shell.md), same tag/integrity hash. -->
{{ SHARED_SHELL_MERMAID_TAG from references/report-shell.md }}
<style>
  /* ── Shared chrome ── load references/report-shell.md and inline its CSS block
     HERE (chart tokens, reset & base, .page layout, .doc-head family, h2/h3 + .no,
     table/th/td, .lede/.note, .rule-cite/.pre-flag, .callout, .help-strip,
     .feat-grid, .timeline, .doc-foot). Single-sourced there so poc-report and
     recommendation-report share identical chrome. ── */
  {{ SHARED_SHELL_CSS from references/report-shell.md }}

  /* ── POC-specific content CSS ── */
  .diff-before { background:#fef2f2; border-left:3px solid #ef4444; }
  .diff-after  { background:#f0fdf4; border-left:3px solid #16a34a; }
  .diff-block { font-family: ui-monospace, monospace; font-size:12px; padding:12px 14px;
                border-radius:6px; white-space:pre-wrap; margin:6px 0; }
</style>
</head>
<body>

<div class="page">

<!-- ═══ DOCUMENT HEADER ═══ -->
<div class="doc-head">
  <div class="doc-kicker">AWS Migration POC · agent-advisor</div>
  <div class="doc-title">Deployable POC: {{ SYSTEM_NAME or "Agent Platform" }}</div>
  <div class="doc-meta">
    <span>Run <b>{{ RUN_ID }}</b></span><span>Date <b>{{ RUN_DATE }}</b></span>
    <span>Mode <b>{{ MODE_TEXT }}</b></span>
  </div>
</div>

<!-- ═══ HELP STRIP — GATED on report-help-banner.md `banner_status`. It currently reads
     SUPPRESSED (support page not launched): OMIT this whole block — render NOTHING here. When
     it flips to LIVE, render the strip below and substitute {{ HELP_URL }} with the
     single-source destination URL from report-help-banner.md (do NOT hardcode the URL here):
<div class="help-strip">
  <div class="txt"><b>Need help getting to AWS?</b> &nbsp;Install the AI agent for hands-on
  guidance, talk with an AWS expert, or work with a certified AWS Partner.</div>
  <a class="btn" href="{{ HELP_URL }}" target="_blank" rel="noopener">Explore your options</a>
</div>
     ═══ -->

<!-- ═══ 1. STATUS ═══ -->
<h2><span class="no">1.</span>Status</h2>
{{ IF WARNING_TODOS }}
<div class="callout warn"><b>Warning.</b> {{ WARNING_TODOS }}</div>
{{ END IF }}
<p class="lede">{{ MODE_TEXT }}</p>

<!-- ═══ 2. MIGRATION CHANGES (when plan-backed) ═══ -->
{{ IF PLAN_BACKED }}
<h2><span class="no">2.</span>Migration changes</h2>
<p>Key changes applied from the migration plan:</p>
{{ FOR EACH change IN CHANGES }}
<div class="diff-block diff-before">{{ change.before }}</div>
<div class="diff-block diff-after">{{ change.after }}</div>
{{ END FOR }}
{{ END IF }}

<!-- ═══ FILES ═══ -->
<h2><span class="no">{{ PLAN_BACKED ? "3" : "2" }}.</span>Files</h2>
<div class="feat-grid">
  {{ FOR EACH file IN POC_FILES }}
  <div class="feat">
    <div class="feat-icon">📄</div>
    <div>
      <div class="feat-name"><a class="dl-link" href="{{ file.relative_path }}" download>{{ file.name }}</a></div>
      <div class="feat-desc">{{ file.purpose }}</div>
    </div>
  </div>
  {{ END FOR }}
</div>

<!-- ═══ DEPLOY STEPS ═══ -->
<h2><span class="no">{{ PLAN_BACKED ? "4" : "3" }}.</span>Deploy steps</h2>
<div class="timeline">
  {{ FOR EACH (index, step) IN DEPLOY_STEPS }}
  <div class="tstep">
    <div class="tnum">{{ index }}</div>
    <div>
      <div class="tstep-title">{{ step.title }}</div>
      <div class="tstep-body">{{ step.body }}</div>
    </div>
  </div>
  {{ END FOR }}
</div>

<!-- ═══ ARCHITECTURE ═══ -->
<h2><span class="no">{{ PLAN_BACKED ? "5" : "4" }}.</span>Architecture</h2>
<div class="figure">
<pre class="mermaid">{{ DIAGRAM_MERMAID }}</pre>
<div class="figcap">Figure 1 — {{ DIAGRAM_CAPTION }}</div>
</div>

<!-- ═══ KNOWN ISSUES / TODO ═══ -->
<h2><span class="no">{{ PLAN_BACKED ? "6" : "5" }}.</span>Known issues &amp; TODOs</h2>
<ul class="plain">
  {{ FOR EACH todo IN TODOS }}
  <li>{{ todo }}</li>
  {{ END FOR }}
</ul>

<!-- ═══ MODE B RESOURCES (Mode B only) ═══ -->
{{ IF MODE === "B" }}
<h2><span class="no">{{ PLAN_BACKED ? "7" : "6" }}.</span>Deployed resources</h2>
<table>
  <thead><tr><th>Type</th><th>Name</th><th>Region</th><th>Status</th></tr></thead>
  <tbody>
    {{ FOR EACH resource IN LEDGER }}
    <tr><td>{{ resource.type }}</td><td>{{ resource.name }}</td>
        <td>{{ resource.region }}</td><td>{{ resource.status }}</td></tr>
    {{ END FOR }}
  </tbody>
</table>
<p class="note">See <code>cleanup.sh</code> for teardown.</p>
{{ END IF }}

<!-- ═══ DOCUMENT FOOTER ═══ -->
<div class="doc-foot">
  This POC is a disposable deployment-proof — your original repo was not modified.
  For the authoritative in-repo migration (git branch, tests, eval), run
  <code>/aws-startup-advisor:llm-to-bedrock</code>. Generated {{ RUN_DATE }}.
</div>

</div><!-- .page -->

<script>
mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
</script>
</body>
</html>
```

The shell provides `.doc-head`, `.help-strip`, numbered `h2`/`h3`, document `table`, `.feat-grid`,
`.timeline`, `.callout`, and `.doc-foot`. POC-specific styles (`.diff-before`, `.diff-after`) are
added after the shared block. Dynamic numbering: sections shift by 1 when plan-backed (migration
changes is §2, pushing files/deploy/architecture/todos/resources down).

## Step P4 — Open in browser

```bash
open "$RUN_DIR/poc/poc-report.html"    # macOS
xdg-open "$RUN_DIR/poc/poc-report.html"  # Linux
```

If it fails (no GUI), print: `POC report ready — open: file://$RUN_DIR/poc/poc-report.html`

## Step P5 — Report completion

Return to poc.md. Do NOT update `.phase-status.json` — poc.md Step 6 handles phase state.
