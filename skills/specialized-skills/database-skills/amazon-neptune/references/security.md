# Neptune Security Reference

Detailed security guidance for Amazon Neptune Database and Neptune Analytics.

## Encryption at rest

- **Neptune Database**: encryption at rest using AWS KMS is **not enabled by default** via CLI/SDK (the console enforces it for new clusters). Always specify `--storage-encrypted` and optionally `--kms-key-id` when creating clusters. Cannot be changed after creation.
- **Neptune Analytics**: always encrypted at rest using an AWS-managed key (or specify `--kms-key-identifier` for a customer-managed KMS key). No opt-out.

## Encryption in transit

- Neptune requires SSL/TLS for ALL connections (see the Neptune security documentation for the minimum TLS version it enforces). You cannot connect over unencrypted protocols. Use `wss://` for Gremlin WebSocket and `https://` for HTTP/openCypher.

## IAM authentication

- Strongly recommended for ALL environments, including dev and test — do not skip it when helping a user stand up a non-production cluster. Enable with `--enable-iam-database-authentication` on the cluster. Requires SigV4-signed requests.
- **Neptune Analytics**: IAM auth is always required (SigV4). No opt-out.

## VPC isolation and public endpoints

- Neptune Database is deployed inside a VPC. Use VPC endpoints, or enable public endpoints (with IAM auth — check the Neptune userguide "public endpoints" page for the minimum engine version). Never expose without IAM auth.
- When using public endpoints, scope the cluster's security-group inbound rule on port 8182 to specific CIDR ranges or trusted source security groups — do NOT use `0.0.0.0/0`. Network-level restriction is defense-in-depth on top of IAM auth.
- Neptune Analytics graphs reside outside the customer VPC. Restrict access with Private Graph Endpoints / VPC endpoints for Neptune Analytics. Note that VPC endpoint policies apply to the Neptune Analytics data-plane service (`neptune-graph-data`); the control-plane service (`neptune-graph`) does not support VPC endpoint policies.

## Audit logging and monitoring

- Enable CloudWatch Logs exports: `--enable-cloudwatch-logs-exports audit` (requires `neptune_enable_audit_log=1` in the cluster parameter group). Available log types: `audit`, `slowquery`.
- Encrypt the CloudWatch Logs group with a customer-managed KMS key — audit and slow-query logs can expose graph data patterns and query details. Associate the key when creating the log group, or call `aws logs associate-kms-key` afterwards.
- Enable CloudTrail for control-plane API call auditing.
- Consider CloudWatch alarms on key metrics (graph memory utilization, import-task failures) so operators are alerted to anomalous activity such as unexpectedly large exports or unrecognized import tasks.

## S3 data encryption (bulk loader / exports)

- S3 buckets used for Neptune bulk loading or exports must have default encryption enabled (`SSE-S3` or `SSE-KMS`).
- Attach a bucket policy that denies non-TLS traffic (`Condition: {"Bool": {"aws:SecureTransport": "false"}}`).
- Use least-privilege IAM roles scoped to specific S3 prefixes (e.g., `Resource: arn:aws:s3:::your-bucket/neptune/*`), not service-wide access. Do not attach `*FullAccess` managed policies or `Resource:"*"` to production roles.
- Restrict access with `aws:SourceAccount` and, where applicable, `aws:SourceVpc` condition keys.
- Enable S3 server access logging or CloudTrail S3 data events on export buckets to audit access to exported graph data.

## Credentials

- Use ephemeral credentials only: IAM roles, STS `AssumeRole`, or SSO. Never long-lived IAM user access keys.

## Recurring Neptune Analytics automation

- Run scheduled snapshot, import, query, export, stop, and start workflows under a dedicated IAM role, such as a Lambda or Step Functions execution role. Use its ephemeral credentials and SigV4-signed AWS API calls; use IAM database authentication for Neptune Database access.
- Grant only the lifecycle actions the workflow needs and scope them to the specific graph ARN. A stop/start workflow needs `neptune-graph:StopGraph` and `neptune-graph:StartGraph`; do not grant `neptune-graph:DeleteGraph` unless a separately authorized, change-controlled deletion workflow requires it. Never grant `neptune-graph:*` or use `Resource:"*"`.
- Deliver CloudTrail continuously to CloudWatch Logs and monitor `CreateGraphUsingImportTask`, `ExecuteQuery`, `StopGraph`, `StartGraph`, and `DeleteGraph`. Create metric filters and CloudWatch alarms for `DeleteGraph` and for `StopGraph` calls whose principal is not an approved automation role, then route alarms to the team's SNS or on-call destination.
- Encrypt both the CloudWatch Logs log group receiving CloudTrail events and the SNS alarm topic with a customer-managed KMS key; query and lifecycle events can contain sensitive graph-operation metadata.
- Restrict the SNS topic access policy so only approved accounts and principals can publish or subscribe, and verify that every subscription endpoint belongs to authorized on-call personnel.
- Neptune Analytics remains encrypted at rest while stopped. Use a customer-managed KMS key for sensitive workloads and TLS for every database or graph data-plane connection.

## FIPS endpoints

- For regulated workloads, check the Neptune security documentation for FIPS endpoint availability across the control plane and data plane, plus the supported cipher suites, before committing to an architecture.
