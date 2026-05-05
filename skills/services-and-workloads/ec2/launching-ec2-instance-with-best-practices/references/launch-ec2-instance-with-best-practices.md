# Launch EC2 Instance with Best Practices

## Overview

This SOP provides a guided, safe approach to launching an EC2 instance with sensible defaults optimized for security, cost-efficiency, and AWS best practices. The SOP intelligently suggests defaults based on user context while ensuring security hardening, proper IAM roles, appropriate instance sizing, and comprehensive tagging.

## Parameters

Prompt the user in a single message to provide all required parameters at once. Clearly list the required parameters and their descriptions, and include any optional parameters with their default values. Do not proceed until you have received and confirmed all required parameters. If any required parameter is missing or unclear, you MUST explicitly request the missing information before moving forward.

- **workload_type** (required): The primary purpose of this instance (e.g., "web-server", "application-server", "database", "batch-processing", "development", "testing", "bastion-host")
- **region** (required): The AWS region where the instance will be launched (e.g., "us-east-1", "eu-west-1", "ap-southeast-1")
- **environment** (optional, default: "development"): The environment type (e.g., "production", "staging", "development", "testing")
- **vpc_id** (optional): VPC ID where the instance should be launched (if not provided, will use default VPC)
- **subnet_id** (optional): Subnet ID for instance placement (if not provided, will select appropriate subnet from VPC)
- **services_needed** (optional): Comma-separated list of AWS services the instance needs to access (e.g., "s3,dynamodb,sqs")
- **instance_name** (optional): Name tag for the instance (if not provided, will generate based on workload_type and environment)
- **enable_public_ip** (optional, default: based on workload_type): Whether to assign a public IP address (true/false)
- **root_volume_size** (optional, default: 20): Root volume size in GB (8-100 recommended based on workload)
- **enable_monitoring** (optional, default: false): Enable detailed CloudWatch monitoring (costs extra, recommended for production)
- **enable_termination_protection** (optional, default: based on environment): Enable termination protection (recommended for production)
- **allow_ssh_from** (optional; required if `workload_type` is `bastion-host`): CIDR block to allow SSH access from (e.g., "203.0.113.25/32"). If omitted (and not bastion-host), SSH is disabled and access is via AWS Systems Manager Session Manager instead

Only proceed to the steps below if you have all required information.

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context:
  - call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects, consume resources unnecessarily, or trigger actions before the user is ready
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort

### 2. Analyze User Context and Set Intelligent Defaults

Based on the provided parameters, determine appropriate defaults for unspecified options.

**Constraints:**

- You MUST analyze the `workload_type` to determine appropriate defaults:
  - **web-server**: t3.micro or t3.small, public IP enabled, HTTP/HTTPS ports, CloudWatch Logs access
  - **application-server**: t3.small or t3.medium, private subnet preferred, application ports, S3/CloudWatch access
  - **database**: t3.small or t3.medium (minimum), private subnet required, database ports, EBS-optimized, larger root volume (50GB+)
  - **batch-processing**: t3.medium or larger, private subnet, S3/SQS access, larger root volume (50GB+)
  - **development**: t3.micro or t3.small, public IP optional, broader security group, cost optimization priority
  - **testing**: t3.micro, public IP optional, temporary resources, no termination protection
  - **bastion-host**: t3.nano or t3.micro, public subnet required, SSH only, restrictive source IP
- You MUST set defaults based on `environment`:
  - **production**: Enable termination protection, detailed monitoring, regular backups, stricter security groups, proper tagging
  - **staging**: Moderate settings, cost-conscious, similar to production but less restrictive
  - **development**: Cost-optimized, relaxed security (still secure), no termination protection, minimal monitoring
  - **testing**: Minimal resources, temporary nature, easy cleanup
- You MUST determine appropriate instance type based on workload:
  - Start with t3 family (burstable, cost-efficient)
  - Recommend t3.micro for: development, testing, bastion-host, low-traffic web
  - Recommend t3.small for: web-server, light applications
  - Recommend t3.medium for: application-server, database, batch-processing
  - Consider t3a family as cost-effective alternative (AMD processors)
- You MUST determine appropriate AMI:
  - Default to Amazon Linux 2023 (latest, free tier eligible, optimized for AWS)
  - Alternative options: Ubuntu 22.04 LTS, Amazon Linux 2, Red Hat Enterprise Linux (RHEL), Windows Server
  - Consider workload-specific AMIs (e.g., Deep Learning AMI for ML workloads)
- You MUST determine security settings:
  - Default to private subnet unless workload requires public access
  - Enable public IP only for: web-server, bastion-host, development (if needed)
  - Apply principle of least privilege for security groups
- You MUST determine storage defaults:
  - 8-10 GB: Minimal (testing, bastion)
  - 20-30 GB: Standard (web-server, development, application-server)
  - 50-100 GB: Data-intensive (database, batch-processing)
  - Use gp3 volume type (better performance and cost than gp2)
- You MUST present all proposed defaults to the user for confirmation before proceeding
- You MUST explain the reasoning behind each default recommendation
- You MUST allow the user to override any default

### 3. Verify Network Configuration

Validate the VPC and subnet configuration or select appropriate defaults.

**Constraints:**

- You MUST check if a VPC was specified, otherwise identify the default VPC using: `aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --region ${region}`
- You MUST verify the VPC exists and is available using: `aws ec2 describe-vpcs --vpc-ids ${vpc_id} --region ${region}`
- You MUST retrieve available subnets in the VPC: `aws ec2 describe-subnets --filters "Name=vpc-id,Values=${vpc_id}" --region ${region}`
- You MUST analyze subnet characteristics:
  - Check if subnet has a route to an Internet Gateway (public subnet)
  - Check if subnet has a route to a NAT Gateway (private subnet with internet access)
  - Check availability zone distribution
  - Check available IP addresses
- You MUST select an appropriate subnet based on requirements:
  - If `enable_public_ip` is true, select a public subnet
  - If `enable_public_ip` is false, select a private subnet
  - Prefer subnets with more available IP addresses
  - Distribute across availability zones for resilience
- You MUST warn the user if:
  - No default VPC exists and no VPC was specified
  - Selected subnet has limited available IPs (< 10)
  - Public IP is requested but subnet is private (will fail)
  - Private instance without NAT gateway (no internet access for updates)
- You MUST present the selected VPC and subnet to the user for confirmation
- You MUST explain the network topology and access implications

### 4. Select Appropriate AMI

Choose the most suitable Amazon Machine Image based on workload and region.

**Constraints:**

- You MUST retrieve the latest AMI that matches the selected operating system in the target region
  - For Amazon Linux 2023 recommendations, use: `aws ec2 describe-images --owners amazon --filters "Name=name,Values=al2023-ami-2023.*-x86_64" "Name=state,Values=available" --query "sort_by(Images, &CreationDate)[-1].[ImageId,Name,Description]" --region ${region}`
  - For other operating systems (e.g., Ubuntu, Windows, custom Hardened AMIs), adjust the filters accordingly and show the exact command you used
- You MUST verify the AMI exists and is available
- You MUST retrieve AMI details including:
  - Architecture (x86_64 or arm64)
  - Virtualization type (HVM recommended)
  - Root device type (EBS)
  - Block device mappings
  - Free tier eligibility
- You MUST provide alternative AMI options based on workload:
  - **General Purpose**: Amazon Linux 2023 (recommended), Amazon Linux 2, Ubuntu 22.04 LTS
  - **Web Server**: Amazon Linux 2023 with pre-configured LAMP/NGINX
  - **Windows**: Windows Server 2022, Windows Server 2019
  - **Database**: Amazon Linux 2023 (for self-managed databases)
  - **Development**: Ubuntu 22.04 LTS (popular for dev environments)
  - **Machine Learning**: AWS Deep Learning AMI
