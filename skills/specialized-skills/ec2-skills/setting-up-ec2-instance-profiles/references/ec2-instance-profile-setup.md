# EC2 Instance Profile Setup

## Overview

This SOP guides you through the complete process of granting an EC2 instance permissions to call AWS services securely using IAM roles and instance profiles. Instead of embedding AWS credentials in your application code, instance profiles allow EC2 instances to assume IAM roles and obtain temporary credentials automatically. This SOP helps identify required permissions, creates or uses an existing IAM role, sets up the instance profile, and attaches it to the target EC2 instance.

## Parameters

Prompt the user in a single message to provide all required parameters at once. Clearly list the required parameters and their descriptions, and include any optional parameters with their default values. Do not proceed until you have received and confirmed all required parameters. If any required parameter is missing or unclear, you MUST explicitly request the missing information before moving forward.

- **instance_id** (required): The ID of the EC2 instance to configure (e.g., "i-1234567890abcdef0")
- **region** (required): The AWS region where the instance is running (e.g., "us-east-1", "eu-west-1")
- **services_needed** (required): Comma-separated list of AWS services the instance needs to access (e.g., "s3,dynamodb,sqs", "s3,lambda,cloudwatch")
- **role_name** (optional): Name for the IAM role to create or reuse (default: "{instance_id}-role")

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

### 2. Verify EC2 Instance Exists

Confirm the target EC2 instance exists and retrieve its current configuration.

**Constraints:**

- You MUST verify the instance exists using: `aws ec2 describe-instances --instance-ids ${instance_id} --region ${region}`
- You MUST check if the instance already has an IAM instance profile attached by examining the `IamInstanceProfile` field in the response
- You MUST extract the instance name from tags (if available) for better identification
- You MUST inform the user of the instance's current state (running, stopped, etc.)
- You MUST warn the user if the instance already has an instance profile attached and ask if they want to replace it
- You MUST handle the case where the instance does not exist and provide a clear error message
- You MUST retain the `describe-instances` output for reuse in later steps (e.g., to reference association IDs in Step 8)

### 3. Check for Existing IAM Role

Determine whether to create a new IAM role or reuse an existing one, then verify the selected option.

**Constraints:**

- You MUST ask the user if they want to reuse an existing IAM role or create a new one
- You MUST require the user to provide the role name if they choose to reuse an existing role and one was not already supplied
- If the user opts to create a new role, you MUST proceed to Step 4 and skip the remaining checks in this step
- If the user opts to reuse an existing role:
  - You MUST verify the role exists using: `aws iam get-role --role-name ${role_name} --region ${region}`
  - You MUST retrieve the role's trust policy to verify it allows EC2 service to assume it
  - You MUST check the trust policy contains:

    ```json
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
    ```

  - You MUST list all policies attached to the role using: `aws iam list-attached-role-policies --role-name ${role_name}`
  - You MUST list all inline policies using: `aws iam list-role-policies --role-name ${role_name}`
  - You MUST present the existing permissions to the user for review
  - You MUST ask the user if they want to add additional permissions or use the role as-is
  - You MUST handle the case where the role does not exist and inform the user
  - You MUST verify the role has the correct trust relationship for EC2, and if not, ask the user if they want to update it

### 4. Identify Required Permissions

Analyze the requested services and determine appropriate IAM permissions.

**Constraints:**

