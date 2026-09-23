# Generated-IaC Security Posture Rules

Cross-cutting security posture that generated AWS Terraform must follow, regardless of the
source cloud (GCP, Heroku, …). These are **authoring rules** — "what good AWS Terraform looks
like." Load this file **before** writing `terraform/`; emit resources that satisfy it.

**Source-agnostic by design.** Every rule here is a statement about AWS Terraform only. This
file contains **no** GCP/Heroku/source-cloud logic — the consuming skill (the caller) owns all
source-specific concerns and passes the caller-context signals a rule needs (see below).

## Rule categories

- **Gate-enforced** — the read-only policy gate (`scripts/validate-terraform-policy.py`)
  statically verifies these after generation: ALB TLS, no-public-database, RDS + ElastiCache
  encryption-at-rest, no-public-DB-port ingress, no-public admin/datastore-port ingress,
  no-wildcard-IAM. Each is **fail-open on ambiguity** — fires only on unambiguous in-block
  literal evidence, so a valid stack is never falsely blocked.
- **Authoring-only** — best-practice rules the static gate cannot check but the caller must
  still emit: `deletion_protection`, the master-password-via-Secrets-Manager recipe, S3
  hardening, EKS/ECR settings, private-subnet placement, backups, and the compliance-conditional
  emissions below. Not gate-blocked; still required for well-formed output.

## Caller-context signals

A few rules are conditional on facts only the caller knows. The caller passes these when it
loads this file; the rules reference them abstractly (never a source-cloud artifact):

- **`compliance`** — the set of declared compliance frameworks (`soc2`, `pci`, `hipaa`,
  `fedramp`), or empty. Gates the **Compliance-conditional emissions** section. The caller
  derives this from its own requirements gathering and supplies the value; this file only says
  "if `compliance` includes X, emit Y."
- **`aws_config` values** (instance classes, CPU/memory, sizes) — the caller reads these from
  its own design artifact and populates resource attributes; the posture rules constrain the
  _shape_, not the specific numbers.

The caller also owns any source-cloud detection (e.g. mapping a public-ingress finding from the
source infra into a warning) — that logic never lives here.

## Internet-facing ALB — TLS termination and HTTP redirect

**Applies when:** an `aws_lb` is an internet-facing **Application** load balancer —
`internal = false`, omitted, or variable-driven (treated as internet-facing, fail-safe).
Exempt: internal ALBs (`internal = true`), and **Network (L4) / Gateway (L3) load balancers**
(`load_balancer_type = "network"` or `"gateway"`) — these front raw TCP/UDP and legitimately
have no HTTPS:443 listener.

**Rules:**

1. Emit an HTTPS listener on port `443` (`protocol = "HTTPS"`) with a modern `ssl_policy`, a
   `certificate_arn`, and a `forward` default action to the app target group.
2. Emit an HTTP listener on port `80` whose default action is a **redirect** to HTTPS
   (`HTTP_301`) — never a `forward` to targets.
3. The ALB security group allows `443` from the internet and `80` only for the redirect;
   never forward plaintext HTTP to targets. Target groups may use HTTP to the tasks behind
   the ALB — TLS terminates at the ALB.

**Reference HCL (emit whenever `aws_lb` is internet-facing):**

```hcl
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the public ALB HTTPS listener"
  type        = string
  # TODO: request or import a certificate for your app domain
}
```

**Gate mapping:** rule 1 → `alb_https_listener`; rule 2 → `alb_http_redirect`
(see `scripts/validate-terraform-policy.py`). If generated Terraform lacks the HTTPS
listener or forwards HTTP, that is a generation defect the caller must fix — not a reason to
draw or ship plaintext HTTP.

## Managed database — no public exposure

**Applies to:** `aws_db_instance`, `aws_rds_cluster`.

**Rules:**

1. Never emit `publicly_accessible = true`. Place the database in private subnets and reach it
   from application security groups only. RDS defaults to `false`, so simply omitting the
   attribute is compliant.
2. Emit `storage_encrypted = true` — RDS storage defaults to **unencrypted**, so this must be
   explicit. Optionally set `kms_key_id` for a customer-managed key.

**Gate mapping:** rule 1 → `rds_not_public`; rule 2 → `rds_encryption_at_rest`. The gate fires
only on a literal `publicly_accessible = true` / missing-or-`false` `storage_encrypted`; a
variable-driven value fails open (not flagged). S3 is not checked — buckets have default SSE-S3
since Jan 2023, so a missing SSE block is not an unencrypted bucket.

## ElastiCache — encryption at rest

**Applies to:** `aws_elasticache_replication_group`.

