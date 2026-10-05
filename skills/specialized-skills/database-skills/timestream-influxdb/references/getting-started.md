# Getting Started and Setup

## When to Activate

User wants to create a new Timestream for InfluxDB instance or cluster, connect to an existing one, choose between engine variants, or configure authentication.

## Workflow

### 1. Determine Engine Variant

Ask the user one question: "Are you starting a new project or working with an existing InfluxDB deployment?"

- **New project** → Recommend InfluxDB 3 (SQL support, Processing Engine, better high-cardinality handling)
- **Existing V2 deployment** → Stay on V2 unless they want to migrate (route to `migration`)
- **Need read scaling** → Verify the supported read-scaling options; use a Read Replica Cluster only when the engine and licensing documentation supports it for the selected variant

### 2. Provision

Before either V2 creation command, store the initial username and generated password as JSON in Secrets Manager. Retrieve that `SecretString` to a mode-600 file on an encrypted volume, use it as CLI input, and delete it immediately after creation:

```bash
V2_ADMIN_SECRET_ID="/timestream-influxdb/<resource-name>/initial-admin"
V2_ADMIN_INPUT="<mode-600-json-file-on-encrypted-volume>"
umask 077
aws secretsmanager get-secret-value \
  --secret-id "$V2_ADMIN_SECRET_ID" \
  --query SecretString --output text > "$V2_ADMIN_INPUT"
```

Keep shell tracing disabled. The password is not a literal command argument or written to shell history.

**InfluxDB 2 (standalone instance):**

```bash
aws timestream-influxdb create-db-instance \
  --cli-input-json "file://${V2_ADMIN_INPUT}" \
  --name my-influxdb \
  --db-instance-type <instance-type> \
  --db-storage-type <storage-type> \
  --allocated-storage <allocated-storage-gib> \
  --deployment-type SINGLE_AZ \
  --vpc-subnet-ids subnet-abc \
  --vpc-security-group-ids sg-abc \
  --db-parameter-group-identifier <param-group-id> \
  --organization my-org --bucket my-bucket \
  --tags Key=created_by,Value=timestream-skill Key=generation_model,Value={your-model-id}
rm -f "$V2_ADMIN_INPUT"
```

Before selecting `<instance-type>`, `<storage-type>`, or `<allocated-storage-gib>`, verify the supported DB instance classes, storage types, and storage ranges for the V2 deployment type and Region in the [Timestream for InfluxDB documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/timestream-for-influxdb.html) and `CreateDbInstance` API model. Encryption at rest is required; verify the service-applied encryption behavior and supported key choices in the Data protection documentation and `CreateDbInstance` API model.

