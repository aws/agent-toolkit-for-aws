# CodeDeploy

## Deployment Strategy Comparison

| Strategy | EC2/On-Premises | ECS | Lambda | Best For |
|----------|----------------|-----|--------|----------|
| In-place | Yes | No | No | Simple apps with acceptable downtime |
| Blue/green | Yes (new ASG) | Yes (task set swap) | Yes (alias shift) | Zero-downtime with instant rollback |
| Canary | No | Yes | Yes | High-risk changes needing validation window |
| Linear | No | Yes | Yes | Gradual rollout with steady monitoring |
| All-at-once | Yes | Yes | Yes | Non-production or low-risk changes |

**Recommendation**: Blue/green for production EC2. Canary for ECS/Lambda production where you need a validation window.

## EC2/On-Premises

### appspec.yml

```yaml
version: 0.0
os: linux
files:
  - source: /
    destination: /opt/myapp
    overwrite: true
permissions:
  - object: /opt/myapp/bin
    pattern: "*.sh"
    owner: appuser
    mode: 755
    type:
      - file
hooks:
  ApplicationStop:
    - location: scripts/stop.sh
      timeout: 120
      runas: appuser
  BeforeInstall:
    - location: scripts/before_install.sh
      timeout: 300
  AfterInstall:
    - location: scripts/after_install.sh
      timeout: 300
  ApplicationStart:
    - location: scripts/start.sh
      timeout: 120
  ValidateService:
    - location: scripts/validate.sh
      timeout: 300
```

### EC2 Lifecycle Hooks (Ordered)

**In-place deployment:**

1. **ApplicationStop** — Runs PREVIOUS revision's stop script
2. **DownloadBundle** — Agent-only; downloads revision
3. **BeforeInstall** — Setup tasks (create dirs, decrypt)
4. **Install** — Agent-only; copies files per `files` section
5. **AfterInstall** — Post-install config (permissions, config generation)
6. **ApplicationStart** — Start services
7. **ValidateService** — Health checks, smoke tests

**Additional hooks when a load balancer is configured (both in-place and blue/green):**

1. **BeforeBlockTraffic** — Pre-deregistration on original instances
2. **BlockTraffic** — Agent-only; deregisters from ELB
3. **AfterBlockTraffic** — Cleanup on original instances
4. *(Standard hooks 1-7 on replacement instances)*
5. **BeforeAllowTraffic** — Pre-registration on replacement instances
6. **AllowTraffic** — Agent-only; registers with ELB
7. **AfterAllowTraffic** — Post-registration validation

### EC2 Deployment Configurations

| Configuration | Behavior |
|---------------|----------|
| CodeDeployDefault.OneAtATime | One instance at a time |
| CodeDeployDefault.HalfAtATime | Up to half simultaneously |
| CodeDeployDefault.AllAtOnce | All simultaneously |
| Custom | Specify HOST_COUNT or FLEET_PERCENT threshold |

### EC2 Pitfalls

**ApplicationStop uses PREVIOUS revision's scripts**: Broken stop scripts block ALL future deployments. Fix: deploy a revision that only fixes the stop script, or remove `/opt/codedeploy-agent/deployment-root/` on affected instances and restart agent.

**file_exists_behavior unset**: Redeploys fail with "file already exists." Always set in CreateDeployment: `OVERWRITE`, `RETAIN`, or `DISALLOW`.

**Auto Scaling loop**: Failed deployments on new instances cause infinite provision-terminate cycle. Fix: suspend `Launch` on ASG, fix deployment, resume.

**MinimumHealthyHosts miscalculation**: Setting 90% on 3 instances = 2.7 rounded to 3 — deployment can never proceed. Ensure at least one instance can be taken offline.

## ECS (Blue/Green)

ECS deployments always use blue/green. CodeDeploy creates a replacement task set, optionally routes test traffic, then shifts production traffic.

### appspec.yml (ECS)

