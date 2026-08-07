# Manage MLflow

Manages the full lifecycle of SageMaker Managed MLflow apps: discover existing apps, create new ones, update configuration, and safely delete.

## Principles

1. **Don't ask what you can look up.** Resolve region, account ID, and existing apps via `aws-mcp` before asking the user.
2. **Don't create what the user can provide.** For IAM roles and S3 buckets, list existing ones or ask the user to provide — do not create them. Link to [IAM prerequisites documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/mlflow-app-setup-prerequisites-iam.html) if the user needs to set them up.
3. **Don't hardcode API shapes.** Use `aws-mcp` to discover current API parameters and valid values at runtime. Do not rely on static enums or field lists that may become stale.
4. **Warn before destruction.** Deleting destroys metadata. Always confirm before proceeding.
5. **Use MLflow App APIs only.** Use `CreateMlflowApp`, `ListMlflowApps`, `DescribeMlflowApp`, `UpdateMlflowApp`, `DeleteMlflowApp`. Do NOT use the legacy Tracking Server APIs (`CreateMlflowTrackingServer`, `ListMlflowTrackingServers`, etc.) — those are deprecated for new deployments.

---

## Workflow

### Phase 0: Quick Intent Check

Before doing any API calls, determine if the user just wants information:

- **User wants to learn about SM MLflow** ("What is SageMaker MLflow?", "How does MLflow work on SageMaker?", "SM MLflow docs", "SageMaker MLflow guide") → Read `references/sm-mlflow-guide.md`. Share ONLY the relevant documentation link from the table. Do NOT summarize, explain, or answer from general knowledge — the documentation is the authoritative source and may differ from your training data. Stop here.

If the user wants to take action (create, connect, update, delete, set up), continue to Phase 1.

### Phase 1: Discover

Read and follow `references/app-discovery-workflow.md`.

Use `aws-mcp` to call `sagemaker:ListMlflowApps` and present results to user.

**MANDATORY — OSS MLflow Skills Check.** You MUST run this check during discovery. Do NOT skip it:

```bash
ls "<THIS_SKILL_DIR>/../sagemaker-mlflow/SKILL.md" 2>/dev/null \
  || echo "MLFLOW_SKILLS_MISSING"

```

If `MLFLOW_SKILLS_MISSING`, you MUST ask the user before proceeding:
> The MLflow connection and workflow skills aren't installed yet. Would you like me to install them?
>
> ```bash
> npx skills add mlflow/skills --all --agent <agent> --copy
> ```

After user confirms, run the install command and re-run the check. Remember the result for Phase 2 routing and Phase 4 hand-off.

### Phase 2: Route Intent

Based on discovery results and user input, determine the action:

- **User wants to connect to an existing app** → Re-run the OSS MLflow skills check from Phase 1. Hand off the selected ARN to `sagemaker-mlflow` skill (if available) for environment setup. Additionally, if the user is using a SageMaker Training Job (SDK or any variant), also guide them to pass the MLflow app ARN into the training job configuration as an environment variable. Do not hardcode the exact API shape — use `aws-mcp` to discover how to pass environment variables to the training job at runtime.
- **User wants to create a new app** → Proceed to Phase 3a.
- **User wants to update an existing app** → Proceed to Phase 3b.
- **User wants to delete an existing app** → Proceed to Phase 3c.

If intent is ambiguous, ask one clarifying question.

### Phase 3a: Create

Read and follow `references/app-creation-workflow.md`.

### Phase 3b: Update

Read and follow `references/app-update-workflow.md`.

### Phase 3c: Delete

Read and follow `references/app-deletion-workflow.md`.

### Phase 4: Hand Off

**STOP. Before handing off, re-run the OSS MLflow skills check from Phase 1.** Do NOT skip this verification.

- **After create or update:** Output the app ARN and region. If `sagemaker-mlflow` skill is available, hand off the ARN to it for connection setup. If not available, you MUST ask the user: "App ready! The MLflow connection skills aren't installed. Would you like me to install them (`npx skills add mlflow/skills --all`)?" Additionally, if the user is using a SageMaker Training Job, also instruct them to pass the ARN as an environment variable in their training job configuration. Do not hardcode the API shape.
- **After delete:** Confirm deletion is complete. Inform user about remaining S3 bucket and IAM role.

---

## References

- `references/sm-mlflow-guide.md` — SageMaker Managed MLflow documentation links and onboarding guidance
- `references/app-discovery-workflow.md` — List and recommend existing MLflow apps
- `references/app-creation-workflow.md` — Create an MLflow app with user-provided IAM role and S3 bucket
- `references/app-update-workflow.md` — Modify app configuration safely
- `references/app-deletion-workflow.md` — Delete with destructive-action warning and cleanup guidance
