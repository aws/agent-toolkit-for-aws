# Secondary costs

Each row is a charge the named service brings with it.

## Contents

- Core services: EC2, EBS, Lambda, ECS and Fargate, EKS, S3, EFS, RDS and
  Aurora, DynamoDB, Redshift, VPC, Route 53, CloudFront, SageMaker, Bedrock,
  CloudTrail, CloudWatch, API Gateway, Elastic Load Balancing, SQS, SNS
- Other services: the checklist for a service with no entry
- Lines that come with a service: lines inside a kept service that are easy to miss

- **Service code** is where the charge bills. Several bill under another service's
  code: EBS and NAT gateways under `AmazonEC2`, public IPv4 addresses and VPC
  endpoints under `AmazonVPC`, and data transfer under `AWSDataTransfer`.
- **Data transfer** comes from `AWSDataTransfer` only. `AmazonEC2` also lists
  between-AZ and other-region lines; leave those out so no transfer is counted
  twice. In `AWSDataTransfer`, internet traffic out is `DataTransfer-Out-Bytes`,
  traffic between AZs is `DataTransfer-Regional-Bytes` (keep its
  `<region>-DataTransfer-xAZ-In-Bytes` and `-xAZ-Out-Bytes` lines with it; they
  price at $0), traffic in from CloudFront is `<region>-CloudFront-In-Bytes`
  (also $0, kept whenever CloudFront is in front), and traffic to another
  region is `<from>-<to>-AWS-Out-Bytes` (`USE1-USW2-AWS-Out-Bytes` from us-east-1
  to us-west-2). These are the us-east-1 names; in other regions the first two
  carry the region's prefix, such as `EU-DataTransfer-Out-Bytes` for eu-west-1.
  `USE1-AWS-Out-Bytes` has no destination
  region; the price list calls it inter-region peering, so it is not the line for
  traffic to a named region.
  CloudFront is the exception: it prices its own data transfer out.
- **Origin** `required` means the service cannot run without it, so it is always
  included. `optional` means it depends on the setup: it is included when the
  description says its "Applies when" condition holds, and is otherwise listed as
  not included unless the user says so.
- Each entry already lists what its companions bring (ECS lists EBS for its EC2
  instances), so take a service's companions from its own entry only and never
  follow a companion into its entry. That way the list cannot loop.

## Core services

### Amazon EC2 (`AmazonEC2`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| EBS volumes | `AmazonEC2` | required | always (root volume) |
| EBS snapshots | `AmazonEC2` | optional | snapshots or backups are taken |
| KMS | `awskms` | optional | volumes are encrypted |
| Data transfer | `AWSDataTransfer` | optional | serves the internet, or sends data to another AZ or region |
| NAT gateway (hours, data processed and its public IPv4 address) | `AmazonEC2`, plus `AmazonVPC` for the address | optional | in a private subnet with outbound internet access |
| Public IPv4 address | `AmazonVPC` | optional | has a public or Elastic IP |
| CloudWatch | `AmazonCloudWatch` | optional | alarms, logs, custom metrics or detailed monitoring |
| Secrets Manager (secrets and API requests) | `AWSSecretsManager` | optional | the application reads credentials, API keys or database passwords at run time |

### Amazon EBS (`AmazonEC2`)

EBS has no service code of its own; its lines are the `EBS:` lines in `AmazonEC2`.

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Snapshots | `AmazonEC2` | optional | snapshots or backups are taken |
| KMS | `awskms` | optional | volumes are encrypted |

### AWS Lambda (`AWSLambda`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| CloudWatch Logs | `AmazonCloudWatch` | required | always (functions write logs by default; Lambda logs bill as CloudWatch vended logs, so keep the vended log lines, not standard log ingestion) |
| Data transfer | `AWSDataTransfer` | optional | sends data to the internet or another region |
| NAT gateway (hours, data processed and its public IPv4 address) | `AmazonEC2`, plus `AmazonVPC` for the address | optional | attached to a VPC and calls the internet |
| VPC endpoints | `AmazonVPC` | optional | attached to a VPC and reaches AWS services through interface endpoints |
| CloudTrail data events | `AWSCloudTrail`, plus `AmazonS3` when a trail delivers them | optional | data events are logged for the function's invocations (off by default) |
| Secrets Manager (secrets and API requests) | `AWSSecretsManager` | optional | the application reads credentials, API keys or database passwords at run time |

