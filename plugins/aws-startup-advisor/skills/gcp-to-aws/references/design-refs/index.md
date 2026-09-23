# GCP Service → Design Reference Mapping

> **Column note:** **Typical AWS target** is the usual rubric outcome for that Terraform type. It is **not** the same as **`deterministic` confidence** in `aws-design.json`. Only resource types listed in **`fast-path.md` → Direct Mappings** get `deterministic`; everything else in this table is mapped via rubric → `inferred` (unless `billing_inferred` on the billing-only path).

## Compute Services

| GCP Service         | Resource Type                    | Reference File | Typical AWS target                                                                              |
| ------------------- | -------------------------------- | -------------- | ----------------------------------------------------------------------------------------------- |
| Cloud Run           | `google_cloud_run_service`       | `compute.md`   | Fargate                                                                                         |
| Cloud Functions     | `google_cloudfunctions_function` | `compute.md`   | Lambda                                                                                          |
| Compute Engine (VM) | `google_compute_instance`        | `compute.md`   | EC2 or Fargate                                                                                  |
| GKE                 | `google_container_cluster`       | `compute.md`   | EKS                                                                                             |
| App Engine          | `google_app_engine_application`  | `compute.md`   | Elastic Beanstalk (default), Fargate, Lambda, or EKS (when `compute: "eks"` / Q5 = multi-cloud) |

## Database Services

| GCP Service            | Resource Type                  | Reference File | Typical AWS target                                                                |
| ---------------------- | ------------------------------ | -------------- | --------------------------------------------------------------------------------- |
| Cloud SQL (PostgreSQL) | `google_sql_database_instance` | `database.md`  | RDS PostgreSQL or Aurora PostgreSQL (Q6 selects family)                           |
| Cloud SQL (MySQL)      | `google_sql_database_instance` | `database.md`  | RDS MySQL or Aurora MySQL (Q6 selects family)                                     |
| Cloud SQL (SQL Server) | `google_sql_database_instance` | `database.md`  | RDS SQL Server                                                                    |
| Firestore (instance)   | `google_firestore_database`    | `database.md`  | DynamoDB                                                                          |
| Firestore (document)   | `google_firestore_document`    | `database.md`  | DynamoDB                                                                          |
| BigQuery               | `google_bigquery_*`            | `database.md`  | **`Deferred — specialist engagement`** only (see `design-infra.md` BigQuery gate) |
| Memorystore (Redis)    | `google_redis_instance`        | `database.md`  | ElastiCache Redis                                                                 |
| Cloud Spanner          | `google_spanner_instance`      | `database.md`  | Aurora DSQL                                                                       |

## Storage Services

| GCP Service         | Resource Type               | Reference File | Typical AWS target |
| ------------------- | --------------------------- | -------------- | ------------------ |
| Cloud Storage (GCS) | `google_storage_bucket`     | `storage.md`   | S3                 |
| Filestore           | `google_filestore_instance` | `storage.md`   | EFS                |

## Networking Services

| GCP Service          | Resource Type                     | Reference File  | Typical AWS target |
| -------------------- | --------------------------------- | --------------- | ------------------ |
| VPC Network          | `google_compute_network`          | `networking.md` | VPC                |
| Firewall Rules       | `google_compute_firewall`         | `networking.md` | Security Groups    |
| Cloud Load Balancing | `google_compute_forwarding_rule`  | `networking.md` | ALB/NLB            |
| Cloud CDN            | (part of compute_backend_service) | `networking.md` | CloudFront         |
| Cloud DNS            | `google_dns_managed_zone`         | `networking.md` | Route 53           |
| Cloud Interconnect   | (custom config)                   | `networking.md` | AWS Direct Connect |
| Cloud Armor          | `google_compute_security_policy`  | `networking.md` | AWS WAF            |

## Messaging Services

| GCP Service | Resource Type              | Reference File | Typical AWS target |
| ----------- | -------------------------- | -------------- | ------------------ |
| Pub/Sub     | `google_pubsub_topic`      | `messaging.md` | SNS or SQS         |
| Cloud Tasks | `google_cloud_tasks_queue` | `messaging.md` | SQS or EventBridge |

## AI/ML Services

| GCP Service                | Resource Type       | Reference File            | Typical AWS target      |
| -------------------------- | ------------------- | ------------------------- | ----------------------- |
| Vertex AI (LLM/Gemini)     | (generative models) | `ai-gemini-to-bedrock.md` | Bedrock                 |
| OpenAI (in GCP env)        | (openai SDK)        | `ai-openai-to-bedrock.md` | Bedrock                 |
| Vertex AI (traditional ML) | (custom endpoints)  | `ai.md`                   | SageMaker               |
| Vertex AI (pipelines)      | (custom config)     | `ai.md`                   | SageMaker Pipelines     |
| Cloud Vision API           | (managed API)       | `ai.md`                   | Textract or Rekognition |

## Secondary/Infrastructure Services

| GCP Service              | Resource Type                          | Reference File    | Typical AWS target |
| ------------------------ | -------------------------------------- | ----------------- | ------------------ |
| Service Accounts         | `google_service_account`               | `networking.md`   | IAM Roles          |
| Secret Manager (secret)  | `google_secret_manager_secret`         | `security.md`     | Secrets Manager    |
| Secret Manager (version) | `google_secret_manager_secret_version` | `security.md`     | Secrets Manager    |
| Cloud Monitoring         | (managed)                              | Not in v1.0 scope | CloudWatch         |

---

**Usage:**

1. Extract GCP resource type from Terraform
2. Find in table above
3. If resource found in `fast-path.md` Direct Mappings table: use that mapping (confidence = deterministic)
4. Otherwise: load Reference File listed above and apply 6-criteria rubric (confidence = inferred)

**User-facing labels** for chat and reports: see `fast-path.md` → **User-facing vocabulary** (e.g. **Standard pairing** / **Tailored to your setup** / **Estimated from billing only**).
