> **Credentials MUST be ephemeral-first.** Prefer, in order: (1) IAM Identity
> Center / SSO, then (2) `aws sts assume-role` session credentials (which include
> `AWS_SESSION_TOKEN`). Do NOT ask the seller to provide, paste, or export long-lived IAM
> **user** access keys, and do NOT ask for credentials outright as a first step — have the
> seller configure one of the ephemeral paths in their own environment. **Never log or echo
> credential values.**

#### Option A: IAM Identity Center (SSO) — recommended, default

```bash
aws configure sso
aws sso login
# or a named SSO profile
export AWS_PROFILE=marketplace-seller
```

#### Option B: STS assume-role (ephemeral session credentials)

Create a dedicated deployer role (see policy below) and assume it — the session includes
`AWS_SESSION_TOKEN` and expires automatically:

```bash
aws sts assume-role \
  --role-arn arn:aws:iam::<ACCOUNT_ID>:role/MarketplaceMeteringDeployer \
  --role-session-name mp-metering-setup
# export the returned AccessKeyId / SecretAccessKey / SessionToken
```

#### Option C (last resort only): short-lived environment-variable credentials

```bash
# ⚠️ LAST RESORT — prefer SSO (A) or sts assume-role (B) above.
# Use ONLY short-lived STS session credentials (with AWS_SESSION_TOKEN), never
# long-lived IAM user access keys. If credentials must be stored, use AWS Secrets
# Manager or SSM Parameter Store — never plaintext files or source control.
export AWS_ACCESS_KEY_ID=<temporary-key>
export AWS_SECRET_ACCESS_KEY=<temporary-secret>
export AWS_SESSION_TOKEN=<session-token>   # REQUIRED — do not use keys without a session token
```

**Verify credentials immediately after configuration:**

```bash
aws sts get-caller-identity
```

Confirm the output shows the correct seller account ID. **Do not proceed until this succeeds.** These same credentials will be used for all subsequent operations: Catalog API validation, stack deployment, and integration testing.

#### Required IAM Permissions

If the seller asks "what permissions do I need?", provide the policy below. Otherwise, proceed with whatever credentials they provide — if a permission is missing, the error will indicate exactly which action is needed.

<details>
<summary>Click to expand: Full IAM policy for MarketplaceMeteringDeployer role</summary>

