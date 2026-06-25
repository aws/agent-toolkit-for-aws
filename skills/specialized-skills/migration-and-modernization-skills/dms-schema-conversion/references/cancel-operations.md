# Cancel Operations Reference

## Cancellable Operations

| Running command | Cancel command | Wait for cancellation |
|----------------|---------------|----------------------|
| `start-metadata-model-conversion` | `cancel-metadata-model-conversion` | `aws dms wait metadata-model-conversion-cancelled` |
| `start-metadata-model-creation` | `cancel-metadata-model-creation` | `aws dms wait metadata-model-creation-cancelled` |

### cancel-metadata-model-conversion

```bash
aws dms cancel-metadata-model-conversion \
  --migration-project-identifier <project_arn>
```

After cancelling, wait for completion:

```bash
aws dms wait metadata-model-conversion-cancelled \
  --migration-project-identifier <project_arn>
```

### cancel-metadata-model-creation

```bash
aws dms cancel-metadata-model-creation \
  --migration-project-identifier <project_arn>
```

After cancelling, wait for completion:

```bash
aws dms wait metadata-model-creation-cancelled \
  --migration-project-identifier <project_arn>
```

All other operations (import, assessment, export) are non-cancellable — inform the customer they must wait for completion.

---

## When Customer Requests Cancel

1. Identify which async operation is currently running
2. Check if it is cancellable (see table above)
3. If cancellable: warn the customer that **all progress will be lost** and the operation will need to be restarted from scratch. If they confirm, run the cancel command
4. Wait for the cancellation to complete using the corresponding waiter
5. If not cancellable: inform the customer the operation cannot be cancelled and must complete
6. Return to the actions menu
