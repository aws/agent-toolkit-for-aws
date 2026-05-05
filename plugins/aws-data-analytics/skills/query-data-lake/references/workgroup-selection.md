# Workgroup Selection

Always list workgroups first before executing any query.

## Detect Execution Context

Before selecting a workgroup, determine the current IAM identity:

```bash
aws sts get-caller-identity --query Arn --output text
```

The ARN pattern reveals the execution context:

| ARN Pattern | Context | Workgroup Strategy |
|---|---|---|
| `arn:aws:sts::*:assumed-role/AmazonDataZone-<project-id>-<suffix>/<session>` | SageMaker Unified Studio project role | Use the project-scoped workgroup (see below) |
| `arn:aws:sts::*:assumed-role/SageMakerUnifiedStudio-<project-id>-<suffix>/<session>` | SageMaker Unified Studio project role | Use the project-scoped workgroup (see below) |
| `arn:aws:sts::*:assumed-role/AmazonSageMaker-ExecutionRole-*` | SageMaker notebook/studio role | Prefer `sagemaker-studio-workgroup-*` |
| Anything else | Standard IAM user/role | Follow general priority order |

## SageMaker Project Role Selection

When running as a SageMaker project role (`AmazonDataZone-*` or `SageMakerUnifiedStudio-*`):

1. List all workgroups the role can access:

   ```bash
   aws athena list-work-groups --query 'WorkGroups[].Name' --output json
   ```

2. Extract the project ID from the role ARN. Split the role name on `-`.
   The first segment is the prefix (e.g., `AmazonDataZone`), the second
   segment is the project ID (e.g., `abc123def`), and subsequent segments
   form the suffix (e.g., `DataLakeAccess`). Take the second segment.
   The project ID is an **alphanumeric string (no hyphens)**.
   Known suffixes that follow the project ID: `DataLakeAccess`, `SparkAccess`,
   `QueryAccess`, `IngestionAccess`. Example:

   ```
   arn:aws:sts::123456789012:assumed-role/AmazonDataZone-abc123def-DataLakeAccess/session
                                                         ^^^^^^^^^
                                                         project ID = abc123def
   ```

3. Match the workgroup to the project. Project workgroups follow the pattern
   `sagemaker-studio-workgroup-<project-id>` or contain the project ID.
4. If exactly one `sagemaker-studio-workgroup-*` exists, verify its suffix
   contains the project ID extracted in step 2. If it matches, use it.
   If it does not match, fall through to step 6.
5. If multiple exist, pick the one whose suffix matches the project ID
   extracted from the role ARN. Optionally check environment variables
   `SAGEMAKER_PROJECT_ID` or `SAGEMAKER_PROJECT_NAME` if the ARN extraction
   is ambiguous.
6. If no `sagemaker-studio-workgroup-*` exists, **do not fall back** to other
   workgroups. Inform the user that no project-scoped workgroup was found and
   ask them to verify their project configuration or IAM permissions.

Project roles typically have IAM permissions scoped to their own workgroup.
Attempting to use `primary` or another project's workgroup will fail with
AccessDeniedException. Do not retry with `primary` in this context.

## General Priority Order (Non-Project Roles)

1. `sagemaker-studio-workgroup-*` workgroups -- most reliable, always have output locations configured
2. Workgroups with explicitly configured output locations
3. `primary` workgroup (use with caution, may lack output location)

## Error Recovery

| Error | Context | Action |
|---|---|---|
| No output location | Any | Retry with the next workgroup in priority order |
| AccessDeniedException on workgroup | Project role | Do not retry with other workgroups. Inform the user their project role lacks access. |
| AccessDeniedException on workgroup | Standard role | Retry with the next workgroup in priority order |
| No workgroups found | Any | Ask the user to configure a workgroup or check IAM permissions |

## Anti-patterns

- Never default to `primary` workgroup without checking others first
- Never hardcode a workgroup name across sessions
- Never retry with `primary` when running as a SageMaker project role -- it will fail with AccessDeniedException