> **Tag-authorization principle (why the policy is split into Create / Manage / Read buckets):** Tags supplied at creation are authorized with `aws:RequestTag`, **never** `aws:ResourceTag` — on a create the resource does not exist yet, so it has no tags and an `aws:ResourceTag/*` condition is always false, denying the create. Services that attach tags/targets/sub-resources in a **separate call after** the parent resource is created — **CloudFormation, API Gateway, EventBridge** — cannot be `aws:ResourceTag`-gated for their create/rollback lifecycle at all (gating them also wedges rollback in `DELETE_FAILED`/`ROLLBACK_FAILED`). Only services CloudFormation tags **atomically at creation** (Lambda, DynamoDB, IAM roles) can keep `aws:ResourceTag/ManagedBy` on their non-create operations. Read actions (`Get*`/`Describe*`/`List*`/`Query`/`Scan`/`apigateway:GET`) are also **never** tag-gated, because CloudFormation issues describe/GET waiters during creation (e.g. `dynamodb:DescribeTable` waiting for `ACTIVE`, `lambda:GetFunction`) against a just-created, not-yet-tagged resource.
>
> Buckets: **Create** — no condition, name-scoped `awsmp-*`. **Manage** — `aws:ResourceTag/ManagedBy` for mutations of existing resources. **Read** — no condition, name-scoped. **Special** — `iam:PassRole` scoped by `iam:PassedToService`; unconditioned `aws-marketplace` catalog read.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "CloudFormationCreate",
            "Effect": "Allow",
            "Action": [
                "cloudformation:CreateStack",
                "cloudformation:DeleteStack",
                "cloudformation:CreateChangeSet",
                "cloudformation:DescribeChangeSet",
                "cloudformation:ExecuteChangeSet",
                "cloudformation:DeleteChangeSet",
                "cloudformation:ListChangeSets",
                "cloudformation:DescribeStacks",
                "cloudformation:DescribeStackEvents",
                "cloudformation:GetTemplate",
                "cloudformation:GetTemplateSummary",
                "cloudformation:ListStackResources"
            ],
            "Resource": "arn:aws:cloudformation:*:*:stack/awsmp-*/*"
        },
        {
            "Sid": "CloudFormationServerlessTransform",
            "Effect": "Allow",
            "Action": [
                "cloudformation:CreateChangeSet"
            ],
            "Resource": "arn:aws:cloudformation:*:aws:transform/Serverless-2016-10-31"
        },
        {
            "Sid": "CloudFormationManage",
            "Effect": "Allow",
            "Action": [
                "cloudformation:UpdateStack",
                "cloudformation:DeleteStack"
            ],
            "Resource": "arn:aws:cloudformation:*:*:stack/awsmp-*/*",
            "Condition": {
                "StringEquals": {
                    "aws:ResourceTag/ManagedBy": "marketplace-metering-skill"
                }
            }
        },
        {
            "Sid": "CloudFormationEventsStack",
            "Effect": "Allow",
            "Action": [
                "cloudformation:CreateStack",
                "cloudformation:UpdateStack",
                "cloudformation:DeleteStack",
                "cloudformation:DescribeStacks",
                "cloudformation:DescribeStackEvents",
                "cloudformation:GetTemplate",
                "cloudformation:ListStackResources",
                "cloudformation:GetTemplateSummary",
                "cloudformation:CreateChangeSet",
                "cloudformation:DescribeChangeSet",
                "cloudformation:ExecuteChangeSet",
                "cloudformation:DeleteChangeSet"
            ],
            "Resource": "arn:aws:cloudformation:*:*:stack/awsmp-events-stack/*"
        },
        {
            "Sid": "S3DeploymentArtifacts",
            "Effect": "Allow",
            "Action": [
                "s3:CreateBucket",
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:PutBucketPolicy",
                "s3:PutBucketVersioning",
                "s3:GetBucketLocation",
                "s3:PutEncryptionConfiguration",
                "s3:GetEncryptionConfiguration",
                "s3:PutBucketTagging"
            ],
            "Resource": [
                "arn:aws:s3:::aws-sam-cli-managed-default-*",
                "arn:aws:s3:::aws-sam-cli-managed-default-*/*"
            ]
        },
        {
            "Sid": "IAMRolesCreate",
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole"
            ],
            "Resource": "arn:aws:iam::*:role/awsmp-*",
            "Condition": {
                "StringLike": {
                    "iam:PermissionsBoundary": "arn:aws:iam::*:policy/awsmp-metering-boundary"
                }
            }
        },
        {
            "Sid": "IAMRolesManage",
            "Effect": "Allow",
            "Action": [
                "iam:DeleteRole",
                "iam:PutRolePolicy",
                "iam:DeleteRolePolicy",
                "iam:AttachRolePolicy",
                "iam:DetachRolePolicy",
                "iam:TagRole",
                "iam:UntagRole"
            ],
            "Resource": "arn:aws:iam::*:role/awsmp-*",
            "Condition": {
                "StringEquals": {
                    "aws:ResourceTag/ManagedBy": "marketplace-metering-skill"
                }
            }
        },
        {
            "Sid": "IAMPassRoleScoped",
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": "arn:aws:iam::*:role/awsmp-*",
            "Condition": {
                "StringEquals": {
                    "iam:PassedToService": [
                        "lambda.amazonaws.com",
                        "events.amazonaws.com"
                    ]
                }
            }
        },
        {
            "Sid": "LambdaCreate",
            "Effect": "Allow",
            "Action": [
                "lambda:CreateFunction",
                "lambda:PutFunctionConcurrency"
            ],
            "Resource": "arn:aws:lambda:*:*:function:awsmp-*"
        },
        {
            "Sid": "LambdaManage",
            "Effect": "Allow",
            "Action": [
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:DeleteFunction",
                "lambda:AddPermission",
                "lambda:RemovePermission",
                "lambda:InvokeFunction",
                "lambda:PutFunctionConcurrency",
                "lambda:DeleteFunctionConcurrency",
                "lambda:TagResource",
                "lambda:UntagResource"
            ],
            "Resource": "arn:aws:lambda:*:*:function:awsmp-*",
            "Condition": {
                "StringEquals": {
                    "aws:ResourceTag/ManagedBy": "marketplace-metering-skill"
                }
            }
        },
        {
            "Sid": "DynamoDBCreate",
            "Effect": "Allow",
            "Action": [
                "dynamodb:CreateTable"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/awsmp-*"
        },
        {
            "Sid": "DynamoDBManage",
            "Effect": "Allow",
            "Action": [
                "dynamodb:DeleteTable",
                "dynamodb:UpdateTable",
                "dynamodb:UpdateContinuousBackups",
                "dynamodb:UpdateTimeToLive",
                "dynamodb:TagResource",
                "dynamodb:UntagResource",
                "dynamodb:PutItem"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/awsmp-*",
            "Condition": {
                "StringEquals": {
                    "aws:ResourceTag/ManagedBy": "marketplace-metering-skill"
                }
            }
        },
        {
            "Sid": "SQSCreate",
            "Effect": "Allow",
            "Action": [
                "sqs:CreateQueue"
            ],
            "Resource": "arn:aws:sqs:*:*:awsmp-*"
        },
        {
            "Sid": "SQSManage",
            "Effect": "Allow",
            "Action": [
                "sqs:DeleteQueue",
                "sqs:SetQueueAttributes",
                "sqs:SendMessage",
                "sqs:TagQueue",
                "sqs:UntagQueue"
            ],
            "Resource": "arn:aws:sqs:*:*:awsmp-*",
            "Condition": {
                "StringEquals": {
                    "aws:ResourceTag/ManagedBy": "marketplace-metering-skill"
                }
            }
        },
        {
            "Sid": "SNSCreate",
            "Effect": "Allow",
            "Action": [
                "sns:CreateTopic"
            ],
            "Resource": "arn:aws:sns:*:*:awsmp-*"
        },
        {
            "Sid": "SNSManage",
            "Effect": "Allow",
            "Action": [
                "sns:DeleteTopic",
                "sns:Subscribe",
                "sns:TagResource",
                "sns:UntagResource"
            ],
            "Resource": "arn:aws:sns:*:*:awsmp-*",
            "Condition": {
                "StringEquals": {
                    "aws:ResourceTag/ManagedBy": "marketplace-metering-skill"
                }
            }
        },
        {
            "Sid": "ApiGatewayCreate",
            "Effect": "Allow",
            "Action": [
                "apigateway:POST",
                "apigateway:PUT",
                "apigateway:PATCH",
                "apigateway:DELETE",
                "apigateway:SetWebACL"
            ],
            "Resource": [
                "arn:aws:apigateway:*::/restapis*",
                "arn:aws:apigateway:*::/tags/*"
            ]
        },
        {
            "Sid": "WafV2BaselineWebAcl",
            "Effect": "Allow",
            "Action": [
                "wafv2:CreateWebACL",
                "wafv2:GetWebACL",
                "wafv2:UpdateWebACL",
                "wafv2:AssociateWebACL",
                "wafv2:DisassociateWebACL",
                "wafv2:DeleteWebACL",
                "wafv2:TagResource",
                "wafv2:ListTagsForResource"
            ],
            "Resource": [
                "arn:aws:wafv2:*:*:regional/webacl/awsmp-*/*",
                "arn:aws:wafv2:*:*:regional/managedruleset/*/*"
            ]
        },
        {
            "Sid": "WafV2GetWebAclForResource",
            "Effect": "Allow",
            "Action": [
                "wafv2:GetWebACLForResource"
            ],
            "Resource": "arn:aws:wafv2:*:*:regional/webacl/*"
        },
        {
            "Sid": "ApiGatewayAccountCloudWatchRole",
            "Effect": "Allow",
            "Action": [
                "apigateway:GET",
                "apigateway:PATCH"
            ],
            "Resource": "arn:aws:apigateway:*::/account"
        },
        {
            "Sid": "CreateApiGatewayCloudWatchLogsRole",
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole",
                "iam:GetRole",
                "iam:DetachRolePolicy",
                "iam:DeleteRole",
                "iam:TagRole"
            ],
            "Resource": "arn:aws:iam::*:role/awsmp-apigw-cloudwatch-logs"
        },
        {
            "Sid": "AttachApiGatewayCloudWatchLogsPolicy",
            "Effect": "Allow",
            "Action": "iam:AttachRolePolicy",
            "Resource": "arn:aws:iam::*:role/awsmp-apigw-cloudwatch-logs",
            "Condition": {
                "ArnEquals": {
                    "iam:PolicyARN": "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
                }
            }
        },
        {
            "Sid": "PassApiGatewayCloudWatchLogsRole",
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": "arn:aws:iam::*:role/awsmp-apigw-cloudwatch-logs",
            "Condition": {
                "StringEquals": {
                    "iam:PassedToService": "apigateway.amazonaws.com"
                }
            }
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:DeleteLogGroup",
                "logs:DescribeLogGroups",
                "logs:PutRetentionPolicy",
                "logs:TagLogGroup",
                "logs:TagResource",
                "logs:FilterLogEvents",
                "logs:GetLogEvents",
                "logs:DescribeLogStreams"
            ],
            "Resource": [
                "arn:aws:logs:*:*:log-group:/aws/lambda/awsmp-*",
                "arn:aws:logs:*:*:log-group:/aws/lambda/awsmp-*:*",
                "arn:aws:logs:*:*:log-group:/aws/apigateway/awsmp-*",
                "arn:aws:logs:*:*:log-group:/aws/apigateway/awsmp-*:*"
            ]
        },
        {
            "Sid": "LogsDescribeGlobal",
            "Effect": "Allow",
            "Action": [
                "logs:DescribeLogGroups"
            ],
            "Resource": "*"
        },
        {
            "Sid": "ObservabilityReadOnly",
            "Effect": "Allow",
            "Action": [
                "cloudtrail:LookupEvents",
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:GetMetricData",
                "cloudwatch:ListDashboards",
                "events:ListRuleNamesByTarget"
            ],
            "Resource": "*"
        },
        {
            "Sid": "CloudWatchAlarms",
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricAlarm",
                "cloudwatch:DescribeAlarms",
                "cloudwatch:DeleteAlarms",
                "cloudwatch:TagResource"
            ],
            "Resource": "arn:aws:cloudwatch:*:*:alarm:awsmp-*"
        },
        {
            "Sid": "CloudWatchDashboards",
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutDashboard",
                "cloudwatch:GetDashboard",
                "cloudwatch:DeleteDashboards"
            ],
            "Resource": "arn:aws:cloudwatch::*:dashboard/awsmp-*"
        },
        {
            "Sid": "SNSReadOnly",
            "Effect": "Allow",
            "Action": [
                "sns:GetTopicAttributes",
                "sns:ListTagsForResource"
            ],
            "Resource": "arn:aws:sns:*:*:awsmp-*"
        },
        {
            "Sid": "LambdaEventSourceMappingReadOnly",
            "Effect": "Allow",
            "Action": [
                "lambda:GetEventSourceMapping",
                "lambda:ListEventSourceMappings"
            ],
            "Resource": "*"
        },
        {
            "Sid": "LambdaEventSourceMapping",
            "Effect": "Allow",
            "Action": [
                "lambda:CreateEventSourceMapping",
                "lambda:UpdateEventSourceMapping",
                "lambda:DeleteEventSourceMapping"
            ],
            "Resource": "*",
            "Condition": {
                "ArnLike": {
                    "lambda:FunctionArn": "arn:aws:lambda:*:*:function:awsmp-*"
                }
            }
        },
        {
            "Sid": "MarketplaceCatalogReadOnly",
            "Effect": "Allow",
            "Action": [
                "aws-marketplace:DescribeEntity",
                "aws-marketplace:ListEntities"
            ],
            "Resource": "*"
        },
        {
            "Sid": "EventBridgeLifecycle",
            "Effect": "Allow",
            "Action": [
                "events:PutRule",
                "events:DeleteRule",
                "events:PutTargets",
                "events:RemoveTargets",
                "events:TagResource",
                "events:UntagResource"
            ],
            "Resource": "arn:aws:events:*:*:rule/awsmp-*"
        },
        {
            "Sid": "BoundaryPolicyRead",
            "Effect": "Allow",
            "Action": [
                "iam:GetPolicy"
            ],
            "Resource": "arn:aws:iam::*:policy/awsmp-metering-boundary"
        },
        {
            "Sid": "ServiceReadOnly",
            "Effect": "Allow",
            "Action": [
                "apigateway:GET",
                "dynamodb:DescribeContinuousBackups",
                "dynamodb:DescribeTable",
                "dynamodb:DescribeTimeToLive",
                "dynamodb:GetItem",
                "dynamodb:ListTagsOfResource",
                "dynamodb:Query",
                "events:DescribeRule",
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:ListRoleTags",
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
                "lambda:ListTags",
                "sqs:GetQueueAttributes",
                "sqs:ListQueueTags"
            ],
            "Resource": [
                "arn:aws:lambda:*:*:function:awsmp-*",
                "arn:aws:dynamodb:*:*:table/awsmp-*",
                "arn:aws:dynamodb:*:*:table/awsmp-*/index/*",
                "arn:aws:sqs:*:*:awsmp-*",
                "arn:aws:events:*:*:rule/awsmp-*",
                "arn:aws:iam::*:role/awsmp-*",
                "arn:aws:apigateway:*::/restapis*",
                "arn:aws:apigateway:*::/tags/*"
            ]
        },
        {
            "Sid": "CloudFormationListStacks",
            "Effect": "Allow",
            "Action": [
                "cloudformation:ListStacks"
            ],
            "Resource": "*"
        }
    ]
}
```

</details>

To create this role, the seller can run the following. **The trust policy MUST be
conditioned** — an unconditioned `Principal: {"AWS": "...:root"}` lets ANY
principal in the account assume the deployer. The DEFAULT below targets a **headless-agent
caller**: a named role-ARN principal + an `sts:ExternalId` condition, and **no MFA** (a
headless agent cannot satisfy MFA). For a **human operator** you MAY additionally require
MFA (`"Bool": {"aws:MultiFactorAuthPresent": "true"}`) — that is a human-only variant, not
the default. This role is commonly assumed **cross-account** (the caller's account assuming
into the seller's account); in that case the caller's own principal ALSO needs an
`sts:AssumeRole` grant on this role ARN (both sides), in addition to the trust policy below.
First create the permissions boundary the `iam:CreateRole` statement requires:

```bash
# 1. Create the permissions boundary as a MANAGED policy (a boundary MUST be managed,
#    never an inline put-role-policy). This caps what any awsmp-* role can do.
aws iam create-policy --policy-name awsmp-metering-boundary \
  --policy-document file://boundary.json

