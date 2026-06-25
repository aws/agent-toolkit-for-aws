# Schema Conversion Operations Reference

## Command Summary

| Command | Purpose | Async | Poll via | Waiter |
|---------|---------|-------|----------|--------|
| [start-metadata-model-import](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-import.html) | Import metadata from source or target DB | Yes | `describe-metadata-model-imports` | [`metadata-model-imported`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-imported.html) |
| [start-metadata-model-conversion](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-conversion.html) | Convert source schema to target | Yes | `describe-metadata-model-conversions` | [`metadata-model-converted`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-converted.html) |
| [start-metadata-model-assessment](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-assessment.html) | Assess conversion complexity | Yes | `describe-metadata-model-assessments` | [`metadata-model-assessed`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-assessed.html) |
| [start-metadata-model-creation](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-creation.html) | Create statement-based model | Yes | `describe-metadata-model-creations` | [`metadata-model-created`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-created.html) |
| [start-metadata-model-export-as-script](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-export-as-script.html) | Export DDL to S3 | Yes | `describe-metadata-model-exports-as-script` | [`metadata-model-exported-as-script`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-exported-as-script.html) |
| [start-metadata-model-export-to-target](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-export-to-target.html) | Apply converted DDL to target DB | Yes | `describe-metadata-model-exports-to-target` | [`metadata-model-exported-to-target`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-exported-to-target.html) |
| [export-metadata-model-assessment](https://docs.aws.amazon.com/cli/latest/reference/dms/export-metadata-model-assessment.html) | Generate PDF/CSV report to S3 | Sync | N/A | sync |
| [describe-metadata-model-children](https://docs.aws.amazon.com/cli/latest/reference/dms/describe-metadata-model-children.html) | Navigate tree structure | Sync | N/A | sync |
| [describe-metadata-model](https://docs.aws.amazon.com/cli/latest/reference/dms/describe-metadata-model.html) | Get object definition (DDL) | Sync | N/A | sync |
| [cancel-metadata-model-conversion](https://docs.aws.amazon.com/cli/latest/reference/dms/cancel-metadata-model-conversion.html) | Cancel running conversion | Yes* | N/A | [`metadata-model-conversion-cancelled`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-conversion-cancelled.html) |
| [cancel-metadata-model-creation](https://docs.aws.amazon.com/cli/latest/reference/dms/cancel-metadata-model-creation.html) | Cancel running creation | Yes* | N/A | [`metadata-model-creation-cancelled`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-creation-cancelled.html) |

> \* The cancel API call returns synchronously, but the cancellation state transition is async (`CANCEL_RECEIVED` → `CANCELING` → `CANCELED`). Use the corresponding waiter to confirm the operation reached the `CANCELED` state.
>
> **Note:** All waiters require `--filter 'Name=schema-conversion-operation-id,Values=<RequestId>'` in addition to `--migration-project-identifier`.

For full parameter details and examples, refer to the linked CLI documentation for each command.

---

## DMS Waiters

Use DMS waiters to wait for async operations to complete:

| Operation | Waiter command |
|-----------|---------------|
| Import | `aws dms wait metadata-model-imported` |
| Conversion | `aws dms wait metadata-model-converted` |
| Assessment | `aws dms wait metadata-model-assessed` |
| Creation (statement) | `aws dms wait metadata-model-created` |
| Export as script | `aws dms wait metadata-model-exported-as-script` |
| Export to target | `aws dms wait metadata-model-exported-to-target` |
| Cancel conversion | `aws dms wait metadata-model-conversion-cancelled` |
| Cancel creation | `aws dms wait metadata-model-creation-cancelled` |
| Extension pack | `aws dms wait extension-pack-associated` |

Documentation: https://docs.aws.amazon.com/cli/latest/reference/dms/wait/index.html

---

## Operation Statuses

All async operations use the same status values:

| Status | Meaning |
|--------|---------|
| `RECEIVED` | Request received, queued |
| `IN_PROGRESS` | Operation is running |
| `SUCCESS` | Operation completed successfully |
| `FAILED` | Operation failed — check error details |
| `CANCEL_RECEIVED` | Cancellation request received |
| `CANCELING` | Cancellation in progress |
| `CANCELED` | Operation was cancelled |
| `RETRY` | Operation is being retried |
| `PENDING` | Operation is pending |

---

## Execution Pattern

1. Call `start-*` → extract `RequestIdentifier`
2. Wait for completion using the corresponding `aws dms wait` command (see DMS Waiters table)
3. If the waiter returns successfully → proceed to next step
4. If the waiter fails or is unavailable (e.g., `Invalid choice` due to outdated CLI) → fall back to manual polling with the corresponding `describe-*` command until status reaches `SUCCESS` or `FAILED`

**Fallback polling pattern** (use when waiter is not available):

```
aws dms describe-metadata-model-<operation>s \
  --migration-project-identifier <migration_project_identifier> \
  --filter Name=request-id,Values=<RequestIdentifier>
```

Check `Requests[0].Status` — repeat every 30 seconds until it reaches `SUCCESS` or `FAILED`.

**Constraint:** You MUST NOT proceed to the next step until the operation has completed. If the waiter fails or times out, you MUST fall back to polling with the describe command. Never assume an operation succeeded without confirming its status.

---

## Key Notes

- `describe-metadata-model` returns `TargetMetadataModels` with target `SelectionRules` — use these to query the TARGET tree (do NOT reuse source selection rules for target)
- `describe-metadata-model-children` returns `MetadataModelChildren[]` with `MetadataModelName` and `SelectionRules` — use the child's `SelectionRules` to drill deeper
- `export-metadata-model-assessment` is synchronous — returns S3 links immediately (`PdfReport.S3ObjectKey`, `CsvReport.S3ObjectKey`)
- `start-metadata-model-creation` only supports **SQL Server → PostgreSQL/Aurora PostgreSQL**
