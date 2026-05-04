# Create API Gateway Stage with Logging Configuration

## Overview
This SOP creates an API Gateway stage with comprehensive logging configuration, stage variables, and necessary IAM roles. It follows AWS best practices for API Gateway stage setup including CloudWatch logging, X-Ray tracing, and proper access logging.

## Parameters

- **rest_api_id** (required): The ID of the REST API for which to create the stage
- **stage_name** (required): The name of the stage (e.g., dev, test, prod)
- **deployment_id** (required): The deployment ID to associate with the stage
- **log_level** (optional, default: "INFO"): The logging level for execution logs (OFF, ERROR, INFO)
- **metrics_enabled** (optional, default: "true"): Whether to enable detailed CloudWatch metrics
- **data_trace_enabled** (optional, default: "false"): Whether to enable data tracing for all methods
- **throttling_rate_limit** (optional, default: "1000"): The throttling rate limit per second
- **throttling_burst_limit** (optional, default: "2000"): The throttling burst limit
- **enable_waf** (optional, default: "true"): Whether to create and associate a WAF web ACL for security

## Steps

### 1. Verify Dependencies
Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context: `call_aws`
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects, consume resources unnecessarily, or trigger actions before the user is ready
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort

### 2. Validate API Gateway Resources
Verify that the specified REST API and deployment exist.

**Constraints:**

- You MUST inform the customer that you are validating the REST API and deployment existence
- You MUST use `call_aws` to describe the REST API using: `aws apigateway get-rest-api --rest-api-id {rest_api_id}`
- You MUST use `call_aws` to verify the deployment exists using: `aws apigateway get-deployment --rest-api-id {rest_api_id} --deployment-id {deployment_id}`
- You MUST stop execution and inform the user if either resource does not exist
- You MUST NEVER use positional arguments that require local files or filesystem access

### 3. Check Existing CloudWatch Logs IAM Role
Verify if API Gateway has the necessary IAM role for CloudWatch logging.

**Constraints:**

- You MUST inform the customer that you are checking for existing CloudWatch logging IAM role configuration
- You MUST use `call_aws` to check the account settings: `aws apigateway get-account`
- You MUST examine the `cloudwatchRoleArn` field in the response
- You SHOULD note if the role is already configured or needs to be created

### 4. Create CloudWatch Logs IAM Role (if needed)
Create the IAM role for API Gateway CloudWatch logging if it doesn't exist.

**Constraints:**

- You MUST inform the customer that you are creating the CloudWatch logs IAM role if none exists
- You MUST create the role with the following trust policy allowing apigateway.amazonaws.com to assume it: `{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"apigateway.amazonaws.com"},"Action":"sts:AssumeRole"}]}`
- You MUST use `call_aws` with: `aws iam create-role --role-name APIGatewayCloudWatchLogsRole --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"apigateway.amazonaws.com"},"Action":"sts:AssumeRole"}]}'`
- You MUST attach the AWS managed policy for CloudWatch logs: `aws iam attach-role-policy --role-name APIGatewayCloudWatchLogsRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs`
- You MUST NEVER use passwords and always rely on IAM roles and policies for authentication
- You MUST skip this step if a CloudWatch role is already configured

### 5. Update Account Settings with CloudWatch Role
Configure the API Gateway account to use the CloudWatch logs role.

**Constraints:**

- You MUST inform the customer that you are updating account settings to use the CloudWatch role
- You MUST use `call_aws` to update account settings: `aws apigateway update-account --patch-operations`
- You MUST set the cloudwatchRoleArn to the created or existing role ARN
- You MUST handle cases where the role is already set appropriately

### 6. Create CloudWatch Log Group
Create a dedicated log group for the API Gateway stage.

**Constraints:**

- You MUST inform the customer that you are creating a CloudWatch log group for the stage
- You MUST use a naming convention like: `/aws/apigateway/{rest_api_id}/{stage_name}`
- You MUST use `call_aws` with: `aws logs create-log-group --log-group-name`
- You SHOULD handle cases where the log group already exists gracefully

### 7. Configure Log Group Retention Policy
Set the retention policy for the CloudWatch log group to manage log lifecycle.

**Constraints:**

- You MUST inform the customer that you are configuring the retention policy for the CloudWatch log group
- You MUST set retention period using: `aws logs put-retention-policy --log-group-name --retention-in-days 14`
- You MUST handle cases where retention is already set appropriately

