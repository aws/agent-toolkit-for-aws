# Lambda VPC Internet Access Setup

## Overview

This SOP guides you through enabling internet access for a Lambda function that currently exists in a VPC subnet without internet access. Lambda functions in VPC cannot receive public IP addresses, so the only way to provide internet access is through NAT Gateway infrastructure that routes traffic from private subnets to the internet.

## Parameters

- **lambda_function_name** (required): The name or ARN of the Lambda function that needs internet access
- **availability_zone** (optional): Specific AZ for resource creation, if not provided will use the AZ of existing Lambda subnets

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods including:
  - Direct input: Text provided directly in the conversation
  - File path: Path to a local file
  - URL: Link to an internal resource
  - Other methods: You SHOULD be open to other ways the user might want to provide the data
- You MUST use appropriate tools to access content based on the input method
- You MUST confirm successful acquisition of all parameters before proceeding
- You SHOULD save any acquired data to a consistent location for use in subsequent steps

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

### 2. Analyze Current Lambda Configuration

Retrieve and analyze the current Lambda function configuration to understand its VPC setup.

**Constraints:**

- You MUST retrieve the Lambda function configuration using AWS CLI
- You MUST identify the current subnet IDs and security group IDs
- You MUST determine if the current subnets are private or public
- You MUST check the route tables associated with current subnets
- You MUST save the current configuration details for reference

```
# Get Lambda function configuration
aws lambda get-function --function-name <lambda_function_name>

# Check subnet details
aws ec2 describe-subnets --subnet-ids <subnet_id>

# Check route tables for the subnet
aws ec2 describe-route-tables --filters "Name=association.subnet-id,Values=<subnet_id>"
```

### 3. Analyze VPC Network Infrastructure

Examine the VPC's current networking setup to determine what infrastructure needs to be created.

**Constraints:**

- You MUST check for existing Internet Gateway attached to the VPC
- You MUST identify existing public and private subnets
- You MUST examine existing NAT Gateways in the VPC
- You MUST analyze route tables and their associations
- You MUST determine the most appropriate approach based on existing infrastructure

```
# Check all route tables in VPC
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=<vpc_id>"

# Check all subnets in VPC
aws ec2 describe-subnets --filters "Name=vpc-id,Values=<vpc_id>"

# Check for existing Internet Gateway
aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=<vpc_id>"

# Check for existing NAT Gateways
aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=<vpc_id>"
```

### 4. Plan NAT Gateway Implementation

Plan the NAT Gateway setup based on the VPC analysis.

**Constraints:**

- You MUST determine the target availability zone for NAT Gateway placement
- You MUST identify if a public subnet exists in the target AZ or needs to be created
- You MUST check if an Elastic IP is available or needs to be allocated
- You MUST plan the route table updates needed for Lambda's private subnets

### 5. Confirm Infrastructure Changes with User

Present the planned infrastructure changes and estimated costs to the user for explicit approval before creating any resources.

**Constraints:**

- You MUST present a summary of ALL resources that will be created, including:
  - NAT Gateway (high monthly base cost + per-GB data processing charges — refer to AWS NAT Gateway pricing documentation for current rates)
  - Elastic IP (billed for the public IPv4 address whether associated or not, plus additional charges when unassociated — refer to AWS Elastic IP pricing documentation for current rates)
  - Any new subnets or route tables
  - Internet Gateway (if needed)
- You MUST list the target VPC, availability zone, and affected Lambda function
- You MUST wait for explicit user confirmation before proceeding
- You MUST NOT create any billable resources without user approval
- If the user declines, You MUST abort the procedure and suggest alternatives (e.g., VPC endpoints for specific AWS services)

### 6. Create Internet Gateway (if needed)

Create an Internet Gateway if one doesn't exist and attach it to the VPC.

**Constraints:**

- You MUST check if an Internet Gateway already exists for the VPC
- If no Internet Gateway exists, You MUST create one and attach it to the VPC
- You MUST verify the attachment was successful
- You MUST NOT create duplicate Internet Gateways since each VPC can only have one

```
# Create Internet Gateway
aws ec2 create-internet-gateway --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Name,Value=<lambda_function_name>-igw}]"

# Attach Internet Gateway to VPC
aws ec2 attach-internet-gateway --internet-gateway-id <internet_gateway_id> --vpc-id <vpc_id>
```

