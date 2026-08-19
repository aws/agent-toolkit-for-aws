# Amazon Elastic Container Registry

## Overview

Domain expertise for managing ECR registries and repositories, as well as pushing container images and other artifacts. Covers various topics.

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

See the [relevant documentation](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-scanning-basic.html) for more information.

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

See the [relevant documentation](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-scanning-enhanced.html) for more information.

## Lifecycle policies

Amazon ECR lifecycle policies provide more control over the lifecycle management of images in a private repository. A lifecycle policy contains one or more rules, and each rule defines an action for Amazon ECR. Based on the expiration criteria in the lifecycle policy, images can be archived or expired based on the criteria specified in the lifecycle policy within 24 hours.

See the [relevant documentation](https://docs.aws.amazon.com/AmazonECR/latest/userguide/LifecyclePolicies.html) for more information.

Note: `sinceImagePulled` cannot expire images. When a user wants to clean up images based on
last-pull time, be aware that the `sinceImagePulled` count type only works with the
`transition` action (to the `archive` storage class) — it cannot be used with `expire`.
To actually delete images by pull activity, use two rules: first `transition` them to
archive with `sinceImagePulled`, then `expire` them with `sinceImageTransitioned`. Archived
images must stay in archive for a minimum of 90 days before they can be deleted. Never
produce a policy that pairs `sinceImagePulled` with an `expire` action.

## Security Considerations

- **Encryption at rest**: Use `KMS` via `--encryption-configuration` when you need key-level audit trail (KMS logs `GenerateDataKey`, `Decrypt` calls in CloudTrail) and customer-managed key rotation. `AES256` (S3-managed keys) is the default. All ECR API calls are logged by CloudTrail regardless of encryption type.
- **Image tag immutability**: Set `IMMUTABLE` to prevent tag overwriting attacks (supply chain security). Use `IMMUTABLE_WITH_EXCLUSION` only when specific tags must remain mutable.
- **Least-privilege IAM**: Scope ECR permissions to specific repository ARNs. Separate push (CI/CD) from pull (execution role) permissions. `ecr:GetAuthorizationToken` requires `Resource: "*"` — it cannot be scoped to a repository.
- **Cross-account access**: Use `aws:PrincipalOrgID` conditions in repository policies. Grant only `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` for pull-only access. Prefer specific role ARNs over `:root` principals.
- **Logging and monitoring**: ECR API calls are logged by CloudTrail. Set CloudWatch alarms on ECR API usage metrics to detect unusual pull patterns or approaching quota limits. See [ECR usage metrics](https://docs.aws.amazon.com/AmazonECR/latest/userguide/monitoring-usage.html).
- **Lifecycle policies**: Expire untagged and old images to reduce attack surface from unpatched images.

## Resources

- [Amazon ECR Documentation](https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html)
- [IAM Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonelasticcontainerregistry.html)
