# Elastic Beanstalk Design Reference

**Applies to:** Google App Engine (Standard/Flexible)

## Discovery Inputs (what fires this mapping)

App Engine → EB fidelity depends on how the workload was discovered:

- **Terraform** (`google_app_engine_application` + `*_app_version` resources) → full mapping: Q7b fires (only when `compute` ≠ `"eks"`), and the design fan-out emits one EB environment per service with per-service `runtime`/scaling/sizing. This is the primary path. Under `compute: "eks"` (Q5 = multi-cloud) Q7b does not fire and App Engine routes to EKS instead — the fan-out does not run.
- **Billing export** (no Terraform) → coarse mapping via the billing design path (`design-billing.md`): App Engine targets EB (when `compute` ≠ `"eks"`), but without per-service or runtime detail (`confidence: billing_inferred`). Under `compute: "eks"` (Q5 = multi-cloud) the billing path routes App Engine to EKS instead — see `design-billing.md` App Engine multi-cloud override.
- **App code only** (no Terraform, no billing) → no App Engine compute inventory is produced today, so no EB mapping fires.
- **Live `gcloud` discovery** → App Engine capture is **not yet wired** (tracked as a follow-up to the live-discovery work); until then TF-less, billing-less App Engine projects surface App Engine as an unmapped asset rather than an EB target.

This is not a "Terraform required" policy — it reflects which discovery paths currently produce the inventory the fast-path needs. Widening the non-Terraform paths is follow-up work.

## Key Distinction

- **EB is application management** (AWS manages lifecycle: provisioning, load balancing, scaling, patching) vs **ECS/Fargate as infrastructure management** (user manages task definitions, service configs, scaling policies).
- "Don't want to manage servers" does **NOT** mean serverless/Lambda. Lambda imposes a different programming model: stateless functions, cold starts, event-driven invocation, 15-min max execution, no persistent connections.
- EB eliminates server management while preserving the standard application programming model: long-running processes, persistent connections, threads, local state, WebSockets.

## When to Use

Routing signals — these apply ONLY when `google_app_engine_application` is in the inventory **and `compute_model` is absent or `"managed_platform"` and `compute` ≠ `"eks"`** (Q7b). If the user chose `compute_model: "container_orchestration"` or `"serverless"` (Q7b = B/C), App Engine does **not** map to EB — it routes to Fargate/Lambda via the `compute.md` rubric, and this reference is not the target (see **NOT the Right Choice** below). Likewise, if `compute: "eks"` (Q5 = multi-cloud), Q7b does not fire and App Engine routes to **EKS** — this reference is not the target. Routing authority lives in `compute.md` / `fast-path.md` / `design-infra.md`; this file is a supplementary config reference. When the gate holds, any of these signals is sufficient:

- `google_app_engine_application` detected in Terraform (strongest PaaS-to-PaaS signal)
- User answers `compute_model: "managed_platform"` in Clarify (Q7b)
- User explicitly requests "managed platform" or "Elastic Beanstalk" for their App Engine workloads

These signals do NOT apply to Cloud Run resources. Cloud Run maps to Fargate unconditionally via fast-path.

## NOT the Right Choice

- User explicitly wants serverless/Lambda (event-driven functions, stateless, cold starts) → use Lambda
- User wants fine-grained container orchestration control → use ECS/Fargate or EKS
- User requires scale-to-zero → use Lambda or Fargate with scaling policies
- GPU workloads → use EC2 or EKS
- Kubernetes orchestration required → use EKS

## Supported Platforms

