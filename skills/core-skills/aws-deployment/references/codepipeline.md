# CodePipeline V2

## Creating a V2 Pipeline

**Default: V2 pipeline type with QUEUED execution mode.**

```
aws codepipeline create-pipeline --pipeline '{
  "name": "my-app-pipeline",
  "pipelineType": "V2",
  "executionMode": "QUEUED",
  "roleArn": "arn:aws:iam::ACCOUNT_ID:role/pipeline-service-role",
  "artifactStore": {
    "type": "S3",
    "location": "my-pipeline-artifacts-bucket",
    "encryptionKey": {
      "id": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID",
      "type": "KMS"
    }
  },
  "stages": [
    {
      "name": "Source",
      "actions": [{
        "name": "Source",
        "actionTypeId": {
          "category": "Source",
          "owner": "AWS",
          "provider": "CodeStarSourceConnection",
          "version": "1"
        },
        "outputArtifacts": [{"name": "SourceOutput"}],
        "configuration": {
          "ConnectionArn": "arn:aws:codeconnections:REGION:ACCOUNT_ID:connection/CONNECTION_ID",
          "FullRepositoryId": "org/repo",
          "BranchName": "main",
          "OutputArtifactFormat": "CODE_ZIP"
        },
        "namespace": "SourceVariables"
      }]
    },
    {
      "name": "Build",
      "actions": [{
        "name": "Build",
        "actionTypeId": {
          "category": "Build",
          "owner": "AWS",
          "provider": "CodeBuild",
          "version": "1"
        },
        "inputArtifacts": [{"name": "SourceOutput"}],
        "outputArtifacts": [{"name": "BuildOutput"}],
        "configuration": {
          "ProjectName": "my-build-project"
        },
        "namespace": "BuildVariables"
      }]
    },
    {
      "name": "Deploy",
      "actions": [{
        "name": "Deploy",
        "actionTypeId": {
          "category": "Deploy",
          "owner": "AWS",
          "provider": "CodeDeploy",
          "version": "1"
        },
        "inputArtifacts": [{"name": "BuildOutput"}],
        "configuration": {
          "ApplicationName": "my-app",
          "DeploymentGroupName": "my-deployment-group"
        }
      }]
    }
  ]
}'
```

### Deploy Action Providers

CodePipeline supports multiple deploy providers beyond CodeDeploy:

| Provider | Use Case |
|----------|----------|
| CodeDeploy | EC2/ECS/Lambda with traffic shifting strategies |
| CloudFormation | Deploy CDK/SAM/CloudFormation stacks (action modes: CREATE_UPDATE, CHANGE_SET_*) |
| S3 | Static asset uploads (web apps, config files) |
| ECS | Direct ECS service update (rolling, no CodeDeploy) |
| EKS | Kubernetes deployments |
| AppConfig | Feature flags and configuration deployment |

## V1 vs V2

| Feature | V1 | V2 |
|---------|----|----|
| Execution modes | SUPERSEDED only | SUPERSEDED, QUEUED, PARALLEL |
| Triggers | Polling or webhook | Push/PR filtering with globs |
| Variables | Action output only | Pipeline-level + action output |
| Stage conditions | Not available | Entry/success/failure conditions |
| Rollback | Not available | Stage-level rollback |

## Execution Modes

| Mode | Behavior | Max Concurrent | Use When |
|------|----------|----------------|----------|
| SUPERSEDED | Newer replaces older at stage boundaries | 1 active | Only latest matters (default V1 behavior) |
| QUEUED | FIFO order, each completes before next starts | 50 queued | Order matters (migrations, sequential deploys) |
| PARALLEL | All run independently, no waiting | 50 concurrent | Independent feature branches, no shared state |

**Pitfalls:**
- PARALLEL loses rollback capability and source revision tracking — do not use for prod pipelines requiring rollback
- Changing mode discards queued executions — stop pipeline first
- QUEUED rejects execution 51 (not queued silently)

## Triggers with Git Filtering

### Push Trigger (deploy on main, only src/ changes)

```json
"triggers": [{
  "providerType": "CodeStarSourceConnection",
  "gitConfiguration": {
    "sourceActionName": "Source",
    "push": [{
      "branches": {
        "includes": ["main"],
        "excludes": ["feature/*"]
      },
      "filePaths": {
        "includes": ["src/**", "deploy/**"],
        "excludes": ["docs/**", "*.md"]
      }
    }]
  }
}]
```

### Pull Request Trigger

```json
"triggers": [{
  "providerType": "CodeStarSourceConnection",
  "gitConfiguration": {
    "sourceActionName": "Source",
    "pullRequest": [{
      "branches": { "includes": ["main"] },
      "events": ["OPEN", "UPDATE"]
    }]
  }
}]
```

### Tag Trigger

```json
"push": [{
  "tags": {
    "includes": ["release-*"],
    "excludes": ["release-*-rc*"]
  }
}]
```

### Trigger Limits

| Limit | Value |
|-------|-------|
| Triggers per pipeline | 50 |
| Filters per trigger | 3 |
| Glob patterns per includes/excludes | 8 each |
| **File path evaluation limit** | **100 files** — commits exceeding this skip path filtering entirely |

## Pipeline Variables

### Pipeline-Level Variables

Declare in pipeline definition:

```json
"variables": [
  {"name": "DeployEnvironment", "defaultValue": "staging", "description": "Target environment"},
  {"name": "SkipTests", "defaultValue": "false", "description": "Skip integration tests"}
]
```

Reference in action configs: `#{variables.DeployEnvironment}`

Override at execution:

```
aws codepipeline start-pipeline-execution \
  --name my-pipeline \
  --variables name=DeployEnvironment,value=production
```

