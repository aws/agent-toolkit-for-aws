# Cancel Operations Reference

## Cancellable Operations

| Running command | Cancel command | Wait for cancellation |
|----------------|---------------|----------------------|
| `start-metadata-model-conversion` | `cancel-metadata-model-conversion` | `aws dms wait metadata-model-conversion-cancelled` |
| `start-metadata-model-creation` | `cancel-metadata-model-creation` | `aws dms wait metadata-model-creation-cancelled` |

### cancel-metadata-model-conversion

```bash
aws dms cancel-metadata-model-conversion \
  --migration-project-identifier <project_arn> \
  --request-identifier <RequestIdentifier>
```

After cancelling, wait for completion:

```bash
aws dms wait metadata-model-conversion-cancelled \
  --migration-project-identifier <project_arn> \
  --filter 'Name=request-id,Values=<RequestIdentifier>'
```

### cancel-metadata-model-creation

```bash
aws dms cancel-metadata-model-creation \
  --migration-project-identifier <project_arn> \
  --request-identifier <RequestIdentifier>
```

After cancelling, wait for completion:

```bash
aws dms wait metadata-model-creation-cancelled \
  --migration-project-identifier <project_arn> \
  --filter 'Name=request-id,Values=<RequestIdentifier>'
```

All other operations (import, assessment, export) are non-cancellable — inform the customer they must wait for completion.

---

## When Customer Requests Cancel

1. Identify which async operation is currently running and preserve its original `RequestIdentifier`
2. Check if it is cancellable (see table above)
3. If cancellable: warn the customer that **all progress will be lost** and the operation will need to be restarted from scratch. Show the exact cancellation action, including the project and request identifiers, and wait for explicit customer confirmation immediately before running it
4. Run the matching cancel command with the original `RequestIdentifier`, then wait for the same request using the corresponding waiter and request-ID filter
5. If the cancellation waiter fails, describe the same request with `Name=request-id,Values=<RequestIdentifier>`. If the operation reached another terminal status before cancellation, report that status; do not retry cancellation or claim it was cancelled
6. If not cancellable: inform the customer the operation cannot be cancelled and must complete
7. Return to the actions menu
