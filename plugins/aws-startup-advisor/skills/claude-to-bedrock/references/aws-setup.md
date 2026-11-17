# AWS one-time setup for Claude 3P on Bedrock

Performed once per AWS org by an admin. HUMAN STEP — done in the AWS Console.

## 1. Enable Claude models in Amazon Bedrock

**Agent first (read-only):** check whether the account already submitted the
form with `aws bedrock get-use-case-for-model-access` (see
`terminal-helpers.md`). If it did, skip the form. If not, open the Model
catalog for the person and give the prompt below.

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

### 2b. Optional: create it from the CLI (admin; ask first)

Only for Route B, and only after a **separate, explicit yes** for this step:
it gives a whole group permission to call Bedrock in an AWS account, which the
CONFIRM notice never covers. Rules:

- Run it from the Identity Center management account or its delegated
  administrator, with a role that can manage Identity Center. Never switch to a
  more powerful role than the one the person gave you without asking.
- Prefer a test or sandbox account first. Treat any account you can't confirm
  as non-production as production.
- Run the preflight block, show the person its output and every command below
  with the values filled in, and have them **retype the Bedrock account ID**
  before you run anything that writes.
- Write `bedrock-policy.json` yourself from the policy in section 2, in a new
  temp folder, and show it.

Preflight (read-only):

```bash
set -euo pipefail
REGION="<identity-center-region>"; ACCOUNT="<bedrock-account-id>"; GROUP="<group display name>"
aws sts get-caller-identity --query '[Account,Arn]' --output text
read -r INSTANCE_ARN STORE_ID < <(aws sso-admin list-instances --region "$REGION" \
  --query 'Instances[0].[InstanceArn,IdentityStoreId]' --output text)
case "$INSTANCE_ARN" in arn:*) ;; *) echo "No Identity Center instance in $REGION"; exit 1;; esac
case "$GROUP" in *'"'*) echo "Group names with double quotes aren't supported here"; exit 1;; esac
GROUP_ID=$(aws identitystore get-group-id --region "$REGION" --identity-store-id "$STORE_ID" \
  --alternate-identifier "{\"UniqueAttribute\":{\"AttributePath\":\"displayName\",\"AttributeValue\":\"$GROUP\"}}" \
  --query GroupId --output text)
for ps in $(aws sso-admin list-permission-sets --region "$REGION" --instance-arn "$INSTANCE_ARN" \
  --query 'PermissionSets[]' --output text); do
  aws sso-admin describe-permission-set --region "$REGION" --instance-arn "$INSTANCE_ARN" \
    --permission-set-arn "$ps" --query 'PermissionSet.Name' --output text
done | grep -qx ClaudeBedrockInference && { echo "ClaudeBedrockInference already exists; stop and ask"; exit 1; }
echo "Instance: $INSTANCE_ARN  Group: $GROUP ($GROUP_ID)  Target account: $ACCOUNT"
```

Create and assign (only after the retyped account ID matches `$ACCOUNT`):

```bash
PS_ARN=$(aws sso-admin create-permission-set --region "$REGION" \
  --instance-arn "$INSTANCE_ARN" --name ClaudeBedrockInference \
  --description "Claude Desktop and Claude Code on Amazon Bedrock" \
  --session-duration PT12H --query 'PermissionSet.PermissionSetArn' --output text)
aws sso-admin put-inline-policy-to-permission-set --region "$REGION" \
  --instance-arn "$INSTANCE_ARN" --permission-set-arn "$PS_ARN" \
  --inline-policy file://bedrock-policy.json
aws sso-admin create-account-assignment --region "$REGION" \
  --instance-arn "$INSTANCE_ARN" --permission-set-arn "$PS_ARN" \
  --principal-type GROUP --principal-id "$GROUP_ID" \
  --target-type AWS_ACCOUNT --target-id "$ACCOUNT" \
  --query 'AccountAssignmentCreationStatus.RequestId' --output text
```

Check the request ID with `aws sso-admin
describe-account-assignment-creation-status --instance-arn "$INSTANCE_ARN"
--account-assignment-creation-request-id <id>`. A new assignment provisions the
permission set itself. If you change the inline policy later, run
`aws sso-admin provision-permission-set --instance-arn "$INSTANCE_ARN"
--permission-set-arn "$PS_ARN" --target-type ALL_PROVISIONED_ACCOUNTS` so the
change reaches the account. The permission set name (`ClaudeBedrockInference`)
is the `inferenceBedrockSsoRoleName` / `sso_role_name` value for device
configuration.

Undo (also ask first):

```bash
aws sso-admin delete-account-assignment --region "$REGION" \
  --instance-arn "$INSTANCE_ARN" --permission-set-arn "$PS_ARN" \
  --principal-type GROUP --principal-id "$GROUP_ID" \
  --target-type AWS_ACCOUNT --target-id "$ACCOUNT"
# after the deletion request completes:
aws sso-admin delete-permission-set --region "$REGION" \
  --instance-arn "$INSTANCE_ARN" --permission-set-arn "$PS_ARN"
```

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
