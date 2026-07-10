# CodeBuild

## Source Configuration

Code reaches CodeBuild via:

- **Pipeline action** — CodePipeline passes artifacts (most common in CI/CD)
- **Direct source** — CodeBuild pulls from CodeCommit, S3, GitHub, GitLab, or Bitbucket
- **No source** — buildspec commands handle everything (e.g., `git clone` in install phase)

When using CodePipeline, the source is passed as an input artifact. When using CodeBuild standalone, configure source in the project:

```bash
aws codebuild create-project --name my-project \
  --source type=CODECOMMIT,location=https://git-codecommit.REGION.amazonaws.com/v1/repos/REPO \
  --source-version main \
  --service-role arn:aws:iam::ACCOUNT_ID:role/codebuild-role \
  --artifacts type=NO_ARTIFACTS \
  --environment type=LINUX_CONTAINER,computeType=BUILD_GENERAL1_SMALL,image=aws/codebuild/amazonlinux2-x86_64-standard:5.0
```

For GitHub/GitLab via CodeConnections, use `type=CODEPIPELINE` (pipeline manages source) or configure a webhook for standalone builds.

## Phase Error Handling (on-failure)

Each buildspec phase supports an `on-failure` attribute controlling behavior when commands fail:

```yaml
phases:
  install:
    on-failure: ABORT
    commands:
      - npm ci
  build:
    on-failure: CONTINUE
    commands:
      - npm run build
  post_build:
    on-failure: ABORT
    commands:
      - npm run package
```

| Strategy | Behavior |
|----------|----------|
| `ABORT` | Stop build immediately (default for install, pre_build, build) |
| `CONTINUE` | Move to next phase even if commands fail |
| `RETRY` | Retry failed command (default settings) |
| `RETRY-n` | Retry up to n times (e.g., `RETRY-3`) |
| `RETRY-regex` | Retry only if error matches regex pattern |
| `RETRY-n-regex` | Retry up to n times only for matching errors |

Use `RETRY-3-.*timeout.*` for transient network failures during dependency install.

Note: `post_build` runs even if `build` phase failed. Gate post_build logic with the `CODEBUILD_BUILD_SUCCEEDING` env var.

## VPC Configuration

Required when builds access private resources (RDS, internal APIs).

```bash
aws codebuild create-project --name my-project \
  --source type=CODEPIPELINE \
  --service-role arn:aws:iam::ACCOUNT_ID:role/codebuild-role \
  --vpc-config vpcId=VPC_ID,subnets=PRIVATE_SUBNET_1,PRIVATE_SUBNET_2,securityGroupIds=SG_ID
```

**CRITICAL: CodeBuild CANNOT assign public IPs in VPC.** Without a NAT gateway, builds hang silently at DOWNLOAD_SOURCE or dependency install with no error message.

| Requirement | Consequence if Missing |
|-------------|----------------------|
| NAT gateway on private subnets | Build hangs indefinitely — no timeout error, just silence |
| Private subnets only | Public subnets not supported for CodeBuild VPC |
| S3 VPC endpoint | Artifact operations route through NAT (slow, costly) |
| CloudWatch Logs VPC endpoint | Logs missing or delayed |

Service role needs: `ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface`, `ec2:CreateNetworkInterfacePermission`.

**Security group**: Restrict egress to required destinations only (VPC endpoints, NAT gateway). Avoid `0.0.0.0/0` egress — scope to S3 prefix lists and specific internal CIDRs. Ingress should be empty unless builds require inbound connections.

## Caching

| Cache Type | Scope | Best For | Constraint |
|------------|-------|----------|------------|
| S3 | Across builds | Dependencies (node_modules, .m2, pip) | Network transfer cost |
| Local - docker_layer_cache | Same host | Docker rebuilds | Best-effort on-demand; reliable on fleet |
| Local - source_cache | Same host | Incremental git fetch | Best-effort on-demand; reliable on fleet |
| Local - custom_cache | Same host | Arbitrary paths | Best-effort on-demand; reliable on fleet |

