# Security Best Practices

Apply this guidance to every deployment, including development, experimentation, and production.

## IAM and Access Control

- Before Marketplace activation, verify the selected engine variant's permissions in the [AWS managed policies for Timestream for InfluxDB documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/security-iam-awsmanpol-influxdb.html) and the IAM policy versions. Attach only policies the documentation requires. If it requires `AmazonTimestreamInfluxDBFullAccess` or `AmazonTimestreamConsoleFullAccess` for activation, remove them immediately afterward and replace them with a scoped custom policy.
- Follow least privilege: grant only the actions the application actually calls.
- Use IAM roles for EC2, Lambda, and ECS. Never embed long-lived credentials in code or S3.

## InfluxDB API Tokens

- Rotate the initial admin token or password immediately after setup.
- Create per-application scoped tokens with the minimum required permissions, such as read or write access to a specific bucket or database.
- Store tokens in AWS Secrets Manager and configure rotation only when the rotation workflow also updates the token in InfluxDB.
- Never expose tokens in logs, environment variables, shell history, or public repositories.

## Network Isolation

- For existing resources, read `publiclyAccessible` from `GetDbInstance` or `GetDbCluster`. Before creation or update, inspect the API model before asserting public-access availability or mutability. Prefer private placement when the service supports it unless public access is explicitly required.
- For existing resources, use the `port` returned by `GetDbInstance` or `GetDbCluster`; before creation, verify the Create API or SDK model. Restrict security-group ingress for that port to known CIDR ranges or security-group IDs. Never use `0.0.0.0/0`.
- For private resources, choose a remote-access path supported by the Timestream for InfluxDB and VPC documentation.
- For a directly accessible public endpoint, treat security-group restrictions as the minimum network control, not as rate limiting. Allow only trusted client CIDRs, and enforce request-rate and concurrency limits in each calling application or an approved reverse proxy before traffic reaches InfluxDB.
- Callers MUST validate line-protocol writes before submission: reject malformed records, enforce expected measurement, tag, and field names and types, bound payload and batch sizes, and reject or normalize unbounded tag values that could cause cardinality exhaustion.
- Before recommending a load balancer or AWS WAF, verify the Timestream connectivity options and [AWS WAF supported-resource matrix](https://docs.aws.amazon.com/waf/latest/developerguide/waf-chapter.html). Use WAF only through a supported integration; do not present it as direct protection for the native endpoint unless the matrix explicitly lists that resource.
- Before configuring browser response headers, verify the Elastic Load Balancing or CloudFront capability. When supported, emit `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, and a restrictive `Content-Security-Policy`; choose values compatible with the InfluxDB UI and authorized embedding, and test API clients before deployment.

## Encryption

- You MUST require encryption at rest and in transit for every deployment. Verify the service-applied at-rest encryption behavior and supported key choices in the [Data protection documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/data-protection-for-influx-db.html) and the Create and Update API models, including whether and when `kmsKeyId` is accepted. For production workloads, prefer a customer-managed KMS key when the API supports it and the workload requires customer-controlled policy, rotation, revocation, or CloudTrail visibility.
- Load [encryption guidance](encryption.md) for key selection, key policy, backup scope, migration, key lifecycle, TLS, custom domains, load-balancer security, and AWS WAF guidance.
- Before configuring S3 log-delivery encryption, verify the bucket account and Region constraints and supported KMS key ownership arrangements in the log-delivery documentation.
- Enable SSE-KMS on Amazon SNS topics used for alarm notifications and on CloudWatch Logs log groups receiving operational data. Confirm that every SNS topic subscription delivers only to authorized security or operations personnel, and periodically audit subscriptions to prevent unauthorized recipients from receiving sensitive alarm data.

## S3 Bucket Policy for Log Delivery

- Verify the log-delivery service principal, object prefix, bucket ownership constraints, and supported source-condition keys before writing the bucket policy. Use `aws:SourceArn` and `aws:SourceAccount` when the documentation prescribes them.
- Verify log and data-bucket ownership in the service documentation, and apply a customer bucket policy only to buckets the customer manages.

## Auditing

- Check the [Timestream for InfluxDB CloudTrail documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/logging-using-cloudtrail-influxdb.html) before asserting event coverage. Enable CloudTrail for the event classes that documentation lists.
- Encrypt CloudTrail log files in the associated S3 delivery bucket with SSE-KMS, and enable CloudTrail log file validation to detect modification or deletion.
- Verify data-plane, `/metrics`, and native audit-log availability for the selected engine, and state only the coverage the observability documentation confirms.

## References

- [Security best practices for Timestream for InfluxDB](https://docs.aws.amazon.com/timestream/latest/developerguide/security-best-practices.html)
- [AWS managed policies for Timestream for InfluxDB](https://docs.aws.amazon.com/timestream/latest/developerguide/security-iam-awsmanpol-influxdb.html)
- [Security best practices in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [Security best practices for your VPC](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-best-practices.html)
- [Logging Timestream for InfluxDB API calls using AWS CloudTrail](https://docs.aws.amazon.com/timestream/latest/developerguide/logging-using-cloudtrail-influxdb.html)
- [Encrypt CloudTrail log files with AWS KMS keys](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/encrypting-cloudtrail-log-files-with-aws-kms.html)
- [Validate CloudTrail log file integrity](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html)
- [HTTP header modification for Application Load Balancers](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/header-modification.html)
- [Add or remove HTTP headers in CloudFront responses](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-response-headers.html)
