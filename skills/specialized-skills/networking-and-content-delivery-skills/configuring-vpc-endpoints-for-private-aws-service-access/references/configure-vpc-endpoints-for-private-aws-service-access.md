# Configure VPC Endpoints for Private AWS Service Access

## Overview
This SOP configures VPC endpoints to enable private access to AWS services without routing traffic through the internet. VPC endpoints provide secure, private connectivity to supported AWS services and VPC endpoint services powered by AWS PrivateLink.

## Parameters

- vpc_id (required): The ID of the VPC where endpoints will be created
- subnet_ids (required): Comma-separated list of subnet IDs for interface endpoints
- service_names (required): Comma-separated list of AWS service names to create endpoints for (e.g., s3, ec2, ssm, secretsmanager)
- route_table_ids (optional): Comma-separated list of route table IDs for gateway endpoints
- security_group_ids (optional): Comma-separated list of security group IDs for interface endpoints
- policy_document (optional): Custom endpoint policy JSON document
- enable_dns_hostnames (optional, default: "true"): Enable DNS hostnames for interface endpoints
- enable_dns_support (optional, default: "true"): Enable DNS support for interface endpoints

## Steps

### 1. Verify Dependencies
Check for required tools and inform the user about capabilities needed.

Constraints:

- You MUST verify that the `call_aws` tool is available in your context
- You MUST inform the user that this SOP requires AWS CLI access and will make AWS API calls
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort
- You MUST inform the user that passwords will be managed through AWS Secrets Manager and MUST NEVER prompt for password input

### 2. Gather Required Parameters
Collect all required parameters from the user in a single prompt.

Constraints:

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods for parameter provision
- You MUST validate that vpc_id follows the format vpc-xxxxxxxx
- You MUST validate that subnet_ids follow the format subnet-xxxxxxxx
- You MUST confirm successful acquisition of all parameters before proceeding

### 3. Validate VPC and Subnets
Verify that the specified VPC and subnets exist and are properly configured.

Constraints:

- You MUST call AWS CLI to describe the VPC and verify it exists
- You MUST call AWS CLI to describe subnets and verify they exist in the specified VPC
- You MUST inform the user about each validation step being performed and why
- You MUST check that DNS hostnames and DNS resolution are enabled on the VPC for interface endpoints
- You SHOULD warn the user if DNS settings are not optimal for VPC endpoints

### 4. Check Existing VPC Endpoints
Check for existing VPC endpoints to avoid duplicates.

Constraints:

- You MUST call AWS CLI to list existing VPC endpoints in the VPC
- You MUST inform the user about existing endpoints for the requested services
- You MUST ask the user whether to skip, replace, or modify existing endpoints
- You MUST respect the user's decision on handling existing endpoints

### 5. Create Security Groups for Interface Endpoints
Create or validate security groups for interface endpoints if not provided.

Constraints:

- You MUST create a security group for interface endpoints if security_group_ids is not provided
- You MUST configure inbound rules to allow HTTPS traffic (port 443) from VPC CIDR
- You MUST call AWS CLI to create security group and rules
- You MUST inform the user about security group creation and configuration
- You MUST use AWS Secrets Manager for any authentication requirements and MUST NEVER prompt for passwords

### 6. Determine Endpoint Types
Categorize services into gateway and interface endpoint types.

Constraints:

- You MUST identify which services support gateway endpoints (S3, DynamoDB)
- You MUST identify which services require interface endpoints (EC2, SSM, Secrets Manager, etc.)
- You MUST inform the user about the endpoint types that will be created
- You MUST explain the difference between gateway and interface endpoints

### 7. Create Gateway Endpoints
Create VPC gateway endpoints for supported services.

Constraints:

- You MUST create gateway endpoints for S3 and DynamoDB if requested
- You MUST associate gateway endpoints with route tables
- You MUST use provided route_table_ids or discover route tables automatically
- You MUST call AWS CLI to create each gateway endpoint
- You MUST inform the user about each endpoint creation step
- You MUST apply custom policy if policy_document is provided

### 8. Create Interface Endpoints
Create VPC interface endpoints for supported services.

Constraints:

