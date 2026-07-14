# DSQL Authentication & Connection Guide

Part of [DSQL Development Guide](../development-guide.md).

---

## Connection and Authentication

### IAM Authentication

**Principle of least privilege:**

- Grant only `dsql:DbConnect` for standard users
- Reserve `dsql:DbConnectAdmin` for administrative operations
- Link database roles to IAM roles for proper access control
- Use IAM policies to restrict cluster access by resource tags

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "dsql:DbConnect",
      "Resource": "arn:aws:dsql:us-east-1:123456789012:cluster/<cluster-id>",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/Environment": "development"
        }
      }
    }
  ]
}
```

### Token Management

**Rotation strategies:**

- Generate fresh token per connection (simplest, most secure)
- Implement periodic refresh before 15-minute expiration
- Use connection pool hooks for automated refresh
- Handle token expiration gracefully with retry logic

**Best practices:**

- Keep authentication tokens in memory only; discard after use
- Regenerate token on connection errors
- Monitor token generation failures
- Set connection timeouts appropriately

### Secrets Management

**ALWAYS dynamically assign credentials:**

- Use environment variables for configuration
- Store cluster endpoints in AWS Systems Manager Parameter Store
- Use AWS Secrets Manager for any sensitive configuration
- Rotate credentials regularly even though tokens are short-lived

```bash
# Good - Use Parameter Store
export CLUSTER_ENDPOINT=$(aws ssm get-parameter \
  --name /myapp/dsql/endpoint \
  --query 'Parameter.Value' \
  --output text)

# Bad - Hardcoded in code
const endpoint = "abc123.dsql.us-east-1.on.aws" // BAD: Use Parameter Store instead
```

### Connection Rules

Defaults below; verify against the live limits via the AWS MCP Server's `aws___search_documentation` if available (`aurora dsql connection limits`), or check the [DSQL connection limits docs](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/) directly:

- 15-minute IAM auth token expiry (verify via the AWS MCP Server's `aws___search_documentation` if available, or the [DSQL authentication docs](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/): `aurora dsql authentication token`)
- 60-minute connection maximum
- 10,000 connections per cluster
- SSL required

### SSL/TLS Requirements

Aurora DSQL uses the [PostgreSQL wire protocol](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility.html) and enforces SSL:

```
sslmode: verify-full
sslnegotiation: direct      # PostgreSQL 17+ drivers (better performance)
port: 5432
database: postgres           # single database per cluster
```

**Key details:**

- SSL always enabled server-side
- Use `verify-full` to verify server certificate
- Use `direct` TLS negotiation for PostgreSQL 17+ compatible drivers
- System trust store must include Amazon Root CA

### Connection Pooling (Recommended)

For production applications:

- SHOULD Implement connection pooling
- ALWAYS Configure token refresh before expiration
- MUST Set appropriate pool size (e.g., max: 10, min: 2)
- MUST Configure connection lifetime and idle timeout
- MUST Generate fresh token in `BeforeConnect` or equivalent hook

### Security Best Practices

- ALWAYS dynamically set credentials
- MUST use IAM authentication exclusively
- ALWAYS use SSL/TLS with certificate verification
- SHOULD grant least privilege IAM permissions
- ALWAYS rotate tokens before expiration
- SHOULD use connection pooling to minimize token generation overhead

---

## Audit Logging

**CloudTrail integration:**

- Enable CloudTrail logging for DSQL API calls
- Monitor token generation patterns
- Track cluster configuration changes
- Set up alerts for suspicious activity

**Recommended setup:** Enable a CloudTrail trail with data events for DSQL API calls.

**Prerequisite:** The target S3 bucket MUST have SSE-KMS encryption enabled with a bucket policy restricting access to the CloudTrail service principal. The policy MUST include `aws:SourceArn` and `aws:SourceAccount` condition keys to prevent confused-deputy attacks (any other AWS account that knows the bucket name could otherwise direct CloudTrail to write forged logs into your bucket):

```bash
# Ensure S3 bucket has SSE-KMS encryption
aws s3api put-bucket-encryption \
  --bucket my-cloudtrail-bucket \
  --server-side-encryption-configuration '{
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": "arn:aws:kms:us-east-1:123456789012:key/<key-id>"}}]
  }'

# Apply a bucket policy scoped to THIS account's CloudTrail trail.
# Replace 123456789012 with your account ID and dsql-audit-trail with your trail name.
cat > /tmp/cloudtrail-bucket-policy.json <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSCloudTrailAclCheck",
      "Effect": "Allow",
      "Principal": {"Service": "cloudtrail.amazonaws.com"},
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:aws:s3:::my-cloudtrail-bucket",
      "Condition": {
        "StringEquals": {
          "aws:SourceArn": "arn:aws:cloudtrail:us-east-1:123456789012:trail/dsql-audit-trail",
          "aws:SourceAccount": "123456789012"
        }
      }
    },
    {
      "Sid": "AWSCloudTrailWrite",
      "Effect": "Allow",
      "Principal": {"Service": "cloudtrail.amazonaws.com"},
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::my-cloudtrail-bucket/AWSLogs/123456789012/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-acl": "bucket-owner-full-control",
          "aws:SourceArn": "arn:aws:cloudtrail:us-east-1:123456789012:trail/dsql-audit-trail",
          "aws:SourceAccount": "123456789012"
        }
      }
    }
  ]
}
POLICY
aws s3api put-bucket-policy --bucket my-cloudtrail-bucket --policy file:///tmp/cloudtrail-bucket-policy.json