- You MUST skip this step if the user chooses to reuse an existing role without modifications
- You MUST analyze each service in `services_needed` and recommend appropriate permissions
- You MUST use the principle of least privilege - recommend specific actions rather than full access when possible
- You MUST provide permission recommendations based on common use cases:
  - **s3**: For general S3 access, recommend `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on specific buckets
  - **dynamodb**: For DynamoDB access, recommend `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:Query`, `dynamodb:Scan` on specific tables
  - **sqs**: For SQS access, recommend `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage` on specific queues
  - **sns**: For SNS access, recommend `sns:Publish` on specific topics
  - **lambda**: For Lambda invocation, recommend `lambda:InvokeFunction` on specific functions
  - **cloudwatch**: For CloudWatch Logs, recommend `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`
  - **secretsmanager**: For Secrets Manager, recommend `secretsmanager:GetSecretValue` on specific secrets
  - **ssm**: For Systems Manager Parameter Store, recommend `ssm:GetParameter`, `ssm:GetParameters` on specific parameters
  - **kms**: For KMS encryption, recommend `kms:Decrypt`, `kms:Encrypt` on specific keys
  - **ec2**: For EC2 operations, recommend specific actions like `ec2:DescribeInstances`, `ec2:DescribeTags`
- You MUST NOT recommend FullAccess or overly broad managed policies (e.g., `AmazonS3FullAccess`, `AmazonDynamoDBFullAccess`, `AmazonSQSFullAccess`, `AmazonSNSFullAccess`, `SecretsManagerReadWrite`, `CloudWatchLogsFullAccess`)
- You MUST ask the user if they want to:
  1. Create custom policies with specific permissions (RECOMMENDED - most secure, principle of least privilege)
  2. Use AWS managed read-only policies (broader but acceptable for read-only use cases, e.g., `AmazonS3ReadOnlyAccess`)
  3. Provide their own custom policy JSON
- You MUST present the recommended permissions to the user in a clear, organized format
- You MUST ask the user to confirm or modify the permissions before proceeding
- You MUST warn users about overly permissive policies (e.g., `*:*` actions or resources)

### 5. Create or Update IAM Role

Create a new IAM role or update an existing one with the identified permissions.

**Constraints:**

- You MUST skip role creation if the user chooses to reuse an existing role without modifications
- You MUST create the trust policy document that allows EC2 to assume the role:

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

- You MUST save the trust policy to a temporary file or use inline JSON
- You MUST create the IAM role using: `aws iam create-role --role-name ${role_name} --assume-role-policy-document file://trust-policy.json --description "IAM role for EC2 instance ${instance_id} to access ${services_needed}"`
- You MUST handle the case where the role already exists with a clear message
- You MUST add tags to the role for better tracking: `aws iam tag-role --role-name ${role_name} --tags Key=ManagedBy,Value=ec2-instance-profile-setup Key=InstanceId,Value=${instance_id} Key=CreatedDate,Value=$(date +%Y-%m-%d)`
- You MUST wait for the role to be created before proceeding (typically immediate, but verify with describe command)
- You MUST verify the role was created successfully using: `aws iam get-role --role-name ${role_name}`

### 6. Attach Policies to IAM Role

Attach the necessary AWS managed policies or create and attach custom inline policies.

**Constraints:**

- You MUST attach each AWS managed policy using: `aws iam attach-role-policy --role-name ${role_name} --policy-arn ${policy_arn}`
- You MUST use proper policy ARNs in the format: `arn:aws:iam::aws:policy/${policy_name}`
- Common managed policy ARNs to use (PREFER LEAST PRIVILEGE — avoid FullAccess policies):
  - S3 Read Only: `arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess` (acceptable for read-only use cases)
  - DynamoDB Read Only: `arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess` (acceptable for read-only use cases)
  - SQS Read Only: `arn:aws:iam::aws:policy/AmazonSQSReadOnlyAccess` (acceptable for queue monitoring/inspection only — consumers that process messages need a custom policy with `sqs:ReceiveMessage` and `sqs:DeleteMessage`)
  - SSM Managed Instance Core: `arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore`
- You MUST NOT recommend or attach FullAccess or overly broad managed policies (e.g., `AmazonS3FullAccess`, `AmazonDynamoDBFullAccess`, `AmazonSQSFullAccess`, `AmazonSNSFullAccess`, `SecretsManagerReadWrite`, `CloudWatchLogsFullAccess`). Instead, create custom policies scoped to specific resources.
- You MUST prefer custom inline policies over managed policies for write access:

  ```bash
  aws iam put-role-policy --role-name ${role_name} --policy-name ${policy_name} --policy-document file://custom-policy.json
  ```

