---
_assemble: assemble-generation
_of_phase: generate
_reads:
  - artifacts-infra
  - artifacts-docs
  - artifacts-report
_produces:
  - migration-report.html
  - generation-warnings.json
  - validation-report.json
  - README.md
  - terraform/
  - scripts/
  - MIGRATION_GUIDE.md
---

# Assemble generation and validate

The worker performs file-only assembly and writes `generation-warnings.json`; the main window is the sole author of `validation-report.json` and the sole owner of completion.

## Worker accounting gate

Validate the warnings ledger against `schema-generation-warnings.json`. Every `aws-design.json` mapping appears in exactly one classification array, with no duplicate or unknown ID. A generated row names existing target files; consumed topology names the concrete files into which it was folded; deferred and unsupported rows carry an explicit reason and no fabricated target file. Recompute all counts and byte-sort source IDs. Scan all outputs for captured secret values, credential patterns, `{{VARIABLE}}`, unexpanded tokens, and prohibited AI artifacts. Any mismatch is a gate failure.

## Main-window validation protocol

Run these independent checks after all worker writes, recording the exact command, terminal status, and bounded evidence for each:

1. **terraform_fmt** — `terraform fmt -check -recursive "$MIGRATION_DIR/terraform"`. Failure blocks completion.
2. **terraform_init** — from the Terraform directory run `terraform init -backend=false -input=false`. Only stderr that identifies provider-registry DNS/connectivity failure may become `provider_registry_unavailable`. Authentication, syntax, backend, checksum, configuration, or empty/unknown failures remain failures.
3. **terraform_validate** — run `terraform validate` after successful init. If init has the narrowly classified registry outage, record `provider_registry_unavailable`; otherwise any failure blocks completion.
4. **policy** — regardless of init outcome, run `python3 "$PLUGIN_ROOT/skills/tf-best-practices/scripts/validate-terraform-policy.py" "$MIGRATION_DIR/terraform" --json "$MIGRATION_DIR/.policy-verdict.tmp.json"`. Merge the verdict, require `POLICY_OK`, then remove the sidecar. `POLICY_FAIL` or not-run blocks completion.
5. **secret_scan** — run the repository-approved no-git secret scanner across the generated pack. Any finding or scanner failure blocks completion.
6. **schemas** — validate `generation-warnings.json` and the prospective validation report against their skill-local schemas and re-run cross-artifact accounting. Any error blocks completion.
7. **report** — run `validate-render-migration-report.py` with its absolute-path ABI. Only `REPORT_OK` passes. On failure rename the HTML to `migration-report.incomplete.html` and block completion.

Write one atomic `validation-report.json` conforming to `schema-validation-report.json`. `status: passed` requires every stage passed. `status: passed_degraded_offline` requires only `terraform_init` and optionally `terraform_validate` to be `provider_registry_unavailable`; fmt, policy, secret, schema, and report checks remain passed. No `not_run`, skipped, user-continue, warning-only, or policy override status can complete Generate.

After writing, re-read and schema-validate the report, confirm the recorded commands correspond to the final file digests, then evaluate Generate postconditions. The main window emits `HANDOFF_OK` and updates phase state only on success.
