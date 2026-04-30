# Connect Lambda Function to API Gateway

## Overview
This SOP creates a REST API using Amazon API Gateway and connects it to an existing Lambda function, enabling HTTP-based invocation of the Lambda function through API endpoints.

## Parameters

- lambda_function_name (required): The name of the existing Lambda function to connect to API Gateway
- api_name (required): The name for the new REST API Gateway
- region (optional): The AWS region where resources will be created. If not provided, uses the default region from AWS configuration
- stage_name (optional, default: "dev"): The deployment stage name for the API (use "prod" only for production deployments)
- resource_path (optional, default: "invoke"): The resource path for the API endpoint
- http_method (optional, default: "POST"): The HTTP method for the API endpoint
- authorization_type (optional, default: "AWS_IAM"): Authorization type - AWS_IAM, COGNITO_USER_POOLS, CUSTOM, or NONE
- enable_api_key (optional, default: false): Require API key for access (recommended for production)
- enable_cors (optional, default: false): Whether to enable CORS (Cross-Origin Resource Sharing) for the API

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

### 2. Validate Lambda Function Exists
Verify that the specified Lambda function exists and is accessible.

**Constraints:**

- You MUST check if the Lambda function exists using `aws lambda get-function`
- You MUST retrieve the Lambda function's ARN for later use
- You MUST abort the SOP if the Lambda function does not exist
- You SHOULD display the Lambda function's runtime and description for confirmation

### 3. Create REST API Gateway
Create a new REST API Gateway with the specified name.

**Constraints:**

- You MUST create the REST API using `aws apigateway create-rest-api`
- You MUST save the API ID for subsequent steps
- You MUST retrieve the root resource ID using `aws apigateway get-resources`
- You SHOULD verify the API was created successfully

### 4. Create API Resource
Create a new resource under the root resource with the specified path.

**Constraints:**

- You MUST create the resource using `aws apigateway create-resource`
- You MUST use the root resource ID as the parent
- You MUST save the new resource ID for method creation
- You MAY skip this step if using the root resource directly

### 5. Create HTTP Method
Create the specified HTTP method for the resource.

**Constraints:**

- You MUST create the method using `aws apigateway put-method`
- You MUST set authorization type to the specified authorization_type parameter
- You MUST warn user if using NONE authorization: "WARNING: Using NONE authorization allows unrestricted access. Consider AWS_IAM, API keys, or other authorization methods for production."
- You MUST add `--api-key-required` flag if enable_api_key is true
- You MUST configure the method to accept requests

### 6. Configure Lambda Integration
Set up the integration between the API method and Lambda function.

**Constraints:**

- You MUST create the integration using `aws apigateway put-integration`
- You MUST set integration type to "AWS_PROXY" for Lambda proxy integration
- You MUST use the Lambda function ARN in the integration URI
- You MUST set the HTTP method to "POST" for Lambda integration regardless of the API method
- You MUST include the AWS region in the integration URI

### 7. Configure Security Controls (Recommended for Production)

Configure additional security measures for production deployments.

**Constraints:**

- You MUST inform user about production security requirements:
  - **Authorization**: Use AWS_IAM, Cognito, or custom authorizers instead of NONE
  - **API Keys**: Enable API key requirement for access control
  - **Throttling**: Configure rate limiting to prevent abuse
  - **Input Validation**: Add request validation models
  - **Access Logging**: Enable CloudWatch logging for monitoring
  - **Security Headers**: Add security headers in Lambda response
  - **WAF**: Consider AWS WAF for additional protection
- You MUST provide commands for enabling throttling if requested:

  ```bash
  aws apigateway create-usage-plan --name {api_name}-usage-plan --throttle burstLimit=100,rateLimit=50 --region {region}
  aws apigateway create-api-key --name {api_name}-key --enabled --region {region}
  ```

- You MUST provide CloudWatch logging configuration if requested:

  ```bash
  aws logs create-log-group --log-group-name API-Gateway-Execution-Logs_{api_id}/{stage_name} --region {region}
  aws apigateway update-stage --rest-api-id {api_id} --stage-name {stage_name} --patch-ops op=replace,path=/accessLogSettings/destinationArn,value=arn:aws:logs:{region}:{account_id}:log-group:API-Gateway-Execution-Logs_{api_id}/{stage_name} --region {region}
  ```

### 8. Configure CORS (Conditional)
If CORS is enabled, configure Cross-Origin Resource Sharing settings for the API.