For production instances, inspect `CreateDbInstance` for create-time log-delivery support. When supported, configure log delivery during creation with the documented request shape and apply the bucket-policy and SSE-KMS controls in [Log Delivery to S3](#log-delivery-to-s3). Do not pass a log-delivery field when the operation does not accept it.

> **Security best practice — InfluxDB V2 credentials:**
>
> - Keep the generated password in Secrets Manager and do not print the secret value.
> - Rotate the initial admin password immediately after first login; it is set during instance creation and should not be used by applications.
> - Create scoped API tokens for each application or service — never share the operator token.
> - The engine does not support automatic token expiration or rotation. Token rotation is the customer's responsibility. There is no automatic synchronization between AWS Secrets Manager and the engine's token management layer.
> - For InfluxDB V3 or new deployments, the preferred approach is Secrets Manager-based Bearer tokens provisioned automatically by the service.

**InfluxDB 2 Read Replica Cluster:**

```bash
aws timestream-influxdb create-db-cluster \
  --cli-input-json "file://${V2_ADMIN_INPUT}" \
  --name my-rr-cluster \
  --db-instance-type <instance-type> \
  --db-storage-type <storage-type> \
  --allocated-storage <allocated-storage-gib> \
  --deployment-type MULTI_NODE_READ_REPLICAS \
  --vpc-subnet-ids subnet-az1 subnet-az2 \
  --vpc-security-group-ids sg-abc \
  --db-parameter-group-identifier <param-group-id> \
  --organization my-org --bucket my-bucket \
  --tags Key=created_by,Value=timestream-skill Key=generation_model,Value={your-model-id}
rm -f "$V2_ADMIN_INPUT"
```

Before selecting `<instance-type>`, `<storage-type>`, or `<allocated-storage-gib>`, verify the supported DB instance classes, storage types, and storage ranges for the V2 Read Replica deployment type and Region in the Timestream for InfluxDB documentation and `CreateDbCluster` API model.

For production Read Replica Clusters, inspect `CreateDbCluster` for create-time log-delivery support. When supported, configure log delivery during creation with the documented request shape and apply the bucket-policy and SSE-KMS controls in [Log Delivery to S3](#log-delivery-to-s3). Do not pass a log-delivery field when the operation does not accept it.

> **V2 Read Replica security:** Encryption at rest is required. Before creation, verify the service-applied encryption and supported key choices for V2 Read Replica Clusters in the [Data protection documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/data-protection-for-influx-db.html) and `CreateDbCluster` API model. Pass `--kms-key-id` only when the API supports it for the selected engine variant. Verify the credential-secret response field in the API model; when the service returns `influxAuthParametersSecretArn`, retrieve the initial admin credentials from that Secrets Manager secret, rotate the password immediately after setup, and use a separate scoped token for each application.

#### InfluxDB 3 Core Creation Contract

The current [`CreateDbCluster` API contract](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_CreateDbCluster.html) for InfluxDB 3 Core is:

1. **Use `create-db-cluster`.** Never substitute the V2 `create-db-instance` operation.
2. **Use the exact default parameter-group identifier `InfluxDBV3Core`.** Do not substitute a guessed identifier or a V2 parameter group.
3. **Omit V2-only creation fields.** Do not pass `allocatedStorage`, `dbStorageType`, `deploymentType`, `username`, `password`, `organization`, or `bucket` (the CLI forms are `--allocated-storage`, `--db-storage-type`, `--deployment-type`, `--username`, `--password`, `--organization`, and `--bucket`).
4. **Verify Core's current Marketplace and licensing prerequisites.** Check the Timestream for InfluxDB documentation and current `CreateDbCluster` API model before provisioning. Do not infer Core requirements from V2, Read Replica, or Enterprise. If an intended Core creation returns a Marketplace or Read Replica licensing error, recheck the current documentation, parameter-group identifier, and request fields rather than switching to a V2 operation.
5. **Use port 8181.** Port 8086 is for V2. Restrict inbound access to known CIDR ranges or security-group IDs; never use `0.0.0.0/0`.

Treat the current service API reference and Timestream for InfluxDB documentation as authoritative. If the installed AWS CLI or SDK model does not expose `create-db-cluster` or `InfluxDBV3Core`, update the CLI or SDK before provisioning. Do not work around a stale local model by falling back to `create-db-instance`, V2 fields, port 8086, or V2 licensing assumptions.

**InfluxDB 3 (cluster):**

```bash
aws timestream-influxdb create-db-cluster \
  --name my-v3-cluster \
  --db-instance-type <instance-type> \
  --db-parameter-group-identifier InfluxDBV3Core \
  --vpc-subnet-ids subnet-abc subnet-def \
  --vpc-security-group-ids sg-abc \
  --tags Key=created_by,Value=timestream-skill Key=generation_model,Value={your-model-id}

# Recommended arguments for production after verifying CreateDbCluster support:
#   --kms-key-id <kms-key-arn>
#   --log-delivery-configuration '{"s3Configuration":{"bucketName":"<logs-bucket>","enabled":true}}'
```

After `create-db-cluster` returns, use its cluster ID to poll `get-db-cluster` until the status is `AVAILABLE` or a terminal failure. Do not report creation complete or ask the user to take over polling while the cluster remains `CREATING`. When creation requested a customer-managed KMS key, also require the returned `kmsKeyId` ARN to exactly match the requested key ARN before reporting success. Treat an absent `kmsKeyId` during `CREATING` as unverified and check it again at `AVAILABLE`; a missing or different value at `AVAILABLE` is a failed verification.

After creation, follow [AWS CloudTrail integration](monitoring-operations.md#aws-cloudtrail-integration). Verify event coverage in the Timestream for InfluxDB CloudTrail documentation, then confirm that a trail records the documented management events with the required retention, encryption, and log-file validation controls.

For production clusters, configure log delivery when the selected engine variant supports it and apply the documented bucket-policy and SSE-KMS controls in [Log Delivery to S3](#log-delivery-to-s3). Omit `--log-delivery-configuration` only for dev/test workloads or when the current API model and documentation explicitly show that the selected engine variant does not support it.

Before selecting `<instance-type>`, check the [Timestream for InfluxDB DB instance classes documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/timestream-for-influxdb.html); supported classes can change and should not be inferred from examples.

Encryption at rest is required for production workloads. Verify the service-applied encryption option and `kmsKeyId` support in the Create API. Use `--kms-key-id` when customer-controlled policy, rotation, revocation, or auditing is required. Omit it only when the current documentation confirms AWS-owned default encryption and that option satisfies the workload's requirements, generally for dev/test. Load [encryption guidance](encryption.md) before choosing between the documented encryption options.

**Default parameter group identifiers:** List the available groups and verify the documentation or API model before selecting an identifier:

```bash
aws timestream-influxdb list-db-parameter-groups --region <region>
```

Use the exact default identifier listed for the selected engine variant. Create a custom group only when you need to override defaults.

### 3. Retrieve Token

**V2:** Token is stored in Secrets Manager at the ARN returned in `influxAuthParametersSecretArn`:

```bash
aws secretsmanager get-secret-value \
  --secret-id <influxAuthParametersSecretArn> \
  --query SecretString --output text
```

After retrieving the initial credentials, create an all-access operator token via the InfluxDB UI or cookie-based API auth (see V2 Onboarding below).

**V3:** Inspect the `GetDbCluster` output or API model for the token-secret ARN field. When the response includes `influxAuthParametersSecretArn`, use the ARN it returns; do not derive a secret identifier from a naming convention:

```bash
V3_TOKEN_SECRET_ARN="$(
  aws timestream-influxdb get-db-cluster \
    --db-cluster-id <cluster-id> \
    --query influxAuthParametersSecretArn \
    --output text
)"
aws secretsmanager get-secret-value \
  --secret-id "$V3_TOKEN_SECRET_ARN" \
  --query SecretString --output text
```

Before modifying or rotating the secret, verify its ownership and rotation behavior in the Timestream for InfluxDB documentation. Do not assume that changing its `SecretString` changes the cluster token.

### 4. Connect

**Security group configuration for publicly accessible instances:**

When creating an instance or cluster with `--publicly-accessible`, the endpoint is exposed over the public internet. Public access is a supported opt-in feature at creation time — by default, instances are private (VPC-only). For publicly accessible deployments, the default security group blocks all inbound traffic. You must add an inbound rule for the InfluxDB port:

```bash
# V2 (port 8086)
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp --port 8086 \
  --cidr <your-ip>/32   # or another trusted client CIDR; never use 0.0.0.0/0

# V3 (port 8181)
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp --port 8181 \
  --cidr <your-ip>/32
```

Restrict the CIDR to the smallest set of IPs that need access. Never use `0.0.0.0/0`.

**For private (VPC-only) deployments:** Clients must be in the same VPC or reach the instance via VPN, Direct Connect, or Transit Gateway. Security group rules should allow inbound from the VPC CIDR or specific private subnets.

**InfluxDB 2:** Endpoint on port 8086. Use the InfluxDB 2.x API with org/bucket/token. Keep the scoped token in Secrets Manager and supply it through the CLI's supported environment variable instead of saving it in an unencrypted local config:

```bash
export INFLUX_TOKEN="$(
  aws secretsmanager get-secret-value \
    --secret-id "<v2-application-token-secret-id>" \
    --query SecretString --output text |
  jq -er '.token'
)"
INFLUX_HOST="https://<endpoint>:8086" INFLUX_ORG="<org>" influx bucket list
unset INFLUX_TOKEN
```

**InfluxDB 3:** Endpoint on port 8181. Use SQL or InfluxQL via the InfluxDB 3.x API.

```bash
# Set V3_TOKEN_SECRET_ARN from GetDbCluster as shown in Retrieve Token.
V3_TOKEN="$(
  aws secretsmanager get-secret-value \
    --secret-id "$V3_TOKEN_SECRET_ARN" \
    --query SecretString --output text |
  jq -er '.token'
)"

# Write via line protocol
printf 'Authorization: Bearer %s\n' "$V3_TOKEN" |
curl -X POST "https://<endpoint>:8181/api/v3/write_lp?db=<database>" \
  -H @- \
  -H "Content-Type: text/plain" \
  -d "measurement,tag=value field=1.0"

# Query via SQL
printf 'Authorization: Bearer %s\n' "$V3_TOKEN" |
curl -X POST "https://<endpoint>:8181/api/v3/query_sql" \
  -H @- \
  -H "Content-Type: application/json" \
  -d '{"db":"<database>","q":"SELECT * FROM measurement LIMIT 10"}'

unset V3_TOKEN V3_TOKEN_SECRET_ARN
```

### 5. Post-Setup

- Configure maintenance window
- Set up CloudWatch alarms → route to `monitoring`
- Design schema → route to `schema-design`

## Private Access via SSM Bastion

For V3 clusters in private subnets without direct connectivity:

```bash
aws ssm start-session --target <bastion-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<CLUSTER_ENDPOINT>"],"portNumber":["8181"],"localPortNumber":["8181"]}'
```

Add `127.0.0.1 <CLUSTER_ENDPOINT>` to `/etc/hosts` so TLS certificate validation succeeds against the forwarded connection.

## Log Delivery to S3

Before configuring log delivery, verify its availability, delivery cadence, bucket account and Region constraints, KMS key constraints, service principal, object prefix, and source-ARN formats in the Timestream for InfluxDB documentation and the applicable create or update API reference. Treat those sources as authoritative; adapt or omit the following template when they differ.

> **SSE-KMS note:** Use only the KMS key ownership and account arrangements that the log-delivery documentation supports. Do not assume that a cross-account key works.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "timestream-influxdb.amazonaws.com"},
    "Action": "s3:PutObject",
    "Resource": "arn:aws:s3:::BUCKET_NAME/InfluxLogs/*",
    "Condition": {
      "StringEquals": {
        "aws:SourceAccount": "YOUR_ACCOUNT_ID"
      },
      "ArnLike": {
        "aws:SourceArn": [
          "arn:aws:timestream-influxdb:<REGION>:<ACCOUNT_ID>:db-instance/<INSTANCE_ID>",
          "arn:aws:timestream-influxdb:<REGION>:<ACCOUNT_ID>:db-cluster/<CLUSTER_ID>"
        ]
      }
    }
  }]
}
```

When the log-delivery documentation prescribes `aws:SourceArn`, add it to prevent confused deputy attacks and scope it to the exact source resource. Apply this template only to a customer-managed log bucket, and verify data-bucket ownership before stating whether the customer can configure its bucket policy.

Enable via create or update:

```bash
--log-delivery-configuration '{"s3Configuration":{"bucketName":"BUCKET","enabled":true}}'
```

## Reboot Commands

Before targeting specific nodes, inspect the current [`RebootDbCluster` request model](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_RebootDbCluster.html) and Timestream for InfluxDB documentation to verify the maximum number of `instanceIds` and any other request constraints. Do not assume a fixed limit.

```bash
# V2 instance
aws timestream-influxdb reboot-db-instance --identifier <instance-id>