- You MUST consider ARM-based alternatives (Graviton processors):
  - t4g instance types offer better price-performance
  - Compatible with most Linux workloads
  - Recommend arm64 AMIs if appropriate
- You MUST present the selected AMI to the user with:
  - AMI ID
  - AMI name and description
  - Architecture
  - Operating system version
  - Free tier eligibility status
- You MUST allow the user to specify a different AMI ID if desired
- You MUST verify any user-specified AMI exists and is compatible with selected instance type

### 5. Determine Instance Type and Configuration

Recommend appropriate instance type based on workload and budget.

**Constraints:**

- You MUST consider t3/t3a instance family first (burstable, cost-efficient):
  - **t3.nano**: 2 vCPU, 0.5 GB RAM - Minimal workloads, monitoring, bastion
  - **t3.micro**: 2 vCPU, 1 GB RAM - Free tier eligible, development, testing, low-traffic web
  - **t3.small**: 2 vCPU, 2 GB RAM - Web servers, small applications, light databases
  - **t3.medium**: 2 vCPU, 4 GB RAM - Application servers, development databases, batch jobs
  - **t3.large**: 2 vCPU, 8 GB RAM - Medium applications, production databases
  - **t3a.*** variants: AMD processors, 10% cost savings
- You MUST consider t4g instance family for ARM compatibility:
  - Up to 40% better price-performance than t3
  - Requires ARM-compatible AMI
  - Same size options as t3 family
- You MUST recommend instance type based on workload_type:
  - **bastion-host**: t3.nano or t3.micro
  - **web-server**: t3.micro (low traffic) or t3.small (moderate traffic)
  - **application-server**: t3.small or t3.medium
  - **database**: t3.medium minimum (consider m6i for production databases)
  - **batch-processing**: t3.medium or larger (consider compute-optimized c6i for intensive tasks)
  - **development**: t3.micro or t3.small
  - **testing**: t3.micro
- You MUST warn about t-class burst credit limitations:
  - Explain baseline CPU performance and burst credits
  - Recommend unlimited mode for consistent workloads
  - Suggest monitoring credit balance in production
- You MUST check if instance type is available in the selected availability zone: `aws ec2 describe-instance-type-offerings --location-type availability-zone --filters "Name=instance-type,Values=${instance_type}" --region ${region}`
- You MUST present instance type recommendation with:
  - vCPU count and memory size
  - Cost estimate (hourly and monthly)
  - Baseline CPU performance and burst credits
  - Free tier eligibility status
  - Network performance characteristics
- You MUST allow the user to override with a different instance type
- You MUST validate any user-specified instance type is compatible with the selected AMI architecture

### 6. Create or Verify SSH Key Pair

Ensure an SSH key pair exists for instance access.

**Constraints:**

- If `allow_ssh_from` is NOT provided **and `workload_type` is not `bastion-host`** and no SSH ingress rule is being created, you MUST skip key pair creation entirely — SSM Session Manager does not require a key pair. Proceed to the next step.
- If `allow_ssh_from` IS provided or an SSH ingress rule is being created:
  - You MUST check if `key_pair_name` was provided
  - You MUST verify existing key pair if specified: `aws ec2 describe-key-pairs --key-names ${key_pair_name} --region ${region}`
  - You MUST create a new key pair if requested or none exists:

    ```bash
    aws ec2 create-key-pair --key-name ${key_pair_name} --key-type rsa --key-format pem --region ${region} --query 'KeyMaterial' --output text > ${key_pair_name}.pem
    ```

  - You MUST set appropriate file permissions immediately after creation: `chmod 400 ${key_pair_name}.pem`
  - You MUST instruct the user to save the private key material themselves in a secure location and you MUST NOT request or attempt to view the key contents
  - If the user asks you to store, transmit, or inspect the private key, you MUST decline and recommend engaging AppSec or following the organization's secure key handling policy
  - You MUST warn the user that this is the ONLY opportunity to download the private key
  - You MUST provide clear instructions for saving and protecting the key file:

    ```
    IMPORTANT: Save this private key securely!
    - File location: ./${key_pair_name}.pem
    - This is the ONLY copy - it cannot be recovered if lost
    - Keep it secure - anyone with this key can access your instance
    - Never commit this file to version control
    - Set proper permissions: chmod 400 ${key_pair_name}.pem
    ```

  - You MUST add tags to the key pair for tracking: `aws ec2 create-tags --resources ${key_pair_id} --tags Key=Name,Value=${key_pair_name} Key=Environment,Value=${environment} Key=CreatedBy,Value=ec2-instance-launch-script --region ${region}`
  - You MUST handle the case where key pair name conflicts with existing key pair
  - You MUST offer alternative options:
    - Use existing key pair
    - Create new key pair with different name
    - Proceed without key pair (not recommended - limits access options)
  - You MUST inform user how to connect using the key pair later

### 7. Create IAM Role with Least Privilege

Set up an IAM role if the instance needs to access AWS services.

**Constraints:**

- If `allow_ssh_from` is NOT provided **and `workload_type` is not `bastion-host`** (SSM Session Manager is the access method), you MUST create the IAM role even if `services_needed` is empty, and you MUST attach `AmazonSSMManagedInstanceCore` to it
- You MUST skip this step only if `services_needed` is empty AND (`allow_ssh_from` IS provided OR `workload_type` is `bastion-host`)
- You MUST check if a role name was suggested, otherwise generate one: `${instance_name}-role` or `${workload_type}-${environment}-role`
- You MUST check if the role already exists: `aws iam get-role --role-name ${role_name}`
- You MUST create EC2 trust policy document:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "ec2.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }
  ```

- You MUST create the IAM role: `aws iam create-role --role-name ${role_name} --assume-role-policy-document file://trust-policy.json --description "IAM role for ${workload_type} instance in ${environment}"`
- You MUST apply least privilege principle when selecting permissions:
  - **s3**: If read-only: `AmazonS3ReadOnlyAccess`, if read-write: custom policy with specific bucket ARNs
  - **dynamodb**: Custom policy with specific table ARNs and required actions only
  - **sqs**: Custom policy with specific queue ARNs
  - **cloudwatch**: `CloudWatchAgentServerPolicy` for metrics and logs
  - **ssm**: `AmazonSSMManagedInstanceCore` for Systems Manager access
  - **secretsmanager**: Custom policy with specific secret ARNs