- You MUST validate that all policies were attached successfully
- You MUST list all attached policies to confirm: `aws iam list-attached-role-policies --role-name ${role_name}`
- You MUST also list inline policies to confirm: `aws iam list-role-policies --role-name ${role_name}`
- You MUST handle errors such as invalid policy ARNs or permission issues
- You MUST inform the user of all attached policies

### 7. Create Instance Profile

Create an instance profile that wraps the IAM role for EC2 use.

**Constraints:**

- You MUST check if an instance profile with the same name already exists using: `aws iam get-instance-profile --instance-profile-name ${role_name}`
- You MUST handle the case where the instance profile already exists:
  - If it exists and contains the correct role, you MAY reuse it
  - If it exists but contains a different role, you MUST ask the user if they want to remove the old role and add the new one
  - If it exists with the same role, you MAY skip creation and proceed to attachment
- You MUST create the instance profile if it doesn't exist: `aws iam create-instance-profile --instance-profile-name ${role_name}`
- You MUST add the IAM role to the instance profile: `aws iam add-role-to-instance-profile --instance-profile-name ${role_name} --role-name ${role_name}`
- You MUST verify the instance profile was created successfully using: `aws iam get-instance-profile --instance-profile-name ${role_name}`
- You MUST wait for the instance profile to be fully created before proceeding (check that the role is listed in the instance profile)
- You MUST extract the instance profile ARN for the next step

### 8. Attach Instance Profile to EC2 Instance

Associate the instance profile with the target EC2 instance.

**Constraints:**

- You MUST check if the instance already has an instance profile attached (from step 2)
- You MUST handle existing instance profile associations:
  - If an instance profile is already attached, you MUST first disassociate it using: `aws ec2 disassociate-iam-instance-profile --association-id ${association_id}`
  - You MUST wait for the disassociation to complete before proceeding
- You MUST attach the new instance profile using: `aws ec2 associate-iam-instance-profile --instance-id ${instance_id} --iam-instance-profile Name=${role_name} --region ${region}`
- You MUST verify the attachment was successful using: `aws ec2 describe-instances --instance-ids ${instance_id} --region ${region}`
- You MUST check that the `IamInstanceProfile` field now contains the correct instance profile ARN
- You MUST inform the user that the attachment was successful
- You MUST note that the instance profile association takes effect immediately for new credential requests, but existing application sessions may need to refresh their credentials

### 9. Verify Configuration and Test Access

Confirm the instance profile is properly configured and test that credentials are accessible.

**Constraints:**

- You MUST verify the complete configuration by checking:
  1. Instance profile is attached to the instance
  2. Instance profile contains the correct role
  3. Role has the expected policies attached
  4. Trust relationship allows EC2 to assume the role
- You MUST provide instructions for testing the configuration from within the instance using IMDSv2 (token-based):

  ```bash
  # SSH into the instance and run:

  # 1. Get an IMDSv2 session token (valid for 6 hours)
  TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

  # 2. Verify instance metadata service can provide credentials
  curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/

  # 3. Retrieve temporary credentials (will show role name)
  curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/${role_name}

  # 4. Test AWS CLI with the instance profile (no credentials needed in CLI config)
  aws sts get-caller-identity

  # 5. Test access to a specific service (example for S3)
  aws s3 ls
  ```

- You MUST NOT use IMDSv1 (plain curl without token) — always use IMDSv2 with a session token
- You MUST explain that applications using AWS SDKs will automatically use these credentials
- You MUST provide code examples for common SDK languages to verify automatic credential resolution:
  - **Python (boto3)**:

    ```python
    import boto3
    # No credentials needed - automatically uses instance profile
    s3 = boto3.client('s3')
    print(s3.list_buckets())
    ```

  - **Node.js (AWS SDK v3)**:

    ```javascript
    import { S3Client, ListBucketsCommand } from "@aws-sdk/client-s3";
    // No credentials needed - automatically uses instance profile
    const client = new S3Client({ region: "us-east-1" });
    const command = new ListBucketsCommand({});
    const response = await client.send(command);
    console.log(response);
    ```

  - **Java (AWS SDK v2)**:

    ```java
    import software.amazon.awssdk.services.s3.S3Client;
    // No credentials needed - automatically uses instance profile
    S3Client s3 = S3Client.builder().region(Region.US_EAST_1).build();
    s3.listBuckets();
    ```

