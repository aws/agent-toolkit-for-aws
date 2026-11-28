# Report Appendix Skeleton (canonical, cloud-agnostic)

## What this file is

This is the **canonical appendix build skeleton** for every full-mode
migration report the plugin renders: the single source of truth for how the
appendix block of `migration-report.html` is assembled — the shared pre- and
post-steps, the stable lettering, and the purpose, trigger, data sources,
table shapes and content rules of Appendices A through J. It is the prose side
of the appendix contract that `$PLUGIN_ROOT/scripts/validate-migration-report.py`
(the shared validator) checks by machine. It is vendored byte-for-byte into
each migration skill; the skill's **report spec** (the phase file that builds
`migration-report.html`) loads this copy and then supplies the values written
here as `⟨parameter⟩` — the artifact names, the source cloud's service names,
the scripts the run emitted, the security "source equivalent" column. Read
nothing outside the skill you are running: the report spec plus this vendored
copy (plus `references/vendored/report/report-decision-core.md`, which owns
the executive sections) are the only files the appendix build needs.

Where this file and the shared validator disagree, the validator wins — report
the discrepancy rather than working around it.

The executive-summary block (Decision Summary through "What this assessment
rests on"), the cost anchors, the CSS readability contract and the
draft-footer rule live in `references/vendored/report/report-decision-core.md`.
This file does not restate them; it governs what follows the last executive
section.

## Shared steps

### Step 0 — artifact pre-check (precondition)

The JSON artifacts the report is rendered from must pass the plugin's artifact
validator **before** any report content is built. A report built on an
artifact that fails its own contract inherits the defect and hides it. Who
runs the check is ⟨precheck_owner⟩ — either the report spec loads the skill's
validate-artifacts fragment itself, or the caller runs the plugin-root
`validate-artifacts.py` with `--run-dir "$MIGRATION_DIR"` and
⟨precheck_skill_flag⟩ in the main window before dispatching the spec.
The semantics are the same either way:

- Run the **required** checks only (field presence — never rewrite artifact
  prose).
- On failure: surface every failure line to the user, emit
  `GATE_FAIL | phase=generate | fragment=artifacts-report | reason=artifact_contract`,
  name the phase that owns the failing artifact so the user can re-run it, do
  **NOT** patch any artifact to pass validation, and do **NOT** write
  `migration-report.html`.
- A check that did not run (e.g. `python3` unavailable) is reported as skipped
  and is never recorded as a pass.
- When the caller owns the check, Step 0 inside the spec is a precondition,
  not a command: if the spec is executing, the caller's check passed or was
  reported as skipped. Never write the report when the caller reports the
  check as failed.

### Load the skeleton and fail closed

The report spec loads `references/vendored/report/report-appendix-skeleton.md`
(this file) for the appendix block and renders it in ⟨report_mode⟩ (`full`, or
`ai_only` for a skill that has that path). There is no hand-rolled fallback.
If this file is missing, emit
`GATE_FAIL | phase=generate | fragment=artifacts-report | reason=renderer_missing`
and stop — a report that silently degrades to unstructured HTML is worse than
one that fails loudly, because the phase still reports success and the
customer still receives the file.

### Cost-figure anchors

The `data-cost-key` anchors (`aws_monthly_balanced`, `current_monthly`, the
optional per-tier keys) live inside `exec-costs` per the decision core; the
appendix block adds none. A skill that checks further anchors with a
skill-local validator declares them as ⟨extra_anchors⟩ (or `none`).

### Accounting split

When the skill writes a generation ledger (`generation-warnings.json`), every
mapping / service / headline count the report states — the headline "N
services", a per-section subtotal, the appendix mapping table's row count —
MUST equal the ledger's accounted count, ⟨accounting_ledger_field⟩. The report
body, the Terraform `migration_summary` count and the ledger must all agree.
State the split in the report body as ⟨accounting_split_sentence⟩, at
⟨accounting_location⟩, so a bare number never appears to disagree with the
discovery count. Deferred and unsupported rows are still rows the customer
must plan for — never present them as generated. A skill with no ledger
declares these three parameters `n/a`.

### Stable appendix lettering (pinned by the contract test)

Use the same stable customer-visible appendix labels as the full-report
contract. The letter is part of the `<h2>` heading and of the TOC label, and it
does **not** shift when a conditional section is absent (a run with no AI
track has no Appendix D and still labels its artifact catalog Appendix E):

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

Render `appendix-artifacts` before `appendix-config`. Conditional sections keep
their reserved letters when absent — for example, an infra-only report still
uses Appendix E for artifacts, never renumbering it to D. The shared validator
checks section IDs, not these letters; the plugin's contract test pins the
lettering table, so a skill keeps the labels exactly as written here. A skill that adds its own appendix uses a
dotted slot (as A.1 does) so the shared letters never move.

Which rows a skill renders is ⟨appendices_rendered⟩: per letter, **required**,
**conditional** (with the trigger from this file), or a **declared omission**
with a one-line reason. The validator's defaults are: `appendix-services`,
`appendix-costs`, `appendix-steps`, `appendix-artifacts` required in `full`
mode; `appendix-ai`, `appendix-artifacts`, `appendix-config`,
`appendix-glossary` required in `ai_only` mode; `appendix-ai`,
`appendix-config`, `appendix-security`, `appendix-security-gap`,
`appendix-assumptions`, `appendix-optimization`, `appendix-glossary` optional
and checked when present. A skill with a `--profile` follows that profile's
sets instead (§ Declared skill exceptions).

### Appendix divider

The appendix block follows the last executive section, clearly separated with
a `<div class="appendix-header">⟨appendix_header_text⟩</div>` divider (a
`<div>`, not a `<section>`, so section validation stays unambiguous), then
`<div class="appendix">` containing one `<section id="appendix-…">` per
appendix. Never nest `<section>` elements.

### Draft-for-review footer

Every report carries a footer stating it is a draft for review, generated from
the migration artifacts, and that figures are estimates to validate before
decisions. The footer names the generator as ⟨footer_text⟩ (the shape is
"Generated by ⟨source_cloud⟩ to AWS Migration Advisor — draft for review;
verify figures against source JSON artifacts before executive sign-off."). Do
not emit a plan-share link (landing page not live); the `exec-share` CFO brief
is unaffected.

### Validate the rendered report (mandatory gate)

The prose in this file is not self-enforcing. After the HTML is written, run
the shared validator first, then the skill-local add-on validator when the
skill has one — the exact commands are ⟨validator_invocation⟩, with absolute
paths (cwd must not be load-bearing), the artifact flags
(`--estimation-infra`, `--estimation-ai`, `--aws-design`) only when those files
exist in `$MIGRATION_DIR`, and `--migration-dir "$MIGRATION_DIR"` on every real
run:

```sh
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" "$MIGRATION_DIR/migration-report.html" [--mode <full|ai_only>] [--profile <name>] [--estimation-infra <path>] [--estimation-ai <path>] [--aws-design <path>] --migration-dir "$MIGRATION_DIR"
```

- Every command must print `REPORT_OK` and exit 0; that is the only pass.
- Exit 1 (`REPORT_FAIL`) from any of them: **rename** the file to
  `migration-report.incomplete.html` (do not delete), emit every failure line
  to the user, and report incompleteness to the parent. Never present, patch
  around, or describe a stub as a complete report.
- Any other exit code means the validator did not run (e.g. `python3`
  unavailable). Tell the user; never record it as a pass.
- The shared validator is stdlib-only. Do not ask the user to install Vale,
  Pa11y, axe, Lighthouse, Chromium, or any other prose/accessibility tooling,
  and do not skip validation because such tooling is absent — it is never
  required.
- `REPORT_OK` is not a substitute for this file or for the decision core: the
  validator rejects a report that has the right section IDs but omits the
  content those artifacts require. A report written only to satisfy the
  section-ID list will fail.

### Post-write appendix self-check

After writing the HTML, verify (in addition to the executive-side checks the
report spec keeps):

1. **Appendix not a stub**: Appendix B contains at least three cost line items
   with dollar amounts; Appendix A contains per-service mappings (not only
   JSON file links).
2. **Security baseline surfaced**: when `projected_costs.breakdown.security_baseline`
   exists, GuardDuty or dollar-formatted component costs appear in
   `appendix-security` / `appendix-costs`.
3. **Conditional sections**: each conditional appendix is present only when
   its trigger in this file holds (AI appendix only when AI artifacts exist;
   Bedrock monitoring rows only when `bedrock_monitoring.tf` exists or the
   AI setup script contains `== 6. Bedrock budget and cost anomaly monitor`).
4. **Configuration provenance**: when `preferences.json` exists and
   `appendix-config` renders, its table has Question / assumption, Your
   choice, Source and Design consequence columns populated from `prompt` and
   `design_consequence`.
5. **Glossary last**: a full report that renders `appendix-glossary` ends with
   it, rendered as a two-column `<table class="glossary-table">`.
6. **Cost Optimization**: when `optimization_opportunities[]` is non-empty,
   `exec-optimization` and `appendix-optimization` are present and
   TOC-linked; the opportunity table is never buried only in Appendix B.

## Appendices

Everything each appendix needs is specified here, from the artifacts the skill
writes — no other skill has to be installed. Copy figures and choices from the
artifacts; do not invent rows. Every table has a `<caption>` and `scope="col"`
on header cells; currency columns carry `class="num"`; monthly figures are
whole dollars.

### Appendix A — Service Recommendations (`appendix-services`, REQUIRED)

The per-resource mapping table belongs here, never in the executive flow. One
row (or block) per design mapping from ⟨design_mapping_source⟩, at least two
(the validator's depth floor), each carrying:

- the source resource — name and type / kind, in ⟨source_cloud⟩ terms
- the AWS service recommendation
- **How the mapping was chosen** — **Standard pairing**, **Tailored to your
  setup**, or **Estimated from billing only**, per the skill's
  ⟨how_we_chose_vocabulary_ref⟩; the JSON `confidence` may appear in
  parentheses for support
- the rationale text from the design artifact
- ⟨service_row_extras⟩ — any extra columns or blocks the skill adds (rubric
  criteria, disposition, the size the reader controls)

Mappings the design or ledger classified as deferred, consumed topology or
unsupported appear with that disposition stated — a deferral is not silent.
If `human_expertise_required: true`: include the specialist guidance callout.
A section that only says "see `aws-design.json`" is a stub and fails.

### Appendix B — Cost Estimates (`appendix-costs`, REQUIRED)

At least three content blocks (tables or paragraphs — the validator's depth
floor).

**Per-line cost breakdown table** from ⟨cost_breakdown_source⟩ — columns:
Service Category (or line), AWS Service, Monthly Cost (Balanced) as
`class="num"`, Calculation / Notes, plus ⟨extra_cost_columns⟩. Mandatory rows
when present in the source: ⟨mandatory_breakdown_rows⟩, and always
`security_baseline` — include its cost AND its component sub-rows from
`components` (GuardDuty, cloudtrail_s3, budgets, …) when the key exists. Do
NOT collapse `security_baseline` into "other". Surface GuardDuty explicitly.

**Baseline breakdown** (when ⟨baseline_breakdown⟩ exists): the current
⟨source_cloud⟩ categories vs the infra total.

**Three-tier comparison table** with columns: **Tier** (name + subtitle as the
decision core's tier subtitles define them), Monthly Cost, vs ⟨source_cloud⟩
Monthly, Annual Difference. Repeat the **How to read cost tiers** guidance as a
`<details class="reading-guide">` after the table, or include a one-line
pointer: _See executive summary — the three tiers are pricing scenarios for one
design: Balanced is right-sized, Premium is Balanced plus the Multi-AZ / HA
uplift, Optimized is Balanced minus a commitment discount on RI/SP-eligible
lines; generated Terraform matches **Balanced**._

**Floors and provenance.** State the baseline provenance (user-stated bracket
vs invoice vs unavailable) and the accuracy band. When the estimate's
⟨floor_fields⟩ say so (`is_floor: true`, non-empty unpriced-line lists), label
that total a **known-cost floor** and name the unpriced lines; when a `$0`
consumption line was substituted with a reserved-equivalent rate, say so —
never present it as free. When no floor applies, say no unpriced lines remain.

> **Security baseline costs** are included as a line item in the breakdown
> above. For control names and ⟨source_cloud⟩ equivalents, see Appendix G.

### Appendix B.1 — Savings Plans and Reserved Instances (`appendix-optimization`, conditional)

**Trigger:** `optimization_opportunities[]` is non-empty in any of
⟨optimization_sources⟩. Then the executive `exec-optimization` section (decision
core) is required, and the line-level table MUST be a standalone
`<section id="appendix-optimization">` immediately after `appendix-costs`. **Do
not** put the opportunity table only as an `<h3>` inside Appendix B — a table
buried in Appendix B does **not** pass the report validator.

**Optimization opportunities table** with columns: Optimization, Target,
Monthly Savings (or Est. savings), Commitment, Effort. Eligibility follows the
skill's ⟨ri_sp_eligibility_ref⟩. Every row is incremental to **Balanced**; the
commitment rows (Savings Plans, Reserved Instances) are what **Optimized**
already includes at their mid-point rate, so never add them on top of
Optimized. Spot, S3 Intelligent-Tiering / Infrequent Access and other
consumption-model or storage-class rows are opportunities only — no tier
assumes them.

When an AI estimate exists beside the infra estimate, merge the two sources'
rows. **The two sources use different field names for the same rendered
column** — apply this key map, do not assume the field names match:

| Column          | Infra key (`estimation-infra.json`)                          | AI key (`estimation-ai.json`)                                                                                                                                             |
| --------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Optimization    | `opportunity`                                                | `opportunity`                                                                                                                                                             |
| Target Services | `target_services`                                            | `target_services`                                                                                                                                                         |
| Monthly Savings | `savings_monthly` (fall back to `savings_percent` when null) | `potential_savings_monthly` (fall back to `potential_savings_percent` when null — the AI schema requires this field on every entry precisely so this cell is never blank) |
| Commitment      | `commitment`                                                 | `commitment`                                                                                                                                                              |
| Effort          | `implementation_effort`                                      | `implementation_effort`                                                                                                                                                   |

**Render the Activate-credits caveat once, below the whole merged table, scoped only to the infra-side rows it actually describes — never per-row and never implied to cover every row in a merged table.** That caveat applies only to RI/Savings Plan upfront costs. If the merged table contains any infra-side row with a `commitment` other than `"none"` (Compute SP, Database SP, RDS RI, DynamoDB reserved capacity, ElastiCache Reserved Nodes), render the caveat once beneath the table, worded to make clear it applies to those rows specifically (e.g. "The Activate-credits note below applies to the Reserved Instance/Savings Plan rows only"). Do not render it at all if the table contains only AI-side rows. AI-side rows (including Provisioned Throughput, which is billed hourly with no upfront fee) never trigger this caveat — if any AI-side row is `type: provisioned_throughput`, its Commitment cell reads the exact wording from that row's JSON (`"no-commit, 1-month, or 6-month"`), never the infra-side "1-year or 3-year" vocabulary, and never implies an upfront cost.

**Sequencing (`available`), when AI-side rows exist:** AI-side rows carry an
`available` field (`day_1`, `after_2_weeks_production_traffic`,
`after_sustained_traffic_baseline`). Group or flag rows so a reader can tell
day-1 levers (prompt caching, Batch API, model downsizing, input token
reduction, multi-model tiered routing) apart from traffic-gated ones
(Intelligent Prompt Routing, Provisioned Throughput) — do not present all
optimization rows as equally actionable at migration time.

### Appendix C — Migration Steps and Rollback (`appendix-steps`, REQUIRED)

Numbered migration phases, each as an `<h3>Phase N — …</h3>` block (the
validator requires at least two, counting whichever is larger: these headings
or the section's table rows), in ⟨phase_order_source⟩ order so the report and
the runbook agree, each carrying:

- Phase name and what moves — name the clusters / services that move in each
  phase.
- The scripts the operator runs in that phase, by name and in order:
  ⟨scripts_list⟩. State that every script is dry-run by default and that
  nothing was executed during Generate.
- The cutover strategy each phase depends on — ⟨cutover_strategy_fields⟩ from
  `preferences.json` — and a prerequisite blocker named verbatim when the
  preferences record one.
- Dependencies and the verification that gates the next phase.
- Deferred items from the design, each named with its recommendation, so a
  deferral the runbook carries is not silent in the report.

Do not quote week or hour durations — the plugin has none that are
calibrated. Communicate time as stage order plus duration drivers.

**Rollback procedure** — a table (Track | Trigger | Action | Recovery
objective) built from ⟨rollback_source⟩: keep the ⟨source_cloud⟩ resource
running until verification passes; DNS and traffic cutover last; then the
track-specific rows ⟨rollback_rows⟩. Add an AI track row (feature-flag rollback
to the current provider) when `ai-migration/` exists.

### Appendix D — AI Migration (`appendix-ai`, conditional)

**Trigger:** an AI track exists — `aws-design-ai.json` or `estimation-ai.json`
is present in `$MIGRATION_DIR/`. The build instruction for this appendix is
skill-specific and lives at ⟨ai_appendix_spec⟩ in the report spec; a skill with
no AI track declares the omission. The lettering row above is canonical: when
the appendix is absent, Appendix E keeps its letter.

### Appendix E — Generated Artifacts Catalog (`appendix-artifacts`, REQUIRED)

List every file and directory generated during the Generate phase, one line
on what each is for:

- `terraform/` — the `.tf` files and **`README.md`**
- the migration scripts the run emitted (⟨scripts_list⟩)
- `MIGRATION_GUIDE.md`, `README.md`
- ⟨pack_extras⟩ — skill-specific pack files (AI adapters, warnings ledger,
  validation report, startup-programs guide)

Check for actual file/directory existence before listing. Do not list files
that were not generated. Deferred or unsupported work appears here only as
"not generated". When `decision-report.html` exists from a prior Decide run,
note that this report supersedes it.

**Data artifacts (for detailed review):** a table (Artifact | Contents) of
⟨data_artifacts⟩ — `preferences.json`, the source inventory file, the
estimation artifact, the design artifact, the AI workload profile when present.
Open any JSON file with a text editor or `cat <filename> | python3 -m json.tool`
for formatted output.

### Appendix F — Your Configuration (`appendix-config`, conditional)

**Trigger:** `preferences.json` exists in `$MIGRATION_DIR/`.

Key decisions that shaped this migration plan. Read every constraint object in
⟨preferences_groups⟩ — iterate every key, do not hardcode a subset. Render an
HTML table, one row per constraint object:

| Column                    | Source                                                                                                                                 |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Question / assumption** | `prompt` on each constraint object                                                                                                     |
| **Your choice**           | formatted `value` (human-readable; expand arrays)                                                                                      |
| **Source**                | `chosen_by` → "User answer", "Extracted from infrastructure", "Default applied", or "Derived"                                          |
| **Source signal**         | the `source` field when present (provenance such as `terraform:…` or `default:…`); leave blank for user/derived rows; optional column |
| **Design consequence**    | `design_consequence` on each constraint object                                                                                         |

The validator checks the `<thead>` for the Question (or Assumption), Your
choice, Source and Design consequence columns and at least two rows.

**Assumption flag:** Rows where `source` starts with `"default:"` are
unverified assumptions — label them "Default applied" and use italic text or a
border marker so the reader can spot values that were not explicitly verified.
Do not lower text contrast: assumption rows must retain the same WCAG AA
contrast floor as every other table row, including on alternating row
backgrounds.

**Critical-default caveats:** ⟨critical_default_caveats⟩ — the skill's
callouts for defaulted or unknown compliance, spend baseline and availability
answers, placed at the top of Appendix F, before the table, so they are
immediately visible.

**Sort order:** user-answered rows first, then extracted, then default, then
derived.

**Legacy fallback:** If a constraint object lacks `prompt` or
`design_consequence` (pre-extension runs), use the catalog in
⟨preferences_schema_ref⟩ keyed by constraint name — never omit the appendix or
leave cells empty.

**Do not** reduce this section to a key/value dump without question text and
consequences.

### Appendix G — Security Capabilities (`appendix-security`, conditional)

**Trigger:** the infra track ran and `terraform/baseline.tf` was emitted.

Full security-baseline capability table. The executive flow carries only a
teaser (`exec-security-teaser`); this appendix is the complete picture. One
row per always-on control `terraform/baseline.tf` emits, from
⟨baseline_controls_table⟩, with columns Control · What it does for you ·
⟨security_equivalent_label⟩ · Monthly cost, plus ⟨security_extra_columns⟩
(Threat mitigated, Terraform resource in a `class="mono"` cell).

State the budget limit `baseline.tf` wrote (⟨budget_limit_formula⟩) and say
plainly that the Estimate does **not** roll CloudTrail storage, GuardDuty,
Config or Security Hub into `aws_monthly_balanced` — the cost column is an
indicative list-price range, not a line of the estimate.

**Compliance-conditional** (only when ⟨compliance_field⟩ contains `soc2`,
`pci`, `hipaa` or `fedramp`): add rows for AWS Config (continuous recording of
resource configuration changes; change audit trail for SOC 2 / PCI) and
Security Hub + FSBP (automated security checks against AWS best practices;
baseline posture scoring). When the compliance list is empty or `["unknown"]`,
say the add-on was not generated and what would trigger it.

**Cost guardrails** (when `$MIGRATION_DIR/ai-migration/bedrock_monitoring.tf`
exists, or the AI setup script in `$MIGRATION_DIR/ai-migration/` that
⟨cost_guardrail_rows⟩ names contains the step
`== 6. Bedrock budget and cost anomaly monitor`, which
bedrock-migration-assessment's Generate writes): the Bedrock budget and
cost-anomaly rows, ⟨cost_guardrail_rows⟩. Add an
**Inference profiles (tagged)** row for per-model Cost Explorer attribution,
never from the setup script (it creates no inference profile), and only when the
actual generated `bedrock_monitoring.tf` contains an enabled
`aws_bedrock_inference_profile` resource and its `bedrock_inference_profile_arns`
output, and the selected model/API supports that profile. A file's existence,
a comment mentioning profiles, or a disabled resource is not evidence of this
control. Apply this same condition to the artifact description in Appendix E.
These are detective controls, not spend caps. You will know within ~24 hours
if something goes wrong — not at invoice time.

**What the baseline does NOT cover (you still need):**

- SOC 2: Qualified auditor, formal policies, employee training, vendor management
- HIPAA: BAA with AWS, qualified HIPAA auditor, data handling policies
- PCI: QSA assessment, network segmentation validation, pen testing
- FedRAMP: Agency-level NIST 800-53 controls, ATO process

**For detailed cost breakdown:** See Appendix B (cost estimates include the
security baseline as a line item).

**To enable / opt out:** `terraform apply` on `baseline.tf`; opting out is
⟨opt_out_procedure⟩. Point at `terraform/README.md`.

### Appendix H — Security Gap Analysis (`appendix-security-gap`, conditional)

**Trigger:** the infra track ran and a ⟨source_cloud⟩ security posture exists
to compare against.

Table: Capability | ⟨source_cloud⟩ (detected) | AWS (generated) | Gap / action.
Minimum rows, with the source-side names from ⟨gap_source_names⟩:

- Network perimeter (source firewall / network rules → VPC security groups and
  subnets)
- Identity & access (source identities and roles → IAM roles and scoped
  policies)
- Audit logging (source audit log → CloudTrail in `baseline.tf`)
- Threat detection (source detector, if enabled → GuardDuty in `baseline.tf`)
- Public data exposure (public buckets or `allUsers`-style grants detected in
  the design or inventory → S3 account-level public-access block)
- Observability cost shift (the source's logging allowance vs the CloudWatch
  always-free tier; pull the gap text from the `estimation-infra.json`
  observability line's ⟨observability_note_field⟩ — do **not** say CloudWatch
  has no free tier; compare tier sizes and note the estimate assumes usage
  above free-tier limits)
- ⟨gap_extra_rows⟩ — skill-specific rows (secrets management, bastion /
  operator access) or `none`

The Gap / action column compares the two postures and names the action
(net-new control, mapped 1:1, review in production), not a bare "different".

### Appendix I — Assumptions, Exclusions, and Validation (`appendix-assumptions`, required by the skill spec; optional in the validator's default set, required under `--profile heroku`)

**Pricing confidence table:** domain / source, status, accuracy band, last
updated — from the estimate's ⟨pricing_source_fields⟩ and
`accuracy_confidence`. When the fields record a region mismatch, say which
region the rates are from and which the design targets. Add an AI row from
`estimation-ai.json` when it exists.

**Exclusions list** — one line each, every one that applies:

- Deferred services, each with its recommendation (and whether the deferred
  resource is cost-bearing on ⟨source_cloud⟩ today, when the estimate says so)
- Unpriced and partially priced lines — say the totals are floors when the
  ⟨floor_fields⟩ say so
- Professional services / dual-run period / human labor (not modeled)
- ⟨exclusion_extras⟩ — the skill's further exclusions (egress categories,
  licensing, unexpired reservations, unsupported semantics, `terraform apply`
  prohibitions)
- Utilization-based right-sizing (**Known limitations**): ⟨rightsizing_limitations⟩
  — one line per affected resource or group, each naming the action that
  would unlock measured sizing

**Terraform validation:** ⟨terraform_validation_rule⟩ — whether
`validation-report.json` may be read at this point and what to say when it
cannot.

**Design and generation warnings:** ⟨warnings_sources⟩ — design `warnings[]`
and ledger entries, so a resource that produced no Terraform is accounted for
in writing.

### Appendix J — Glossary (`appendix-glossary`, conditional)

**Trigger:** every full report that is not a declared profile exception
renders it, as the final section.

Expand acronyms on first use and include a dedicated final
`<section id="appendix-glossary">` glossary appendix — the audience is startup
founders, not AWS specialists. Include only terms that appear in the report
(⟨glossary_examples⟩ are typical), plus the monthly-run-rate definition.
Render the glossary as a bordered two-column `<table class="glossary-table">`
with `Term` and `Meaning` headers, one distinct cell per term and definition,
a caption, `scope="col"` headers and at least three rows. Do not render it as
a `<dl>` or loose paragraphs. Define monthly run rate as recurring modeled
cloud-service charges and explicitly distinguish it from total cost of
ownership.

## Skill spec must supply

The report spec (the phase file inside the skill's own references that loaded
this one) supplies a value for every parameter below. A parameter the skill
does not use is declared "n/a" or "none" with a one-line reason — never left
silent.

| Parameter                                                                                   | What it is                                                                                                                                         |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| ⟨source_cloud⟩                                                                              | The source platform's display name (same value as the decision core)                                                                               |
| ⟨report_mode⟩                                                                               | `full`, plus `ai_only` when the skill has that path                                                                                                |
| ⟨precheck_owner⟩ / ⟨precheck_skill_flag⟩                                                    | Who runs the Step 0 artifact pre-check (in-spec fragment vs caller-owned script) and the `--skill <name>` flag                                      |
| ⟨appendices_rendered⟩                                                                       | Per letter A–J (+ A.1): required / conditional (trigger) / declared omission (reason)                                                               |
| ⟨appendix_header_text⟩                                                                      | The text inside the `appendix-header` divider                                                                                                      |
| ⟨footer_text⟩                                                                               | The "Generated by … — draft for review …" footer line                                                                                              |
| ⟨extra_anchors⟩                                                                             | Skill-local `data-cost-key` anchors beyond the decision core's, or `none`                                                                           |
| ⟨accounting_ledger_field⟩ / ⟨accounting_split_sentence⟩ / ⟨accounting_location⟩             | The ledger's accounted-count field, the split sentence, and the section that states it; or `n/a`                                                   |
| ⟨validator_invocation⟩                                                                      | The exact shared-validator command block (artifact flags, `--profile` when declared) and any skill-local add-on validator                           |
| ⟨design_mapping_source⟩                                                                     | Where Appendix A rows come from                                                                                                                    |
| ⟨how_we_chose_vocabulary_ref⟩                                                               | Where the mapping-confidence vocabulary is defined for the skill (same value as the decision core); `n/a` allowed with a reason                     |
| ⟨service_row_extras⟩                                                                        | Extra Appendix A columns or blocks                                                                                                                 |
| ⟨cost_breakdown_source⟩ / ⟨mandatory_breakdown_rows⟩ / ⟨baseline_breakdown⟩ / ⟨floor_fields⟩ / ⟨extra_cost_columns⟩ | Appendix B inputs: the per-line source, rows that must appear, the current-cost breakdown, the floor fields, extra columns                        |
| ⟨optimization_sources⟩ / ⟨ri_sp_eligibility_ref⟩                                            | Appendix B.1 inputs: which estimates carry `optimization_opportunities[]`; the skill's RI/SP eligibility reference (same value as the decision core) |
| ⟨phase_order_source⟩ / ⟨scripts_list⟩ / ⟨cutover_strategy_fields⟩ / ⟨rollback_source⟩ / ⟨rollback_rows⟩ | Appendix C inputs                                                                                                                                  |
| ⟨ai_appendix_spec⟩                                                                          | Where the skill's Appendix D build instruction lives, or a declared omission                                                                        |
| ⟨pack_extras⟩ / ⟨data_artifacts⟩                                                            | Appendix E inputs                                                                                                                                  |
| ⟨preferences_groups⟩ / ⟨preferences_schema_ref⟩ / ⟨critical_default_caveats⟩                | Appendix F inputs                                                                                                                                  |
| ⟨baseline_controls_table⟩ / ⟨security_equivalent_label⟩ / ⟨security_extra_columns⟩ / ⟨budget_limit_formula⟩ / ⟨compliance_field⟩ / ⟨cost_guardrail_rows⟩ / ⟨opt_out_procedure⟩ | Appendix G inputs                                                                                                                                  |
| ⟨gap_source_names⟩ / ⟨gap_extra_rows⟩ / ⟨observability_note_field⟩                           | Appendix H inputs                                                                                                                                  |
| ⟨pricing_source_fields⟩ / ⟨exclusion_extras⟩ / ⟨rightsizing_limitations⟩ / ⟨terraform_validation_rule⟩ / ⟨warnings_sources⟩ | Appendix I inputs                                                                                                                                  |
| ⟨glossary_examples⟩                                                                         | Appendix J example terms                                                                                                                           |

Beyond parameters, the report spec carries the skill's own **declared add-ons**
(appendices or rules that exist only for that source platform, such as a dotted
A.1 slot) and **declared omissions** (canonical appendices the skill never
renders, each with its reason). Nothing in the report spec may contradict a
rule here except through § Declared skill exceptions.

## Declared skill exceptions

The default contract above is the shape every full report follows. A skill
whose appendix block differs in **shape** — a different required-appendix set,
a canonical appendix it never renders, or a check it cannot satisfy yet —
declares that divergence in two places that must agree:

1. In its report spec, in ⟨appendices_rendered⟩ and under a "Declared
   exceptions" heading: every appendix the default requires that the skill
   does not render, every check it switches off, and a one-line reason for
   each.
2. In `SKILL_PROFILES` inside `$PLUGIN_ROOT/scripts/validate-migration-report.py`,
   as a named profile with `required_sections` per mode, `not_required`
   (section ID → reason), and `skip` (check name → reason). The skill passes
   `--profile <name>` on every validator run.

Rules:

- No silent divergence. A skill without a profile follows the default sets
  exactly; a skill with a profile lists every `not_required` and `skip` entry
  in its spec with the validator's reason.
- Vocabulary-only differences (different table columns, a differently named
  section) are declared exceptions pending a content follow-up that converges
  the skill on the default contract — they are not a second contract.
- Add-ons never need a profile: a skill may require **more** than the default
  (a dotted appendix slot, extra anchors, a skill-local validator) and
  declares those in its spec.
- Where this file and the validator disagree, the validator wins; list the
  discrepancy in the change that fixes one of them.