# 2. Create the deployer role with a CONDITIONED trust policy (NOT open :root).
#    DEFAULT = headless agent: role-ARN principal + sts:ExternalId, NO MFA.
aws iam create-role --role-name MarketplaceMeteringDeployer --assume-role-policy-document '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<CALLER_ACCOUNT_ID>:role/<AGENT_CALLER_ROLE>"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"sts:ExternalId": "<CHOOSE_A_SECRET_EXTERNAL_ID>"}
    }
  }]
}'
# (Human-operator variant only: add "Bool": {"aws:MultiFactorAuthPresent": "true"} to Condition.)
aws iam put-role-policy --role-name MarketplaceMeteringDeployer --policy-name DeployPolicy --policy-document file://policy.json
```

> **Permissions boundary — REQUIRED before deployment, and the names MUST match.**
> The deployer policy's `iam:CreateRole` is gated on
> `iam:PermissionsBoundary = arn:aws:iam::*:policy/awsmp-metering-boundary`. IAM only
> populates the `iam:PermissionsBoundary` request key when a boundary is actually attached,
> so **any `awsmp-*` role created without that exact boundary is denied with AccessDenied.**
> SAM auto-generates the Register/Meter/Subscription Lambda execution roles from the inline
> `Policies` in the templates, so the templates set
> `Globals.Function.PermissionsBoundary: arn:aws:iam::${AWS::AccountId}:policy/${PermissionsBoundaryName}`
> (parameter `PermissionsBoundaryName`, default `awsmp-metering-boundary`) on those
> generated roles. The boundary policy MUST already exist in the account before you run
> `deploy.sh`, and its name MUST equal both the deployer condition and the
> `PermissionsBoundaryName` parameter. If you rename it, update all three.
>
> A boundary that caps the generated Lambda roles to exactly what this skill's Lambdas use
> (`boundary.json`):
>
> ```json
> {
>     "Version": "2012-10-17",
>     "Statement": [
>         {
>             "Sid": "MarketplaceMeteringRuntime",
>             "Effect": "Allow",
>             "Action": [
>                 "aws-marketplace:BatchMeterUsage",
>                 "aws-marketplace:ResolveCustomer"
>             ],
>             "Resource": "*"
>         },
>         {
>             "Sid": "DynamoDBRuntime",
>             "Effect": "Allow",
>             "Action": [
>                 "dynamodb:GetItem",
>                 "dynamodb:PutItem",
>                 "dynamodb:UpdateItem",
>                 "dynamodb:Query"
>             ],
>             "Resource": [
>                 "arn:aws:dynamodb:*:*:table/awsmp-*",
>                 "arn:aws:dynamodb:*:*:table/awsmp-*/index/*"
>             ]
>         },
>         {
>             "Sid": "SqsRuntime",
>             "Effect": "Allow",
>             "Action": [
>                 "sqs:SendMessage",
>                 "sqs:ReceiveMessage",
>                 "sqs:DeleteMessage",
>                 "sqs:GetQueueAttributes"
>             ],
>             "Resource": "arn:aws:sqs:*:*:awsmp-*"
>         },
>         {
>             "Sid": "SnsRuntime",
>             "Effect": "Allow",
>             "Action": [
>                 "sns:Publish"
>             ],
>             "Resource": "arn:aws:sns:*:*:awsmp-*"
>         },
>         {
>             "Sid": "LogsRuntime",
>             "Effect": "Allow",
>             "Action": [
>                 "logs:CreateLogGroup",
>                 "logs:CreateLogStream",
>                 "logs:PutLogEvents"
>             ],
>             "Resource": "arn:aws:logs:*:*:log-group:/aws/lambda/awsmp-*:*"
>         },
>         {
>             "Sid": "KmsRuntime",
>             "Effect": "Allow",
>             "Action": [
>                 "kms:Decrypt",
>                 "kms:GenerateDataKey"
>             ],
>             "Resource": "*",
>             "Condition": {
>                 "StringLike": {
>                     "kms:ViaService": [
>                         "dynamodb.*.amazonaws.com",
>                         "sqs.*.amazonaws.com",
>                         "sns.*.amazonaws.com"
>                     ]
>                 }
>             }
>         }
>     ]
> }
> ```
>
> Note: the boundary does NOT grant permissions — it caps them. The role's own inline
> policy still governs effective access; the boundary just ensures a self-created `awsmp-*`
> role can never exceed this action set. Each statement is also resource-scoped to
> `awsmp-*` (DynamoDB tables + their indexes, SQS queues, SNS topics, and the
> `/aws/lambda/awsmp-*` log groups), and `kms:Decrypt`/`kms:GenerateDataKey` are constrained
> by a `kms:ViaService` condition so keys can only be used through DynamoDB, SQS, and SNS. It
> deliberately omits `dynamodb:Scan`, `dynamodb:DeleteItem`, and any `iam:*`, so a boundary'd
> role cannot broaden its own DynamoDB access or escalate via IAM.
>
> **Important:** Do NOT use an admin role. Create a dedicated role with only the permissions above. Using admin credentials violates least-privilege and poses a security risk if the agent environment is compromised.
>
> **Key Facts — Dimension Validation (ALWAYS mention when asked about new dimensions):**
>
> - Call `aws marketplace-catalog describe-entity --entity-id <ProductId> --catalog AWSMarketplace`
> - Check that dimension appears with `ExternallyMetered` type — case-sensitive match required
> - If the dimension is not a defined pricing dimension for the product, BatchMeterUsage REJECTS the record with InvalidUsageDimensionException (not billed)
> - Verify dimension keys against the Catalog API BEFORE deploying the metering Lambda
