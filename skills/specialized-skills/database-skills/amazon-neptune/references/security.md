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

## FIPS endpoints

- For regulated workloads, check the Neptune security documentation for FIPS endpoint availability across the control plane and data plane, plus the supported cipher suites, before committing to an architecture.