# V3 cluster (all nodes)
aws timestream-influxdb reboot-db-cluster --db-cluster-id <cluster-id>

# V3 cluster (specific nodes)
aws timestream-influxdb reboot-db-cluster --db-cluster-id <cluster-id> \
  --instance-ids <id1> <id2>
```

## Determine Updatable Fields

For a V2 instance, inspect the [`UpdateDbInstance` request parameters](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_UpdateDbInstance.html) or the installed CLI or SDK model. For a cluster, inspect the [`UpdateDbCluster` request parameters](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_UpdateDbCluster.html) or installed model. Use only fields exposed by the selected operation, and verify documented restart, replacement, transition, and value constraints before proposing an update. Do not infer updatability from a Create operation or a cached field list. For `kmsKeyId`, follow the API verification and migration guidance in [encryption guidance](encryption.md).

## V2 Onboarding: Cookie Auth for Operator Token

After initial provisioning, the credentials in Secrets Manager give you UI access but not a full API operator token. To create one:

1. Sign in to the InfluxDB UI at `https://<endpoint>:8086` with the username/password from Secrets Manager
2. Navigate to **Load Data → API Tokens → Generate API Token → All Access API Token**
3. Copy the generated operator token directly into a new AWS Secrets Manager secret. Do not persist it in local files, shell profiles, logs, or source control; clear any clipboard copy after storage.
4. Create scoped tokens for application use, store each one in AWS Secrets Manager immediately, and avoid using the all-access operator token in production applications.