**Constraints:**

- You MUST check if `enable_cors` parameter is true before proceeding with this step
- If CORS is enabled, You MUST create an OPTIONS method using `aws apigateway put-method`
- You MUST add method response headers for CORS: `Access-Control-Allow-Origin`, `Access-Control-Allow-Headers`, `Access-Control-Allow-Methods`
- You MUST create a MOCK integration for the OPTIONS method
- You MUST configure integration responses with appropriate CORS headers
- If CORS is not enabled, You MUST skip this step entirely

### 9. Grant API Gateway Permission to Invoke Lambda
Add the necessary permissions for API Gateway to invoke the Lambda function.

**Constraints:**

- You MUST add permission using `aws lambda add-permission`
- You MUST set the principal to "apigateway.amazonaws.com"
- You MUST include the API Gateway execution ARN in the source ARN
- You MUST use a unique statement ID
- You SHOULD verify the permission was added successfully

### 10. Deploy the API
Deploy the API to the specified stage to make it accessible.

**Constraints:**

- You MUST deploy the API using `aws apigateway create-deployment`
- You MUST specify the stage name for deployment
- You MUST save the deployment ID
- You SHOULD verify the deployment was successful

### 11. Retrieve API Endpoint URL
Get the invoke URL for the deployed API.

**Constraints:**

- You MUST construct the invoke URL using the format: `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}/{resource-path}`
- You MUST display the complete endpoint URL to the user
- You SHOULD provide example curl commands for testing
- You MUST include the HTTP method in the usage instructions

### 12. Verify Lambda Response Format
Inform the user about the required response format for Lambda proxy integration.

**Constraints:**

- You MUST explain that the Lambda function must return a response in the following format for API Gateway proxy integration:

  ```json
  {
    "statusCode": 200,
    "headers": {
      "Content-Type": "application/json"
    },
    "body": "{\"message\": \"response data\"}"
  }
  ```

- You MUST inform the user that the `body` field must be a string (JSON stringified if returning JSON)
- You SHOULD provide a link or reference to AWS Lambda proxy integration documentation
- You MUST warn that incorrect response format will result in API Gateway errors

### 13. Test the Integration
Verify that the API Gateway can successfully invoke the Lambda function.

**Constraints:**

- You SHOULD attempt to test the integration using `aws apigateway test-invoke-method`
- You MUST provide the user with testing instructions
- You SHOULD show example request and response formats
- You MAY provide troubleshooting guidance if the test fails

## Examples

### Example Input

```
lambda_function_name: my-lambda-function
api_name: my-rest-api
region: us-east-1
stage_name: dev
resource_path: execute
http_method: POST
authorization_type: AWS_IAM
enable_api_key: true
enable_cors: true
```

### Example Output

```
API Gateway URL: https://abc123def4.execute-api.us-east-1.amazonaws.com/dev/execute

Test with curl (requires AWS IAM authentication):
aws apigateway test-invoke-method --rest-api-id abc123def4 --resource-id xyz789 --http-method POST --body '{"key": "value"}'
```

## Troubleshooting

### Lambda Function Not Found
If you receive an error that the Lambda function doesn't exist, verify the function name is correct and that you have permission to access it.

### Permission Denied Errors
If API Gateway cannot invoke the Lambda function, ensure the `lambda:InvokeFunction` permission was added correctly with the proper source ARN.

### API Gateway 502 Bad Gateway
This typically indicates an issue with the Lambda integration. Check that:

- The integration URI is correctly formatted
- The Lambda function is returning a proper response format for API Gateway proxy integration (see Step 13)
- The Lambda function must return an object with `statusCode`, `headers`, and `body` fields
- The `body` field must be a string (use `JSON.stringify()` for JSON responses)

### Malformed Lambda Proxy Response
If you receive errors about malformed responses, ensure your Lambda function returns:

```json
{
  "statusCode": 200,
  "headers": {
    "Content-Type": "application/json"
  },
  "body": "{\"key\": \"value\"}"
}
```

Note that `body` must be a string, not an object.

### CORS Errors in Browser
If you're getting CORS errors when calling the API from a web browser:

- Ensure you set `enable_cors: true` when creating the API
- Verify that the OPTIONS method was created successfully
- Check that CORS headers are properly configured in both method and integration responses
- Ensure your Lambda function also returns CORS headers in its response if needed

### Deployment Issues
If the API deployment fails, ensure all method and integration configurations are complete before attempting to deploy.
