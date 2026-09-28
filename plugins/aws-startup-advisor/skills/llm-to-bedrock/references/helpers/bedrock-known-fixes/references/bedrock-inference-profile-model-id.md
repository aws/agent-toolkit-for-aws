# Fix: bedrock-inference-profile-model-id

## Symptom

Bedrock returns:

```
ValidationException: Invocation of model ID <bare-model-id> with on-demand throughput isn't supported. Retry your request with the ID or ARN of an inference profile that contains this model.
```

This affects newer Claude models (Haiku 4.5, Sonnet 4.5+, Opus 4+) and some other vendors' newer models. Bare model IDs like `anthropic.claude-haiku-4-5-20251001-v1:0` cannot be invoked with on-demand throughput directly.

## Fix

### Step 1: Use inference profile prefix in model ID

Replace bare model ID with the cross-region inference profile prefix:

```
anthropic.claude-haiku-4-5-20251001-v1:0  →  us.anthropic.claude-haiku-4-5-20251001-v1:0
```

Update `variables.tf` default:

```hcl
variable "bedrock_model_id" {
  default = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}
```

### Step 2: IAM policy must cover inference profile ARNs

The IAM policy resource must include BOTH foundation-model AND inference-profile ARNs:

```hcl
resource "aws_iam_role_policy" "bedrock_access" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = [
        "arn:aws:bedrock:us-east-1::foundation-model/*",
        "arn:aws:bedrock:us-east-1:<ACCOUNT_ID>:inference-profile/*",
        "arn:aws:bedrock:*::foundation-model/*"
      ]
    }]
  })
}
```

**Do NOT** use a narrow ARN like `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` — it won't match the inference profile invocation.

## Verification

```bash
aws bedrock-runtime invoke-model --model-id us.<model-id> \
  --body '<minimal test payload>' --region <region> /tmp/out.json
```

Expected: returns 200 with a response body (no `ValidationException`).

If you see `AccessDeniedException` instead of `ValidationException` after this fix, you also need `bedrock-iam-inference-profile`.