- You MUST remind the user to remove any hardcoded AWS credentials from their application code
- You MUST warn about credential caching - applications may need to be restarted to pick up the new credentials

### 10. Generate Configuration Summary Report

Create a comprehensive report documenting the setup.

**Constraints:**

- You MUST create a detailed summary report containing:
  - Instance ID and region
  - IAM role name and ARN
  - Instance profile name and ARN
  - List of all attached policies (managed and inline)
  - Services granted access
  - Trust policy configuration
  - Verification test results
  - Instructions for testing from within the instance
  - Security best practices and recommendations
  - Next steps for the user
- You MUST include security recommendations:
  - Regularly review and audit IAM permissions
  - Use resource-level permissions when possible (specify exact ARNs)
  - Enable CloudTrail to log API calls made by the instance
  - Consider using IAM policy conditions for additional security (e.g., IP restrictions, time-based access)
  - Rotate credentials regularly (automatic with instance profiles)
  - Monitor for unusual API activity using CloudWatch
- You MUST provide instructions for updating permissions in the future:

  ```bash
  # To add more policies:
  aws iam attach-role-policy --role-name ${role_name} --policy-arn ${new_policy_arn}

  # To remove policies:
  aws iam detach-role-policy --role-name ${role_name} --policy-arn ${policy_arn}

  # To update inline policies:
  aws iam put-role-policy --role-name ${role_name} --policy-name ${policy_name} --policy-document file://updated-policy.json
  ```

- You MUST provide instructions for cleanup if needed:

  ```bash
  # To remove the instance profile from the instance:
  aws ec2 disassociate-iam-instance-profile --association-id ${association_id}

  # To delete the instance profile:
  aws iam remove-role-from-instance-profile --instance-profile-name ${role_name} --role-name ${role_name}
  aws iam delete-instance-profile --instance-profile-name ${role_name}

  # To delete the role (must detach policies first):
  aws iam detach-role-policy --role-name ${role_name} --policy-arn ${policy_arn}
  aws iam delete-role --role-name ${role_name}
  ```

- You MUST format the report in a clear, well-organized manner
- You MUST present the report to the user

## Examples

### Example Input

```
instance_id: i-0abcd1234efgh5678
region: us-east-1
services_needed: s3,dynamodb,cloudwatch
role_name: web-server-role
```

During Step 3, the user chose to create a new IAM role.

### Example Output

```
# EC2 Instance Profile Setup Report

**Instance ID:** i-0abcd1234efgh5678
**Region:** us-east-1
**IAM Role:** web-server-role
**Instance Profile:** web-server-role

## Configuration Summary

### Instance Details
- **Instance ID:** i-0abcd1234efgh5678
- **Instance Name:** web-server-prod-01
- **Instance State:** running
- **Previous Instance Profile:** None
- **New Instance Profile:** web-server-role

### IAM Role Configuration
- **Role Name:** web-server-role
- **Role ARN:** arn:aws:iam::123456789012:role/web-server-role
- **Trust Policy:** Configured to allow EC2 service to assume role
- **Created:** 2025-10-13

### Attached Policies

#### Least Privilege Policy Examples

**SECURITY BEST PRACTICE: Always use the minimum permissions required for your use case.**

#### Custom S3 Policy (Specific Bucket Access)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::my-app-bucket/*"
    }
  ]
}
```

#### Custom CloudWatch Logs Policy (Specific Log Group)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:log-group:/aws/ec2/my-app:*"
    }
  ]
}
```

#### Custom DynamoDB Policy (Specific Table Access)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/my-app-table"
    }
  ]
}
```

### AWS Managed Read-Only Policies (Acceptable for Read-Only Use Cases)