Detect the **platform name** (below), then resolve the exact platform version at generate time. **Do not hardcode language version numbers** — the EB platform lineup changes frequently (versions are added and retired). Look up the current version against the [EB supported platforms documentation](https://docs.aws.amazon.com/elasticbeanstalk/latest/platforms/platforms-supported.html) or `aws elasticbeanstalk list-available-solution-stacks`, and pick the newest platform version that supports the app's language version.

| Platform           | Base OS | Notes                                                                       |
| ------------------ | ------- | --------------------------------------------------------------------------- |
| Python             | AL2023  |                                                                             |
| Node.js            | AL2023  |                                                                             |
| Java SE (Corretto) | AL2023  | Standalone `.jar` applications                                              |
| Tomcat             | AL2023  | **Separate platform** from Java SE; for `.war` web apps (Corretto + Tomcat) |
| .NET Core on Linux | AL2023  | Requires pre-built artifacts                                                |
| Go                 | AL2023  |                                                                             |
| Ruby               | AL2023  |                                                                             |
| PHP                | AL2023  |                                                                             |
| Docker             | AL2023  | Single container, or ECS-managed multi-container                            |

All current platforms run on Amazon Linux 2023 (AL2 branches are being retired).

## Platform Detection Rules

Detect from app source to select EB platform automatically:

| File/Pattern                                 | Platform           |
| -------------------------------------------- | ------------------ |
| `requirements.txt` or `Pipfile`              | Python             |
| `package.json`                               | Node.js            |
| `pom.xml` or `build.gradle` with .jar output | Java SE (Corretto) |
| `pom.xml` or `build.gradle` with .war output | Tomcat             |
| `*.csproj` or `*.sln`                        | .NET Core on Linux |
| `go.mod`                                     | Go                 |
| `Gemfile`                                    | Ruby               |
| `Dockerfile`                                 | Docker             |
| `composer.json`                              | PHP                |

## Environment Types

- **Web server** (default): Handles HTTP requests via ALB. Use for APIs, web apps, frontends.
- **Worker**: Processes background jobs from SQS queue. No public endpoint. Use for async tasks, cron-like jobs, batch processing.

**This skill uses the Web server tier only.** All App Engine services map to WebServer-tier environments (SingleInstance or LoadBalanced per Sizing Defaults) — the Worker tier is not selected. App Engine background work (`cron.yaml`, task queues) maps to EventBridge + SQS alongside the web environment, not to an EB Worker environment.

## Configuration

**Provisioning vs deployment (two distinct steps):**

- **Provision the environment with Terraform** — the Generate phase emits `aws_elastic_beanstalk_application` + `aws_elastic_beanstalk_environment` (with `setting` blocks), consistent with the rest of the generated stack. Terraform is the source of truth for the environment's infrastructure. Do **not** use the EB CLI (`eb`) or `aws elasticbeanstalk create-environment` to provision.
- **Deploy the app code with the AWS CLI** — the one-time migration script (`03-migrate-containers.sh`) bundles the app source (including the `Dockerfile` for the Docker platform, which EB builds at deploy time) and runs `aws elasticbeanstalk create-application-version` + `update-environment` to push it into the Terraform-provisioned environment. This is app migration, not provisioning.

**Port:** On AL2023 platforms the reverse proxy (nginx) forwards to the application on port **5000** by default, and EB sets the `PORT` environment variable to that value. However, most application frameworks bind to their own default port unless told otherwise (e.g. Node/Express often 3000, Python/gunicorn 8000, .NET/Kestrel 5000/8080). **The app must listen on the port EB advertises**, or the first deploy fails its health checks. Two safe options:

- **Have the app read `PORT`** and bind to it (e.g. `process.env.PORT`, `os.environ["PORT"]`) — recommended, and how App Engine apps already behave.
- **Set the `PORT` environment property** (namespace `aws:elasticbeanstalk:application:environment`) to whatever fixed port the app listens on.

Migrated App Engine apps already read `PORT` (App Engine sets it too), so the first option usually works with no code change.

**Deployment policies:**

| Policy                     | Use case                           |
| -------------------------- | ---------------------------------- |
| AllAtOnce                  | Dev/test (fastest, brief downtime) |
| Rolling                    | Prod with some tolerance           |
| RollingWithAdditionalBatch | Prod (maintains full capacity)     |
| Immutable                  | Prod (safe rollback)               |
| TrafficSplitting           | Canary/prod (percentage-based)     |

**Secrets:** Use the `aws:elasticbeanstalk:application:environmentsecrets` namespace to fetch values from Secrets Manager or SSM Parameter Store into environment variables at instance bootstrap. Supported on platform versions released **on or after March 26, 2025**. (JSON-key extraction from a Secrets Manager secret — appending `:keyName` to the ARN — requires platform versions on or after January 13, 2026.) Values are pulled at bootstrap only; rotate via `UpdateEnvironment` or `RestartAppServer`. Source: [EB dev guide — environment properties and secrets](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/environments-cfg-secrets.html); re-verify the namespace and cutoff dates against that page before relying on them, as EB platform schedules change.

**IAM:**

- Instance profile: scan source for AWS SDK usage; attach least-privilege policies for accessed services
- Service role: `aws-elasticbeanstalk-service-role` (auto-created on first environment)

**VPC:**

- Web tier, **LoadBalanced**: ALB in public subnets, EC2 instances in private subnets (instances reach the internet via NAT for outbound; only the ALB is public-facing)
- Web tier, **SingleInstance** (no ALB): the single instance goes in a **public** subnet with a public IP (`AssociatePublicIpAddress=true`) so it is reachable — there is no load balancer to front it. This is the one case where an EB instance is public-facing; scope its security group tightly (only the app port from the intended sources) since it lacks the ALB boundary. Prefer LoadBalanced for anything internet-facing at scale.
- Worker-style background work is not an EB Worker tier here (see Environment Types); it maps to EventBridge + SQS alongside the web env.

**Scaling:**

- Configure min/max instances
- Scaling triggers: CPU utilization, network out, latency, request count

## GCP App Engine to EB Mapping

| App Engine Feature           | EB Equivalent                                                       |
| ---------------------------- | ------------------------------------------------------------------- |
| App Engine Standard          | EB with matching platform (Python, Node, etc.)                      |
| App Engine Flexible          | EB Docker platform                                                  |
| `app.yaml` env vars          | EB environment properties                                           |
| `cron.yaml`                  | EventBridge scheduled events → the web-tier env (no EB Worker tier) |
| Task queues                  | SQS + EventBridge → the web-tier env (no EB Worker tier)            |
| `instance_class` (F/B tiers) | Right-sizing signal for instance type (see Sizing Defaults below)   |
| Automatic scaling min/max    | EB auto-scaling min/max instances                                   |

### Where the config comes from (Terraform)

In Terraform, `google_app_engine_application` is only the **container** for an app — it carries the project/location, not the workload config. The `runtime`, `instance_class`, `env_variables`, and scaling settings live on the **`google_app_engine_standard_app_version`** / **`google_app_engine_flexible_app_version`** resources. Each such resource is one **version** of one **service** (identified by its `service` argument; a service can have many versions).

During discovery these version resources are classified SECONDARY (`configuration`), and the App Engine fan-out step in `phases/design/design-infra.md` reads their config when mapping the parent. They are **config sources**: their attributes build the parent's EB mapping, but they are not emitted as standalone resources (they are a Skip Mapping — logged to `warnings`, see `fast-path.md`). Read them as follows:

- **One EB environment per App Engine _service_, not per version.** Group app_version resources by their `service` value (a version with no `service` argument belongs to service `"default"`). Multiple versions of the same service (e.g. `v1`, `v2` both with `service = "myapp"`) collapse to **one** EB environment — pick the config-source version by the tie-break defined in `design-infra.md` fan-out step 4 (prefer `serving_status = "SERVING"`; if several or none are SERVING, highest `version_id` by case-insensitive lexical order, with a `warnings` note). Distinct `service` values (e.g. `default`, `worker`) each become a **separate** EB environment under one EB application. Do not emit one env per version, and do not collapse distinct services into one.
- Read `runtime` → EB platform (via Platform Detection Rules above). For Flexible, `flexible_runtime_settings.operating_system` / `runtime_version` may further qualify it.
- Read `automatic_scaling` / `basic_scaling` / `manual_scaling` → EB min/max instances (whichever block is present; Standard defaults to automatic).
- Read `env_variables` → EB environment properties.
- Derive `environment_type` and `instance_type` **from the service's own config** (see Sizing Defaults below): the app_version's scaling block sets the environment type (multi-instance/autoscaled → LoadBalanced; single/manual-1 → SingleInstance) and its `instance_class` (Standard) or `resources` block (Flexible) sets the instance size. This is per-service — different services of one app can land in different bands. Default to Graviton (`t4g.*`) and emit a `graviton` block.

If **only** `google_app_engine_application` is present (no app_version resources — e.g. billing-only or partial Terraform), map a single EB environment and detect the platform/runtime from the app source instead, noting the assumption in `warnings`.

## Sizing Defaults

EB environment type and instance size are derived **per service, from that service's own App Engine config** — the same "size from the source resource" approach the rubric uses for Cloud Run → Fargate. Q6 availability is a _database_ HA signal and does **not** drive EB compute sizing.

**Environment type** — from the app_version's scaling block:

| App Engine scaling on the version                                             | EB environment type | ALB | Min instances                                                       |
| ----------------------------------------------------------------------------- | ------------------- | --- | ------------------------------------------------------------------- |
| `automatic_scaling`, or `manual_scaling`/`basic_scaling` with **>1** instance | LoadBalanced        | Yes | 2 (or the version's `min_instances`/`min_idle_instances` if higher) |
| `manual_scaling`/`basic_scaling` with **1** instance, or no scaling block     | SingleInstance      | No  | 1                                                                   |

**Instance size** — from the version's declared class/resources, defaulting to Graviton (`t4g.*`):

| App Engine signal                                      | EB instance type (Graviton default)           |
| ------------------------------------------------------ | --------------------------------------------- |
| Standard `instance_class` F1 / B1                      | t4g.small                                     |
| Standard `instance_class` F2 / B2                      | t4g.small                                     |
| Standard `instance_class` F4 / F4_1G / B4 / B4_1G / B8 | t4g.medium                                    |
| Flexible `resources { cpu, memory_gb }`                | smallest `t4g.*` meeting cpu+memory           |
| absent / unknown                                       | t4g.small (note the assumption in `warnings`) |

**CPU architecture:** default to **Graviton (ARM64)** per the skill-wide posture — EB runs on EC2, so the same `cpu_architecture` decision applies (see `shared/graviton.md`). Use the `t4g.*` families above; fall back to x86 (`t3.*`) only when `cpu_architecture.value == "x86"` or the runtime/image is Graviton-incompatible (e.g. an App Engine Flexible → Docker image built only for amd64, or a .NET workload not published for arm64), and record the reason in the `graviton` block `caveats`. Emit a `graviton` block on each EB mapping (see `compute.md` Output Schema).

## Output Schema

The design phase emits **one mapping per App Engine service** (see the App Engine fan-out step in `phases/design/design-infra.md`). `gcp_type` stays `google_app_engine_application` (the Direct Mappings row), and `aws_config.source_service` records which App Engine service the environment came from. `runtime`, `instance_class`, and the scaling block are read from that service's `*_app_version` resource, not from the parent. `environment_type` and `instance_type` are derived **per service from that version's own scaling/class** (see Sizing Defaults) — so services can differ. Each mapping carries a `graviton` block like other compute resources. This shape lives inside the standard `aws-design.json` cluster structure — the array below shows only the two resource objects.

Example — a two-service app: `default` (a web service with `automatic_scaling` → LoadBalanced) and `worker` (a `manual_scaling { instances = 1 }` service → SingleInstance). Each service's env type comes from its own scaling block:

```json
[
  {
    "gcp_type": "google_app_engine_application",
    "gcp_address": "google_app_engine_application.example#default",
    "gcp_config": {
      "source_service": "default",
      "runtime": "python312",
      "instance_class": "F4",
      "scaling": "automatic_scaling"
    },
    "aws_service": "Elastic Beanstalk",
    "aws_config": {
      "eb_application": "example",
      "eb_environment": "default",
      "source_service": "default",
      "platform": "Python 3.12 running on 64bit Amazon Linux 2023",
      "environment_type": "LoadBalanced",
      "instance_type": "t4g.medium",
      "min_instances": 2,
      "max_instances": 10,
      "env_variables": { "LOG_LEVEL": "info" },
      "region": "us-east-1"
    },
    "graviton": { "compatibility": "ready", "target_architecture": "arm64", "caveats": [] },
    "confidence": "deterministic",
    "human_expertise_required": false,
    "rationale": "Direct Mapping: App Engine service 'default' → Elastic Beanstalk environment (compute_model absent or managed_platform); LoadBalanced + t4g.medium from the version's automatic_scaling and instance_class F4"
  },
  {
    "gcp_type": "google_app_engine_application",
    "gcp_address": "google_app_engine_application.example#worker",
    "gcp_config": {
      "source_service": "worker",
      "runtime": "python312",
      "instance_class": "B2",
      "scaling": "manual_scaling(instances=1)"
    },
    "aws_service": "Elastic Beanstalk",
    "aws_config": {
      "eb_application": "example",
      "eb_environment": "worker",
      "source_service": "worker",
      "platform": "Python 3.12 running on 64bit Amazon Linux 2023",
      "environment_type": "SingleInstance",
      "instance_type": "t4g.small",
      "min_instances": 1,
      "max_instances": 1,
      "region": "us-east-1"
    },
    "graviton": { "compatibility": "ready", "target_architecture": "arm64", "caveats": [] },
    "confidence": "deterministic",
    "human_expertise_required": false,
    "rationale": "Direct Mapping: App Engine service 'worker' → Elastic Beanstalk environment (compute_model absent or managed_platform); SingleInstance + t4g.small from the version's manual_scaling (1 instance) and instance_class B2"
  }
]
```
