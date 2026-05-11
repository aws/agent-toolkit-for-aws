# ATX CLI Reference

## Execution Flags (`atx custom def exec`)

| Flag | Long Form | Description |
|------|-----------|-------------|
| `-n` | `--transformation-name <name>` | TD name (from `atx custom def list --json`) |
| `-p` | `--code-repository-path <path>` | Path to code repo (`.` for current dir) |
| `-x` | `--non-interactive` | No user prompts (always use this flag) |
| `-t` | `--trust-all-tools` | Auto-approve tool executions (required with `-x`) |
| `-d` | `--do-not-learn` | Prevent knowledge item extraction |
| `-g` | `--configuration <config>` | Inline configuration (`'key=val'`) |
| `--tv` | `--transformation-version <ver>` | Specific TD version |

## Configuration

Inline: `--configuration 'additionalPlanContext=Target Python 3.13'`

Example: `atx custom def exec -n my-td -p /source/repo -g 'additionalPlanContext=Target Java 17' -x -t`

`--configuration` is optional. Omit if no extra context needed.

## Other Commands

| Action | Command |
|--------|---------|
| Start interactive conversation | `atx` |
| Resume most recent conversation | `atx --resume` |
| Resume specific conversation | `atx --conversation-id <id>` (30-day limit) |
| List TDs | `atx custom def list --json` |
| Download TD | `atx custom def get -n <name>` (optional: `--tv <version>`, `--td <directory>`) |
| Delete TD | `atx custom def delete -n <name>` |
| Save TD as draft | `atx custom def save-draft -n <name> --description "<desc>" --sd <dir>` |
| Publish TD | `atx custom def publish -n <name> --description "<desc>" --sd <dir>` |
| List knowledge items | `atx custom def list-ki -n <name>` |
| View knowledge item | `atx custom def get-ki -n <name> --id <id>` |
| Enable/disable KI | `atx custom def update-ki-status -n <name> --id <id> --status ENABLED or DISABLED` |
| KI auto-approval on/off | `atx custom def update-ki-config -n <name> --auto-enabled TRUE or FALSE` |
| Export KIs | `atx custom def export-ki-markdown -n <name>` |
| Delete KI | `atx custom def delete-ki -n <name> --id <id>` |
| Update CLI | `atx update` |
| Check for CLI updates only | `atx update --check` |
| Tag a TD | `atx custom def tag --arn <arn> --tags '{"key":"value"}'` |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ATX_SHELL_TIMEOUT` | 900 (15 min) | Shell command timeout in seconds |
| `ATX_DISABLE_UPDATE_CHECK` | false | Disable version check |
| `AWS_PROFILE` | — | AWS credentials profile |
| `AWS_ACCESS_KEY_ID` | — | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | — | AWS secret key |
| `AWS_SESSION_TOKEN` | — | Session token (temporary credentials) |

## IAM Permissions

Minimum: `transform-custom:*` on `Resource: "*"`.

| Permission | Operation |
|-----------|----------|
| `transform-custom:ConverseStream` | Interactive conversations |
| `transform-custom:ExecuteTransformation` | Execute transforms |
| `transform-custom:ListTransformationPackageMetadata` | List transforms (`atx custom def list --json`) |
| `transform-custom:DeleteTransformationPackage` | Delete transforms |
| `transform-custom:CompleteTransformationPackageUpload` | Upload TDs |
| `transform-custom:CreateTransformationPackageUrl` | Create upload URLs |
| `transform-custom:GetTransformationPackageUrl` | Download TDs |
| `transform-custom:ListKnowledgeItems` | List knowledge items |
| `transform-custom:GetKnowledgeItem` | View knowledge item details |
| `transform-custom:DeleteKnowledgeItem` | Delete knowledge items |
| `transform-custom:UpdateKnowledgeItemConfiguration` | Configure auto-approval |
| `transform-custom:UpdateKnowledgeItemStatus` | Enable/disable items |
| `transform-custom:ListTagsForResource` | List tags |
| `transform-custom:TagResource` | Add tags |
| `transform-custom:UntagResource` | Remove tags |

### Remote Mode Caller Permissions

The caller's AWS credentials (the user or role running the session) need additional
permissions beyond `transform-custom:*` for remote mode. Generate the policies,
then create and attach them:

```bash
ATX_INFRA_DIR="$HOME/.aws/atx/custom/remote-infra"
if [ -d "$ATX_INFRA_DIR" ]; then
  git -C "$ATX_INFRA_DIR" add -A
  git -C "$ATX_INFRA_DIR" commit -m "Local customizations" -q 2>/dev/null || true
  git -C "$ATX_INFRA_DIR" pull -q
else
  git clone -b atx-remote-infra --single-branch https://github.com/aws-samples/aws-transform-custom-samples.git "$ATX_INFRA_DIR"
fi
cd "$ATX_INFRA_DIR"
npx ts-node generate-caller-policy.ts
```

This produces two policies:

| Policy | Purpose | When Needed |
|--------|---------|-------------|
| `atx-runtime-policy.json` | Invoke Lambdas, S3 upload/download, KMS, Secrets Manager, CloudWatch logs | Day-to-day remote operations |
| `atx-deployment-policy.json` | CloudFormation, ECR, IAM roles, Batch, VPC, KMS key creation | One-time CDK deploy/destroy |

After generating, create and attach the runtime policy:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)

# Create the managed policy (ignore EntityAlreadyExists, fail on other errors)
if ! create_output=$(aws iam create-policy --policy-name ATXRuntimePolicy \
  --policy-document "file://$ATX_INFRA_DIR/atx-runtime-policy.json" 2>&1); then
  echo "$create_output" | grep -q "EntityAlreadyExists" \
    || { echo "Failed to create policy: $create_output" >&2; exit 1; }
fi

if echo "$CALLER_ARN" | grep -q ":user/"; then
  IDENTITY_NAME=$(echo "$CALLER_ARN" | awk -F'/' '{print $NF}')
  aws iam attach-user-policy --user-name "$IDENTITY_NAME" \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/ATXRuntimePolicy"
elif echo "$CALLER_ARN" | grep -Eq ":assumed-role/|:role/"; then
  ROLE_NAME=$(echo "$CALLER_ARN" | sed 's/.*:\(assumed-\)\{0,1\}role\///' | cut -d'/' -f1)
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/ATXRuntimePolicy"
fi
```

The runtime policy covers: `transform-custom:*` for ATX CLI operations (TD discovery, execution),
`lambda:InvokeFunction` on all `atx-*` functions,
`s3:PutObject`/`s3:GetObject` on source and output buckets, `kms:Encrypt`/`kms:Decrypt`/`kms:GenerateDataKey`
on the ATX encryption key, `secretsmanager:CreateSecret`/`PutSecretValue`/`DeleteSecret` on `atx/*` secrets,
`logs:GetLogEvents`/`FilterLogEvents` on the Batch log group, and `cloudformation:DescribeStacks`
for infrastructure status checks.
