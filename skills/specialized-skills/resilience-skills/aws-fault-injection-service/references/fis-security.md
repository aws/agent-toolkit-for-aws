# Security Considerations — aws-fault-injection-service

FIS runs **real, potentially destructive actions on real resources**. Secure both *who can run
experiments* and *what an experiment is allowed to touch*, and always bound the blast radius.

## Contents

- The experiment IAM role (`roleArn`)
- Restrict who can start experiments
- Bounded blast radius (safety, not just IAM)
- Data handling
- Auditing
- Further reading

## The experiment IAM role (`roleArn`)

FIS assumes the experiment role to perform actions on your behalf. It is a **service role** with:

1. A **trust policy** allowing `fis.amazonaws.com` to assume it, with confused-deputy conditions.
2. **Identity-based permissions** for exactly the target-service APIs the experiment's actions
   invoke (and SSM / logs / report S3+CloudWatch if those features are used).

### Trust policy with confused-deputy protection (required)

Condition on `aws:SourceAccount` and `aws:SourceArn` so only your account's FIS experiments can
assume the role — never leave the trust policy unconditioned.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "fis.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "123456789012" },
      "ArnLike": {
        "aws:SourceArn": "arn:aws:fis:us-east-1:123456789012:experiment/*"
      }
    }
  }]
}
```

### Least-privilege permissions (scope to actions AND target ARNs)

Grant only what the chosen actions need, scoped to the specific target resources — never `"*"`
across a service. Example for an EC2 reboot experiment on tagged prod instances:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:RebootInstances"],
      "Resource": "arn:aws:ec2:us-east-1:123456789012:instance/*",
      "Condition": { "StringEquals": { "aws:ResourceTag/env": "prod" } }
    },
    {
      "Effect": "Allow",
      "Action": ["ec2:DescribeInstances"],
      "Resource": "*"
    }
  ]
}
```

