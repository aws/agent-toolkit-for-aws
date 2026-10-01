# Forwarding telemetry into a Space

Gets an account's CloudWatch logs and traces into the CloudWatch Dataset, so
CloudWatch Omni can query and correlate them. Logs and traces do not enter the
Dataset directly — they are copied from CloudWatch Logs (including the `aws/spans`
trace records), so getting them into Omni always means getting them into CloudWatch
first, then forwarding. OTel metrics are the exception: they land in the Dataset
natively via the CloudWatch metrics OTLP endpoint and need no forwarding.

> **Always state these, in any answer drawn from this file:**
>
> - **Which of the two paths applies, and why the other exists.** OTLP ingestion —
>   the standard CloudWatch OTLP endpoints — is for telemetry not yet in CloudWatch;
>   dataset forwarding is for telemetry already there. They compose: OTLP lands data in
>   CloudWatch, and the dataset integration brings it into the Dataset. A customer
>   starting from nothing needs both.
> - **Forwarding with nothing arriving in CloudWatch yields a working integration with
>   no data flowing through it**, which reads as a failure even though every call
>   succeeded.
> - **Logs and traces forward; metrics do not.** Customer OTel metrics land in the
>   Dataset natively; AWS-vended CloudWatch metrics arrive through OTel enrichment
>   (`aws observabilityadmin start-telemetry-enrichment`, then
>   `aws cloudwatch start-otel-enrichment`) instead.
> - **Enabling Omni from the console already creates the integration and its
>   execution role**, which is why you check before creating.
> - The first-ever integration in an account and Region triggers a **one-time import
>   of the previous week**; it never repeats, and log groups encrypted with a customer
>   managed key are excluded from it.

## Contents