- You MUST create custom inline policies for specific permissions:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        "Resource": [
          "arn:aws:s3:::specific-bucket-name",
          "arn:aws:s3:::specific-bucket-name/*"
        ]
      }
    ]
  }
  ```

- You MUST attach policies to the role: `aws iam attach-role-policy --role-name ${role_name} --policy-arn ${policy_arn}`
- You MUST create instance profile: `aws iam create-instance-profile --instance-profile-name ${role_name}`
- You MUST add role to instance profile: `aws iam add-role-to-instance-profile --instance-profile-name ${role_name} --role-name ${role_name}`
- You MUST add tags to the role: `aws iam tag-role --role-name ${role_name} --tags Key=Name,Value=${role_name} Key=Environment,Value=${environment} Key=ManagedBy,Value=ec2-instance-launch-script`
- You MUST wait for the instance profile to be fully created (may take 10-15 seconds)
- You MUST verify the instance profile exists: `aws iam get-instance-profile --instance-profile-name ${role_name}`
- You MUST present the created role and attached policies to the user

### 8. Create Hardened Security Group

Configure a security group with minimal required access based on workload type.

**Constraints:**

- You MUST generate a security group name: `${instance_name}-sg` or `${workload_type}-${environment}-sg`
- You MUST create the security group in the selected VPC: `aws ec2 create-security-group --group-name ${sg_name} --description "Security group for ${workload_type} instance in ${environment}" --vpc-id ${vpc_id} --region ${region}`
- You MUST implement least privilege access - only open ports that are absolutely necessary
- You MUST determine required ingress rules based on `workload_type`:
  - **web-server**:
    - Port 80 (HTTP) from 0.0.0.0/0
    - Port 443 (HTTPS) from 0.0.0.0/0
    - Port 22 (SSH) from specific IP only **if `allow_ssh_from` is provided**
  - **application-server**:
    - Application port (ask user) from VPC CIDR only
    - Port 22 (SSH) from bastion host or specific IP **if `allow_ssh_from` is provided**
  - **database**:
    - Database port (3306 for MySQL, 5432 for PostgreSQL, etc.) from application security group only
    - Port 22 (SSH) from bastion host or specific IP only **if `allow_ssh_from` is provided**
    - NEVER expose database ports to 0.0.0.0/0
  - **batch-processing**:
    - Port 22 (SSH) from specific IP only **if `allow_ssh_from` is provided**
    - No other inbound access required typically
  - **development**:
    - Port 22 (SSH) from specific IP only **if `allow_ssh_from` is provided**
    - Additional ports as needed for development (ask user)
  - **testing**:
    - Port 22 (SSH) from specific IP only **if `allow_ssh_from` is provided**
  - **bastion-host**:
    - Port 22 (SSH) from specific IP only (NEVER 0.0.0.0/0)
    - `allow_ssh_from` is REQUIRED for bastion-host — if not provided, you MUST ask the user for it before proceeding
- You MUST handle SSH access IP configuration:
  - If `allow_ssh_from` is provided:
    - Validate it's a proper CIDR block and add an SSH ingress rule for it
    - Recommend /32 for single IP (e.g., "203.0.113.25/32")
    - Warn against using 0.0.0.0/0 for SSH access
  - If `allow_ssh_from` is NOT provided **and `workload_type` is not `bastion-host`**, default to NO SSH ingress rule — use AWS Systems Manager Session Manager instead (attach AmazonSSMManagedInstanceCore to the IAM role). Mention this choice in the summary and proceed without asking
- You MUST add ingress rules using: `aws ec2 authorize-security-group-ingress --group-id ${sg_id} --ip-permissions IpProtocol=${protocol},FromPort=${port},ToPort=${port},IpRanges="[{CidrIp=${cidr},Description=${description}}]" --region ${region}`
- You MUST NOT modify the default egress rule (allow all outbound) unless specifically required
- You MUST add tags to the security group: `aws ec2 create-tags --resources ${sg_id} --tags Key=Name,Value=${sg_name} Key=Environment,Value=${environment} Key=WorkloadType,Value=${workload_type} Key=ManagedBy,Value=ec2-instance-launch-script --region ${region}`
- You MUST present the security group configuration to the user for review:
  - List all ingress rules with ports, protocols, and source CIDRs
  - Explain what each rule allows
  - Highlight any security concerns
- You MUST allow the user to add additional rules if needed
- You MUST warn about common security misconfigurations:
  - SSH (port 22) open to 0.0.0.0/0
  - Database ports open to public internet
  - RDP (port 3389) open to 0.0.0.0/0
  - Unnecessary ports open

### 9. Configure Storage Settings

Define the root volume and any additional EBS volumes.

**Constraints:**

- You MUST determine appropriate root volume size based on `workload_type` and `root_volume_size` parameter:
  - Minimum 8 GB (operating system)
  - Default 20 GB for most workloads
  - 50+ GB for database or batch-processing workloads
  - 100+ GB for data-intensive applications
- You MUST use gp3 volume type (General Purpose SSD) as default:
  - Better performance than gp2 (3000 IOPS baseline)
  - Lower cost than gp2
  - Configurable IOPS and throughput
- You MUST consider volume type alternatives:
  - **gp3**: Default, best cost-performance for most workloads
  - **gp2**: Legacy, use gp3 instead
  - **io2**: Provisioned IOPS for high-performance databases (expensive)
  - **st1**: Throughput-optimized HDD for big data (lower cost, slower)
  - **sc1**: Cold HDD for infrequently accessed data (lowest cost)
- You MUST enable encryption by default for security best practices
- You MUST use the default AWS-managed KMS key unless user specifies custom key
- You MUST configure delete on termination based on environment:
  - **production**: false (preserve data)
  - **staging**: true (clean up automatically)
  - **development**: true (clean up automatically)
  - **testing**: true (clean up automatically)
- You MUST construct block device mapping for launch:

  ```json
  [
    {
      "DeviceName": "/dev/xvda",
      "Ebs": {
        "VolumeSize": ${volume_size},
        "VolumeType": "gp3",
        "DeleteOnTermination": ${delete_on_termination},
        "Encrypted": true
      }
    }
  ]
  ```

- You MUST ask user if additional EBS volumes are needed:
  - Data volume separate from root volume
  - Different volume types for different access patterns
  - Snapshots for backup
- You MUST present storage configuration to user:
  - Volume size and type
  - Encryption status
  - Delete on termination setting
  - Estimated monthly cost
- You MUST warn about cost implications of large volumes and provisioned IOPS

### 10. Define Comprehensive Tags

Create a robust tagging strategy for cost tracking, organization, and automation.

**Constraints:**

- You MUST implement a comprehensive tagging strategy with required tags:
  - **Name**: Human-readable instance name (from `instance_name` or generated)
  - **Environment**: Environment type (production, staging, development, testing)
  - **WorkloadType**: Type of workload (web-server, application-server, etc.)
  - **ManagedBy**: Tool that created the instance (e.g., "ec2-instance-launch-script")
  - **CreatedDate**: Date instance was created (YYYY-MM-DD format)
  - **Owner**: Person or team responsible (ask user if not obvious)
  - **CostCenter**: Cost allocation tag (ask user if tracking costs by department/project)
  - **Project**: Project name (ask user if applicable)
- You MUST generate a default instance name if not provided:
  - Format: `${workload_type}-${environment}-${random_suffix}`
  - Example: "web-server-production-a1b2"
  - Ensure name is descriptive and follows naming conventions
- You MUST ask user for additional tags relevant to their organization:
  - Department
  - Application name
  - Backup schedule
  - Compliance requirements
  - Contact email
- You MUST format tags for AWS CLI:

  ```json
  [
    {"Key": "Name", "Value": "${instance_name}"},
    {"Key": "Environment", "Value": "${environment}"},
    {"Key": "WorkloadType", "Value": "${workload_type}"},
    {"Key": "ManagedBy", "Value": "ec2-instance-launch-script"},
    {"Key": "CreatedDate", "Value": "2025-10-14"},
    {"Key": "Owner", "Value": "${owner}"},
    {"Key": "CostCenter", "Value": "${cost_center}"}
  ]
  ```

- You MUST present the tagging strategy to the user for review
- You MUST explain the importance of consistent tagging:
  - Cost allocation and tracking
  - Resource organization and filtering
  - Automation and policy enforcement
  - Compliance and audit requirements
- You MUST validate tag keys and values:
  - Maximum 128 characters for keys
  - Maximum 256 characters for values
  - No spaces in keys (use PascalCase or camelCase)
  - Consistent naming conventions

### 11. Configure Advanced Settings

Set up additional instance configuration options.

**Constraints:**

- You MUST determine user data SOP needs:
  - Ask if user wants to run initialization scripts
  - Common use cases: Install packages, configure services, register with management tools
  - Provide templates for common scenarios:
    - Install CloudWatch agent
    - Install and configure web server (Apache/Nginx)
    - Install security agents
    - Configure OS updates
    - Join Active Directory domain
- You MUST configure monitoring settings:
  - Basic monitoring: Free, 5-minute metric intervals (default)
  - Detailed monitoring: Costs extra, 1-minute intervals (recommended for production)
  - Enable detailed monitoring if `enable_monitoring` is true or environment is production
- You MUST configure termination protection:
  - Enable for production environments (default)
  - Disable for development/testing (default)
  - Respect `enable_termination_protection` parameter if provided
- You MUST configure tenancy settings:
  - Default: Shared hardware (cost-efficient)
  - Dedicated: Dedicated hardware (compliance requirements, higher cost)
  - Dedicated Host: Specific physical server (license requirements, highest cost)
  - Use default (shared) unless user has specific requirements
- You MUST consider placement group if launching multiple instances:
  - Cluster: High network performance between instances
  - Partition: Large distributed workloads
  - Spread: Critical instances on different hardware
  - Not needed for single instance launch
- You MUST configure instance metadata service (IMDS) settings:
  - Use IMDSv2 (more secure, prevents SSRF attacks)
  - Set HttpTokens=required to enforce IMDSv2
  - Set HttpPutResponseHopLimit=1 (prevent forwarding from containers)
- You MUST configure credit specification for t-class instances:
  - Standard mode: Limited burst, lower cost
  - Unlimited mode: Consistent performance, possible extra charges
  - Recommend unlimited for production workloads
- You MUST present all advanced settings to user for confirmation

### 12. Review and Confirm Launch Configuration

Present a comprehensive summary of the instance configuration before launching.

**Constraints:**

- You MUST create a detailed pre-launch summary including:
  - **Instance Details**:
    - Instance name and tags
    - Instance type (vCPU, memory, cost estimate)
    - AMI ID and description
    - Region and availability zone
  - **Network Configuration**:
    - VPC ID and name
    - Subnet ID and type (public/private)
    - Public IP assignment status
    - Security group ID and rules
  - **Storage Configuration**:
    - Root volume size and type
    - Encryption status
    - Delete on termination setting
    - Additional volumes (if any)
  - **Access Configuration**:
    - Key pair name
    - SSH access source IP/CIDR
    - IAM instance profile (if configured)
  - **Security Features**:
    - Termination protection status
    - Detailed monitoring status
    - IMDSv2 enforcement
    - Security group rules
  - **Cost Estimate**:
    - Hourly compute cost
    - Monthly compute cost (assuming 730 hours)
    - Storage cost per month
    - Data transfer cost estimates (if applicable)
    - Total estimated monthly cost
- You MUST format the summary in a clear, readable format with sections
- You MUST highlight important security settings and warnings:
  - Public IP assignment
  - Open security group rules
  - No termination protection (if production)
  - Missing IAM role (if services access needed)
- You MUST ask the user to explicitly confirm the launch: "Do you want to proceed with launching this EC2 instance? (yes/no)"
- You MUST allow the user to go back and modify any settings
- You MUST wait for explicit user confirmation before proceeding
- You MUST save the complete configuration for reference

### 13. Launch EC2 Instance

Execute the instance launch with all configured settings.

**Constraints:**

- You MUST construct the complete run-instances command with all parameters:

  ```bash
  aws ec2 run-instances \
    --image-id ${ami_id} \
    --instance-type ${instance_type} \
    --key-name ${key_pair_name} \
    --security-group-ids ${sg_id} \
    --subnet-id ${subnet_id} \
    --iam-instance-profile Name=${instance_profile_name} \
    --block-device-mappings '${block_device_mappings}' \
    --tag-specifications "ResourceType=instance,Tags=[${tags}]" "ResourceType=volume,Tags=[${tags}]" \
    --metadata-options "HttpTokens=required,HttpPutResponseHopLimit=1,HttpEndpoint=enabled" \
    --monitoring Enabled=${enable_monitoring} \
    --disable-api-termination=${enable_termination_protection} \
    --credit-specification CpuCredits=${cpu_credits} \
    --user-data file://user-data.sh \
    --region ${region}
  ```

- You MUST include optional parameters only if they were configured:
  - `--iam-instance-profile` only if IAM role was created
  - `--user-data` only if user data script was provided
  - `--associate-public-ip-address` only if explicitly set
  - `--placement` only if specific availability zone was requested
- You MUST capture the instance ID from the response: Extract `InstanceId` from JSON output
- You MUST handle launch errors gracefully:
  - Insufficient instance capacity: Suggest different instance type or availability zone
  - Subnet has no available IPs: Suggest different subnet
  - AMI not available: Verify AMI ID and region
  - Permission errors: Check IAM permissions
  - Limit exceeded: Request limit increase or use different instance type
- You MUST parse the response and extract key information:
  - Instance ID
  - Private IP address
  - Public IP address (if assigned)
  - Availability zone
  - Launch time
- You MUST inform the user immediately upon successful launch:

  ```
  ✓ Instance launched successfully!
  Instance ID: i-0abcd1234efgh5678
  Private IP: 10.0.1.25
  Public IP: 203.0.113.45 (if applicable)
  Status: pending (initializing)
  ```

- You MUST save all launch details for the final report

### 14. Wait for Instance to Reach Running State

Monitor the instance until it's fully initialized and running.

**Constraints:**

- You MUST poll the instance status using: `aws ec2 describe-instances --instance-ids ${instance_id} --region ${region}`
- You MUST wait for instance state to transition from "pending" to "running"
- You MUST monitor the state transition with appropriate polling:
  - Check every 5 seconds initially
  - Increase interval to 10 seconds after 30 seconds
  - Timeout after 5 minutes and report error
- You MUST display progress updates to the user:

  ```
  Waiting for instance to start...
  Status: pending (0:05)
  Status: pending (0:10)
  Status: running (0:15) ✓
  ```

- You MUST retrieve and display instance status checks once running:
  - System status check (AWS infrastructure)
  - Instance status check (operating system)
  - Wait for both status checks to pass (typically 2-3 minutes)
- You MUST handle timeout scenarios:
  - Instance stuck in pending state (> 5 minutes)
  - Status checks failing repeatedly
  - Unexpected state transitions (terminated, stopped, etc.)
- You MUST provide troubleshooting guidance if launch fails:
  - Check system logs: `aws ec2 get-console-output --instance-id ${instance_id}`
  - Review status check failures
  - Verify AMI compatibility with instance type
  - Check subnet IP availability
- You MUST inform user when instance is fully ready:

  ```
  ✓ Instance is running and ready!
  System status check: passed ✓
  Instance status check: passed ✓
  Time to ready: 2 minutes 45 seconds
  ```

### 15. Verify Instance Configuration

Confirm all settings were applied correctly after launch.

**Constraints:**

- You MUST retrieve complete instance details: `aws ec2 describe-instances --instance-ids ${instance_id} --region ${region}`
- You MUST verify all configured settings:
  - Instance type matches requested type
  - AMI ID matches selected AMI
  - Security groups are correctly attached
  - IAM instance profile is attached (if configured)
  - Tags are applied to instance and volumes
  - Public IP is assigned (if requested)
  - Subnet and VPC are correct
  - Key pair is associated
  - Termination protection is enabled (if requested)
  - Detailed monitoring is enabled (if requested)
- You MUST verify the security group rules: `aws ec2 describe-security-groups --group-ids ${sg_id} --region ${region}`
- You MUST verify the IAM instance profile (if used): `aws ec2 describe-iam-instance-profile-associations --filters "Name=instance-id,Values=${instance_id}" --region ${region}`
- You MUST verify EBS volumes: `aws ec2 describe-volumes --filters "Name=attachment.instance-id,Values=${instance_id}" --region ${region}`
- You MUST check for any configuration mismatches or errors
- You MUST inform user of any discrepancies between requested and actual configuration
- You MUST retrieve instance metadata to verify IMDSv2 is enforced:
  - Check HttpTokens setting is "required"
  - Verify HttpPutResponseHopLimit is set correctly

### 16. Provide Connection Instructions

Give the user clear instructions for connecting to the instance.

**Constraints:**

- You MUST provide SSH connection instructions if key pair was configured:

  ```bash
  # Make sure key file has correct permissions
  chmod 400 ${key_pair_name}.pem

  # Connect to the instance
  ssh -i ${key_pair_name}.pem ec2-user@${public_ip}

  # Or using private IP from within VPC
  ssh -i ${key_pair_name}.pem ec2-user@${private_ip}
  ```

- You MUST specify the correct default username based on AMI:
  - Amazon Linux 2023/2: `ec2-user`
  - Ubuntu: `ubuntu`
  - RHEL: `ec2-user` or `root`
  - CentOS: `centos`
  - Debian: `admin`
  - SUSE: `ec2-user`
  - Windows: Use RDP with password from EC2 console
- You MUST provide alternative connection methods:
  - **AWS Systems Manager Session Manager** (no SSH key required):

    ```bash
    aws ssm start-session --target ${instance_id} --region ${region}
    ```

    Note: Requires SSM agent (pre-installed on Amazon Linux 2023) and IAM role with SSM permissions
  - **EC2 Instance Connect** (browser-based SSH):

    ```bash
    aws ec2-instance-connect send-ssh-public-key \
      --instance-id ${instance_id} \
      --availability-zone ${availability_zone} \
      --instance-os-user ec2-user \
      --ssh-public-key file://~/.ssh/id_rsa.pub
    ```

  - **EC2 Serial Console** (troubleshooting when network is unavailable)
- You MUST provide connection troubleshooting tips:
  - Verify security group allows SSH from your IP
  - Check that instance is in running state
  - Verify public IP address (if connecting from internet)
  - Ensure key file permissions are correct (400)
  - Check network connectivity to the subnet
  - Verify NACLs allow inbound SSH traffic
- You MUST provide instructions for retrieving instance password (Windows instances):

  ```bash
  aws ec2 get-password-data --instance-id ${instance_id} --priv-launch-key file://${key_pair_name}.pem
  ```

- You MUST explain connection scenarios:
  - **Public instance with public IP**: Connect directly from internet using public IP
  - **Private instance**: Connect via bastion host, VPN, or AWS Session Manager
  - **No key pair**: Use AWS Session Manager or EC2 Serial Console

### 17. Generate Comprehensive Launch Report

Create a detailed report documenting the entire instance launch and configuration.

**Constraints:**

- You MUST create a complete launch report containing:
  - **Executive Summary**:
    - Instance ID and name
    - Instance type and AMI
    - Region and availability zone
    - Launch timestamp
    - Current status
    - Total launch time
    - Estimated monthly cost
  - **Instance Configuration**:
    - Complete technical specifications
    - Network configuration details
    - Storage configuration
    - Security settings
    - IAM role and permissions
    - Tags applied
  - **Security Configuration**:
    - Security group rules (ingress and egress)
    - IAM instance profile and policies
    - Encryption settings
    - IMDSv2 configuration
    - Termination protection status
  - **Access Information**:
    - SSH/RDP connection commands
    - Public and private IP addresses
    - Alternative access methods (SSM, Instance Connect)
    - Key pair name and location
  - **Cost Breakdown**:
    - Hourly compute cost
    - Monthly compute estimate
    - Storage cost
    - Data transfer estimates
    - Monitoring costs (if enabled)
    - Total estimated monthly cost
  - **Post-Launch Tasks**:
    - Recommended immediate actions
    - Security hardening steps
    - Monitoring setup
    - Backup configuration
    - Update management
  - **Management Commands**:
    - How to stop/start the instance
    - How to modify configuration
    - How to create AMI backup
    - How to terminate the instance
  - **Troubleshooting Guide**:
    - Common connection issues
    - How to access system logs
    - Status check failures
    - Performance issues
- You MUST include specific commands and examples for common operations:

  ```bash
  # Stop the instance (preserves EBS volumes, stops charges)
  aws ec2 stop-instances --instance-ids ${instance_id} --region ${region}

  # Start the instance
  aws ec2 start-instances --instance-ids ${instance_id} --region ${region}

  # Reboot the instance
  aws ec2 reboot-instances --instance-ids ${instance_id} --region ${region}

  # Get instance details
  aws ec2 describe-instances --instance-ids ${instance_id} --region ${region}

  # Get console output (troubleshooting)
  aws ec2 get-console-output --instance-id ${instance_id} --region ${region}

  # Create AMI backup
  aws ec2 create-image --instance-id ${instance_id} --name "${instance_name}-backup-$(date +%Y%m%d)" --no-reboot --region ${region}

  # Terminate the instance (WARNING: This will delete the instance)
  aws ec2 terminate-instances --instance-ids ${instance_id} --region ${region}
  ```

- You MUST provide a security hardening checklist:
  - [ ] Update all packages: `sudo yum update -y` (Amazon Linux) or `sudo apt update && sudo apt upgrade -y` (Ubuntu)
  - [ ] Configure automatic security updates
  - [ ] Set up CloudWatch monitoring and alarms
  - [ ] Enable CloudTrail logging for API calls
  - [ ] Configure AWS Backup for automated backups
  - [ ] Install and configure security agents (if applicable)
  - [ ] Disable root login via SSH
  - [ ] Configure fail2ban or similar intrusion prevention
  - [ ] Set up log forwarding to CloudWatch Logs
  - [ ] Configure AWS Systems Manager for patch management
  - [ ] Review and tighten security group rules
  - [ ] Implement least privilege IAM policies
  - [ ] Enable VPC Flow Logs
  - [ ] Configure OS-level firewall (iptables/firewalld)
- You MUST provide monitoring recommendations:
  - Set up CloudWatch alarms for:
    - CPU utilization > 80%
    - Status check failures
    - Disk space usage > 80%
    - Network anomalies
  - Enable CloudWatch Logs Agent for application logs
  - Configure AWS X-Ray for application tracing (if applicable)
  - Set up AWS Cost Anomaly Detection
- You MUST include cost optimization tips:
  - Stop instances when not in use (development/testing)
  - Use AWS Compute Optimizer recommendations
  - Consider Reserved Instances or Savings Plans for long-term workloads
  - Right-size instances based on actual usage metrics
  - Use EBS volume snapshots instead of keeping full volumes
  - Configure lifecycle policies for old snapshots
  - Review and remove unused elastic IPs
- You MUST format the report in a clear, professional manner with proper sections and subsections
- You MUST save the report to a file for user reference: `instance-launch-report-${instance_id}-${timestamp}.md`
- You MUST present the complete report to the user

## Examples

### Example Input

```
workload_type: web-server
region: us-east-1
environment: production
services_needed: s3,cloudwatch
allow_ssh_from: 203.0.113.25/32
instance_name: company-website-prod
```

### Example Output

```
# EC2 Instance Launch Report

