# OpenSearch Ingestion (OSI) Pipelines for Log Ingestion

## Overview

OpenSearch Ingestion (OSI) is a fully managed, serverless pipeline service that delivers logs from sources like CloudWatch Logs, Fluent Bit, and HTTP into AOS/AOSS without managing infrastructure.

> The AWS MCP server is recommended for executing these commands but is not required — all steps use standard AWS CLI syntax.

## Creating a Pipeline for CloudWatch Logs

### Step 1: Create Pipeline Role

```bash
aws iam create-role --role-name OSIPipelineRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "osis-pipelines.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"aws:SourceAccount": "<account>"},
        "ArnLike":      {"aws:SourceArn":     "arn:aws:osis:<region>:<account>:pipeline/*"}
      }
    }]
  }'
```

Both `aws:SourceAccount` and `aws:SourceArn` conditions are required to prevent the **confused-deputy** pattern: without `aws:SourceArn`, any OSI pipeline in the same account could assume this role; the `ArnLike` condition narrows the trust to your OSI pipelines only. For a single-pipeline trust, replace `pipeline/*` with the specific pipeline name.

Attach policies for CloudWatch Logs source and OpenSearch sink:

```bash
aws iam put-role-policy --role-name OSIPipelineRole --policy-name osis-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {"Effect": "Allow", "Action": ["logs:DescribeLogGroups", "logs:FilterLogEvents", "logs:GetLogEvents"], "Resource": "arn:aws:logs:<region>:<account>:log-group:<log-group-name>:*"},
      {"Effect": "Allow", "Action": ["es:DescribeDomain", "es:ESHttpPost", "es:ESHttpPut"], "Resource": "arn:aws:es:<region>:<account>:domain/<domain>/*"}
    ]
  }'
```

### Step 2: Create Pipeline

```bash
aws osis create-pipeline --pipeline-name my-log-pipeline \
  --min-units 1 --max-units 4 \
  --pipeline-configuration-body file://pipeline.yaml
```

> **Tip — pipeline logging for debugging.** OSI pipeline logs may carry sensitive data (document content, field values, query parameters), so create the log group **with KMS encryption first**, then attach it:
>
> ```bash
> # 1. Create the log group with a customer-managed KMS key
> aws logs create-log-group \
>   --log-group-name /aws/vendedlogs/OpenSearchIngestion/my-log-pipeline \
>   --kms-key-id arn:aws:kms:<region>:<account>:key/<key-id>
> aws logs put-retention-policy \
>   --log-group-name /aws/vendedlogs/OpenSearchIngestion/my-log-pipeline \
>   --retention-in-days 30
>
> # 2. Attach it to the pipeline
> aws osis update-pipeline --pipeline-name my-log-pipeline \
>   --log-publishing-options 'CloudWatchLogDestination={LogGroup=/aws/vendedlogs/OpenSearchIngestion/my-log-pipeline},IsLoggingEnabled=true'
> ```

### Pipeline YAML for CloudWatch Logs → AOS

```yaml
version: "2"
cloudwatch-pipeline:
  source:
    cloudwatch_logs:
      acknowledgments: true
      aws:
        sts_role_arn: "arn:aws:iam::<account>:role/OSIPipelineRole"
        region: "<region>"
  processor:
    - date:
        from_time_received: true
        destination: "@timestamp"
  sink:
    - opensearch:
        hosts: ["https://<domain-endpoint>"]
        index: "cwl-%{yyyy.MM.dd}"
        aws:
          sts_role_arn: "arn:aws:iam::<account>:role/OSIPipelineRole"
          region: "<region>"
```

### Pipeline YAML for CloudWatch Logs → AOSS

```yaml
version: "2"
cloudwatch-pipeline:
  source:
    cloudwatch_logs:
      acknowledgments: true
      aws:
        sts_role_arn: "arn:aws:iam::<account>:role/OSIPipelineRole"
        region: "<region>"
  processor:
    - date:
        from_time_received: true
        destination: "@timestamp"
  sink:
    - opensearch:
        hosts: ["https://<collection-endpoint>"]
        index: "cwl-logs"
        serverless: true
        aws:
          sts_role_arn: "arn:aws:iam::<account>:role/OSIPipelineRole"
          region: "<region>"
```

### Step 3: Configure CloudWatch Subscription Filter

