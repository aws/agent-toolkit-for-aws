# Minimum IAM Policy

The `endpoint-diagnostics` skill requires these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DescribeEndpoint",
      "Effect": "Allow",
      "Action": "sagemaker:DescribeEndpoint",
      "Resource": "arn:aws:sagemaker:REGION:ACCOUNT_ID:endpoint/ENDPOINT_NAME"
    },
    {
      "Sid": "CloudWatchMetrics",
      "Effect": "Allow",
      "Action": "cloudwatch:GetMetricData",
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": "logs:FilterLogEvents",
      "Resource": "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/sagemaker/Endpoints/*:*"
    }
  ]
}

```

## Scoping Notes

- **sagemaker:DescribeEndpoint** — Scope to specific endpoint(s) by replacing `ENDPOINT_NAME` with the actual name, or use `*` for all endpoints in the account.
- **cloudwatch:GetMetricData** — Cannot be resource-scoped; `*` is required.
- **logs:FilterLogEvents** — Scoped to SageMaker endpoint log groups. The trailing `:*` is required by IAM for log group actions.
- **Graceful degradation** — If any permission is missing, the skill continues collecting data from the other APIs and reports the permission error.
