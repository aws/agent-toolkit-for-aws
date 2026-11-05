# Troubleshooting

## TargetNotConnected

```
An error occurred (TargetNotConnected) when calling the StartSession operation
```

Causes:

- Wrong target format — verify underscore between cluster ID and group name, hyphen before instance ID
- Cluster ID is wrong — must be extracted from ARN, not the cluster name
- Node not in `Running` state — check with `aws sagemaker list-cluster-nodes`
- SSM Agent not responding on the node — if the node is `Running`, tell the user and point them to [Troubleshooting TargetNotConnected](https://repost.aws/knowledge-center/session-manager-targetnotconnected)

Verify:

```bash
aws sagemaker list-cluster-nodes --cluster-name CLUSTER --region REGION \
  --query 'ClusterNodeSummaries[?InstanceId==`INSTANCE_ID`].[InstanceGroupName,InstanceStatus.Status]' \
  --output text
```

## AccessDeniedException

Run `aws sts get-caller-identity` to see which identity is calling, and tell the user which of these permissions it is missing. Don't change IAM yourself. See [IAM for SageMaker HyperPod](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-prerequisites-iam.html), and keep access least-privilege.

- `sagemaker:DescribeCluster`, `sagemaker:ListClusterNodes`, `sagemaker:ListClusters`
- `ssm:StartSession`, `ssm:TerminateSession`

## Command Timeout / Hangs

- Long-running commands without output can cause SSM to hang
- Add periodic output. For work that runs a long time, tell the user and let them run it in their own session.

## Base64 Upload Corruption

- Always use `base64 -w 0` (no line wrapping)
- The whole command must fit in 65,535 characters, the [StartSession](https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_StartSession.html) parameter limit (this can change), so `ssm-exec.sh` stops with an error for a file over about 48KB after gzip. Copy larger files through a shared filesystem (FSx/EFS) or S3 instead.

## RunAs User Error

```
Unable to start command: failed to start pty since RunAs user does not exist
```

SSM Run-as-user is configured but user doesn't exist on the node. Use default (root) and `sudo -u USERNAME` explicitly.

## ThrottlingException on StartSession

```
An error occurred (ThrottlingException) when calling the StartSession operation: Rate exceeded
```

Cause: Too many concurrent `start-session` calls. SSM has per-account rate limits.

Fix: start SSM sessions in smaller batches (see "Running Commands Across Many Nodes" in ../overview.md for the limit and the batch size).

## send-command Not Supported

A `ValidationException` from `aws ssm send-command` on a `sagemaker-cluster:` target is expected: use `ssm-exec.sh` instead (see "Running Commands Across Many Nodes" in ../overview.md).
