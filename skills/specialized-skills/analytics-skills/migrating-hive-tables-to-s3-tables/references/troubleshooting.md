# Troubleshooting

Async failures appear in `get-table-migration` as `failureReason.code`, often with a `detail`.
Synchronous errors are returned by the call itself as an exception and HTTP status. Key on the code,
detail, or exception type, not on message wording, which can change.

## Synchronous errors (returned by the call)

| Error | Cause | Fix |
|---|---|---|
| `BadRequestException` (400) at Start naming the source catalog | `catalogId` is missing or wrong in `source.glueTable` | Set `catalogId` to the source account id and run Start again. Nothing was created |
| `NotFoundException` (404) at Start naming the destination namespace | The destination namespace does not exist in the table bucket | Create the namespace (after approval), then run Start again. Not the same as the async `resourceNotFound` below |
| `ConflictException` (409) at Start: destination table exists | A table with that name already exists in the namespace | Check `get-table --query managedByService`. Offer to delete only if it is `migration.s3tables.amazonaws.com` (or `list-table-migrations` finds it) and the user confirms that exact table ARN. If the earlier migration has `hasValidPlan: true` and the right settings, resume with `sync-table-migration` instead. Otherwise use a different table name. Never delete a table the migration did not create |
| `ConflictException` (409) on Complete while copying | The migration is still `queued` or `migrating` | Poll until `succeeded`, then Complete with `--table-arn` |
| `ConflictException` (409) or `BadRequestException` (400) on Complete: already completed, or not managed | The table was already handed over, or the ARN is not the migration's destination | Confirm with `get-table` (`managedByService` is null means done) and `get-table-migration` (`tableARN`). No action if already done |
| `BadRequestException` (400) on Sync after Complete | The migration was completed, so it can no longer be synced | Nothing to sync. Confirm `get-table` shows `managedByService` null. A shortfall found now cannot be fixed with Sync |
| `ForbiddenException` (403) on a migration call | The caller lacks permission, or the `migrationId` is not in this account | Check the caller policy in `references/iam-roles.md` and the `migrationId`. Do not widen the caller policy to `Resource: *` |

## Async failures (`failureReason.code`)

| `failureReason.code` | Cause | Fix |
|---|---|---|
| `resourceNotFound` | A source resource is missing, such as the Glue table | Confirm the Glue database and table exist and `catalogId` is correct, then start again |
| `rolePermissions` | The migration service cannot assume the role: wrong principal, or `aws:SourceAccount`/`aws:SourceArn` do not match | The trust must name `migration.s3tables.amazonaws.com` with `aws:SourceAccount` and `aws:SourceArn` matching your account and destination table-bucket ARN exactly. Compare the ARN character by character. Do not remove the conditions. Show the user the missing statement and apply it only after approval (see `references/iam-roles.md`) |
| `sourcePermissions` | The role cannot read the source (S3 objects, Glue table or partitions, or source KMS key) | Show the user the missing statement and apply it only after approval (see `references/iam-roles.md`). If the IAM policy is already correct and the table is registered with Lake Formation, see `metadata.glueLakeFormation` below |
| `destinationPermissions` | The role cannot write the destination, most often the report bucket | Check `s3:PutObject` on the report prefix and the report-bucket KMS grant. Show the user the missing statement and apply it only after approval (see `references/iam-roles.md`) |
| `sourceNotSupported`, with `detail` naming the reason (for example `UNSUPPORTED_TABLE_TYPE`, `UNSUPPORTED_FILE_FORMAT`, `UNSUPPORTED_SERDE`, `UNSUPPORTED_TABLE_LOCATION`, `UNSUPPORTED_COLUMNS`, `UNSUPPORTED_PARTITION_KEYS`, `UNSUPPORTED_PARTITIONS`, `UNSUPPORTED_TABLE_PARAMETER`, `EMPTY_TABLE`, `NO_DATA_OBJECTS`, `MAX_KEYS_REACHED`, `UNSUPPORTED_SOURCE`) | The table cannot be migrated: a managed table or view, a non-Parquet format or SerDe, an unsupported column or partition key type, partitions outside the table location, an unsupported table property (for example transactional or Iceberg), or a table that is empty or too large. The table compatibility report lists the findings | Fails during planning and is not fixable by IAM. For partitions outside the table location, show the user the partitions (`preflight.md` §3) and do not move data or edit partitions. Otherwise change the source or use the `ingesting-into-data-lake` skill. Before starting again, delete the leftover destination table with the user's confirmation |
| Finding `metadata.glueLakeFormation` in the table compatibility report | The source table or its S3 location is registered with Lake Formation, which is not supported | Stop. Tell the user, and suggest contacting AWS Support or their account team with the migration ID to request support. Never grant Lake Formation permissions, deregister locations, or change data lake settings |
| `tableCompatibilityReport` | The table compatibility report has a blocking (`invalid`) finding | Read the report (`migrationOutput.tableCompatibilityReport.key`). If you fix the findings at the source and `hasValidPlan` is true, resume with `sync-table-migration`. To change `migrationPolicies` or the destination schema, delete the destination table (with the user's confirmation) and Start again with the new settings |
| `objectCompatibilityReport` | Source objects cannot migrate, for example SSE-C encrypted or archived (Glacier) objects, or (on Sync) an object overwritten in place since the last run (`data.objectModified`) | Read the report (`migrationOutput.objectCompatibilityReport.key`) and fix the objects at the source. Sync cannot reconcile in-place overwrites; start a fresh migration of the current source instead |
| `objectMigrationReport` | One or more objects failed to copy, for example a value that does not fit the destination column type under `incompatibleValuesPolicy=fail`. A single failed object fails the whole run | Read the per-object errors in the report (`migrationOutput.objectMigrationReport.key`) and fix the objects or the type mapping |
| `reportBucketNotSupported` | `migrationOutput.bucket` is not a general-purpose bucket in the same account and Region | Use a general-purpose S3 bucket in the same account and Region |
| `internalError`, no `detail` | A service-side error | Check the configuration once (`catalogId`, `migrationOutput`, namespace, trust policy). If it repeats, stop retrying and open a case with AWS Support with the `migrationId` and Region |
| Planning fails on an SSE-KMS destination, IAM looks correct | The destination key policy does not allow `maintenance.s3tables.amazonaws.com` | Add the key-policy statement in `references/iam-roles.md` (read the policy with `get-key-policy`, add one statement, never replace the policy), after approval |

## No progress

| Symptom | Fix |
|---|---|
| Stuck in `queued` or `migrating` with no `failureReason`, far longer than the data size warrants | Re-check `failureReason`. If it is still empty, open a case with AWS Support with the `migrationId` and Region. Do not treat a stalled job as success |

## General approach

1. Pull `failureReason` first: `get-table-migration --query failureReason`.
2. Find the code or exception in the tables above and fix that gap.
3. Recover per `references/lifecycle.md` (Recovery after a cancel or fail): the destination table is kept; resume with `sync-table-migration` when `hasValidPlan` is true and the fix is outside the migration settings.
4. Unsupported sources (`sourceNotSupported`, `metadata.glueLakeFormation`) are not fixable by retrying or by changing IAM. Stop and explain.
5. Confirm success with an Athena row count and spot check on the destination (`references/validation.md`).
