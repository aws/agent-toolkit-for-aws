# Create EFS File System and Mount on EC2

## Overview

This SOP provides a systematic approach to create an encrypted Amazon EFS file system and mount it on an EC2 instance.

## Parameters

- **vpc_id** (required): The VPC ID where resources will be created
- **subnet_id** (required): The subnet ID for the EC2 instance and EFS mount target
- **use_private_subnets** (required): Whether to use private subnets (true) or public subnets (false)
- **instance_type** (optional, default: "t3.micro"): The EC2 instance type
- **aws_region** (optional, default: "us-west-2"): The AWS region where resources will be created
- **file_system_name** (optional, default: "EFS-Walkthrough"): The name tag for the EFS file system

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods including:
  - Direct input: Values provided directly in the conversation
  - Configuration files: JSON or YAML configuration files
- You MUST validate that vpc_id follows AWS VPC ID format (vpc-xxxxxxxx)
- You MUST validate that subnet_id follows AWS subnet ID format (subnet-xxxxxxxx)
- You MUST confirm successful acquisition of all parameters before proceeding

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context:
  - call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort
- You MUST verify AWS CLI is properly configured with this command:

  ```
  aws sts get-caller-identity
  ```

### 2. Validate VPC Configuration

Validate VPC settings and configure connectivity method based on use_private_subnets parameter.

**Constraints:**

- You MUST validate VPC DNS settings if use_private_subnets is true:

  ```
  aws ec2 describe-vpc-attribute --vpc-id ${vpc_id} --attribute enableDnsHostnames
  aws ec2 describe-vpc-attribute --vpc-id ${vpc_id} --attribute enableDnsSupport
  ```

- You MUST ensure both DNS hostnames and DNS support are enabled for VPC endpoints when use_private_subnets is true
- You MUST determine subnet type by checking route table for internet gateway:

  ```
  aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=${subnet_id} --query "RouteTables[0].Routes[?GatewayId!=null && starts_with(GatewayId, 'igw-')]"
  ```

- If use_private_subnets is false and no internet gateway route exists, you MUST inform the user that the subnet lacks internet access (no IGW route) and cannot function as a public subnet. Recommend either attaching an internet gateway or switching to private subnets with VPC endpoints.
- You MUST use the use_private_subnets parameter to determine SSM connectivity method
- You MUST inform user of chosen SSM connectivity method

### 3. Create IAM Role for EC2 SSM Access

Create an IAM role that allows the EC2 instance to be managed by Systems Manager.

**Constraints:**

- You MUST check if role already exists before creating:

  ```
  aws iam get-role --role-name EFS-EC2-SSM-Role
  ```

- You MUST create an IAM role named "EFS-EC2-SSM-Role" with EC2 service trust policy only if it doesn't exist
- You MUST attach the AWS managed policy "AmazonSSMManagedInstanceCore" to the role
- You MUST create an instance profile for the role only if it doesn't exist
- You MUST save the instance profile ARN for EC2 launch
- You MUST handle cases where the role already exists gracefully

### 4. Create Security Groups

Create two security groups: one for the EC2 instance and one for the EFS mount target.

**Constraints:**

- You MUST check if security groups already exist before creating
- You MUST create an EC2 security group named "efs-walkthrough-ec2-sg" with description "EFS walkthrough, SG for EC2 instance (SSM access)"
- You MUST create an EFS security group named "efs-walkthrough-mt-sg" with description "EFS walkthrough, SG for mount target"
- You MUST NOT add SSH (port 22) rules since SSM Session Manager doesn't require them
- You MUST add HTTPS outbound (port 443) to EC2 security group for SSM communication
- You MUST save the security group IDs for use in subsequent steps

### 5. Configure Security Group Rules

Add inbound rules to allow NFS access to EFS and conditional VPC endpoint access.

**Constraints:**

- You MUST add NFS (port 2049) access from the EC2 security group to the EFS security group
- You MUST add HTTPS outbound (port 443) access from EC2 security group to 0.0.0.0/0 for SSM communication
- If use_private_subnets is true, you MUST add HTTPS inbound (port 443) from EC2 security group to itself for VPC endpoint communication
- You MUST use the security group IDs obtained from the previous step
- You MUST NOT add SSH access rules

