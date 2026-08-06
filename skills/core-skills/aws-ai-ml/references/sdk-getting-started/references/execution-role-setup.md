# Execution Role Setup

## Resolve

Auto-detect the execution role by running:

```
python -c "from sagemaker.core.helper.session_helper import get_execution_role; print(get_execution_role())"

```

If it succeeds, store the printed ARN as ROLE_ARN and continue to Validate.

If it fails (user is not authenticated as a role, or credentials are missing), ask the user for their execution role ARN:

> What IAM role should SageMaker use to run jobs? I need the full ARN (e.g., `arn:aws:iam::123456789012:role/MySageMakerRole`). This must be an IAM role (not an IAM user).
>
> If you don't have one yet, see: https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-open-weight-prereq.html

Store the user-provided ARN as ROLE_ARN, continue to Validate.

## Validate

Extract role name from ROLE_ARN and run:

```
aws iam get-role --role-name <ROLE_NAME>

```

- **AccessDenied** → warn: "⚠️ Cannot verify role (missing iam:GetRole). Proceeding with unverified role." Continue.
- **Role found** → check `AssumeRolePolicyDocument` for trust principals:
  - `sagemaker.amazonaws.com` missing → STOP. Tell user their role needs `sagemaker.amazonaws.com` in the trust policy. Link to [the SageMaker model-customization prerequisites documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-open-weight-prereq.html).
  - `bedrock.amazonaws.com` missing → WARN: "Role missing bedrock trust. Bedrock steps may fail."
  - `lambda.amazonaws.com` missing (and plan includes RLVR) → WARN: "Role missing lambda trust. RLVR reward functions will fail."

## Required Permissions

Attach the `AmazonSageMakerModelCustomizationCoreAccess` managed policy to your SageMaker AI execution role. This policy covers the permissions needed for model customization — serverless training, custom reward-function RL, model evaluation, and deployment to SageMaker AI or Bedrock endpoints.

For full setup instructions (including separate scoped-down roles for Lambda and Bedrock), see: https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-open-weight-prereq.html

**S3 caveat:** The managed policy only grants S3 access to buckets with "sagemaker" in the name. If your data is in other buckets, add a supplemental S3 policy.

## Troubleshooting

### "Access denied when attempting to assume role"

The role's trust policy is missing the required service principal. Add `sagemaker.amazonaws.com` to the trust policy.
