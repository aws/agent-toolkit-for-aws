# Getting Started & Setup

## When to Activate

User wants to create a new Timestream for InfluxDB instance or cluster, connect to an existing one, choose between engine versions, or configure authentication.

## Workflow

### 1. Determine Engine Version

Ask the user one question: "Are you starting a new project or working with an existing InfluxDB deployment?"

- **New project** → Recommend InfluxDB 3 (SQL support, Processing Engine, better high-cardinality handling)
- **Existing V2 deployment** → Stay on V2 unless they want to migrate (route to `migration`)
- **Need read scaling** → InfluxDB 2 Read Replica Clusters (requires Marketplace subscription)

### 2. Provision

**InfluxDB 2 (standalone instance):**

```bash
aws timestream-influxdb create-db-instance \
  --name my-influxdb \
  --db-instance-type db.influx.large \
  --db-storage-type InfluxIOIncludedT1 \
  --allocated-storage 400 \
  --deployment-type SINGLE_AZ \
  --vpc-subnet-ids subnet-abc \
  --vpc-security-group-ids sg-abc \
  --db-parameter-group-identifier <param-group-id> \
  --username admin --password <alphanumeric-only> \
  --organization my-org --bucket my-bucket
```

> **Security best practice — InfluxDB V2 credentials:**
>
> - Generate the initial admin password as a strong random value rather than choosing one by hand, e.g. `aws secretsmanager get-random-password --exclude-punctuation --password-length 32 --query RandomPassword --output text` (InfluxDB requires an alphanumeric password, hence `--exclude-punctuation`).
> - Rotate the initial admin password immediately after first login; it is set during instance creation and should not be used by applications.
> - Create scoped API tokens for each application or service — never share the operator token.
> - The engine does not support automatic token expiration or rotation. Token rotation is the customer's responsibility. There is no automatic synchronization between AWS Secrets Manager and the engine's token management layer.
> - For InfluxDB V3 or new deployments, the preferred approach is Secrets Manager-based Bearer tokens provisioned automatically by the service.

**InfluxDB 2 Read Replica Cluster:**

```bash
aws timestream-influxdb create-db-cluster \
  --name my-rr-cluster \
  --db-instance-type db.influx.large \
  --db-storage-type InfluxIOIncludedT1 \
  --allocated-storage 400 \
  --deployment-type MULTI_NODE_READ_REPLICAS \
  --vpc-subnet-ids subnet-az1 subnet-az2 \
  --vpc-security-group-ids sg-abc \
  --db-parameter-group-identifier <param-group-id> \
  --username admin --password <alphanumeric-only> \
  --organization my-org --bucket my-bucket
```

**InfluxDB 3 (cluster):**

```bash
aws timestream-influxdb create-db-cluster \
  --name my-v3-cluster \
  --db-instance-type db.influx.large \
  --db-parameter-group-identifier InfluxDBV3Core \
  --vpc-subnet-ids subnet-abc subnet-def \
  --vpc-security-group-ids sg-abc
```

> ⚠️ **CRITICAL V3 WARNING:** You **MUST NOT** pass `--username`, `--password`, `--organization`, `--bucket`, or `--deployment-type` when creating V3 clusters. These parameters switch the cluster into a non-V3 initialization mode. V3 clusters use `Bearer` token auth provisioned automatically via Secrets Manager.

**Literal parameter group identifiers:** You can use `InfluxDBV3Core` or `InfluxDBV3Enterprise` as literal identifiers without creating a custom parameter group first. Create a custom group only when you need to override defaults.

### 3. Retrieve Token

**V2:** Token is stored in Secrets Manager at the ARN returned in `influxAuthParametersSecretArn`:

```bash
aws secretsmanager get-secret-value \
  --secret-id <influxAuthParametersSecretArn> \
  --query SecretString --output text
```

After retrieving the initial credentials, create an all-access operator token via the InfluxDB UI or cookie-based API auth (see V2 Onboarding below).

**V3:** Token secret follows the naming convention `READONLY-InfluxDB-auth-parameters-<CLUSTER_ID>`:

```bash
aws secretsmanager get-secret-value \
  --secret-id "READONLY-InfluxDB-auth-parameters-<CLUSTER_ID>" \
  --query SecretString --output text
```

The `READONLY-` prefix means the secret is service-managed — modifying it does not change the cluster's actual token.

### 4. Connect

**Security group configuration for publicly accessible instances:**

When creating an instance or cluster with `--publicly-accessible`, the endpoint is exposed over the public internet. Public access is a supported opt-in feature at creation time — by default, instances are private (VPC-only). For publicly accessible deployments, the default security group blocks all inbound traffic. You must add an inbound rule for the InfluxDB port:

```bash
# V2 (port 8086)
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp --port 8086 \
  --cidr <your-ip>/32   # or a CIDR range — avoid 0.0.0.0/0 in production

# V3 (port 8181)
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp --port 8181 \
  --cidr <your-ip>/32
```

Restrict the CIDR to the smallest set of IPs that need access. Never use `0.0.0.0/0` for production workloads.

**For private (VPC-only) deployments:** Clients must be in the same VPC or reach the instance via VPN, Direct Connect, or Transit Gateway. Security group rules should allow inbound from the VPC CIDR or specific private subnets.

**InfluxDB 2:** Endpoint on port 8086. Use the InfluxDB 2.x API with org/bucket/token.

```
influx config create --config-name my-config \
  --host-url https://<endpoint>:8086 \
  --org <org> --token <token>
```

**InfluxDB 3:** Endpoint on port 8181. Use SQL or InfluxQL via the InfluxDB 3.x API.

```bash
# Write via line protocol
curl -X POST "https://<endpoint>:8181/api/v3/write_lp?db=<database>" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: text/plain" \
  -d "measurement,tag=value field=1.0"

# Query via SQL
curl -X POST "https://<endpoint>:8181/api/v3/query_sql" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"db":"<database>","q":"SELECT * FROM measurement LIMIT 10"}'
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

Logs are delivered hourly to S3. The bucket **must** be in the same account and region, with this policy:

> **SSE-KMS note:** SSE-KMS encryption on the log delivery bucket is supported, but the KMS key **must** be owned by the same AWS account as the InfluxDB instance. A cross-account KMS key will break log delivery silently.

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
        "aws:SourceArn": "arn:aws:timestream-influxdb:<REGION>:<ACCOUNT_ID>:db-instance/*"
      }
    }
  }]
}
```

Add an `aws:SourceArn` condition to your S3 bucket policy to prevent confused deputy attacks — this ensures requests to the bucket can only originate from your Timestream for InfluxDB instance, not from other AWS services that share the same service principal. This bucket policy applies to your logs bucket (the S3 bucket you configure to receive InfluxDB service logs). The InfluxDB 3 data bucket is provisioned and managed by the service — you do not configure a bucket policy for it directly.

Enable via create or update:

```bash
--log-delivery-configuration '{"s3Configuration":{"bucketName":"BUCKET","enabled":true}}'
```

## Reboot Commands

```bash
# V2 instance
aws timestream-influxdb reboot-db-instance --identifier <instance-id>

# V3 cluster (all nodes)
aws timestream-influxdb reboot-db-cluster --db-cluster-id <cluster-id>

# V3 cluster (specific nodes, up to 3)
aws timestream-influxdb reboot-db-cluster --db-cluster-id <cluster-id> \
  --instance-ids <id1> <id2>
```

## Updatable Fields

### InfluxDB 2 (`update-db-instance`)

- `--db-instance-type` — triggers reboot
- `--db-parameter-group-identifier` — triggers reboot
- `--db-storage-type` — triggers reboot
- `--allocated-storage` — increase only
- `--deployment-type` — SINGLE_AZ ↔ WITH_MULTIAZ_STANDBY
- `--port`
- `--log-delivery-configuration`
- `--maintenance-schedule`

### InfluxDB 3 (`update-db-cluster`)

- `--db-instance-type` — triggers reboot
- `--db-parameter-group-identifier` — triggers reboot
- `--port`
- `--failover-mode`
- `--log-delivery-configuration`
- `--maintenance-schedule`