**Rule:** set `at_rest_encryption_enabled = true` (and consider
`transit_encryption_enabled = true`). ElastiCache does not encrypt at rest by default.

**Gate mapping:** `elasticache_encryption_at_rest`. Fires on missing-or-`false`; variable-driven
fails open. `aws_elasticache_cluster` (standalone Memcached) is not checked — that attribute is
configured on the replication group.

## Database security group — no public ingress on DB ports

**Applies to:** inline `ingress { ... }` blocks inside `aws_security_group`.

**Rule:** an ingress rule covering a database port (`5432` PostgreSQL, `3306` MySQL) must not
allow `0.0.0.0/0` (in `cidr_blocks`) or `::/0` (in `ipv6_cidr_blocks`). Restrict to the
application security group (`security_groups = [...]`) or a private CIDR.

**Gate mapping:** `db_sg_no_public_ingress`. The gate inspects only inline ingress blocks;
separate `aws_security_group_rule` / `aws_vpc_security_group_ingress_rule` resources fail open
(the static reader cannot correlate them to their security group), so prefer inline ingress
where you want gate coverage.

## Security group — no public admin / datastore ports

**Applies to:** inline `ingress { ... }` blocks inside `aws_security_group`.

**Rule:** an ingress rule must not open a well-known admin or datastore port to `0.0.0.0/0` or
`::/0`. The enforced set is deliberately fixed to ports that are ~never legitimately public: `22`
(SSH), `3389` (RDP), `6379` (Redis), `11211` (Memcached), `27017` (MongoDB), `9200`/`9300`
(Elasticsearch), `5601` (Kibana). Reach these from a bastion/app security group or a private
CIDR instead.

**Gate mapping:** `sg_no_public_admin_ingress`. Web ports (`80`/`443`) and application/game
ports (e.g. high ranges) are **not** flagged — the rule targets a curated never-public list,
not "any public ingress", so legitimately-public workloads pass. Database ports (`5432`/`3306`)
are handled by `db_sg_no_public_ingress` and excluded here to avoid double-reporting. Same
inline-only fail-open scope as that rule.

Both security-group gates read `cidr_blocks` and `ipv6_cidr_blocks` as separate attributes and
check each family's "entire internet" range. On dual-stack and IPv6-only VPCs, `::/0` on an
admin or database port is exactly as exposed as `0.0.0.0/0`, so a benign IPv4 list does not
excuse an open IPv6 list. The violation message names the range that actually fired.

Ranges are compared **after canonicalisation**, not as text: `::/0`, `::0/0` and
`0:0:0:0:0:0:0:0/0` are the same range and all fire. `terraform fmt` treats a CIDR as an opaque
string, so nothing else normalises these — and IPv6 has many more legal spellings of the zero
address than IPv4. Only quoted literals inside the list count, and comments are stripped first,
so a range named only in a comment (`# TODO: was 0.0.0.0/0`) is not an allowed range and does
not fire. Non-literal values (`var.x`, `${...}`) remain fail-open as documented above.

## IAM — no wildcard permissions

**Applies to:** `aws_iam_policy`, `aws_iam_role_policy`, `aws_iam_group_policy`,
`aws_iam_user_policy`.

**Rule:** an `Allow` statement must not use a sole wildcard for `Action` or `Resource`, in
either string form (`"*"`) or single-element list form (`["*"]`). Scope to specific actions
and resource ARNs. A list that also contains scoped entries (e.g. `["s3:GetObject", ...]`) is
not a blanket wildcard and is allowed.

The narrow exception is an isolated `elasticbeanstalk:CreateStorageLocation`
statement with `Resource = "*"`. AWS does not define resource-level permissions
for that action; combining it with any other action does not qualify for the
exception.

**Gate mapping:** `no_wildcard_iam`. The gate scans literal policy JSON (heredoc or
`jsonencode({...})`) in the resources above. `aws_iam_policy_document` **data sources** fail
open (their statements are HCL blocks, not literal JSON the reader can inspect), and assume-role
trust policies on `aws_iam_role` are out of scope — so a scoped data-source policy is never
falsely flagged.

---

## Authoring-only rules (not gate-enforced)

The static gate cannot verify these, but well-formed AWS Terraform must still emit them. Apply
them at authoring time alongside the gate-enforced rules above.

## Database — durability & credential hygiene

**Applies to:** `aws_db_instance`, `aws_rds_cluster` and their supporting resources.

1. **`deletion_protection = true`** by default. Add an inline comment:
   `# Set to false only when intentionally destroying this cluster.`
2. **Backups enabled** (`backup_retention_period` > 0).
3. Emit a **DB subnet group + parameter group + security group**; place the instance in
   **private subnets**.
