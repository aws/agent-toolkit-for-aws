# Troubleshooting

## First Check These 5 Things

1. **Connection status**: `aws codeconnections get-connection --connection-arn ARN` — if PENDING, complete OAuth in console
2. **Pipeline state**: `aws codepipeline get-pipeline-state --name NAME` — find which action failed and why
3. **Build logs**: `aws codebuild batch-get-builds --ids BUILD_ID` — check `phases` array for first failed phase
4. **Deployment status**: `aws deploy get-deployment --deployment-id ID` — check `deploymentOverview` and `errorInformation`
5. **Service role permissions**: `aws iam simulate-principal-policy --policy-source-arn ROLE_ARN --action-names ACTION` — verify IAM

## Error Table

### CodePipeline

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| `InternalError` on action | Artifact bucket wrong region or KMS permission denied | Ensure S3 bucket same region as pipeline; check KMS key policy |
| `ActionConfigurationError` | Referenced resource deleted (CodeBuild project, deployment group) | Verify all resource names in action config still exist |
| `AccessDeniedException` on action | Service role missing permissions for the action's provider | Add required permissions to pipeline service role |
| Pipeline stuck InProgress | Disabled transition, waiting approval, or slow action | Check `get-pipeline-state` for `actionStates`; look for PENDING approval |
| `PipelineExecutionNotStoppableException` | Execution in terminal state (Succeeded/Failed) | Already finished — no action needed |
| `InvalidStructureException` on create/update | Malformed pipeline JSON | Validate JSON; check all required fields per action type |
| `StageNotRetryableException` | Stage not in Failed state | Only failed stages can be retried |
| `RevisionOutOfSyncException` | PARALLEL mode race between executions | Use QUEUED mode for sequential consistency |
| Trigger fires on unrelated changes | File path filter skipped (>100 files in commit) | Add branch filter as primary gate |
| Trigger never fires | sourceActionName mismatch or connection PENDING | Verify trigger config matches source action name exactly |
| `AccessDenied` on cross-account action | Missing KMS/S3/IAM trust (need all three) | Verify: KMS key policy, S3 bucket policy, target role trust policy |

### CodeBuild

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| `DOWNLOAD_SOURCE` failure | VPC without NAT, connection PENDING, or repo not found | Check VPC NAT gateway; verify connection AVAILABLE; check repo access |
| `YAML_FILE_ERROR` | Missing `runtime-versions`, bad YAML syntax, or wrong filename | Add runtime-versions block; validate YAML; file must be `buildspec.yml` at root |
| Build hangs indefinitely | VPC subnet without NAT gateway or S3 endpoint | Add NAT gateway to private subnet route table |
| `Cannot connect to Docker daemon` | Privileged mode not enabled or dockerd not started | Set `privilegedMode=true` AND start dockerd in pre_build phase |
| `BUILD_GENERAL1_SMALL not available` | Compute type not available in region or quota reached | Try different compute type or request quota increase |
| Build timeout (default 60 min) | Long-running build or hanging dependency download | Increase `timeoutInMinutes`; check for network issues (VPC) |
| `CODEBUILD_CLONE_REF` permission error | CodeBuild role missing UseConnection | Add `codeconnections:UseConnection` to CodeBuild service role (not pipeline role) |
| `CLIENT_ERROR: unable to locate credentials` | Service role insufficient for operation | Check CodeBuild service role has needed permissions |
| Artifacts not found by next stage | `base-directory` wrong or files pattern too restrictive | Verify `artifacts.base-directory` matches build output location |

### CodeDeploy

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| "no instances were found" | Tag filters match zero instances or agent not running | Verify EC2 tags; check `codedeploy-agent` status on instances |
| "specified key does not exist" | S3 revision artifact location wrong | Verify S3 path matches revision location in `create-deployment` |
| `ApplicationStop` fails every deploy | Previous revision's stop script is broken | Deploy fix-only revision or use `--ignore-application-stop-failures` |
| "file already exists at this location" | file_exists_behavior not set | Set `OVERWRITE` in deployment or appspec `files.overwrite: true` |
| `InstanceLimitExceeded` | ASG scaling faster than deployment completes | Suspend ASG Launch process, fix deployment, resume |
| "agent was not able to receive the lifecycle event" | Agent not running or network timeout | SSH to instance; `sudo service codedeploy-agent status`; check SG |
| HEALTH_CONSTRAINTS error | Not enough healthy instances to proceed | Reduce minimumHealthyHosts or fix unhealthy instances |
| ECS deployment stuck | Health check failing on replacement task set | Verify target group health check path and port match container |
| ECS "replacement task set did not stabilize" | Task crashes on startup or resource limits | Check ECS task stopped reason; verify CPU/memory, image exists |
| Lambda deployment failed at BeforeAllowTraffic | Validation Lambda errored or timed out | Check Lambda logs; ensure it calls `codedeploy:PutLifecycleEventHookExecutionStatus` |

### CodeConnections

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| Connection stays PENDING | Created via CLI/CFN without console completion | Complete OAuth handshake in AWS Console |
| "Unable to use Connection" | IAM policy only has one service prefix | Add `codeconnections:UseConnection` and `codestar-connections:UseConnection` |
| Repository not found | Wrong FullRepositoryId format or no repo access | Use `org/repo` format (case-sensitive); verify app has repo access |
| Host in VPC_CONFIG_FAILED_INITIALIZATION | Network or TLS issue | Verify VPC routes to provider endpoint; validate TLS certificate |
| Cookie error during GitHub authorization | Non-owner attempting GitHub App install | Organization owner must perform the installation |

## Diagnostic Commands

```bash
# Pipeline: Get execution history
aws codepipeline list-pipeline-executions --pipeline-name NAME --max-items 5

# Pipeline: Get action execution details
aws codepipeline list-action-executions --pipeline-name NAME \
  --filter pipelineExecutionId=EXEC_ID

# Build: Get failed phase details
aws codebuild batch-get-builds --ids BUILD_ID \
  --query "builds[0].phases[?phaseStatus=='FAILED']"

# Build: Stream logs (if CloudWatch configured)
aws logs tail /aws/codebuild/PROJECT_NAME --follow

# Deploy: Get deployment target status
aws deploy list-deployment-targets --deployment-id DEPLOY_ID

# Deploy: Get lifecycle event details for failed target
aws deploy get-deployment-target --deployment-id DEPLOY_ID --target-id TARGET_ID

# Connections: List all with status
aws codeconnections list-connections --query "Connections[].[ConnectionName,ConnectionStatus]" --output table
```

## End-to-End Trace

When a pipeline fails and you don't know which service caused it:

1. `aws codepipeline get-pipeline-state --name NAME` → find failed stage/action
2. Check `latestExecution.externalExecutionId` on the failed action — this is the build ID or deployment ID
3. For build actions: `aws codebuild batch-get-builds --ids BUILD_ID`
4. For deploy actions: `aws deploy get-deployment --deployment-id DEPLOY_ID`
5. For source actions: `aws codeconnections get-connection --connection-arn ARN` (check status)

## Related

- [codepipeline.md](codepipeline.md) for pipeline-specific errors
- [codebuild.md](codebuild.md) for build configuration issues
- [codedeploy.md](codedeploy.md) for deployment strategy issues
- [codeconnections.md](codeconnections.md) for connection setup issues

## Security

- MUST NOT include secrets, credentials, or sensitive data in diagnostic commands shared with users
- Use CloudTrail to audit API calls across all CodeSuite services when investigating security incidents
- Verify IAM permissions using `aws iam simulate-principal-policy` rather than granting broad access for debugging
