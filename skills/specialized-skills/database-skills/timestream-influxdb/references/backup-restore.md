# Backup and Restore

## Contents

- [When to Activate](#when-to-activate)
- [Verify Before Advising](#verify-before-advising)
- [Confirm Capabilities for the Engine Variant](#confirm-capabilities-for-the-engine-variant)
- [Create an On-Demand Backup](#create-an-on-demand-backup)
- [Configure Automated Backups](#configure-automated-backups)
- [Restore from a Backup](#restore-from-a-backup)
- [List, Retain, and Delete Backups](#list-retain-and-delete-backups)
- [Portable Data-Plane Export](#portable-data-plane-export)
- [Access Control and Cost](#access-control-and-cost)

## When to Activate

User asks about backups, snapshots, scheduled or continuous backups, point-in-time restore (PITR), recovering deleted or corrupted data, backup retention, or copying data out of Timestream for InfluxDB.

## Verify Before Advising

- Retrieve the documentation page for the engine variant: [InfluxDB 3 backup and restore](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-customer-managed-backup-restore.html) or [InfluxDB 2 backup and restore](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb2-customer-managed-backup-restore.html). Then inspect the installed API model, for example `aws timestream-influxdb create-db-backup help` and `aws timestream-influxdb restore-from-db-backup help`.
- When the documentation and the API model disagree on request syntax, use the API model. For example, the guides show a `CUSTOM` backup type, but the API enum value is `CUSTOM_SCHEDULE`. If the installed CLI or SDK lacks these operations, update it; do not fall back to an older workaround.
- Call these resources **DbBackups** (backups), never "snapshots." Service-managed backups are a separate mechanism: AWS maintains them, and recovering from them requires an AWS Support case. Customer-managed DbBackups are self-service. When a user asks for a "snapshot," explain the distinction and use DbBackup operations.
- Backups and restores stay in the same AWS account and Region. Cross-account and cross-Region restore are not supported.

## Confirm Capabilities for the Engine Variant

Backup capabilities differ by engine variant and change over time, so confirm each one in the variant's guide and the installed API model before offering it. Do not assume a capability documented for one variant applies to another.

- **Backup types:** Read the `type` enum from the API model, then check which types the variant's guide documents. Offer `CONTINUOUS` and `--restore-to-time` only for variants whose guide documents them. If the V2 guide does not document them, say so; do not offer them for V2 instances or Read Replica clusters.
- **Retention:** Take `retentionDays` ranges from the API model, and apply any tighter per-type limit the guide states, such as a maximum for `CONTINUOUS`.
- **Restore targets:** Confirm in the guide which targets a backup can restore to. For V2, check whether a cluster backup can restore to a standalone instance, and the WAL caveat for restoring an instance backup to a Read Replica cluster.
- **Resource identifier:** For a V2 Read Replica cluster, confirm that the guide uses the cluster ID as `--db-resource-id`.
- **Storage billing:** Take the storage service and charges from the guide's pricing section and the pricing page; do not quote rates from memory.

Do not claim restore across engine variants (V2 to V3 or the reverse); use the [migration guide](migration-guide.md) instead.

## Create an On-Demand Backup

```bash
aws timestream-influxdb create-db-backup \
  --db-resource-id <instance-or-cluster-id> \
  --name <backup-name> \
  --retention-days <retention-days> \
  --tags created_by=timestream-skill,generation_model=<your-model-id> \
  --region <region>
```

- `--db-resource-id` takes the resource **ID** returned by `get-db-instance` or `get-db-cluster`, not its name.
- `--name` must have 3–40 characters, start with a letter, and contain letters, digits, and single hyphens. It must be unique within the account and Region.
- The guides describe automatic deletion only when retention is set. Read `expiresAfter` from `get-db-backup` before telling the user when the backup expires.
- Apply the same `created_by` and `generation_model` tags the skill requires on clusters and instances, appending any tags the user supplies.
- If the call returns a conflict because the resource is `UPDATING`, `MAINTENANCE`, or otherwise transitioning, poll `get-db-instance` or `get-db-cluster` until `AVAILABLE`, then retry.
- The resource stays available while the backup runs. A backup can take up to about an hour to start. The first backup is a full copy; later backups are incremental.
- Status flows `IN_PROGRESS` → `COMPLETED` or `FAILED`; a backup being deleted shows `DELETING` and then `DELETED`. Only a `COMPLETED` backup can be restored. Poll `get-db-backup --identifier <backup-id>` and report the actual status. Never describe an `IN_PROGRESS` backup as complete or restorable.

## Configure Automated Backups

`--db-backup-configurations` is accepted by `create-db-instance`, `create-db-cluster`, `update-db-instance`, `update-db-cluster`, and `restore-from-db-backup`. Each entry has the following fields:

| Field | Rule |
| --- | --- |
| `type` (required) | `HOURLY`, `DAILY` (midnight, Region time zone), `WEEKLY` (Sunday midnight), `MONTHLY` (the 1st at midnight), `CUSTOM_SCHEDULE`, or `CONTINUOUS` (only where the variant's guide documents it) |
| `retentionDays` (required) | The range in the API model, within any tighter `CONTINUOUS` maximum the guide states |
| `enabled` (required) | `true` or `false` |
| `customSchedule` | Required for `CUSTOM_SCHEDULE`: a six-field AWS cron expression such as `cron(00 18 * * * *)`, at most once per day |

At most one configuration per type and at most four per resource. Scheduled backups can start any time within an hour of the scheduled time.

```bash
# Cluster on a variant whose guide documents CONTINUOUS: point-in-time coverage plus daily and monthly archives
aws timestream-influxdb update-db-cluster \
  --db-cluster-id <cluster-id> \
  --db-backup-configurations '[
    {"type":"CONTINUOUS","retentionDays":30,"enabled":true},
    {"type":"DAILY","retentionDays":7,"enabled":true},
    {"type":"MONTHLY","retentionDays":365,"enabled":true}]' \
  --region <region>

# V2 instance: hourly plus daily
aws timestream-influxdb update-db-instance \
  --identifier <instance-id> \
  --db-backup-configurations '[
    {"type":"HOURLY","retentionDays":1,"enabled":true},
    {"type":"DAILY","retentionDays":7,"enabled":true}]' \
  --region <region>
```

- Send every configuration the user wants to keep. To turn one off, send it with `"enabled": false` rather than assuming that omitting it removes it.
- After the update, wait until the resource returns to `AVAILABLE`. Then read `dbBackupConfigurations` from `get-db-cluster` or `get-db-instance` and confirm each type, `retentionDays`, `enabled`, and `nextAutomatedBackupTime`.

## Restore from a Backup

Before calling `restore-from-db-backup`, show the user the backup ID, the source resource, the restore mode, the target name, and any overrides. Obtain explicit confirmation.

**`NEW_RESOURCE` (default and recommended):** creates a new instance or cluster and leaves the source untouched.

```bash
aws timestream-influxdb restore-from-db-backup \
  --name <new-resource-name> \
  --db-backup-id <backup-id> \
  --restore-mode NEW_RESOURCE \
  --tags created_by=timestream-skill,generation_model=<your-model-id> \
  --region <region>
```

- The new resource inherits its configuration from the backup. You can override a subset, as listed by the API model: subnets, security groups, public accessibility, log delivery, maintenance schedule, port, network type, deployment type, backup configurations, and KMS key.
- **Point-in-time restore:** add `--restore-to-time <unix-epoch-seconds>` with a `CONTINUOUS` backup ID. The time must fall within the retention window and be at least 15 minutes in the past, because data written in the last 15 minutes might not be included. Scheduled and on-demand backups do not support point-in-time restore.

**`REPLACE_EXISTING` (destructive):**

```bash
aws timestream-influxdb restore-from-db-backup \
  --name <existing-resource-name> \
  --db-backup-id <backup-id> \
  --restore-mode REPLACE_EXISTING \
  --region <region>
```

- `--name` must equal the existing resource's name. No other parameters are accepted, and the configuration is unchanged.
- The resource is unavailable during the operation. Its current data is deleted and cannot be recovered unless a backup exists. If the restore fails, the service attempts to roll the resource back to its original data, but do not rely on that rollback. Before proceeding, you MUST create an on-demand backup, wait for it to reach `COMPLETED`, and state this impact to the user.
- Not supported for a cluster encrypted with a customer-managed KMS key. Use `NEW_RESOURCE` for such a cluster.

**V2-specific limits:**

- A cluster backup cannot be restored to a standalone instance.
- Restoring a standalone-instance backup to a Read Replica cluster is a migration. It includes only data already flushed from the WAL to TSM files; a lightly written instance can restore as empty. To capture all data, stop writes for at least 10 minutes before taking the backup. Restoring to another standalone instance preserves WAL data.

**After the restore call:**

- The response returns `restoredDbResourceId`, `resourceType` (`DB_INSTANCE` or `DB_CLUSTER`), and `restoreStatus`.
- Poll `get-db-instance` or `get-db-cluster` with that ID until it reaches `AVAILABLE`, or report a terminal state such as `RESTORE_FAILED` or `FAILED`. Do not report success while the resource is still `RESTORING`.
- For `NEW_RESOURCE`, give the user the new endpoint, read the new resource's `influxAuthParametersSecretArn` rather than reusing the source's secret, and remind them to repoint clients.
- When a customer-managed KMS key is involved, confirm the restored resource's `kmsKeyId` matches the intended key ARN.

## List, Retain, and Delete Backups

```bash
aws timestream-influxdb list-db-backups --db-resource-id <resource-id> --region <region>
aws timestream-influxdb get-db-backup --identifier <backup-id> --region <region>
aws timestream-influxdb delete-db-backup --identifier <backup-id> --region <region>
```

- `delete-db-backup` is irreversible. Show the backup ID, name, source resource, and type, and obtain explicit confirmation first.
- Deleting an instance or cluster deletes its automated backups by default and retains its on-demand backups. Pass `--retain-automated-backups` to `delete-db-instance` or `delete-db-cluster` to keep automated backups until they expire.
- Before deleting a resource, tell the user which of its backups will survive and that retained backups continue to incur storage charges until they expire or are deleted.

## Portable Data-Plane Export

DbBackups can only be restored into Timestream for InfluxDB in the same account and Region. For an independent, portable copy, use the InfluxDB data-plane API and store the export in an S3 bucket protected with SSE-KMS. Never put a token literal in the command or write an unencrypted export to local disk.

Load `INFLUX_TOKEN` or `V3_TOKEN` from Secrets Manager using the patterns in [getting started](getting-started.md), keep shell tracing disabled, and then export:

```bash
# V2: Stage only on an encrypted volume, then upload an encrypted archive.
set -o pipefail
umask 077
BACKUP_DIR="<directory-on-encrypted-volume>"
install -d -m 700 "$BACKUP_DIR"

influx backup "$BACKUP_DIR" --host https://<endpoint>:8086 &&
  tar -C "$BACKUP_DIR" -czf - . |
    aws s3 cp - s3://<backup-bucket>/<backup-key>.tar.gz \
      --sse aws:kms --sse-kms-key-id <kms-key-arn>
BACKUP_STATUS=$?

unset INFLUX_TOKEN
if test "$BACKUP_STATUS" -eq 0; then
  rm -rf -- "$BACKUP_DIR"
else
  printf 'Backup or upload failed; staging preserved at %s\n' "$BACKUP_DIR" >&2
  exit "$BACKUP_STATUS"
fi

# V3: Stage only on an encrypted volume, then upload the verified export.
set -o pipefail
umask 077
EXPORT_FILE="<file-on-encrypted-volume>"

printf 'Authorization: Bearer %s\n' "$V3_TOKEN" |
  curl --fail-with-body -X POST "https://<endpoint>:8181/api/v3/query_sql" \
    -H @- \
    -H "Content-Type: application/json" \
    -d '{"db":"<database>","q":"SELECT * FROM <table>","format":"csv"}' \
    -o "$EXPORT_FILE" &&
  test -s "$EXPORT_FILE" &&
  aws s3 cp "$EXPORT_FILE" s3://<backup-bucket>/<backup-key>.csv \
    --sse aws:kms --sse-kms-key-id <kms-key-arn>
EXPORT_STATUS=$?

unset V3_TOKEN
if test "$EXPORT_STATUS" -eq 0; then
  rm -f -- "$EXPORT_FILE"
else
  printf 'Export or upload failed; staging preserved at %s\n' "$EXPORT_FILE" >&2
  exit "$EXPORT_STATUS"
fi
```

Delete staging data only after a successful S3 upload, following the organization's secure-deletion policy. Preserve it on failure so the upload can be retried. Restrict the backup bucket and KMS key policies to authorized backup and restore roles.

## Access Control and Cost

- Backups are encrypted at rest. A resource that uses a customer-managed KMS key has its backups encrypted with the same key, so keep that key enabled for as long as any backup must stay restorable. See [encryption guidance](encryption.md).
- Grant the backup and restore actions (`CreateDbBackup`, `GetDbBackup`, `ListDbBackups`, `DeleteDbBackup`, `RestoreFromDbBackup`) only to operator roles that need them. To block in-place restores, attach a deny on `timestream-influxdb:RestoreFromDbBackup` with the condition `"StringEquals": {"timestream-influxdb:RestoreMode": "REPLACE_EXISTING"}`.
- Take the feature charge, the storage service backups are billed to, and any restore charge from the variant's guide and the pricing page before quoting costs.