`Describe*` calls FIS uses for target resolution/filtering generally require `Resource: "*"`
(they don't support resource-level scoping), but the **fault** actions should be scoped by ARN
and/or `aws:ResourceTag`. Match permissions to the action's underlying API.

### Action → underlying-permission mapping (illustrative — verify with `get-action`)

The exact IAM actions each FIS action needs evolve; treat this as a starting point and confirm the
authoritative list before finalizing a policy (see "authoritative source" below). The pattern is
always the same: **fault** permission(s) scoped by ARN/tag + the `Describe*` **resolution**
permission on `Resource: "*"`.

| FIS action | Fault permission(s) | Typical resolution permission |
|---|---|---|
| `aws:ec2:reboot-instances` / `stop-instances` / `terminate-instances` | `ec2:RebootInstances` / `ec2:StopInstances`(+`StartInstances` if auto-restart) / `ec2:TerminateInstances` | `ec2:DescribeInstances` |
| `aws:rds:failover-db-cluster` / `reboot-db-instances` | `rds:FailoverDBCluster` / `rds:RebootDBInstance` | `rds:DescribeDBClusters` / `rds:DescribeDBInstances` |
| `aws:elasticache:replicationgroup-interrupt-az-power` | `elasticache:InterruptClusterAzPower` | `elasticache:DescribeReplicationGroups` |
| `aws:lambda:invocation-*` | `lambda:<verify with get-action>` on the function — never `lambda:*` **+ the FIS Lambda extension layer** | `lambda:GetFunction` |
| `aws:ssm:send-command` / `start-automation-execution` | `ssm:SendCommand` / `ssm:StartAutomationExecution` (+ the doc/automation ARNs) | resource-type `Describe*` |
| `aws:eks:pod-*` | **IAM is not sufficient** — needs `eks:DescribeCluster` for resolution **plus Kubernetes RBAC** mapping the FIS role to a k8s group bound to a Role/ClusterRole, **plus the cluster "prepared for FIS"** | `eks:DescribeCluster` |
| `aws:network:disrupt-connectivity` / `route-table-*` / `transit-gateway-*` | NACL/route-table EC2 actions (e.g. `ec2:CreateNetworkAcl`, `ec2:CreateNetworkAclEntry`, `ec2:ReplaceNetworkAclAssociation`, `ec2:DeleteNetworkAcl`) — **verify the exact set with `get-action`** | `ec2:DescribeSubnets` / `ec2:DescribeRouteTables` / `ec2:DescribeVpcs` |
| `aws:ebs:pause-volume-io` | `ec2:<verify with get-action>` volume-IO fault permission — do not grant `ec2:*` (Nitro only) | `ec2:DescribeVolumes` |

> **EKS pod actions are the common trap:** IAM alone will not run them. You also need Kubernetes
> RBAC (map the experiment role into the cluster and bind it to a role that permits the pod
> operation) and the cluster must be prepared for FIS. Grant `eks:*` sparingly and lean on k8s RBAC
> for the actual pod permissions.

**Authoritative source (use when an action is not in the table above, or to confirm one that is):**
run `aws fis get-action --id <action-id>` and consult
[How AWS FIS works with IAM](https://docs.aws.amazon.com/fis/latest/userguide/security_iam_service-with-iam.html)
and any AWS-managed FIS policies. **Do not invent IAM action names** for an action whose underlying
API you cannot confirm — scaffold the correctly-scoped policy and mark the fault permissions as
`<verify with get-action>` rather than guessing.

### Additional permissions per feature

- **Experiment logging** — grant FIS vended-logs delivery permissions to the CloudWatch Logs log
  group and/or S3 bucket you configure.
- **Experiment reports** — `cloudwatch:GetDashboard`, `cloudwatch:GetMetricWidgetImage`,
  `s3:PutObject`, `s3:GetObject` (scoped to the report bucket/prefix); plus
  `kms:GenerateDataKey`, `kms:Decrypt` if the report bucket uses a customer-managed KMS key.
- **Multi-account** — each *target account* needs its own role that the orchestrator's FIS can
  assume, with the same confused-deputy conditions and least-privilege target permissions.

## Restrict who can start experiments

Starting an experiment is a privileged action. Scope the human/CI principals allowed to call
`fis:StartExperiment` (and template CRUD), ideally with `aws:ResourceTag` conditions and by
template ARN. FIS supports identity-based policies, ABAC (tags in policies), service-specific
condition keys, and PassRole controls — use `iam:PassRole` conditions so only approved experiment
roles can be passed to FIS.

### Caller `iam:PassRole` — required

When emitting an experiment role, ALSO emit the caller's `PassRole` policy. Without it, any
caller who can create/update templates can reference any FIS-trusting role in the account.

Rules: `Resource` = explicit experiment-role ARN(s), never `*`. Condition
`iam:PassedToService = fis.amazonaws.com`.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "iam:PassRole",
    "Resource": ["arn:aws:iam::123456789012:role/FISExperimentRole"],
    "Condition": {
      "StringEquals": { "iam:PassedToService": "fis.amazonaws.com" }
    }
  }]
}
```

## Bounded blast radius (safety, not just IAM)

- **Always attach a stop condition** — a CloudWatch alarm on your steady-state metric. It is the
  automated kill-switch. `{"source":"none"}` is acceptable only in a throwaway sandbox.
- **Start narrow** — `COUNT(1)` or a small `PERCENT(n)`, single AZ, pre-production first. Widen
  only after the experiment passes.
- **Preview targets** (`actionsMode: skip-all`) before a real run to confirm the exact resources.
- **Production requires change management** — treat prod fault injection as a change with
  approval, a run window, and a rollback/stop plan.
- **Empty-target behavior** — leave `emptyTargetResolutionMode` at `fail` so an over- or
  under-matching target surfaces immediately instead of silently doing nothing.

## Data handling

- **No sensitive data in string fields** — template/experiment descriptions, action assertion
  text, tags, and log/report content surface in CloudTrail, CloudWatch Logs, S3, the console, and
  (multi-account) target-account **AWS Health dashboards**. Never embed PII, secrets, or
  sensitive architecture detail.
- **Encrypt logs & reports** — experiment logs and PDF reports reveal resilience posture and
  architectural weaknesses. Use SSE-KMS on the S3 buckets, enforce TLS with a bucket policy
  condition on `aws:SecureTransport`, restrict to a dedicated bucket/prefix, and consider S3
  Object Lock on report buckets so evidence can't be altered or deleted.

## Auditing

FIS API calls are recorded in **AWS CloudTrail** (including the actions FIS takes in each target
account for multi-account experiments). Review CloudTrail and experiment logs after each run.

## Further reading

- [Security in AWS FIS](https://docs.aws.amazon.com/fis/latest/userguide/security.html)
- [How AWS FIS works with IAM](https://docs.aws.amazon.com/fis/latest/userguide/security_iam_service-with-iam.html)
- [IAM best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [AWS Well-Architected Reliability Pillar](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/)
