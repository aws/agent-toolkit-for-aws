# AWS one-time setup for Claude 3P on Bedrock

Performed once per AWS org by an admin. HUMAN STEP — done in the AWS Console.

## 1. Enable Claude models in Amazon Bedrock

- AWS Console → **Amazon Bedrock → Model catalog** → open an Anthropic model
  (e.g. Claude Sonnet 5.5, Opus 5.5, Haiku 5.5) → complete the **use case
  form**. You do this once per AWS account, and access is granted right after
  you submit.
- AWS Organizations: submit once from the management account with the
  `PutUseCaseForModelAccess` API (needs `bedrock:PutUseCaseForModelAccess`);
  approval extends to member accounts.
- The first invocation also subscribes the account to the model through AWS
  Marketplace, which is why the policy below includes the Marketplace actions.
- Pick a region where the inference profiles you want exist, and use it as
  `inferenceBedrockRegion` / `AWS_REGION`.

Record the **inference-profile IDs** you want, e.g.:

```
us.anthropic.claude-sonnet-5-5
us.anthropic.claude-opus-5-5
us.anthropic.claude-haiku-5-5
```

List them with:

```bash
aws bedrock list-inference-profiles --region <region> \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'anthropic')].inferenceProfileId"
```

## 2. (Fleet / in-app AWS sign-in) Create an IAM Identity Center permission set
Skip for bearer-token or IdP auth. For named-profile and in-app AWS sign-in:

- IAM Identity Center → create a **permission set** with inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowModelAndInferenceProfileAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListInferenceProfiles",
        "bedrock:GetInferenceProfile"
      ],
      "Resource": [
        "arn:aws:bedrock:*:*:inference-profile/*",
        "arn:aws:bedrock:*:*:application-inference-profile/*",
        "arn:aws:bedrock:*:*:foundation-model/*"
      ]
    },
    {
      "Sid": "AllowMarketplaceSubscription",
      "Effect": "Allow",
      "Action": ["aws-marketplace:ViewSubscriptions", "aws-marketplace:Subscribe"],
      "Resource": "*",
      "Condition": {"StringEquals": {"aws:CalledViaLast": "bedrock.amazonaws.com"}}
    }
  ]
}
```

- `ListInferenceProfiles` lets Claude Code discover the inference profiles in
  the account (without it, it applies the region prefix unchecked).
  `GetInferenceProfile` resolves application inference profile ARNs (without
  it, requests still work but retry once per new model). To lock down further, replace the
  `Resource` wildcards with your specific inference profile ARNs.
- Set **Session duration** 8–12h.
- (Optional) Federate Identity Center to your IdP (Entra ID / Okta) so users
  sign in with corporate credentials.
- Assign the permission set to the Bedrock account + the users/groups.

## 3. Record values for device configuration
From IAM Identity Center → Settings:

- **AWS access portal URL**: `https://d-xxxxxxxxxx.awsapps.com/start`
- **Identity Center region** (may differ from Bedrock region)
- **AWS account ID** (12-digit, hosts Bedrock)
- **Permission set name**

These map to the desktop managed-config keys:
`inferenceBedrockSsoStartUrl`, `inferenceBedrockSsoRegion`,
`inferenceBedrockSsoAccountId`, `inferenceBedrockSsoRoleName`.

## 4. Single-user alternatives (no Identity Center)

- **Named profile:** a working `~/.aws` profile with the policy from section 2
  (SSO, `credential_process`, or static). Desktop key: `inferenceBedrockProfile`.
- **Bearer token:** Bedrock console → API keys → generate (underlying principal
  must allow `bedrock:CallWithBearerToken`). Or short-term token:

  ```bash
  pip install aws-bedrock-token-generator
  python -c "from aws_bedrock_token_generator import provide_token; print(provide_token(region='us-east-1'))"
  ```

  Desktop key: `inferenceBedrockBearerToken`; CLI env: `AWS_BEARER_TOKEN_BEDROCK`.