1. **AmazonS3ReadOnlyAccess**
   - ARN: `arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess`
   - Grants: Read-only access to all S3 buckets

2. **AmazonDynamoDBReadOnlyAccess**
   - ARN: `arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess`
   - Grants: Read-only access to all DynamoDB tables
   - **Use custom policy for write access scoped to specific tables**

#### Custom Inline Policies

**CloudWatchLogsWrite** (scoped to specific log group):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:log-group:/aws/ec2/web-server-prod-01:*"
    }
  ]
}
```

### Instance Profile Configuration

- **Instance Profile Name:** web-server-role
- **Instance Profile ARN:** arn:aws:iam::123456789012:instance-profile/web-server-role
- **Associated IAM Role:** web-server-role
- **Attached to Instance:** Yes

## Verification Results

### Instance Profile Attachment: ✓ Success

- Instance profile successfully attached to instance i-0abcd1234efgh5678
- Configuration is active and ready to use

### Role and Policy Validation: ✓ Success

- IAM role exists and is properly configured
- Trust policy allows EC2 service to assume role
- All requested policies are attached

### Credential Availability: Ready to Test
Follow the test instructions below to verify from within the instance.

## Testing Instructions

### From Within the EC2 Instance

SSH into your instance and run these commands:

```bash
# 1. Get an IMDSv2 session token (valid for 6 hours)
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

# 2. Check if instance profile is available
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Expected output: web-server-role

# 3. Retrieve temporary credentials
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/web-server-role

# Expected output: JSON with AccessKeyId, SecretAccessKey, Token

# 4. Verify AWS CLI can use the credentials
aws sts get-caller-identity

# Expected output: Your account ID, user ID, and role ARN

# 5. Test S3 access
aws s3 ls

# Expected output: List of S3 buckets (if any exist)

# 6. Test DynamoDB access
aws dynamodb list-tables

# Expected output: List of DynamoDB tables (if any exist)

# 7. Test CloudWatch Logs write access
aws logs create-log-group --log-group-name /aws/ec2/web-server-prod-01

# Expected output: (none on success; ResourceAlreadyExistsException if it already exists)

```

### Application Code Examples

#### Python (boto3)

```python
import boto3

# No explicit credentials needed - boto3 automatically uses instance profile
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Test S3 access
buckets = s3.list_buckets()
print(f"Found {len(buckets['Buckets'])} S3 buckets")

# Test DynamoDB access
table = dynamodb.Table('your-table-name')
response = table.get_item(Key={'id': '123'})
print(response)
```

#### Node.js (AWS SDK v3)

```javascript
import { S3Client, ListBucketsCommand } from "@aws-sdk/client-s3";
import { DynamoDBClient, ListTablesCommand } from "@aws-sdk/client-dynamodb";

// No explicit credentials needed - SDK automatically uses instance profile
const s3Client = new S3Client({ region: "us-east-1" });
const dynamoClient = new DynamoDBClient({ region: "us-east-1" });

// Test S3 access
const s3Response = await s3Client.send(new ListBucketsCommand({}));
console.log(`Found ${s3Response.Buckets.length} S3 buckets`);

// Test DynamoDB access
const dynamoResponse = await dynamoClient.send(new ListTablesCommand({}));
console.log(`Found ${dynamoResponse.TableNames.length} DynamoDB tables`);
```

#### Java (AWS SDK v2)

```java
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.regions.Region;

// No explicit credentials needed - SDK automatically uses instance profile
S3Client s3 = S3Client.builder()
    .region(Region.US_EAST_1)
    .build();

DynamoDbClient dynamoDb = DynamoDbClient.builder()
    .region(Region.US_EAST_1)
    .build();

// Test S3 access
var s3Response = s3.listBuckets();
System.out.println("Found " + s3Response.buckets().size() + " S3 buckets");

