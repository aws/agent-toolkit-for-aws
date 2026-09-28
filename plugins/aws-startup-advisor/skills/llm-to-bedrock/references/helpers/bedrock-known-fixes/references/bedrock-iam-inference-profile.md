# Fix: bedrock-iam-inference-profile

## Symptom

At runtime, Bedrock invocations fail with:

```
AccessDeniedException: User: <role-arn> is not authorized to perform: bedrock:InvokeModel on resource: arn:aws:bedrock:<region>:<account>:inference-profile/<id>
```

Or, statically: the IAM policy contains only `arn:aws:bedrock:*::foundation-model/*` AND the model ID starts with a region prefix like `us.`, `eu.`, or `apac.` (indicating a cross-region inference profile).

**Root cause**: Cross-region inference profile IDs (prefixed with `us.`) are invoked via inference profile ARNs, not foundation model ARNs. AWS resolves them to account-scoped ARNs like `arn:aws:bedrock:<REGION>:<ACCOUNT_ID>:inference-profile/*`, which does NOT match the foundation-model ARN pattern.

## Fix

### In Terraform (`security.tf`)

Replace the single foundation-model ARN with a two-element resource list that covers both foundation models and inference profiles:

```hcl
# In security.tf — bedrock_access policy
Resource = [
  "arn:aws:bedrock:*::foundation-model/*",
  "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/*"
]
```

The full policy resource:

```hcl
resource "aws_iam_role_policy" "bedrock_access" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/*"
      ]
    }]
  })
}
```

This allows both direct foundation model invocation and cross-region inference profile invocation.

### At runtime (already-deployed cluster)

Update the inline policy via CLI without re-running Terraform:

```bash
ROLE_NAME=$(aws iam list-roles --query 'Roles[?contains(RoleName,`ecs-task`)].RoleName' --output text --region us-east-1 | head -1)
aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name bedrock-access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:us-east-1:<ACCOUNT_ID>:inference-profile/*"
      ]
    }]
  }' --region us-east-1
```

### Anti-pattern

Do NOT use a narrow ARN like `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` — it does not match the inference profile invocation path.

## Verification

```bash
aws iam get-role-policy --role-name <ROLE> --policy-name bedrock-access \
  --query 'PolicyDocument.Statement[0].Resource' --output json
```

Expected: an array containing BOTH `arn:aws:bedrock:*::foundation-model/*` AND `arn:aws:bedrock:<region>:<account>:inference-profile/*`. Re-invoke the model — `AccessDeniedException` is gone.