```yaml
version: 0.0
Resources:
  - TargetService:
      Type: AWS::ECS::Service
      Properties:
        TaskDefinition: "arn:aws:ecs:REGION:ACCOUNT:task-definition/my-task:3"
        LoadBalancerInfo:
          ContainerName: "my-container"
          ContainerPort: 8080
        PlatformVersion: "LATEST"
Hooks:
  - BeforeInstall: "arn:aws:lambda:REGION:ACCOUNT:function:BeforeInstallHook"
  - AfterInstall: "arn:aws:lambda:REGION:ACCOUNT:function:AfterInstallHook"
  - AfterAllowTestTraffic: "arn:aws:lambda:REGION:ACCOUNT:function:TestTrafficHook"
  - BeforeAllowTraffic: "arn:aws:lambda:REGION:ACCOUNT:function:BeforeTrafficHook"
  - AfterAllowTraffic: "arn:aws:lambda:REGION:ACCOUNT:function:AfterTrafficHook"
```

### ECS Lifecycle Hooks (Ordered)

1. **BeforeInstall** — Lambda (scriptable)
2. **Install** — Agent-only; creates replacement task set, waits for stability
3. **AfterInstall** — Lambda (scriptable); validate replacement task set
4. **AllowTestTraffic** — Agent-only; routes test listener to replacement target group
5. **AfterAllowTestTraffic** — Lambda (scriptable); test via test traffic port
6. **BeforeAllowTraffic** — Lambda (scriptable); pre-cutover gate
7. **AllowTraffic** — Agent-only; shifts production traffic per config
8. **AfterAllowTraffic** — Lambda (scriptable); post-cutover validation

Scriptable hooks: BeforeInstall, AfterInstall, AfterAllowTestTraffic, BeforeAllowTraffic, AfterAllowTraffic. All invoke Lambda functions (not shell scripts).

### ECS Deployment Configurations

| Configuration | Behavior |
|---------------|----------|
| CodeDeployDefault.ECSAllAtOnce | 100% immediately |
| CodeDeployDefault.ECSCanary10Percent5Minutes | 10% for 5 min, then 100% |
| CodeDeployDefault.ECSCanary10Percent15Minutes | 10% for 15 min, then 100% |
| CodeDeployDefault.ECSLinear10PercentEvery1Minutes | 10% every 1 min |
| CodeDeployDefault.ECSLinear10PercentEvery3Minutes | 10% every 3 min |

### ECS Pitfalls

**Lifecycle hook 1-hour timeout**: CodeDeploy waits up to 3600s for the `PutLifecycleEventHookExecutionStatus` callback. This is the CodeDeploy hook timeout, not the Lambda execution timeout (which is max 900s). If the Lambda doesn't call back within 1 hour, the hook fails.

**Test listener required for AfterAllowTestTraffic**: Without a test listener on the ALB, this hook is skipped — no pre-production validation window.

**Original task set termination**: Configure `terminationWaitTimeInMinutes` on deployment group. Default is 0 — original tasks terminated immediately after shift (no manual rollback window).

## Lambda

Traffic shifts between two function versions using an alias.

### appspec.yml (Lambda)

```yaml
version: 0.0
Resources:
  - MyFunction:
      Type: AWS::Lambda::Function
      Properties:
        Name: "my-function"
        Alias: "live"
        CurrentVersion: "1"
        TargetVersion: "2"
Hooks:
  - BeforeAllowTraffic: "arn:aws:lambda:REGION:ACCOUNT:function:PreTrafficHook"
  - AfterAllowTraffic: "arn:aws:lambda:REGION:ACCOUNT:function:PostTrafficHook"
```

### Lambda Lifecycle Hooks

1. **BeforeAllowTraffic** — Validate new version (invoke directly, run tests)
2. **AllowTraffic** — Agent-only; shifts alias traffic per config
3. **AfterAllowTraffic** — Validate production behavior post-shift

### Lambda Deployment Configurations