### 8. Create API Gateway Stage
Create the API Gateway stage with data tracing configuration.

**Constraints:**

- You MUST inform the customer that you are creating the API Gateway stage with logging and monitoring configuration
- You MUST use `call_aws` to create the stage with all configurations: `aws apigateway create-stage --rest-api-id {rest_api_id} --stage-name {stage_name} --deployment-id {deployment_id} --description {stage_description} --variables {environment-variables} --tracing-enabled`
- You MUST include stage variables for environment-specific configuration
- You MUST enable CloudWatch logging with specified log level
- You MUST enable X-Ray tracing for distributed tracing capabilities
- You MUST configure data tracing using the data_trace_enabled parameter: `--data-trace-enabled {data_trace_enabled}`
- You MUST NEVER configure throttling, access-logs and method settings in this step, and do it in the next step

### 9. Configure Throttling limits and caching
Update the API Gateway stage with comprehensive configuration.

**Constraints:**

- You MUST inform the customer that you are configuring throttling limits the API Gateway stage
- You MUST set appropriate caching and throttling settings per method
- You MUST use `call_aws` to configure API Gateway Stage `aws apigateway update-stage --rest-api-id {api_gateway_id} --stage-name {stage_name} --patch-operations op=replace,path=/*/*/throttling/rateLimit,value={throttling_rate_limit} op=replace,path=/*/*/throttling/burstLimit,value={throttling_burst_limit}`
- You MUST set up throttling limits for rate protection including throttlingRateLimit and throttlingBurstLimit
- You MUST include stage variables for environment-specific configuration
- You MUST use SecretsManager for any sensitive configuration values
- You MUST NEVER prompt for or use passwords directly

### 10. Configure Method-Level Logging
Set up method-level access and execution logging configuration for better granularity.

**Constraints:**

