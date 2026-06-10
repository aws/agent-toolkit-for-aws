# Application Lifecycle Operations

## Overview

Day-2 operations: start, stop, deploy code updates, rollback, manage snapshots, delete. Covers MSF-specific behaviors and guardrails not obvious from the API. For initial creation and IaC patterns, see [iac-and-deployment.md](iac-and-deployment.md).

## Version ID Discipline

Every `update-application`, `add-application-vpc-configuration`, and `add-application-cloud-watch-logging-option` requires `--current-application-version-id` (or `--conditional-token`). The version ID **increments after every change**. Always fetch it immediately before each update — a stale ID returns `ConcurrentModificationException` ("Exception thrown as a result of concurrent modifications to an application"). For better concurrency support in scripted/CI workflows, the API recommends `ConditionalToken` over `CurrentApplicationVersionId` — also fetched from `describe-application`.

```bash
VERSION=$(aws kinesisanalyticsv2 describe-application --application-name "$APP" \
  --query 'ApplicationDetail.ApplicationVersionId' --output text)
```

## Status Transitions and Polling

| From | To (terminal) | Trigger |
|------|---------------|---------|
| READY | STARTING → RUNNING | `start-application` |
| RUNNING | STOPPING → READY | `stop-application` |
| RUNNING | UPDATING → RUNNING | `update-application` while running |
| RUNNING | AUTOSCALING → RUNNING | autoscaling event |
| READY | UPDATING → READY | `update-application` while stopped |
| any | FORCE_STOPPING → READY | `stop-application --force` |
| RUNNING / UPDATING / AUTOSCALING | ROLLING_BACK → RUNNING | `rollback-application`, or system auto-rollback on a failed update / scaling / version upgrade |
| ROLLING_BACK | → READY or ROLLED_BACK | rollback itself failed (app moves to READY for manual remediation), or rollback completed against an app that was not running (terminal `ROLLED_BACK`) |
| READY | DELETING → *(gone)* | `delete-application` — app is removed; `describe-application` returns `ResourceNotFoundException` |
| any | MAINTENANCE → previous status | service maintenance window (transient, no action required) |

Most CLI calls return immediately. After any mutation, **poll until terminal state** before issuing the next command. The exact terminal state depends on the operation — `delete-application` has no terminal `ApplicationStatus` because the app is gone, so detect the `ResourceNotFoundException` instead of breaking on a status:

```bash
# Generic poll for start/stop/update/rollback (terminal = READY or RUNNING)
while true; do
  STATUS=$(aws kinesisanalyticsv2 describe-application --application-name "$APP" \
    --query 'ApplicationDetail.ApplicationStatus' --output text)
  case "$STATUS" in
    READY|RUNNING|ROLLED_BACK) break ;;
    *) sleep 10 ;;
  esac
done

# Poll for delete-application (terminal = app no longer exists)
while aws kinesisanalyticsv2 describe-application --application-name "$APP" \
        --query 'ApplicationDetail.ApplicationStatus' --output text 2>/dev/null; do
  sleep 10
done
```

If a transition has not completed after 10 minutes, the app is stuck — diagnose via [first-fault-isolation.md](first-fault-isolation.md) rather than retrying.

## Stop

`stop-application` without `--force` only succeeds from RUNNING. With `--force`, it stops from any state but skips a graceful savepoint, so any unflushed state since the last checkpoint is lost. Use `--force` only when the app is wedged in a transitional state.

```bash
aws kinesisanalyticsv2 stop-application --application-name "$APP" --force
```

## Start with Restore Type

`ApplicationRestoreType` controls what state the application starts from:

| Restore Type | Behavior | When to Use |
|-------------|----------|-------------|
| `RESTORE_FROM_LATEST_SNAPSHOT` (default) | Most recent successful snapshot | Normal restart |
| `RESTORE_FROM_CUSTOM_SNAPSHOT` | Specific named snapshot | Rollback to known-good state |
| `SKIP_RESTORE_FROM_SNAPSHOT` | No state — start fresh | Schema change, recovery blocker, intentional reprocess (⚠️ data loss / reprocessing) |

