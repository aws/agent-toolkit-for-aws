# ECS Troubleshooting

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [Exit Code Reference](#exit-code-reference)
- [OOM Kills Deep Dive](#oom-kills-deep-dive)
- [Task Placement Failures](#task-placement-failures)
- [Health Check Debugging Checklist](#health-check-debugging-checklist)
- [Image Pull Errors](#image-pull-errors)
- [Private Subnet Networking](#private-subnet-networking)
- [ENI Trunking for EC2 awsvpc Density](#eni-trunking-for-ec2-awsvpc-density)
- [Security Considerations](#security-considerations)

---

## Verify Dependencies

Operators MUST confirm the following before proceeding:

| Dependency | Check Command |
|---|---|
| Correct account/region | `aws sts get-caller-identity --output json` |
| ECS cluster exists | `aws ecs describe-clusters --clusters $CLUSTER --region $REGION --output json` |
| Sufficient IAM permissions | Caller MUST have `ecs:Describe*`, `ecs:List*`, `logs:GetLogEvents` at minimum |

---

## Exit Code Reference

| Exit Code | Signal | Meaning | Common Cause |
|---|---|---|---|
| 0 | — | Normal exit | Application completed successfully |
| 1 | — | Application error | Unhandled exception, startup failure, config error |
| 134 | SIGABRT | Abort | `abort()` called, assertion failure, corrupted heap |
| 137 | SIGKILL | Killed | **OOM kill** or **SIGTERM timeout** (container did not exit within `stopTimeout` and was forcefully killed). Also: manual `docker kill`. |
| 139 | SIGSEGV | Segmentation fault | Null pointer dereference, memory corruption, native library crash |
| 143 | SIGTERM | Graceful termination | Container handled SIGTERM and exited on its own during ECS task stop, scaling in, or deployment replacement |

### Key Diagnostic Rules

- Exit code **137** means the container received SIGKILL. Check `stoppedReason` from `describe-tasks` first: if it contains "OutOfMemoryError", investigate OOM — see [OOM Kills Deep Dive](#oom-kills-deep-dive). If the task was being stopped (deployment, scale-in) and `stoppedReason` does NOT mention OOM, the container likely did not handle SIGTERM within `stopTimeout` — add a SIGTERM handler and verify `stopTimeout` is sufficient.
- Exit code **143** is expected during normal operations (deployments, scale-in). It means the container handled SIGTERM gracefully. It is NOT an error.
- Exit code **1** requires application log analysis — check CloudWatch Logs for the container's last output.

---

## OOM Kills Deep Dive

Exit code 137 commonly indicates the container exceeded its memory limit and was killed by the kernel (OOM killer) or the Docker daemon. It can also occur when a container does not exit within `stopTimeout` after receiving SIGTERM.

### Container Memory Hard Limit vs Task-Level Memory

| Scope | Setting | Behavior |
|---|---|---|
| **Container hard limit** (`memory` in container definition) | Per-container ceiling | Container is killed immediately when it exceeds this limit |
| **Container soft limit** (`memoryReservation`) | Per-container reservation | Used for task placement; container MAY exceed this up to the hard limit |
| **Task-level memory** (`memory` in task definition) | Total for all containers | On Fargate, this is the only **required** memory setting. Container-level `memory` hard limits are optional but enforced if set. Without per-container limits, all containers share this pool. |

On Fargate, the task-level memory is the overall ceiling. If a container definition sets a `memory` hard limit, Fargate enforces it — the container is killed if it exceeds that limit. If no per-container `memory` is set, a single container MAY consume all task memory, starving sidecars.

### Diagnosing OOM Kills

```bash
# Step 1: Describe the stopped task to find the stop reason
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ID \
  --region $REGION \
  --output json \
  --query 'tasks[0].{stopCode:stopCode,stoppedReason:stoppedReason,containers:containers[*].{name:name,exitCode:exitCode,reason:reason}}'
```

Look for:

- `stoppedReason` containing "OutOfMemoryError" or "oom"
- Container `reason` containing "OutOfMemoryError: Container killed due to memory usage"
- `exitCode: 137` on the affected container

### JVM Fix: Use MaxRAMPercentage Instead of Fixed Xmx

```bash
# Fixed heap — works but does not adapt when container memory changes
java -Xmx512m -jar app.jar

# Container-aware — heap scales automatically with container memory limit
java -XX:MaxRAMPercentage=75.0 -jar app.jar
```

- In containerized environments, `-XX:MaxRAMPercentage` is preferred over fixed `-Xmx` because the heap scales automatically when the container memory limit changes. Fixed `-Xmx` values also work but require manual adjustment and must account for non-heap memory.
- A starting value of 75.0 leaves ~25% for JVM non-heap memory (metaspace, thread stacks, direct buffers, GC overhead). Workloads with many threads or large direct buffers may need a lower percentage (e.g., 50–70%); simple applications may safely use 80% or higher.
- On Fargate (Platform 1.4+), HotSpot-based JVMs (OpenJDK, Corretto, Temurin) correctly detect the task memory limit via cgroup. OpenJ9 has a known bug where it may not detect the limit correctly ([openj9#11998](https://github.com/eclipse-openj9/openj9/issues/11998)) — set container-level `memory` as a workaround if using OpenJ9.

### Quick Memory Check

```bash
# Check memory utilization for running tasks in a service
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE_NAME \
  --region $REGION \
  --output json \
  --query 'services[0].{desiredCount:desiredCount,runningCount:runningCount,deployments:deployments[*].{status:status,desiredCount:desiredCount,runningCount:runningCount,failedTasks:failedTasks}}'
```

---

## Task Placement Failures

When ECS cannot place a task, the service event log shows the reason. Common failures:

| Error Message | Cause | Resolution |
|---|---|---|
| `no container instances were found in your cluster` | EC2 launch type: no instances registered | Register EC2 instances to the cluster or switch to Fargate |
| `...has insufficient CPU units available` | EC2: closest matching instance lacks free CPU units for the task | Add larger instances, reduce task CPU, or enable more instances via ASG |
| `...was unable to place a task because no container instance met all of its requirements` (cause: Not enough memory) | EC2: instances lack free memory for the task | Add larger instances, reduce task memory, or enable more instances via ASG |
| `RESOURCE:ENI` | `awsvpc` mode: instance ENI limit reached | Enable ENI trunking (see [ENI Trunking](#eni-trunking-for-ec2-awsvpc-density)) or use more/larger instances |
| `RESOURCE:PORTS` | `bridge`/`host` mode: requested host port already in use | Use dynamic port mapping, reduce tasks per instance, or switch to `awsvpc` |
| `...was unable to place a task because no container instance met all of its requirements` (generic — check service events for specific sub-cause) | Multiple possible causes: placement constraints, missing attributes, insufficient resources, or wrong subnet for `awsvpc` | Run `describe-services` to see events; check placement constraints, instance attributes, subnet configuration, and resource availability |

### Diagnosing Placement Failures

```bash
# Check service events for placement failure messages
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE_NAME \
  --region $REGION \
  --output json \
  --query 'services[0].events[:10]'
```

---

## Health Check Debugging Checklist

When tasks are being killed by ALB health checks, follow these steps in order:

### Step 1: Verify the Health Check Endpoint Responds Locally

Confirm the application responds on the health check path and port. Use ECS Exec if available:

```bash
aws ecs execute-command \
  --cluster $CLUSTER \
  --task $TASK_ID \
  --container $CONTAINER_NAME \
  --interactive \
  --command "curl -s -o /dev/null -w '%{http_code}' http://localhost:$CONTAINER_PORT/health" \
  --region $REGION
```

### Step 2: Check healthCheckGracePeriod

If tasks are killed before the application finishes starting, `healthCheckGracePeriod` is too low or not set.

```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE_NAME \
  --region $REGION \
  --output json \
  --query 'services[0].healthCheckGracePeriodSeconds'
```

This value MUST be greater than the application startup time. Operators SHOULD set it to at least 60 seconds.

### Step 3: Verify Target Group Health Check Settings

```bash
aws elbv2 describe-target-health \
  --target-group-arn $TARGET_GROUP_ARN \
  --region $REGION \
  --output json
```

Check that:

- Health check path matches the application's actual health endpoint.
- Health check port matches the container port (or is set to `traffic-port`).
- Healthy threshold, interval, and timeout are reasonable.

### Step 4: Check Security Group Rules

The ALB security group MUST be allowed to reach the container port on the task security group.

```bash
aws ec2 describe-security-groups \
  --group-ids $TASK_SG_ID \
  --region $REGION \
  --output json \
  --query 'SecurityGroups[0].IpPermissions'
```

### Step 5: Check Container Logs for Startup Errors

```bash
aws logs get-log-events \
  --log-group-name $LOG_GROUP \
  --log-stream-name "$STREAM_PREFIX/$CONTAINER_NAME/$TASK_ID" \
  --limit 50 \
  --region $REGION \
  --output json
```

### Step 6: Verify the Container Is Listening on the Correct Interface

The application MUST listen on `0.0.0.0` (all interfaces), not `127.0.0.1` (localhost only). In `awsvpc` mode, the ALB health check comes from the ALB's IP, not localhost.

---

## Image Pull Errors

| Error | Cause | Resolution |
|---|---|---|
| `CannotPullContainerError: pull image manifest has been retried N time(s)` | Image/tag resolution failure — image name or tag doesn't match repository, or image version stability enforcement removed the original image. Can also be caused by network connectivity issues. | 1. Verify image URI and tag match the repository. 2. Avoid `:latest` — use a specific tag. 3. If image is correct, check VPC endpoints (private subnet) or NAT gateway (public subnet). |
| `AccessDeniedException` or `is not authorized to perform ecr:GetAuthorizationToken` | Execution role lacks ECR permissions | Attach `AmazonECSTaskExecutionRolePolicy` to the execution role |
| `invalid reference format` | Malformed image URI (typo, missing tag, wrong registry) | Verify image URI: `$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:$TAG` |
| `manifest unknown` or `manifest for $IMAGE not found` | Image tag does not exist in the repository | Verify the tag exists: `aws ecr describe-images --repository-name $REPO --image-ids imageTag=$TAG --region $REGION --output json` |
| `no space left on device` | Disk full — on EC2: instance storage exhausted. On Fargate: image exceeds ephemeral storage (default 20 GiB). | EC2: clean unused images (`docker system prune`) or increase instance storage. Fargate: increase `ephemeralStorage` in task definition (up to 200 GiB). |
| `CannotPullContainerError: ref pull has been retried ... httpReaderSeeker: failed open` | ECR image layers stored in S3 — S3 endpoint missing | Add S3 gateway endpoint to VPC |

### Diagnosing Image Pull Failures

```bash
# Check stopped task for pull error details
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ID \
  --region $REGION \
  --output json \
  --query 'tasks[0].containers[*].{name:name,reason:reason,lastStatus:lastStatus}'
```

---

## Private Subnet Networking

When ECS tasks run in private subnets (no internet gateway route), the following VPC endpoints are required:

### Required Endpoints (Minimum for ECS Fargate)

| Endpoint | Service Name | Type | Purpose |
|---|---|---|---|
| ECR Docker | `com.amazonaws.$REGION.ecr.dkr` | Interface | Pull container images |
| ECR API | `com.amazonaws.$REGION.ecr.api` | Interface | ECR authentication |
| CloudWatch Logs | `com.amazonaws.$REGION.logs` | Interface | Container log delivery |
| S3 | `com.amazonaws.$REGION.s3` | Gateway | ECR image layer storage |

### Additional Endpoints by Feature

| Endpoint | Service Name | Type | When Required |
|---|---|---|---|
| SSM Messages | `com.amazonaws.$REGION.ssmmessages` | Interface | ECS Exec (`execute-command`) |
| Secrets Manager | `com.amazonaws.$REGION.secretsmanager` | Interface | Secrets referenced in task definition |
| SSM Parameter Store | `com.amazonaws.$REGION.ssm` | Interface | SSM parameters referenced in task definition |

### Verifying Endpoint Connectivity

```bash
# List VPC endpoints in the VPC
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --region $REGION \
  --output json \
  --query 'VpcEndpoints[*].{ServiceName:ServiceName,State:State,VpcEndpointType:VpcEndpointType}'
```

Operators MUST verify:

1. Endpoints are in `available` state.
2. Interface endpoints have security groups that allow inbound HTTPS (port 443) from the task security group.
3. Interface endpoints are associated with the same subnets as the ECS tasks.
4. The S3 gateway endpoint route table is associated with the task subnets.

---

## ENI Trunking for EC2 awsvpc Density

By default, each ECS task using `awsvpc` network mode on EC2 consumes one ENI on the host instance. This limits the number of tasks per instance to the instance's ENI limit minus one (reserved for the host).

ENI trunking allows multiple tasks to share a trunk ENI, significantly increasing task density.

### Enabling ENI Trunking

```bash
# Enable for the entire account (all clusters in the region)
aws ecs put-account-setting-default \
  --name awsvpcTrunking \
  --value enabled \
  --region $REGION \
  --output json
```

```bash
# Or enable for a specific IAM user/role only
aws ecs put-account-setting \
  --name awsvpcTrunking \
  --value enabled \
  --principal-arn $PRINCIPAL_ARN \
  --region $REGION \
  --output json
```

### Requirements

- Instance MUST be launched **after** the setting is enabled. Existing instances are NOT affected.
- Instance type MUST support ENI trunking (most `c5`, `m5`, `r5` and newer generation types).
- The ECS agent on the instance MUST be version 1.28.1 or later, with `ecs-init` version 1.28.1-2 or later.

### Verifying ENI Trunking

```bash
# Check account setting
aws ecs list-account-settings \
  --name awsvpcTrunking \
  --effective-settings \
  --region $REGION \
  --output json
```

```bash
# Check instance ENI attachment (look for trunk ENI)
aws ecs describe-container-instances \
  --cluster $CLUSTER \
  --container-instances $CONTAINER_INSTANCE_ID \
  --region $REGION \
  --output json \
  --query 'containerInstances[0].{attachments:attachments,remainingResources:remainingResources}'
```

### Task Density Comparison (Example: c5.large)

| Setting | Max ENIs | Tasks per Instance (awsvpc) |
|---|---|---|
| Trunking **disabled** | 3 | 2 (3 ENIs - 1 for host) |
| Trunking **enabled** | 12 (trunk + branch ENIs) | 10 (12 - 1 primary - 1 trunk = 10 branch) |

Exact limits vary by instance type — see [Supported instance types for ENI trunking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/container-instance-eni.html).

Operators SHOULD enable ENI trunking for any EC2 cluster using `awsvpc` network mode to avoid `RESOURCE:ENI` placement failures.

---

## Security Considerations

- The troubleshooting commands in this guide require read-only permissions (`ecs:Describe*`, `ecs:List*`, `logs:GetLogEvents`, `ec2:DescribeSecurityGroups`, `ec2:DescribeVpcEndpoints`, `elbv2:DescribeTargetHealth`). Do not grant broader permissions for debugging.
- ECS Exec (`execute-command`) provides shell access to running containers. Restrict `ssmmessages:*` permissions to authorized operators only and audit usage via CloudTrail.
- VPC endpoint security groups MUST restrict inbound HTTPS (port 443) to the task security group — do not use `0.0.0.0/0`.
- When reviewing container logs for errors, be aware that application logs may contain sensitive data. Use CloudWatch Logs encryption with a KMS key for log groups containing sensitive output.
- The `0.0.0.0` listen address in Health Check Step 6 refers to the container's network interface binding, not a security group rule. In `awsvpc` mode, each task has its own ENI and the ALB health check arrives from the ALB's IP, requiring the application to listen on all interfaces.
