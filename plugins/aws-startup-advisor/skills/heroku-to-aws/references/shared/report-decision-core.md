# Report Decision Core (shared renderer spec)

The `decision-summary` / `decision-basis` / `exec-costs` / `developer-workflow` /
`what-if-scenarios` / `next-steps` sections below are the **decision core** — the single source of
truth for verdict, cost, and next-step rendering. Two consumers load this
file; the content rules are identical in both:

| Mode         | Loaded by                                      | Output                                                                                      |
| ------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **decision** | `estimate-assemble.md` Decision gate, choice A | Standalone `decision-report.html` + `DECISION.md` — decision core only, CTA footer          |
| **full**     | `generate-report.md` Step 2                    | `migration-report.html` — the decision-core sections, plus the five appendices declared in `generate-report.md` |

The full report and the decision report share the GCP visual shell defined in
`generate-report.md` ("Visual shell"). The full report also has five
appendices (`appendix-services`, `appendix-costs`, `appendix-config`,
`appendix-security`, `appendix-assumptions`). **Decision mode omits that
appendix block** — Generate has not run, so the security baseline and the
artifact catalog are not execution output yet. This file is where that
decision-mode override is declared.

**Never patch one output into the other.** When Execute runs after a Decide
run, `migration-report.html` is rendered **fresh from the artifacts** — do not
extend, edit, or splice `decision-report.html`. All data needed for either
output lives in the JSON artifacts (`estimation-infra.json`, `preferences.json`,
`aws-design.json`, `scenarios/` when present).