`AllowNonRestoredState=true` is required when the operator topology has changed (added/removed/renamed operators with `uid()`). Without it, restore fails with state-incompatibility errors.

```bash
aws kinesisanalyticsv2 start-application --application-name "$APP" \
  --run-configuration '{
    "FlinkRunConfiguration": {"AllowNonRestoredState": true},
    "ApplicationRestoreConfiguration": {"ApplicationRestoreType": "RESTORE_FROM_LATEST_SNAPSHOT"}
  }'
```

## Deploy New Code

MSF does not pull new code from S3 automatically. After uploading the new artifact, call `update-application` to point the app at the new S3 key, then **restart** to pick it up. Without a restart the app keeps running the old code.

A code update from a RUNNING state triggers a restart automatically (UPDATING → RUNNING with 10–30s downtime, varies with state size). A code update from READY does not — start the app afterward.

**Always state both behaviors when answering "how do I deploy new code":** the user's app may be RUNNING today, but the next deploy might be from READY (after a stop, or for a fresh deploy). The `update-application` → auto-restart behavior is conditional on the source state, not universal:

| Starting state | `update-application` triggers restart? | Required follow-up |
|---|---|---|
| RUNNING | Yes (UPDATING → RUNNING) | None — verify new code is live |
| READY (stopped) | No (UPDATING → READY) | Call `start-application` to pick up the new code |

```bash
aws s3 cp my-app.jar s3://$BUCKET/$KEY
aws kinesisanalyticsv2 update-application --application-name "$APP" \
  --current-application-version-id "$VERSION" \
  --application-configuration-update '{
    "ApplicationCodeConfigurationUpdate": {
      "CodeContentTypeUpdate": "ZIPFILE",
      "CodeContentUpdate": {"S3ContentLocationUpdate": {
        "BucketARNUpdate": "arn:aws:s3:::'$BUCKET'",
        "FileKeyUpdate": "'$KEY'"
      }}
    }
  }'
```

### Safe Deploy Procedure (Required Companion to Any Deploy Answer)

A safe deploy is incomplete without its rollback path. **Whenever a user asks "how do I deploy code updates safely" or any related deploy question, you MUST include both the deploy steps and the rollback options in the same answer** — they are inseparable.

**Deploy steps:**

1. (Optional but recommended) Take a snapshot from RUNNING and poll until READY. This is your fallback rollback point if both the automatic system rollback and `RollbackApplication` paths fail.
2. (One-time, recommended for production) Opt in to **automatic system rollback** by setting `ApplicationSystemRollbackConfigurationUpdate.RollbackEnabledUpdate=true` on the application. With this enabled, MSF auto-reverts failed updates, scaling actions, and version upgrades to the previous running version with minimal downtime. It is **not** on by default — existing applications must opt in.
3. Upload the new JAR to a versioned S3 key (do NOT overwrite — pointer change must be unambiguous).
4. Fetch the current `ApplicationVersionId` immediately before the update (stale ID returns `ConcurrentModificationException`).
5. Call `update-application` pointing at the new key. From RUNNING this auto-restarts; from READY call `start-application` after.
6. For state-incompatible code changes (operator topology change, removed/renamed `uid()`), set `FlinkRunConfiguration.AllowNonRestoredState=true` on restart.
7. Verify the deploy: `describe-application` shows the new `FileKey` and incremented `ApplicationVersionId`; CloudWatch shows a fresh `uptime` reset.

**Rollback options (always state these alongside the deploy steps), in priority order:**

