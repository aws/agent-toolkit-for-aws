---
_fragment: artifacts-report
_of_phase: generate
_contributes:
  - migration-report.html
  - generation-warnings.json
---

# Generate migration report

Load `references/shared/report-decision-core.md`; it is the normative report contract. Read the current design, estimate, preferences, inventory, and generated-file ledger from disk. Do not use recalled values.

Render exact selected targets, all four required cost anchors, complete accounting, assumptions, risks, migration procedures, validation status, and cutover/rollback guidance. `exec-targets` has one row per design mapping and carries the exact source-resource ID and selected AWS service in machine-checkable attributes. `appendix-accounting` uses the final ledger's `accounted_count`.

Write `generation-warnings.json` against `references/shared/schema-generation-warnings.json`. Every design mapping occurs exactly once in `generated`, `consumed_topology`, `deferred`, or `unsupported`; counts and canonical byte-sorted IDs reconcile. Emit:

- `deferred_shared_ai_engine` whenever the design AI track has that exact status. The warning states that `ai-workload-profile.json` conforms to the shared #415 contract and that AI execution resumes once `bedrock-migration-assessment` consumes it (future; not implemented). No AI target, cost, model, adapter, or Terraform may appear.
- `conditional_workflow_generation_unsupported` for each Workflow or task whose automatic artifacts lack validated semantic coverage. The selected design still appears in the report, while the report plainly states that its Terraform was not generated and lists the manual validation needed.
- `unpriced_cost_floor` when either estimate scenario has unpriced lines.

The report must not contain captured secrets, environment values, email/account/workspace/project/environment IDs, repository URLs, or local paths. It is a draft for review, not a deployment-success claim.

The worker writes the candidate as `migration-report.html` but does not validate it. In the main window, run the skill-local validator with absolute paths:

```bash
uv run --project "$SKILL_BASE/scripts" --frozen python \
  "$SKILL_BASE/scripts/validate-render-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" --migration-dir "$MIGRATION_DIR"
```

`REPORT_OK` with exit 0 is the only pass. On `REPORT_FAIL`/1, atomically rename the candidate to `migration-report.incomplete.html`, preserve all diagnostics, and block completion. Exit 2 or inability to run the validator also blocks completion; there is no validation skip.
