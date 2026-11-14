---
_fragment: artifacts-infra
_of_phase: generate
_contributes:
  - terraform/
---

# Generate infrastructure artifacts

Emit one balanced-baseline Terraform configuration for the exact recommendations in `aws-design.json`. This is not three stacks: capacity-preserving and right-sized values are pricing scenarios, while Terraform follows the selected balanced sizing recorded by Design.

## Required core

Always emit `terraform/main.tf`, `variables.tf`, `outputs.tf`, `.gitignore`, `terraform.tfvars.example`, and a Terraform README. Use Terraform 1.5 or newer, a constrained AWS provider version (`~> 6.71` when any Fargate mapping has `ecs_mode: "express"`, otherwise `~> 5.80`), `var.aws_region`, default tags, explicit VPC/subnets/security groups, descriptions for variables/outputs, and no default-VPC discovery. Public ALB subnets require an internet-gateway default route; private Fargate subnets require an explicit NAT route or complete ECR, S3, CloudWatch Logs, Secrets Manager, and STS endpoint set. User-provided values use typed variables with validation; never emit a captured secret value or a `{{VARIABLE}}` placeholder. Database credentials must use RDS-managed master credentials or an equivalent Secrets Manager integration and must never enter Terraform through a password variable.

For each `service_to_disk` edge selected as EFS, bind the access point to the owning task definition with transit encryption, mount it at the selected absolute path, permit NFS only from that task's security group, and make service startup depend on mount-target readiness.

Route each supported selected target to a domain file and record that file in `generation-warnings.json`:

| Design target | Required generated content |
| --- | --- |
| Amazon S3 + Amazon CloudFront | Private S3 origin, versioning, encryption, public-access block, CloudFront OAC, distribution-scoped `s3:GetObject` bucket policy, and distribution |
| ECS on Fargate / Fargate service | Per `aws_config.ecs_mode`: standard emits the ECS cluster, task definitions, services, and a public ALB only for the public web service; express emits one `aws_ecs_express_gateway_service` per the Express Mode rules below |
| EventBridge Scheduler + ECS RunTask | Scheduler with one ECS task target, retry policy, time-zone intent, and scoped execution role |
| Amazon RDS for PostgreSQL | Private encrypted RDS, subnet/parameter groups, Multi-AZ choice, Secrets Manager reference, backup/PITR settings |
| ElastiCache for Valkey | Private encrypted replication group with the selected persistence/eviction posture |
| Amazon EFS | Encrypted filesystem, mount targets, access point for `/var/data`, and app-scoped security group |
| ACM + external DNS | Require the ARN of an ACM certificate already validated and `Issued`; never attach a newly requested pending certificate to a listener and never fabricate Route 53 ownership |
| Secrets Manager + Parameter Store | Names/references only; values are input at deployment and remain sensitive |
| ECR immutable promotion | ECR repository with immutable tags and scan-on-push plus promotion outputs |
| Project/environment boundaries | Consume into VPC, tags, state, and deployment boundaries without a fake standalone service |

The checked-in representative design selects Step Functions Standard and Lambda for a Workflow whose callback, retry, compensation, and state-retention semantics are not fixture-validated for automatic generation. Classify those rows as `unsupported`, emit `conditional_workflow_generation_unsupported`, and emit no Workflow Terraform. For another run, Workflow artifacts may be generated only when the rubric marks every required semantic supported and the generated definition has dedicated contract tests. AI is always `deferred_shared_ai_engine`; emit no model, adapter, Bedrock, or AI Terraform.

Branch each Fargate mapping on `aws_config.ecs_mode`. A mapping with no `ecs_mode` key is `"standard"`, never an error and never `"express"`.

- `"express"`: emit one `aws_ecs_express_gateway_service` (provider 6.23.0 or newer, `cpu_architecture` 6.71.0 or newer) instead of the task definition, `aws_ecs_service`, ALB, target group, and listener. Pass `cluster`, `execution_role_arn`, `infrastructure_role_arn` (one IAM role per design, trusting `ecs.amazonaws.com`, attached to `arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices`), a `service_name` containing the sanitized Render service name, `wait_for_steady_state = true`, `cpu` and `memory` within 256 to 4096 units and 512 to 8192 MiB, `cpu_architecture`, `primary_container` (image digest from ECR promotion, port, log group, `environment`, `secret` references only), `network_configuration`, `scaling_target`, and `health_check_path`. Subnets follow `aws_config.placement`: public placement uses the public subnets and records the accepted deviation from the private-subnet rule as a non-blocking `ecs_express_public_subnet_placement` warning and in the Terraform README. Output `ingress_paths[0].endpoint` as the service URL. Add `depends_on` on the infrastructure role's policy attachment. Emit no separate ALB for this service.
- `"standard"`: emit the existing task definition, service, and ALB set. Write the deployment strategy explicitly from `compute.release_strategy`: `rolling` means no `deployment_controller` block; `blue_green` on a load-balanced service means `deployment_controller { type = "CODE_DEPLOY" }`, a green target group, a test listener, and CodeDeploy resources; `canary` where Express was ruled out means a rolling update plus a non-blocking `ecs_express_not_selected_rolling_release` warning naming `ecs_mode_reason`, repeated in the Terraform README.

The report and migration guide state, per service, whether it got an AWS-provided HTTPS endpoint (express) or a hand-built ALB (standard) and the `ecs_mode_reason`.
Preserve build-once behavior: one build creates an ECR digest, environment promotion consumes that digest, and no environment rebuilds source independently. Preserve private-only ingress for private services. Never add App Runner or a public load balancer for a private service.

Before returning, ensure every emitted `.tf` file is deterministic, contains no source credential/value, and maps back to exactly one design classification. Validation belongs to the main window, not this worker.