**Generated:** 2025-10-14 15:30:45 UTC
**Launch Status:** ✓ Success
**Instance ID:** i-0abcd1234efgh5678

---

## Executive Summary

Successfully launched EC2 instance for production web server workload in us-east-1.

- **Instance Name:** company-website-prod
- **Instance Type:** t3.small (2 vCPU, 2 GB RAM)
- **Operating System:** Amazon Linux 2023
- **Region:** us-east-1a
- **Launch Time:** 2:35 minutes
- **Status:** Running ✓
- **Estimated Monthly Cost:** $15.33

---

## Instance Configuration

### Compute Resources
- **Instance ID:** i-0abcd1234efgh5678
- **Instance Type:** t3.small
  - vCPUs: 2
  - Memory: 2 GB RAM
  - CPU Credits: Unlimited mode (consistent performance)
  - Network Performance: Up to 5 Gigabit
- **AMI:** ami-0abcdef1234567890
  - Name: Amazon Linux 2023 AMI 2023.4.20250315.0 x86_64 HVM kernel-6.1
  - Architecture: x86_64
  - Virtualization: HVM
  - Root Device: EBS

### Network Configuration
- **VPC ID:** vpc-0a1b2c3d4e5f67890
- **Subnet ID:** subnet-0123456789abcdef0
  - Type: Public subnet (internet gateway attached)
  - Availability Zone: us-east-1a
  - Available IPs: 247