### 6. Create VPC Endpoints (Private Subnets Only)

Create VPC endpoints for SSM communication if instance is in private subnet.

**Constraints:**

- You MUST only create VPC endpoints if use_private_subnets is true
- You MUST create endpoints for: ssm, ssmmessages, ec2messages
- You MUST use the EFS security group for VPC endpoints
- You MUST wait for endpoints to be available before proceeding
- You MUST skip this step entirely for public subnets

### 7. Launch EC2 Instance

Launch an EC2 instance in the specified subnet with appropriate IP assignment based on subnet type.

**Constraints:**

- You MUST launch the instance with the specified instance type
- You MUST use the EC2 security group created in step 4
- You MUST attach the IAM instance profile created in step 3
- You MUST use Amazon Linux 2023 AMI (has SSM agent pre-installed)
- If use_private_subnets is false (public subnet), you MUST use --associate-public-ip-address
- If use_private_subnets is true (private subnet), you MUST NOT assign public IP
- You MUST save the instance ID for later use
- You MUST wait for the instance to be in "running" state before proceeding
- You MUST NOT specify a key pair since SSM access doesn't require it

### 8. Create EFS File System

Create an encrypted EFS file system with lifecycle management.

**Constraints:**

- You MUST check if file system with same name already exists
- You MUST create the file system with encryption enabled
- You MUST use a unique creation token (e.g., "FileSystemForWalkthrough" + timestamp)
- You MUST add a Name tag with the specified file_system_name
- You MUST save the file system ID for use in subsequent steps
- You MUST enable lifecycle management to transition files to IA after 30 days

### 9. Create EFS Mount Target

Create a mount target in the specified subnet with the EFS security group.

**Constraints:**

- You MUST create the mount target in the same subnet as the EC2 instance
- You MUST use the EFS security group created in step 4
- You MUST wait for the mount target to be available before proceeding
- You MUST save the mount target DNS name for mounting

### 10. Wait for SSM Agent Registration

Ensure the EC2 instance is registered with Systems Manager with enhanced validation.

**Constraints:**

- You MUST wait for the instance to appear in SSM managed instances
- You MUST check SSM agent status using: `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=${instance_id}"`
- You MUST verify PingStatus is "Online" before proceeding
- You MUST wait up to 10 minutes for registration to complete (increased from 5 minutes)
- You MUST check every 30 seconds and provide progress updates
- You MUST inform the user if SSM registration fails and provide troubleshooting steps based on subnet type

### 11. Install NFS Utils via SSM

Use Systems Manager to install NFS utilities on the EC2 instance.

**Constraints:**

- You MUST use the full command: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["sudo yum update -y && sudo yum install -y nfs-utils"]'`
- You MUST wait for command completion and check execution status
- You MUST handle command failures gracefully

### 12. Mount EFS via SSM

Use Systems Manager to create mount point and mount the EFS file system.

**Constraints:**

- You MUST use the full command to create mount point: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["sudo mkdir -p /mnt/efs"]'`
- You MUST use the full command to mount EFS: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["sudo mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 ${efs_dns_name}:/ /mnt/efs"]'`
- You MUST verify mount success by checking /proc/mounts using: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["cat /proc/mounts | grep efs"]'`
- You MUST handle mount failures and provide troubleshooting guidance

### 13. Test EFS Setup via SSM

Verify that the EFS file system is properly mounted and functional using SSM commands.

**Constraints:**

- You MUST test write access by creating a test file using: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["sudo touch /mnt/efs/test-file.txt"]'`
- You MUST test read access by listing files using: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["ls -la /mnt/efs/"]'`
- You MUST verify the mount persists by checking /proc/mounts using: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["cat /proc/mounts | grep efs"]'`
- You MUST provide instructions for making the mount permanent via /etc/fstab using: `aws ssm send-command --instance-ids ${instance_id} --document-name "AWS-RunShellScript" --parameters 'commands=["echo \"${efs_dns_name}:/ /mnt/efs nfs4 nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 0 0\" | sudo tee -a /etc/fstab"]'`

