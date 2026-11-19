<!-- markdownlint-disable MD013 -->

# Setup

Follow these steps before using Amazon Braket in an AWS account that has not
previously been enabled for Amazon Braket.

## Creating the Braket service-linked role

### AWS CLI

```bash
aws iam create-service-linked-role \
  --aws-service-name braket.amazonaws.com
```

If the role already exists, the command returns `EntityAlreadyExists`; no
additional action is required.

### AWS MCP

Reference the `aws-iam` skill and use the service principal `braket.amazonaws.com` to create the service-linked role.

### Console

For manual console onboarding, follow [Enable Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-enable-overview.html).

## Accepting third-party device terms and conditions

The user must manually accept these terms in the Braket console, once per AWS account, before using third-party QPUs.
See [Enable Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-enable-overview.html) for the steps.

## Creating execution roles

Before creating each role, run `aws iam get-role --role-name <name>` to check if a role already exists and reuse it if it does.
If programmatic IAM role creation is unavailable, follow the console workflows in [Hybrid Jobs prerequisites](https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-prerequisites.html) and [Create an Amazon Braket notebook instance](https://docs.aws.amazon.com/braket/latest/developerguide/braket-get-started-create-notebook.html).

Replace every `<account-id>` in this section with the customer's AWS account ID.
Pass each policy document as an inline JSON string, quoted for the user's shell. Do not use `file://` with AWS MCP `call_aws`.

### Hybrid Jobs execution role

Create `AmazonBraketJobsExecutionRole` with the trust policy and command below:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "braket.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "<account-id>"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:braket:*:<account-id>:*"
        }
      }
    }
  ]
}
```

```bash
aws iam create-role \
  --role-name AmazonBraketJobsExecutionRole \
  --path /service-role/ \
  --assume-role-policy-document '<trust policy JSON above>'
```

Attach the `AmazonBraketJobsExecutionPolicy` AWS managed policy:

```bash
aws iam attach-role-policy \
  --role-name AmazonBraketJobsExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonBraketJobsExecutionPolicy
```

Separately, grant the principal that submits Hybrid Jobs `iam:PassRole` on the exact execution-role ARN, restricted to Braket.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<account-id>:role/service-role/AmazonBraketJobsExecutionRole",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "braket.amazonaws.com"
        }
      }
    }
  ]
}
```

### Notebook execution role

Create `AmazonBraketServiceSageMakerNotebookRole` at the `/service-role/` path.

Configure the role with this trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "sagemaker.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "<account-id>"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:sagemaker:*:<account-id>:notebook-instance/*"
        }
      }
    }
  ]
}
```

Create the role with the trust policy above:

```bash
aws iam create-role \
  --role-name AmazonBraketServiceSageMakerNotebookRole \
  --path /service-role/ \
  --assume-role-policy-document '<trust policy JSON above>'
```

Create and attach a customer-managed policy named
`AmazonBraketServiceSageMakerNotebookAccess` with the following policy document, and attach the `AmazonBraketFullAccess` managed policy, as the Braket console does:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::amazon-braket-*",
        "arn:aws:s3:::braketnotebookcdk-*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:DescribeLogStreams",
        "logs:PutLogEvents",
        "logs:CreateLogGroup"
      ],
      "Resource": [
        "arn:aws:logs:*:<account-id>:log-group:/aws/sagemaker/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "braket:*",
      "Resource": "*"
    }
  ]
}
```

```bash
aws iam create-policy \
  --policy-name AmazonBraketServiceSageMakerNotebookAccess \
  --path /service-role/ \
  --policy-document '<policy JSON above>'

aws iam attach-role-policy \
  --role-name AmazonBraketServiceSageMakerNotebookRole \
  --policy-arn arn:aws:iam::<account-id>:policy/service-role/AmazonBraketServiceSageMakerNotebookAccess

aws iam attach-role-policy \
  --role-name AmazonBraketServiceSageMakerNotebookRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonBraketFullAccess
```

