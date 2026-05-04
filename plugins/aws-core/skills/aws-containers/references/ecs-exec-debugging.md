# ECS Exec Debugging Reference

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [Enable ECS Exec on a Service](#enable-ecs-exec-on-a-service)
- [Task Role SSM Permissions](#task-role-ssm-permissions)
- [Caller IAM Permissions](#caller-iam-permissions)
- [Run an Interactive Command](#run-an-interactive-command)
- [Common Errors](#common-errors)
- [Session Logging](#session-logging)
- [Considerations and Limitations](#considerations-and-limitations)
- [Security Considerations](#security-considerations)

---

## Verify Dependencies

Before using ECS Exec, the operator MUST confirm:

1. The **Session Manager plugin** is installed locally. Verify with:

   ```bash
   session-manager-plugin
   ```

   If installed, this returns: `The Session Manager plugin is installed successfully. Use the AWS CLI to start a session.`
2. The ECS service uses Fargate platform version **1.4.0** or later (Linux) or **1.0.0** (Windows), or EC2 with ECS agent 1.50.2+.
3. The task role has SSM permissions (see below).
4. The container image includes `/bin/sh` (or the shell specified in the `--command` flag).

**Constraints for parameter acquisition:**

- You MUST verify all required parameters (`$CLUSTER`, `$SERVICE`) are provided. If any are missing, ask for them upfront in a single prompt.
- If all required parameters are provided, proceed to enable ECS Exec — do not ask the user to confirm what they already specified.
- For `$TASK_ID` and `$CONTAINER`, you SHOULD discover them via `aws ecs list-tasks` and `aws ecs describe-tasks` if not provided, inform the user what you found, and proceed.

```bash
aws sts get-caller-identity --output json
aws ecs describe-services \
  --cluster "$CLUSTER" \
  --services "$SERVICE_NAME" \
  --region "$REGION" \
  --query "services[0].platformVersion" \
  --output json
```

---

## Enable ECS Exec on a Service

ECS Exec MUST be enabled on the service. Enabling it on an existing service requires `--force-new-deployment` to replace running tasks with new tasks that have the SSM agent binaries bind-mounted into the container.

```bash
aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE_NAME" \
  --enable-execute-command \
  --force-new-deployment \
  --region "$REGION" \
  --output json
```

Verify that `enableExecuteCommand` is `true`:

```bash
aws ecs describe-services \
  --cluster "$CLUSTER" \
  --services "$SERVICE_NAME" \
  --region "$REGION" \
  --query "services[0].enableExecuteCommand" \
  --output json
```

> The `--force-new-deployment` flag triggers a rolling replacement of all tasks. The operator SHOULD perform this during a maintenance window for services with tight availability requirements.

---

## Task Role SSM Permissions

The **task role** (not the execution role) MUST have the following SSM permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel"
      ],
      "Resource": "*"
    }
  ]
}
```

If session logging is enabled (see [Session Logging](#session-logging)), the task role MUST also have permissions for the logging destination:

- **CloudWatch Logs:**
  - `logs:DescribeLogGroups` (Resource: `*`)
  - `logs:CreateLogStream` (on the log group ARN)
  - `logs:DescribeLogStreams` (on the log group ARN)
  - `logs:PutLogEvents` (on the log group ARN)
- **S3:**
  - `s3:GetBucketLocation` (Resource: `*`)
  - `s3:GetEncryptionConfiguration` (on the bucket ARN)
  - `s3:PutObject` (on the bucket ARN/`*`)
- **KMS (if encrypted):** `kms:Decrypt` on the KMS key.

---

## Caller IAM Permissions

The IAM principal running `ecs execute-command` MUST have:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ecs:ExecuteCommand",
      "Resource": [
        "arn:aws:ecs:$REGION:$ACCOUNT_ID:task/$CLUSTER/*",
        "arn:aws:ecs:$REGION:$ACCOUNT_ID:cluster/$CLUSTER"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "ecs:DescribeTasks",
      "Resource": "arn:aws:ecs:$REGION:$ACCOUNT_ID:task/$CLUSTER/*"
    }
  ]
}
```

> **Least-privilege tip:** Use condition keys such as `ecs:cluster`, `ecs:container-name`, `ecs:task`, `ecs:ResourceTag/${TagKey}`, and `aws:ResourceTag/${TagKey}` to further restrict which clusters, containers, or tagged tasks a principal can exec into. See [Using IAM policies to limit access to ECS Exec](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html).
> **KMS encryption:** If the cluster's `executeCommandConfiguration` specifies a `kmsKeyId`, the caller MUST also have `kms:GenerateDataKey` on that KMS key ARN.

---

## Run an Interactive Command

```bash
aws ecs execute-command \
  --cluster "$CLUSTER" \
  --task "$TASK_ID" \
  --container "$CONTAINER_NAME" \
  --interactive \
  --command "/bin/sh" \
  --region "$REGION"
```

For a specific diagnostic command (single command, not a shell):

```bash
aws ecs execute-command \
  --cluster "$CLUSTER" \
  --task "$TASK_ID" \
  --container "$CONTAINER_NAME" \
  --interactive \
  --command "cat /etc/resolv.conf" \
  --region "$REGION"
```

> Amazon ECS only supports initiating interactive sessions, so the `--interactive` flag is always required.

---

## Common Errors

> **Tip:** Use the [ECS Exec Checker](https://github.com/aws-containers/amazon-ecs-exec-checker) script to verify that your cluster and task meet all prerequisites for ECS Exec. It checks your AWS CLI environment, cluster, and task configuration.

### TargetNotConnectedException

This is the most common error. It means the SSM agent in the task cannot establish a connection.

**Debugging steps (check in order):**

1. **SSM agent startup delay** — After a new deployment with `--enable-execute-command`, the SSM agent inside the task needs time to start and register. Verify the agent is running by checking that `ExecuteCommandAgent` `lastStatus` is `RUNNING` in `describe-tasks` output before retrying. In practice, this typically takes 30–60 seconds after the task reaches `RUNNING` status.

2. **Private subnet networking** — If the task runs in a private subnet, it MUST have a route to the `ssmmessages` endpoint. Either:
   - A NAT gateway in the route table, OR
   - A VPC interface endpoint for `com.amazonaws.$REGION.ssmmessages` with a security group allowing inbound HTTPS (port 443) from the task security group. Do NOT use `0.0.0.0/0` — scope the inbound rule to the task security group or the VPC CIDR.

   ```bash
   aws ec2 describe-vpc-endpoints \
     --filters Name=service-name,Values="com.amazonaws.$REGION.ssmmessages" \
     --region "$REGION" \
     --output json
   ```

3. **Task role permissions** — Verify the task role has all four `ssmmessages:*` actions. A missing permission causes a silent connection failure.

   ```bash
   aws iam list-attached-role-policies \
     --role-name "$TASK_ROLE_NAME" \
     --output json

   aws iam list-role-policies \
     --role-name "$TASK_ROLE_NAME" \
     --output json
   ```

4. **Platform version** — Confirm the task is running on Fargate platform version `1.4.0` or later:

   ```bash
   aws ecs describe-tasks \
     --cluster "$CLUSTER" \
     --tasks "$TASK_ID" \
     --region "$REGION" \
     --query "tasks[0].platformVersion" \
     --output json
   ```

5. **Container has a shell** — The container image MUST include `/bin/sh`. Minimal or distroless images may not have a shell. Use a debug sidecar or rebuild the image with a shell for debugging.

### InvalidParameterException: Execute command not enabled

The service does not have ECS Exec enabled. Run `update-service` with `--enable-execute-command --force-new-deployment`.

### SessionManagerPlugin is not found

The Session Manager plugin is not installed or not in the system PATH. Install it from the [AWS documentation](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html).

---

## Session Logging

ECS Exec sessions SHOULD be logged to S3 or CloudWatch Logs for audit purposes. AWS CloudTrail automatically records `ExecuteCommand` API calls, but session content (commands and output) is only captured when logging is explicitly configured below.

> The container image requires `script` and `cat` to be installed in order to have command logs uploaded correctly to Amazon S3 or CloudWatch Logs. Some minimal or distroless images may not include these utilities.

### Configure Logging

```bash
aws ecs create-cluster \
  --cluster-name "$CLUSTER" \
  --configuration '{
    "executeCommandConfiguration": {
      "kmsKeyId": "$KMS_KEY_ID",
      "logging": "OVERRIDE",
      "logConfiguration": {
        "cloudWatchLogGroupName": "/ecs/exec/$CLUSTER",
        "cloudWatchEncryptionEnabled": true,
        "s3BucketName": "$LOGGING_BUCKET",
        "s3EncryptionEnabled": true,
        "s3KeyPrefix": "ecs-exec-logs"
      }
    }
  }' \
  --region "$REGION" \
  --output json
```

> **Security:** The `kmsKeyId` encrypts the data channel between the local client and the container (in addition to the default TLS 1.2). The `cloudWatchEncryptionEnabled` and `s3EncryptionEnabled` flags encrypt session logs at rest. The CloudWatch log group MUST be encrypted with a KMS customer managed key when `cloudWatchEncryptionEnabled` is `true`.
> **Warning:** ECS Exec session logs may capture sensitive data such as environment variables, secrets, database queries, and command output. Ensure logging destinations are encrypted and access is restricted to authorized personnel.
> For existing clusters, use `update-cluster` with the same `--configuration` parameter.

The task role MUST have write permissions to the configured logging destination.

---

## Considerations and Limitations

| Consideration                  | Detail                                                                                     |
|--------------------------------|--------------------------------------------------------------------------------------------|
| `readonlyRootFilesystem`       | MUST NOT be set to `true`. ECS Exec requires a writable root filesystem because the SSM agent needs to write to the filesystem. Making the root file system read-only using `readonlyRootFilesystem` or any other method is not supported. |
| `initProcessEnabled`           | SHOULD be set to `true`. This ensures proper signal handling and zombie process reaping. Without it, orphaned processes from exec sessions may accumulate. |
| Idle timeout                   | Default 20 minutes of inactivity. Per [ECS Exec docs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html), this value cannot be changed.                                                                 |
| PID namespace                  | Only **one exec session** is supported per PID namespace. For tasks with `pidMode: "task"`, this means one session per task. For the default PID namespace, one session per container. |
| Fargate platform version       | MUST be `1.4.0` or later (Linux) or `1.0.0` (Windows).                                    |
| Shell requirement              | The container MUST have `/bin/sh` or the specified shell available in the image.           |
| Runs as root                   | ECS Exec commands run as the `root` user regardless of the container's user configuration. The SSM agent and its child processes also run as root. |
| CPU/memory overhead            | ECS Exec uses some CPU and memory. Account for this when specifying CPU and memory resource allocations in your task definition. |
| `run-task` with managed scaling | Cannot use ECS Exec with `run-task` on clusters that use managed scaling with asynchronous placement (launch a task with no instance). |
| IPv6-only not supported        | ECS Exec is not supported for tasks running in an IPv6-only network configuration. |
| Nano Server not supported      | ECS Exec cannot be run against Microsoft Nano Server containers. |

---

## Security Considerations

ECS Exec provides powerful break-glass access to running containers. The following security controls SHOULD be applied:

- **Root access risk:** All ECS Exec commands run as `root` regardless of the container's user configuration. Limit who can call `ecs:ExecuteCommand` via IAM policies with condition keys (`ecs:cluster`, `ecs:container-name`, `aws:ResourceTag`).
- **Prevent SSM session hijacking:** Deny `ssm:StartSession` directly on ECS task ARNs to prevent unlogged sessions that bypass ECS Exec auditing. See [Limiting access to the Start Session action](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html).
- **Encrypt the data channel:** Provide a `kmsKeyId` in the cluster's `executeCommandConfiguration` to encrypt data between the local client and the container beyond the default TLS 1.2.
- **Enable and encrypt session logging:** Configure session logging to S3 or CloudWatch Logs with encryption enabled. Session logs may contain sensitive data (environment variables, secrets, query results).
- **Audit with CloudTrail:** `ExecuteCommand` API calls are recorded in AWS CloudTrail. Ensure CloudTrail is enabled and that trails cover the regions where ECS Exec is used.
- **Task role trust policy:** When creating the task IAM role, use `aws:SourceAccount` and `aws:SourceArn` condition keys in the trust policy to prevent the [confused deputy problem](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html).
- **Disable ECS Exec in production when not needed:** Use the `ecs:enable-execute-command` condition key to prevent services from being launched with ECS Exec enabled unless explicitly authorized.

For more information, see [ECS Exec security](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html) and [Amazon ECS security best practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/security.html).
