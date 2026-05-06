# Create Secrets Using Best Practices

## Overview

This SOP provides a comprehensive approach to creating and managing secrets in AWS Secrets Manager following security best practices. It covers creating secrets with proper encryption using KMS, implementing automatic rotation, configuring least-privilege IAM policies, enabling CloudTrail auditing, and setting up lifecycle management with proper tagging and deletion policies.

## Parameters

- **secret_name** (required): The name of the secret to create
- **secret_description** (required): Description of what the secret contains
- **secret_type** (required): Type of secret (database, api-key, oauth, custom)
- **secret_value** (required): The secret value or JSON structure
- **aws_region** (required): The AWS region where the secret will be created
- **kms_key_id** (optional): KMS key ID for encryption (will create if not provided)
- **enable_rotation** (optional, default: true): Whether to enable automatic rotation
- **rotation_interval** (optional, default: 30): Rotation interval in days
- **lambda_function_arn** (optional): ARN of Lambda function for custom rotation
- **allowed_principals** (optional): List of IAM principals that should have access
- **tags** (optional): Key-value pairs for resource tagging
- **recovery_window** (optional, default: 30): Recovery window in days before permanent deletion

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods including:
  - Direct input: Text provided directly in the conversation
  - File path: Path to a local file containing secret configuration
  - URL: Link to configuration resources
- You MUST validate secret_type is one of: database, api-key, oauth, custom
- You MUST confirm successful acquisition of all parameters before proceeding
- You MUST NOT log or display the actual secret value in any output

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
- You MUST explain the reason for every tool call before executing it throughout the entire SOP
- You MUST verify AWS CLI is properly configured with this command:

  ```
  aws sts get-caller-identity
  ```

### 2. Create or Verify KMS Key

Set up KMS key for secret encryption if not provided.

**Constraints:**

- If kms_key_id is provided, You MUST verify the key exists and is accessible
- If kms_key_id is not provided, You MUST create a new KMS key specifically for secrets
- You MUST configure the KMS key policy to grant the calling principal `kms:GenerateDataKey`, `kms:Decrypt`, and `kms:DescribeKey` permissions, scoped with the condition key `kms:ViaService` set to `secretsmanager.{aws_region}.amazonaws.com` so the key can only be used through Secrets Manager
- If allowed_principals is provided, You MUST add those principals to the key policy with `kms:Decrypt` and `kms:DescribeKey` permissions (read-only access to decrypt secrets)
- You MUST ensure the key policy retains the root account as key administrator to prevent lockout
- You MUST enable key rotation for the KMS key
- You MUST tag the KMS key with appropriate metadata

### 3. Create the Secret

Create the secret in AWS Secrets Manager with proper configuration.

**Constraints:**

- You MUST create the secret using the specified KMS key for encryption
- You MUST set the description and tags as provided
- You MUST configure the secret based on the secret_type:
  - For database: Structure as JSON with host, username, password, engine, port, dbname
  - For api-key: Structure as JSON with key and optional metadata
  - For oauth: Structure as JSON with client_id, client_secret, and optional fields
  - For custom: Use the provided structure as-is
- You MUST set the recovery window using the recovery_window parameter for deletion protection
- You MUST NOT display the secret value in any output or logs

### 4. Configure Automatic Rotation

Set up automatic rotation if enabled.

**Constraints:**

- If enable_rotation is true, You MUST configure automatic rotation
- You MUST set the rotation interval as specified
- For database secrets, You MUST use the appropriate AWS-managed rotation function
- For custom secrets, You MUST require and use the lambda_function_arn parameter
- You MUST verify the rotation function (specified by lambda_function_arn) has proper permissions to access the secret
- You MUST test the rotation configuration by triggering an initial rotation
- You MUST handle rotation setup failures gracefully and provide clear error messages

### 5. Create Least-Privilege IAM Policy

Create an IAM policy that grants minimal necessary permissions.

**Constraints:**

- You MUST create a read-only policy that allows only:
  - `secretsmanager:GetSecretValue` for the specific secret ARN
  - `secretsmanager:DescribeSecret` for the specific secret ARN
  - `kms:Decrypt` for the specific KMS key ARN
  - `kms:DescribeKey` for the specific KMS key ARN