- **Private IP Address:** 10.0.1.42
- **Public IP Address:** 54.198.123.45
- **Public DNS:** ec2-54-198-123-45.compute-1.amazonaws.com
- **Security Group:** sg-0abc123def456789
  - Name: company-website-prod-sg
  - Rules: 3 ingress, 1 egress

### Storage Configuration
- **Root Volume:**
  - Volume ID: vol-0123456789abcdef0
  - Size: 20 GB
  - Type: gp3 (General Purpose SSD)
  - IOPS: 3000 (baseline)
  - Throughput: 125 MB/s
  - Encrypted: Yes (AWS managed key)
  - Delete on Termination: No (data preserved)

### IAM Configuration
- **Instance Profile:** company-website-prod-role
- **IAM Role:** company-website-prod-role
- **Attached Policies:**
  - AmazonS3ReadOnlyAccess (AWS managed)
  - CloudWatchAgentServerPolicy (AWS managed)

### Tags Applied
| Key | Value |
|-----|-------|
| Name | company-website-prod |
| Environment | production |
| WorkloadType | web-server |
| ManagedBy | ec2-instance-launch-script |
| CreatedDate | 2025-10-14 |
| Owner | DevOps Team |
| CostCenter | Engineering |

---

## Security Configuration

### Security Group Rules

