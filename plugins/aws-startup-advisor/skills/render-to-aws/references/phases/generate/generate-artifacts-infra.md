---
_fragment: artifacts-infra
_of_phase: generate
_contributes:
  - terraform/
---

# Generate infrastructure artifacts

Emit one balanced-baseline Terraform configuration for the exact recommendations in `aws-design.json`. This is not three stacks: capacity-preserving and right-sized values are pricing scenarios, while Terraform follows the selected balanced sizing recorded by Design.

## Required core

Always emit `terraform/main.tf`, `variables.tf`, `outputs.tf`, `.gitignore`, `terraform.tfvars.example`, and a Terraform README. Use Terraform 1.5 or newer, a constrained AWS provider version, `var.aws_region`, default tags, explicit VPC/subnets/security groups, descriptions for variables/outputs, and no default-VPC discovery. Public ALB subnets require an internet-gateway default route; private Fargate subnets require an explicit NAT route or complete ECR, S3, CloudWatch Logs, Secrets Manager, and STS endpoint set. User-provided values use typed variables with validation; never emit a captured secret value or a `{{VARIABLE}}` placeholder. Database credentials must use RDS-managed master credentials or an equivalent Secrets Manager integration and must never enter Terraform through a password variable.

For each `service_to_disk` edge selected as EFS, bind the access point to the owning task definition with transit encryption, mount it at the selected absolute path, permit NFS only from that task's security group, and make service startup depend on mount-target readiness.

Route each supported selected target to a domain file and record that file in `generation-warnings.json`:

| Design target | Required generated content |
| --- | --- |
| Amazon S3 + Amazon CloudFront | Private S3 origin, versioning, encryption, public-access block, CloudFront OAC, distribution-scoped `s3:GetObject` bucket policy, and distribution |
| ECS on Fargate / Fargate service | ECS cluster, task definitions, private services, desired counts, health/shutdown behavior, public ALB only for the public web service |
| EventBridge Scheduler + ECS RunTask | Scheduler with one ECS task target, retry policy, time-zone intent, and scoped execution role |
| Amazon RDS for PostgreSQL | Private encrypted RDS, subnet/parameter groups, Multi-AZ choice, Secrets Manager reference, backup/PITR settings |
| ElastiCache for Valkey | Private encrypted replication group with the selected persistence/eviction posture |
| Amazon EFS | Encrypted filesystem, mount targets, access point for `/var/data`, and app-scoped security group |
| ACM + external DNS | Require the ARN of an ACM certificate already validated and `Issued`; never attach a newly requested pending certificate to a listener and never fabricate Route 53 ownership |
| Secrets Manager + Parameter Store | Names/references only; values are input at deployment and remain sensitive |
| ECR immutable promotion | ECR repository with immutable tags and scan-on-push plus promotion outputs |
| Project/environment boundaries | Consume into VPC, tags, state, and deployment boundaries without a fake standalone service |

The checked-in representative design selects Step Functions Standard and Lambda for a Workflow whose callback, retry, compensation, and state-retention semantics are not fixture-validated for automatic generation. Classify those rows as `unsupported`, emit `conditional_workflow_generation_unsupported`, and emit no Workflow Terraform. For another run, Workflow artifacts may be generated only when the rubric marks every required semantic supported and the generated definition has dedicated contract tests. AI is always `deferred_shared_ai_engine`; emit no model, adapter, Bedrock, or AI Terraform.

Preserve build-once behavior: one build creates an ECR digest, environment promotion consumes that digest, and no environment rebuilds source independently. Preserve private-only ingress for private services. Never add App Runner or a public load balancer for a private service.

Before returning, ensure every emitted `.tf` file is deterministic, contains no source credential/value, and maps back to exactly one design classification. Validation belongs to the main window, not this worker.