- You MUST inform the customer that you are configuring method-level logging settings
- You MUST use update access logging and execution logging separately
- You MUST configure logging for all HTTP methods (*/*) unless specified otherwise
- You MUST use `call_aws` to update method settings for access logging using `aws apigateway update-stage --rest-api-id {api_gateway_id} --stage-name {stage_name} --patch-operations '[{"op":"replace","path":"/accessLogSettings/destinationArn","value":{log_group_arn}},{"op":"replace","path":"/accessLogSettings/format","value":"$context.requestId $context.ip $context.caller $context.user [$context.requestTime] \"$context.httpMethod $context.resourcePath $context.protocol\" $context.status $context.error.message $context.responseLength $context.requestTime $context.xrayTraceId"}]'`
- You MUST use `call_aws` to update method settings for execution logging using `aws apigateway update-stage --rest-api-id {api_gateway_id} --stage-name {stage_name} --patch-operations '[{"op":"replace","path":"/*/*/logging/loglevel","value":"INFO"},{"op":"replace","path":"/*/*/metrics/enabled","value":"true"}]'`

### 11. Create and Associate WAF Web ACL (if enabled)
Create a WAF web ACL with basic security rules and associate it with the API Gateway stage for defense in depth.

**Constraints:**

- You MUST inform the customer that you are creating a WAF web ACL for API security if enable_waf is true
- You MUST create a WAFv2 web ACL with basic managed rules using: `aws wafv2 create-web-acl --name {api_name}-{stage_name}-waf --scope REGIONAL --default-action Allow={} --rules`
- You MUST include AWS managed rule groups for common protections: AWSManagedRulesCommonRuleSet, AWSManagedRulesKnownBadInputsRuleSet
- You MUST add rate limiting rule to prevent abuse: `aws wafv2 create-web-acl` with rate-based rule
- You MUST associate the web ACL with the API Gateway stage using: `aws wafv2 associate-web-acl --web-acl-arn {web_acl_arn} --resource-arn arn:aws:apigateway:{region}::/restapis/{rest_api_id}/stages/{stage_name}`
- You MUST skip this step if enable_waf is false
- You SHOULD inform the user about WAF costs and monitoring

### 12. Configure Authorization
Ask the user about authorization requirements and provide configuration guidance.

**Constraints:**

- You MUST ask the user: "Do you want to configure authorization for this API Gateway stage? Options: NONE (no auth), IAM (AWS IAM), API_KEYS (require API keys), LAMBDA (Lambda authorizer), or CUSTOM (custom authorizer)?"
- You MUST provide setup instructions based on their choice:
  - For NONE: Inform that the API will be publicly accessible
  - For IAM: Provide guidance on setting up IAM policies and roles
  - For API_KEYS: Show how to create and manage API keys
  - For LAMBDA: Provide instructions for creating Lambda authorizer functions
  - For CUSTOM: Provide guidance for custom authorization implementations
- You SHOULD recommend using IAM, API_KEYS, or LAMBDA for production environments
- You MUST inform the user that authorization can be configured later if they choose NONE

### 13. Test Stage Configuration
Validate that the stage has been created successfully with proper configuration.

**Constraints:**

- You MUST inform the customer that you are validating the stage configuration
- You MUST use `call_aws` to get stage details: `aws apigateway get-stage --rest-api-id {rest_api_id} --stage-name {stage_name}`
- You MUST verify all logging configurations are properly applied
- You MUST check that CloudWatch logs are being generated
- You MUST verify WAF association if enabled using: `aws wafv2 get-web-acl-for-resource --resource-arn arn:aws:apigateway:{region}::/restapis/{rest_api_id}/stages/{stage_name}`
- You MUST provide the stage URL for testing

### 14. Provide Testing Instructions
Provide comprehensive examples for testing of new API Gateway stage.

**Constraints:**

- You MUST provide AWS CLI commands for testing the API Gateway stage
- You MUST show how to monitor logs and metrics in CloudWatch
- You MUST explain how to use stage variables in applications
- You MUST provide troubleshooting guidance for common issues

## Examples

### AWS CLI Commands for Testing

```bash
# Test the API Gateway stage
aws apigateway test-invoke-method --rest-api-id {rest_api_id} --stage-name {stage_name} --method GET --path-with-query-string /

# Get stage information
aws apigateway get-stage --rest-api-id {rest_api_id} --stage-name {stage_name}

# View CloudWatch logs
aws logs describe-log-streams --log-group-name /aws/apigateway/{rest_api_id}/{stage_name}

# Get stage metrics
aws cloudwatch get-metric-statistics --namespace AWS/ApiGateway --metric-name Count --dimensions Name=ApiName,Value={api_name} Name=Stage,Value={stage_name} --start-time 2024-01-01T00:00:00Z --end-time 2024-01-01T23:59:59Z --period 3600 --statistics Sum

# Check WAF web ACL association (if WAF is enabled)
aws wafv2 get-web-acl-for-resource --resource-arn arn:aws:apigateway:{region}::/restapis/{rest_api_id}/stages/{stage_name}

# Monitor WAF metrics
aws cloudwatch get-metric-statistics --namespace AWS/WAFV2 --metric-name AllowedRequests --dimensions Name=WebACL,Value={web_acl_name} Name=Region,Value={region} --start-time 2024-01-01T00:00:00Z --end-time 2024-01-01T23:59:59Z --period 3600 --statistics Sum
```

## Troubleshooting

### CloudWatch Logs Not Appearing
If logs are not appearing in CloudWatch:

- Verify the CloudWatch role has correct permissions
- Check that the log group exists and has proper retention settings
- Ensure the API Gateway account settings point to the correct IAM role
- Verify that logging is enabled at both stage and method levels

### Stage Creation Fails
If stage creation fails:

- Verify the REST API ID and deployment ID are correct
- Check that you have sufficient IAM permissions
- Ensure the stage name follows AWS naming conventions
- Verify that throttling limits are within account limits

### High Latency or Errors
If experiencing performance issues:

- Check CloudWatch metrics for error rates and latencies
- Review X-Ray traces for bottlenecks
- Verify caching settings are appropriate
- Check throttling configuration and adjust if needed

### WAF Issues
If WAF is blocking legitimate requests:

- Review WAF logs in CloudWatch to identify blocked requests
- Adjust WAF rules or add exceptions for legitimate traffic
- Monitor WAF metrics for blocked vs allowed requests
- Consider using WAF in count mode initially for testing

### Authorization Issues
If experiencing authorization problems:

- Verify IAM policies have correct permissions for AWS_IAM auth
- Check Cognito user pool configuration for COGNITO_USER_POOLS auth
- Validate Lambda authorizer function for CUSTOM auth
- Test authorization independently before API Gateway integration