**Ingress Rules (Inbound):**
| Protocol | Port | Source | Description |
|----------|------|--------|-------------|
| TCP | 80 | 0.0.0.0/0 | HTTP web traffic |
| TCP | 443 | 0.0.0.0/0 | HTTPS web traffic |
| TCP | 22 | 203.0.113.25/32 | SSH from admin IP |

**Egress Rules (Outbound):**
| Protocol | Port | Destination | Description |
|----------|------|-------------|-------------|
| All | All | 0.0.0.0/0 | Allow all outbound |

### IAM Permissions Summary
- **S3 Access:** Read-only access to all S3 buckets
- **CloudWatch:** Full access to write metrics and logs
- **EC2 Metadata:** IMDSv2 enforced (secure)

### Security Features Enabled
- ✓ EBS encryption enabled (all volumes)
- ✓ IMDSv2 required (prevents SSRF attacks)
- ✓ Termination protection enabled
- ✓ Detailed monitoring enabled
- ✓ Security group restricts SSH to specific IP
- ✓ Least privilege IAM role attached

---

## Access Information

### SSH Connection

**Primary Method (SSH):**
```bash
# Ensure correct key permissions
chmod 400 company-website-prod-key.pem

# Connect from internet (public IP)
ssh -i company-website-prod-key.pem ec2-user@54.198.123.45

# Connect from within VPC (private IP)
ssh -i company-website-prod-key.pem ec2-user@10.0.1.42
```

**Alternative: AWS Systems Manager Session Manager:**

```bash
# No SSH key required, works even without public IP
aws ssm start-session --target i-0abcd1234efgh5678 --region us-east-1

# Requires:
# - SSM agent installed (pre-installed on Amazon Linux 2023)
# - IAM instance profile with AmazonSSMManagedInstanceCore policy
```

**Alternative: EC2 Instance Connect:**

```bash
# Browser-based SSH from AWS Console
# Navigate to: EC2 → Instances → i-0abcd1234efgh5678 → Connect → EC2 Instance Connect
```

### Connection Details

- **Username:** ec2-user (Amazon Linux default)
- **Key Pair:** company-website-prod-key
- **Key File Location:** ./company-website-prod-key.pem
- **Public IP:** 54.198.123.45
- **Private IP:** 10.0.1.42

### Connection Troubleshooting

- Verify security group allows SSH from your current IP
- Ensure key file permissions are 400 (chmod 400 keyfile.pem)
- Check instance is in "running" state
- Verify you're using the correct username (ec2-user)
- Confirm network connectivity to AWS region

---

## Cost Breakdown

### Compute Costs

| Component | Rate | Hours/Month | Monthly Cost |
|-----------|------|-------------|--------------|
| t3.small instance | $0.0208/hour | 730 | $15.18 |
| Detailed monitoring | $0.14/instance | 1 | $0.14 |

### Storage Costs

| Component | Size | Rate | Monthly Cost |
|-----------|------|------|--------------|
| EBS gp3 volume | 20 GB | $0.08/GB | $1.60 |
| EBS snapshots | 0 GB (initial) | $0.05/GB | $0.00 |

### Data Transfer Costs (Estimated)

- Inbound: Free
- Outbound (first 100 GB): Free
- Outbound (additional): $0.09/GB (varies by destination)

### Total Estimated Monthly Cost
**$16.92** (compute + storage + monitoring)

*Note: Costs are estimates and may vary based on actual usage, data transfer, and AWS pricing changes. Does not include costs for S3, CloudWatch Logs, or other services.*

### Cost Optimization Recommendations

- ✓ Using burstable t3 instance (cost-efficient)
- ✓ Using gp3 volumes (cheaper than gp2)
- ✓ Right-sized for web server workload
- Consider Reserved Instance for 1-year commitment: Save up to 40%
- Consider Savings Plan for flexible commitment: Save up to 54%
- Stop instance when not needed (dev/test only)
- Set up AWS Budget alerts for cost overruns

---

## Post-Launch Tasks

### Immediate Actions Required

1. **Update Operating System** (Critical - Security)

   ```bash
   ssh -i company-website-prod-key.pem ec2-user@54.198.123.45
   sudo dnf update -y
   sudo reboot
   ```

2. **Install Web Server** (Application Setup)

   ```bash
   # Install Nginx
   sudo dnf install nginx -y
   sudo systemctl start nginx
   sudo systemctl enable nginx

   # Or install Apache
   sudo dnf install httpd -y
   sudo systemctl start httpd
   sudo systemctl enable httpd
   ```

3. **Configure CloudWatch Agent** (Monitoring)

   ```bash
   # Download and install CloudWatch agent
   wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
   sudo rpm -U ./amazon-cloudwatch-agent.rpm

   # Configure and start agent
   sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-config-wizard
   ```

4. **Set Up Automatic Security Updates** (Security)

   ```bash
   # Enable automatic updates
   sudo dnf install dnf-automatic -y
   sudo systemctl enable --now dnf-automatic.timer
   ```

5. **Configure Application Logging** (Monitoring)

   ```bash
   # Forward logs to CloudWatch
   sudo vi /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
   # Configure log files to monitor
   ```

### Security Hardening Checklist

- [ ] Change default SSH port (optional, security through obscurity)
- [ ] Disable root login: Edit `/etc/ssh/sshd_config`, set `PermitRootLogin no`
- [ ] Install fail2ban for intrusion prevention:

  ```bash
  sudo dnf install fail2ban -y
  sudo systemctl enable --now fail2ban
  ```

- [ ] Configure OS firewall:

  ```bash
  sudo systemctl start firewalld
  sudo firewall-cmd --permanent --add-service=http
  sudo firewall-cmd --permanent --add-service=https
  sudo firewall-cmd --reload
  ```

- [ ] Set up CloudWatch Logs for SSH access logs
- [ ] Configure AWS Backup for automated backups
- [ ] Enable VPC Flow Logs for network monitoring
- [ ] Implement AWS Config rules for compliance
- [ ] Set up AWS GuardDuty for threat detection
- [ ] Review IAM policies and tighten to specific resources