- [Which path](#which-path)
- [What arrives when forwarding starts](#what-arrives-when-forwarding-starts)
- [Prerequisites](#prerequisites)
- [Step 1 — Check whether forwarding already exists](#step-1--check-whether-forwarding-already-exists)
- [Step 2 — Create the execution role](#step-2--create-the-execution-role)
- [Step 3 — Create the dataset integration](#step-3--create-the-dataset-integration)
- [Changing what is forwarded](#changing-what-is-forwarded)
- [Forwarding in more than one account](#forwarding-in-more-than-one-account)
- [Cleanup](#cleanup)
- [Troubleshooting](#troubleshooting)
- [Security considerations](#security-considerations)
- [Additional resources](#additional-resources)

## Which path

Two different things are described as sending data to Omni. Identify which the
customer needs before making any change:

| The customer has | Path |
|---|---|
| Applications or AWS services already ingesting into CloudWatch log groups | **Dataset forwarding** — this file |
| An agent or application not sending to CloudWatch | **Standard CloudWatch OTLP endpoints** — the per-signal OTLP entry points that deliver into CloudWatch. Deploy a collector that exports to them: see `references/cloudwatch-omni/instrumentation/collector.md` |

The two paths solve different problems. The **standard CloudWatch OTLP endpoints** are
OTLP entry points: they exist so an application or agent that is not currently sending
anything to CloudWatch has somewhere to send it. **Dataset forwarding** does not accept
telemetry at all — it collects what is already in CloudWatch log groups and brings it
into the Dataset.

**So the two compose.** An application sends over OTLP to the CloudWatch OTLP endpoints,
which lands telemetry in CloudWatch, and the dataset integration brings it into the
Dataset. **A customer starting from nothing needs both**; a customer who already has
logs in CloudWatch needs only forwarding.

Forwarding set up for a customer whose application is not yet sending to CloudWatch
produces a working integration with nothing flowing through it, which reads as a
failure even though every call succeeded.

**Constraints:**

- You MUST establish which path applies rather than assuming. Setting up forwarding

  for a customer whose application is not sending to CloudWatch produces a working
  integration with nothing flowing through it, which reads as a failure.

## What arrives when forwarding starts

Forwarding moves logs and traces as they are ingested. Metrics do not flow through
the dataset integration — they become available through metric enrichment.

When the dataset integration is created for the first time in an account and
Region, CloudWatch performs a one-time import of the previous week of existing log
data. After that:

- The import runs **once**. Deleting and recreating the integration does not

  repeat it.

- Log groups encrypted with a customer managed AWS KMS key are **not** included in

  the import. Their forwarding still begins normally from creation onward.

- Adding a log group to the integration's scope later forwards its records from

  that point on, not its existing contents.

**Constraints:**

- You MUST set this expectation before creating the integration. A customer who

  expects all of their history, or none of it, will misread a correctly working
  integration.

- You MUST tell a customer with customer managed key encryption that their

  encrypted log groups are excluded from the initial import, because the result
  otherwise looks like a partial failure.

- You MUST tell the customer that metrics do not arrive through this integration.

  Expecting metrics because forwarding is on is a reasonable and common
  misunderstanding.

## Prerequisites

- The AWS Region, confirmed with the customer rather than inferred. Forwarding is

  **same-account and same-Region**, and a Region mismatch produces an integration
  that forwards nothing.

- `iam:PassRole` on the execution role, for whoever runs Step 3. Without it the

  create call fails after the role already exists.

A Space is not a technical prerequisite — forwarding can be set up without one, but
nothing in Omni reads the forwarded data until a Space exists.
Within onboarding it effectively is one, since the Space is the Omni experience
being set up, so sequence it first. See `references/cloudwatch-omni/spaces-and-domains.md`.

Report the caller identity before starting:

```
aws___call_aws → aws sts get-caller-identity
```

### Operations you will call

Every operation runs through the `aws___call_aws` tool, which executes an
`aws <service> <operation>` CLI command — the service (`observabilityadmin`, `iam`,
or `sts`), the kebab-case operation, and a flag for each input parameter. Policy
documents are shown below as standalone JSON blocks — pass each one as the value of
the corresponding flag (`--assume-role-policy-document`, `--policy-document`).

**`aws observabilityadmin`:**

| Intent | Operation |
|---|---|
| Check for existing forwarding | `get-dataset-integration` |
| Start forwarding | `create-dataset-integration` |
| Change which role the integration uses | `update-dataset-integration` |
| Stop forwarding | `delete-dataset-integration` |

**`aws iam`:**

| Intent | Operation |
|---|---|
| Create the execution role | `create-role` |
| Attach forwarding permissions | `put-role-policy` |
| Remove an inline policy | `delete-role-policy` |
| Delete the execution role | `delete-role` |

**`aws sts`:**

| Intent | Operation |
|---|---|
| Confirm the calling identity | `get-caller-identity` |

## Step 1 — Check whether forwarding already exists

When CloudWatch Omni is enabled from the console, forwarding is set up
automatically — the console creates the dataset integration and its execution role
as part of enablement. Check before creating anything.

There is one dataset integration per account per Region and it is named `default`,
so its ARN is deterministic. Construct it and read it directly:

```
aws___call_aws → aws observabilityadmin get-dataset-integration \
  --arn arn:aws:observabilityadmin:<region>:<account-id>:dataset-integration/default
```

A successful response means forwarding already exists. A not-found error means it
does not.

**Constraints:**

- You MUST run this check before creating an integration. There is one per account

  per Region, so a second create conflicts.

- If one exists, you MUST report what the call returns and stop. The remaining work

  is scoping (see [Changing what is forwarded](#changing-what-is-forwarded)), not
  creation.

- If you cannot determine whether an integration exists — access is denied, or the

  response is ambiguous — you MUST treat the result as **inconclusive, not
  negative**. Report that the check could not be completed and stop. You MUST NOT
  create an integration on that basis.

## Step 2 — Create the execution role

Only if Step 1 found no integration. This is the role CloudWatch Logs assumes to
bring logs and traces into the Dataset.

Ask the customer whether the **CloudWatch Dataset** is encrypted with a customer
managed KMS key. If it is, the execution role needs `kms:Decrypt` on that key, or
forwarded telemetry cannot be written.

**Constraints:**

- You MUST ask before creating the role. A missing `kms:Decrypt` produces an

  integration that reports success and silently writes nothing.

- You MUST ask about the **Dataset's** key specifically. Log group encryption is a

  separate matter and has no bearing on this role's permissions.

### Create the role

Call `aws iam create-role` with `--role-name` set to the customer's chosen
role name and `--assume-role-policy-document` set to this trust policy. The
`aws:SourceAccount` and `aws:SourceArn` conditions are confused-deputy
protection — keep both. A condition that does not match — the wrong account, or
an `aws:SourceArn` that is not the `dataset-integration/default` resource —
blocks `logs.amazonaws.com` from assuming the role, and that failure is silent:
nothing surfaces on the create call, so forwarding ends up set up yet never
delivers.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "logs.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "<account-id>" },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:observabilityadmin:<region>:<account-id>:dataset-integration/default"
        }
      }
    }
  ]
}
```

```
aws___call_aws → aws iam create-role \
  --role-name <role-name> --assume-role-policy-document <trust-policy-json>
```

### Attach the forwarding permissions

Forward all log groups in the account. This is the onboarding default: it gives Omni
the fullest picture to correlate across, and log groups created later are picked up
without a permission change. `cloudwatch:PutRecords` does not support
resource-level scoping.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "logs:IntegrateWithDataset",
      "Resource": ["arn:aws:logs:<region>:<account-id>:log-group:*"]
    },
    {
      "Effect": "Allow",
      "Action": "cloudwatch:PutRecords",
      "Resource": "*"
    }
  ]
}
```

```
aws___call_aws → aws iam put-role-policy \
  --role-name <role-name> --policy-name DatasetIntegrationAccess --policy-document <policy-json>
```

**Constraints:**

- You SHOULD use the account-wide `log-group:*` resource shown above.
- If the customer asks to forward only specific log groups, replace `log-group:*`

  with their ARNs, and tell them log groups created later will not forward until
  the policy is updated.

- You MUST NOT add actions beyond these two. This role exists solely to move

  telemetry into the Dataset.

### Attach KMS decrypt, only if the Dataset uses a customer managed key

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:<region>:<account-id>:key/<key-id>"
    }
  ]
}
```

```
aws___call_aws → aws iam put-role-policy \
  --role-name <role-name> --policy-name DatasetKeyDecrypt --policy-document <policy-json>
```

**Constraints:**

- You MUST scope this to the Dataset's key ARN. Do not use `"Resource": "*"`.
- You MUST NOT author or modify the KMS key policy. This grants the role permission

  to use the key; it does not change who the key trusts. If the key policy needs
  changing, direct the customer to their key administrator.

## Step 3 — Create the dataset integration

```
aws___call_aws → aws observabilityadmin create-dataset-integration \
  --role-arn arn:aws:iam::<account-id>:role/<role-name>
```

**Constraints:**

- Creating the integration starts forwarding logs and traces together. There is no

  per-signal switch at create time; scope is controlled by the role's permissions.

- If the call fails on `iam:PassRole`, you MUST report which principal lacks it and

  stop. Do not attach permissions to your own caller to get past it.

Forwarding begins on creation. Allow a few minutes before telemetry appears in the
Space — permission changes take effect within a few minutes, and there is delivery
latency on top of that. If telemetry does not appear, see
[Troubleshooting](#troubleshooting).

## Changing what is forwarded

Scope is the execution role's `logs:IntegrateWithDataset` permissions, not a
setting on the integration.

- Narrowing or widening the role's log group ARNs takes effect within a few

  minutes.

- Scope changes are forward-only in both directions. **Adding** a log group

  forwards its records from that point on, not its existing contents. **Removing**
  one stops future records, while records already in the Dataset remain until they
  pass their retention period.

- To change which role the integration uses, or to stop forwarding entirely, use

  `update-dataset-integration` or `delete-dataset-integration`.

Retention in the Dataset mirrors each record's source retention, so records with
different retention periods coexist. It is not configured on the Dataset.

**Constraints:**

- You MUST state which direction applies. A customer who widens scope expecting the

  new log group's history, or narrows it expecting forwarded records to disappear,
  will be wrong in both cases.

## Forwarding in more than one account

Forwarding is same-account and same-Region. One account's integration does not
collect telemetry from other accounts, and one Region's integration does not
collect from other Regions.

To cover several accounts, each account forwards its own telemetry in the Region
where its Space lives, and each account gets its own execution role and
integration.

A **Region mismatch fails silently**: the integration is created, forwards nothing,
and produces no error anywhere. And do **not** reason by analogy from how other AWS
services centralize into a monitoring account — that pattern does not exist here, and
proposing it recommends an architecture that cannot work.

**Constraints:**

- You MUST NOT compose a cross-account or monitoring-account forwarding pattern

  from how other AWS services centralize. Doing so recommends a plausible
  architecture that does not work here.

## Cleanup

1. Stop forwarding:

   ```
   aws___call_aws → aws observabilityadmin delete-dataset-integration \
     --arn arn:aws:observabilityadmin:<region>:<account-id>:dataset-integration/default
   ```

2. Detach the inline policies, then delete the execution role. A role with inline

   policies attached cannot be deleted:

   ```
   aws___call_aws → aws iam delete-role-policy \
     --role-name <role-name> --policy-name DatasetIntegrationAccess

   aws___call_aws → aws iam delete-role-policy \
     --role-name <role-name> --policy-name DatasetKeyDecrypt

   aws___call_aws → aws iam delete-role --role-name <role-name>
   ```

   Skip `DatasetKeyDecrypt` if it was never attached.

Deleting the integration stops future forwarding. It does not remove records
already in the Dataset — those age out under their source retention.

**Constraints:**

- You MUST warn the customer that deleting the integration is not reversible in

  effect: recreating it restores forwarding, but the one-time import does not run
  again.

- You MUST NOT delete and recreate the integration to try to obtain missing

  history. The import runs only on first creation, so recreating gains nothing and
  interrupts working forwarding.

## Troubleshooting

**Rule:** When an AWS call returns an error, surface the error code and message
**verbatim** to the customer, then map to the mitigation below. Do NOT invent error
text, do NOT paraphrase what the service returned, and do NOT synthesize a
plausible-sounding mitigation for an error that is not listed.

Establish which kind of failure this is before investigating. They have different
causes and different fixes, and treating one as the other wastes the whole
diagnosis:

- **The API call was rejected** — creating, reading, or deleting the integration

  failed. The cause is the caller's own permissions or a bad argument.

- **The API call succeeded but telemetry is not appearing** — the integration

  exists. The cause is almost always the execution role's contents, or a Region
  mismatch.

### The API call was rejected

| Error signal | Cause | Mitigation to surface |
|---|---|---|
| `AccessDenied` on create | Caller lacks `observabilityadmin:CreateDatasetIntegration` | Ask the customer to add the action to their calling role |
| `AccessDenied` naming `iam:PassRole` | Caller may create the integration but cannot pass the execution role to `logs.amazonaws.com`. This is a permission on the **caller**, not on the execution role — a common misdiagnosis | Ask the customer to add `iam:PassRole` on the specific role ARN to their calling role |
| Execution role not found | Role ARN typo, or role in a different account | Ask the customer to verify the exact role ARN and confirm it is in the same account. The role must exist before the integration can reference it |
| Conflict on create | An integration already exists for this account and Region | Read it instead — see [Step 1](#step-1--check-whether-forwarding-already-exists). Do NOT retry the create |

**Constraints:**

- You MUST report the principal and the action, and direct the customer to whoever

  administers their IAM permissions. You cannot widen your own access.

### The integration exists but telemetry is not appearing

Work through these in order. Each is cheap to check and rules out the ones below
it.

- **Is anything reaching CloudWatch at all?** Confirm the source log group is

  receiving records. If it is empty, the problem is upstream of forwarding — see
  `references/cloudwatch-omni/instrumentation/collector.md`.

- **Is everything in the same Region?** Forwarding is same-Region. A mismatch fails

  silently, with no error anywhere.

- **Can `logs.amazonaws.com` assume the execution role?** Check the trust policy's

  principal, and that `aws:SourceAccount` and `aws:SourceArn` match this account and
  the `dataset-integration/default` ARN. A condition that does not match blocks the
  assume, and nothing surfaces on the create call.

- **Does the role cover the log groups in question?** `logs:IntegrateWithDataset`

  must include their ARNs. A role scoped to specific log groups forwards only those.

- **Does the role have `cloudwatch:PutRecords`?** Without it there is nowhere to

  write.

- **Does the Dataset use a customer managed key?** If so the role needs

  `kms:Decrypt` on that key. Without it the integration reports healthy and silently
  writes nothing.

**Constraints:**

- You MUST change one thing at a time and recheck. Stacked fixes hide which one

  worked, and some conflict.

### Expectations that look like faults

- **Metrics are missing.** Metrics do not flow through this integration; they become

  available through metric enrichment.

- **Only part of the expected history appeared.** The one-time import covers the

  previous week and excludes log groups encrypted with a customer managed key.

- **Recent records appear but older ones do not.** Scope changes are forward-only.

  Adding a log group forwards its records from that point on, not its existing
  contents.

## Security considerations

- The `logs:IntegrateWithDataset` resource controls what enters the Dataset.

  Account-wide forwarding is the onboarding default; restrict it to specific log
  group ARNs only when a customer needs particular log groups kept out.

- Keep both `aws:SourceAccount` and `aws:SourceArn` conditions in the trust policy.

  They are the confused-deputy protection.

- Do not attach `*FullAccess` managed policies to the execution role. It needs the

  dataset-integration actions and nothing else.

- Forwarded telemetry is encrypted at rest in the Dataset. When a customer managed

  key is in use, the execution role needs `kms:Decrypt` on it.

- Access to query the Dataset is controlled separately from ingestion, so read

  access can be granted without granting the ability to change forwarding.

## Additional resources

- `references/cloudwatch-omni/instrumentation/collector.md` — deploying a collector that exports to

  CloudWatch's OTLP endpoints, for telemetry not already reaching CloudWatch

- `references/cloudwatch-omni/spaces-and-domains.md` — creating a Space and configuring access
- [CloudWatch Dataset](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch-dataset.html)

  — forwarding setup, policies, retention, encryption
