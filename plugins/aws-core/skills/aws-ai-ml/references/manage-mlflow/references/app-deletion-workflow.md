# App Deletion Workflow

Guides safe deletion of a SageMaker Managed MLflow app with appropriate warnings.

> **IMPORTANT:** Use only `sagemaker:DeleteMlflowApp`. Do NOT use `DeleteMlflowTrackingServer` (legacy) — that API is deprecated.

## Step 1: Identify Target App

- If user provided an ARN: use it directly
- If not: run the discovery workflow (`references/app-discovery-workflow.md`), ask user to pick an app

## Step 2: Pre-deletion Checks

Use `aws-mcp` to call `sagemaker:DescribeMlflowApp` to get the app's current status.

- **Status is ACTIVE:** proceed to Step 3
- **Status is CREATING:** inform user — "This app is still being created. Wait until it's active before deleting."
- **Status is DELETING:** inform user — "This app is already being deleted."
- **Status is FAILED:** proceed to Step 3 (failed apps can be deleted to clean up)
- **Any other status:** inform user — "This app is not in a deletable state ({status})."

## Step 3: Destructive Action Warning

Display an explicit warning:

> **Warning:** This will permanently delete the MLflow app "{name}" and all its data, including:
>
> - All experiments and runs
> - All metrics, parameters, and tags
> - All trace data
> - All registered models (if model registration was enabled)
>
> The S3 artifact bucket and IAM role will **NOT** be deleted (they may be shared with other resources).

Ask for explicit confirmation: "Type 'yes' to confirm deletion."

**Do NOT proceed if:**

- User gives an ambiguous response ("maybe", "I think so", "sure")
- User changes the subject
- User says anything other than a clear affirmative

## Step 4: Execute Deletion

Use `aws-mcp` to call `sagemaker:DeleteMlflowApp` with the app ARN.

## Step 5: Post-deletion Guidance

Inform user:

- "MLflow app '{name}' has been deleted."
- "Your S3 bucket and IAM role still exist. You can delete them manually if they're no longer needed by other resources."

If the deleted app had `AccountDefaultStatus=Enabled`:

- Warn: "This was the account-default MLflow app. Other users or Studio domains that relied on it as default will need to be reconfigured."

## Error Handling

| Error | Resolution |
|---|---|
| `ResourceNotFound` | "This app has already been deleted." |
| `ResourceInUse` | "This app has active operations. Wait for them to complete first." |
| `AccessDeniedException` | "You need `sagemaker:DeleteMlflowApp` permission." |
