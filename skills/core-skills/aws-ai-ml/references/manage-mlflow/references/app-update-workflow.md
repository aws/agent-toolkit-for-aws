# App Update Workflow

Guides safe updates to an existing MLflow app's configuration.

> **IMPORTANT:** Use only `sagemaker:UpdateMlflowApp`. Do NOT use `UpdateMlflowTrackingServer` (legacy) — that API is deprecated.

## Step 1: Identify Target App

- If user provided an ARN: use it directly
- If not: run the discovery workflow (`references/app-discovery-workflow.md`), ask user to pick an app

## Step 2: Show Current Configuration

Use `aws-mcp` to call `sagemaker:DescribeMlflowApp` with the app ARN. Present the updatable fields with their current values.

Use `aws-mcp` to discover which fields are updatable on the `UpdateMlflowApp` API at runtime — do not hardcode a static field list.

Ask: "Which field would you like to update?"

## Step 3: Confirm the Change

- Ask user for the new value
- Use `aws-mcp` to discover valid values for the field if applicable
- Present confirmation: "Change `{field}` from `{old_value}` to `{new_value}`?"
- Do not proceed without explicit confirmation

## Step 4: Apply and Verify

- Use `aws-mcp` to call `sagemaker:UpdateMlflowApp` with the ARN and updated field
- Poll: use `aws-mcp` to call `sagemaker:DescribeMlflowApp` in a loop (every minute) until status returns to `ACTIVE` (update triggers `UPDATING` status)
- Timeout: 10 minutes. If exceeded, warn user and suggest checking Console.
- Once `ACTIVE`: verify the field value matches the requested change
- Confirm to user: "{field} updated successfully."

## Error Handling

| Error | Resolution |
|---|---|
| `ConflictException` | Another update is in progress. Wait 30 seconds, then retry. |
| `AccessDeniedException` | "You need `sagemaker:UpdateMlflowApp` permission." |
| `ResourceNotFound` | "This app no longer exists." |
| `ValidationException` | Use `aws-mcp` to look up valid values and present them to the user. |
