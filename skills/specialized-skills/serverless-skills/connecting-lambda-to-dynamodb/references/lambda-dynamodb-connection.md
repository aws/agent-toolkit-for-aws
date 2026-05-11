# Connect Lambda Function to DynamoDB

## Overview

This SOP provides a systematic approach to connect a Lambda function to DynamoDB, including creating the necessary IAM execution role, Lambda function, DynamoDB table with streams, and event source mapping. It enables Lambda to process DynamoDB events and perform read/write operations.

## Parameters

- **function_name** (required): The name for the Lambda function
- **table_name** (required): The name for the DynamoDB table
- **runtime** (optional, default: "python3.12"): The Lambda runtime environment
- **aws_region** (optional, default: "us-east-1"): The AWS region where resources will be created
- **role_name** (optional, default: "lambda-dynamodb-role"): The name for the IAM execution role
- **partition_key_name** (optional, default: "id"): The name of the DynamoDB table's partition key
- **partition_key_type** (optional, default: "S"): The type of the partition key - S (String), N (Number), or B (Binary)

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods including:
  - Direct input: Values provided directly in the conversation
  - Configuration files: JSON or YAML configuration files
- You MUST validate that function_name follows AWS Lambda naming conventions (alphanumeric and hyphens only)
- You MUST validate that table_name follows DynamoDB naming conventions
- You MUST confirm successful acquisition of all parameters before proceeding

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context:
  - fs_write
  - call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort
- You MUST verify AWS CLI is properly configured with this command:

  ```
  aws sts get-caller-identity
  ```

### 2. Confirm Infrastructure Changes with User

Present the planned resources to the user for explicit approval before creating anything.

**Constraints:**

- You MUST present a summary of ALL resources that will be created:
  - IAM execution role (${role_name})
  - Lambda function (${function_name})
  - DynamoDB table (${table_name}) with partition key `${partition_key_name}` (${partition_key_type}) and streams enabled
  - Event source mapping between DynamoDB stream and Lambda
- You MUST list the target region
- You MUST wait for explicit user confirmation before proceeding
- You MUST NOT create any resources without user approval
- If the user declines, You MUST abort the procedure

### 3. Create IAM Execution Role

Create an IAM role that allows Lambda to access DynamoDB and write logs to CloudWatch.

**Constraints:**

- You MUST create a role with the name specified by the role_name parameter
- You MUST create the lambda with the runtime specified by the runtime parameter
- You MUST create a role with the trusted entity set to Lambda service
- You MUST attach the AWSLambdaDynamoDBExecutionRole managed policy
- You MUST wait for role creation to complete before proceeding
- You MUST capture and store the role ARN for later use
- You MUST handle cases where the role already exists gracefully

### 4. Create Lambda Function Code

Generate the Lambda function code that processes DynamoDB events.

**Constraints:**

- You MUST create a Python function that handles DynamoDB stream events
- You MUST include proper error handling and logging
- You MUST save the function code to a local file named `lambda_function.py`
- You MUST create a deployment package (ZIP file) containing the function code
- You SHOULD include JSON formatting for readable log output

### 5. Create Lambda Function

Deploy the Lambda function with the created IAM role.

**Constraints:**

- You MUST create the Lambda function using the deployment package
- You MUST use the IAM role ARN from step 3
- You MUST set appropriate timeout and memory settings
- You MUST verify the function was created successfully
- You MUST handle cases where the function already exists

### 6. Create DynamoDB Table

Create a DynamoDB table with streams enabled for Lambda integration.

**Constraints:**

- You MUST create a table with a primary key named ${partition_key_name} of type ${partition_key_type}
- You MUST enable DynamoDB streams with "NEW_AND_OLD_IMAGES" view type
- You MUST capture and store the stream ARN for event source mapping
- You MUST wait for table creation to complete
- You MUST handle cases where the table already exists
- You SHOULD recommend enabling encryption with a customer-managed KMS key (CMK) for production workloads, since the default AWS-owned key does not support key rotation control or cross-account access
- If the Lambda function is in a VPC, You SHOULD recommend creating a VPC gateway endpoint for DynamoDB to keep traffic off the public internet

### 7. Create Event Source Mapping

Connect the DynamoDB stream to the Lambda function.

**Constraints:**

- You MUST create an event source mapping between the DynamoDB stream and Lambda function
- You MUST set batch size to 100 and starting position to LATEST
- You MUST verify the event source mapping was created successfully
- You MUST capture the mapping UUID for future reference
- You SHOULD check the mapping status to ensure it's active

### 8. Test the Setup

Verify the end-to-end integration works correctly.

**Constraints:**

- You MUST create a test event file with sample DynamoDB stream data
- You MUST invoke the Lambda function with the test event
- You MUST verify the function executes successfully
- You MUST check CloudWatch logs for proper event processing
- You SHOULD provide instructions for testing with actual DynamoDB operations

### 9. Provide Usage Instructions

Give the user clear instructions on how to use the setup.

**Constraints:**

- You MUST provide examples of how to add, update, and delete items in the DynamoDB table
- You MUST explain how to monitor Lambda function execution in CloudWatch
- You MUST provide the ARNs and identifiers of all created resources
- You SHOULD include troubleshooting tips for common issues

## Examples

### Example Lambda Function Code

```python
import json

def lambda_handler(event, context):
    print(json.dumps(event, indent=2))

    for record in event['Records']:
        log_dynamodb_record(record)

    return {
        'statusCode': 200,
        'body': json.dumps('Successfully processed DynamoDB events')
    }

def log_dynamodb_record(record):
    print(f"Event ID: {record['eventID']}")
    print(f"Event Name: {record['eventName']}")
    print(f"DynamoDB Record: {json.dumps(record['dynamodb'])}")
```

### Example Test Event

```json
{
   "Records":[
      {
         "eventID":"1",
         "eventName":"INSERT",
         "eventVersion":"1.0",
         "eventSource":"aws:dynamodb",
         "awsRegion":"us-east-1",
         "dynamodb":{
            "Keys":{
               "id":{
                  "S":"test-item-1"
               }
            },
            "NewImage":{
               "id":{
                  "S":"test-item-1"
               },
               "message":{
                  "S":"Hello from DynamoDB!"
               }
            },
            "SequenceNumber":"111",
            "SizeBytes":26,
            "StreamViewType":"NEW_AND_OLD_IMAGES"
         }
      }
   ]
}
```

## Troubleshooting

### Lambda Function Not Triggering
If the Lambda function is not being triggered by DynamoDB events:

- Verify the event source mapping is active using `aws lambda list-event-source-mappings`
- Check that the DynamoDB stream is enabled and has the correct view type
- Ensure the Lambda function has the correct execution role permissions

### Permission Denied Errors
If you encounter permission errors:

- Verify the IAM role has the AWSLambdaDynamoDBExecutionRole policy attached
- Check that the role's trust policy allows Lambda service to assume it
- Ensure your AWS credentials have sufficient permissions to create resources

### Function Timeout Issues
If the Lambda function times out:

- Increase the function timeout setting (default is 3 seconds)
- Optimize the function code to process records more efficiently
- Consider adjusting the batch size in the event source mapping