// Test DynamoDB access
var dynamoResponse = dynamoDb.listTables();
System.out.println("Found " + dynamoResponse.tableNames().size() + " DynamoDB tables");
```

## Security Best Practices

### Implemented

- ✓ Using IAM roles instead of hardcoded credentials
- ✓ Instance profile provides automatic credential rotation
- ✓ Credentials are temporary and expire automatically

### Recommended Additional Steps

1. **Apply Least Privilege Principle**
   - Current setup uses managed policies with broad permissions
   - Consider creating custom policies with specific resource ARNs
   - Example for S3 bucket-specific access:

     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Action": [
             "s3:GetObject",
             "s3:PutObject",
             "s3:ListBucket"
           ],
           "Resource": [
             "arn:aws:s3:::your-specific-bucket",
             "arn:aws:s3:::your-specific-bucket/*"
           ]
         }
       ]
     }
     ```

2. **Enable CloudTrail Logging**

   ```bash
   # Track all API calls made using this role
   aws cloudtrail create-trail --name instance-audit-trail \
     --s3-bucket-name your-cloudtrail-bucket

   aws cloudtrail start-logging --name instance-audit-trail
   ```

3. **Set Up CloudWatch Alarms**
   - Monitor for unusual API activity
   - Alert on unauthorized access attempts
   - Track resource usage patterns

4. **Regular Permission Audits**
   - Review attached policies quarterly
   - Remove unused permissions
   - Use AWS IAM Access Analyzer to identify unused access

5. **Use Resource Tags**
   - Tag resources accessed by this instance
   - Implement tag-based access control policies
   - Track costs by application/instance

6. **Consider Using IAM Policy Conditions**

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:GetObject",
           "s3:PutObject"
         ],
         "Resource": "arn:aws:s3:::your-specific-bucket/*",
         "Condition": {
           "StringEquals": {
             "aws:PrincipalTag/Environment": "production"
           }
         }
       }
     ]
   }
   ```

  Use with tag-based access control (ABAC): tag the IAM role with `Environment=production` and add `aws:PrincipalTag conditions` to the IAM policy (as shown above) to restrict access based on the role's tags. This lets you manage access across many instances without updating policies individually.

## Managing Permissions

### Adding More Permissions

```bash
# Attach additional managed policy
aws iam attach-role-policy \
  --role-name web-server-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

# Add custom inline policy (RECOMMENDED - most secure)
aws iam put-role-policy \
  --role-name web-server-role \
  --policy-name CustomS3Access \
  --policy-document file://custom-policy.json
```

### Removing Permissions

```bash
# Detach managed policy
aws iam detach-role-policy \
  --role-name web-server-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess

# Delete inline policy
aws iam delete-role-policy \
  --role-name web-server-role \
  --policy-name CustomS3Access
```

### Updating Existing Policies

```bash
# Update inline policy (overwrites existing)
aws iam put-role-policy \
  --role-name web-server-role \
  --policy-name CustomS3Access \
  --policy-document file://updated-policy.json
```

## Cleanup Instructions

If you need to remove this configuration:

```bash
# 1. Disassociate instance profile from instance
aws ec2 disassociate-iam-instance-profile \
  --association-id iip-assoc-0abcd1234efgh5678

# 2. Remove role from instance profile
aws iam remove-role-from-instance-profile \
  --instance-profile-name web-server-role \
  --role-name web-server-role

# 3. Delete instance profile
aws iam delete-instance-profile \
  --instance-profile-name web-server-role

# 4. Detach all policies from role
aws iam delete-role-policy \
  --role-name web-server-role \
  --policy-name CloudWatchLogsWrite

aws iam detach-role-policy \
  --role-name web-server-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

aws iam detach-role-policy \
  --role-name web-server-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess

aws iam detach-role-policy \
  --role-name web-server-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