### Monitoring Setup

**CloudWatch Alarms to Create:**

1. **CPU Utilization** (Performance)

   ```bash
   aws cloudwatch put-metric-alarm \
     --alarm-name company-website-prod-high-cpu \
     --alarm-description "Alert when CPU exceeds 80%" \
     --metric-name CPUUtilization \
     --namespace AWS/EC2 \
     --statistic Average \
     --period 300 \
     --threshold 80 \
     --comparison-operator GreaterThanThreshold \
     --evaluation-periods 2 \
     --dimensions Name=InstanceId,Value=i-0abcd1234efgh5678
   ```

2. **Status Check Failed** (Availability)

   ```bash
   aws cloudwatch put-metric-alarm \
     --alarm-name company-website-prod-status-check \
     --alarm-description "Alert when status checks fail" \
     --metric-name StatusCheckFailed \
     --namespace AWS/EC2 \
     --statistic Maximum \
     --period 60 \
     --threshold 1 \
     --comparison-operator GreaterThanOrEqualToThreshold \
     --evaluation-periods 2 \
     --dimensions Name=InstanceId,Value=i-0abcd1234efgh5678
   ```

3. **Disk Space Monitoring** (Capacity)
   - Requires CloudWatch agent configuration
   - Monitor root volume at `/`
   - Alert when usage > 80%

### Backup Configuration

#### Option 1: AWS Backup (Recommended)

```bash
# Create backup plan in AWS Backup console or CLI
aws backup create-backup-plan --backup-plan file://backup-plan.json

# Associate instance with backup plan
aws backup create-backup-selection --backup-plan-id ${plan_id} --backup-selection file://selection.json
```

#### Option 2: EBS Snapshots

```bash
# Create manual snapshot
aws ec2 create-snapshot \
  --volume-id vol-0123456789abcdef0 \
  --description "company-website-prod backup $(date +%Y-%m-%d)" \
  --tag-specifications "ResourceType=snapshot,Tags=[{Key=Name,Value=company-website-prod-backup}]"

# Set up automated snapshots with Data Lifecycle Manager (DLM)
```

---

## Management Commands

### Instance Lifecycle

**Stop Instance** (Preserves data, stops charges)

```bash
aws ec2 stop-instances --instance-ids i-0abcd1234efgh5678 --region us-east-1
```

#### Start Instance

```bash
aws ec2 start-instances --instance-ids i-0abcd1234efgh5678 --region us-east-1
```

**Reboot Instance** (Graceful restart)

```bash
aws ec2 reboot-instances --instance-ids i-0abcd1234efgh5678 --region us-east-1
```

#### Get Instance Status

```bash
aws ec2 describe-instance-status --instance-ids i-0abcd1234efgh5678 --region us-east-1
```

### Backup and Recovery

**Create AMI Backup** (Complete instance image)

```bash
aws ec2 create-image \
  --instance-id i-0abcd1234efgh5678 \
  --name "company-website-prod-backup-$(date +%Y%m%d)" \
  --description "Backup of company-website-prod created on $(date)" \
  --no-reboot \
  --tag-specifications "ResourceType=image,Tags=[{Key=Name,Value=company-website-prod-backup}]" \
  --region us-east-1
```

#### Restore from AMI

```bash
# Launch new instance from AMI backup
aws ec2 run-instances \
  --image-id ami-0xyz789... \
  --instance-type t3.small \
  --key-name company-website-prod-key \
  --security-group-ids sg-0abc123def456789 \
  --subnet-id subnet-0123456789abcdef0 \
  --region us-east-1
```

### Monitoring and Logs

**Get Console Output** (Boot logs, troubleshooting)

```bash
aws ec2 get-console-output --instance-id i-0abcd1234efgh5678 --region us-east-1 --output text
```

#### View CloudWatch Metrics

```bash
# CPU Utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-0abcd1234efgh5678 \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average \
  --region us-east-1
```

**View System Logs** (via SSH)

```bash
# System messages
sudo tail -f /var/log/messages

# Authentication logs
sudo tail -f /var/log/secure

# Web server logs (Nginx)
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Instance Termination

**⚠️ WARNING: Termination is permanent and will delete the instance!**

```bash
# Disable termination protection first
aws ec2 modify-instance-attribute \
  --instance-id i-0abcd1234efgh5678 \
  --no-disable-api-termination \
  --region us-east-1

# Terminate the instance (DESTRUCTIVE)
aws ec2 terminate-instances --instance-ids i-0abcd1234efgh5678 --region us-east-1
```

**Before terminating:**

- Create final AMI backup
- Take EBS snapshots if needed
- Save any application data
- Update DNS records if applicable
- Remove from load balancers
- Deregister from monitoring systems

---

## Troubleshooting Guide

### Cannot Connect via SSH

**Symptoms:** Connection timeout, connection refused, or authentication failures

**Solutions:**

1. Verify instance is running: `aws ec2 describe-instances --instance-ids i-0abcd1234efgh5678`
2. Check security group allows SSH from your IP:

   ```bash
   # Get your current public IP
   curl ifconfig.me

   # Verify it matches the security group rule (203.0.113.25/32)
   # If changed, update security group:
   aws ec2 authorize-security-group-ingress \
     --group-id sg-0abc123def456789 \
     --protocol tcp --port 22 \
     --cidr $(curl -s ifconfig.me)/32
   ```

3. Verify key file permissions: `ls -l company-website-prod-key.pem` (should be 400)
4. Try verbose SSH output: `ssh -vvv -i company-website-prod-key.pem ec2-user@54.198.123.45`
5. Use Session Manager as alternative: `aws ssm start-session --target i-0abcd1234efgh5678`

### Status Check Failures

**System Status Check Failed:**

- AWS infrastructure issue
- Wait a few minutes and retry
- If persistent, stop and start instance (not reboot)
- Contact AWS Support if issue continues

**Instance Status Check Failed:**

- Operating system issue
- Check console output: `aws ec2 get-console-output --instance-id i-0abcd1234efgh5678`
- Verify disk is not full
- Check for kernel panics or OS errors
- May require instance restart or recovery

### High CPU Utilization

**Symptoms:** Slow performance, CPU metrics above 80%

**Investigation:**

```bash
# SSH into instance
ssh -i company-website-prod-key.pem ec2-user@54.198.123.45

# Check current CPU usage
top

# Identify CPU-intensive processes
ps aux --sort=-%cpu | head

# Check for background updates
sudo systemctl status dnf-automatic

# Monitor over time
watch -n 5 'top -b -n 1 | head -20'
```

**Solutions:**

- Stop unnecessary processes
- Optimize application code
- Scale vertically (larger instance type)
- Scale horizontally (multiple instances + load balancer)
- Configure t3 unlimited mode if hitting burst limits

### Disk Space Issues

**Symptoms:** Application errors, cannot write files

**Investigation:**

```bash
# Check disk usage
df -h

# Find large directories
sudo du -h / | sort -h | tail -20

# Find large files
sudo find / -type f -size +100M 2>/dev/null
```

**Solutions:**

- Delete unnecessary files and logs
- Rotate and compress old logs
- Increase EBS volume size:

  ```bash
  # Modify volume size (online, no downtime)
  aws ec2 modify-volume --volume-id vol-0123456789abcdef0 --size 40

  # After modification, extend filesystem
  sudo growpart /dev/xvda 1
  sudo resize2fs /dev/xvda1
  ```

### Network Connectivity Issues

**Symptoms:** Cannot access internet, cannot reach AWS services

**Investigation:**

```bash
# Test internet connectivity
ping -c 3 8.8.8.8

# Test DNS resolution
nslookup google.com

