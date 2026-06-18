### Step 5: Create IAM Roles

Constraints:

- You MUST create four IAM roles: Lambda execution role, ECS task execution role, ECS task role, and Step Functions role
- For each trust policy, create a working copy from `scripts/` and replace ACCOUNT_ID:

  ```
  sed 's/ACCOUNT_ID/{account_id}/' scripts/lambda-trust-policy.json > /tmp/lambda-trust-policy.json
  sed 's/ACCOUNT_ID/{account_id}/' scripts/ecs-trust-policy.json > /tmp/ecs-trust-policy.json
  sed 's/ACCOUNT_ID/{account_id}/' scripts/stepfunctions-trust-policy.json > /tmp/stepfunctions-trust-policy.json
  sed 's/ACCOUNT_ID/{account_id}/' scripts/eventbridge-trust-policy.json > /tmp/eventbridge-trust-policy.json
  ```

- You MUST create the Lambda role with S3 read access:

  ```
  aws iam create-role --role-name sfn-lambda-role --assume-role-policy-document file:///tmp/lambda-trust-policy.json
  aws iam attach-role-policy --role-name sfn-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  aws iam put-role-policy --role-name sfn-lambda-role --policy-name s3-read --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::{bucket_name}/*"
    }]
  }'
  ```

- You MUST create the ECS task execution role (for pulling images and writing logs):

  ```
  aws iam create-role --role-name sfn-ecs-execution-role --assume-role-policy-document file:///tmp/ecs-trust-policy.json
  aws iam attach-role-policy --role-name sfn-ecs-execution-role --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
  ```

- You MUST create the ECS task role with only S3 read access (not Step Functions access):

  ```
  aws iam create-role --role-name sfn-ecs-task-role --assume-role-policy-document file:///tmp/ecs-trust-policy.json
  aws iam put-role-policy --role-name sfn-ecs-task-role --policy-name s3-read --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::{bucket_name}/*"
    }]
  }'
  ```

- You MUST create the Step Functions role with scoped permissions:

  ```
  aws iam create-role --role-name sfn-state-machine-role --assume-role-policy-document file:///tmp/stepfunctions-trust-policy.json
  ```

- You MUST attach a scoped policy to the Step Functions role:

  ```
  aws iam put-role-policy --role-name sfn-state-machine-role --policy-name sfn-policy --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": "lambda:InvokeFunction",
        "Resource": "arn:aws:lambda:{region}:{account_id}:function:sfn-file-processor"
      },
      {
        "Effect": "Allow",
        "Action": "ecs:RunTask",
        "Resource": "arn:aws:ecs:{region}:{account_id}:task-definition/StepFunctionFargateTask:*"
      },
      {
        "Effect": "Allow",
        "Action": "iam:PassRole",
        "Resource": [
          "arn:aws:iam::{account_id}:role/sfn-ecs-execution-role",
          "arn:aws:iam::{account_id}:role/sfn-ecs-task-role"
        ]
      },
      {
        "Effect": "Allow",
        "Action": [
          "events:PutTargets",
          "events:PutRule",
          "events:DescribeRule"
        ],
        "Resource": "arn:aws:events:{region}:{account_id}:rule/StepFunctionsGetEventsForECSTaskRule"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ecs:StopTask",
          "ecs:DescribeTasks"
        ],
        "Resource": [
          "arn:aws:ecs:{region}:{account_id}:cluster/sfn-cluster",
          "arn:aws:ecs:{region}:{account_id}:task/sfn-cluster/*"
        ]
      },
      {
        "Effect": "Allow",
        "Action": "states:StartExecution",
        "Resource": "arn:aws:states:{region}:{account_id}:stateMachine:{state_machine_name}"
      }
    ]
  }'
  ```

- You MUST create a separate EventBridge target role with only `states:StartExecution` permission:

  ```
  aws iam create-role --role-name sfn-eventbridge-role --assume-role-policy-document file:///tmp/eventbridge-trust-policy.json
  aws iam put-role-policy --role-name sfn-eventbridge-role --policy-name eventbridge-sfn-policy --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "states:StartExecution",
      "Resource": "arn:aws:states:{region}:{account_id}:stateMachine:{state_machine_name}"
    }]
  }'
  ```

- You MUST wait at least 10 seconds for IAM role propagation
