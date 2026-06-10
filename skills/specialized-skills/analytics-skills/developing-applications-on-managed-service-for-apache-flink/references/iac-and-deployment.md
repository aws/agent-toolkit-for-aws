# Infrastructure as Code and Deployment Guide

## Overview

This guide covers IaC patterns and deployment automation for Amazon Managed Service for Apache Flink applications. Use it when generating CloudFormation, CDK, Terraform, or deployment scripts for MSF applications. The patterns here address common deployment ordering issues, IAM configuration, and resource dependencies that are specific to MSF.

## CRITICAL: MSF Application JAR Dependency

**The most common IaC failure for MSF is a deployment ordering problem: the MSF application resource requires the application JAR to exist in S3 at creation time.**

When CloudFormation (or any IaC tool) creates a `AWS::KinesisAnalyticsV2::Application` resource with `ApplicationConfiguration.ApplicationCodeConfiguration` pointing to an S3 bucket and key, the MSF service validates that the JAR exists during resource creation. If the JAR is not yet uploaded, the stack fails with:

```
Resource handler returned message: "Please check the role provided or validity of S3 location
you provided. We are unable to get the specified fileKey: <key> in the specified bucket: <bucket>"
```

### Solution: Two-Phase Deployment

**Always structure MSF deployments in two phases:**

1. **Phase 1 — Infrastructure**: Deploy all supporting resources (S3 buckets, Kinesis streams, IAM roles, CloudWatch log groups, VPC resources). This phase does NOT include the MSF application itself.
2. **JAR Upload**: Build the application JAR and upload it to the S3 bucket created in Phase 1.
3. **Phase 2 — Application**: Deploy the MSF application resource, referencing the JAR that now exists in S3.

This applies to all IaC tools: CloudFormation, CDK, Terraform, SAM, etc.

### CloudFormation: Two-Stack Pattern

Split the deployment into two CloudFormation stacks:

**Stack 1 — Infrastructure (`cfn-infra.yaml`)**:

- S3 bucket for JAR staging
- S3 bucket for application output (if applicable)
- Kinesis streams or Kafka/MSK resources
- IAM execution role for the MSF application
- CloudWatch log group and log stream
- VPC, subnets, security groups (if VPC deployment)
- Exports: bucket names, stream ARNs, role ARN, log group/stream ARNs

**Stack 2 — Application (`cfn-app.yaml`)**:

- `AWS::KinesisAnalyticsV2::Application` resource
- `AWS::KinesisAnalyticsV2::ApplicationCloudWatchLoggingOption` (if not inline)
- Imports: references from Stack 1 via `Fn::ImportValue` or parameters

**Deploy script ordering:**

```bash
# 1. Deploy infrastructure
aws cloudformation deploy --template-file cfn-infra.yaml --stack-name my-app-infra ...

# 2. Build and upload JAR
mvn clean package -q
aws s3 cp target/my-app.jar s3://${JAR_BUCKET}/${JAR_KEY}

# 3. Deploy application (JAR now exists in S3)
aws cloudformation deploy --template-file cfn-app.yaml --stack-name my-app ...
```

### CDK: Deployment Ordering with Dependencies

In CDK, use separate stacks or ensure the JAR upload happens before the MSF application construct is created. CDK does not natively upload JARs during synthesis — you need a custom resource or a deploy script wrapper.

**Option A — Two CDK stacks with a script wrapper:**

```typescript
// InfraStack: buckets, streams, IAM, logs
// AppStack: MSF application (depends on InfraStack)
// Deploy script uploads JAR between the two stack deployments
```

**Option B — CDK `BucketDeployment` construct:**

```typescript
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';

// Upload JAR to S3 as part of the CDK deployment
const jarDeployment = new s3deploy.BucketDeployment(this, 'JarDeployment', {
  sources: [s3deploy.Source.asset('./target')],
  destinationBucket: jarBucket,
  destinationKeyPrefix: 'jars/',
});

// Ensure MSF application is created AFTER the JAR is uploaded
flinkApp.node.addDependency(jarDeployment);
```

### Terraform: `depends_on` for Upload Ordering

In Terraform, use `aws_s3_object` to upload the JAR and add an explicit `depends_on` to the MSF application resource:

