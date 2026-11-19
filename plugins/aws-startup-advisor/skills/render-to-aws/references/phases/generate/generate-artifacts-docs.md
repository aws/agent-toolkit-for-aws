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

1. **Overview and scope** — selected AWS architecture, generated versus consumed topology, exact deferred AI state, generated Workflow semantics (the tested set in `generate-infra-workflow.md`), and any Workflow left `conditional_workflow_generation_unsupported`.
2. **Prerequisites** — AWS credentials/region, Terraform version, backend bootstrap, Render source-retention window, certificate/DNS control, target secret population, source PostgreSQL privileges, network paths, maintenance window, and named owners. For a public HTTPS web service with external DNS, explain how to request the certificate in ACM, create every ACM DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and then supply the validated certificate ARN. When Clarify records that a source Render service must call AWS during coexistence or cutover, include a temporary-access subsection that recommends [Render-managed OIDC](https://render.com/docs/oidc) and a least-privilege AWS role instead of long-lived AWS access keys. Scope the trust relationship to the confirmed Render workspace and service subject supported by Render, tell the user to set `AWS_ROLE_ARN` and redeploy, and explicitly say that Render sets `AWS_WEB_IDENTITY_TOKEN_FILE` and the user must not set it manually. Render-managed OIDC requires a Pro workspace or higher. Omit this subsection when no Render-hosted workload needs AWS access. State the `identity.human_sign_in` source (IAM Identity Center directory or the named external provider) and the `identity.deploy_principal` role, and list every store with `data.regulated_data` true with its KMS and backup constraint.
3. **Build and deployment migration** — name the `delivery.ci_owner` runner, build once, push one immutable ECR digest, promote without rebuilding, retain serving-deploy identity, record auto-deploy state, and verify rollback lineage.
4. **PostgreSQL migration** — choose the method from `database.downtime_tolerance` and `database.replication_privilege`; preflight version/extensions/privileges, schema/full-load, AWS DMS CDC when selected, lag monitoring, writer quiescence, final delta, integrity checks, connection switch, and source retention. Do not claim DMS works until privileges and Render connectivity are proven.
5. **Key Value migration** — persistence/eviction compatibility, key-count/sample validation without capturing values, only the `key_value.migration_strategy` method (dual-write, snapshot restore, or empty start), endpoint switch, and rollback limits.
6. **Persistent-disk migration** — `/var/data` capacity and file inventory, EFS access point, permissions/ownership/locking checks, pre-copy, delta copy, writer quiescence, final integrity manifest, remount, and source retention. Never describe EBS as a Fargate disk.
7. **Deployment and service cutover** — follow the `cutover.downtime_window` pattern (`short_window` is one switch with traffic stopped; `staged_shift` is a weighted shift), limited by `domain.ttl_control` as the Clarify cutover precedence list defines; private-service discovery, worker drain/restart semantics, cron disable/enable ordering, health checks, and capacity acceptance. For each generated Workflow add a Workflow cutover subsection: upload the owner-built Lambda package and set its package, runtime, handler, and memory variables; replace each Render run trigger with `states:StartExecution` on the state machine; for each ECS Fargate task, say that the state input reaches the container only as the `STEP_INPUT` environment variable (a JSON string, at most 8192 characters with the rest of the `RunTask` overrides), so an existing Render task image run unchanged would start without its arguments and nothing would fail: the owner must make the container read `STEP_INPUT`; name the owner who grants the callback sender `states:SendTaskSuccess`, `states:SendTaskFailure`, and `states:SendTaskHeartbeat` (Terraform does not grant them); run executions in parallel with Render only when they are side-effect-free verification executions, and otherwise follow `cutover.downtime_window` (with `short_window` stop Render runs before enabling the AWS callers); and state that Render run history is not migrated. State for every Fargate mapping whether it is ECS Express Mode or standard and its `ecs_mode_reason`, and for each `ecs_express_not_selected_rolling_release` warning that the default canary release became a rolling update.
8. **DNS and traffic cutover** — lower TTL in advance when `domain.ttl_control` allows it and validate ACM. Then follow the section 7 pattern: for `short_window`, switch once with traffic stopped; for `staged_shift` with TTL control, stage traffic, observe, then move fully; for `staged_shift` with `cannot_lower`, fall back to one switch. State the hard-switch exposure window as the current TTL whenever TTL was not lowered. External DNS remains external.
9. **Verification** — concrete checks for public/static/private endpoints, database read/write, cache semantics, disk ownership/locking, worker drain/idempotency, cron overlap/retry, Build Source digest identity, and, for each generated Workflow, executions that exercise the declared retry and backoff, per-attempt timeout, task-token callback, and compensation path (when declared), plus the 90-day Step Functions history window, log retention (`observability.log_retention`, default 30 days), and the three alarms. Name any Workflow behavior outside the tested set as manually validated.
10. **Rollback and source retention** — measurable rollback triggers, fence target writers before restoring Render writers, restore DNS/traffic, preserve copied data, and retain Render for the `cutover.source_retention` period and until sign-off. A database rollback must not permit two primaries.
11. **Known limitations** — cost floors, `deferred_shared_ai_engine` (the profile conforms to the shared #415 contract; execution resumes once `bedrock-migration-assessment` consumes it, which is future work), each `conditional_workflow_generation_unsupported` reason copied from the ledger warning `detail`, with the statement that Render execution parity is not claimed, the `delivery.preview_policy` limitation when `per_pr_stack` is not generated, and the `cost.budget_guardrail` limit with a recommended AWS Budgets alert when one was stated. For each generated Workflow with an ECS task, add that the container returns no data to the Workflow (`runTask.sync` returns the task description, so `ResultPath` is `null`): any result a later state or a Map fan-in relied on must be written somewhere the owner chooses, such as S3 or DynamoDB, and the next state reads it from there.

## Scripts

Emit deterministic, non-secret-bearing helper scripts:

- `scripts/promote-image.sh` requires an ECR repository URL, immutable source digest, and target environment. It defaults to dry-run; explicit `--execute` verifies the repository enforces immutable tags, resolves the exact digest, and creates the environment promotion tag from that manifest without rebuilding. It never accepts `latest` or a mutable source reference.
- `scripts/migrate-postgres.sh` defaults to dry-run and prints the reviewed full-load/CDC stages; execution requires explicit `--execute`, environment-provided endpoints, and a confirmed quiescence gate.
- `scripts/migrate-disk.sh` defaults to dry-run and requires source/target roots plus a confirmed quiescence gate for the final delta; it records checksums and never deletes source data.

Use `set -euo pipefail`, quote all expansions, reject unknown arguments, and never print credentials. Scripts do not invoke Render mutation APIs.

## `README.md`

List every generated file, state that Terraform implements the balanced baseline, show offline-safe initialization, link the migration guide, identify manual inputs, and explain that `validation-report.json` is authoritative. State that `passed_degraded_offline` requires a later network-connected `terraform init -backend=false && terraform validate` before apply.