```bash
aws logs put-subscription-filter \
  --log-group-name /aws/lambda/my-function \
  --filter-name osi-filter \
  --filter-pattern "" \
  --destination-arn arn:aws:osis:<region>:<account>:pipeline/my-log-pipeline
```

## Common Index Patterns

| Source | Index Pattern | Fields |
|--------|--------------|--------|
| CloudWatch Logs | `cwl-*` | @timestamp, message, log_group, log_stream |
| OTel Collector | `otel-v1-apm-span-*` | traceId, spanId, serviceName, durationInNanos |
| Fluent Bit | `fluent-bit-*` | @timestamp, log, kubernetes.* |

## AOSS Considerations

- The pipeline role's **IAM policy** must grant `aoss:BatchGetCollection` and `aoss:APIAccessAll` (these are IAM data-plane permissions, not data access policy permissions)
- The **data access policy** must grant the pipeline role the index/collection actions it needs (e.g. `aoss:CreateIndex`, `aoss:WriteDocument`) — see the merge step below
- Network policy must allow OSI pipeline VPC access
- Use `serverless: true` in the sink configuration

### Adding the pipeline role to an AOSS data access policy

You MUST merge the pipeline role into the existing policy rather than replacing it, because overwriting the policy would drop other principals and rules already granted on the collection.

1. Get the current policy and note its `policyVersion`. Use the data access policy name created during provisioning — `<collection-name>-data` in [`provisioning-serverless-provision.md`](provisioning-serverless-provision.md) (Step 3); substitute your actual policy name if it differs:

   ```bash
   aws opensearchserverless get-access-policy --type data \
     --name <collection-name>-data --region <region>
   ```

2. Append the pipeline role ARN to the existing `Principal` array (preserve all existing rules/principals). Grant it only the minimum actions the pipeline needs — scope index-level writes to the target index pattern rather than `aoss:*` on all resource types, because a broad grant lets the pipeline role read or delete unrelated data:
   - `collection` rule: `aoss:DescribeCollectionItems` on `collection/<collection-name>`
   - `index` rule: `aoss:CreateIndex`, `aoss:DescribeIndex`, `aoss:WriteDocument` on `index/<collection-name>/<target-index>*`
   - The role also needs the IAM permissions `aoss:BatchGetCollection` and `aoss:APIAccessAll` (data-plane access), granted in its IAM policy — not the data access policy.
3. Update with the captured version:

   ```bash
   aws opensearchserverless update-access-policy --type data \
     --name <collection-name>-data \
     --policy-version "<current-version>" \
     --policy '<merged-policy-json>' --region <region>
   ```

4. Wait ~30 seconds for propagation, then stop/start the pipeline (see the gotcha below).

## After Changing IAM or Data Access Policies

> **After changing the pipeline role's IAM permissions or an AOSS data access policy, you MUST stop and restart the pipeline**, because OSI caches the assumed-role credentials and will keep failing on the stale permissions until it re-assumes the role:
>
> ```bash
> aws osis stop-pipeline  --pipeline-name <pipeline-name> --region <region>   # wait for STOPPED
> aws osis start-pipeline --pipeline-name <pipeline-name> --region <region>
> ```
>
> After restart, confirm delivery has recovered rather than assuming success: verify CloudTrail recorded the `StopPipeline`/`StartPipeline` calls, and check that the pipeline's health metrics return to normal (e.g. `opensearch.documentsSuccess` climbing and `opensearch.documentErrors`/`dlqS3RecordsFailed` flat) via a CloudWatch alarm on the failure metrics, because a silent post-restart failure means data loss until the next manual check.

## Security Considerations

- Apply least-privilege IAM policies: grant only the specific actions needed (e.g., `es:ESHttpPost`, `es:ESHttpPut`) scoped to the target domain/collection resource ARN.
- All data in transit between OSI pipelines and OpenSearch is encrypted via TLS. Ensure domain or collection enforces HTTPS-only access.
- Use dedicated IAM roles for pipeline execution rather than sharing roles across services.
- Enable CloudTrail at the account level to audit all OSI API calls (pipeline creation, modification, deletion) for compliance monitoring.
- Encrypt the pipeline's CloudWatch log group with a customer-managed KMS key, because pipeline error logs and DLQ records may contain document field values from your data. Create the log group with encryption *before* pipeline creation so it applies from first write — `aws logs create-log-group --log-group-name /aws/vendedlogs/osi-pipeline --kms-key-id <key-arn>` — or attach a key to an existing group with `aws logs associate-kms-key`.
