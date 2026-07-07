# ECS / Fargate — RDS SQL Server

Container tasks connecting to RDS SQL Server in the same VPC (or peered).

## Networking

- Tasks use `awsvpc` networking mode — each task gets an ENI in a subnet
- Task SG inbound: none required (outbound-only for DB connections)
- Task SG outbound: allow 1433 → RDS SG, 443 → Secrets Manager / STS
- RDS SG inbound: 1433 from task SG (by SG ID)

```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-sqlserver \
  --protocol tcp --port 1433 \
  --source-group sg-ecs-task
```

For Fargate in private subnets without internet access, create VPC endpoints for:

- `com.amazonaws.<region>.secretsmanager`
- `com.amazonaws.<region>.ecr.dkr` and `com.amazonaws.<region>.ecr.api` (for ECR image pulls)
- `com.amazonaws.<region>.s3` (gateway — for ECR image layers)
- `com.amazonaws.<region>.logs` (CloudWatch Logs)

## Secrets injection — two approaches

### Approach 1: Inject at container start (recommended)

ECS resolves the secret before the container runs. The secret value appears as an environment variable:

```json
{
  "containerDefinitions": [
    {
      "name": "app",
      "image": "111122223333.dkr.ecr.us-east-1.amazonaws.com/app:latest",
      "secrets": [
        {
          "name": "DB_SECRET",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:111122223333:secret:rds/sqlserver/app-AbCdEf"
        }
      ]
    }
  ],
  "executionRoleArn": "arn:aws:iam::111122223333:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::111122223333:role/app-task-role",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"]
}
```

**Critical**: `secrets` requires `executionRoleArn` (not `taskRoleArn`) to have `secretsmanager:GetSecretValue` permission. This is the most common ECS secrets misconfiguration.

Execution role policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:111122223333:secret:rds/sqlserver/app-*"
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "arn:aws:kms:us-east-1:111122223333:key/<kms-key-id>"
    }
  ]
}
```

Parse JSON in the container:

```python
import os, json
creds = json.loads(os.environ["DB_SECRET"])
conn = pymssql.connect(
    server=creds["host"], port="1433",
    user=creds["username"], password=creds["password"], database=creds["dbname"],
    tds_version="7.3", encryption="require",
)
```

### Approach 2: Fetch at runtime via task role

App code calls `secretsmanager:GetSecretValue` directly using the task role. Useful for rotation-aware apps:

```python
import boto3, json, os
sm = boto3.client("secretsmanager")
c = json.loads(sm.get_secret_value(SecretId=os.environ["SECRET_ARN"])["SecretString"])
```

Task role needs `secretsmanager:GetSecretValue` + `kms:Decrypt`. Execution role just needs container image pull permissions.

Approach 2 handles rotation better: app can re-fetch after an 18456 error. Approach 1 requires a task restart to pick up rotated secrets.

## Windows auth on Fargate

- **Windows containers on Fargate**: gMSA (Group Managed Service Account) is supported
- **Linux containers**: must manage Kerberos tickets explicitly — mount keytab or KRB5CCNAME

### gMSA for Windows containers

```json
{
  "containerDefinitions": [{
    "name": "app",
    "image": "...",
    "credentialSpecs": [
      "credentialspec:arn:aws:s3:::my-bucket/app-gmsa.json"
    ]
  }]
}
```

See `ad-kerberos.md` for domain join + gMSA setup.

## Connection pooling

For long-running tasks, use a proper pool:

- Python: SQLAlchemy `QueuePool` (pool_size=5, max_overflow=10)
- Java: HikariCP (maximumPoolSize=10)
- .NET: ADO.NET built-in (`Max Pool Size=20`)
- Node.js: `mssql` built-in (`pool: { max: 10 }`)

Pool size should be tuned to ECS task count × concurrent requests per task. RDS can handle thousands of connections but each one costs memory.

## Full Fargate task definition (Python + pymssql)

```json
{
  "family": "app",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::111122223333:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::111122223333:role/app-task-role",
  "containerDefinitions": [
    {
      "name": "app",
      "image": "111122223333.dkr.ecr.us-east-1.amazonaws.com/app:v1.0.0",
      "essential": true,
      "portMappings": [{ "containerPort": 8080, "protocol": "tcp" }],
      "environment": [
        { "name": "AWS_REGION", "value": "us-east-1" }
      ],
      "secrets": [
        {
          "name": "DB_SECRET",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:111122223333:secret:rds/sqlserver/app-AbCdEf"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/app",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "app"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3
      }
    }
  ]
}
```

## Service — with ALB

```bash
aws ecs create-service \
  --cluster my-cluster \
  --service-name app \
  --task-definition app:1 \
  --desired-count 3 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-priv-a,subnet-priv-b],securityGroups=[sg-ecs-task],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=arn:...,containerName=app,containerPort=8080"
```

`assignPublicIp=DISABLED` keeps tasks in private subnets. Use VPC endpoints for AWS service access.

## Health check endpoint

```python
# Flask
@app.route("/health")
def health():
    try:
        cur = pool.connection().cursor()
        cur.execute("SELECT 1")
        return {"status": "ok"}, 200
    except Exception as e:
        return {"status": "error", "detail": str(e)}, 503
```

Return 200 only when DB is reachable. ALB will replace unhealthy tasks.

## Rolling updates during Multi-AZ failover

During RDS Multi-AZ failover:

- Existing connections fail (error 18456 or network disconnect)
- New connections (after ~60-120s) succeed against the new primary

App behavior:

- Pools with `pool_pre_ping` / `connectionTestQuery` recover cleanly
- Pools without will serve errors for the failover duration

For minimum downtime:

- HikariCP: `maxLifetime=1800000` (30 min), `validationTimeout=5000`
- SQLAlchemy: `pool_pre_ping=True, pool_recycle=1800`

## Verify from inside a task

```bash
aws ecs execute-command \
  --cluster my-cluster \
  --task <task-arn> \
  --container app \
  --interactive \
  --command "/bin/sh"

# inside the container:
nc -zv mydb.xxxx.us-east-1.rds.amazonaws.com 1433
```

Requires `enableExecuteCommand: true` on the service and task role permissions for SSM (`ssmmessages:CreateControlChannel` etc.).
