---
_fragment: infra-compute
_of_phase: generate
_contributes:
  - terraform/compute.tf
---

# Generate compute.tf

This fragment is the only writer of `terraform/compute.tf`; `artifacts-infra` writes the other Terraform files. Apply this guidance only to design rows routed to `terraform/compute.tf`. Network, data, storage, and delivery resources stay with their own guidance; reference them by variable or resource address and do not re-create them here.

This fragment owns three shared addresses that other fragments (for example `workflow.tf` ECS tasks) reference by name: the cluster `aws_ecs_cluster.main`, the task execution role `aws_iam_role.ecs_execution`, and the task role `aws_iam_role.ecs_task`. Declare them under exactly these addresses whenever this fragment runs, including for an Express-only stack (Express takes the cluster and `execution_role_arn`) and for a stack whose only ECS rows are Workflow ECS tasks. Network owns `aws_security_group.data`, the Cloud Map namespace, and the Cloud Map service.

## Common rules

- Emit one resource set per design row and tag it `SourceResourceId = "<source_resource_id>"`.
- Name resources `"${local.name_prefix}-<role>"`, unique per source resource. Target group names are at most 32 characters and Scheduler schedule names at most 64.
- Read `aws_config.vcpu`, `memory_gb`, `desired_count`, `graceful_shutdown_seconds`, `time_zone`, `duration_minutes`, and the architecture from `aws-design.json` when present. Never invent counts or sizes beyond the fallbacks below.
- Fallbacks when `aws_config` omits a field (the representative design omits them for `rr-private`, `rr-worker`, and `rr-cron`). Generate resolves them without returning to Design:
  - `vcpu` and `memory_gb`: resolve the captured plan through `knowledge/design/service-plan-fargate-sizing.json` and take the smallest valid pair. With no resolvable plan, use 0.5 vCPU and 1 GB (`cpu = 512`, `memory = 1024`).
  - `desired_count`: preserve the captured instance count. With none captured, use 1. Never default to 2.
  - `time_zone`: `UTC`. `graceful_shutdown_seconds`: omit `stopTimeout` so the ECS default applies.
  - `duration_minutes` has no fallback. It is required only for Lambda and Batch timeouts. If it is absent there, return to Design.
- Images come only from per-service `<name>_image` variables holding an ECR digest reference. Never use `:latest` or a mutable tag.
- Secrets use Secrets Manager or Parameter Store ARNs only: `secrets = [{ name, valueFrom }]` for ECS, `aws:elasticbeanstalk:application:environmentsecrets` for Elastic Beanstalk, and a runtime lookup for Lambda. Never put a secret in an `environment` value. A JSON secret key uses `${arn}:key::`.
- IAM trust policies name the exact service principal. Every Allow lists actions and resource ARNs. Never use `Action = "*"`. Use `Resource = "*"` only where the API requires it, in its own statement. Build managed-policy ARNs with `data.aws_partition.current.partition`. Never write a literal account ID.
- Architecture defaults to x86_64 unless the design records `arm64`. For `arm64`, set `runtime_platform { cpu_architecture = "ARM64" }` on ECS, `architectures = ["arm64"]` on Lambda, or Graviton instance types.
- Create every log group in Terraform with `retention_in_days` set (the resolved Clarify answer `observability.log_retention`, default 30 days; for Elastic Beanstalk `RetentionInDays` round up to an accepted value). Never rely on implicit log group creation.

## ECS on Fargate: Express vs standard mode

Branch each Fargate mapping on `aws_config.ecs_mode`. A mapping with no `ecs_mode` key is `"standard"`, never an error and never `"express"`.

