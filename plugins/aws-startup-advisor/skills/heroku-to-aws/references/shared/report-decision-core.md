# Report Decision Core (shared renderer spec)

The `decision-summary` / `decision-basis` / `exec-costs` / `what-if-scenarios` /
`next-steps` sections below are the **decision core** — the single source of
truth for verdict, cost, and next-step rendering. Two consumers load this
file; the content rules are identical in both:

| Mode         | Loaded by                                      | Output                                                                                      |
| ------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **decision** | `estimate-assemble.md` Decision gate, choice A | Standalone `decision-report.html` + `DECISION.md` — decision core only, CTA footer          |
| **full**     | `generate-report.md` Step 2                    | `migration-report.html` in full — the same sections, unchanged, no separate full-mode rules |

Heroku's report was already thin by design (`generate-report.md`'s own
framing: "decision + costs + optional what-if scenarios... not a full
GCP/Vercel assessment clone"). Unlike GCP's decision/full split, **Heroku has
no appendices to omit in decision mode** — the full-mode report already is the
decision core. This file exists so the Decision gate does not have to
duplicate `generate-report.md`'s section rules, and so a future full-mode
addition (e.g. an appendix) has one place to declare a decision-mode override,
matching GCP's pattern.

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

## Decision-mode specifics

- **HTML shell:** same inline-CSS `<head>` as the full report
  (`generate-report.md` Step 2 "Minimal CSS" + skeleton), title "Heroku to AWS
  Migration Assessment — Decision Report". Body contains `<nav class="toc">`
  then the sections below, in the same order `generate-report.md`'s skeleton
  uses: `decision-summary` → `decision-basis` (when present) → `exec-costs` →
  `what-if-scenarios` (when present) → `decision-cta` (new, decision-mode
  only, replaces `next-steps`).
- **Required section IDs in decision mode:** `decision-summary`, `exec-costs`
  (+ conditional `decision-basis`, `what-if-scenarios` per their triggers in
  `generate-report.md`).
- **Section content:** render `decision-summary`, `decision-basis`, and
  `exec-costs` / `what-if-scenarios` using the **exact same rules** as
  `generate-report.md` Step 2 — do not restate them here; that file is the
  single source of truth for content rules in both modes.
- **`decision-cta` (required, replaces `next-steps` in decision mode):**
  `<section id="decision-cta">` — "**Ready to execute?** Say \"generate the
  Terraform and migration scripts\" and I'll produce the full execution pack
  (Terraform, migration scripts, MIGRATION_GUIDE.md) from this same analysis."
  Plus one line: "This decision report was generated without execution
  artifacts; the full migration report replaces it if you proceed."
- **`DECISION.md` (required twin):** same content as the HTML, as plain
  Markdown (Slack/GitHub-friendly): verdict headline, cost line/table,
  timeline band, `would_flip_if[]` when present, the CTA line. No HTML tags.
- **Validation:** run
  `python3 "<SKILL_BASE>/scripts/validate-heroku-migration-report.py" "$MIGRATION_DIR/decision-report.html" --mode decision --migration-dir "$MIGRATION_DIR"`
  (absolute paths — cwd must not be load-bearing; `--migration-dir` is required so the
  decision-mode pre-execution checks run) and fix failures before presenting.
- **Cost labeling, reader vocabulary:** unchanged from `generate-report.md` —
  every dollar figure is "estimated monthly"; no `*.json` filenames or
  `aws_*.` resource IDs in `decision-summary` / `exec-costs` /
  `what-if-scenarios`.

## Full-mode specifics

No overrides today — `generate-report.md` Step 2 already IS the decision
core; `migration-report.html`'s `next-steps` section (not `decision-cta`) is
the only structural difference from decision mode. If a future change adds
appendix-only content to the full report, declare its decision-mode override
here rather than in `generate-report.md`.
