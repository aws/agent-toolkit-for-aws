# Connect Two VPCs Using VPC Peering

## Overview
This SOP establishes a secure, private network connection between two VPCs using VPC peering. It handles peering creation, route table updates, DNS resolution configuration, and supports both same-region and cross-region peering with comprehensive connectivity validation and security group adjustments.

## Parameters

- **requester_vpc_id** (required): The VPC ID that will initiate the peering connection
- **accepter_vpc_id** (required): The VPC ID that will accept the peering connection
- **requester_region** (optional): The AWS region of the requester VPC. If not provided, uses the default region from AWS configuration
- **accepter_region** (optional): The AWS region of the accepter VPC. If not provided, uses the same region as requester
- **accepter_account_id** (optional): The AWS account ID that owns the accepter VPC. If not provided, assumes same account
- **enable_dns_resolution** (optional, default: true): Whether to enable DNS resolution for the peering connection
- **enable_dns_hostnames** (optional, default: true): Whether to enable DNS hostnames for the peering connection
- **auto_accept** (optional, default: true): Whether to automatically accept the peering connection (only works for same account)

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods for parameters including:
  - Direct input: Values provided directly in the conversation
  - Configuration files: Reading from AWS config or similar files
- You MUST confirm successful acquisition of all required parameters before proceeding
- You SHOULD provide sensible defaults for optional parameters when not specified

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

### 2. Validate VPC Information
Verify that both VPCs exist and gather their CIDR blocks and route table information.

**Constraints:**

- You MUST check if both VPCs exist using `aws ec2 describe-vpcs`
- You MUST retrieve each VPC's CIDR blocks for route configuration
- You MUST identify all route tables associated with each VPC
- You MUST abort the SOP if either VPC does not exist
- You SHOULD display VPC information including CIDR blocks for confirmation
- You MUST check for CIDR block overlaps and warn if found because overlapping CIDR blocks will prevent proper routing

### 3. Create VPC Peering Connection
Create the VPC peering connection between the two VPCs.

**Constraints:**

- You MUST create the peering connection using `aws ec2 create-vpc-peering-connection`
- You MUST specify the requester VPC ID and accepter VPC ID
- You MUST include the accepter_region parameter if different from requester_region
- You MUST include the accepter_account_id parameter if different from current account
- You MUST store the peering connection ID for subsequent steps
- You SHOULD add descriptive tags to the peering connection for identification

### 4. Accept VPC Peering Connection
Accept the peering connection if auto-accept is enabled and conditions allow.

**Constraints:**

- You MUST check if auto_accept is enabled
- You MUST only attempt auto-accept for same-account peering connections because cross-account connections require manual acceptance
- You MUST use `aws ec2 accept-vpc-peering-connection` if auto-accepting
- You MUST switch to the accepter_region parameter if different from requester_region
- You SHOULD inform the user if manual acceptance is required for cross-account connections (when accepter_account_id is different)
- You MUST wait for the peering connection to reach "active" state before proceeding

### 5. Configure DNS Resolution
Enable DNS resolution and hostnames for the peering connection if requested.

**Constraints:**

- You MUST configure DNS settings only if enable_dns_resolution or enable_dns_hostnames is true
- You MUST use `aws ec2 modify-vpc-peering-connection-options` to enable DNS resolution
- You MUST configure DNS options for both the requester and accepter sides
- You MUST handle cross-region DNS configuration by switching between requester_region and accepter_region as needed
- You SHOULD verify DNS settings are applied correctly

### 6. Update Route Tables
Add routes to enable traffic flow between the VPCs through the peering connection.

**Constraints:**

- You MUST add routes to all route tables in both VPCs
- You MUST use `aws ec2 create-route` to add routes pointing to the peering connection
- You MUST add routes for each CIDR block of the peer VPC
- You MUST handle route conflicts by checking existing routes first
- You SHOULD skip adding routes that already exist to avoid errors
- You MUST verify routes are added successfully to all route tables

### 7. Validate Connectivity
Test the peering connection to ensure proper configuration.

**Constraints:**

- You MUST verify the peering connection status is "active"
- You MUST check that routes are properly configured in all route tables
- You MUST validate DNS resolution settings if enabled
- You SHOULD provide guidance on testing connectivity between instances
- You MUST inform the user about security group requirements for instance communication

### 8. Security Group Recommendations
Provide guidance on security group configuration for cross-VPC communication.

**Constraints:**

- You MUST explain that security groups need to be updated to allow cross-VPC traffic
- You MUST provide examples of security group rules for common use cases
- You SHOULD recommend using security group references when possible
- You MUST warn about overly permissive rules that could create security risks
- You SHOULD suggest testing with minimal permissions first

## Examples

### Example Input

```
requester_vpc_id: vpc-12345678
accepter_vpc_id: vpc-87654321
requester_region: us-east-1
accepter_region: us-west-2
enable_dns_resolution: true
auto_accept: true
```

### Example Output

```
VPC Peering Connection Created Successfully:
- Peering Connection ID: pcx-abcdef123456
- Status: active
- Requester VPC: vpc-12345678 (10.0.0.0/16) in us-east-1
- Accepter VPC: vpc-87654321 (10.1.0.0/16) in us-west-2
- DNS Resolution: Enabled
- Routes Added: 4 route tables updated

Next Steps:
1. Update security groups to allow cross-VPC traffic
2. Test connectivity between instances in both VPCs
```

## Troubleshooting

### Peering Connection Stuck in Pending State
If the peering connection remains in "pending-acceptance" state, check if it's a cross-account connection that requires manual acceptance from the accepter account.

### Route Creation Fails
If route creation fails, check for existing routes with the same destination CIDR block. You may need to replace existing routes instead of creating new ones.

### DNS Resolution Not Working
Ensure both VPCs have DNS resolution and DNS hostnames enabled in their VPC settings, not just the peering connection options.

### Cross-Region Connectivity Issues
Verify that routes are added in both regions and that security groups allow traffic from the peer VPC's CIDR blocks.

### CIDR Block Conflicts
If VPCs have overlapping CIDR blocks, peering will not work properly. Consider using VPC sharing or Transit Gateway as alternatives.