1. **Automatic system rollback** (if opted in): MSF detects update/scaling failures (code bugs, permission issues, snapshot incompatibility on version upgrade, parallelism over `maxParallelism`, bad VPC subnets, etc.) and automatically calls `RollbackApplication` to restore the previous version with its state. If auto-rollback succeeds, the app keeps processing with minimal downtime. If auto-rollback also fails, the app transitions to READY for manual remediation. You only see this if you opted in via `ApplicationSystemRollbackConfigurationUpdate`.
2. **Manual `RollbackApplication`** (always available, no opt-in required): if the deploy succeeded but you observe downstream issues (processing errors, output regression, performance regression), call `RollbackApplication` to revert to the previous running version with its state. Monitor the operation with `DescribeApplicationOperation`. Use this when the application is stuck in a transient state, or when a deploy that completed cleanly turns out to be bad in production.
3. **Last-resort manual restore from a custom snapshot**: only if both `RollbackApplication` and the auto-rollback path failed, or if the bad code change was made many versions ago and is no longer the "previous running version." Stop with `--force`, poll until READY, `update-application` back to the previous S3 key, then start with `ApplicationRestoreType=RESTORE_FROM_CUSTOM_SNAPSHOT` pointing at the snapshot you took in step 1 above. This works only if you actually took the pre-deploy snapshot.

