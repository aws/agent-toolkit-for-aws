---
_fragment: artifacts-docs
_of_phase: generate
_contributes:
  - README.md
  - MIGRATION_GUIDE.md
  - scripts/
---

# Generate documentation and migration scripts

Emit executable guidance for the selected design; infrastructure alone is not a migration pack.

## `MIGRATION_GUIDE.md`

Write these sections in order:

1. **Overview and scope** — selected AWS architecture, generated versus consumed topology, exact deferred AI state, and conditionally unsupported Workflow generation.
2. **Prerequisites** — AWS credentials/region, Terraform version, backend bootstrap, Render source-retention window, certificate/DNS control, target secret population, source PostgreSQL privileges, network paths, maintenance window, and named owners. For a public HTTPS web service with external DNS, explain how to request the certificate in ACM, create every ACM DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and then supply the validated certificate ARN.
3. **Build and deployment migration** — build once, push one immutable ECR digest, promote without rebuilding, retain serving-deploy identity, record auto-deploy state, and verify rollback lineage.
4. **PostgreSQL migration** — preflight version/extensions/privileges, schema/full-load, AWS DMS CDC when selected, lag monitoring, writer quiescence, final delta, integrity checks, connection switch, and source retention. Do not claim DMS works until privileges and Render connectivity are proven.
5. **Key Value migration** — persistence/eviction compatibility, key-count/sample validation without capturing values, application dual-write or downtime choice, endpoint switch, and rollback limits.
6. **Persistent-disk migration** — `/var/data` capacity and file inventory, EFS access point, permissions/ownership/locking checks, pre-copy, delta copy, writer quiescence, final integrity manifest, remount, and source retention. Never describe EBS as a Fargate disk.
7. **Deployment and service cutover** — private-service discovery, worker drain/restart semantics, cron disable/enable ordering, health checks, and capacity acceptance.
8. **DNS and traffic cutover** — lower TTL in advance, validate ACM, stage traffic, observe, then move fully. External DNS remains external.
9. **Verification** — concrete checks for public/static/private endpoints, database read/write, cache semantics, disk ownership/locking, worker drain/idempotency, cron overlap/retry, Build Source digest identity, and Workflow behavior that remains manually validated.
10. **Rollback and source retention** — measurable rollback triggers, fence target writers before restoring Render writers, restore DNS/traffic, preserve copied data, and retain Render until sign-off. A database rollback must not permit two primaries.
11. **Known limitations** — cost floors, `deferred_shared_ai_engine` (the profile conforms to the shared #415 contract; execution resumes once `bedrock-migration-assessment` consumes it, which is future work), and each `conditional_workflow_generation_unsupported` reason.

## Scripts

Emit deterministic, non-secret-bearing helper scripts:

- `scripts/promote-image.sh` requires an ECR repository URL, immutable source digest, and target environment. It defaults to dry-run; explicit `--execute` verifies the repository enforces immutable tags, resolves the exact digest, and creates the environment promotion tag from that manifest without rebuilding. It never accepts `latest` or a mutable source reference.
- `scripts/migrate-postgres.sh` defaults to dry-run and prints the reviewed full-load/CDC stages; execution requires explicit `--execute`, environment-provided endpoints, and a confirmed quiescence gate.
- `scripts/migrate-disk.sh` defaults to dry-run and requires source/target roots plus a confirmed quiescence gate for the final delta; it records checksums and never deletes source data.

Use `set -euo pipefail`, quote all expansions, reject unknown arguments, and never print credentials. Scripts do not invoke Render mutation APIs.

## `README.md`

List every generated file, state that Terraform implements the balanced baseline, show offline-safe initialization, link the migration guide, identify manual inputs, and explain that `validation-report.json` is authoritative. State that `passed_degraded_offline` requires a later network-connected `terraform init -backend=false && terraform validate` before apply.