S3 caching (works on-demand and fleet):

```yaml
cache:
  paths:
    - '/root/.npm/**/*'
    - '/root/.m2/**/*'
```

Project config: `--cache type=S3,location=BUCKET/cache` (MUST enable SSE-KMS or SSE-S3 on the cache bucket — cached artifacts may contain dependency metadata)

Local caching (reliable on fleet, best-effort on on-demand): `--cache type=LOCAL,modes=[LOCAL_DOCKER_LAYER_CACHE,LOCAL_SOURCE_CACHE]`

**Key distinction:** S3 cache survives across any build host but costs network transfer. Local cache is instant (no transfer) but only works when consecutive builds land on the same host — guaranteed with fleet, probabilistic with on-demand.

## Docker Image Builds

For custom images or VPC builds: `privilegedMode: true` AND manual dockerd start. CodeBuild-managed standard images may have Docker pre-configured, but privileged mode is still required for Docker-in-Docker.

```bash
aws codebuild create-project --name docker-builder \
  --environment type=LINUX_CONTAINER,computeType=BUILD_GENERAL1_MEDIUM,image=aws/codebuild/amazonlinux2-x86_64-standard:5.0,privilegedMode=true
```

Buildspec for Docker + ECR push:

```yaml
version: 0.2
phases:
  pre_build:
    commands:
      - nohup /usr/local/bin/dockerd --host=unix:///var/run/docker.sock &
      - timeout 15 sh -c "until docker info; do sleep 1; done"
      - aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $ECR_REPO_URI
  build:
    commands:
      - docker build -t $IMAGE_REPO:$IMAGE_TAG .
      - docker push $IMAGE_REPO:$IMAGE_TAG
```

## Secrets Reference

Secrets Manager format in buildspec: `secret-id:json-key:version-stage:version-id` (last two optional).

```yaml
env:
  parameter-store:
    API_KEY: "/myapp/api-key"
  secrets-manager:
    DB_PASS: "myapp/db-creds:password"
```

IAM: `ssm:GetParameters` for Parameter Store, `secretsmanager:GetSecretValue` for Secrets Manager.

## Logging

Always enable CloudWatch Logs with KMS encryption (build logs may contain sensitive output):

```bash
--logs-config cloudWatchLogs={status=ENABLED,groupName=/aws/codebuild/PROJECT_NAME}
```

Encrypt the log group: `aws logs associate-kms-key --log-group-name /aws/codebuild/PROJECT_NAME --kms-key-id KEY_ARN`

## Timeouts

| Setting | Default | Maximum |
|---------|---------|---------|
| Build timeout | 60 min | 480 min (8 hours) |
| Queued timeout | 480 min | 480 min |

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Build hangs in VPC | No NAT gateway on private subnet | Add NAT gateway to route table |
| `Cannot connect to Docker daemon` | Privileged mode off or dockerd not started | Set `privilegedMode=true` AND start dockerd |
| `CODEBUILD_CLONE_REF` auth failure | CodeBuild role missing UseConnection | Add `codeconnections:UseConnection` to CodeBuild service role |
| `AccessDenied` on artifacts | Cross-region bucket | Artifact bucket MUST be same region as project |

## Security

- MUST scope service role to specific S3 buckets and ECR repos; avoid `*` resource
- Enable SSE-KMS or SSE-S3 on cache buckets (cached artifacts may reveal application internals)
- MUST NOT use `type: PLAINTEXT` environment variables for secrets — use `PARAMETER_STORE` or `SECRETS_MANAGER`
- Use VPC endpoints to keep artifact and log traffic off the public internet
- Enable CloudTrail for `codebuild:*` API auditing
- See [CodeBuild security best practices](https://docs.aws.amazon.com/codebuild/latest/userguide/security-best-practices.html)

## Related

- [codepipeline.md](codepipeline.md) for pipeline build action configuration
- [troubleshooting.md](troubleshooting.md) for additional error patterns