- You MUST create interface endpoints for services that don't support gateway endpoints
- You MUST associate interface endpoints with specified subnets
- You MUST attach security groups to interface endpoints
- You MUST enable DNS hostnames and support based on parameters
- You MUST call AWS CLI to create each interface endpoint
- You MUST inform the user about each endpoint creation step and its purpose

### 9. Configure Endpoint Policies
Apply custom endpoint policies if provided.

Constraints:

- You MUST apply custom policy_document to endpoints if provided
- You MUST validate JSON policy syntax before applying
- You MUST call AWS CLI to modify endpoint policy
- You MUST inform the user about policy application
- You SHOULD provide examples of common endpoint policies if no custom policy is provided

### 10. Verify Endpoint Status
Check that all endpoints are created successfully and are available.

Constraints:

- You MUST call AWS CLI to describe all created endpoints
- You MUST verify that endpoints are in "Available" state
- You MUST inform the user about endpoint status and any issues
- You MUST wait for endpoints to become available before proceeding
- You SHOULD provide estimated time for endpoint availability

### 11. Test Connectivity
Provide instructions for testing VPC endpoint connectivity.

Constraints:

- You MUST provide AWS CLI commands to test connectivity to each service
- You MUST explain how to verify that traffic is using the VPC endpoint
- You MUST provide examples of testing from EC2 instances within the VPC
- You MUST inform the user about DNS resolution testing for interface endpoints

### 12. Provide Integration Examples
Provide code examples and testing instructions for the configured VPC endpoints.

Constraints:

- You MUST provide AWS CLI examples for testing each endpoint type
- You MUST provide Python boto3 code examples for connecting through endpoints
- You MUST provide Java AWS SDK examples for endpoint usage
- You MUST provide JavaScript/Node.js AWS SDK examples
- You MUST explain how applications can leverage the private endpoints
- You MUST include examples of endpoint-specific DNS names for interface endpoints

## Examples

### Example AWS CLI Commands

```bash
# List VPC endpoints
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids vpce-12345678

# Test S3 connectivity through gateway endpoint
aws s3 ls --region us-east-1

# Test EC2 connectivity through interface endpoint
aws ec2 describe-instances --region us-east-1

# Test DNS resolution for interface endpoint
nslookup ec2.us-east-1.amazonaws.com
```

### Example Integration Code

#### Python Example

```python
import boto3

# Configure client to use VPC endpoint
ec2_client = boto3.client('ec2',
    region_name='us-east-1',
    endpoint_url='https://vpce-12345678-abcdefgh.ec2.us-east-1.vpce.amazonaws.com')

# List instances using private endpoint
response = ec2_client.describe_instances()
```

#### Java Example

```java
// Configure client with VPC endpoint
EC2Client ec2Client = EC2Client.builder()
    .region(Region.US_EAST_1)
    .endpointOverride(URI.create("https://vpce-12345678-abcdefgh.ec2.us-east-1.vpce.amazonaws.com"))
    .build();

// Use client normally
DescribeInstancesResponse response = ec2Client.describeInstances();
```

#### JavaScript/Node.js Example

```javascript
const AWS = require('aws-sdk');

// Configure service with VPC endpoint
const ec2 = new AWS.EC2({
    region: 'us-east-1',
    endpoint: 'https://vpce-12345678-abcdefgh.ec2.us-east-1.vpce.amazonaws.com'
});

// Use service normally
ec2.describeInstances({}, (err, data) => {
    if (err) console.log(err);
    else console.log(data);
});
```

## Troubleshooting

### Endpoint Not Available
If VPC endpoints show "Failed" or "Rejected" state, check security group rules, subnet configurations, and service availability in the region.

### DNS Resolution Issues
If interface endpoint DNS names don't resolve, verify that DNS hostnames and DNS resolution are enabled on the VPC and that the VPC has a DHCP options set with the correct domain name servers.

### Connection Timeouts
If connections to services timeout, verify security group rules allow HTTPS traffic (port 443) and that route tables are properly configured for gateway endpoints.

### Policy Restrictions
If access is denied, review endpoint policies and ensure they allow the required actions for your use case. Default policies allow all access, but custom policies may be restrictive.
