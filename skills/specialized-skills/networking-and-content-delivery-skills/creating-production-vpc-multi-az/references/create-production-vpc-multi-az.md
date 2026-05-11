# Create Production-Ready VPC Across Multiple Availability Zones

## Overview
Creates a production-ready VPC infrastructure with public and private subnets distributed across multiple Availability Zones, including internet gateway, NAT gateways, route tables, and security groups following AWS Well-Architected principles with automatic CIDR planning and DNS resolution.

## Parameters
vpc_name (required): Name for the VPC and associated resources
vpc_cidr (optional, default: "10.0.0.0/16"): CIDR block for the VPC
availability_zones (optional, default: 3): Number of Availability Zones to use (minimum 2, maximum 6)
environment (required): Environment tag for resources (e.g., "production", "staging", "development")
region (required): AWS region where the VPC will be created
allowed_web_cidrs (required): Comma-separated CIDR blocks allowed web access (e.g., "203.0.113.0/24,198.51.100.0/24"). You SHOULD recommend specific CIDR ranges over 0.0.0.0/0, but allow 0.0.0.0/0 if the user explicitly requests it.
enable_ssh_access (optional, default: false): Enable SSH access security group
ssh_allowed_cidrs (optional, default: "10.0.0.0/8"): CIDR blocks allowed SSH access when enabled

## Steps

### 1. Verify Dependencies
Check for required tools and warn the user if any are missing.

Constraints:

- You MUST verify the following tools are available in your context:
  - call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects, consume resources unnecessarily, or trigger actions before the user is ready
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort

### 2. Validate Region and Get Available Availability Zones
Validate the specified region and retrieve available Availability Zones for subnet distribution.

Constraints:

- You MUST inform the customer that you are validating the AWS region and retrieving available Availability Zones
- You MUST use call_aws to execute: `aws ec2 describe-availability-zones --region {region} --state available`
- You MUST verify that the region has at least 2 available Availability Zones
- You MUST select the first N Availability Zones based on the availability_zones parameter
- You MUST NOT proceed if fewer than 2 Availability Zones are available

### 3. Create VPC with DNS Support
Create the main VPC with DNS hostname and resolution enabled for production readiness.

Constraints:

- You MUST inform the customer that you are creating the VPC with DNS support enabled
- You MUST use call_aws to execute: `aws ec2 create-vpc --cidr-block {vpc_cidr} --region {region}`
- You MUST capture the VPC ID from the response
- You MUST enable DNS hostnames using: `aws ec2 modify-vpc-attribute --vpc-id {vpc_id} --enable-dns-hostnames --region {region}`
- You MUST enable DNS resolution using: `aws ec2 modify-vpc-attribute --vpc-id {vpc_id} --enable-dns-support --region {region}`
- You MUST tag the VPC using: `aws ec2 create-tags --resources {vpc_id} --tags Key=Name,Value={vpc_name} Key=Environment,Value={environment} --region {region}`

### 4. Create Internet Gateway
Create and attach an Internet Gateway for public subnet internet access.

Constraints:

- You MUST inform the customer that you are creating and attaching an Internet Gateway
- You MUST use call_aws to execute: `aws ec2 create-internet-gateway --region {region}`
- You MUST capture the Internet Gateway ID from the response
- You MUST attach it to the VPC using: `aws ec2 attach-internet-gateway --internet-gateway-id {igw_id} --vpc-id {vpc_id} --region {region}`
- You MUST tag the Internet Gateway using: `aws ec2 create-tags --resources {igw_id} --tags Key=Name,Value={vpc_name}-igw Key=Environment,Value={environment} --region {region}`

### 5. Calculate and Create Public Subnets
Create public subnets across the selected Availability Zones with automatic CIDR calculation.

Constraints:

