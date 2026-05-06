# Fargate Service Deployment Reference

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [Create Cluster](#create-cluster)
- [Register Task Definition](#register-task-definition)
- [Create Application Load Balancer](#create-application-load-balancer)
- [Create Target Group](#create-target-group)
- [Create ALB Listener](#create-alb-listener)
- [Create ECS Service](#create-ecs-service)
- [Verify Service Health](#verify-service-health)
- [Private Subnet Networking](#private-subnet-networking)
- [502 Bad Gateway Debugging Checklist](#502-bad-gateway-debugging-checklist)
- [Path-Based Routing](#path-based-routing)
- [Security Considerations](#security-considerations)

---

## Verify Dependencies

Before deploying a Fargate service, the operator MUST confirm:

1. A registered task definition `$TASK_DEFINITION` exists.
2. A VPC (`$VPC_ID`) with at least two subnets (`$SUBNET_1`, `$SUBNET_2`) in different AZs exists.
3. Security groups for the ALB (`$ALB_SG_ID`) and tasks (`$TASK_SG_ID`) exist.
4. The execution role and task role referenced in the task definition exist.
5. An ACM certificate (`$ACM_CERT_ARN`) exists for the ALB HTTPS listener.

**Constraints for parameter acquisition:**

- You MUST verify all required parameters (`$CLUSTER`, `$TASK_DEFINITION`, `$SUBNET_1`, `$SUBNET_2`, `$ALB_SG_ID`, `$TASK_SG_ID`, `$CONTAINER_NAME`, `$CONTAINER_PORT`) are provided. If any are missing, ask for them upfront in a single prompt.
- If all required parameters are provided, proceed to Step 1 — do not ask the user to confirm what they already specified.
- For optional parameters not specified by the user (`$SERVICE_NAME`, `$CLUSTER` name, health check path), you SHOULD select reasonable defaults, inform the user what you chose, and proceed.

```bash
aws sts get-caller-identity --output json
aws ecs describe-task-definition \
  --task-definition "$TASK_DEFINITION" \
  --region "$REGION" \
  --output json
aws ec2 describe-subnets \
  --subnet-ids "$SUBNET_1" "$SUBNET_2" \
  --region "$REGION" \
  --output json
```

---

## Create Cluster

```bash
aws ecs create-cluster \
  --cluster-name "$CLUSTER" \
  --settings name=containerInsights,value=enabled \
  --region "$REGION" \
  --output json
```

The operator SHOULD enable Container Insights for observability.

---

## Register Task Definition

If not already registered, register the task definition from a JSON file:

```bash
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region "$REGION" \
  --output json
```

See [task-definition-authoring.md](task-definition-authoring.md) for the task definition structure.

---

## Create Application Load Balancer

```bash
aws elbv2 create-load-balancer \
  --name "$ALB_NAME" \
  --subnets "$SUBNET_1" "$SUBNET_2" \
  --security-groups "$ALB_SG_ID" \
  --scheme internet-facing \
  --type application \
  --region "$REGION" \
  --output json
```

The ALB security group MUST allow inbound traffic on the listener ports:

```json
[
  {
    "IpProtocol": "tcp",
    "FromPort": 443,
    "ToPort": 443,
    "IpRanges": [
      { "CidrIp": "$ALLOWED_CIDR", "Description": "Inbound HTTPS from allowed range" }
    ]
  },
  {
    "IpProtocol": "tcp",
    "FromPort": 80,
    "ToPort": 80,
    "IpRanges": [
      { "CidrIp": "$ALLOWED_CIDR", "Description": "Inbound HTTP for HTTPS redirect" }
    ]
  }
]
```

The task security group MUST allow inbound traffic from the ALB security group on the container port:

```json
{
  "IpProtocol": "tcp",
  "FromPort": $CONTAINER_PORT,
  "ToPort": $CONTAINER_PORT,
  "UserIdGroupPairs": [
    { "GroupId": "$ALB_SG_ID", "Description": "Inbound from ALB" }
  ]
}
```

---

## Create Target Group

For Fargate with `awsvpc` networking, the target type MUST be `ip`.

```bash
aws elbv2 create-target-group \
  --name "$TG_NAME" \
  --protocol HTTP \
  --port $CONTAINER_PORT \
  --vpc-id "$VPC_ID" \
  --target-type ip \
  --health-check-path "/health" \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 2 \
  --region "$REGION" \
  --output json
```

### Health Check Configuration

| Parameter                        | Recommended Value | Notes                                         |
|----------------------------------|-------------------|-----------------------------------------------|
| `health-check-path`             | `/health`         | MUST return HTTP 200 when the app is ready.   |
| `health-check-interval-seconds` | 30                | SHOULD be 10–30s.                             |
| `health-check-timeout-seconds`  | 5                 | SHOULD be less than the interval.             |
| `healthy-threshold-count`       | 2                 | Minimum consecutive successes to mark healthy.|
| `unhealthy-threshold-count`     | 2                 | Consecutive failures before marking unhealthy.|

### Deregistration Delay

The operator SHOULD set deregistration delay to 30–60 seconds to allow in-flight requests to complete:

```bash
aws elbv2 modify-target-group-attributes \
  --target-group-arn "$TG_ARN" \
  --attributes Key=deregistration_delay.timeout_seconds,Value=30 \
  --region "$REGION" \
  --output json
```

---

## Create ALB Listener

The operator MUST create an HTTPS listener with an ACM certificate for encryption in transit. Per [AWS ECS Network Security Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-network.html): "If your service is fronted by a public facing load balancer, use TLS/SSL to encrypt the traffic from the client's browser to the load balancer."

```bash
aws elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" \
  --protocol HTTPS \
  --port 443 \
  --ssl-policy "ELBSecurityPolicy-TLS13-1-2-2021-06" \
  --certificates CertificateArn="$ACM_CERT_ARN" \
  --default-actions Type=forward,TargetGroupArn="$TG_ARN" \
  --region "$REGION" \
  --output json
```

The operator SHOULD also create an HTTP-to-HTTPS redirect listener:

```bash
aws elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" \
  --protocol HTTP \
  --port 80 \
  --default-actions 'Type=redirect,RedirectConfig={Protocol=HTTPS,Port=443,StatusCode=HTTP_301}' \
  --region "$REGION" \
  --output json
```

---

## Create ECS Service

```bash
aws ecs create-service \
  --cluster "$CLUSTER" \
  --service-name "$SERVICE_NAME" \
  --task-definition "$TASK_DEFINITION" \
  --desired-count 2 \
  --launch-type FARGATE \
  --platform-version "LATEST" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$TASK_SG_ID],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=$CONTAINER_NAME,containerPort=$CONTAINER_PORT" \
  --health-check-grace-period-seconds 90 \
  --deployment-configuration "minimumHealthyPercent=100,maximumPercent=200,deploymentCircuitBreaker={enable=true,rollback=true}" \
  --region "$REGION" \
  --output json
```

### Deployment Configuration

| Parameter              | Recommended Value | Notes                                                   |
|------------------------|-------------------|---------------------------------------------------------|
| `minimumHealthyPercent`| 100               | Keeps all existing tasks running during deployment.     |
| `maximumPercent`       | 200               | Allows double the desired count during rolling update.  |

### Health Check Grace Period

The `healthCheckGracePeriodSeconds` SHOULD be set when using a load balancer to prevent ECS from marking tasks unhealthy before the application finishes starting. CDK defaults to 60 seconds when a load balancer is attached.

| Application Type       | Recommended Value |
|------------------------|-------------------|
| Lightweight apps       | 60 seconds        |
| JVM-based apps         | 90–120 seconds    |
| Apps with DB migrations| 120+ seconds      |

### Circuit Breaker with Rollback

The operator SHOULD enable the deployment circuit breaker with rollback. When enabled, ECS automatically rolls back to the last stable deployment if the new deployment fails to reach a steady state.

---

## Verify Service Health

```bash
aws ecs describe-services \
  --cluster "$CLUSTER" \
  --services "$SERVICE_NAME" \
  --region "$REGION" \
  --output json

aws ecs list-tasks \
  --cluster "$CLUSTER" \
  --service-name "$SERVICE_NAME" \
  --desired-status RUNNING \
  --region "$REGION" \
  --output json

aws elbv2 describe-target-health \
  --target-group-arn "$TG_ARN" \
  --region "$REGION" \
  --output json
```

The operator MUST verify:

1. `runningCount` equals `desiredCount` in the service description.
2. All targets in the target group report `healthy`.
3. No deployment events show errors in the service `events` list.

---

## Private Subnet Networking

When tasks run in private subnets with `assignPublicIp=DISABLED`, they MUST have a path to reach AWS service endpoints.

### Option 1: NAT Gateway

Tasks route through a NAT gateway in a public subnet. This is simpler but incurs NAT gateway data processing charges.

### Option 2: VPC Endpoints (Recommended for Cost Optimization)

The operator SHOULD create VPC endpoints to avoid NAT gateway costs for AWS service traffic:

| Endpoint                          | Type      | Required For                   |
|-----------------------------------|-----------|--------------------------------|
| `com.amazonaws.$REGION.ecr.dkr`  | Interface | Pulling images from ECR        |
| `com.amazonaws.$REGION.ecr.api`  | Interface | ECR API calls (auth, describe) |
| `com.amazonaws.$REGION.s3`       | Gateway   | ECR image layer storage in S3  |
| `com.amazonaws.$REGION.logs`     | Interface | CloudWatch Logs                |

Interface endpoints MUST have a security group allowing inbound HTTPS (port 443) from the task security group:

```json
{
  "IpProtocol": "tcp",
  "FromPort": 443,
  "ToPort": 443,
  "UserIdGroupPairs": [
    { "GroupId": "$TASK_SG_ID", "Description": "HTTPS from ECS tasks" }
  ]
}
```

> Without either a NAT gateway or VPC endpoints, tasks in private subnets fail to pull images and push logs.

---

## 502 Bad Gateway Debugging Checklist

When the ALB returns HTTP 502, the operator MUST check these items in order:

1. **Target group health** — Run `describe-target-health`. If targets are `unhealthy`, the application is not responding on the health check path. Check application logs in CloudWatch.
2. **Security group rules** — Confirm the task security group allows inbound from the ALB security group on the container port. Confirm the ALB security group allows inbound on the listener ports.
3. **Container port mismatch** — Verify the `containerPort` in the task definition matches the port the application listens on, and matches the target group port.
4. **Health check grace period** — If tasks are being killed before the application starts, increase `healthCheckGracePeriodSeconds`.
5. **Application crash** — Check CloudWatch Logs for the task. If the container exits immediately, inspect the `stoppedReason`:

```bash
aws ecs describe-tasks \
  --cluster "$CLUSTER" \
  --tasks "$TASK_ARN" \
  --region "$REGION" \
  --output json
```

---

## Path-Based Routing

To route different URL paths to different target groups, create ALB listener rules.

### Create Additional Target Group

```bash
aws elbv2 create-target-group \
  --name "$TG_NAME_API" \
  --protocol HTTP \
  --port $CONTAINER_PORT \
  --vpc-id "$VPC_ID" \
  --target-type ip \
  --health-check-path "/api/health" \
  --region "$REGION" \
  --output json
```

### Create Listener Rule

```bash
aws elbv2 create-rule \
  --listener-arn "$LISTENER_ARN" \
  --priority 10 \
  --conditions Field=path-pattern,Values='/api/*' \
  --actions Type=forward,TargetGroupArn="$TG_ARN_API" \
  --region "$REGION" \
  --output json
```

Rules are evaluated in priority order (lowest number first). The default action on the listener acts as a catch-all for unmatched paths.

The operator SHOULD assign priorities with gaps (e.g., 10, 20, 30) to allow inserting new rules later without reordering.

---

## Security Considerations

The operator SHOULD review the following security controls for production deployments:

- **HTTPS/TLS**: The ALB listener MUST use HTTPS with an ACM certificate. HTTP traffic SHOULD redirect to HTTPS (see [Create ALB Listener](#create-alb-listener)). Per [AWS ECS Network Security Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-network.html): "use TLS/SSL to encrypt the traffic from the client's browser to the load balancer."
- **AWS WAF**: The operator SHOULD associate an AWS WAF web ACL with the ALB for defense in depth against common web exploits (SQL injection, XSS, rate limiting).
- **ALB access logs**: The operator SHOULD enable ALB access logs to an S3 bucket for audit and troubleshooting. See [Enable access logs for your ALB](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/enable-access-logging.html).
- **VPC Flow Logs**: Per [AWS ECS best practices](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-network.html): "Use Amazon VPC Flow Logs to analyze the traffic to and from long-running tasks." The operator SHOULD enable VPC Flow Logs for the subnets running Fargate tasks.
- **Security headers**: The application SHOULD return security headers (Strict-Transport-Security, Content-Security-Policy, X-Content-Type-Options, X-Frame-Options) in HTTP responses.