# Test AWS service connectivity
curl https://s3.amazonaws.com

# Check routing
ip route show

# Check network interfaces
ip addr show
```

**Solutions:**

- Verify subnet has route to internet gateway (public) or NAT gateway (private)
- Check Network ACLs allow traffic
- Verify security group outbound rules
- Ensure DNS resolution is working
- Check for IP address conflicts

### Application Not Accessible

**Symptoms:** Cannot access web application from browser

**Investigation:**

```bash
# Check web server is running
sudo systemctl status nginx  # or httpd

# Verify port is listening
sudo netstat -tlnp | grep :80
sudo netstat -tlnp | grep :443

# Test locally
curl http://localhost
curl https://localhost

# Check firewall
sudo firewall-cmd --list-all

# Check logs
sudo tail -f /var/log/nginx/error.log
```

**Solutions:**

- Start web server: `sudo systemctl start nginx`
- Verify security group allows HTTP/HTTPS
- Check application configuration
- Verify SSL certificate (for HTTPS)
- Check DNS records point to correct IP

---

## Best Practices and Recommendations

### Security

- ✓ Minimize security group rules (least privilege)
- ✓ Never expose databases to public internet
- ✓ Use IMDSv2 for instance metadata (already configured)
- ✓ Enable termination protection for production
- ✓ Rotate SSH keys regularly
- ✓ Use Systems Manager Session Manager to avoid SSH keys
- ✓ Enable CloudTrail for API audit logging
- ✓ Implement AWS Config for compliance monitoring
- ✓ Use AWS Secrets Manager for sensitive data

### Reliability

- ✓ Create regular backups (AMIs and EBS snapshots)
- ✓ Deploy across multiple AZs for high availability
- ✓ Use Auto Scaling for automatic recovery
- ✓ Implement health checks and monitoring
- ✓ Set up CloudWatch alarms for critical metrics
- ✓ Test recovery procedures regularly
- ✓ Document runbooks for common incidents

### Cost Optimization

- ✓ Right-size instances based on actual usage
- ✓ Stop instances when not in use (dev/test)
- ✓ Use Reserved Instances or Savings Plans for steady workloads
- ✓ Clean up unused snapshots and AMIs
- ✓ Use gp3 volumes instead of gp2
- ✓ Set up AWS Budgets and alerts
- ✓ Review AWS Cost Explorer regularly

### Performance

- ✓ Choose appropriate instance type for workload
- ✓ Use enhanced networking when available
- ✓ Implement caching (application and CDN)
- ✓ Optimize application code and database queries
- ✓ Use EBS-optimized instances for I/O intensive workloads
- ✓ Monitor and act on CloudWatch metrics
- ✓ Consider Graviton processors (t4g) for better price-performance

---

## Next Steps

1. **Connect to Instance:** Use SSH or Session Manager to access the instance
2. **Install Application:** Set up your web server, application, and dependencies
3. **Configure Security:** Complete the security hardening checklist
4. **Set Up Monitoring:** Create CloudWatch alarms and configure logs
5. **Enable Backups:** Configure AWS Backup or snapshot schedules
6. **Test Application:** Verify your application works correctly
7. **Update DNS:** Point your domain to the instance public IP (if applicable)
8. **Document:** Add instance details to your infrastructure documentation
9. **Review Costs:** Monitor actual costs vs. estimates
10. **Plan for Scale:** Consider load balancing and auto scaling for production

---

## Summary

Successfully launched and configured EC2 instance `i-0abcd1234efgh5678` (company-website-prod) in us-east-1. The instance is running with secure, cost-efficient settings following AWS best practices. Complete the post-launch tasks above to finalize your setup and begin using the instance.

**Quick Reference:**

- Instance ID: i-0abcd1234efgh5678
- Public IP: 54.198.123.45
- SSH: `ssh -i company-website-prod-key.pem ec2-user@54.198.123.45`
- Console: https://console.aws.amazon.com/ec2/v2/home?region=us-east-1#Instances:instanceId=i-0abcd1234efgh5678
- Estimated Monthly Cost: $16.92

---

*Report generated by ec2-instance-launch-script on 2025-10-14 15:30:45 UTC*

```

## Troubleshooting

### Insufficient Instance Capacity

**Symptoms:** Launch fails with "InsufficientInstanceCapacity" error

**Solutions:**
- Try a different availability zone within the same region
- Try a different instance type (e.g., t3a instead of t3)
- Wait a few minutes and retry
- Consider using different instance family (m6i, c6i, r6i)
- Request a service quota increase if consistently hitting limits

### VPC Limit Reached

**Symptoms:** Cannot launch instance, VPC-related errors

**Solutions:**
- Use existing VPC instead of creating new one
- Delete unused VPCs if at limit (default 5 per region)
- Request VPC limit increase through AWS Support
- Consolidate resources into fewer VPCs

### AMI Not Available

**Symptoms:** AMI ID not found or architecture mismatch

**Solutions:**
- Verify AMI ID is correct for the region
- Check AMI is not deprecated or deregistered
- Ensure AMI architecture matches instance type (x86_64 vs arm64)
- Query for the latest AMI that matches the selected OS (e.g., Amazon Linux 2023 via `describe-images`, Ubuntu via SSM Parameter Store)
- Consider using AWS Systems Manager Parameter Store for latest AMI IDs

### Security Group Errors

**Symptoms:** Cannot create security group or rules

**Solutions:**
- Check security group limit (default 2,500 per VPC)
- Verify VPC ID is correct
- Ensure CIDR blocks are valid format
- Check for duplicate rules
- Verify IAM permissions allow security group operations

### IAM Role Creation Failures

**Symptoms:** Cannot create IAM role or attach policies

**Solutions:**
- Verify IAM permissions to create roles
- Check role name doesn't conflict with existing role
- Ensure trust policy is valid JSON
- Verify policy ARNs are correct
- Wait for eventual consistency (IAM can take 10-15 seconds)
- Check account limits for IAM roles

### Instance Immediately Terminates

**Symptoms:** Instance launches but immediately transitions to "terminated"

**Solutions:**
- Check console output for errors: `aws ec2 get-console-output`
- Verify EBS volume size is sufficient for AMI
- Check AMI is not corrupted
- Ensure instance type is available in selected AZ
- Verify subnet has available IP addresses
- Check user data script doesn't cause failure

### Cannot Assign Public IP

**Symptoms:** Public IP not assigned despite configuration

**Solutions:**
- Verify subnet is configured as public subnet
- Check subnet has "Auto-assign public IPv4 address" enabled
- Ensure route table has route to internet gateway
- Launch in different subnet if current subnet is private
- Use Elastic IP as alternative

### Key Pair Issues

**Symptoms:** Cannot create or use key pair

**Solutions:**
- Check key pair name doesn't already exist
- Verify key pair limit (default 5,000 per region)
- Ensure key file has correct permissions (400)
- Try creating key pair manually in AWS console
- Use Session Manager as alternative to SSH

### Termination Protection Conflicts

**Symptoms:** Cannot modify or terminate instance

**Solutions:**
- Disable termination protection first:
  ```bash
  aws ec2 modify-instance-attribute \
    --instance-id ${instance_id} \
    --no-disable-api-termination
  ```

- Verify IAM permissions allow termination protection changes
- Check for SCPs (Service Control Policies) blocking changes

### Cost Higher Than Expected

**Symptoms:** Actual costs exceed estimates

**Solutions:**

- Review CloudWatch detailed monitoring charges ($0.14/instance)
- Check data transfer costs (especially cross-region)
- Verify EBS volume type and size
- Monitor for unexpected snapshots
- Check for elastic IP charges when instance stopped
- Review AWS Cost Explorer for breakdown
- Set up AWS Budgets for cost alerts