| Configuration | Behavior |
|---------------|----------|
| CodeDeployDefault.LambdaAllAtOnce | 100% immediately |
| CodeDeployDefault.LambdaCanary10Percent5Minutes | 10% for 5 min, then 100% |
| CodeDeployDefault.LambdaCanary10Percent10Minutes | 10% for 10 min, then 100% |
| CodeDeployDefault.LambdaLinear10PercentEvery1Minute | 10% every 1 min |
| CodeDeployDefault.LambdaLinear10PercentEvery2Minutes | 10% every 2 min |
| CodeDeployDefault.LambdaLinear10PercentEvery10Minutes | 10% every 10 min |

## Rollback Configuration

```bash
aws deploy update-deployment-group \
  --application-name MyApp \
  --deployment-group-name MyDG \
  --auto-rollback-configuration enabled=true,events=DEPLOYMENT_FAILURE,DEPLOYMENT_STOP_ON_ALARM
```

| Trigger | When |
|---------|------|
| DEPLOYMENT_FAILURE | Any deployment fails |
| DEPLOYMENT_STOP_ON_ALARM | CloudWatch alarm breaches during deployment |
| DEPLOYMENT_STOP_ON_REQUEST | Manual stop triggers rollback |

ECS/Lambda: rollback re-routes traffic to original task set/version. EC2: rollback creates a NEW deployment with last known good revision.

Manual rollback: `aws deploy stop-deployment --deployment-id ID --auto-rollback-enabled`

**Recommendation**: Always enable DEPLOYMENT_STOP_ON_ALARM with error rate + latency alarms for production.

## Creating Deployment Groups

### EC2 Deployment Group

```bash
aws deploy create-deployment-group \
  --application-name MyApp \
  --deployment-group-name MyDG \
  --deployment-config-name CodeDeployDefault.OneAtATime \
  --ec2-tag-filters Key=Environment,Value=MyEnvironment,Type=KEY_AND_VALUE \
  --service-role-arn arn:aws:iam::ACCOUNT:role/CodeDeployServiceRole \
  --auto-rollback-configuration enabled=true,events=DEPLOYMENT_FAILURE,DEPLOYMENT_STOP_ON_ALARM
```

### ECS Deployment Group

```bash
aws deploy create-deployment-group \
  --application-name MyECSApp \
  --deployment-group-name MyECSDG \
  --deployment-config-name CodeDeployDefault.ECSCanary10Percent5Minutes \
  --service-role-arn arn:aws:iam::ACCOUNT:role/CodeDeployECSRole \
  --ecs-services serviceName=my-service,clusterName=my-cluster \
  --load-balancer-info "targetGroupPairInfoList=[{targetGroups=[{name=tg-blue},{name=tg-green}],prodTrafficRoute={listenerArns=[ALB_LISTENER_ARN]},testTrafficRoute={listenerArns=[TEST_LISTENER_ARN]}}]"
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| "no instances were found" | Tag filters match zero instances | Verify EC2 tags match deployment group filters |
| "too many individual instances failed" | MinimumHealthyHosts impossible | Recalculate threshold for fleet size |
| "file already exists" | file_exists_behavior not set | Set OVERWRITE in CreateDeployment |
| "agent was not able to receive the lifecycle event" | Agent not running | `sudo service codedeploy-agent status` |
| "HEALTH_CONSTRAINTS" | Not enough healthy instances | Reduce minimumHealthyHosts or fix failing instances |

## Security

- Scope CodeDeploy service role to specific deployment groups and S3 artifact paths
- Encrypt deployment artifacts in S3 (SSE-KMS recommended)
- Enable CloudTrail for `codedeploy:*` API auditing
- MUST NOT log secrets in appspec hook scripts (stdout is captured in deployment logs)
- Encrypt CloudWatch Logs groups for CodeDeploy event logs with KMS
- Configure CloudWatch alarms on error rate/latency metrics for use with `DEPLOYMENT_STOP_ON_ALARM`
- See [CodeDeploy security best practices](https://docs.aws.amazon.com/codedeploy/latest/userguide/security-best-practices.html)

## Related

- [codepipeline.md](codepipeline.md) for CodeDeploy action in pipelines
- [troubleshooting.md](troubleshooting.md) for additional error patterns