- `"express"`: emit one `aws_ecs_express_gateway_service` (provider 6.23.0 or newer, `cpu_architecture` 6.71.0 or newer) instead of the task definition, `aws_ecs_service`, ALB, target group, and listener. Pass `cluster`, `execution_role_arn`, `infrastructure_role_arn` (one IAM role per design, trusting `ecs.amazonaws.com`, attached to `arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices`), a `service_name` containing the sanitized Render service name, `wait_for_steady_state = true`, `cpu` and `memory` within 256 to 4096 units and 512 to 8192 MiB, `cpu_architecture`, `primary_container` (image digest from ECR promotion, port, log group, `environment`, `secret` references only), `network_configuration`, `scaling_target`, and `health_check_path`. Subnets follow `aws_config.placement`: public placement uses the public subnets and records the accepted deviation from the private-subnet rule as a non-blocking `ecs_express_public_subnet_placement` warning and in the Terraform README. Output `ingress_paths[0].endpoint` as the service URL. Add `depends_on` on the infrastructure role's policy attachment. Emit no separate ALB for this service. Express rows skip the target group and listener, so the target group, listener and `depends_on` rules in the sections below apply only to `"standard"` rows.
- `"standard"`: emit the existing task definition, service, and ALB set. Write the deployment strategy explicitly from `compute.release_strategy`: `rolling` means no `deployment_controller` block; `blue_green` on a load-balanced service means `deployment_controller { type = "CODE_DEPLOY" }`, a green target group, a test listener, and CodeDeploy resources; `canary` (answered or defaulted) where Express was ruled out means a rolling update plus a non-blocking `ecs_express_not_selected_rolling_release` warning for that service, naming `ecs_mode_reason` and repeated in the Terraform README. The warning applies when `ecs_mode_reason` is anything other than `release_strategy`, `no_http_listener`, or `private_discovery`: the user got canary by default or by choice and loses it, and a service with no `compute.release_strategy` answer (worker, cron, private discovery) never warns.

## ECS on Fargate: public web service

Required resources: cluster with Container Insights, log group, execution role, task role, task definition, service, and an ALB target group with `target_type = "ip"`. The listener and certificate belong to network guidance; the service only references the target group.

- Execution role: trust `ecs-tasks.amazonaws.com`, attach `AmazonECSTaskExecutionRolePolicy`, and add an inline policy scoped to the exact secret and parameter ARNs (`secretsmanager:GetSecretValue`, `ssm:GetParameters`, and `kms:Decrypt` on the key that encrypts any referenced secret). That key is the customer-managed key the design names, or the data-tier key `aws_kms_key.stack` from `kms.tf` when it exists and the secret (for example the database master secret) is encrypted with it. Scope the statement to those exact key ARNs, and omit it when every referenced secret uses an AWS-managed key.
- Task role: application permissions only, empty by default, never the same role as the execution role. Add the `ssmmessages` channel actions only when `enable_execute_command = true`.
- Task definition: `network_mode = "awsvpc"`, `requires_compatibilities = ["FARGATE"]`, a valid Fargate cpu/memory pair, `essential = true`, an `awslogs` log configuration, `stopTimeout` from `graceful_shutdown_seconds` (Fargate maximum 120), and `readonlyRootFilesystem = true` where the source allows it. Add a container `healthCheck` (command, interval, timeout, retries, `startPeriod`) when the source declares a health path and no load balancer health check already covers that path. When an ALB target group checks the path, omit the container `healthCheck`.
- Service: `launch_type = "FARGATE"`, `desired_count` from design, private subnets with `assign_public_ip = false`, `health_check_grace_period_seconds` behind an ALB, `deployment_circuit_breaker { enable = true, rollback = true }`, explicit `deployment_minimum_healthy_percent` and `deployment_maximum_percent`, and `depends_on` the listener.
- Autoscaling: when `monitoring.tf` attaches an `aws_appautoscaling_target` to a service (its `desired_count` is greater than 1 or the design records a scaling preference), write `lifecycle { ignore_changes = [desired_count] }` on that `aws_ecs_service` here, so `monitoring.tf` never edits `compute.tf`.
- Anti-patterns: public IPs on tasks, a public ALB for private or worker services, one role serving as both task and execution role, `latest` tags, secrets in `environment`, missing log retention.

## ECS on Fargate: private service

Follow the public web rules without a public ALB or public ingress.

- Set `service_registries` on the ECS service from the network output `service_discovery_service_arn`. Do not declare the Cloud Map namespace or `aws_service_discovery_service` here; `network.tf` owns both.
- Allow security group ingress only from the named caller security groups.
- For EFS, declare the task `volume` with `transit_encryption = "ENABLED"` and an access point, add `mountPoints` to the container, and set `depends_on = [aws_efs_mount_target.<name>]` on the service so each mount target exists before tasks start.
- Add an internal ALB only when the design row says so.

## ECS on Fargate: background worker