### Action Output Variables (Namespace)

Add `"namespace": "BuildVars"` to an action to expose its outputs.

| Provider | Output Variables |
|----------|-----------------|
| CodeStarSourceConnection | CommitId, CommitMessage, BranchName, AuthorDate, ConnectionArn, FullRepositoryName |
| CodeBuild | BuildId, BuildTag, ResolvedSourceVersion |
| CloudFormation | StackId, all stack Outputs |
| Lambda | FunctionOutput (custom JSON) |
| Manual Approval | ApprovalStatus, ApprovalSummary, CustomData |

Reference: `#{Namespace.VariableName}` — e.g., `#{SourceVariables.CommitId}`

### Variable Limits

| Limit | Value |
|-------|-------|
| Pipeline-level variables | 50 |
| Variable value length | 1000 characters |
| Output variables per compute action | 15 |
| Total output size per action | 122,880 bytes (silently truncates if exceeded) |

## Cross-Account Deployment

Requires ALL THREE configured together:

### Step 1: Customer-Managed KMS Key (Source Account)

MUST use key ID or full ARN — aliases do not resolve cross-account.

Key policy grants target account:

```json
{
  "Sid": "AllowTargetAccountDecrypt",
  "Effect": "Allow",
  "Principal": {"AWS": "arn:aws:iam::TARGET_ACCOUNT_ID:root"},
  "Action": ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey*", "kms:ReEncrypt*"],
  "Resource": "*",
  "Condition": {
    "ArnLike": {
      "aws:PrincipalArn": "arn:aws:iam::TARGET_ACCOUNT_ID:role/cross-account-deploy-role"
    }
  }
}
```

### Step 2: S3 Bucket Policy (Source Account)

```json
[
  {
    "Sid": "AllowTargetAccountAccess",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::TARGET_ACCOUNT_ID:role/cross-account-deploy-role"},
    "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:GetBucketVersioning", "s3:PutObject"],
    "Resource": ["arn:aws:s3:::BUCKET", "arn:aws:s3:::BUCKET/*"]
  },
  {
    "Sid": "DenyInsecureTransport",
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:*",
    "Resource": ["arn:aws:s3:::BUCKET", "arn:aws:s3:::BUCKET/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }
]
```

### Step 3: Cross-Account Role (Target Account)

Trust policy:

```json
{
  "Effect": "Allow",
  "Principal": {"AWS": "arn:aws:iam::SOURCE_ACCOUNT_ID:root"},
  "Action": "sts:AssumeRole",
  "Condition": {
    "ArnLike": {"aws:PrincipalArn": "arn:aws:iam::SOURCE_ACCOUNT_ID:role/pipeline-service-role"}
  }
}
```

### Step 4: Pipeline Action Configuration

```json
"artifactStore": {
  "type": "S3",
  "location": "BUCKET",
  "encryptionKey": {"id": "arn:aws:kms:REGION:SOURCE_ACCOUNT_ID:key/KEY_ID", "type": "KMS"}
},
"actions": [{
  "roleArn": "arn:aws:iam::TARGET_ACCOUNT_ID:role/cross-account-deploy-role",
  ...
}]
```

For cross-region: use `artifactStores` (plural) with per-region bucket and KMS key configuration.

## Manual Approval Gates

```json
{
  "name": "DeploymentApproval",
  "actionTypeId": {"category": "Approval", "owner": "AWS", "provider": "Manual", "version": "1"},
  "configuration": {
    "NotificationArn": "arn:aws:sns:REGION:ACCOUNT_ID:pipeline-approvals",
    "CustomData": "Deploy #{SourceVariables.CommitId}?",
    "ExternalEntityLink": "https://staging.example.com"
  }
}
```

Approve via CLI:

```
aws codepipeline put-approval-result \
  --pipeline-name my-pipeline \
  --stage-name Production \
  --action-name DeploymentApproval \
  --token TOKEN_FROM_NOTIFICATION \
  --result summary="Approved",status=Approved
```

**Timeout**: Default 7 days, configurable 5 min to 60 days. Token expires with timeout.

**Security**: MUST encrypt the SNS topic with KMS (`aws sns set-topic-attributes --topic-arn ARN --attribute-name KmsMasterKeyId --attribute-value KEY_ARN`). MUST NOT include secrets, API keys, or credentials in CustomData. Verify commit messages contain no sensitive information before referencing them in CustomData. Restrict SNS topic subscriptions to authorized approvers only.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `InvalidStructureException` | Missing required field or bad JSON | Validate with `--cli-input-json file://pipeline.json` |
| `StageNotRetryableException` | Stage not in Failed state | Only failed stages can be retried |
| `InvalidActionDeclarationException` with KMS | Using alias cross-account | Use full key ARN |
| Trigger fires on unrelated commits | >100 files touched, path filter skipped | Use branch filter as primary gate |
| `PipelineExecutionNotStoppableException` | Execution in terminal state | Already finished, no action needed |

## Security

- MUST encrypt artifact bucket with customer-managed KMS key (shown in examples above)
- Scope pipeline service role to specific resource ARNs; avoid `*` on sensitive actions
- MUST encrypt SNS topics for approval notifications with KMS (CustomData may contain commit metadata)
- Enable CloudTrail for `codepipeline:*` API auditing
- See [CodePipeline security best practices](https://docs.aws.amazon.com/codepipeline/latest/userguide/security-best-practices.html)

## Related

- [codebuild.md](codebuild.md) for build action configuration
- [codedeploy.md](codedeploy.md) for deployment strategies
- [codeconnections.md](codeconnections.md) for source connection setup
