# teardown

Remove individual resources from your project or tear down the entire deployment.

## When to use

- You want to remove a gateway, memory, credential, evaluator, or other resource from your project
- You want to delete a deployed agent and clean up all AWS resources
- You're iterating in a sandbox account and want to start fresh
- You need to remove a resource that's stuck or no longer needed

## Process

### Removing individual resources from your project

Use `agentcore remove` to remove a resource from `agentcore.json`. This marks the resource for deletion — the actual AWS resource is removed on the next `agentcore deploy`.

```bash
# Remove a memory resource
agentcore remove memory --name MyMemory

# Remove a gateway target
agentcore remove gateway-target --name WeatherTools --gateway MyGateway

# Remove a gateway (remove all its targets first)
agentcore remove gateway --name MyGateway

# Remove a credential
agentcore remove credential --name MyAPIKey

# Remove an evaluator
agentcore remove evaluator --name ResponseQuality

# Remove an online eval config
agentcore remove online-eval --name production_monitor

# Remove a policy
agentcore remove policy --name SpendingLimit --engine MyPolicyEngine

# Remove a policy engine (remove all its policies first)
agentcore remove policy-engine --name MyPolicyEngine
```

After removing, deploy to apply the changes:

```bash
agentcore deploy -y
```

Check what's pending removal before deploying:

```bash
agentcore status --state pending-removal
```

### Removing an agent from a multi-agent project

If your project has multiple agents (runtimes), you can remove one:

```bash
agentcore remove agent --name SecondAgent
agentcore deploy -y
```

This deletes the agent's runtime, endpoint, and associated resources from AWS. The agent's code in `app/<AgentName>/` is not deleted — remove it manually if you no longer need it.

### Tearing down the entire deployment

To remove all deployed AWS resources for a project:

```bash
# Preview what will be destroyed
agentcore deploy --diff

# Destroy all resources
npx cdk destroy --app "npx ts-node agentcore/cdk/bin/cdk.ts" --force
```

Alternatively, delete the CloudFormation stack directly:

```bash
# Find the stack name
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?contains(StackName, '<ProjectName>')].StackName"

# Delete it
aws cloudformation delete-stack --stack-name <StackName>

# Wait for deletion to complete
aws cloudformation wait stack-delete-complete --stack-name <StackName>
```

### What gets deleted and what doesn't

| Resource | Deleted by `cdk destroy` | Notes |
|---|---|---|
| AgentCore Runtime(s) | ✅ | Includes all endpoints and versions |
| Memory resource(s) | ✅ | Memory data is deleted permanently |
| Gateway(s) and targets | ✅ | |
| Credentials | ✅ | Secrets Manager entries are removed |
| Policy engine(s) and policies | ✅ | |
| Evaluator definitions | ✅ | |
| Online eval configs | ✅ | |
| IAM roles | ✅ | Created by CDK |
| CloudWatch log groups | ❌ | Persist after deletion — delete manually if needed |
| ECR images (Container builds) | ❌ | Persist — delete the repository manually |
| CDK bootstrap stack | ❌ | Shared across projects — don't delete unless you're done with CDK entirely |
| Local project files | ❌ | `agentcore/`, `app/` — delete manually |

### Cleaning up CloudWatch log groups

Log groups persist after stack deletion. To clean them up:

```bash
# List AgentCore log groups
aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/ \
  --query "logGroups[].logGroupName"

# Delete a specific log group
aws logs delete-log-group --log-group-name /aws/bedrock-agentcore/runtimes/<AGENT_ID>-DEFAULT
```

### Cleaning up ECR repositories (Container builds)

```bash
# List AgentCore ECR repositories
aws ecr describe-repositories \
  --query "repositories[?contains(repositoryName, 'bedrock-agentcore')].repositoryName"

# Delete a repository and all its images
aws ecr delete-repository --repository-name <repo-name> --force
```

### Handling stuck resources

If a runtime is stuck in DELETING state for more than 30 minutes, see the "Runtime stuck in DELETING" section in `agents-debug`. The short version: don't keep retrying — open an AWS Support case with the runtime ARN and the original delete request ID from CloudTrail.

## Common issues

**"Can't remove gateway — targets still attached"**
Remove all gateway targets first, then remove the gateway:

```bash
agentcore remove gateway-target --name Target1 --gateway MyGateway
agentcore remove gateway-target --name Target2 --gateway MyGateway
agentcore remove gateway --name MyGateway
```

**"Can't remove policy engine — policies still attached"**
Remove all policies first, then remove the engine:

```bash
agentcore remove policy --name Policy1 --engine MyEngine
agentcore remove policy-engine --name MyEngine
```

**"Resource shows pending-removal but deploy doesn't delete it"**
Check `agentcore status --state pending-removal` and verify the resource is listed. If deploy completes without removing it, check the CDK output for errors — the deletion may have failed silently due to a dependency.

## Output

- CLI commands to remove the specific resource(s)
- Guidance on what persists after deletion and how to clean it up
- Warnings about irreversible data loss (memory data, credentials)
