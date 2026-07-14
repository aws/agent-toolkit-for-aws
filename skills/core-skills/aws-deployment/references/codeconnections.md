# CodeConnections

## Service Prefixes

Two ARN prefixes coexist (service was rebranded from CodeStar Connections to CodeConnections):

| Prefix | ARN Format |
|--------|-----------|
| `codeconnections` | `arn:aws:codeconnections:REGION:ACCOUNT:connection/UUID` |
| `codestar-connections` | `arn:aws:codestar-connections:REGION:ACCOUNT:connection/UUID` |

Both work in pipeline configurations. IAM policy prefix must match the resource ARN prefix.

## Provider Comparison

| Feature | GitHub | GitHub Enterprise | GitLab.com | GitLab Self-Managed | Bitbucket Cloud | Azure DevOps |
|---------|--------|-------------------|------------|---------------------|-----------------|--------------|
| Host resource required | No | Yes | No | Yes | No | No |
| Auth mechanism | GitHub App | GitHub App | OAuth | OAuth | OAuth | OAuth |
| Org owner required | Yes | Yes | No | No | No | No |
| VPC endpoint needed | No | Yes (if private) | No | Yes | No | No |
| Provider type value | `GitHub` | `GitHubEnterpriseServer` | `GitLab` | `GitLabSelfManaged` | `Bitbucket` | `AzureDevOps` |

## Create a Connection

```bash
aws codeconnections create-connection \
  --provider-type GitHub \
  --connection-name my-github-connection \
  --tags Key=managed_by,Value=aws-skills Key=skill,Value=deploy
```

For self-managed providers, use `--host-arn` instead of `--provider-type`:

```bash
aws codeconnections create-connection \
  --host-arn arn:aws:codeconnections:REGION:ACCOUNT:host/HOST_ID \
  --connection-name my-gitlab-sm-connection
```

Check status:

```bash
aws codeconnections get-connection --connection-arn CONNECTION_ARN \
  --query "Connection.ConnectionStatus" --output text
```

## The PENDING State Trap

Connections created via CLI/CloudFormation/CDK are **always** `PENDING`. There is NO API to complete authorization — the console OAuth handshake is mandatory.

A PENDING connection:

- Returns no errors from `create-connection`
- Passes ARN validation in pipeline definitions
- **Silently fails** when the pipeline fetches source

## Authorize a Connection (Console Required)

### GitHub / GitHub Enterprise

1. AWS Console → **Developer Tools > Settings > Connections**
2. Select PENDING connection → **Update pending connection**
3. **Install a new app** (or select existing GitHub App)
4. Browser redirects to GitHub — sign in as **organization owner**
5. Select org, choose repos → **Install**
6. Back in AWS Console → **Connect**

**Pitfall**: Non-owner members get cookie errors or blank pages. GitHub App installation REQUIRES org owner role.

### GitLab.com / GitLab Self-Managed

1. AWS Console → **Developer Tools > Settings > Connections**
2. Select PENDING connection → **Update pending connection**
3. Redirects to GitLab → authorize the AWS application
4. **Connect** to finalize

### Bitbucket Cloud

Same flow as GitLab: Console → select connection → redirect → authorize → Connect.

### Verify

```bash
aws codeconnections get-connection --connection-arn CONNECTION_ARN \
  --query "Connection.ConnectionStatus" --output text
# Expected: AVAILABLE
```

## Create a Host Resource (Self-Managed Only)

Required for GitHub Enterprise Server and GitLab Self-Managed. NOT needed for hosted providers.

```bash
aws codeconnections create-host \
  --name my-gitlab-host \
  --provider-type GitLabSelfManaged \
  --provider-endpoint https://gitlab.internal.example.com \
  --vpc-configuration VpcId=VPC_ID,SubnetIds=SUBNET_1,SUBNET_2,SecurityGroupIds=SG_ID,TlsCertificate=BASE64_PEM_CERT
```

`--vpc-configuration` required when endpoint is not publicly accessible. `TlsCertificate` accepts PEM-encoded CA cert (base64).

Host creation is async — check status:

```bash
aws codeconnections get-host --host-arn HOST_ARN --query "Status" --output text
# Wait for: AVAILABLE
```

## Connection Sharing

A single connection serves unlimited pipelines within the same account and region. Create one connection per provider per account — do not create one per pipeline.

Cross-account: share connections using AWS Resource Access Manager (RAM). See [sharing connections](https://docs.aws.amazon.com/dtconsole/latest/userguide/connections-share.html). Without RAM, each account needs its own connection.

## IAM Configuration

Use `codeconnections:` prefix for all Actions. The dual prefix only matters in the `Resource` field (to match existing ARNs):

```json
{
  "Effect": "Allow",
  "Action": [
    "codeconnections:UseConnection"
  ],
  "Resource": [
    "arn:aws:codeconnections:REGION:ACCOUNT:connection/CONNECTION_UUID",
    "arn:aws:codestar-connections:REGION:ACCOUNT:connection/OLD_CONNECTION_UUID"
  ],
  "Condition": {
    "StringEquals": {
      "codeconnections:FullRepositoryId": "org/repo"
    }
  }
}
```

**CRITICAL: UseConnection is over-permissive without condition keys.** It grants access to ALL repositories the connection can reach. MUST specify conditions:

| Condition Key | Purpose |
|--------------|---------|
| `codeconnections:FullRepositoryId` | Restrict to specific repo (e.g., `org/repo`) |
| `codeconnections:ProviderAction` | Restrict operations (e.g., `read` only) |
| `codeconnections:BranchName` | Restrict to specific branch |

For pipeline service roles: minimum `codeconnections:UseConnection` with condition keys scoped to the repo.

For CodeBuild roles using `CODEBUILD_CLONE_REF`: add `codeconnections:UseConnection` to the **CodeBuild** service role (not the pipeline role), with the same condition key scoping.

## Common Errors

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| Pipeline fails "connection not available" | Connection PENDING | Complete OAuth in console |
| Blank page / cookie error during GitHub auth | User not org owner | Have org owner perform installation |
| `AccessDeniedException` on UseConnection | IAM only has one prefix | Add `codeconnections:UseConnection` and `codestar-connections:UseConnection` |
| Host stuck in `VPC_CONFIG_FAILED_INITIALIZATION` | VPC/subnet/SG misconfiguration | Verify route to provider endpoint, validate TLS cert |
| Pipeline trigger never fires | `sourceActionName` mismatch | Ensure trigger `sourceActionName` matches action `Name` exactly |
| Repository not found | Wrong FullRepositoryId format | Use `org/repo` format (case-sensitive) |

## Security

- MUST scope UseConnection with condition keys (FullRepositoryId, ProviderAction) — without them, any repo accessible to the connection is exposed
- Scope Resource to specific connection ARNs in production
- Enable CloudTrail for `codeconnections:*` API auditing
- Revoke connections when personnel with OAuth access leave the organization
- Connections store OAuth tokens managed by AWS — prefer connections over manual PATs which cannot be auto-rotated

## Related

- [codepipeline.md](codepipeline.md) for source action and trigger configuration
- [troubleshooting.md](troubleshooting.md) for pipeline-level debugging