### Amazon ECS and AWS Fargate (`AmazonECS`)

Fargate compute bills in `AmazonECS`.

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| EC2 instances | `AmazonEC2` | optional | EC2 launch type |
| EBS volumes | `AmazonEC2` | optional | EC2 launch type (each instance's root volume) |
| KMS | `awskms` | optional | the container instances' volumes are encrypted, or Fargate ephemeral storage uses a customer managed key |
| CloudWatch Logs | `AmazonCloudWatch` | optional | tasks use the `awslogs` log driver |
| ECR | `AmazonECR` | optional | images are pulled from ECR |
| Data transfer | `AWSDataTransfer` | optional | serves the internet, or sends data to another AZ or region |
| NAT gateway (hours, data processed and its public IPv4 address) | `AmazonEC2`, plus `AmazonVPC` for the address | optional | tasks in a private subnet that reach the internet, or pull images from ECR without VPC endpoints |
| VPC endpoints | `AmazonVPC` | optional | tasks reach ECR or other AWS services through interface endpoints |
| Load balancer (and its public IPv4 addresses when internet-facing) | `AWSELB`, plus `AmazonVPC` for the addresses | optional | services use a load balancer |
| Public IPv4 address | `AmazonVPC` | optional | tasks or container instances have public IPs |
| Secrets Manager (secrets and API requests) | `AWSSecretsManager` | optional | the application reads credentials, API keys or database passwords at run time |

### Amazon EKS (`AmazonEKS`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| EC2 instances | `AmazonEC2` | optional | nodes run on EC2 (node groups or Auto Mode) |
| EBS volumes | `AmazonEC2` | optional | nodes run on EC2 (each node's root volume) |
| KMS | `awskms` | optional | nodes run on EC2 and their volumes are encrypted |
| ECR | `AmazonECR` | optional | images are pulled from ECR |
| Data transfer | `AWSDataTransfer` | optional | serves the internet, or sends data to another AZ or region |
| NAT gateway (hours, data processed and its public IPv4 address) | `AmazonEC2`, plus `AmazonVPC` for the address | optional | nodes in a private subnet that reach the internet, or pull images from ECR without VPC endpoints |
| VPC endpoints | `AmazonVPC` | optional | nodes reach ECR or other AWS services through interface endpoints |
| Public IPv4 address | `AmazonVPC` | optional | nodes have public IPs |
| Load balancer (and its public IPv4 addresses when internet-facing) | `AWSELB`, plus `AmazonVPC` for the addresses | optional | Kubernetes services or ingresses use a load balancer |
| CloudWatch | `AmazonCloudWatch` | optional | control plane logging or Container Insights |
| Secrets Manager (secrets and API requests) | `AWSSecretsManager` | optional | the application reads credentials, API keys or database passwords at run time |

### Amazon S3 (`AmazonS3`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Data transfer | `AWSDataTransfer` | optional | objects are read from the internet or another region |
| KMS | `awskms` | optional | SSE-KMS (the default SSE-S3 is free) |
| CloudWatch | `AmazonCloudWatch` | optional | request metrics or alarms |
| CloudTrail data events | `AWSCloudTrail` | optional | data events are logged for the bucket's objects (off by default) |

### Amazon EFS (`AmazonEFS`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Data transfer | `AWSDataTransfer` | optional | mounted from another AZ or region |
| KMS | `awskms` | optional | encrypted at rest (the console default) |
| Backups | `AWSBackup` | optional | backups are taken with AWS Backup (on by default for file systems created in the console) |
| CloudWatch | `AmazonCloudWatch` | optional | alarms |

### Amazon RDS and Aurora (`AmazonRDS`)

Storage, I/O and backups bill in `AmazonRDS`, not EBS.

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Data transfer | `AWSDataTransfer` | optional | cross-region read replicas or snapshot copies, or clients in another AZ or on the internet |
| KMS | `awskms` | optional | storage is encrypted |
| Secrets Manager | `AWSSecretsManager` | optional | the master password is managed in Secrets Manager |
| Public IPv4 address | `AmazonVPC` | optional | publicly accessible |
| CloudWatch | `AmazonCloudWatch` | optional | Database Insights in Advanced mode or with more than 7 days of retention, Enhanced Monitoring, log exports or alarms |

### Amazon DynamoDB (`AmazonDynamoDB`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Data transfer | `AWSDataTransfer` | optional | global tables, or reads from the internet or another region |
| KMS | `awskms` | optional | an AWS managed or customer managed key (the default AWS owned key is free) |
| CloudWatch | `AmazonCloudWatch` | optional | alarms |

### Amazon Redshift (`AmazonRedshift`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| S3 | `AmazonS3` | optional | COPY or UNLOAD, or Spectrum queries over S3 |
| Data transfer | `AWSDataTransfer` | optional | cross-region snapshot copies, or results sent to the internet |
| KMS | `awskms` | optional | encrypted with a KMS key |
| CloudWatch | `AmazonCloudWatch` | optional | alarms or audit logs to CloudWatch |

### Amazon VPC (`AmazonVPC`)

Public IPv4 addresses, VPC endpoints, Transit Gateway and VPN bill in `AmazonVPC` itself.

An interface VPC endpoint bills hours for each endpoint in each AZ, plus the
data it processes. Whenever the design reaches AWS services through interface
endpoints, keep the endpoint hour lines even if the user doesn't know how many
endpoints there are. Ask for the count; if the user can't say, assume one
endpoint per AWS service the design reaches through them, in each AZ the
workload runs in, and say so in the line's assumption.

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| NAT gateway (hours, data processed and its public IPv4 address) | `AmazonEC2`, plus `AmazonVPC` for the address | optional | private subnets with outbound internet access |
| Data transfer | `AWSDataTransfer` | optional | traffic to the internet, or to another AZ or region |
| Flow logs | `AmazonCloudWatch`, plus `AmazonS3` or `AmazonKinesisFirehose` when delivered there | optional | flow logs are on (delivery bills as CloudWatch vended logs) |

### Amazon Route 53 (`AmazonRoute53`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| KMS | `awskms` | optional | DNSSEC signing |
| CloudWatch | `AmazonCloudWatch` | optional | query logging or health check alarms |

### Amazon CloudFront (`AmazonCloudFront`)

CloudFront's own price list includes its data transfer out, Lambda@Edge and
Functions, so it gets no companion for them. Lambda@Edge is also listed under
`AWSLambda` at the same price; list it only under `AmazonCloudFront`.

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Origin | `AmazonS3`, `AmazonEC2` or `AWSELB` | required | always, unless the description already names the origin (S3 if it names none) |
| EBS volumes | `AmazonEC2` | required | the origin is EC2 instances (root volume) |
| Standard logs | `AmazonCloudWatch`, plus `AmazonS3` or `AmazonKinesisFirehose` when delivered there | optional | logging is on (delivery bills as CloudWatch vended logs; legacy logging to S3 bills S3 only) |
| Real-time logs | `AmazonKinesis` | optional | real-time logs are on |
| WAF | `awswaf` | optional | a web ACL is attached |
| Route 53 (hosted zone and DNS queries) | `AmazonRoute53` | optional | a custom domain name (assume one unless the user says it uses the default domain) |
| ACM certificate | `ACM` | optional | HTTPS on a custom domain (a public certificate prices at $0; keep the line) |

### Amazon SageMaker (`AmazonSageMaker`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| S3 | `AmazonS3` | required | always (training data and model artifacts) |
| CloudWatch Logs | `AmazonCloudWatch` | required | always (jobs and endpoints write logs) |
| ECR | `AmazonECR` | optional | custom containers |
| KMS | `awskms` | optional | data or volumes are encrypted with a KMS key |
| Data transfer | `AWSDataTransfer` | optional | endpoints serve the internet or another region |
| NAT gateway (hours, data processed and its public IPv4 address) | `AmazonEC2`, plus `AmazonVPC` for the address | optional | runs in a private subnet with outbound internet access |

### Amazon Bedrock (`AmazonBedrock`)

Titan and Nova embeddings and guardrails bill in `AmazonBedrock` itself, on their
own lines. Cohere Embed bills in `AmazonBedrockFoundationModels`.

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Embedding model | `AmazonBedrock` (Titan, Nova) or `AmazonBedrockFoundationModels` (Cohere) | optional | a knowledge base is used (documents are embedded when ingested, and every query is embedded) |
| Vector store | `AmazonES` (OpenSearch Serverless), `AmazonS3` (S3 Vectors) or `AmazonRDS` (Aurora PostgreSQL) | optional | a knowledge base is used (the store the description names) |
| Documents | `AmazonS3` | optional | a knowledge base reads its documents from S3 |
| Guardrails | `AmazonBedrock` | optional | guardrails are applied |
| Invocation logs | `AmazonCloudWatch` or `AmazonS3` | optional | model invocation logging is on (it is off by default) |
| KMS | `awskms` | optional | a knowledge base or agent is encrypted with a customer managed key |

### AWS CloudTrail (`AWSCloudTrail`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| S3 | `AmazonS3` | required | a trail is used (trails deliver log files to a bucket; CloudTrail Lake does not) |
| KMS | `awskms` | optional | log files encrypted with SSE-KMS |
| CloudWatch Logs | `AmazonCloudWatch` | optional | the trail also sends events to CloudWatch Logs |
| Paid management events | `AWSCloudTrail` | optional | more than one trail logs the account's management events, such as its own trail and an organization trail (the first copy is free) |

### Amazon CloudWatch (`AmazonCloudWatch`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| S3 | `AmazonS3` | optional | logs are exported to S3 |
| Firehose | `AmazonKinesisFirehose` | optional | metric streams or log subscriptions to Firehose |

### Amazon API Gateway (`AmazonApiGateway`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Data transfer | `AWSDataTransfer` | optional | serves the internet (any public API) |
| CloudWatch Logs | `AmazonCloudWatch` | optional | access or execution logging is on |
| WAF | `awswaf` | optional | a web ACL is attached (REST APIs only) |
| Route 53 (hosted zone and DNS queries) | `AmazonRoute53` | optional | a custom domain name |
| ACM certificate | `ACM` | optional | a custom domain name (a public certificate prices at $0; keep the line) |

### Elastic Load Balancing (`AWSELB`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Public IPv4 address | `AmazonVPC` | optional | internet-facing |
| Data transfer | `AWSDataTransfer` | optional | serves the internet, or an NLB or Gateway Load Balancer has cross-zone load balancing on (free for an ALB) |
| Access logs | `AmazonS3` | optional | access logs are on |
| WAF | `awswaf` | optional | a web ACL is attached (Application Load Balancers only) |
| CloudWatch | `AmazonCloudWatch` | optional | alarms |
| Route 53 (hosted zone and DNS queries) | `AmazonRoute53` | optional | internet-facing (assume a custom domain name unless the user says otherwise) |
| ACM certificate | `ACM` | optional | an HTTPS or TLS listener (a public certificate prices at $0; keep the line) |

### Amazon SQS (`AWSQueueService`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| KMS | `awskms` | optional | SSE-KMS (the default SSE-SQS is free) |
| Data transfer | `AWSDataTransfer` | optional | consumers on the internet or in another region |
| CloudWatch | `AmazonCloudWatch` | optional | alarms |

### Amazon SNS (`AmazonSNS`)

| Companion | Service code | Origin | Applies when |
|---|---|---|---|
| Subscribers | `AWSQueueService`, `AWSLambda` or `AmazonKinesisFirehose` | optional | the topic delivers to them |
| KMS | `awskms` | optional | the topic is encrypted |
| Data transfer | `AWSDataTransfer` | optional | delivers to HTTP endpoints or another region |
| CloudWatch Logs | `AmazonCloudWatch` | optional | delivery status logging is on, or the topic delivers to a Lambda function (its logs) |

## Other services

For a service not listed above, work through these in order, and add only what
normal use of the service bills:

1. **Infrastructure it runs on:** data transfer (`AWSDataTransfer`), VPC networking
   (NAT gateways in `AmazonEC2`, each with a public IPv4 address; public IPv4
   addresses and endpoints in `AmazonVPC`) and block storage (EBS in `AmazonEC2`).
2. **Encryption:** KMS (`awskms`), only with an AWS managed or customer managed
   key. AWS owned keys are free.
3. **Services it needs to work:** Clean Rooms needs data in S3 and a Glue Data
   Catalog (`AWSGlue`); Athena reads tables from Glue and writes results to S3; EMR
   runs on EC2 and reads S3.
4. **Logs and monitoring:** CloudWatch (`AmazonCloudWatch`).

Mark a companion `required` only when the service cannot run without it, and
give every `optional` one an "Applies when" condition.

## Lines that come with a service

A kept service brings these lines of its own. Keep each one Step 5 lists when
its condition holds, even when it prices at $0.

| Service | Lines to keep | When |
|---|---|---|
| CloudWatch | `CW:MetricMonitorUsage`, `CW:AlarmMonitorUsage` (plus `CW:CompositeAlarmMonitorUsage` for composite alarms), `CW:Requests` and `CW:GMD-Metrics` | the design has custom metrics or alarms (dashboards and alarms read metrics through these APIs) |
| CloudWatch | `DashboardsUsageHour-Basic` for most dashboards and `DashboardsUsageHour` for dashboards above the metric count its Price List description names (each bills per dashboard per month, so the amount is the dashboard count, not hours). Put the count on the Basic line unless the user says dashboards are larger than that | the design has dashboards |
| CloudWatch | `CW:ContributorRulesManaged` and `CW:ContributorEventsManaged` for DynamoDB tables, `CW:ContributorInsightRules` and `CW:ContributorInsightEvents` for log groups (rules bill per rule per month, though one unit reads Rule-Hour, so the amount is the rule count; events are the events the rules match) | Contributor Insights is on |
| CloudWatch | `DataScanned-Bytes` (Logs Insights queries) | logs are kept and someone queries them (assume yes for application logs) |
| CloudWatch | `S3-Egress-Bytes` | logs are delivered or exported to S3 |
| DynamoDB | `TimedPITRStorage-ByteHrs` | point-in-time recovery is on |
| DynamoDB | `ReplWriteRequestUnits` (on-demand) or `ReplWriteCapacityUnit-Hrs` (provisioned) in every replica region, the table's own region included, in place of the table's `WriteRequestUnits` or `WriteCapacityUnit-Hrs`; storage and point-in-time recovery lines in every replica region; a `<from>-<to>-AWS-Out-Bytes` line for each replica region | the table is a global table |
| SNS | `Requests-Tier1` (publishes), and `DeliveryAttempts-<protocol>` for each subscriber type, such as `DeliveryAttempts-SQS` | always |
| SQS | `Requests-RBP`, and `Requests-FIFO-RBP` for FIFO queues | always |
| X-Ray | `XRay-TracesStored` and `XRay-TracesAccessed` | tracing is on |
| Lambda | `Lambda-GB-Second-ARM` and `Request-ARM` instead of the x86 lines | the functions run on arm64 (Graviton); use the x86 lines unless the user says arm64 |