## Marketplace Activation and IAM Prerequisites

Before provisioning, verify the Marketplace subscription and activation requirements for the selected engine variant in the [Timestream for InfluxDB documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/timestream-for-influxdb.html) and the [`CreateDbCluster` API reference](https://docs.aws.amazon.com/ts-influxdb/latest/ts-influxdb-api/API_CreateDbCluster.html). Do not reuse licensing prerequisites from another engine variant.

When the documentation requires first-time Marketplace activation through the console, attach `AmazonTimestreamInfluxDBFullAccess` and `AmazonTimestreamConsoleFullAccess` only to the principal performing that activation. Remove both managed policies immediately after activation succeeds, within the same administrative session whenever possible, and replace them with the scoped custom policy below before production or operational use. Leaving either FullAccess policy attached to a production identity is a significant over-privilege risk. Configure an AWS Config custom rule or equivalent periodic control to detect either policy remaining attached after activation, and use IAM Access Analyzer unused-access findings to further reduce the replacement policy.

Example scoped policy for day-to-day operations (read plus the operational write actions this guide uses — update, reboot, tag):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListResources",
      "Effect": "Allow",
      "Action": [
        "timestream-influxdb:ListDbInstances",
        "timestream-influxdb:ListDbClusters"
      ],
      "Resource": "*"
    },
    {
      "Sid": "OperateOnSelectedResources",
      "Effect": "Allow",
      "Action": [
        "timestream-influxdb:GetDbInstance",
        "timestream-influxdb:GetDbCluster",
        "timestream-influxdb:ListTagsForResource",
        "timestream-influxdb:UpdateDbInstance",
        "timestream-influxdb:UpdateDbCluster",
        "timestream-influxdb:RebootDbInstance",
        "timestream-influxdb:RebootDbCluster",
        "timestream-influxdb:TagResource"
      ],
      "Resource": [
        "arn:aws:timestream-influxdb:<region>:<account-id>:db-instance/<instance-id>",
        "arn:aws:timestream-influxdb:<region>:<account-id>:db-cluster/<cluster-id>"
      ]
    }
  ]
}
```

Retain only the actions and resource type required by the operator. Replace each identifier with an exact resource ID; do not broaden it to `*`. Verify action-level resource support in the Service Authorization Reference, and use `Resource: "*"` only for actions that do not support resource-level permissions.

## Compare Engine Variants

Before comparing engine variants, retrieve the [Timestream for InfluxDB documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/timestream-for-influxdb.html) and inspect the applicable Create, Get, and Update API models for each candidate. Verify each variant's query languages, authentication flow, data model, endpoint, resource operation, deployment and storage model, scaling behavior, Processing Engine support, and Region-specific constraints. Use only capabilities confirmed by those sources for the user's Region and requested operation; do not infer one variant's behavior from another variant or from examples in this guide.

## Instance Types

Before recommending an instance class, retrieve the [Timestream for InfluxDB DB instance classes documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/timestream-for-influxdb.html) and inspect the Create API model for the selected engine variant and Region. Use only instance classes and hardware specifications those sources identify as supported. Do not infer availability, vCPU, memory, or workload fit from examples or a cached class list.