### 14. Provide SSM Access Instructions

Provide instructions for ongoing access to the EC2 instance via Session Manager.

**Constraints:**

- You MUST provide the Session Manager connection command: `aws ssm start-session --target ${instance_id}`
- You MUST explain how to access the instance via AWS Console Session Manager
- You MUST provide examples of running commands via SSM send-command
- You MUST explain the benefits of SSM over SSH (no keys, audit trail, IAM-based access)

### 15. Cleanup Instructions

Provide instructions for cleaning up all created resources.

**Constraints:**

- You MUST provide commands to terminate the EC2 instance
- You MUST provide commands to delete the EFS mount target
- You MUST provide commands to delete the EFS file system
- You MUST provide commands to delete VPC endpoints (if created)
- You MUST provide commands to delete the security groups
- You MUST provide commands to delete the IAM role and instance profile
- You MUST warn that cleanup should be done in the correct order to avoid dependency errors
- You SHOULD remind the user to unmount the EFS before cleanup

## Examples

### Example Input

```
vpc_id: vpc-12345678
subnet_id: subnet-87654321
use_private_subnets: false
aws_region: us-west-2
```

## Troubleshooting

### VPC DNS Configuration Issues
If VPC endpoint creation fails:

- Verify VPC has DNS hostnames enabled: `aws ec2 describe-vpc-attribute --vpc-id ${vpc_id} --attribute enableDnsHostnames`
- Verify VPC has DNS support enabled: `aws ec2 describe-vpc-attribute --vpc-id ${vpc_id} --attribute enableDnsSupport`
- Both must be "true" for VPC endpoints to work properly

### SSM Connectivity Issues by Subnet Type

#### Public Subnet Issues
If SSM registration fails in public subnet:

- Verify instance has public IP assigned
- Check security group allows HTTPS outbound (port 443) to 0.0.0.0/0
- Ensure subnet route table has internet gateway route (0.0.0.0/0 -> igw-xxxxx)
- Do NOT create VPC endpoints for public subnets

#### Private Subnet Issues  
If SSM registration fails in private subnet:

- Verify VPC endpoints are created and available
- Check security group allows HTTPS inbound (port 443) from itself for VPC endpoint communication
- Ensure VPC has DNS hostnames and DNS support enabled
- Verify subnet route table has NAT gateway route for internet access (if needed)

### Mount Target Not Available
If the mount target creation fails or takes too long, check that the subnet has available IP addresses and the security group allows NFS traffic.

### SSM Agent Not Registered
Enhanced troubleshooting based on subnet type:

#### For Public Subnets:

- Verify the instance has a public IP address
- Check that the security group allows HTTPS outbound (port 443) to 0.0.0.0/0
- Ensure the subnet route table has an internet gateway route
- Verify the IAM role has AmazonSSMManagedInstanceCore policy

#### For Private Subnets:

- Verify VPC endpoints for SSM are created and available
- Check that VPC DNS settings are enabled
- Ensure security group allows HTTPS inbound from itself (port 443)
- Verify the IAM role has AmazonSSMManagedInstanceCore policy
- Wait up to 10 minutes for initial registration

### SSM Commands Failing
If SSM send-command fails:

- Check the command execution status and output using get-command-invocation
- Verify the instance PingStatus is "Online" in describe-instance-information
- Ensure the commands have proper syntax and permissions
- For private subnets, verify VPC endpoints are functioning

### Mount Command Fails
If the mount command fails, verify that:

- NFS utilities are installed (nfs-utils package)
- The mount target is in "available" state
- The security group allows NFS traffic (port 2049)
- The mount target DNS name is correct

### Permission Denied on EFS
If you get permission denied when writing to EFS, check that:

- The mount point directory has correct permissions
- You're not trying to write as root without proper EFS access point configuration

### Resource Already Exists Errors
The SOP handles existing resources gracefully:

- IAM roles and instance profiles are checked before creation
- Security groups are validated before creation
- EFS file systems are checked for name conflicts
- All existence checks prevent duplicate resource errors