**Diagnose before rolling back:** the diagnostic procedure described under [Diagnosing a Failed or Unexpected Operation](#diagnosing-a-failed-or-unexpected-operation) (call `ListApplicationOperations` then `DescribeApplicationOperation` to read `statusDescription`) is the canonical first step for any failed deploy, rollback, or unexpected status transition (including `UPDATING` → `READY` when the user did not intend a no-op). Common error categories: customer code bugs (use rollback), permission issues (fix the role and retry), and MSF service issues (check AWS Health Dashboard).

## Rollback

### Diagnosing a Failed or Unexpected Operation

When a deploy goes wrong, or when an `UpdateApplication` call transitions to `UPDATING` and back without producing the expected new state, **always start by collecting diagnostic context before initiating any recovery action or assuming success**. Do not assume the operation succeeded just because the application returned to `READY` or `RUNNING` — `UpdateApplication` can transition through `UPDATING` and back even when the underlying operation failed, the new version was rolled back, or the change was rejected. Run the diagnostic flow first:

1. `ListApplicationOperations` — chronological history of all `UpdateApplication`, `Maintenance`, `RollbackApplication`, and other operations. Find the operation ID for the unexpected transition.
2. `DescribeApplicationOperation` on that operation ID — read `OperationStatus` (do not trust the application status alone) and especially `statusDescription`, which contains the actual failure reason. This is the single most informative diagnostic field MSF surfaces.
3. CloudWatch Logs for the application — read runtime errors that appear after the operation summary. Operation-level failures (IAM, parallelism limits, VPC) show up in `statusDescription`; runtime errors after a successful operation (e.g., the new code crashes on startup) show up in CloudWatch Logs.

Common failure categories surfaced this way: insufficient permissions, incompatible customer code, snapshot incompatibility on a Flink version upgrade, parallelism above `maxParallelism`, VPC misconfiguration, and MSF service issues (check AWS Health Dashboard). Each often points directly at the fix and may make rollback unnecessary.

Only after `statusDescription` is read should you decide whether to retry the operation, roll back, or fix the underlying issue. Retrying or rolling back blindly hides the root cause and tends to repeat the failure.

### Rollback Paths

MSF has three rollback paths — choose the highest one available:

1. **Automatic system rollback** (opt-in via `ApplicationSystemRollbackConfigurationUpdate.RollbackEnabledUpdate=true`). Auto-reverts **failed** `UpdateApplication`, autoscaling, or version-upgrade operations to the previous running version. Triggers when the service detects code bugs, permission issues, snapshot incompatibility on Flink version upgrade, parallelism above `maxParallelism`, or VPC misconfiguration that fails Flink job startup. **Important: this only fires when the operation itself fails.** A deploy that completes successfully but produces wrong output downstream is *not* a failed operation from MSF's perspective — auto-rollback will not engage. Use the manual `RollbackApplication` API (path 2) for that case. If auto-rollback also fails, the app moves to READY.

2. **Manual `RollbackApplication` API** (always available, no opt-in). Reverts to the previous running version with its state. Use when:
   - The deploy succeeded but the new version has downstream issues you only see in production (auto-rollback does not cover this case).
   - The application is stuck in a transient state (e.g., long UPDATING).
   - Auto-rollback was not enabled.

   ```bash
   aws kinesisanalyticsv2 rollback-application --application-name "$APP" \
     --current-application-version-id "$VERSION"
   aws kinesisanalyticsv2 describe-application-operation \
     --application-name "$APP" --operation-id "$OPERATION_ID"
   ```

3. **Manual restore from a custom snapshot** (last resort). Use only when both 1 and 2 are unavailable or have failed — for example, when the bad code change is older than the previous running version that `RollbackApplication` would target, or when both rollback paths returned errors.
   1. `stop-application --force` and poll until READY.
   2. `update-application` to point at a known-good previous S3 key.
   3. `start-application` with `ApplicationRestoreType=RESTORE_FROM_CUSTOM_SNAPSHOT` and `SnapshotName=<pre-deploy snapshot>`.

   This requires a pre-deploy snapshot. Take one before any code update so this fallback is available.

**Operation visibility for any failed deploy or rollback:** use `ListApplicationOperations` (chronological history of all `UpdateApplication`, `Maintenance`, `RollbackApplication`, and other operations) and `DescribeApplicationOperation` for the per-operation failure reason. Common error categories: customer code bugs (use rollback), permission issues (fix the role and retry), and MSF service issues (check AWS Health Dashboard).

## Runtime Properties Update

Application code reads runtime properties via `KinesisAnalyticsRuntime.getApplicationProperties()`. Update them via `EnvironmentPropertyUpdates` — the application picks up the new values on next restart. They are organized by `PropertyGroupId`, which the application code uses to look up its property map.

```bash
aws kinesisanalyticsv2 update-application --application-name "$APP" \
  --current-application-version-id "$VERSION" \
  --application-configuration-update '{
    "EnvironmentPropertyUpdates": {"PropertyGroups": [{
      "PropertyGroupId": "FlinkApplicationProperties",
      "PropertyMap": {"input.stream": "new-stream"}
    }]}
  }'
```

## Snapshots

### Snapshot vs Checkpoint

| | Checkpoint | Snapshot |
|---|---|---|
| Trigger | Automatic, periodic | Manual or stop-with-snapshot |
| Purpose | Fault tolerance | Backup, rollback, restore-on-start |
| Storage | Included in 50 GB / KPU running storage | Billed at $0.023/GB-month (durable backups) |
| Lifecycle | Managed by Flink | User must create and delete |
| Deletion | Cleared on fresh start | Deleted with the application unless preserved |

### Create

Snapshots can only be created from RUNNING. Creation is asynchronous — poll until READY.

```bash
NAME="snapshot-$(date +%Y%m%d-%H%M%S)"
aws kinesisanalyticsv2 create-application-snapshot \
  --application-name "$APP" --snapshot-name "$NAME"

# Poll until READY (timeout matters; large state can take 10+ min)
while true; do
  STATUS=$(aws kinesisanalyticsv2 list-application-snapshots --application-name "$APP" \
    --query 'SnapshotSummaries[?SnapshotName==`'"$NAME"'`].SnapshotStatus' --output text)
  [ "$STATUS" = "READY" ] && break
  [ "$STATUS" = "FAILED" ] && { echo "Snapshot failed"; exit 1; }
  sleep 5
done
```

### Delete

`delete-application-snapshot` requires the **exact** `SnapshotCreationTimestamp` from `list-application-snapshots`. Cannot delete a snapshot in CREATING state — wait for READY or FAILED first.

### Stuck CREATING

If a snapshot stays in CREATING for >10 minutes, the cause is usually:

- Backpressure slowing state serialization (check `backPressuredTimeMsPerSecond`)
- S3 permissions missing on execution role
- VPC NAT gateway down (no network path to S3)
- State too large for the snapshot timeout

Do not stop the application while a snapshot is CREATING — that risks state inconsistency. Wait or contact AWS Support.

### Retention

Snapshots are billed at $0.023/GB-month and not auto-pruned. Implement retention:

| Environment | Keep |
|-------------|------|
| Production | Last 5 + daily for 7 days |
| Staging | Last 3 |
| Development | Last 1 |

A streaming app with checkpoint-sized snapshots and no retention will accumulate cost over months. Iterate `list-application-snapshots`, filter by `SnapshotCreationTimestamp` older than threshold, delete with the exact timestamp.

## Delete Application

`delete-application` is **irreversible** and **deletes all associated snapshots** along with the application. There is no flag, grace period, or "soft delete" that preserves snapshots — they go with the app. The MSF console will warn you, but a CLI/SDK call will not.

**Before calling `delete-application`, two requirements always apply:**

1. The application **MUST be in `READY` (stopped) state.** A `RUNNING` application cannot be deleted; call `stop-application` first and poll until `ApplicationStatus=READY`.
2. The `--create-timestamp` argument **MUST exactly match** the value of `ApplicationDetail.CreateTimestamp` returned by `describe-application`. This is a guard against accidentally deleting a re-created same-named app and there is no way to bypass it.

**To preserve state across a deletion**, you must do one of these *before* calling `delete-application` — there is no way to recover snapshots after the fact:

- **(a) Create a new application from the snapshot first.** Use the existing snapshot as the basis for a new application via `CreateApplication` with the appropriate `ApplicationConfiguration` and run the new app from that snapshot. Only delete the original after the new app is verified.
- **(b) Copy the underlying S3 checkpoint/snapshot data out-of-band.** MSF stores snapshot state in S3 paths derived from your application; you can copy the relevant S3 prefixes to a bucket you control and reconstruct state later via `RESTORE_FROM_CUSTOM_SNAPSHOT` or by reading with the State Processor API. This is the fallback when option (a) isn't practical.

```bash
# 1. Confirm the app is READY (stop first if it isn't)
STATUS=$(aws kinesisanalyticsv2 describe-application --application-name "$APP" \
  --query 'ApplicationDetail.ApplicationStatus' --output text)

# 2. Pull the exact CreateTimestamp — pass this verbatim to delete-application
TIMESTAMP=$(aws kinesisanalyticsv2 describe-application --application-name "$APP" \
  --query 'ApplicationDetail.CreateTimestamp' --output text)

# 3. (Optional) Preserve state via option (a) or (b) above before deleting

# 4. Delete (irreversible — all snapshots gone)
aws kinesisanalyticsv2 delete-application --application-name "$APP" \
  --create-timestamp "$TIMESTAMP"
```

## Pre-Mutation Checklist

Before any stop, code update, scale operation, or deletion:

1. Snapshot the application (RUNNING + poll until READY)
2. Confirm no snapshots are in CREATING (deletion / stop blocks them)
3. Verify the operation is reversible — if not, confirm with the user

## Common Mistakes

| Mistake | Consequence | Prevention |
|---------|-------------|------------|
| Stale `--current-application-version-id` | `ConcurrentModificationException` | Fetch immediately before each update |
| `update-application` without restart | App keeps running old code | Restart after code update if not auto-triggered |
| Code change without `AllowNonRestoredState=true` | Restore fails on topology change | Set `true` for code updates that change operator graph |
| Stop while snapshot CREATING | State corruption risk | Block on READY status before stopping |
| Delete app to "free state" | Snapshots permanently gone | Create new app from snapshot first |
| Force stop a healthy app | Loses unflushed state since last checkpoint | Use `--force` only on stuck transitional states |
| Restore-from-snapshot after schema change | Deserialization errors | Use `SKIP_RESTORE_FROM_SNAPSHOT` and confirm reprocess with user |

## References

- [MSF API: UpdateApplication](https://docs.aws.amazon.com/managed-flink/latest/apiv2/API_UpdateApplication.html)
- [MSF API: RunConfiguration](https://docs.aws.amazon.com/managed-flink/latest/apiv2/API_RunConfiguration.html)
- [MSF Snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/how-it-works-snapshots.html)