- You MUST inform the customer that you are creating public subnets across multiple Availability Zones
- You MUST calculate subnet CIDRs automatically by dividing the VPC CIDR appropriately
- For each selected Availability Zone, You MUST create a public subnet using: `aws ec2 create-subnet --vpc-id {vpc_id} --cidr-block {calculated_cidr} --availability-zone {az} --region {region}`
- You MUST enable auto-assign public IP for public subnets using: `aws ec2 modify-subnet-attribute --subnet-id {subnet_id} --map-public-ip-on-launch --region {region}`
- You MUST tag each public subnet using: `aws ec2 create-tags --resources {subnet_id} --tags Key=Name,Value={vpc_name}-public-{az} Key=Environment,Value={environment} Key=Type,Value=Public --region {region}`
- You MUST store all public subnet IDs for later use

### 6. Calculate and Create Private Subnets
Create private subnets across the selected Availability Zones for backend resources.

Constraints:

- You MUST inform the customer that you are creating private subnets for backend resources
- You MUST calculate private subnet CIDRs to avoid overlap with public subnets
- For each selected Availability Zone, You MUST create a private subnet using: `aws ec2 create-subnet --vpc-id {vpc_id} --cidr-block {calculated_private_cidr} --availability-zone {az} --region {region}`
- You MUST tag each private subnet using: `aws ec2 create-tags --resources {private_subnet_id} --tags Key=Name,Value={vpc_name}-private-{az} Key=Environment,Value={environment} Key=Type,Value=Private --region {region}`
- You MUST store all private subnet IDs for later use

### 7. Create NAT Gateways for High Availability
Create NAT Gateways in each public subnet for outbound internet access from private subnets.

Constraints:

- You MUST inform the customer that you are creating NAT Gateways for high availability outbound internet access
- For each public subnet, You MUST first allocate an Elastic IP using: `aws ec2 allocate-address --domain vpc --region {region}`
- You MUST create a NAT Gateway in each public subnet using: `aws ec2 create-nat-gateway --subnet-id {public_subnet_id} --allocation-id {eip_allocation_id} --region {region}`
- You MUST tag each NAT Gateway using: `aws ec2 create-tags --resources {nat_gateway_id} --tags Key=Name,Value={vpc_name}-nat-{az} Key=Environment,Value={environment} --region {region}`
- You MUST wait for NAT Gateways to become available before proceeding
- You MUST store all NAT Gateway IDs for route table configuration

### 8. Create and Configure Route Tables
Create and configure route tables for public and private subnets with appropriate routes.

Constraints:

- You MUST inform the customer that you are creating and configuring route tables
- You MUST create a public route table using: `aws ec2 create-route-table --vpc-id {vpc_id} --region {region}`
- You MUST add a route to the Internet Gateway using: `aws ec2 create-route --route-table-id {public_rt_id} --destination-cidr-block 0.0.0.0/0 --gateway-id {igw_id} --region {region}`
- You MUST tag the public route table using: `aws ec2 create-tags --resources {public_rt_id} --tags Key=Name,Value={vpc_name}-public-rt Key=Environment,Value={environment} --region {region}`
- For each public subnet, You MUST associate it with the public route table using: `aws ec2 associate-route-table --subnet-id {public_subnet_id} --route-table-id {public_rt_id} --region {region}`
- For each private subnet, You MUST create a separate route table using: `aws ec2 create-route-table --vpc-id {vpc_id} --region {region}`
- You MUST add a route to the corresponding NAT Gateway using: `aws ec2 create-route --route-table-id {private_rt_id} --destination-cidr-block 0.0.0.0/0 --nat-gateway-id {nat_gateway_id} --region {region}`
- You MUST tag each private route table and associate with the corresponding private subnet

### 9. Create Security Groups
Create default security groups following security best practices.

Constraints:

- You MUST inform the customer that you are creating security groups following security best practices
- You MUST create a web tier security group using: `aws ec2 create-security-group --group-name {vpc_name}-web-sg --description "Web tier security group for {vpc_name}" --vpc-id {vpc_id} --region {region}`
- You MUST add HTTP and HTTPS inbound rules for each CIDR in allowed_web_cidrs using: `aws ec2 authorize-security-group-ingress --group-id {web_sg_id} --protocol tcp --port 80 --cidr {cidr_block} --region {region}` and `aws ec2 authorize-security-group-ingress --group-id {web_sg_id} --protocol tcp --port 443 --cidr {cidr_block} --region {region}`
- If 0.0.0.0/0 is included in allowed_web_cidrs, You MUST warn the user that this opens web access to the entire internet and recommend specific CIDR ranges for production workloads, but proceed if the user explicitly requested it
- You MUST create an application tier security group using: `aws ec2 create-security-group --group-name {vpc_name}-app-sg --description "Application tier security group for {vpc_name}" --vpc-id {vpc_id} --region {region}`
- You MUST create a database tier security group using: `aws ec2 create-security-group --group-name {vpc_name}-db-sg --description "Database tier security group for {vpc_name}" --vpc-id {vpc_id} --region {region}`
- If enable_ssh_access is true, You MUST create SSH security group using: `aws ec2 create-security-group --group-name {vpc_name}-ssh-sg --description "SSH access security group for {vpc_name}" --vpc-id {vpc_id} --region {region}`
- If SSH security group created, You MUST add SSH rules for each CIDR in ssh_allowed_cidrs using: `aws ec2 authorize-security-group-ingress --group-id {ssh_sg_id} --protocol tcp --port 22 --cidr {ssh_cidr_block} --region {region}`
- You MUST configure security group rules to allow communication between tiers only as needed
- You MUST tag all security groups appropriately

### 10. Enable VPC Flow Logs
Enable VPC Flow Logs to CloudWatch Logs for network traffic visibility and security monitoring.

Constraints:

- You MUST inform the customer that you are enabling VPC Flow Logs for network traffic monitoring
- You MUST get the AWS account ID: `aws sts get-caller-identity --region {region}` and capture the Account field
- You MUST create an IAM role for VPC Flow Logs with a trust policy for `vpc-flow-logs.amazonaws.com`:

  ```
  aws iam create-role --role-name {vpc_name}-flow-logs-role --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"vpc-flow-logs.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
  ```

- You MUST create and attach an inline policy granting CloudWatch Logs permissions:

  ```
  aws iam put-role-policy --role-name {vpc_name}-flow-logs-role --policy-name {vpc_name}-flow-logs-policy --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["logs:CreateLogStream","logs:PutLogEvents","logs:DescribeLogStreams"],"Resource":"arn:aws:logs:{region}:{account_id}:log-group:/vpc/{vpc_name}/flow-logs:*"},{"Effect":"Allow","Action":"logs:DescribeLogGroups","Resource":"*"}]}'
  ```

- You MUST create a CloudWatch Logs log group:

  ```
  aws logs create-log-group --log-group-name /vpc/{vpc_name}/flow-logs --region {region}
  ```

- You MUST set a retention policy on the log group:

  ```
  aws logs put-retention-policy --log-group-name /vpc/{vpc_name}/flow-logs --retention-in-days 90 --region {region}
  ```

- You MUST wait approximately 10-15 seconds for IAM propagation before creating the flow log
- You MUST create the VPC Flow Log:

  ```
  aws ec2 create-flow-logs --resource-type VPC --resource-ids {vpc_id} --traffic-type ALL --log-destination-type cloud-watch-logs --log-group-name /vpc/{vpc_name}/flow-logs --deliver-logs-permission-arn arn:aws:iam::{account_id}:role/{vpc_name}-flow-logs-role --tag-specifications 'ResourceType=vpc-flow-log,Tags=[{Key=Name,Value={vpc_name}-flow-log},{Key=Environment,Value={environment}},{Key=VPC,Value={vpc_name}}]' --region {region}
  ```

