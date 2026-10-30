# Render-to-AWS Migration Guide

## Overview and scope

This execution pack implements the supported infrastructure mappings in `aws-design.json`. Project and environment rows are consumed as topology. AI remains `deferred_shared_ai_engine`; Workflow and task Terraform remain `conditional_workflow_generation_unsupported` until their callback, compensation, retry, and state-retention semantics have dedicated tests.

## Prerequisites

- Configure AWS credentials and confirm `us-east-1`.
- Install Terraform 1.5 or newer and bootstrap remote state before normal initialization.
- Populate target secrets without copying values into Terraform or this guide.
- Confirm PostgreSQL version, extensions, replication privileges, network paths, and maintenance window.
- Confirm external DNS ownership. Request the public web certificate in ACM, create every DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and supply its ARN as `issued_certificate_arn` before applying this stack.
- Define source-retention and rollback owners before any writer cutover.

## Build and deployment migration

Run `scripts/promote-image.sh ECR_REPOSITORY_URL SHA256_DIGEST TARGET_ENVIRONMENT` to preview promotion, then repeat with `--execute`. The helper verifies an immutable ECR repository, resolves the exact source digest, and creates the environment promotion tag from that manifest without rebuilding. Deploy the emitted `repository@sha256:...` reference, not the environment tag. Record the serving deploy separately from the newest deploy, preserve auto-deploy state, and capture rollback lineage.

## PostgreSQL migration

1. Verify version, extensions, connection pooling, DMS/logical-replication privileges, and connectivity.
2. Rehearse schema and full load in an isolated target.
3. Start AWS DMS CDC only after the privilege preflight passes; monitor lag.
4. Establish writer quiescence, apply the final delta, and compare row counts and checksums.
5. Switch the application connection and retain the Render source until sign-off.

## Key Value migration

Verify supported commands, persistence, eviction, pub/sub, streams, and Lua behavior. Use a rehearsed downtime or dual-write transition, validate key-count/sample behavior without recording values, then switch the endpoint. Document that rollback cannot merge divergent writes.

## Persistent-disk migration

Create the encrypted EFS access point for `/var/data`. Check capacity, ownership, permissions, locking, file count, and performance. Run `scripts/migrate-disk.sh` for a pre-copy, quiesce writers for the final delta, compare the checksum manifest, remount, and retain the Render disk. Do not substitute EBS for Fargate.

## Deployment and service cutover

Verify private service discovery before public traffic. Drain the worker and preserve graceful shutdown/idempotency. Disable the Render cron before enabling EventBridge Scheduler, preventing overlap. Restore desired counts and pass health checks before proceeding.

## DNS and traffic cutover

Lower external DNS TTL in advance. Before applying the listener, request the certificate in ACM, create every ACM DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and provide the issued ARN to Terraform. Freeze releases, quiesce data writers, complete final deltas, shift a small traffic slice, observe, then move fully. DNS remains external; Terraform must not fabricate Route 53 ownership.

## Verification

- Check static, public, and private endpoints.
- Round-trip a database record and reconcile counts/checksums.
- Verify cache eviction and persistence behavior.
- Verify EFS ownership, permissions, locking, and integrity.
- Verify worker drain/retry/idempotency and cron overlap policy.
- Verify the running image digest is the promoted ECR digest.
- Manually test Workflow callbacks, retries, compensation, and retained state.

## Rollback and source retention

Trigger rollback on error rate, integrity mismatch, unacceptable lag, or failed behavior checks. Fence target writers before re-enabling Render writers; never permit two database primaries. Restore traffic and external DNS, retain target evidence, and keep Render resources through the agreed source-retention window.

## Known limitations

Both estimate scenarios are floors because EFS is unpriced. AI execution is `deferred_shared_ai_engine`. Workflow generation is `conditional_workflow_generation_unsupported`; the report preserves the selected targets but no unvalidated Workflow artifacts are emitted.