Separately, grant the principal that creates the notebook `iam:PassRole` on the
exact notebook execution-role ARN, restricted to SageMaker:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<account-id>:role/service-role/AmazonBraketServiceSageMakerNotebookRole",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "sagemaker.amazonaws.com"
        }
      }
    }
  ]
}
```

## S3 results bucket

For new S3 buckets:

- Use the **Secure New Bucket** workflow in the `securing-s3-buckets` skill when available; otherwise follow [Security best practices for Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html).
- Meet the Braket requirements in [Using Amazon S3 buckets with Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-s3-bucket-support.html).

If the user requires a customer managed KMS key, use the key the user specifies.

## Customer Managed Keys

If the user specifies a customer-managed KMS key, ask the user about adding the following statements, substituting the placeholders enclosed in angle brackets `<>`, to the key's existing key policy following the API procedure at [Change a key policy](https://docs.aws.amazon.com/kms/latest/developerguide/key-policy-modifying.html#key-policy-modifying-how-to-api).

```json
[
  {
    "Sid": "Allow Amazon Braket to write quantum task results to S3 with this key",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<account-id>:role/aws-service-role/braket.amazonaws.com/AWSServiceRoleForAmazonBraket"},
    "Action": "kms:GenerateDataKey",
    "Resource": "*",
    "Condition": {
      "StringEquals": {"kms:ViaService": "s3.<key-region>.amazonaws.com"},
      "StringLike": {"kms:EncryptionContext:aws:s3:arn": ["arn:aws:s3:::<bucket>", "arn:aws:s3:::<bucket>/*"]}
    }
  },
  {
    "Sid": "Allow the Braket hybrid jobs execution role to use this key through S3",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<account-id>:role/service-role/AmazonBraketJobsExecutionRole"},
    "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
    "Resource": "*",
    "Condition": {"StringEquals": {"kms:ViaService": "s3.<key-region>.amazonaws.com"}}
  },
  {
    "Sid": "Allow the Braket notebook execution role to use this key through S3",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<account-id>:role/service-role/AmazonBraketServiceSageMakerNotebookRole"},
    "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
    "Resource": "*",
    "Condition": {"StringEquals": {"kms:ViaService": "s3.<key-region>.amazonaws.com"}}
  },
  {
    "Sid": "Allow the Braket hybrid jobs execution role to describe this key",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<account-id>:role/service-role/AmazonBraketJobsExecutionRole"},
    "Action": "kms:DescribeKey",
    "Resource": "*"
  }
]
```

For further customization, see [Key policies in AWS KMS](https://docs.aws.amazon.com/kms/latest/developerguide/key-policies.html) and [Using IAM policies with AWS KMS](https://docs.aws.amazon.com/kms/latest/developerguide/iam-policies.html).

## Notebooks

Open [notebooks.md](./notebooks.md) for information on creating notebooks.

## Spending limits and cost guardrails

Before the first QPU task on each device, search for an existing spending limit and create one if none exists; see [spending-limit.md](./spending-limit.md) for the device-specific commands.

## References

- Developer guide:
  - [Enable Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-enable-overview.html)
  - [Getting started with Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-get-started.html)
  - [Amazon Braket service-linked role](https://docs.aws.amazon.com/braket/latest/developerguide/braket-slr.html)
  - [Hybrid Jobs prerequisites](https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-prerequisites.html)
  - [Using the API with Hybrid Jobs](https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-api.html)
  - [Managing access to Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-manage-access.html)
  - [Restrict user access to certain S3 buckets](https://docs.aws.amazon.com/braket/latest/developerguide/restrict-access-s3-buckets.html)
  - [Restrict user access to certain notebook instances](https://docs.aws.amazon.com/braket/latest/developerguide/restrict-access-notebook-instances.html)
  - [Cost tracking and spending limits](https://docs.aws.amazon.com/braket/latest/developerguide/braket-pricing.html)
- API:
  - [CreateServiceLinkedRole](https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateServiceLinkedRole.html)
  - [CreateSpendingLimit](https://docs.aws.amazon.com/braket/latest/APIReference/API_CreateSpendingLimit.html)
- AWS managed policies:
  - [`AmazonBraketFullAccess`](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonBraketFullAccess.html)
  - [`AmazonBraketJobsExecutionPolicy`](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonBraketJobsExecutionPolicy.html)
  - [`AmazonBraketServiceRolePolicy`](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonBraketServiceRolePolicy.html)
- Local references:
  - [Notebook instances](./notebooks.md)
  - [Hybrid jobs](./hybrid-job.md)
  - [Spending limits and cost tracking](./spending-limit.md)
- AWS IAM skill
  - [aws-iam](https://github.com/aws/agent-toolkit-for-aws/blob/main/skills/core-skills/aws-iam/SKILL.md)
