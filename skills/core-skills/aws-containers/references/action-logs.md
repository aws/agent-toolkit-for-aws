# Amazon ECS Action Logs — recommend, enable, and read

Guidance for proactively recommending, enabling, and reading Amazon ECS Action Logs while
troubleshooting. Action Logs record ECS **control-plane** decisions — deployment
rollout/rollback, task placement, scaling, and task replacement — and deliver them through
the Amazon CloudWatch Logs *vended log delivery* mechanism. They add the most value when the
*reason* behind an orchestration action is not already visible in `DescribeServices` or task
events.

Documentation: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/action-logs-getting-started.html

## Contents

- [When Action Logs help](#when-action-logs-help)
- [Check whether enabled](#check-whether-enabled)
- [Recommend and enable](#recommend-and-enable)
- [Resolve the destination](#resolve-the-destination)
- [Read by destination type](#read-by-destination-type)
- [Report honestly](#report-honestly)
- [MCP server notes](#mcp-server-notes)
- [Security considerations](#security-considerations)

## When Action Logs help

When delivery is **not** already configured for the cluster:

- **Primary — recommend enabling.** Deployment rollback / circuit-breaker; task-placement
  failures (no capacity, unsatisfied constraints or attributes).
- **Secondary — recommend only on control-plane churn.** Stopped-task crash loops (non-zero
  exit) or health-check failures **when** they are driving repeated task replacement or
  redeployment. Otherwise mention Action Logs at most once, as an optional aside.
- **Out of scope — do not recommend.** Image-pull failures (`CannotPullContainerError`) and
  other container-runtime faults whose reason is already in task stop reasons/events. Discuss
  Action Logs only if the user explicitly asks.
- **Ambiguous / low-signal.** If it is genuinely unclear whether Action Logs would help,
  mention them **at most once, in a single tentative sentence** — do **not** give them a
  dedicated section, a numbered step, or a CLI command, and do not repeat across turns. Lead
  with the ordinary signals (service events, deployment configuration, health checks) first.

Do **not** recommend *disabling* Action Logs after a session. If delivery is already
configured for the cluster, do not re-recommend enabling.

## Check whether enabled

Action Logs are configured per cluster. Treat them as **enabled only when BOTH exist**: a
delivery source that carries the cluster ARN with log type `ACTION_LOGS`, **and** a matching
delivery that links that source to a destination. A delivery source on its own does not mean
logs are being delivered.

```
aws logs describe-delivery-sources --region <region>   # find a source with the cluster ARN + ACTION_LOGS
aws logs describe-deliveries       --region <region>   # confirm a delivery references that source
```

Report Action Logs as **enabled** only when a delivery source has the cluster ARN in
`resourceArns` with log type `ACTION_LOGS` **and** a delivery in `describe-deliveries`
references that source. If either is missing, Action Logs are **not enabled** for that
cluster.

## Recommend and enable

**Whenever you recommend enabling, include BOTH the paid-feature caveat AND the documentation
link (below) in the same response** — a recommendation missing either is incomplete.

Before enabling, tell the user, verbatim:

> ECS Action Logs is a paid, opt-in feature — enabling it incurs CloudWatch vended-log
> delivery charges; see AWS pricing before proceeding.

and link the getting-started documentation above.

Action Logs are configured on the **cluster update path**; before attempting to enable at
cluster-creation time, verify whether that is supported against the AWS documentation linked
above. Default the destination to **CloudWatch Logs**; you may mention
Amazon S3 or Amazon Data Firehose as alternatives, but do not require the user to choose a
destination type.

**Before running any mutating call, echo back what will be created — the delivery source, the
delivery destination, and the target cluster — and obtain an explicit "yes." Never create a
delivery without that confirmation.**

If the user has **already** confirmed in their request (for example, "go ahead and enable
it"), treat that as the explicit yes: briefly state what you will create, then run the
calls below in sequence — do not pause to ask again.

Enable with the CloudWatch Logs vended-log-delivery calls below (plain AWS CLI):

```
# Create the destination log group encrypted at rest with a customer-managed KMS key
aws logs create-log-group \
    --log-group-name /aws/vendedlogs/ecs/action-logs/<cluster> \
    --kms-key-id <kms-key-arn>

# Set retention separately — create-log-group has no --retention-in-days parameter
aws logs put-retention-policy \
    --log-group-name /aws/vendedlogs/ecs/action-logs/<cluster> \
    --retention-in-days 90

aws logs put-delivery-source --name <cluster>-action-logs \
    --resource-arn arn:aws:ecs:<region>:<account>:cluster/<cluster> \
    --log-type ACTION_LOGS

aws logs put-delivery-destination --name <cluster>-action-logs-dest \
    --delivery-destination-configuration \
    '{"destinationResourceArn":"arn:aws:logs:<region>:<account>:log-group:/aws/vendedlogs/ecs/action-logs/<cluster>"}'

# Grant the delivery service write access to the destination log groups, constrained with
# aws:SourceArn / aws:SourceAccount to prevent the confused-deputy problem. This is ONE shared,
# prefix-scoped resource policy (not one per cluster): CloudWatch Logs allows only a small
# number of resource policies per account/region, and the vended-logs prefix covers every
# cluster's destination group. Run this before create-delivery so the destination is writable
# when delivery begins.
aws logs put-resource-policy \
    --policy-name ecs-action-logs-delivery \
    --policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "delivery.logs.amazonaws.com"},
        "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
        "Resource": "arn:aws:logs:<region>:<account>:log-group:/aws/vendedlogs/ecs/action-logs/*:log-stream:*",
        "Condition": {
          "StringEquals": {"aws:SourceAccount": "<account>"},
          "ArnLike": {"aws:SourceArn": "arn:aws:logs:<region>:<account>:delivery-source:*"}
        }
      }]
    }'

aws logs create-delivery --delivery-source-name <cluster>-action-logs \
    --delivery-destination-arn arn:aws:logs:<region>:<account>:delivery-destination:<cluster>-action-logs-dest
```

Notes:

- Use `--log-type ACTION_LOGS` (the value the CloudWatch Logs API accepts).
- The default CloudWatch Logs group is `/aws/vendedlogs/ecs/action-logs/<cluster>`. Create it
  with a customer-managed KMS key (encryption at rest), as shown above. The key policy must
  grant the CloudWatch Logs service principal use of the key (see Security considerations for
  the exact actions and an example key policy); without that grant `create-log-group --kms-key-id`
  fails — do not drop the key to unblock, as that leaves the log group unencrypted.
- `--retention-in-days 90` is a reasonable default; adjust it to your organization's compliance
  and cost requirements — log retention is org-specific.
- The destination log group must allow `delivery.logs.amazonaws.com` to write it via the single
  shared, prefix-scoped `put-resource-policy` call in the sequence above — run it before
  `create-delivery` so the destination is writable when delivery begins. See Security
  considerations for the confused-deputy conditions and the shared-policy tradeoff.
- Required IAM to run the calls above: see Security considerations → Least-privilege IAM for the
  delivery actions, ARN scoping, and STS-role guidance.

## Resolve the destination

Never assume a fixed log-group path. Resolve the real destination:

```
aws logs describe-delivery-sources      --region <region>   # find the source for the cluster ARN
aws logs describe-deliveries            --region <region>   # find the delivery for that source
aws logs describe-delivery-destinations --region <region>   # read its destinationResourceArn
```

## Read by destination type

- **CloudWatch Logs.** Query the resolved log group and return the entries. When the user
  gives no time window, default the read to the failure onset (deployment `createdAt` or the
  first failure timestamp); if that cannot be determined, default to the last 3 hours.
  **Always tell the user which window you used and explicitly offer to widen it to 24 hours.**
  Honor any explicit user-specified window. Entries can contain resource identifiers, ARNs, and
  operational metadata — summarize rather than dumping raw entries when the audience or context
  is unclear, and do not surface full log payloads to unauthorized contexts.
- **Amazon S3.** Point the user at the resolved bucket/prefix with a ready-to-run command
  (for example `aws s3 ls` or `aws s3 cp`). Do not download and parse the objects. Harden the
  destination bucket per Security considerations.
- **Amazon Data Firehose.** Point the user at the downstream destination with a ready-to-run
  command. Do not parse the forwarded payload.

## Report honestly

- If no delivery source matches the cluster, report that Action Logs are **not enabled**. Do
  not fabricate entries from another source such as service events.
- Distinguish **"not enabled"** from **"enabled but no activity in the window."**

## MCP server notes

Everything above works with plain AWS CLI and no MCP tools. Where the **AWS MCP Server** is
available, it is recommended for sandboxed execution and audit logging. Where the **ECS MCP
Server** is installed, its `fetch_action_logs` tool performs the destination resolution in a
single call.

## Security considerations

When enabling Action Logs delivery, harden the destination and the delivery path:

- **Encrypt destinations at rest and in transit.** For CloudWatch Logs, create the destination
  log group with a customer-managed KMS key (`--kms-key-id`) whose key policy grants the
  CloudWatch Logs service principal (`logs.<region>.amazonaws.com`) use of the key, scoped to the
  vended-logs log groups with the `kms:EncryptionContext:aws:logs:arn` condition — for example:

  ```
  {
    "Effect": "Allow",
    "Principal": {"Service": "logs.<region>.amazonaws.com"},
    "Action": ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"],
    "Resource": "*",
    "Condition": {
      "ArnLike": {
        "kms:EncryptionContext:aws:logs:arn": "arn:aws:logs:<region>:<account>:log-group:/aws/vendedlogs/ecs/action-logs/*"
      }
    }
  }
  ```

  (`"Resource": "*"` in a key policy refers to the key the policy is attached to.) For Amazon
  S3, enable SSE-KMS on the destination bucket and enforce TLS with a bucket policy that denies
  non-TLS access (`aws:SecureTransport: false`). For Amazon Data Firehose, enable server-side
  encryption on the stream and its backup bucket.
- **Block public access on S3 destinations.** Action Logs can contain operational metadata
  (resource identifiers, ARNs, placement decisions), so enable all four S3 Block Public Access
  settings (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`)
  on any S3 destination bucket to keep it private by default.
- **Least-privilege IAM.** Scope the delivery actions (`logs:PutDeliverySource`,
  `logs:PutDeliveryDestination`, `logs:CreateDelivery`, `logs:GetDelivery`,
  `ecs:AllowVendedLogDeliveryForResource`) to the specific cluster ARN and destination
  log-group ARN rather than `Resource: "*"`, and attach them to an IAM role assumed via STS
  rather than to a long-lived IAM user.
- **Confused-deputy prevention.** In the destination resource policy that grants
  `delivery.logs.amazonaws.com` write access, add the `aws:SourceArn` and `aws:SourceAccount`
  condition keys. With the single shared, prefix-scoped policy above, `aws:SourceArn` is a
  per-account delivery-source wildcard; `aws:SourceAccount` still pins writes to your own
  account, so only delivery sources in your account can write.
- **Audit configuration changes.** Enable CloudTrail to record the delivery-configuration API
  calls (`PutDeliverySource`, `PutDeliveryDestination`, `CreateDelivery`), and enable S3 server
  access logging or CloudTrail data events on any S3 destination bucket.
- **Alarm on delivery and access anomalies.** Set up CloudWatch Alarms for operational and
  security monitoring of the delivery pipeline — for example, on delivery failures (the
  `ForwardingErrors` vended-log metric) or, via a CloudTrail metric filter, on unexpected
  `PutDeliverySource`/`CreateDelivery` attempts or an absence of the expected log volume.
- **Restrict access to the logs.** Action Logs can contain operational metadata about the
  cluster; restrict read access on the destination to authorized personnel.

For deeper guidance, see the AWS security best-practices documentation:
[ECS security best practices](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security.html),
[Encrypt CloudWatch Logs data with KMS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/encrypt-log-data-kms.html),
and [Protecting data in CloudWatch Logs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/data-protection.html).
