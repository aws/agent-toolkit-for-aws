# Running ECS Workloads

Patterns and features for deploying and operating workloads on Amazon ECS.

## IAM Roles

### Execution Role vs Task Role

| Aspect               | Execution Role (`executionRoleArn`)                                                                                         | Task Role (`taskRoleArn`)                                       |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Used by              | ECS agent / Fargate runtime                                                                                                 | Application containers at runtime                               |
| Purpose              | Pull images, push logs, fetch secrets                                                                                       | Call AWS APIs from application code                             |
| Required for Fargate | MUST be set                                                                                                                 | SHOULD be set if the app calls AWS APIs                         |
| Common permissions   | `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`, `logs:CreateLogStream`, `logs:PutLogEvents` | Application-specific (e.g., `s3:GetObject`, `dynamodb:PutItem`) |

### Execution Role Permission Mapping

| Feature                 | Required Permission                                                                                                                                                                                                                                              |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pull from ECR           | `ecr:GetAuthorizationToken` (Resource: `"*"`), `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`. Note: the managed policy `AmazonECSTaskExecutionRolePolicy` also includes `ecr:BatchCheckLayerAvailability` but the minimal custom policy does not require it. |
| CloudWatch Logs         | `logs:CreateLogStream`, `logs:PutLogEvents`                                                                                                                                                                                                                      |
| Secrets Manager secrets | `secretsmanager:GetSecretValue`                                                                                                                                                                                                                                  |
| SSM Parameter Store     | `ssm:GetParameters`                                                                                                                                                                                                                                              |
| KMS-encrypted secrets   | `kms:Decrypt` (on the relevant KMS key)                                                                                                                                                                                                                          |

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

NOTE: Rotated secrets will not be updated in running tasks automatically, which must be recreated to retrieve the rotated secret value.

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

Fargate tasks receive ephemeral storage by default, which may be expanded and will incur additional cost. See [ecs-managing-compute.md](./ecs-managing-compute.md) for more details.

```json
"ephemeralStorage": {
  "sizeInGiB": 100
}
```

## Container Dependencies

The `dependsOn` field controls container startup and shutdown ordering.

| Condition  | Behavior                                                                              |
| ---------- | ------------------------------------------------------------------------------------- |
| `START`    | Dependency container has started.                                                     |
| `COMPLETE` | Dependency container has run to completion (exited).                                  |
| `SUCCESS`  | Dependency container has completed with exit code 0.                                  |
| `HEALTHY`  | Dependency container health check reports healthy. MUST have a `healthCheck` defined. |

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

## Stop Timeout

The `stopTimeout` field controls how long ECS waits after sending SIGTERM before sending SIGKILL.

- Default: **30 seconds**.
- Fargate maximum: **120 seconds**.
- EC2: up to **120 seconds** (configurable via `ECS_CONTAINER_STOP_TIMEOUT` agent parameter).

The operator SHOULD set `stopTimeout` to allow the application to drain connections gracefully.

```json
"stopTimeout": 60
```

## Fargate Platform Version

The operator MUST specify a valid platform version. See [the relevant documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/platform_versions.html) for valid platform versions.

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

## ECS Managed Daemons

Amazon ECS Managed Daemons let you deploy and manage software agents — such as security, observability, and networking agents — across your container infrastructure on **Amazon ECS Managed Instances**.

> **Note:** Managed Daemons is distinct from the older `DAEMON` scheduling strategy. The `DAEMON` scheduling strategy runs one task per active container instance for ECS services on the EC2 launch type and is managed as part of the service. Managed Daemons is a newer capability built specifically for ECS Managed Instances that provides stronger coverage guarantees.

### How Managed Daemons work

1. Register a **daemon task definition** — a template describing the containers that form the daemon.
1. Create a **daemon** and associate it with a cluster and one or more ECS Managed Instances capacity providers.
1. ECS then ensures that exactly one daemon task runs on every EC2 instance provisioned through those capacity providers.

Daemons do not launch instances on their own. When you run an application task on an ECS Managed Instances capacity provider, ECS provisions an EC2 instance, starts the daemon task **first**, and only then transitions the application task to `RUNNING`. This guarantees that cross-cutting functions (logging, tracing, metrics) are operational before your application begins serving requests.

### Key considerations

- **Rolling update** - updating a daemon to a new task definition revision triggers a rolling replacement of all EC2 instances in the associated capacity providers, which is an critical consideration for deployment reliability and safety. This will cause ECS to drain existing instances and provision new ones with the updated daemon.
- **Guaranteed coverage** — daemon tasks start before application tasks on every instance.
- **Automatic instance repair** — if a daemon task stops or becomes unhealthy, ECS automatically drains and replaces that container instance.
- **Deployment safety** — ECS provides built-in circuit breaker protection. You can configure a bake time and CloudWatch alarms so ECS monitors the deployment and automatically rolls back if issues arise.
- **Drain percentage** — the percentage of instances drained simultaneously during a daemon update. Defaults to `25`.
- **Bake time** — the number of minutes ECS waits after updating all instances to the new daemon revision before completing the deployment. During this period ECS monitors the configured CloudWatch alarms and automatically rolls back if any alarm triggers. IMPORTANT: Defaults to `0`.
- **Improved resource utilization** — running a single daemon task per instance eliminates the sidecar-per-task model, reducing overhead across the cluster.

See [the documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-daemons.html) for more information.