### 7. Create Public Subnet (if needed)

Create a public subnet for NAT Gateway placement if one doesn't exist.

**Constraints:**

- You MUST check if a public subnet exists in the target AZ
- If no public subnet exists, You MUST create one with appropriate CIDR block
- You MUST create a route table for the public subnet with route to Internet Gateway
- You MUST associate the route table with the public subnet
- You MUST verify the public subnet is properly configured before proceeding

```
# Create public subnet
aws ec2 create-subnet --vpc-id <vpc_id> --cidr-block <public_subnet_cidr> --availability-zone <availability_zone> --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=<lambda_function_name>-public-subnet}]"

# Create route table for public subnet
aws ec2 create-route-table --vpc-id <vpc_id> --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=<lambda_function_name>-public-rt}]"

# Add route to Internet Gateway
aws ec2 create-route --route-table-id <public_route_table_id> --destination-cidr-block 0.0.0.0/0 --gateway-id <internet_gateway_id>

# Associate subnet with route table
aws ec2 associate-route-table --subnet-id <public_subnet_id> --route-table-id <public_route_table_id>
```

### 8. Create NAT Gateway Infrastructure

Create the NAT Gateway and configure routing for Lambda internet access.

**Constraints:**

- You MUST allocate an Elastic IP address for the NAT Gateway
- You MUST create the NAT Gateway in the public subnet
- You MUST create or update route table for Lambda's private subnets to route 0.0.0.0/0 traffic through NAT Gateway
- You MUST associate the updated route table with the Lambda function's subnets
- You MUST verify the NAT Gateway is in "available" state before proceeding

```
# Allocate Elastic IP
aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=<lambda_function_name>-nat-eip}]"

# Create NAT Gateway
aws ec2 create-nat-gateway --subnet-id <public_subnet_id> --allocation-id <elastic_ip_allocation_id>

# Create private route table
aws ec2 create-route-table --vpc-id <vpc_id> --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=<lambda_function_name>-private-rt}]"

# Check NAT Gateway status
aws ec2 describe-nat-gateways --nat-gateway-ids <nat_gateway_id>

# Add route to NAT Gateway
aws ec2 create-route --route-table-id <private_route_table_id> --destination-cidr-block 0.0.0.0/0 --nat-gateway-id <nat_gateway_id>

# Associate private subnet with private route table
aws ec2 associate-route-table --subnet-id <lambda_subnet_id> --route-table-id <private_route_table_id>
```

### 9. Update Security Groups

Ensure security groups allow necessary outbound internet traffic.

**Constraints:**

- You MUST review current security group rules for the Lambda function
- You MUST ensure outbound rules allow HTTPS (port 443) and HTTP (port 80) traffic
- You SHOULD add specific outbound rules rather than allowing all traffic (0.0.0.0/0) for better security
- You MUST NOT modify inbound rules unless specifically requested since this could create security vulnerabilities

```
# Check current security group rules
aws ec2 describe-security-groups --group-ids <security_group_id>

# Add HTTPS outbound rule if needed
aws ec2 authorize-security-group-egress --group-id <security_group_id> --protocol tcp --port 443 --cidr 0.0.0.0/0

# Add HTTP outbound rule if needed
aws ec2 authorize-security-group-egress --group-id <security_group_id> --protocol tcp --port 80 --cidr 0.0.0.0/0
```

## Examples

### Example Security Group Outbound Rules

```json
{
    "IpPermissions": [
        {
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
        },
        {
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
        }
    ]
}
```

## Troubleshooting

### NAT Gateway Not Working
If the NAT Gateway is created but Lambda still cannot access the internet, check that the route table associated with Lambda's subnets has a route to the NAT Gateway for 0.0.0.0/0 destination.

### Lambda Function Timeout
If Lambda function times out when trying to access the internet, verify that security group outbound rules allow the necessary ports and that the NAT Gateway or Internet Gateway is properly configured.

### Network Changes Not Taking Effect
If network changes don't resolve the issue immediately, you should remember that VPC networking changes can take a minute or two to propagate through AWS's infrastructure. Wait up to 1-2 minutes after creating NAT Gateway and updating route tables before testing again.

### Route Table Association Issues
If Lambda still cannot access the internet after NAT Gateway creation, verify that the Lambda function's subnets are associated with the correct route table that has the 0.0.0.0/0 route pointing to the NAT Gateway.
