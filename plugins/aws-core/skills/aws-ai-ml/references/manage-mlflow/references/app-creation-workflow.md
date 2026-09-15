# App Creation Workflow

Creates a SageMaker Managed MLflow app using a user-provided or discovered IAM role and S3 bucket.

> **IMPORTANT:** Use only `sagemaker:CreateMlflowApp` (Mercury/serverless). Do NOT use `CreateMlflowTrackingServer` (legacy Aloy/serverful) — that API is deprecated for new deployments.

## Step 1: Ask User Preference for IAM Role and S3 Bucket

Before searching, ask the user:

> "To create an MLflow app, I need an IAM role and an S3 bucket. Would you like to:
>
> 1. Provide the ARN/name directly
> 2. Have me search your account for existing ones"

### If user provides directly:

- Accept the IAM role ARN and S3 bucket name as-is
- Proceed to Step 2

### If user wants agent to search:

**IAM Role discovery:**

- Use `aws-mcp` to call `iam:ListRoles` and look for roles with `sagemaker.amazonaws.com` in the trust policy
- If a role from `sdk-getting-started` skill is already in conversation context, suggest reusing it
- If multiple candidates found, present them and ask user to choose

**S3 Bucket discovery:**

- Use `aws-mcp` to call `s3:ListBuckets`
- If a bucket contains "sagemaker" or "mlflow" in the name, suggest it
- Check bucket is in the same region as where the MLflow app will be created

### If no suitable resources found:

**No IAM role:**

- Inform user: "No suitable IAM role found. You need a role with SageMaker as a trusted service and S3 permissions."
- Link to documentation: [MLflow App IAM Prerequisites](https://docs.aws.amazon.com/sagemaker/latest/dg/mlflow-app-setup-prerequisites-iam.html)
- Ask user to create the role and provide the ARN

**No S3 bucket:**

- Inform user: "No suitable S3 bucket found in {region}."
- Suggest user creating one with recommended name: `sagemaker-mlflow-{account_id}-{region}` and provide the bucket name

## Step 2: CreateMlflowApp

Before calling, confirm with user: "I'll create an MLflow app named '{name}' in {region} using role {role_arn} and bucket {bucket}. Proceed?"

Use `aws-mcp` to call `sagemaker:CreateMlflowApp` with:

- `Name`: user-provided, or auto-suggest as `mlflow-app-{YYYYMMDD-HHMMSS}`
- `ArtifactStoreUri`: `s3://{bucket_name}/mlflow-artifacts`
- `RoleArn`: the role from Step 1

For optional parameters (ModelRegistrationMode, AccountDefaultStatus, etc.), use `aws-mcp` to discover what the API accepts at runtime rather than hardcoding values.

## Step 3: Poll until ACTIVE

Use `aws-mcp` to call `sagemaker:DescribeMlflowApp` in a loop (every 15 seconds):

- Expected progression: `CREATING` → `ACTIVE`
- Timeout: 10 minutes
- If `FAILED`: surface the failure reason, suggest checking IAM role trust policy and S3 bucket configuration
- If timeout: warn user, suggest checking Console

## Error Handling

| Error | Resolution |
|---|---|
| `AccessDeniedException` on CreateMlflowApp | "You need `sagemaker:CreateMlflowApp` permission." |
| `ResourceLimitExceeded` | "Account limit on MLflow apps reached. Delete unused apps or request a quota increase." |
| `ValidationException` on RoleArn | "The IAM role is not valid for MLflow. Check trust policy includes sagemaker.amazonaws.com. See: [IAM prereqs doc](https://docs.aws.amazon.com/sagemaker/latest/dg/mlflow-app-setup-prerequisites-iam.html)" |
| `ValidationException` on ArtifactStoreUri | "The S3 bucket is not accessible. Verify bucket exists, is in {region}, and role has access." |
