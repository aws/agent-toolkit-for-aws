# CodeArtifact

## Overview

CodeArtifact is a managed package repository for use in CI/CD pipelines. It stores npm, pip, Maven, NuGet, Swift, Cargo, and generic packages. In the context of CI/CD, it serves as a private package cache and internal package registry that CodeBuild pulls dependencies from.

## Key Concepts

| Concept | Description |
|---------|-------------|
| Domain | Top-level container for repositories. Applies cross-repo policies. One per organization typically. |
| Repository | Stores packages. Can have upstream repositories (including external connections). |
| External connection | Links a repository to a public registry (npmjs.com, pypi.org, Maven Central). Packages are cached on first fetch. |
| Upstream repository | A repo can pull from another CodeArtifact repo (chaining). Packages flow downstream on demand. |

## Using CodeArtifact in CodeBuild

### Authentication

CodeArtifact uses time-limited auth tokens (max 12 hours). In buildspec:

```yaml
phases:
  pre_build:
    commands:
      - aws codeartifact login --tool npm --domain MY_DOMAIN --domain-owner ACCOUNT_ID --repository MY_REPO
      - npm ci
```

For pip:
```yaml
      - aws codeartifact login --tool pip --domain MY_DOMAIN --domain-owner ACCOUNT_ID --repository MY_REPO
      - pip install -r requirements.txt
```

For Maven/Gradle, use `get-authorization-token` and configure settings.xml/build.gradle:
```yaml
      - export CODEARTIFACT_AUTH_TOKEN=$(aws codeartifact get-authorization-token --domain MY_DOMAIN --domain-owner ACCOUNT_ID --query authorizationToken --output text)
```

### IAM Permissions for CodeBuild Role

Minimum permissions for pulling packages:

```json
{
  "Effect": "Allow",
  "Action": [
    "codeartifact:GetAuthorizationToken",
    "codeartifact:GetRepositoryEndpoint",
    "codeartifact:ReadFromRepository"
  ],
  "Resource": [
    "arn:aws:codeartifact:REGION:ACCOUNT:domain/MY_DOMAIN",
    "arn:aws:codeartifact:REGION:ACCOUNT:repository/MY_DOMAIN/MY_REPO"
  ]
}
```

Also requires `sts:GetServiceBearerToken` (for the auth token exchange):
```json
{
  "Effect": "Allow",
  "Action": "sts:GetServiceBearerToken",
  "Resource": "*",
  "Condition": {
    "StringEquals": { "sts:AWSServiceName": "codeartifact.amazonaws.com" }
  }
}
```

### Publishing Packages (CI produces packages)

Additional permission for publish:
```json
{
  "Effect": "Allow",
  "Action": [
    "codeartifact:PublishPackageVersion",
    "codeartifact:PutPackageMetadata"
  ],
  "Resource": "arn:aws:codeartifact:REGION:ACCOUNT:package/MY_DOMAIN/MY_REPO/*"
}
```

## Common Patterns

### Private cache with public fallback

```bash
# Create domain with customer-managed KMS key (required for cross-account access)
aws codeartifact create-domain --domain my-org --encryption-key arn:aws:kms:REGION:ACCOUNT:key/KEY_ID

# Create repo with external connection to npmjs
aws codeartifact create-repository --domain my-org --repository npm-store
aws codeartifact associate-external-connection --domain my-org --repository npm-store --external-connection public:npmjs

# Create internal repo that uses npm-store as upstream
aws codeartifact create-repository --domain my-org --repository my-packages --upstreams repositoryName=npm-store
```

Packages are fetched from npmjs on first request and cached in npm-store. Internal packages are published directly to my-packages.

### Cross-account access

Set a domain policy to allow other accounts to read:
```bash
aws codeartifact put-domain-permissions-policy --domain my-org --policy-document file://policy.json
```

Or use repository policies for finer-grained control.

## Pitfalls

**Auth token expires after 12 hours**: The token from `login` or `get-authorization-token` has a maximum TTL of 12 hours. Long-running builds or pipelines that cache credentials will fail with 401/403. Always refresh the token in `pre_build`.

**`login` sets global config**: `aws codeartifact login --tool npm` modifies `~/.npmrc` globally. In CodeBuild this is fine (ephemeral environment), but locally it overwrites existing registry config. Use `--namespace` or manual token setup for multi-registry scenarios.

**Domain policy vs repository policy**: For cross-account access, you need BOTH — missing either causes AccessDenied. Domain policy: grants `codeartifact:GetAuthorizationToken` to the consuming account. Repository policy: grants `codeartifact:ReadFromRepository` to the consuming account. Plus identity-based policy on the consuming role. All three are required.

**External connection limit**: Each repository can have only ONE external connection. Use upstream chaining to combine multiple public sources (e.g., one repo connected to npmjs, another to pypi, a third repo listing both as upstreams).

**sts:GetServiceBearerToken missing**: The auth token exchange requires `sts:GetServiceBearerToken`. This is frequently missing from CodeBuild service roles because it's not an obvious CodeArtifact permission. Error message: "User is not authorized to perform: sts:GetServiceBearerToken".

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Unable to get authorization token` | Missing `sts:GetServiceBearerToken` | Add to CodeBuild service role with condition key |
| `401 Unauthorized` during npm install | Token expired or login not run | Add `codeartifact login` to pre_build phase |
| `Package not found` | External connection not configured or repo not upstream | Check upstream chain configuration |
| `AccessDeniedException` on cross-account | Missing domain policy OR repository policy | Configure both domain and repository policies |
| `ResourceNotFoundException` on publish | Wrong repository name or domain | Verify domain/repo names match exactly |

## Security

- MUST use a customer-managed KMS key for domain encryption (`--encryption-key`); the default AWS-managed key does NOT support cross-account access
- Scope `codeartifact:ReadFromRepository` to specific repository ARNs; avoid `*`
- Use domain policies (not just repository policies) for cross-account access grants
- Enable CloudTrail for `codeartifact:*` API auditing — critical for cross-account scenarios to track who is accessing packages
- Rotate auth tokens regularly; default 12-hour TTL is the maximum
- See [CodeArtifact security best practices](https://docs.aws.amazon.com/codeartifact/latest/ug/security-best-practices.html)

## Related

- [codebuild.md](codebuild.md) for buildspec integration
- [codepipeline.md](codepipeline.md) for pipeline stages
