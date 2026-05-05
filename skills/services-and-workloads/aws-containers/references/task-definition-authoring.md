# Task Definition Authoring Reference

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [Fargate CPU and Memory Combinations](#fargate-cpu-and-memory-combinations)
- [Networking Modes](#networking-modes)
- [IAM Roles](#iam-roles)
- [Secrets Injection](#secrets-injection)
- [Volumes](#volumes)
- [Container Dependencies](#container-dependencies)
- [Stop Timeout](#stop-timeout)
- [Fargate Platform Version](#fargate-platform-version)
- [Minimal Fargate Task Definition Example](#minimal-fargate-task-definition-example)

---

## Verify Dependencies

Before authoring a task definition, the operator MUST confirm:

1. The target ECS cluster `$CLUSTER` exists.
2. An ECR repository or accessible image URI is available.
3. An execution role (`$EXECUTION_ROLE_ARN`) with the required permissions exists.
4. A task role (`$TASK_ROLE_ARN`) exists if the application needs AWS API access.

```bash
aws sts get-caller-identity --output json
aws ecs describe-clusters \
  --clusters "$CLUSTER" \
  --region "$REGION" \
  --output json
```

---

## Fargate CPU and Memory Combinations

Fargate enforces specific CPU/memory pairings. The operator MUST select a valid combination.

| CPU (cpu units) | Valid Memory Values (MiB)                                |
|-----------------|----------------------------------------------------------|
| 256 (.25 vCPU)  | 512, 1024, 2048                                          |
| 512 (.5 vCPU)   | 1024, 2048, 3072, 4096                                   |
| 1024 (1 vCPU)   | 2048, 3072, 4096, 5120, 6144, 7168, 8192                 |
| 2048 (2 vCPU)   | 4096 through 16384 in 1024 increments                    |
| 4096 (4 vCPU)   | 8192 through 30720 in 1024 increments                    |
| 8192 (8 vCPU)   | 16384 through 61440 in 4096 increments                   |
| 16384 (16 vCPU) | 32768 through 122880 in 8192 increments                  |

> An invalid combination causes a `ClientException` at task definition registration.

---

## Networking Modes

| Mode     | Launch Type | Description                                                    |
|----------|-------------|----------------------------------------------------------------|
| `awsvpc` | Fargate     | MUST be used for Fargate. Each task gets its own ENI.          |
| `awsvpc` | EC2         | MAY be used on EC2 for per-task ENI networking.                |
| `bridge` | EC2 only    | Docker built-in virtual network. Not available on Fargate.     |
| `host`   | EC2 only    | Maps container ports directly to the host. Not on Fargate.     |
| `none`   | EC2 only    | No external networking. Not available on Fargate.              |

The operator MUST set `networkMode` to `awsvpc` for any Fargate task definition.

---

## IAM Roles

### Execution Role vs Task Role

| Aspect              | Execution Role (`executionRoleArn`)                  | Task Role (`taskRoleArn`)                          |
|---------------------|------------------------------------------------------|----------------------------------------------------|
| Used by             | ECS agent / Fargate runtime                          | Application containers at runtime                  |
| Purpose             | Pull images, push logs, fetch secrets                | Call AWS APIs from application code                 |
| Required for Fargate| MUST be set                                          | SHOULD be set if the app calls AWS APIs             |
| Common permissions  | `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`, `logs:CreateLogStream`, `logs:PutLogEvents` | Application-specific (e.g., `s3:GetObject`, `dynamodb:PutItem`) |

### Execution Role Permission Mapping

| Feature                  | Required Permission                                      |
|--------------------------|----------------------------------------------------------|
| Pull from ECR            | `ecr:GetAuthorizationToken` (Resource: `"*"`), `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`. Note: the managed policy `AmazonECSTaskExecutionRolePolicy` also includes `ecr:BatchCheckLayerAvailability` but the minimal custom policy does not require it. |
| CloudWatch Logs          | `logs:CreateLogStream`, `logs:PutLogEvents`              |
| Secrets Manager secrets  | `secretsmanager:GetSecretValue`                          |
| SSM Parameter Store      | `ssm:GetParameters`                                      |
| KMS-encrypted secrets    | `kms:Decrypt` (on the relevant KMS key)                  |

---

## Secrets Injection

Secrets SHOULD be injected via the `secrets` field in the container definition rather than hardcoded in environment variables.

```json
"secrets": [
  {
    "name": "DB_PASSWORD",
    "valueFrom": "arn:aws:secretsmanager:$REGION:$ACCOUNT_ID:secret:$SECRET_NAME"
  },
  {
    "name": "API_KEY",
    "valueFrom": "arn:aws:ssm:$REGION:$ACCOUNT_ID:parameter/$PARAMETER_NAME"
  }
]
```

### JSON Key Extraction

To extract a specific JSON key from a Secrets Manager secret, append the key name after a trailing colon:

```json
"secrets": [
  {
    "name": "DB_PASSWORD",
    "valueFrom": "arn:aws:secretsmanager:$REGION:$ACCOUNT_ID:secret:$SECRET_NAME:password::"
  },
  {
    "name": "DB_USERNAME",
    "valueFrom": "arn:aws:secretsmanager:$REGION:$ACCOUNT_ID:secret:$SECRET_NAME:username::"
  }
]
```

The format is: `arn:...:secret:secret-name:json-key:version-stage:version-id`

Trailing colons MUST be present even when version-stage and version-id are omitted.

### Required Execution Role Permissions

The execution role MUST have:

- `secretsmanager:GetSecretValue` for Secrets Manager references.
- `ssm:GetParameters` for SSM Parameter Store references.
- `kms:Decrypt` if the secret or parameter is encrypted with a customer-managed KMS key.

---

## Volumes

### Bind Mounts

Bind mounts share data between containers in the same task. No external storage is provisioned.

```json
"volumes": [
  { "name": "shared-data" }
],
"containerDefinitions": [
  {
    "name": "writer",
    "mountPoints": [{ "sourceVolume": "shared-data", "containerPath": "/data" }]
  },
  {
    "name": "reader",
    "mountPoints": [{ "sourceVolume": "shared-data", "containerPath": "/data", "readOnly": true }]
  }
]
```

### EFS Volumes

EFS volumes require Fargate platform version `1.4.0` or later.

The security group on EFS mount targets MUST allow inbound TCP on port 2049 from the task security group.

```json
"volumes": [
  {
    "name": "efs-storage",
    "efsVolumeConfiguration": {
      "fileSystemId": "$EFS_FILE_SYSTEM_ID",
      "transitEncryption": "ENABLED",
      "authorizationConfig": {
        "accessPointId": "$EFS_ACCESS_POINT_ID",
        "iam": "ENABLED"
      }
    }
  }
]
```

Security group rule for EFS:

```json
{
  "IpProtocol": "tcp",
  "FromPort": 2049,
  "ToPort": 2049,
  "UserIdGroupPairs": [
    { "GroupId": "$TASK_SG_ID", "Description": "NFS from ECS tasks" }
  ]
}
```

### EBS Volumes

EBS volumes MAY be attached to tasks for high-performance block storage. EBS volumes are provisioned per task and are not shared across tasks.

### Ephemeral Storage

Fargate tasks receive 20 GiB of ephemeral storage by default. This MAY be expanded to 21–200 GiB via `ephemeralStorage.sizeInGiB` (platform version 1.4.0+ required). Additional storage beyond 20 GiB is billed per GB-hour.

```json
"ephemeralStorage": {
  "sizeInGiB": 100
}
```

> Ephemeral storage beyond 20 GiB incurs additional cost.

---

## Container Dependencies

The `dependsOn` field controls container startup and shutdown ordering.

| Condition   | Behavior                                                                 |
|-------------|--------------------------------------------------------------------------|
| `START`     | Dependency container has started.                                        |
| `COMPLETE`  | Dependency container has run to completion (exited).                     |
| `SUCCESS`   | Dependency container has completed with exit code 0.                     |
| `HEALTHY`   | Dependency container health check reports healthy. MUST have a `healthCheck` defined. |

```json
"containerDefinitions": [
  {
    "name": "app",
    "dependsOn": [
      { "containerName": "init", "condition": "SUCCESS" },
      { "containerName": "sidecar", "condition": "HEALTHY" }
    ]
  },
  {
    "name": "sidecar",
    "healthCheck": {
      "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
      "interval": 10,
      "timeout": 5,
      "retries": 3,
      "startPeriod": 30
    },
    "essential": true
  },
  {
    "name": "init",
    "essential": false
  }
]
```

> Using `HEALTHY` without a `healthCheck` on the dependency container causes the dependent container to never start.

---

## Stop Timeout

The `stopTimeout` field controls how long ECS waits after sending SIGTERM before sending SIGKILL.

- Default: **30 seconds**.
- Fargate maximum: **120 seconds**.
- EC2: up to **120 seconds** (configurable via `ECS_CONTAINER_STOP_TIMEOUT` agent parameter).

The operator SHOULD set `stopTimeout` to allow the application to drain connections gracefully.

```json
"stopTimeout": 60
```

---

## Fargate Platform Version

The operator MUST use platform version `LATEST` or `1.4.0` for new task definitions.

| Version | Status                                      |
|---------|---------------------------------------------|
| LATEST  | Recommended. Currently resolves to `1.4.0`. |
| 1.4.0   | Stable. Required for EFS, ECS Exec, ephemeral storage expansion. |
| 1.3.0   | **Retired June 15, 2026** (no new tasks/services). **Terminated June 30, 2026** (all running tasks killed). MUST NOT be used for new workloads. Existing tasks MUST be migrated before June 30, 2026. |

---

## Minimal Fargate Task Definition Example

```json
{
  "family": "$TASK_FAMILY",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "$EXECUTION_ROLE_ARN",
  "taskRoleArn": "$TASK_ROLE_ARN",
  "runtimePlatform": {
    "cpuArchitecture": "X86_64",
    "operatingSystemFamily": "LINUX"
  },
  "containerDefinitions": [
    {
      "name": "$CONTAINER_NAME",
      "image": "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8080,
          "protocol": "tcp"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/$TASK_FAMILY",
          "awslogs-region": "$REGION",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Register the task definition:

```bash
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region "$REGION" \
  --output json
```