- Service without a load balancer or port mappings and without `service_registries` unless the design requires one.
- Set `stopTimeout` from `graceful_shutdown_seconds`, `desired_count` from design, and the deployment circuit breaker.
- Never convert a continuously supervised worker into a Lambda function or Scheduler task.

## EventBridge Scheduler + ECS RunTask

Required resources: a task definition that logs to a retained log group (its own group, or the shared application log group with its own stream prefix) and uses execution and task roles (its own, or the shared ECS roles), an `aws_scheduler_schedule`, and a scheduler role trusting `scheduler.amazonaws.com`.

- Schedule: `schedule_expression`, `schedule_expression_timezone` from `aws_config.time_zone`, `flexible_time_window { mode = "OFF" }`, `retry_policy`, and `ecs_parameters` with `task_definition_arn`, `launch_type`, `task_count = 1`, and a private `network_configuration`.
- Scheduler role policy: `ecs:RunTask` on the exact task definition ARN with an `ArnLike` condition on `ecs:cluster`, and `iam:PassRole` on only the task role and execution role ARNs with `iam:PassedToService = ecs-tasks.amazonaws.com`.
- Anti-patterns: `ecs:*`, `Resource = "*"`, overlapping runs without a concurrency note, `task_count` above 1.

## AWS Lambda (cron or finite task)

Required resources: `aws_lambda_function`, an explicit log group named `/aws/lambda/<function name>`, an execution role trusting `lambda.amazonaws.com`, and an SQS dead-letter queue.

- Function: `package_type = "Image"` with `image_uri = var.<name>_image` (a zip package only when the design says so), `timeout` from `duration_minutes` (at most 900 seconds), `memory_size`, `architectures`, `reserved_concurrent_executions = 1` for cron overlap protection, `dead_letter_config`, and `depends_on` the log group.
- Execution role: `logs:CreateLogStream` and `logs:PutLogEvents` on that log group only, plus `sqs:SendMessage` on the dead-letter queue. Do not attach `AWSLambdaBasicExecutionRole` and widen it. Attach `AWSLambdaVPCAccessExecutionRole` only when the design places the function in a VPC.
- Schedule: `schedule_expression_timezone`, `retry_policy`, and `dead_letter_config`, with `arn = aws_lambda_function.<name>.arn`. The scheduler role gets `lambda:InvokeFunction` on only that function ARN; no `aws_lambda_permission` is needed for a role-based Scheduler target.
- Environment values are non-secret only.
- Do not set `tracing_config { mode = "Active" }` unless the design asks for tracing. If it does, add `xray:PutTraceSegments` and `xray:PutTelemetryRecords` on `Resource = "*"` as a separate statement in the execution role.
- Anti-patterns: Lambda for work longer than 15 minutes, Lambda for a continuous worker, `Resource = "*"`, unbounded retries.

## Elastic Beanstalk (traditional)

Emit one `aws_elastic_beanstalk_application` and one `aws_elastic_beanstalk_environment` per source service.

- `solution_stack_name` comes from `data "aws_elastic_beanstalk_solution_stack"` with `most_recent = true` and a `name_regex`. Never paste a platform label.
- Instance profile: an `aws_iam_role` trusting `ec2.amazonaws.com`, an `aws_iam_instance_profile`, and the partition-built `AWSElasticBeanstalkWebTier` (web) or `AWSElasticBeanstalkWorkerTier` (worker) and `AmazonSSMManagedInstanceCore` policies. Scope secret access with an inline policy on the exact secret ARNs.
- Service role: trust `elasticbeanstalk.amazonaws.com`, attach `AWSElasticBeanstalkEnhancedHealth` and `AWSElasticBeanstalkManagedUpdatesCustomerRolePolicy`.
- Required `setting` blocks, all tiers:
  - `aws:autoscaling:launchconfiguration`: `IamInstanceProfile`, `InstanceType` (from `knowledge/design/service-plan-eb-sizing.json`), `SecurityGroups`.
  - `aws:autoscaling:asg`: `MinSize` (at least 1) and `MaxSize`.
  - `aws:ec2:vpc`: `VPCId`, `Subnets`, `AssociatePublicIpAddress = "false"`.
  - `aws:elasticbeanstalk:environment`: `ServiceRole`.
  - `aws:elasticbeanstalk:healthreporting:system`: `SystemType = "enhanced"`.
  - `aws:elasticbeanstalk:command`: `DeploymentPolicy` (`Rolling` by default, `Immutable` when the design asks).
  - `aws:elasticbeanstalk:cloudwatch:logs`: `StreamLogs = "true"` and `RetentionInDays`, which accepts only 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, or 3653 (round up).
  - `aws:elasticbeanstalk:application:environmentsecrets`: one entry per secret.