```hcl
resource "aws_s3_object" "app_jar" {
  bucket = aws_s3_bucket.jar_bucket.id
  key    = "jars/my-app.jar"
  source = "target/my-app.jar"
  etag   = filemd5("target/my-app.jar")
}

resource "aws_kinesisanalyticsv2_application" "flink_app" {
  name                   = "my-flink-app"
  runtime_environment    = "FLINK-2_2"  # Default for new apps. Use FLINK-1_20 only when migrating an existing 1.20 app and state compatibility forbids the upgrade.
  service_execution_role = aws_iam_role.flink_role.arn

  application_configuration {
    application_code_configuration {
      code_content {
        s3_content_location {
          bucket_arn = aws_s3_bucket.jar_bucket.arn
          file_key   = aws_s3_object.app_jar.key
        }
      }
      code_content_type = "ZIPFILE"
    }
    # ... other configuration
  }

  depends_on = [aws_s3_object.app_jar]
}
```

## IAM Role Configuration

The MSF application's IAM execution role needs permissions for all AWS resources the application accesses. A common mistake is missing permissions, which causes the application to fail at runtime rather than at deployment.

### Minimum Required Permissions

Every MSF application needs at minimum:

```yaml
# CloudWatch Logs (required for application logging)
# Scope to the application's log group, not log-group:* — that grants logs
# permissions across every group in the account.
- Effect: Allow
  Action:
    - logs:PutLogEvents
    - logs:DescribeLogStreams
  Resource:
    - !Sub "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/kinesis-analytics/${ApplicationName}"
    - !Sub "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/kinesis-analytics/${ApplicationName}:log-stream:*"

# DescribeLogGroups does not support resource-level permissions
- Effect: Allow
  Action:
    - logs:DescribeLogGroups
  Resource: "*"

# S3 JAR bucket (required to read the application JAR), and KMS permissions if encrypted by a CMK
- Effect: Allow
  Action:
    - s3:GetObject
    - s3:GetObjectVersion
  Resource:
    - !Sub "${JarBucket.Arn}/*"
```

### Common Source/Sink Permissions

**Kinesis Data Streams (source)**:

```yaml
- Effect: Allow
  Action:
    - kinesis:DescribeStream
    - kinesis:GetShardIterator
    - kinesis:GetRecords
    - kinesis:ListShards
    - kinesis:DescribeStreamSummary
    - kinesis:DescribeStreamConsumer
    - kinesis:SubscribeToShard        # Required for EFO
    - kinesis:RegisterStreamConsumer   # Required for EFO
    - kinesis:DeregisterStreamConsumer # Required for EFO
  Resource:
    - !GetAtt KinesisStream.Arn
    - !Sub "${KinesisStream.Arn}/consumer/*"  # Required for EFO
```

**Kinesis Data Streams (sink)**:

```yaml
- Effect: Allow
  Action:
    - kinesis:PutRecord
    - kinesis:PutRecords
    - kinesis:DescribeStream
    - kinesis:DescribeStreamSummary
  Resource:
    - !GetAtt OutputKinesisStream.Arn
```

**S3 (sink)**:

```yaml
- Effect: Allow
  Action:
    - s3:PutObject
    - s3:GetObject
    - s3:ListBucket
    - s3:DeleteObject
    - s3:GetBucketLocation
    - s3:AbortMultipartUpload
    - s3:ListMultipartUploadParts
  Resource:
    - !GetAtt OutputBucket.Arn
    - !Sub "${OutputBucket.Arn}/*"
```

**Kafka/MSK (source or sink)**:

```yaml
# VPC access for MSK. The describe* and *NetworkInterface* actions don't
# accept ARN-scoped resources, so the resource has to be "*" — but you can
# (and should) constrain them with condition keys to the specific VPC/region.
# Example: ec2:Vpc on the network-interface actions, aws:RequestedRegion on
# the describe actions. See guideline 10 (condition keys) below.
- Effect: Allow
  Action:
    - ec2:DescribeVpcs
    - ec2:DescribeSubnets
    - ec2:DescribeSecurityGroups
    - ec2:DescribeDhcpOptions
    - ec2:CreateNetworkInterface
    - ec2:CreateNetworkInterfacePermission
    - ec2:DescribeNetworkInterfaces
    - ec2:DeleteNetworkInterface
  Resource: "*"
  Condition:
    StringEquals:
      aws:RequestedRegion: !Ref AWS::Region
    # For CreateNetworkInterface / CreateNetworkInterfacePermission you can
    # additionally constrain to the application's VPC:
    # ArnEquals:
    #   ec2:Vpc: !Sub "arn:aws:ec2:${AWS::Region}:${AWS::AccountId}:vpc/${VpcId}"
```

### IAM Anti-Patterns

- **Do not use `*` for resource ARNs in production.** Scope permissions to the specific streams, buckets, and log groups the application uses.
- **Do not grant `s3:*` or `kinesis:*`.** Use the minimum set of actions listed above.
- **Do not forget the consumer sub-resource ARN for EFO.** `SubscribeToShard` requires permissions on `stream/*/consumer/*`, not just the stream ARN.