- You MUST include the condition key `aws:SecureTransport` set to true to enforce HTTPS
- You MUST scope all resource ARNs to the specific secret and KMS key — do NOT use wildcards
- If enable_rotation is true, You MUST create a separate rotation policy that additionally allows:
  - `secretsmanager:PutSecretValue` for the specific secret ARN
  - `secretsmanager:UpdateSecretVersionStage` for the specific secret ARN
  - `kms:GenerateDataKey` for the specific KMS key ARN (required when writing new secret values)
- If allowed_principals is provided, You MUST attach the read-only policy to those specific principals
- If allowed_principals is not provided, You MUST still create the policy but provide guidance for manual attachment
- You MUST provide the policy ARN and JSON for manual attachment if needed

### 6. Enable CloudTrail Auditing

Ensure CloudTrail is configured to audit Secrets Manager operations.

**Constraints:**

- You MUST verify CloudTrail is enabled in the region
- You MUST ensure CloudTrail captures Secrets Manager API calls
- You MUST configure CloudTrail to log to a secure S3 bucket with encryption
- You MUST set up CloudWatch Logs integration for real-time monitoring
- You MUST create CloudWatch alarms for suspicious secret access patterns
- You MUST provide guidance on monitoring and alerting best practices

### 7. Configure Lifecycle Management

Set up proper lifecycle management and monitoring.

**Constraints:**

- You MUST configure appropriate tags for cost allocation and management
- You MUST set up CloudWatch metrics for secret usage monitoring
- You MUST create CloudWatch alarms for:
  - Failed secret retrievals
  - Rotation failures
  - Unusual access patterns
- You MUST configure backup and disaster recovery procedures
- You MUST document the secret management procedures for the team

### 8. Validate Configuration

Perform comprehensive validation of the secret setup.

**Constraints:**

- You MUST test secret retrieval using the created IAM policy
- You MUST verify encryption is working properly
- You MUST validate rotation configuration (if enabled)
- You MUST check CloudTrail logging is capturing secret operations
- You MUST verify all CloudWatch alarms are properly configured
- You MUST provide a summary of all created resources and their ARNs
- You MUST create documentation for ongoing secret management

## Examples

### Example Input for Database Secret

```
secret_name: "prod-database-credentials"
secret_description: "Production database credentials for main application"
secret_type: "database"
secret_value: {
  "host": "prod-db.example.com",
  "username": "app_user",
  "password": "secure_password_123",
  "engine": "mysql",
  "port": 3306,
  "dbname": "production"
}
aws_region: "us-east-1"
enable_rotation: true
rotation_interval: 30
tags: {
  "Environment": "Production",
  "Application": "MainApp",
  "Owner": "DevOps"
}
```

### Example Input for API Key Secret

```
secret_name: "third-party-api-key"
secret_description: "API key for external service integration"
secret_type: "api-key"
secret_value: {
  "api_key": "EXAMPLE-API-KEY-REPLACE-ME",
  "service_name": "ExternalAPI",
  "endpoint": "https://api.external.com"
}
aws_region: "us-west-2"
enable_rotation: false
```

## Troubleshooting

### KMS Key Access Issues
If you encounter KMS key access errors, verify that:

- The IAM user/role has kms:CreateKey and kms:PutKeyPolicy permissions
- The key policy includes the necessary principals
- The Secrets Manager service has access to the key

### Rotation Setup Failures
If automatic rotation setup fails:

- Verify the Lambda function exists and has proper permissions
- Check that the rotation function can access both the secret and the target system
- Ensure network connectivity between Lambda and the target system
- Review CloudWatch logs for the rotation function

### CloudTrail Configuration Issues
If CloudTrail setup encounters problems:

- Verify S3 bucket permissions for CloudTrail
- Check that CloudTrail has proper IAM permissions
- Ensure the S3 bucket is in the same region or properly configured for cross-region access

### Secret Access Denied
If secret retrieval fails:

- Verify the IAM policy is correctly attached to the principal
- Check that the KMS key policy allows the principal to decrypt
- Ensure the secret exists in the specified region
- Verify the principal is using HTTPS (aws:SecureTransport condition)