- You MUST verify the flow log was created: `aws ec2 describe-flow-logs --filter "Name=resource-id,Values={vpc_id}" --region {region}`
- You MUST tag the log group: `aws logs tag-resource --resource-arn arn:aws:logs:{region}:{account_id}:log-group:/vpc/{vpc_name}/flow-logs --tags Environment={environment},VPC={vpc_name} --region {region}`
- You MUST tag the IAM role: `aws iam tag-role --role-name {vpc_name}-flow-logs-role --tags Key=Environment,Value={environment} Key=VPC,Value={vpc_name}`

### 11. Validate VPC Configuration
Validate the created VPC infrastructure to ensure all components are properly configured.

Constraints:

- You MUST inform the customer that you are validating the VPC infrastructure configuration
- You MUST verify VPC creation using: `aws ec2 describe-vpcs --vpc-ids {vpc_id} --region {region}`
- You MUST verify all subnets using: `aws ec2 describe-subnets --filters "Name=vpc-id,Values={vpc_id}" --region {region}`
- You MUST verify route tables using: `aws ec2 describe-route-tables --filters "Name=vpc-id,Values={vpc_id}" --region {region}`
- You MUST verify NAT Gateways using: `aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values={vpc_id}" --region {region}`
- You MUST verify Internet Gateway attachment using: `aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values={vpc_id}" --region {region}`
- You MUST confirm DNS resolution and hostname support are enabled
- You MUST verify VPC Flow Logs are active using: `aws ec2 describe-flow-logs --filter "Name=resource-id,Values={vpc_id}" --region {region}`

### 12. Generate Infrastructure Summary
Provide a comprehensive summary of the created infrastructure.

Constraints:

- You MUST inform the customer that you are generating a summary of the created infrastructure
- You MUST provide the VPC ID, CIDR block, and region
- You MUST list all created subnets with their IDs, CIDR blocks, Availability Zones, and types (public/private)
- You MUST list all NAT Gateway IDs and their associated Elastic IP addresses
- You MUST provide the Internet Gateway ID
- You MUST list all security group IDs and names
- You MUST list the VPC Flow Log ID and CloudWatch Logs log group name
- You MUST include next steps for deploying resources into the VPC
- You SHOULD provide estimated monthly costs for the NAT Gateways and Elastic IPs

## Constraints for All Steps

- You MUST NEVER prompt for passwords as this script uses SecretsManager managed passwords where applicable
- You MUST inform the customer about each step being performed and why the call_aws tool is being called
- You MUST follow AWS Well-Architected Framework principles including security, reliability, performance efficiency, cost optimization, and operational excellence
- You MUST use consistent naming conventions with the vpc_name parameter as prefix
- You MUST ensure all resources are properly tagged for cost allocation and management
- You MUST handle errors gracefully and provide clear error messages
- You SHOULD implement resource limits to prevent accidental over-provisioning

Examples of AWS CLI commands that will be used:

- `aws ec2 describe-availability-zones --region {region} --state available`
- `aws ec2 create-vpc --cidr-block {vpc_cidr} --region {region}`
- `aws ec2 modify-vpc-attribute --vpc-id {vpc_id} --enable-dns-hostnames --region {region}`
- `aws ec2 create-internet-gateway --region {region}`
- `aws ec2 create-subnet --vpc-id {vpc_id} --cidr-block {cidr} --availability-zone {az} --region {region}`
- `aws ec2 allocate-address --domain vpc --region {region}`
- `aws ec2 create-nat-gateway --subnet-id {subnet_id} --allocation-id {eip_id} --region {region}`
- `aws ec2 create-route-table --vpc-id {vpc_id} --region {region}`
- `aws ec2 create-security-group --group-name {name} --description {desc} --vpc-id {vpc_id} --region {region}`
- `aws ec2 create-tags --resources {resource_id} --tags Key=Name,Value={name} --region {region}`
