### Step 8: Create the ECS Cluster and Task Definition

Constraints:

- You MUST create the ECS cluster:
  `aws ecs create-cluster --cluster-name sfn-cluster --capacity-providers FARGATE --region {region}`
- You MUST register the task definition with:

  ```
  aws ecs register-task-definition \
      --family StepFunctionFargateTask \
      --cpu 1024 \
      --memory 8192 \
      --network-mode awsvpc \
      --requires-compatibilities FARGATE \
      --execution-role-arn arn:aws:iam::{account_id}:role/sfn-ecs-execution-role \
      --task-role-arn arn:aws:iam::{account_id}:role/sfn-ecs-task-role \
      --runtime-platform cpuArchitecture=X86_64,operatingSystemFamily=LINUX \
      --container-definitions '[{
        "name": "StepFunctionFargateTask1",
        "image": "{account_id}.dkr.ecr.{region}.amazonaws.com/{ecr_repo_name}:latest",
        "cpu": 1024,
        "memory": 8192,
        "logConfiguration": {
          "logDriver": "awslogs",
          "options": {
            "awslogs-group": "/StepFunctionFargateTask",
            "awslogs-region": "{region}",
            "awslogs-stream-prefix": "containerlog"
          }
        }
      }]' \
      --region {region}
  ```

- You MUST capture the task definition ARN from the response
