# Generated Render-to-AWS pack

This fixture is the deterministic balanced-baseline output for the representative design.

## Artifacts

- `terraform/` — supported AWS infrastructure; no AI or unsupported Workflow resources.
- `MIGRATION_GUIDE.md` — prerequisites, migration, cutover, verification, rollback, and source retention.
- `scripts/promote-image.sh` — immutable ECR digest promotion.
- `scripts/migrate-postgres.sh` — dry-run-first PostgreSQL migration stages.
- `scripts/migrate-disk.sh` — dry-run-first EFS pre-copy/final-delta stages.
- `migration-report.html` — validated stakeholder report.
- `generation-warnings.json` — complete generation accounting and honest deferred surfaces.
- `validation-report.json` — independent validation evidence and authoritative completion status.

## Validate and apply

Bootstrap with `terraform init -backend=false -input=false`, run `terraform validate`, configure remote state, review variables, then plan. Terraform represents the balanced baseline; cost scenarios do not create separate stacks.

A `passed_degraded_offline` result is not provider validation. Before apply, rerun `terraform init -backend=false -input=false && terraform validate` from a network-connected shell and update the canonical validation report through the main-window protocol.
