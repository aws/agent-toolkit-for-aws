# ECR Repository Management Reference

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [Create Repository](#create-repository)
- [Authenticate and Push Images](#authenticate-and-push-images)
- [Lifecycle Policies](#lifecycle-policies)
- [Image Scanning](#image-scanning)
- [Cross-Account Image Pulls](#cross-account-image-pulls)
- [Common Image Pull Errors](#common-image-pull-errors)
- [Security Considerations](#security-considerations)

---

## Verify Dependencies

Before managing ECR repositories, the operator MUST confirm:

1. Docker is installed and the Docker daemon is running.
2. The caller has the specific IAM permissions needed for the operation (e.g., `ecr:CreateRepository`, `ecr:GetAuthorizationToken`, `ecr:PutImage`). Avoid granting `ecr:*` in production — scope permissions to the actions and repositories required.

```bash
aws sts get-caller-identity --output json
docker info --format '{{.ServerVersion}}'
```

---

## Create Repository

```bash
aws ecr create-repository \
  --repository-name "$REPO_NAME" \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE \
  --encryption-configuration encryptionType=AES256 \
  --region "$REGION" \
  --output json
```

> **Deprecation notice:** `--image-scanning-configuration` is being deprecated in favor of registry-level scanning configuration via `put-registry-scanning-configuration` (see [Image Scanning](#image-scanning) section). The parameter still works but prefer the registry-level approach for new setups.

The operator SHOULD set:

- `scanOnPush=true` to automatically scan images for vulnerabilities on push (or configure scanning at the registry level — see [Image Scanning](#image-scanning)).
- `image-tag-mutability IMMUTABLE` to prevent tag overwriting. This ensures a given tag always refers to the same image digest. Use `IMMUTABLE_WITH_EXCLUSION` with `--image-tag-mutability-exclusion-filters` if specific tags (e.g., `latest`) must remain mutable.

---

## Authenticate and Push Images

### Authenticate Docker to ECR

```bash
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS \
    --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
```

> **Warning:** The authentication token expires after **12 hours**. The operator MUST re-authenticate before pushing if the token has expired. CI/CD pipelines SHOULD call `get-login-password` at the start of every build.

### Build, Tag, and Push

```bash
docker build -t "$REPO_NAME:$IMAGE_TAG" .
docker tag "$REPO_NAME:$IMAGE_TAG" \
  "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"
docker push \
  "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"
```

### Verify the Push

```bash
aws ecr describe-images \
  --repository-name "$REPO_NAME" \
  --image-ids imageTag="$IMAGE_TAG" \
  --region "$REGION" \
  --output json
```

---

## Lifecycle Policies

Lifecycle policies automatically expire old images. ECR evaluates rules approximately every **24 hours** — images are not removed immediately after a rule matches.

### Policy JSON Structure

```json
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Keep only the last 10 tagged images",
      "selection": {
        "tagStatus": "tagged",
        "tagPrefixList": ["v"],
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": {
        "type": "expire"
      }
    },
    {
      "rulePriority": 2,
      "description": "Expire untagged images older than 7 days",
      "selection": {
        "tagStatus": "untagged",
        "countType": "sinceImagePushed",
        "countUnit": "days",
        "countNumber": 7
      },
      "action": {
        "type": "expire"
      }
    }
  ]
}
```

### Key Fields

| Field            | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `rulePriority`   | Integer. Lower numbers are evaluated first. MUST be unique per rule.     |
| `tagStatus`      | `tagged`, `untagged`, or `any`.                                          |
| `tagPrefixList`  | Required when `tagStatus` is `tagged` and `tagPatternList` is not specified. Matches image tags by prefix. |
| `tagPatternList` | Alternative to `tagPrefixList` when `tagStatus` is `tagged`; supports wildcards (`*`, max 4 per pattern). AWS recommends `tagPatternList` over `tagPrefixList`. |
| `countType`      | `imageCountMoreThan`, `sinceImagePushed`, `sinceImagePulled`, or `sinceImageTransitioned`. |
| `countNumber`    | Threshold count or age in days.                                          |
| `action.type`    | `expire` (delete images) or `transition` (move to archive storage; requires `targetStorageClass: "archive"`). |

### Apply a Lifecycle Policy

```bash
aws ecr put-lifecycle-policy \
  --repository-name "$REPO_NAME" \
  --lifecycle-policy-text file://lifecycle-policy.json \
  --region "$REGION" \
  --output json
```

Verify the policy was applied:

```bash
aws ecr get-lifecycle-policy \
  --repository-name "$REPO_NAME" \
  --region "$REGION" \
  --output json
```

### Preview Before Applying

The operator SHOULD preview the policy to see which images would be affected before applying:

```bash
aws ecr start-lifecycle-policy-preview \
  --repository-name "$REPO_NAME" \
  --lifecycle-policy-text file://lifecycle-policy.json \
  --region "$REGION" \
  --output json
```

> Poll the preview status with `get-lifecycle-policy-preview` until it completes.

```bash
aws ecr get-lifecycle-policy-preview \
  --repository-name "$REPO_NAME" \
  --region "$REGION" \
  --output json
```

### Manifest List Blocking

Lifecycle policies do not delete images referenced by a manifest list (multi-architecture images). The operator MUST account for this when designing policies for multi-arch repositories.

### CDK addLifecycleRule

```typescript
import * as ecr from 'aws-cdk-lib/aws-ecr';

const repo = new ecr.Repository(this, 'Repo', {
  repositoryName: '$REPO_NAME',
  imageScanOnPush: true,
  imageTagMutability: ecr.TagMutability.IMMUTABLE,
});

repo.addLifecycleRule({
  tagPrefixList: ['v'],
  maxImageCount: 10,
  description: 'Keep only the last 10 tagged images',
});

repo.addLifecycleRule({
  maxImageAge: cdk.Duration.days(7),
  tagStatus: ecr.TagStatus.UNTAGGED,
  description: 'Expire untagged images older than 7 days',
});
```

---

## Image Scanning

### Basic Scanning

Basic scanning has no separate ECR charge (only enhanced scanning incurs Inspector charges).

```bash
# Trigger a manual scan
aws ecr start-image-scan \
  --repository-name "$REPO_NAME" \
  --image-id imageTag="$IMAGE_TAG" \
  --region "$REGION" \
  --output json

# Retrieve scan findings
aws ecr describe-image-scan-findings \
  --repository-name "$REPO_NAME" \
  --image-id imageTag="$IMAGE_TAG" \
  --region "$REGION" \
  --output json
```

### Enhanced Scanning with Amazon Inspector

Enhanced scanning provides continuous, automated scanning using Amazon Inspector. It covers OS packages and programming language packages.

The operator MUST enable enhanced scanning at the registry level:

```bash
aws ecr put-registry-scanning-configuration \
  --scan-type ENHANCED \
  --rules '[{"scanFrequency":"CONTINUOUS_SCAN","repositoryFilters":[{"filter":"*","filterType":"WILDCARD"}]}]' \
  --region "$REGION" \
  --output json
```

> Enhanced scanning incurs additional Inspector charges.

---

## Cross-Account Image Pulls

To allow account `$CONSUMER_ACCOUNT_ID` to pull images from a repository in account `$ACCOUNT_ID`:

### Step 1: Set Repository Policy (Source Account)

```bash
aws ecr set-repository-policy \
  --repository-name "$REPO_NAME" \
  --policy-text '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "AllowCrossAccountPull",
        "Effect": "Allow",
        "Principal": {
          "AWS": "arn:aws:iam::$CONSUMER_ACCOUNT_ID:root"
        },
        "Action": [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
      }
    ]
  }' \
  --region "$REGION" \
  --output json
```

> **Security:** For tighter control, replace the `:root` principal with a specific IAM role ARN (e.g., the consumer's ECS execution role). For organizations using AWS Organizations, use a `Condition` with `aws:PrincipalOrgID` to allow all accounts in the organization without listing each account ID.
> **Note:** The minimum pull permissions are `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` (per [ECR on ECS docs](https://docs.aws.amazon.com/AmazonECR/latest/userguide/ECR_on_ECS.html)). Omit `ecr:BatchCheckLayerAvailability` — it is not required for pulling images (it is a Read action used by the ECR proxy primarily during push to check if layers already exist). `ecr:GetAuthorizationToken` is registry-level and must be on the consumer's identity-based policy, not the repository policy.

### Step 2: Execution Role Permissions (Consumer Account)

The ECS execution role in the consumer account MUST have `ecr:GetAuthorizationToken` and the pull actions listed above. The execution role's trust policy MUST allow `ecs-tasks.amazonaws.com` to assume it.

---

## Common Image Pull Errors

| Error                        | Cause                                                        | Resolution                                                                                  |
|------------------------------|--------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| `CannotPullContainerError`   | Task cannot reach ECR or lacks permissions.                  | Verify networking (NAT gateway or VPC endpoints for private subnets). Verify execution role has ECR pull permissions. |
| `AccessDeniedException`      | Execution role lacks `ecr:GetAuthorizationToken` or pull actions. | Add `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer` to the execution role. |
| `invalid reference format`   | Malformed image URI in the task definition.                  | Verify the image URI format: `$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:$TAG`.  |
| `manifest unknown`           | The specified tag or digest does not exist in the repository.| Verify the image tag exists with `describe-images`. Check for typos in the tag.             |
| `toomanyrequests`            | Docker Hub pull rate limit exceeded (most common cause per [ECS troubleshooting docs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_cannot_pull_image.html)). Can also occur if ECR API rate limits are hit (see [ECR service quotas](https://docs.aws.amazon.com/AmazonECR/latest/userguide/service-quotas.html)). | For Docker Hub: authenticate pulls, use an ECR pull-through cache, or keep a private copy in ECR. For ECR throttling: implement exponential backoff and request a quota increase if needed. |

---

## Security Considerations

- **Encryption at rest**: Use `KMS` via `--encryption-configuration` when you need key-level audit trail (KMS logs `GenerateDataKey`, `Decrypt` calls in CloudTrail) and customer-managed key rotation. `AES256` (S3-managed keys) is the default. All ECR API calls are logged by CloudTrail regardless of encryption type.
- **Image tag immutability**: Set `IMMUTABLE` to prevent tag overwriting attacks (supply chain security). Use `IMMUTABLE_WITH_EXCLUSION` only when specific tags must remain mutable.
- **Least-privilege IAM**: Scope ECR permissions to specific repository ARNs. Separate push (CI/CD) from pull (execution role) permissions. `ecr:GetAuthorizationToken` requires `Resource: "*"` — it cannot be scoped to a repository.
- **Cross-account access**: Use `aws:PrincipalOrgID` conditions in repository policies. Grant only `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` for pull-only access. Prefer specific role ARNs over `:root` principals.
- **Logging and monitoring**: ECR API calls are logged by CloudTrail. Set CloudWatch alarms on ECR API usage metrics to detect unusual pull patterns or approaching quota limits. See [ECR usage metrics](https://docs.aws.amazon.com/AmazonECR/latest/userguide/monitoring-usage.html).
- **Lifecycle policies**: Expire untagged and old images to reduce attack surface from unpatched images.