## MSF Application Resource Configuration

### CloudFormation `AWS::KinesisAnalyticsV2::Application`

Key configuration sections and their correct usage:

```yaml
FlinkApplication:
  Type: AWS::KinesisAnalyticsV2::Application
  Properties:
    ApplicationName: !Ref ApplicationName
    RuntimeEnvironment: !Ref FlinkRuntimeEnvironment  # FLINK-2_2 (default for new apps). FLINK-1_20 only for in-place upgrades of existing 1.20 apps.
    ServiceExecutionRole: !GetAtt FlinkRole.Arn
    ApplicationConfiguration:
      # JAR location — JAR must exist before this resource is created
      ApplicationCodeConfiguration:
        CodeContent:
          S3ContentLocation:
            BucketARN: !GetAtt JarBucket.Arn
            FileKey: !Ref JarS3Key
        CodeContentType: ZIPFILE
      # Runtime properties — equivalent to MSF console "Runtime properties"
      EnvironmentProperties:
        PropertyGroups:
          - PropertyGroupId: "kinesis.source"
            PropertyMap:
              stream.arn: !GetAtt InputStream.Arn
              aws.region: !Ref AWS::Region
          - PropertyGroupId: "s3.sink"
            PropertyMap:
              bucket.name: !Ref OutputBucket
              path.prefix: "output/"
      # Parallelism and scaling
      FlinkApplicationConfiguration:
        ParallelismConfiguration:
          ConfigurationType: CUSTOM
          Parallelism: !Ref Parallelism          # Total parallelism (= KPU count × par/KPU)
          ParallelismPerKPU: !Ref ParallelismPerKPU
          AutoScalingEnabled: true
        CheckpointConfiguration:
          ConfigurationType: CUSTOM
          CheckpointingEnabled: true
          CheckpointInterval: 60000
          MinPauseBetweenCheckpoints: 5000
        MonitoringConfiguration:
          ConfigurationType: CUSTOM
          LogLevel: INFO
          MetricsLevel: APPLICATION
```

### Key Configuration Notes

