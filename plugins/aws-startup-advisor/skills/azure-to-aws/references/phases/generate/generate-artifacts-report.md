---
_fragment: artifacts-report
_of_phase: generate
_contributes:
  - migration-report.html
---

# Generate — Stakeholder Report

> **Fragment unit.** See `generate.md` for how it is composed into the phase.

The customer-facing report. **It leads with the cluster-level architecture rationale** —
what workloads were found, what each becomes, and why — and moves the per-resource
mapping table to an appendix. This is the visible payoff of the holistic goal and the
part a customer actually reads; a 40-row table as the headline buries the argument.

**Execute the steps in order.**

## Inputs

Read from `$MIGRATION_DIR/`: `aws-design.json` (`clusters[]` with `pattern_status` /
`target_architecture` / `rationale`, `services[]`, `deferred[]`, `warnings[]`),
`estimation-infra.json` (cost comparison, tiers, reservations, `is_floor`),
`azure-resource-inventory.json` (drift + reservation signals), `preferences.json`,
and `scenarios/index.json` if it exists (workshop what-ifs).

**Load `references/shared/report-decision-core.md` and render it in `full` mode.** That file is
the single source of truth for every executive-summary section (Decision Summary through "What
this assessment rests on") — verdict typography, the required section IDs, baseline-quality and
not-comparable rules, Activate wording, and the CSS readability contract all live there. Do not
restate or paraphrase its rules here.

There is no hand-rolled fallback. If that file is missing, emit
`GATE_FAIL | phase=generate | fragment=artifacts-report | reason=renderer_missing` and stop — a
report that silently degrades to unstructured HTML is worse than one that fails loudly, because
the phase still reports success and the customer still receives the file.

## AI-only report path (REQUIRED when there is no infrastructure track)

An app-code-only / AI-workload repo produces the AI artifacts but **no infra track** —
`aws-design.json`, `estimation-infra.json`, and `terraform/` do not exist, only
`ai-workload-profile.json`, `aws-design-ai.json`, `estimation-ai.json`,
`generation-ai.json`, and `ai-migration/`. `migration-report.html` is **still a required
`_produces` artifact on this path** — never skip it. A completed Generate with no report
is the silent-degradation failure this fragment exists to prevent.

When `aws-design.json` and `estimation-infra.json` are BOTH absent but the AI artifacts
exist, render `migration-report.html` in **AI-only mode**: still load
`references/shared/report-decision-core.md` for the decision-core section rules
(verdict typography, `exec-assumptions`, `exec-risks`, Activate wording, the CSS
readability contract), but source every figure from the AI artifacts and OMIT the infra
executive/appendix sections (`exec-services`, `exec-costs`, `appendix-costs`,
`appendix-services`, `appendix-steps`) that no infra track can populate. Required sections
on this path: `decision-summary`, `exec-assumptions`, `exec-risks`, `appendix-ai`,
`appendix-artifacts`, `appendix-config`, `appendix-glossary`. Render:

- **`decision-summary`** — the verdict from `estimation-ai.json` -> `recommendation`
  (e.g. already-on-Bedrock -> `go`, model_change:false), the AI monthly run rate from
  `cost_comparison` (labeled estimated, with the accuracy band), and the residual Azure
  coupling as the real migration work (e.g. retarget Azure AI Search -> OpenSearch
  Serverless / Bedrock Knowledge Bases; re-embed at the target dimension).
- **`exec-optimization`** (REQUIRED when `estimation-ai.json` -> `optimization_opportunities`
  is non-empty, e.g. a `provisioned_throughput` entry) — the same standalone-section rule
  as the full report; a buried table does not satisfy it.
- **`appendix-ai`** — the model migration table from `aws-design-ai.json` (each
  `models_to_migrate` with model_change / migration_path), the feature-flag rollback
  (`AI_PROVIDER`), and the vector-store re-index note.
- **`appendix-artifacts`** — the `ai-migration/` catalog (setup, adapter/mantle, comparison
  test, `bedrock_monitoring.tf`) and `STARTUP_PROGRAMS.md`.
- **`appendix-config`** — the `preferences.json` values and every `chosen_by: "default"`
  assumption (token volume, compliance-unknown, region) with its consequence.

Step 3.5's infra resource-count rule does not apply (no `aws-design.json` services); the
AI accounting lives in `appendix-ai`. Step 5 validates this report with `--mode ai_only`.

## Step 1: Lead with cluster-level rationale (REQUIRED — `_assert`)

The report OPENS with the workload story, one block per `clusters[]` entry:

- the workload (its primary + members, in plain language),
- its `target_architecture` and the cluster `rationale` — what it becomes and why,
- for an `unclassified` cluster or `pattern_status: catalog_absent`, say so plainly so
  the report does not overclaim architectural insight it does not have.

The per-resource mapping table (azure_type → aws_service, confidence) goes in an
**appendix**, not the body. The phase `_assert` fails if the table leads.

## Step 2: Cost section

Present the Premium / Balanced / Optimized comparison from `estimation-infra.json`, and
**surface, not hide**:

- `is_floor: true` and any unpriced lines — say the total is a floor and why.
- Reserved-instance baselines, and that a `$0` consumption line was substituted with an
  RI-equivalent rate (never presented as free).
- The baseline provenance (user-stated bracket vs invoice) and the accuracy band.

**Cost-figure anchor (machine-checkable, REQUIRED).** Wrap the Balanced AWS monthly figure
inside `<section id="exec-costs">` in a `data-cost-key="aws_monthly_balanced"` attribute
(value = `projected_costs.aws_monthly_balanced`), so `validate-migration-report.py` can
confirm the rendered dollars match the estimate. Optional per-tier:
`data-cost-key="aws_monthly_premium"` / `"aws_monthly_optimized"`. Example:
`<strong data-cost-key="aws_monthly_balanced">Est. $155/mo</strong>`. The attribute is not
reader-visible text. The anchor must sit on a rendered element inside `exec-costs` itself —
not in an HTML comment, and not merely somewhere else in the document (a decision-summary
hero metric does not satisfy this rule). **It is mandatory whenever
`projected_costs.aws_monthly_balanced` exists and `exec-costs` is rendered — a missing
anchor is a validator FAIL, not a skip.** The `current_monthly` anchor that the GCP and
Heroku reports carry does not apply here: this skill records current spend under
`current_costs.azure_monthly`, which the validator does not map, so only untagged
illustrative figures remain unchecked.

## Step 3: Surface the rest

- **Drift** between declared IaC and running state (when a live/RDfA source ran).
- **Deferred** specialist items, each named with its recommendation.
- **Availability downgrades** — where a zone-redundant source maps to single-AZ.
- The **what-if comparison** when `scenarios/index.json` has ≥ 2 scenarios (REQUIRED by
  the phase `_assert` in that case).

## Step 3.5: Resource count (REQUIRED)

Any **mapping / plan / service / headline** count the report states — the headline "N
services", a per-section subtotal, or the appendix mapping table's row count — MUST equal
`generation-warnings.json.accounted`: the accounted headline = generated services (each
plan-fold counted ONCE via its parent) + `deferred[]`. `skipped[]` entries (config sources,
observability, plan-folded children) are still recorded in `generation-warnings.json` for
completeness but are **EXCLUDED from the accounted headline** — a folded or config-only
resource is not a distinct billed service, and counting it double-counts against its parent.
Do **not** count only the emitted `.tf` resources, and do **not** count `services[]` alone —
a deferred resource is still a resource the customer must plan for. This mirrors the
PRIMARY-services headline rule in gcp-to-aws `report-decision-core.md` § 1 (secondaries
excluded). The report-body mapping count, the Terraform `migration_summary` count
(`generate-artifacts-infra.md` Step 4), and `generation-warnings.json.accounted` must all
agree.

**Surface the split in the report body (REQUIRED).** State the three figures side by side so
the reader sees raw estate vs. plan rather than a bare number that appears to disagree with
the discovery count: **"N discovered · M mapped services · A accounted (M + D deferred)"** —
where N = `total_resources` (raw discovered), M = generated primary services, D = `deferred[]`,
and A = `accounted` (= M + D).

**Exception — the discovery/"discovered" count is its own figure.** A statement about what
was _discovered_ — "Discovery identified N resources", "N resources discovered", the raw
Azure estate size — references `azure-resource-inventory.json` `total_resources` (the RAW
discovered count), NOT `accounted`. `total_resources` legitimately exceeds `accounted`
(the accounted set excludes resources that were never mapped/planned — e.g. free/zero-cost
or non-migratable items), so forcing the discovery label to equal `accounted` understates
what was actually found. Keep the two distinct: the discovery figure = `total_resources`;
every mapping/plan/service/headline figure = `accounted` (with the three-way agreement
above). This mirrors gcp-to-aws `report-decision-core.md` where the discovered/current
count is a separate figure from the mapping count.

## Step 3.75: Stable appendix lettering (REQUIRED — validator-enforced)

Use the same stable customer-visible appendix labels as the full-report contract. The letter is
part of the heading and TOC label; it does not shift when a conditional section is absent:

| Section ID              | Visible heading prefix                               |
| ----------------------- | ---------------------------------------------------- |
| `appendix-services`     | Appendix A — Service Recommendations                 |
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

Render `appendix-artifacts` before `appendix-config`. Conditional sections keep their reserved
letters when absent — for example, an infra-only report still uses Appendix E for artifacts,
never renumbering it to D. The plugin-root report validator checks both `<h2>` and TOC labels.

## Step 4: Draft-for-review footer (REQUIRED — `_assert`)

Every report carries a footer stating it is a draft for review, generated from the
migration plan, and that figures are estimates to validate before decisions.

> **Plan-share links are GATED OFF** (landing page not live). Do NOT emit a share link.

## Step 5: Validate the rendered report (REQUIRED — mandatory gate)

The prose above is not self-enforcing. Run the plugin's report validator, which is
source-cloud-agnostic and already present at plugin root — resolve it the same way the
`tf-best-practices` policy checker is resolved:

```bash
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" \
  --estimation-infra "$MIGRATION_DIR/estimation-infra.json" \
  --estimation-ai "$MIGRATION_DIR/estimation-ai.json" \
  --migration-dir "$MIGRATION_DIR"
```

Pass `--estimation-infra` / `--estimation-ai` only when those files exist in `$MIGRATION_DIR`.

**AI-only path:** when there is no infra track (no `estimation-infra.json`), add `--mode ai_only` so the validator requires the AI-only section set (`decision-summary`, `exec-assumptions`, `exec-risks`, `appendix-ai`, `appendix-artifacts`, `appendix-config`, `appendix-glossary`) instead of the infra sections. Pass `--estimation-ai "$MIGRATION_DIR/estimation-ai.json"`.

Branch on the exit code, exactly as gcp-to-aws's `generate.md` does:

- `0` (`REPORT_OK`) — proceed.
- `1` (`REPORT_FAIL`) — **rename** the file to `migration-report.incomplete.html` (do not
  delete), emit every failure line to the user, and report incompleteness to the parent. Do NOT
  present a stub as a complete report.
- any other code — the validator did not run (e.g. `python3` unavailable). Tell the user
  validation was skipped; never record it as a pass.

The validator is stdlib-only. Do not ask the user to install Vale, Pa11y, axe, or Chromium, and
do not skip validation because such tooling is absent — it is never required.

## Status — implemented (build step: Generate)

Implemented, mirroring gcp-to-aws's `generate-artifacts-report.md` but honoring azure's
holistic contract: cluster-level rationale leads, per-resource table is an appendix,
cost floor / reservations / drift / deferrals / availability-downgrades / what-if all
surfaced, draft-for-review footer present.