**Decision mode is pre-execution for THIS decide-complete cycle — not "no
generated files exist anywhere on disk."** `validate-heroku-migration-report.py
--mode decision` checks `.phase-status.json`'s `phases.generate` value
(`"pending"` or absent passes; `"completed"`/`"in_progress"` fails), not
whether `terraform/` or `generation-*.json` exist. A prior cycle's execution
pack — including a customer's hand-edited `baseline.tf`/`variables.tf` or
their own `terraform.tfvars`/state — may legitimately still be present after a
workshop reprice (`workshop.md` § Entry never deletes it) and coexists with a
fresh decision without being touched or archived.

## Startup credits callout (both modes)

`preferences.json` `global.startup_program_status` (Clarify Q17) drives one 💡
callout in `decision-summary`. It is rendered in **both** modes — the credits
decision belongs at the decision moment, not only after Generate.

| `startup_program_status` | `decision-summary` copy |
| ------------------------ | ----------------------- |
| `eligible_founders`      | May state "You're flagged as eligible for AWS Activate Founders credits (up to $5,000)" — apply before `terraform apply`; credits do not apply retroactively |
| `eligible_portfolio`     | May state Portfolio credits (up to $200,000) and the Activate Provider Org ID requirement (get it from your VC/accelerator before applying) |
| `has_credits`            | Note that Activate credits are already on the account and apply to the new AWS charges; **no "apply for" language** |
| `unknown` or absent      | **Neutral only:** e.g. "Review AWS Activate credits tiers (Founders for self-funded startups, Portfolio for VC- or accelerator-backed ones) — funding stage not confirmed in Clarify." **Do not** write "eligible for Founders", "your status: eligible_*", or any tier dollar amount ($5K / $200K) |

Rules:

- **Always a 💡 callout, never a metric card.** A credit offer is a call-to-action
  with a link, not a measurement; a card in `.metrics` gives it false equivalence
  with the run rate. Render it as a `<div class="callout callout-info">` (pale blue,
  see the visual shell) inside `decision-summary`, after the cost one-liner.
- **Apply link (required).** Whenever `decision-summary`, `next-steps`, or
  `DECISION.md` mentions AWS Activate, include a clickable link to the official
  apply page: `<a href="https://aws.amazon.com/startups/credits/">AWS Activate
  credits</a>` (HTML) / `[AWS Activate credits](https://aws.amazon.com/startups/credits/)`
  (Markdown). The link goes **inside the callout**, so the action stays attached
  to the benefit. `validate-heroku-migration-report.py` fails a `decision-summary`
  that names Activate without this link, in both modes.
  The validator's tier and apply-language rules read **only** this `.callout-info`
  fragment, so cost lines elsewhere in `decision-summary` may carry any figure.
- **Eligibility, one line:** Pre-Series B, founded in the last 10 years, AWS
  account on the Paid Tier plan, new to Activate or requesting more than before.
- **Do not infer the tier** from Heroku spend, the AWS estimate, or the Q16
  contract. The tier comes from Q17 only.
- **Not retroactive.** When the status is not `has_credits`, say that credits
  apply only to charges after approval, so the founder applies before
  `terraform apply`. In full mode, also add one `next-steps` item: "Apply for AWS
  Activate credits before `terraform apply`" (omit for `has_credits`).
- The RI/Savings Plan caveat under `cost-optimization` ("Activate credits don't
  cover RI/Savings Plan upfront costs") is unchanged and separate from this callout.
- `DECISION.md` carries the same callout as one Markdown paragraph (💡 lead,
  same wording rules, Markdown apply link) directly under the cost line.
- The Decision gate's "See your AWS credits" web handoff (upload `plan.json` to
  AWS Startups Migrate) is a different program and stays as is; this callout
  does not replace it.

## Decision-mode specifics

- **HTML shell:** same inline-CSS `<head>` as the full report
  (`generate-report.md` Step 2 "Visual shell"), title "Heroku to AWS
  Migration Assessment — Decision Report". Body order: `decision-summary`,
  then `<nav class="toc">`, then `exec-share`, then `decision-basis` (when
  present), `exec-costs` →
  `developer-workflow`, then `exec-timeline`, `what-if-scenarios` (when
  present), and `decision-cta` (decision-mode only; it replaces
  `next-steps`). Do not render `.appendix-header` or any `appendix-*` section.
- **Required section IDs in decision mode:** `decision-summary`, `exec-share`,
  `exec-timeline`, `exec-costs` (+ conditional `decision-basis`,
  `what-if-scenarios` per their triggers in `generate-report.md`).
  `developer-workflow` is always rendered (the
  `decision-summary` pointer for a `critical` DX answer links to it, so the
  link must resolve) but is not in the validator's required set.
- **Section content:** render `decision-summary`, `exec-share`, `decision-basis`,
  `exec-costs` / `what-if-scenarios`, `developer-workflow`, and `exec-timeline` using the
  **exact same rules** as `generate-report.md` Step 2 — do not restate them
  here; that file is the single source of truth for content rules in both
  modes.
- **`developer-workflow` pre-execution wording (decision-mode override):**
  nothing has been generated yet, so the status word **Generated** reads
  **Will be generated**, and "is generated" / "the generated Terraform" in a
  cell read "will be generated" / "the Terraform that Generate will produce".
  **Covered**, **Build** and **No equivalent** are unchanged — they do not
  depend on Generate having run. The status rules themselves are the same in
  both modes: the per-target one-off-command and log-tailing rules (EKS apps
  get `kubectl exec` / `kubectl run` / a Kubernetes Job and `kubectl logs -f`,
  with CloudWatch tailing **Build** because log forwarding is additional setup;
  never ECS Exec, `eb ssh` or run-task), the per-target config-vars rules (EB / Fargate / EKS each have
  their own rule — EKS apps get the Kubernetes Secret + `secretKeyRef` wording,
  never the Fargate task-definition wording) and the Scheduler row's status,
  which is **computed** from `aws-design.json` `services[]` vs `deferred[]`
  (both exist at the Decision gate) and never asserted — a deferred
  `advanced-scheduler` renders as **Build** with its deferred count in
  `decision-report.html` and `DECISION.md` exactly as in the full report. The
  decision report shows the user what Generate will and will not emit before
  they commit to it.
- **`decision-cta` (required, replaces `next-steps` in decision mode):**
  `<section id="decision-cta">` — "**Ready to execute?** Say \"generate the
  Terraform and migration scripts\" and I'll produce the full execution pack
  (Terraform, migration scripts, MIGRATION_GUIDE.md) from this same analysis."
  Plus one line: "This decision report was generated without execution
  artifacts; the full migration report replaces it if you proceed."
- **`DECISION.md` (required twin):** same content as the HTML, as plain
  Markdown (Slack/GitHub-friendly): verdict headline, the Activate credits paragraph (§ Startup credits callout), the same CFO paragraph
  under a "Share with your CFO" heading, cost line/table, the timeline
  planning band, `would_flip_if[]` when present, the developer-workflow
  table and its closing paragraph(s) as a Markdown table under a "Developer
  workflow" heading (same pre-execution wording as the HTML), the CTA line.
  No HTML tags.
- **Validation:** run
  `python3 "<SKILL_BASE>/scripts/validate-heroku-migration-report.py" "$MIGRATION_DIR/decision-report.html" --mode decision --migration-dir "$MIGRATION_DIR"`
  (absolute paths — cwd must not be load-bearing; `--migration-dir` is required so the
  decision-mode pre-execution checks run) and fix failures before presenting.
- **Cost labeling, reader vocabulary:** unchanged from `generate-report.md` —
  every dollar figure is "estimated monthly"; no `*.json` filenames or
  `aws_*.` resource IDs in `decision-summary` / `exec-costs` /
  `what-if-scenarios`. The scope-matched block's two variants (zero matched
  baseline → "(percentage not applicable)"; `attribution == "incomplete"` →
  the provisional label naming the unattributed add-ons, never
  "decision-grade") and its `heroku_monthly_like_for_like` anchor apply in
  decision mode exactly as in `generate-report.md` Step 1; the validator
  checks the anchor in both modes.

## Full-mode specifics

`migration-report.html` uses `next-steps` instead of `decision-cta`, and it
adds the appendix block from `generate-report.md`. Decision mode does not
render that block.
