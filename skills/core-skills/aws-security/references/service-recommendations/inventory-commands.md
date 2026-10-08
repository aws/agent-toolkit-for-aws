# Pass 1 — Infrastructure Inventory

Read only the sections needed for the selected workflow. Reuse complete, scope-matched
observations; run global lists once, then relevant regional reads. Let the CLI paginate;
with MCP/API calls follow continuation tokens and respect describe-call batch limits.
This pagination rule applies only to authorized reads: account/member enumeration requires
an explicit request for detailed account-level information. Prefer available statistics or
counts; mark unrequested detail NOT ASSESSED. Projections do not authorize displaying
identifiers or raw responses; follow the parent disclosure rules.
Record account, region, completion and errors alongside observations. Partial results are
useful evidence, but cannot establish absence. Baseline rows use their stated conditions.

## Contents

- [Compute](#compute)
- [Containers](#containers)
- [Data](#data)
- [Network and edge](#network-and-edge)
- [Certificates](#certificates)
- [Foundational logging](#foundational-logging)
- [Organization context](#organization-context)
- [Recording the inventory](#recording-the-inventory)

## Compute

```bash
# EC2 instances (running and stopped — Inspector pauses scanning while an instance is stopped and
# resumes when it starts; its existing findings remain, so stopped instances stay in the inventory)
aws ec2 describe-instances \
  --filters 'Name=instance-state-name,Values=running,stopped' \
  --query 'Reservations[].Instances[].{Id:InstanceId,State:State.Name,Platform:PlatformDetails}' \
  --region <region>

# SSM-managed status — required for GuardDuty Runtime Monitoring agent management on EC2
# and for Inspector's automatic VM Scanner install. Instances absent here can still get
# Inspector coverage through a manual VM Scanner install or agentless scanning.
aws ssm describe-instance-information \
  --query 'InstanceInformationList[].{Id:InstanceId,Ping:PingStatus,Agent:AgentVersion}' \
  --region <region>

# EBS volumes — GuardDuty Malware Protection and Inspector agentless scanning
aws ec2 describe-volumes \
  --query 'Volumes[].{Id:VolumeId,Encrypted:Encrypted,State:State}' \
  --region <region>

# Lambda functions
aws lambda list-functions \
  --query 'Functions[].{Name:FunctionName,Runtime:Runtime}' \
  --region <region>

# AI workloads — discover the current GuardDuty AI Protection covered services and event types
# from GuardDuty documentation before selecting inventory reads. The commands below are
# candidate reads for service families shown in the latest documentation, not a closed coverage list; add or omit
# reads to match the current documented set. Provisioning lists and logging configuration cannot
# exclude on-demand use. Accept scoped user or telemetry confirmation; otherwise mark AI use and
# service eligibility UNKNOWN.
aws bedrock get-model-invocation-logging-configuration --region <region>
aws bedrock list-custom-models --region <region>
aws bedrock-agent list-agents --region <region>
aws bedrock-agentcore-control list-agent-runtimes --region <region>
aws sagemaker list-endpoints --region <region>
```

## Containers

```bash
# ECR repositories — Inspector ECR scanning
aws ecr describe-repositories \
  --query 'repositories[].{Name:repositoryName,ScanOnPush:imageScanningConfiguration.scanOnPush}' \
  --region <region>

# ECS clusters
aws ecs list-clusters --region <region>

# ECS launch type per service — Fargate vs EC2 changes the GuardDuty Runtime
# Monitoring path. Fargate needs a supported platform version (LATEST, or the current
# minimum from AWS documentation) for GuardDuty Runtime Monitoring.
aws ecs list-services --cluster <cluster-arn> --region <region>
aws ecs describe-services --cluster <cluster-arn> --services <service> \
  --query '{Services:services[].{Name:serviceName,LaunchType:launchType,Providers:capacityProviderStrategy,Platform:platformVersion},Failures:failures[].{Arn:arn,Reason:reason}}' \
  --region <region>

# Resolve providers reported by services/tasks; leave unknown backing compute unresolved
aws ecs describe-capacity-providers --capacity-providers <provider-name> \
  --query '{Providers:capacityProviders[].{Name:name,ASG:autoScalingGroupProvider.autoScalingGroupArn},Failures:failures[].{Arn:arn,Reason:reason}}' \
  --region <region>

# Running tasks include standalone tasks; an empty service list does not exclude them
aws ecs list-tasks --cluster <cluster-arn> --desired-status RUNNING --region <region>
aws ecs describe-tasks --cluster <cluster-arn> --tasks <task-arn> \
  --query '{Tasks:tasks[].{Arn:taskArn,LaunchType:launchType,Provider:capacityProviderName,Platform:platformVersion},Failures:failures[].{Arn:arn,Reason:reason}}' \
  --region <region>

# EKS clusters
aws eks list-clusters --region <region>

# EKS can mix compute types. Fargate workloads lack Runtime Monitoring support;
# empty profiles do not prove EC2. Nodegroups/computeConfig do not exhaust self-managed nodes.
aws eks list-fargate-profiles --cluster-name <cluster> --region <region>
aws eks list-nodegroups --cluster-name <cluster> --region <region>

# EKS audit logging and Auto Mode compute configuration
aws eks describe-cluster --name <cluster> \
  --query 'cluster.{Logging:logging.clusterLogging,Compute:computeConfig}' --region <region>
```

## Data

```bash
# S3 buckets — Macie, GuardDuty S3 Protection, S3 Malware Protection.
# s3api list-buckets is global; filter by region if assessing one region.
aws s3api list-buckets --query 'Buckets[].Name'
aws s3api get-bucket-location --bucket <name>

# RDS and Aurora — validate GuardDuty RDS Protection eligibility against its current
# supported engine/version table and prerequisites; engine family alone is insufficient
aws rds describe-db-clusters \
  --query 'DBClusters[].{Id:DBClusterIdentifier,Engine:Engine,EngineVersion:EngineVersion}' --region <region>
aws rds describe-db-instances \
  --query 'DBInstances[].{Id:DBInstanceIdentifier,Engine:Engine,EngineVersion:EngineVersion}' --region <region>

# AWS Backup vaults — GuardDuty Malware Protection for Backup, recovery-critical vaults first
aws backup list-backup-vaults --region <region>
```

## Network and edge

```bash
# CloudFront distributions (global service — no --region). Origins identify ALBs and API
# Gateway endpoints that may sit behind CloudFront. Domain matching does not prove
# origin access restrictions; manually verify without collecting secret header names/values.
aws cloudfront list-distributions \
  --query 'DistributionList.Items[].{Id:Id,Domain:DomainName,WebACL:WebACLId,Origins:Origins.Items[].DomainName}'

# Load balancers — ALBs are WAF-associable, NLBs are not. DNSName matches CloudFront
# origins; Scheme separates internet-facing from internal.
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[].{Arn:LoadBalancerArn,Name:LoadBalancerName,Type:Type,Scheme:Scheme,DNSName:DNSName}' \
  --region <region>

# API Gateway
aws apigateway get-rest-apis --query 'items[].{Id:id,Name:name}' --region <region>
aws apigatewayv2 get-apis --query 'Items[].{Id:ApiId,Name:Name,Protocol:ProtocolType}' \
  --region <region>

# REST API stages supply the regional WAF resource ARN; use the caller's partition
aws apigateway get-stages --rest-api-id <api-id> \
  --query 'item[].stageName' --region <region>
# Use the ALB ARN above or arn:<partition>:apigateway:<region>::/restapis/<api-id>/stages/<stage-name>
aws wafv2 get-web-acl-for-resource --resource-arn <resource-arn> \
  --query 'WebACL.{Arn:ARN,Name:Name}' --region <region>
# CloudFront uses WebACLId above. Preserve errors; do not interpret failed reads as no ACL.

# VPCs — Route 53 Resolver DNS Firewall, Security Lake VPC_FLOW and ROUTE53 (no flow-log
# prerequisite). Existing flow logs matter for the duplicate-collection cost note only.
aws ec2 describe-vpcs --query 'Vpcs[].VpcId' --region <region>
aws ec2 describe-flow-logs \
  --query 'FlowLogs[].{Id:FlowLogId,Resource:ResourceId,Status:FlowLogStatus}' \
  --region <region>

# Availability zones in use — Network Firewall wants an endpoint per AZ with workloads in
# the inspection VPC; spokes in a centralized design need none
aws ec2 describe-subnets \
  --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone,Vpc:VpcId}' --region <region>
```

## Certificates

```bash
# ACM-managed inventory across the current documented key-type set. Read the current
# ListCertificates Includes keyTypes values from ACM documentation and substitute all of them
# below. If that set cannot be read, an unfiltered call is partial evidence only: ACM's default
# key-type filter can omit whole certificate classes, including EC and non-default RSA types.
# Report returned certificates, but mark non-default key types potentially present and
# unenumerated; do not claim fleet completeness.
# Type alone does not prove renewal eligibility or monitoring; use the enablement reference.
# Direct CA issuance may be outside ACM.
aws acm list-certificates \
  --includes keyTypes=<comma-separated-current-key-types> \
  --query 'CertificateSummaryList[].{Arn:CertificateArn,Domain:DomainName,Status:Status,Type:Type,NotAfter:NotAfter,InUse:InUse}' \
  --region <region>

# Private CAs
aws acm-pca list-certificate-authorities \
  --query 'CertificateAuthorities[].{Arn:Arn,Type:Type,Status:Status}' --region <region>
```

## Foundational logging

```bash
# CloudTrail — prerequisite for Security Lake CloudTrail management events, which
# requires a multi-region organization trail capturing read and write management events
aws cloudtrail describe-trails \
  --query 'trailList[].{Name:Name,MultiRegion:IsMultiRegionTrail,Org:IsOrganizationTrail,Home:HomeRegion}'

aws cloudtrail get-event-selectors --trail-name <name> --region <trail-home-region>
```

## Organization context

```bash
# Standalone accounts raise AWSOrganizationsNotInUseException — treat as standalone
aws organizations describe-organization \
  --query 'Organization.{Id:Id,ManagementAccountId:MasterAccountId}'

# ONLY with explicitly requested detailed account enumeration: keep IDs/State for reconciliation.
# Otherwise reuse scoped confirmed counts or mark count-dependent triggers NOT ASSESSED.
aws organizations list-accounts --query 'Accounts[].{Id:Id,State:State}'

# Accounts registered as a delegated administrator for any service. The response has no
# service field, so it does not show which service each account administers: for that, add
# --service-principal <service>.amazonaws.com, or use the per-service admin checks in
# enablement-checks.md.
aws organizations list-delegated-administrators \
  --query 'DelegatedAdministrators[].{Id:Id,Status:Status}'

# Enabled regions — external-access analyzers need regional evidence too
aws account list-regions \
  --region-opt-status-contains ENABLED ENABLED_BY_DEFAULT \
  --query 'Regions[].RegionName'
```

## Recording the inventory

Record observations before pass 2, including scope and completion. Call a type absent
only after complete relevant reads; distinguish UNKNOWN, NOT ASSESSED and NOT APPLICABLE.

| Resource type | Count | Notes |
|---|---|---|
| EC2 instances | | how many SSM-managed |
| EBS volumes | | |
| ECR repositories | | |
| ECS clusters | | Fargate vs EC2 per service/task; unresolved providers |
| EKS clusters | | mixed compute; unresolved self-managed nodes; audit logs |
| Lambda functions | | |
| AI workloads | | GuardDuty AI Protection-covered services from the latest documentation in use; unresolved use or eligibility UNKNOWN |
| S3 buckets | | which take untrusted uploads |
| Backup vaults | | which protect recovery-critical workloads |
| RDS / Aurora | | engine/version and documented eligibility; unresolved prerequisites |
| CloudFront distributions | | WebACL attached? static-only content? |
| ALBs | | internet-facing vs internal; behind CloudFront? |
| API Gateway APIs | | behind CloudFront? |
| VPCs | | DNS Firewall associated? flow logs (duplicate-collection note) |
| AZs with workloads | | Network Firewall endpoint per AZ in the inspection VPC? |
| Active accounts | | Firewall Manager trigger is 10+ with distributed firewalls |
| ACM certificates | | renewal eligibility/path; monitoring evidence |
| Private CAs | | trust domains, issuing relationships and root-isolation evidence |
