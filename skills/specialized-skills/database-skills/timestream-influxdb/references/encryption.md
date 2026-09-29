# InfluxDB 3 Encryption

- [Choose the Key Before Creation](#choose-the-key-before-creation)
- [Response Scope](#response-scope)
- [Key Requirements](#key-requirements)
- [Key Policy](#key-policy)
- [Transport Security](#transport-security)
- [Verify the Key](#verify-the-key)
- [Monitor Key Changes](#monitor-key-changes)
- [Existing Clusters and Key Loss](#existing-clusters-and-key-loss)
- [References](#references)

## Response Scope

Answer only the topics the user requests and return the answer without narrating retrieval or planning. A question about configuring, changing, disabling, or deleting a key does not request an inventory of encrypted resources. Include encryption scope only when the user explicitly asks which resources the key encrypts. Do not add pricing, rotation, restore, or monitoring sections unless requested; distinguish documented key requirements from optional policy recommendations.

Complete every documentation and API-model retrieval required by the user's requested topics before drafting any part of the answer. A message that invokes a tool MUST NOT contain a partial answer. After all retrievals finish, return one complete, standalone final answer that covers every requested topic; do not rely on prose from an earlier tool-use turn. If another retrieval becomes necessary after drafting starts, perform it and then restate the complete answer after the tool result.

## Choose the Key Before Creation

Before recommending an encryption choice, verify the default encryption behavior and `kmsKeyId` support in the [Data protection in Timestream for InfluxDB documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/data-protection-for-influx-db.html), [`CreateDbCluster` API reference](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_CreateDbCluster.html), and [`UpdateDbCluster` API reference](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_UpdateDbCluster.html). Treat those sources as authoritative. When they document a customer-managed KMS key as a creation option, use the following pattern:

When the documentation offers both an AWS-owned default and a customer-managed KMS key, recommend the customer-managed option for production workloads that require customer-controlled policy, rotation, revocation, and CloudTrail visibility. Use the documented default only when the workload's security requirements accept its key-lifecycle controls.

```bash
aws timestream-influxdb create-db-cluster \
  --name <cluster-name> \
  --db-instance-type <instance-type> \
  --db-parameter-group-identifier <verified-v3-parameter-group-identifier> \
  --vpc-subnet-ids <subnet-1> <subnet-2> \
  --vpc-security-group-ids <security-group-id> \
  --kms-key-id <kms-key-arn> \
  --tags Key=created_by,Value=timestream-skill Key=generation_model,Value={your-model-id} \
  --region <region>
```

Verify the identifier forms accepted for `kmsKeyId` in the `CreateDbCluster` API reference. When a full key ARN is accepted, prefer it so the selected key is unambiguous.

Before naming encryption scope, you MUST retrieve the Data protection documentation. When AWS MCP is available, call `aws___read_documentation` with the documentation URL; otherwise use the client's official-document reader. A failed tool call, model memory, or this file's examples do not count as verification. Do not claim that retrieval succeeded when it did not. Include scope only when the user explicitly asks which resources the key encrypts. If retrieval fails, state that the scope could not be verified and omit those claims. When scope is requested, report each resource exactly as the retrieved source describes it; never infer one resource's behavior from another.

Before advising whether an existing cluster's key can be modified, verify the request parameters in the [`UpdateDbCluster` API reference](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_UpdateDbCluster.html) or the installed AWS SDK service model. When `kmsKeyId` is absent, treat it as creation-only: `update-db-cluster` cannot add, remove, or replace the key.

## Key Requirements

Before recommending or validating a key, verify the supported key account, Region, key spec, key usage, origin, and multi-Region behavior in the [Data protection in Timestream for InfluxDB documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/data-protection-for-influx-db.html) and the [`CreateDbCluster` API reference](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_CreateDbCluster.html). Treat those sources as authoritative; do not assume constraints documented here are permanent.

Before configuring rotation, verify that the selected key type supports automatic rotation and confirm the accepted custom rotation periods in the [AWS KMS rotation documentation](https://docs.aws.amazon.com/kms/latest/developerguide/rotating-keys-enable.html) or API model. Follow organizational policy; use the following example only when the documentation accepts a 365-day period and no shorter period is required:

```bash
aws kms enable-key-rotation \
  --key-id <key-arn> \
  --rotation-period-in-days 365 \
  --region <region>
```

## Key Policy

Add these statements to the key's existing policy. Do not replace its administrative statement. Replace the account, role, and Region placeholders with the identity that calls `create-db-cluster`.

Before presenting or adapting this template, retrieve the [Data protection in Timestream for InfluxDB documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/data-protection-for-influx-db.html) and verify the principal, actions, `kms:ViaService` value, condition keys, and `kms:GrantOperations` values. Use `aws___read_documentation` when AWS MCP is available; otherwise use the client's official-document reader. If retrieval fails, disclose that the policy could not be verified and do not present the template as authoritative. If the retrieved policy differs from the template below, use the documented policy.

```json
{
  "Sid": "Allow Timestream InfluxDB to use the key for resource allocations",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::<account-id>:role/<caller-role>"
  },
  "Action": "kms:CreateGrant",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "kms:ViaService": "timestream-influxdb.<region>.amazonaws.com"
    },
    "ForAllValues:StringEquals": {
      "kms:GrantOperations": [
        "Decrypt",
        "Encrypt",
        "GenerateDataKey",
        "GenerateDataKeyWithoutPlaintext",
        "ReEncryptFrom",
        "ReEncryptTo",
        "CreateGrant",
        "DescribeKey"
      ]
    },
    "Bool": {
      "kms:GrantIsForAWSResource": "true"
    }
  }
},
{
  "Sid": "Allow Timestream InfluxDB to describe the key for resource allocations",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::<account-id>:role/<caller-role>"
  },
  "Action": "kms:DescribeKey",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "kms:ViaService": "timestream-influxdb.<region>.amazonaws.com"
    }
  }
}
```

The `kms:ViaService` condition limits use to Timestream for InfluxDB in the selected Region. `kms:GrantIsForAWSResource` and `kms:GrantOperations` constrain the grants the service can create. The tested Timestream for InfluxDB resource-allocation flow requires `CreateGrant` in `kms:GrantOperations` so the service can create the subordinate resource grants used by the cluster. Retain it unless the service documentation and an end-to-end cluster-creation test establish a different policy.

## Transport Security

Before recommending a custom-domain, load-balancer, response-header, or AWS WAF design, verify the Timestream for InfluxDB networking documentation and the linked Elastic Load Balancing, CloudFront, and AWS WAF integration documentation. Use only integrations those sources support.

Verify the endpoint transport requirements before advising. When the service documentation requires HTTPS, keep every connection to the InfluxDB endpoint encrypted and validate the service certificate. If a supported architecture exposes a custom domain through a load balancer, use an ACM-managed certificate for TLS termination instead of a self-managed certificate.

For browser-facing traffic through an Application Load Balancer, configure ALB response-header modification to emit `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, and a restrictive `Content-Security-Policy`. If CloudFront is also used, apply an equivalent CloudFront response headers policy. Choose values compatible with the InfluxDB UI and authorized embedding, and test API clients before deployment.

For an internet-facing load balancer, use AWS WAF only through an integration listed as supported by AWS WAF. If the integration documentation does not list Network Load Balancers, use an Application Load Balancer or another supported integration when Layer 7 protection is required.

Restrict load-balancer security-group ingress to trusted client CIDR ranges or security-group IDs. Never use `0.0.0.0/0`.

## Verify the Key

```bash
aws timestream-influxdb get-db-cluster \
  --db-cluster-id <cluster-id> \
  --query kmsKeyId \
  --output text \
  --region <region>
```

Retrieve the `GetDbCluster` response documentation before interpreting `kmsKeyId`. Positively verify a specific customer-managed KMS key by comparing the returned ARN with the requested key ARN: "A matching ARN confirms that the cluster uses the requested customer-managed KMS key." If the current documentation explicitly states that an absent `kmsKeyId` identifies AWS-owned default encryption, you may report that documented default-key status, but distinguish it from positive verification of a specific customer-managed KMS key. Never use absence to identify a specific customer-managed key or supply missing-field semantics that the retrieved source does not define.

## Monitor Key Changes

Record AWS KMS management events with an AWS CloudTrail trail that delivers to CloudWatch Logs. Encrypt the CloudTrail S3 delivery bucket with SSE-KMS and enable CloudTrail log-file validation to detect modification or deletion. Encrypt the CloudWatch Logs log group with SSE-KMS using a customer-managed KMS key. Create metric filters and CloudWatch alarms scoped to the cluster's customer-managed KMS key ARN for `DisableKey`, `ScheduleKeyDeletion`, and `RevokeGrant`. Route notifications through an encrypted Amazon SNS topic. Confirm that every topic subscription delivers only to authorized security or operations personnel, and periodically audit subscriptions to prevent unauthorized recipients from receiving sensitive alarm data. Test the alarm in a non-production account.

## Existing Clusters and Key Loss

Apply the `UpdateDbCluster` verification above before recommending a migration. When `kmsKeyId` is absent from that operation, move an existing cluster to a customer-managed KMS key by creating a new cluster with `--kms-key-id`, migrating through the standard write APIs, updating clients, and deleting the old cluster after validation. Before restoring a customer-managed backup, verify the restrictions in the [`RestoreFromDbBackup` Boto3 reference](https://docs.aws.amazon.com/boto3/latest/reference/services/timestream-influxdb/client/restore_from_db_backup.html) and the [customer-managed backup and restore documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-customer-managed-backup-restore.html). When those sources prohibit `REPLACE_EXISTING` for a cluster encrypted with a customer-managed KMS key, use `NEW_RESOURCE`.

Before describing the effect of disabling, revoking access to, re-enabling, or deleting the key, you MUST retrieve the key-lifecycle behavior in the Data protection documentation. Use `aws___read_documentation` when AWS MCP is available; otherwise use the client's official-document reader. A failed tool call does not count as retrieval. Warn about availability and recoverability exactly as the retrieved source describes them. If retrieval fails, say that the effects could not be verified and do not infer them from generic AWS KMS behavior.

## References

- [AWS KMS best practices](https://docs.aws.amazon.com/kms/latest/developerguide/best-practices.html)
- [Rotating AWS KMS keys](https://docs.aws.amazon.com/kms/latest/developerguide/rotate-keys.html)
- [Data protection in Timestream for InfluxDB](https://docs.aws.amazon.com/timestream/latest/developerguide/data-protection-for-influx-db.html)
- [Customer-managed backup and restore for InfluxDB 3](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-customer-managed-backup-restore.html)
- [Monitor CloudTrail log files with CloudWatch Logs](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/monitor-cloudtrail-log-files-with-cloudwatch-logs.html)
- [HTTP header modification for Application Load Balancers](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/header-modification.html)
- [Add or remove HTTP headers in CloudFront responses](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-response-headers.html)