# 5. Delete the IAM role
aws iam delete-role --role-name web-server-role
```

## Next Steps

1. **Remove Hardcoded Credentials**: Search your application code for hardcoded AWS credentials and remove them
2. **Test Application**: Restart your application and verify it can access AWS services using the instance profile
3. **Monitor Activity**: Check CloudTrail logs to ensure the instance is making expected API calls
4. **Refine Permissions**: After testing, consider tightening permissions to follow least privilege principle
5. **Document Configuration**: Add this configuration to your infrastructure documentation and deployment scripts
6. **Implement Monitoring**: Set up CloudWatch alarms for permission-denied errors and unusual activity

## Troubleshooting

### Application Cannot Access AWS Services

- Ensure the application is using the AWS SDK's default credential provider chain
- Check that no explicit credentials are configured in application config files
- Verify the instance profile is attached: `aws ec2 describe-instances --instance-ids i-0abcd1234efgh5678`
- Test credential retrieval from metadata service (see testing instructions above)
- Restart the application to refresh credential cache

### Access Denied Errors

- Verify the required permissions are attached to the role
- Check for deny policies that might override allow permissions
- Ensure resource-level permissions include the specific resources being accessed
- Review CloudTrail logs to identify the specific denied action
- Test with broader permissions temporarily to isolate the issue

### Instance Profile Not Available in Metadata Service

- Wait 30-60 seconds after attaching instance profile for propagation
- Verify the instance profile is properly associated with the instance
- Check that IMDSv2 is configured — use token-based requests (see testing instructions above)
- Ensure security groups allow outbound traffic to metadata service (should be default)

### Role Assumption Failures

- Verify the trust policy allows ec2.amazonaws.com as principal
- Check that the role has not been deleted or modified
- Ensure IAM service is available in the region

## Summary

Successfully configured EC2 instance `i-0abcd1234efgh5678` to securely access AWS services using IAM role `web-server-role`. The instance can now access S3, DynamoDB, and CloudWatch Logs without hardcoded credentials. Follow the testing instructions above to verify the configuration and remove any existing hardcoded credentials from your application code.

```

## Troubleshooting

### EC2 Instance Does Not Exist
If the specified instance ID is not found, verify you are using the correct instance ID and region. Use `aws ec2 describe-instances --region ${region}` to list all instances in the region.

### Instance Already Has an Instance Profile
If the instance already has an instance profile attached, the script will prompt you to confirm whether you want to replace it. Replacing an instance profile will immediately change the permissions available to applications running on the instance.

### IAM Role Name Conflicts
If a role with the specified name already exists but has different configurations, you MUST prompt the user either to choose a different name or to confirm updating the existing role. Consider using descriptive, unique names like `{application}-{environment}-{instance-name}-role`.

### Permission Denied Errors
Ensure your AWS credentials have the necessary IAM permissions to create roles, instance profiles, and attach policies. Required permissions include:
- `iam:CreateRole`
- `iam:GetRole`
- `iam:AttachRolePolicy`
- `iam:CreateInstanceProfile`
- `iam:AddRoleToInstanceProfile`
- `ec2:AssociateIamInstanceProfile`
- `ec2:DescribeInstances`
- `ec2:DisassociateIamInstanceProfile`

### Instance Profile Takes Time to Propagate
After attaching an instance profile, it may take 30-60 seconds for the credentials to become available in the instance metadata service. Applications may need to retry credential requests or be restarted.

### Trust Policy Validation Failures
If you're using an existing role and the trust policy doesn't allow EC2 to assume it, you'll need to update the trust policy using:
```bash
aws iam update-assume-role-policy --role-name ${role_name} --policy-document file://trust-policy.json
```

### Overly Permissive Policies
If you receive warnings about overly permissive policies, consider using more restrictive permissions with specific resource ARNs rather than wildcard (`*`) resources. This follows the principle of least privilege and reduces security risks.

### Application Still Uses Hardcoded Credentials
Even after setting up an instance profile, applications may continue using hardcoded credentials if they are explicitly configured. You must remove any AWS credentials from:

- Application configuration files
- Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- Credential files (~/.aws/credentials)

### Multiple Roles Need to Be Combined
If your application needs permissions from multiple existing roles, you cannot attach multiple instance profiles to a single instance. Instead, you must create a new role that combines all required permissions from the multiple roles.

### Region-Specific Resources
Ensure that the policies grant access to resources in the correct regions. Some AWS services are region-specific, and you may need to specify resources with region-aware ARNs.
