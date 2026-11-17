---
_fragment: artifacts-infra
_of_phase: generate
_contributes:
  - terraform/
---

# Generate infrastructure artifacts

Emit one balanced-baseline Terraform configuration for the exact recommendations in `aws-design.json`. This is not three stacks: capacity-preserving and right-sized values are pricing scenarios, while Terraform follows the selected balanced sizing recorded by Design.

## Required core

Account baseline and operational resources (`baseline.tf`, `monitoring.tf`, gated `kms.tf` and `backup.tf`) come from the `artifacts-baseline` fragment; do not emit them here.
Always emit `terraform/main.tf`, `variables.tf`, `outputs.tf`, `.gitignore`, `terraform.tfvars.example`, and a Terraform README. Declare shared data sources once in `terraform/main.tf`. `data "aws_partition" "current"` belongs there; domain files such as `compute.tf` reference `data.aws_partition.current.partition` and do not declare it again. Use Terraform 1.5 or newer, a constrained AWS provider version (`~> 6.71` when any Fargate mapping has `ecs_mode: "express"`, otherwise `~> 5.80`), `var.aws_region`, default tags, explicit VPC/subnets/security groups, descriptions for variables/outputs, and no default-VPC discovery. Public ALB subnets require an internet-gateway default route; private Fargate subnets require an explicit NAT route or complete ECR, S3, CloudWatch Logs, Secrets Manager, and STS endpoint set. User-provided values use typed variables with validation; never emit a captured secret value or a `{{VARIABLE}}` placeholder. Database credentials must use RDS-managed master credentials or an equivalent Secrets Manager integration and must never enter Terraform through a password variable.

For each `service_to_disk` edge selected as EFS, bind the access point to the owning task definition with transit encryption, mount it at the selected absolute path, permit NFS only from that task's security group, and make service startup depend on mount-target readiness.

For `data.tf` (RDS, Aurora, and Key Value targets), follow `phases/generate/generate-infra-data.md`. `network.tf` owns `aws_security_group.data` (ingress from the compute security groups on the database or cache port); `data.tf` only references it.
Route each supported selected target to a domain file and record that file in `generation-warnings.json`:

| Design target | Required generated content |
| --- | --- |
| Amazon S3 + Amazon CloudFront | Private S3 origin, versioning, encryption, public-access block, CloudFront OAC, distribution-scoped `s3:GetObject` bucket policy, and distribution |
| ECS on Fargate / Fargate service | Per `aws_config.ecs_mode`: standard emits the ECS cluster, task definitions, services, and a public ALB only for the public web service; express emits one `aws_ecs_express_gateway_service` per the Express Mode rules below |
| EventBridge Scheduler + ECS RunTask | Scheduler with one ECS task target, retry policy, time-zone intent, and scoped execution role |
| Amazon RDS for PostgreSQL | Private encrypted RDS, subnet/parameter groups, Multi-AZ choice, Secrets Manager reference, backup/PITR settings; when the mapping records `customer_managed_key: true` (set when `data.regulated_data` is true or compliance requires it), `kms_key_id` is `aws_kms_key.stack` from `kms.tf` (no second key) and no cross-Region replica or backup replication |
| ElastiCache for Valkey | Private encrypted replication group with the selected persistence/eviction posture; when the mapping records `customer_managed_key: true` (set when `data.regulated_data` is true or compliance requires it), `kms_key_id` is `aws_kms_key.stack` from `kms.tf` (snapshots included) and no Global Datastore |
| Amazon EFS | Encrypted filesystem, mount targets, access point for `/var/data`, and app-scoped security group; when the mapping records `customer_managed_key: true` (set when `data.regulated_data` is true or compliance requires it), `kms_key_id` is `aws_kms_key.stack` from `kms.tf` and no replication configuration |
| ACM + external DNS | Require the ARN of an ACM certificate already validated and `Issued`; never attach a newly requested pending certificate to a listener and never fabricate Route 53 ownership |
| Secrets Manager + Parameter Store | Names/references only; values are input at deployment and remain sensitive |
| ECR immutable promotion | ECR repository with immutable tags and scan-on-push plus promotion outputs |
| Project/environment boundaries | Consume into VPC, tags, state, and deployment boundaries without a fake standalone service |

Workflow and Workflow task rows follow `generate-infra-workflow.md`: Terraform is emitted only for the semantics that file proves, and every other Workflow stays `unsupported` with `conditional_workflow_generation_unsupported`. AI is always `deferred_shared_ai_engine`; emit no model, adapter, Bedrock, or AI Terraform.
The `infra-compute` fragment is the only writer of `terraform/compute.tf`. This fragment writes every other file under `terraform/` and must not write `compute.tf`. For every row routed to `terraform/compute.tf`, follow `generate-infra-compute.md` for per-target resources, IAM, health, logging, and anti-patterns.

For `terraform/network.tf`, `storage.tf` and `delivery.tf`, also follow `references/phases/generate/generate-artifacts-infra-network-storage-delivery.md`; its rules refine the matching rows above.

Fargate mappings branch on `aws_config.ecs_mode`; the Express and standard rules live in the compute fragment (section "ECS on Fargate: Express vs standard mode"). Express rows emit `aws_ecs_express_gateway_service` and skip the target group and listener.
The report and migration guide each state, for every Fargate mapping, whether it got an AWS-provided HTTPS endpoint (express) or a hand-built ALB (standard) and the `ecs_mode_reason`.
Preserve build-once behavior: one build creates an ECR digest, environment promotion consumes that digest, and no environment rebuilds source independently. Preserve private-only ingress for private services. Never add App Runner or a public load balancer for a private service.

Before returning, ensure every emitted `.tf` file is deterministic, contains no source credential/value, and maps back to exactly one design classification. Validation belongs to the main window, not this worker.