- **`RuntimeEnvironment`**: For new applications, use `FLINK-2_2` (production-recommended default). Use `FLINK-1_20` only when migrating an existing 1.20 application and state compatibility prevents an in-place upgrade (see [flink-2x-migration.md](flink-2x-migration.md) for state-break patterns). The valid enum values come from the `kinesisanalyticsv2` API; the version-segment format mirrors the underlying Flink minor version with an underscore separator (`FLINK-<major>_<minor>`). For the full list of accepted values, see the [`kinesisanalyticsv2 create-application` CLI reference](https://awscli.amazonaws.com/v2/documentation/api/latest/reference/kinesisanalyticsv2/create-application.html), and for migration steps see [flink-2x-migration.md](flink-2x-migration.md).
- **`CodeContentType`**: Always `ZIPFILE` for JAR files (this is the correct value despite the name).
- **`ConfigurationType`**: Set to `CUSTOM` to override defaults. If set to `DEFAULT`, the service ignores your parallelism/checkpoint settings.
- **`Parallelism`**: This is the total parallelism, which equals KPU count × ParallelismPerKPU. For example, 8 KPUs with ParallelismPerKPU=1 means Parallelism=8.
- **`AutoScalingEnabled`**: Set to `true` for production workloads. See [Resource Optimization](resource-optimization.md) for auto-scaling behavior details.
- **`MetricsLevel`**: Use `APPLICATION` for production. `OPERATOR`, `TASK`, and `PARALLELISM` levels increase CloudWatch metric cardinality and cost significantly.

## Deployment Script Patterns

### Build, Deploy, and Start Pattern

A complete deployment script should handle: build → infrastructure deploy → JAR upload → app deploy → code update → start.

**Key considerations:**

- Always build the JAR first and verify it exists before uploading.
- Use `aws cloudformation deploy` (or equivalent) with `--no-fail-on-empty-changeset` to make scripts idempotent.
- After updating the JAR in S3, call `UpdateApplication` with the new S3 object version to point the running application at the new code.
- Starting the application is a separate API call (`StartApplication`) — CloudFormation creates the application in a stopped state.

### Updating a Running Application's Code

To deploy new code to an existing MSF application:

```bash
# 1. Upload new JAR
aws s3 cp target/my-app.jar s3://${JAR_BUCKET}/${JAR_KEY}

# 2. Get current application version
CURRENT_VERSION=$(aws kinesisanalyticsv2 describe-application \
  --application-name my-app \
  --query 'ApplicationDetail.ApplicationVersionId' \
  --output text)

# 3. Update application code reference
aws kinesisanalyticsv2 update-application \
  --application-name my-app \
  --current-application-version-id ${CURRENT_VERSION} \
  --application-configuration-update '{
    "ApplicationCodeConfigurationUpdate": {
      "CodeContentUpdate": {
        "S3ContentLocationUpdate": {
          "BucketARNUpdate": "arn:aws:s3:::'"${JAR_BUCKET}"'",
          "FileKeyUpdate": "'"${JAR_KEY}"'"
        }
      },
      "CodeContentTypeUpdate": "ZIPFILE"
    }
  }'

# 4. Pick up the new code based on current application state.
#    From RUNNING, update-application auto-restarts the app (UPDATING → RUNNING,
#    typically 10–30s downtime depending on state size) — no explicit stop/start needed.
#    From READY (stopped), update-application stays in READY — start the app explicitly
#    to pick up the new code.
#    See application-lifecycle.md for the full state-transition table.
STATUS=$(aws kinesisanalyticsv2 describe-application \
  --application-name my-app \
  --query 'ApplicationDetail.ApplicationStatus' --output text)

if [ "$STATUS" = "READY" ]; then
  aws kinesisanalyticsv2 start-application --application-name my-app \
    --run-configuration '{
      "ApplicationRestoreConfiguration": {
        "ApplicationRestoreType": "RESTORE_FROM_LATEST_SNAPSHOT"
      }
    }'
fi
# Otherwise (RUNNING/UPDATING), poll describe-application until ApplicationStatus
# returns to RUNNING to confirm the auto-restart completed.
```

For guidance on troubleshooting errors after a Flink job upgrade, see [first-fault-isolation.md](first-fault-isolation.md).

Avoid an explicit `stop-application` → `start-application` cycle for code updates on a
RUNNING app. That pattern incurs a full graceful-stop drain plus cold start instead
of the ~10–30s in-place restart that `update-application` performs, and it
contradicts the lifecycle guidance in [application-lifecycle.md](application-lifecycle.md).

### Teardown

When deleting MSF resources:

1. Stop the application first (`StopApplication` API or `Force=true` if stuck).
2. Delete the application stack (MSF application resource).
3. Delete the infrastructure stack (buckets, streams, etc.).
4. S3 buckets with objects require emptying before CloudFormation can delete them — use a custom resource or script.

## CloudFormation vs CDK vs Terraform Comparison for MSF

| Aspect | CloudFormation | CDK | Terraform |
|--------|---------------|-----|-----------|
| JAR upload handling | Manual (script between stack deploys) | `BucketDeployment` construct or manual | `aws_s3_object` resource with `depends_on` |
| Two-phase deployment | Two separate templates | Two stacks or dependency ordering | `depends_on` between resources |
| Application properties | Inline YAML `PropertyGroups` | Typed constructs | HCL `environment_properties` block |
| Drift detection | Supported | Via CloudFormation | Via `terraform plan` |
| Rollback | Automatic on stack failure | Via CloudFormation | Manual `terraform apply` with previous state |

## Common IaC Mistakes to Avoid

1. **Single-stack MSF deployment without pre-uploaded JAR** — The MSF application resource will fail if the JAR doesn't exist in S3. Always use two-phase deployment.
2. **Missing IAM permissions** — The application will start but fail at runtime. Test with the minimum permission set listed above.
3. **Using `ConfigurationType: DEFAULT` with custom values** — The service ignores your parallelism and checkpoint settings. Always use `CUSTOM`.
4. **Hardcoding stream names instead of ARNs** — Use ARNs for cross-account and cross-region compatibility.
5. **Forgetting CloudWatch log permissions** — The application runs but produces no logs, making debugging impossible.
6. **Not setting `CAPABILITY_NAMED_IAM`** — CloudFormation stacks with IAM roles require this capability flag.
7. **S3 bucket cleanup on delete** — CloudFormation cannot delete non-empty S3 buckets. Add a custom resource or use `DeletionPolicy: Retain` and clean up manually.

## References

- See [Best Practices](best-practices.md) for application code patterns and configuration separation
- See [Resource Optimization](resource-optimization.md) for KPU sizing and parallelism configuration
- See [Monitoring and Metrics](monitoring-and-metrics.md) for CloudWatch alarm setup
- See [Logging Configuration](logging-configuration.md) for CloudWatch Logs setup
- See [Kinesis Connector Guide](kinesis-connector-guide.md) for EFO IAM permissions