4. **Never** set the master password from a plaintext variable
   (`master_password = var.database_master_password` is forbidden — it lands in `terraform.tfvars`
   and state in plaintext). Instead generate it into Secrets Manager and reference it via a data
   source:

   ```hcl
   resource "random_password" "db_master" {
     length  = 32
     special = true
   }

   resource "aws_secretsmanager_secret" "db_master" {
     name = "${var.project_name}/rds/master-credentials"
   }

   resource "aws_secretsmanager_secret_version" "db_master" {
     secret_id     = aws_secretsmanager_secret.db_master.id
     secret_string = jsonencode({ password = random_password.db_master.result })
   }

   data "aws_secretsmanager_secret_version" "db_master" {
     secret_id  = aws_secretsmanager_secret.db_master.id
     depends_on = [aws_secretsmanager_secret_version.db_master]
   }

   # on the instance/cluster:
   #   master_password = jsondecode(data.aws_secretsmanager_secret_version.db_master.secret_string)["password"]
   ```

## S3 — bucket hardening

**Applies to:** application `aws_s3_bucket` resources (not log-sink buckets, which have their
own policies).

1. **Versioning enabled.**
2. **Encryption:** SSE-S3 or SSE-KMS (a bucket without an explicit SSE block still has default
   SSE-S3 since Jan 2023 — do not treat its absence as unencrypted, but prefer an explicit block).
3. **Block public access** by default (account- and bucket-level).
4. **Lifecycle policies** for cost/retention where applicable.
5. If **public content** is required, front it with **CloudFront + Origin Access Control (OAC)** —
   never a public bucket policy.

## Compute — Fargate / EKS / ECR

1. **Fargate** tasks run in **private subnets**; size from the caller-supplied `aws_config`
   CPU/memory.
2. **EKS:** default to a private API endpoint — `endpoint_private_access = true`,
   `endpoint_public_access = false`. Add a comment: `# Public endpoint disabled. To enable
   kubectl access from outside the VPC set endpoint_public_access = true and restrict
   public_access_cidrs to known CIDRs.`
3. **ECR:** every `aws_ecr_repository` includes `image_scanning_configuration { scan_on_push = true }`
   (free basic scanning catches known CVEs before images reach production).

## Networking — subnet & egress baseline

1. Span at least **2 Availability Zones**.
2. **Public + private subnets**; workloads (compute, database) live in private subnets.
3. **NAT gateway** for private-subnet outbound internet when required.

## Monitoring — baseline observability

1. A **CloudWatch log group per service** with a sane retention (default 30 days).
2. A **dashboard** with key metrics. (Specific alarm thresholds come from the caller's context —
   the caller supplies success-metric targets; this rule constrains the shape, not the values.)

---

## Compliance-conditional emissions

These are AWS best-practice hardening steps that apply **only when the caller declares a
compliance framework**. The **rule lives here**; the **trigger** (the `compliance` set) is a
caller-context signal (see _Caller-context signals_ above) — the caller passes it in; this file
never reads a source-cloud artifact.

Apply based on the caller-supplied `compliance` set:

| Emit when `compliance` includes…     | Emit                                                                                                                                                                                                                                                          |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pci`, `hipaa`, or `fedramp`         | **VPC flow logs** — `aws_flow_log` for the VPC → a CloudWatch log group. Inline cost note: `# VPC Flow Logs: ~$0.50/GB ingested. Enabled for compliance. Disable if cost is a concern and compliance posture allows.`                                         |
| `pci`, `hipaa`, or `fedramp`         | **S3 access logging** — `aws_s3_bucket_logging` for every application bucket → a dedicated access-log bucket. Inline cost note: `# S3 access logging: ~$0.023/GB stored. Enabled for compliance. Disable if cost is a concern and compliance posture allows.` |
| `soc2`, `pci`, `hipaa`, or `fedramp` | **Secret rotation** — a companion `aws_secretsmanager_secret_rotation` (`automatically_after_days = 30`) for every `aws_secretsmanager_secret`, with a TODO comment for the rotation Lambda ARN.                                                              |
| `pci`, `hipaa`, or `fedramp`         | **Customer-managed KMS** — an `aws_kms_key` referenced via `kms_key_id` on every `aws_secretsmanager_secret` (AWS-managed key is sufficient otherwise).                                                                                                       |

When `compliance` is empty, emit **none** of the above — keep the generated Terraform minimal
and immediately applyable. (The account-hardening `baseline.tf` layer — CloudTrail, GuardDuty,
Config, Security Hub — remains the caller's own generation concern for now; it is a candidate to
migrate here later.)
