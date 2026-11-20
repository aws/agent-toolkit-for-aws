# Render-to-AWS Migration Guide

## Overview and scope

This execution pack implements the supported infrastructure mappings in `aws-design.json`. Project and environment rows are consumed as topology. AI remains `deferred_shared_ai_engine`. Workflow and task Terraform is generated in `terraform/workflow.tf` for the semantics covered by the generation contract tests (task order, per-task retry, timeout, task-token callback, retained logging); a Workflow outside that set is reported as `conditional_workflow_generation_unsupported` and emits no Terraform. Render execution parity is not claimed.

## Prerequisites

- Configure AWS credentials and confirm `us-east-1`.
- Install Terraform 1.5 or newer and bootstrap remote state before normal initialization.
- Populate target secrets without copying values into Terraform or this guide.
- Confirm PostgreSQL version, extensions, replication privileges, network paths, and maintenance window.
- Confirm external DNS ownership. Request the public web certificate in ACM, create every DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and supply its ARN as `issued_certificate_arn` before applying this stack.
- Define source-retention and rollback owners before any writer cutover.
- Human sign-in uses a new IAM Identity Center directory, so re-invite the team. The CI role assumed through OIDC pushes to ECR without long-lived keys.
- No store is marked as holding regulated data, so no customer-managed KMS key or in-Region-only backup constraint is required.
- CloudWatch Logs retention is 30 days.
- This fixture assumes the source web service must call AWS during coexistence. Use [Render-managed OIDC](https://render.com/docs/oidc) with a least-privilege AWS role scoped to the confirmed Render workspace and service subject instead of long-lived AWS access keys. Set `AWS_ROLE_ARN`, redeploy the service, and let Render set `AWS_WEB_IDENTITY_TOKEN_FILE`; do not set that variable manually. Render-managed OIDC requires a Pro workspace or higher.

## Build and deployment migration

GitHub Actions is the promotion runner. Run `scripts/promote-image.sh ECR_REPOSITORY_URL SHA256_DIGEST TARGET_ENVIRONMENT` to preview promotion, then repeat with `--execute`. The helper verifies an immutable ECR repository, resolves the exact source digest, and creates the environment promotion tag from that manifest without rebuilding. Deploy the emitted `repository@sha256:...` reference, not the environment tag. Record the serving deploy separately from the newest deploy, preserve auto-deploy state, and capture rollback lineage.

## PostgreSQL migration

1. Verify version, extensions, connection pooling, DMS/logical-replication privileges, and connectivity.
2. Rehearse schema and full load in an isolated target.
3. Start AWS DMS CDC only after the privilege preflight passes; monitor lag.
4. Establish writer quiescence, apply the final delta, and compare row counts and checksums.
5. Switch the application connection and retain the Render source until sign-off.

## Key Value migration

Verify supported commands, persistence, eviction, pub/sub, streams, and Lua behavior. Use an empty start: no data is copied, so queued and session data is lost at cutover. Validate key-count/sample behavior without recording values, then switch the endpoint. Document that rollback cannot merge divergent writes.

## Persistent-disk migration

Create the encrypted EFS access point for `/var/data`. Check capacity, ownership, permissions, locking, file count, and performance. Run `scripts/migrate-disk.sh` for a pre-copy, quiesce writers for the final delta, compare the checksum manifest, remount, and retain the Render disk. Do not substitute EBS for Fargate.

## Deployment and service cutover

Verify private service discovery before public traffic. Drain the worker and preserve graceful shutdown/idempotency. Disable the Render cron before enabling EventBridge Scheduler, preventing overlap. Restore desired counts and pass health checks before proceeding.

Fargate deployment mode per service: `rr-web` is standard with a hand-built ALB (`custom_domain_alb`) and its default canary release becomes a rolling update; `rr-private` is standard (`private_discovery`); `rr-worker` is standard (`no_http_listener`); `rr-cron` is standard (`no_http_listener`). No service uses ECS Express Mode.

### Workflow cutover

Build and upload the reviewed Lambda package, then set the `rr_workflow_task_package_path`, `rr_workflow_task_runtime`, `rr_workflow_task_handler`, and `rr_workflow_task_memory_mb` variables; this pack contains no function source. Render starts runs through its API or SDK, so replace each caller with `states:StartExecution` on the generated state machine. The callback sender needs `states:SendTaskSuccess`, `states:SendTaskFailure`, and `states:SendTaskHeartbeat`, which Terraform does not grant because those actions cannot be scoped to one state machine. Run executions in parallel with Render only when they are side-effect-free verification executions. Otherwise follow the `short_window` cutover: stop Render runs before enabling the AWS callers. Do not migrate Render run history.

## DNS and traffic cutover

Lower external DNS TTL 24 hours in advance. Before applying the listener, request the certificate in ACM, create every ACM DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and provide the issued ARN to Terraform. Freeze releases, quiesce data writers, complete final deltas, switch traffic once inside the planned maintenance window with traffic stopped, then observe. The short window selects a single switch, so traffic is not shifted in stages. DNS remains external; Terraform must not fabricate Route 53 ownership.

## Verification

- Check static, public, and private endpoints.
- Round-trip a database record and reconcile counts/checksums.
- Verify cache eviction and persistence behavior.
- Verify EFS ownership, permissions, locking, and integrity.
- Verify worker drain/retry/idempotency and cron overlap policy.
- Verify the running image digest is the promoted ECR digest.
- Run Workflow executions and confirm the console shows the declared retries with their backoff, the per-attempt timeout, and the task-token callback completing before `callback_timeout_seconds`. Execution history stays in Step Functions for 90 days; execution logs follow `workflow_log_retention_days`. Confirm the three Workflow alarms exist and `workflow_alarm_actions` points at an owned notification target.

## Rollback and source retention

Trigger rollback on error rate, integrity mismatch, unacceptable lag, or failed behavior checks. Fence target writers before re-enabling Render writers; never permit two database primaries. Restore traffic and external DNS, retain target evidence, and keep Render resources for 14 days after cutover and until sign-off.

## Known limitations

Both estimate scenarios price every line, including EFS at the 5 GB Blueprint disk size. AI execution is `deferred_shared_ai_engine`. Workflow generation covers only the tested semantics; any other Workflow is `conditional_workflow_generation_unsupported` and emits no Terraform. Render run, retry-timing, and platform-error behavior are not claimed to match, and Render run history is not migrated.