- Web tier only (web and private services):
  - `aws:ec2:vpc`: `ELBSubnets` and `ELBScheme` (`public` only for a public web service, otherwise `internal`).
  - `aws:elasticbeanstalk:environment`: `EnvironmentType = "LoadBalanced"`, `LoadBalancerType = "application"`.
  - `aws:elasticbeanstalk:environment:process:default`: `HealthCheckPath`, `Port`.
  - HTTPS: `aws:elbv2:listener:443` with `Protocol = "HTTPS"` (the Application Load Balancer default is HTTP), `SSLCertificateArns` from the already-issued certificate variable, and a TLS 1.2 or newer `SSLPolicy`.
  - Default listener: `aws:elbv2:listener:default` is enabled on port 80 by default. Set `ListenerEnabled = "false"` on it, or use it only as a redirect to HTTPS. Never serve traffic from it.
- Worker tier only (background workers): set `tier = "Worker"` on the environment. Emit no ELB, listener, `HealthCheckPath`, or HTTPS settings. Add `aws:elasticbeanstalk:sqsd` settings (`WorkerQueueURL` or the managed queue, `HttpPath`, `MaxRetries`) when the worker consumes a queue.
- Anti-patterns: pasted platform names, `MinSize = 0`, public instances, an HTTP-only listener on a public environment, secrets in `aws:elasticbeanstalk:application:environment`.

## Elastic Beanstalk Cluster Mode and Amazon EKS

- Elastic Beanstalk Cluster Mode is service-managed Kubernetes with the Beanstalk application and environment lifecycle. Confirm the pinned AWS provider has a resource for it before emitting anything. If it does not, emit no resource, record `unsupported` in `generation-warnings.json` with the design row id, and do not invent resource types.
- Amazon EKS cluster: `aws_eks_cluster` with private endpoint access on and public access off unless the design says otherwise, envelope encryption of secrets with a KMS key, all five control plane log types enabled, and `access_config { authentication_mode = "API" }`. Its role trusts `eks.amazonaws.com` and attaches `AmazonEKSClusterPolicy`.
- Compute: a managed node group (or Fargate profile) in private subnets. The node role trusts `ec2.amazonaws.com` and attaches `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryReadOnly`, and `AmazonEKS_CNI_Policy`. Use a `launch_template` with `http_tokens = "required"` and `http_put_response_hop_limit = 1`.
- Workload identity: an OIDC provider and one IRSA role per workload. Applications never use node role credentials.
- Log group `/aws/eks/<cluster name>/cluster` with retention.
- Kubernetes manifests are not part of `compute.tf` unless the design lists them.
- Anti-patterns: a public API endpoint open to 0.0.0.0/0, application permissions on the shared node role.

## AWS Batch (finite tasks and cron)

- `aws_batch_compute_environment` with `type = "MANAGED"`, `compute_resources { type = "FARGATE" }` unless the design needs GPU or EC2, private subnets, a security group, and `max_vcpus`.
- `aws_batch_job_queue` and `aws_batch_job_definition` with `platform_capabilities = ["FARGATE"]`, an execution role, a job role, a log configuration with a retained log group, `retry_strategy` (attempts from design), and `timeout`.
- Let AWS create the Batch service-linked role; do not emit a custom service role.
- For cron, the scheduler role gets `batch:SubmitJob` on only the job definition and job queue ARNs, and the schedule uses the universal target `arn:aws:scheduler:::aws-sdk:batch:submitJob`.
- Anti-patterns: `batch:*`, EC2 compute environments without a launch template that requires IMDSv2.

## Self-check

- Every compute design row maps to exactly one Terraform target.
- No IAM statement uses a wildcard action, and no `Resource = "*"` appears outside an API that requires it.
- Every log group has `retention_in_days`.
- Every service image is a digest variable.
- Every schedule carries a time zone and a retry policy.
- No `latest` tag appears.