**NOT updatable on V3:** `--allocated-storage` (V3 uses S3), `--deployment-type` (V3 uses param groups for topology), `--db-storage-type`.

## V2 Onboarding: Cookie Auth for Operator Token

After initial provisioning, the credentials in Secrets Manager give you UI access but not a full API operator token. To create one:

1. Sign in to the InfluxDB UI at `https://<endpoint>:8086` with the username/password from Secrets Manager
2. Navigate to **Load Data → API Tokens → Generate API Token → All Access API Token**
3. Copy the generated token — this is your operator token for all API operations
4. Create scoped tokens (read/write per bucket) for application use — avoid using the all-access token in production applications

## Prerequisites for Read Replicas and InfluxDB 3 Enterprise

Both require:

1. **AWS Marketplace subscription** for InfluxData licensed features — subscribe before provisioning
2. **IAM policies** — attach these managed policies to your IAM role/user:
   - `AmazonTimestreamInfluxDBFullAccess`
   - `AmazonTimestreamConsoleFullAccess`

> **Note:** `AmazonTimestreamInfluxDBFullAccess` is suitable for initial setup and experimentation. For production workloads, replace it with a scoped custom IAM policy that grants only the specific actions your application requires. Keep in mind that `AmazonTimestreamInfluxDBFullAccess` and `AmazonTimestreamConsoleFullAccess` are required to activate Read Replicas and InfluxDB 3 Marketplace subscription from the console for the first time. **After initial setup and first-time activation are complete, replace both `AmazonTimestreamInfluxDBFullAccess` and `AmazonTimestreamConsoleFullAccess` with the scoped custom policy below for all production and operational use.**

Example scoped policy for day-to-day operations (read plus the operational write actions this guide uses — update, reboot, tag):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "timestream-influxdb:GetDbInstance",
      "timestream-influxdb:GetDbCluster",
      "timestream-influxdb:ListDbInstances",
      "timestream-influxdb:ListDbClusters",
      "timestream-influxdb:ListTagsForResource",
      "timestream-influxdb:UpdateDbInstance",
      "timestream-influxdb:UpdateDbCluster",
      "timestream-influxdb:RebootDbInstance",
      "timestream-influxdb:RebootDbCluster",
      "timestream-influxdb:TagResource"
    ],
    "Resource": [
      "arn:aws:timestream-influxdb:<region>:<account-id>:db-instance/*",
      "arn:aws:timestream-influxdb:<region>:<account-id>:db-cluster/*"
    ]
  }]
}
```

## Key Differences: V2 vs V3

| Aspect | InfluxDB 2 | InfluxDB 3 |
|--------|-----------|-----------|
| Query language | Flux | SQL, InfluxQL |
| Data model | Orgs → Buckets → Measurements | Databases → Tables |
| Storage | Local disk (TSM engine), allocated at creation | S3-backed (Apache Parquet), no allocated storage parameter |
| Cardinality | Hard limits, performance degrades | Handles high cardinality natively |
| Processing Engine | Not available | Python plugins with triggers |
| Port | 8086 | 8181 |
| AWS resource | `create-db-instance` | `create-db-cluster` |
| Deployment types | SINGLE_AZ, WITH_MULTIAZ_STANDBY | Determined by failover-mode (no deployment-type param) |
| Password | Required at creation | N/A — must not be provided (Bearer token via Secrets Manager) |
| Storage scaling | Yes (update-db-instance) | N/A (S3-backed) |

## Instance Types

| Type | vCPU | Memory | Use Case |
|------|------|--------|----------|
| db.influx.medium | 1 | 8 GiB | Dev/test |
| db.influx.large | 2 | 16 GiB | Small production |
| db.influx.xlarge | 4 | 32 GiB | Medium production |
| db.influx.2xlarge | 8 | 64 GiB | Large production |
| db.influx.4xlarge | 16 | 128 GiB | High-throughput |
| db.influx.8xlarge | 32 | 256 GiB | Enterprise |
| db.influx.12xlarge | 48 | 384 GiB | Enterprise |
| db.influx.16xlarge | 64 | 512 GiB | Enterprise |
| db.influx.24xlarge | 96 | 768 GiB | Enterprise (largest publicly available) |