# Create a trail that logs DSQL management events.
# --enable-log-file-validation lets you detect tampered/deleted log files.
# --cloud-watch-logs-* parameters are REQUIRED for the metric filter and
# alarm below to receive events; without them CloudTrail only delivers to S3.
aws cloudtrail create-trail \
  --name dsql-audit-trail \
  --s3-bucket-name my-cloudtrail-bucket \
  --is-multi-region-trail \
  --kms-key-id arn:aws:kms:us-east-1:123456789012:key/<key-id> \
  --enable-log-file-validation \
  --cloud-watch-logs-log-group-arn arn:aws:logs:us-east-1:123456789012:log-group:CloudTrail/DefaultLogGroup:* \
  --cloud-watch-logs-role-arn arn:aws:iam::123456789012:role/CloudTrail_CloudWatchLogs_Role

aws cloudtrail start-logging --name dsql-audit-trail
```

**CloudWatch alarms for security monitoring:**

```bash
# Encrypt the CloudWatch Log Group (DSQL auth events may contain sensitive metadata)
aws logs associate-kms-key \
  --log-group-name CloudTrail/DefaultLogGroup \
  --kms-key-id arn:aws:kms:us-east-1:123456789012:key/<key-id>

# Create a metric filter for failed authentication attempts
aws logs put-metric-filter \
  --log-group-name CloudTrail/DefaultLogGroup \
  --filter-name DSQLFailedAuth \
  --filter-pattern '{ ($.eventSource = "dsql.amazonaws.com") && ($.errorCode = "AccessDenied*") }' \
  --metric-transformations metricName=DSQLFailedAuth,metricNamespace=DSQL/Security,metricValue=1

# Create an alarm on failed auth attempts
# MUST: Enable SSE-KMS encryption on the SNS topic AND apply an access policy
# that restricts sns:Subscribe to verified security contacts. Security alerts
# may contain sensitive metadata; an unrestricted topic leaks that to anyone
# who guesses or learns the topic ARN.
aws cloudwatch put-metric-alarm \
  --alarm-name DSQLFailedAuthAlarm \
  --metric-name DSQLFailedAuth \
  --namespace DSQL/Security \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 1 \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:security-alerts

# Apply an SNS topic access policy that:
#   - Allows CloudWatch Alarms to publish (Service principal cloudwatch.amazonaws.com,
#     scoped via aws:SourceArn to this account's alarms only).
#   - Restricts sns:Subscribe to your AWS organization OR to an explicit list of
#     IAM principals (security on-call). Replace o-xxxxxxxxxx with your AWS
#     Organizations ID, or substitute an `aws:PrincipalArn` condition with explicit
#     ARNs if you don't use Organizations.
cat > /tmp/sns-security-alerts-policy.json <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowCloudWatchAlarmsPublish",
      "Effect": "Allow",
      "Principal": {"Service": "cloudwatch.amazonaws.com"},
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:us-east-1:123456789012:security-alerts",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "123456789012"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:*"
        }
      }
    },
    {
      "Sid": "RestrictSubscribeToOrg",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "sns:Subscribe",
      "Resource": "arn:aws:sns:us-east-1:123456789012:security-alerts",
      "Condition": {
        "StringEquals": {
          "aws:PrincipalOrgID": "o-xxxxxxxxxx"
        }
      }
    },
    {
      "Sid": "DenyEveryoneElse",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "sns:Subscribe",
      "Resource": "arn:aws:sns:us-east-1:123456789012:security-alerts",
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalOrgID": "o-xxxxxxxxxx"
        }
      }
    }
  ]
}
POLICY
aws sns set-topic-attributes \
  --topic-arn arn:aws:sns:us-east-1:123456789012:security-alerts \
  --attribute-name Policy \
  --attribute-value file:///tmp/sns-security-alerts-policy.json

# Enable SSE-KMS encryption on the SNS topic. Security-alert payloads
# (auth-failure metadata, principal ARNs, IP addresses) are sensitive and MUST
# be encrypted at rest. Use a customer-managed KMS key — AWS-managed
# `alias/aws/sns` works but offers less audit + key-rotation control.
aws sns set-topic-attributes \
  --topic-arn arn:aws:sns:us-east-1:123456789012:security-alerts \
  --attribute-name KmsMasterKeyId \
  --attribute-value arn:aws:kms:us-east-1:123456789012:key/<key-id>
```

**Query logging:**

- Enable query logging if available
- Monitor slow queries and connection patterns
- Track failed authentication attempts
- Review logs regularly for anomalies

---

## Access Control

**ALWAYS prefer scoped database roles over the `admin` role.**

- **ALWAYS** use scoped database roles for application connections — reserve `admin` for initial setup and role management
- **MUST** create purpose-specific database roles and connect with `dsql:DbConnect`
- **MUST** place sensitive data (PII, credentials) in dedicated schemas — not `public`
- **MUST** grant only the minimum privileges each role requires
- **SHOULD** audit role mappings: `SELECT * FROM sys.iam_pg_role_mappings;`

For complete role setup instructions, schema separation patterns, and IAM configuration,
see [access-control.md](../access-control.md).

## Additional Resources

- [IAM Authentication Guide (AWS documentation)](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/using-database-and-iam-roles.html)
