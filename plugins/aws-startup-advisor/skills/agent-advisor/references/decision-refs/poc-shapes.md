# POC Shapes — Per-Runtime Deploy Artifacts

Single source of truth for what a generated POC looks like per winning
runtime. Loaded by `poc.md` Step 3 (non-AgentCore verdicts) and by its
temporal_worker_poll dispatch (whose base shape follows the unit's
effective_runtime — ecs or eks — see the Temporal worker POC section).
Content locked by `scripts/test_poc_shapes.py` — changing a allowlist, auth
mode, or fallback rule requires updating that test in the same commit.

## Common contract (every runtime)

- `plan.md` precedes artifacts (staged deployment plan).
- **Bedrock wiring is CONDITIONAL on the unit's `model_recommendation != null`.** An agent unit
  (model-bearing) carries the minimal Bedrock-calling logic; the **entrypoint file name and
  contract are runtime-specific**: `agent.py` (HTTP `/invocations` + `/ping`) for
  AgentCore/ECS/EKS, `handler.py` (Lambda handler) for Lambda; Harness has no code file; a
  plan-backed 3-F POC ships the user's migrated app instead. **A model-less unit** (a plain
  `service`/`batch`/`light_io` unit in a MIXED system — `model_recommendation: null`) carries NO
  Bedrock code, NO model env var (`BEDROCK_MODEL_ID`), NO `bedrock:InvokeModel` IAM permission, NO
  model-access prerequisite, and NO Bedrock smoke check — its POC is the runtime shape alone
  (container/job/function + its trigger). Every runtime shape below (ECS/EKS/Lambda/Batch/Fargate)
  applies its Bedrock-specific artifacts, env, IAM, and smoke ONLY when the unit is model-bearing.
- `deploy.sh` guardrails (all runtimes): cost warning at top; typed
  `read -p "Type 'deploy' to continue"` confirmation before any
  resource-creating call; region via env var, and model via env var ONLY for a model-bearing
  unit; NO credentials embedded; volatile CLI flags carry `TODO: verify` unless MCP-verified.
- `README.md`: prerequisites, deploy, test-after-deploy, teardown, cost note
  (no dollar figures — point to the recommendation doc).
- Mode A generates files only — nothing is executed. Mode B follows poc.md
  Step 4's safety contract unchanged.

## agentcore

Unchanged — poc.md sections 3-H (Harness) / 3-F (plan-backed framework) /
3a–3e (code path) remain the authority. This file adds nothing for AgentCore.

## ecs

**Also serves `fargate` verdicts (W5/W6).** ECS-on-Fargate is this shape's launch type, so a
`fargate` verdict (a `light_io`/`service` unit under workload-classes W5/W6) uses this exact
shape — same artifacts, same create-allowlist, same smoke path. There is no separate
`## fargate` shape; `ecs-poc.tf` already provisions Fargate tasks (no EC2 launch type).

**Scope limit for W5 (`fargate — Fargate behind ALB`):** this POC deliberately does NOT
provision an ALB (see never-create list below) — provisioning one drags in VPC/subnet/target-group
wiring the POC's never-list exists to avoid. So for a W5 webhook/HTTP-ingress workload, this POC
validates the container via the localhost smoke path (plus Bedrock connectivity ONLY for a
model-bearing unit), **not the public ALB ingress**. State this in the generated `README.md`: for
a model-bearing unit, "POC validates the task and its Bedrock calls; the production W5 design puts
this Fargate service behind an ALB — add the ALB and its target group when you promote beyond the
POC." For a model-less unit, drop the "and its Bedrock calls" clause. Do not claim the POC
exercised the real HTTP entry point, and do not claim Bedrock calls for a model-less unit.

Artifacts: `Dockerfile`, `ecs-poc.tf`, `agent.py`, `deploy.sh`, `README.md`.

> **Model-less variant (a `service`/`batch`/`light_io` SECONDARY unit with
> `model_recommendation: null`):** the entrypoint is a plain `app.py` (the container's real work,
> no Bedrock call), the task role gets NO `bedrock:InvokeModel`, there is no `BEDROCK_MODEL_ID`
> env var or model-access prerequisite, and the smoke path checks the container is healthy (not a
> Bedrock round-trip). Everything below about `agent.py` / model env / InvokeModel applies ONLY
> when the unit is model-bearing.

- **No ALB.** The smoke path is: deploy.sh finishes by running a one-off
  `aws ecs run-task` (or `aws ecs execute-command`) that curls the
  container's localhost endpoint, then prints the
  `aws logs tail /agent-advisor/poc/<run_id> --follow` command. A service
  that deploys but cannot be invoked is not a POC.
- **Terraform may create ONLY**: ECS cluster (reuse-or-create by name), ECR
  repo, CloudWatch log group `/agent-advisor/poc/<run_id>`, IAM roles and
  policies, security group (egress-only), task definition, service
  (desired_count 1, Fargate, 0.25–0.5 vCPU).
- **Terraform must NEVER create**: VPC, subnets, NAT gateway, internet
  gateway, ALB/NLB.
- Networking: `VPC_ID`/`SUBNET_IDS` env vars → if unset, data-source the
  default VPC → if no default VPC exists, FAIL with a clear message; never
  create one. Public IP = ENABLED when in the default VPC (no NAT
  assumption).
- IAM: task execution role attaches the managed
  `AmazonECSTaskExecutionRolePolicy`; task role gets `bedrock:InvokeModel`
  scoped to the resolved model ARN only.
- Image tag: `poc-<run_id>`. deploy.sh creates the ECR repo if missing
  (inside the typed-confirm section), builds, pushes.
- Teardown: `terraform destroy`; note that the ECR repo (if Terraform-created)
  goes with it.

## eks

> **Model-less variant** (a non-agent SECONDARY unit, `model_recommendation: null`): plain
> `app.py` (no Bedrock call), no `bedrock:InvokeModel` in the IRSA/node-role prerequisite, no
> model env var, health-check smoke only. The Bedrock-related items below apply ONLY when the
> unit is model-bearing (per the common-contract conditional).

Artifacts: `Dockerfile`, `k8s/namespace.yaml`, `k8s/deployment.yaml`,
`k8s/service.yaml`, `deploy.sh`, `README.md`.

- **Never creates an EKS cluster.** Requires an existing cluster; without one,
  emit the manifests plus "point kubectl at your cluster".
- Namespace is **`agent-advisor-poc-<run_id>`** — unique per run, created by
  `namespace.yaml`. Never a fixed name like `poc` (teardown of a fixed name
  could delete a user's pre-existing namespace).
- Service type **`ClusterIP`**; the README test path is
  `kubectl port-forward` + local curl. No LoadBalancer (billable cloud
  resource).
- Bedrock auth: manifests include a commented IRSA `serviceAccountName`
  block; README states the prerequisite "your node role or an IRSA service
  account must allow bedrock:InvokeModel". **The EKS POC creates no IAM
  resources.**
- deploy.sh: build/push to ECR, then `kubectl apply -f k8s/`.
- Teardown: `kubectl delete -f k8s/` — deletes exactly what it created.

## lambda

Artifacts: `handler.py`, `lambda-poc.tf`, `deploy.sh`, `README.md`.

> **Model-less variant** (a non-agent SECONDARY unit, `model_recommendation: null`): `handler.py`
> does the function's real work with no Bedrock call, the role omits `bedrock:InvokeModel`, there
> is no `BEDROCK_MODEL_ID` env var, and the smoke is a plain invoke (no model round-trip). The
> Bedrock items below apply ONLY when the unit is model-bearing.

- Function URL auth mode **`AWS_IAM` — never `NONE`** (a public
  Bedrock-invoking endpoint is an open cost hole). README test uses
  `curl --aws-sigv4` or `aws lambda invoke`.
- Terraform locks: timeout 60s, memory 512 MB, `source_code_hash` on the
  package, CloudWatch log group, env vars `AWS_REGION` + `BEDROCK_MODEL_ID`,
  role with `bedrock:InvokeModel` scoped to the resolved model ARN.
- Packaging: zip via pip target-dir; if deps exceed zip limits, container
  image packaging (note it in README).
- Teardown: `terraform destroy`.

## lambda_microvms

Artifacts: the full **lambda** shape above, PLUS `microvms.tf.disabled`.

- **Fallback rule**: every MicroVMs-specific flag or config key MUST be
  MCP-verified this run. If verification fails, the file stays `.disabled`
  with this header: "MicroVMs config pending verification — POC deploys as
  standard Lambda; rename after verifying against AWS docs." No deployable
  claim is made for unverified MicroVMs config.
- If verified: rename guidance in README; config keys cite the verification
  in the freshness footer.

## batch

Artifacts: `Dockerfile`, `batch-poc.tf`, `job.py`, `deploy.sh`, `README.md`.

> **Model-less variant** (common for `batch` — a job that calls no model, `model_recommendation:
> null`): `job.py` does its compute with no Bedrock call, the job role omits `bedrock:InvokeModel`
> (keeping only its data-access policies, e.g. S3), no `BEDROCK_MODEL_ID` env var, and the smoke
> is job SUCCEEDED (no model round-trip). The `bedrock:InvokeModel` grant below applies ONLY when
> the job actually calls a model.

- **Terraform may create ONLY**: `aws_batch_compute_environment` (Fargate
  compute environment), `aws_batch_job_queue`, `aws_batch_job_definition`,
  `aws_ecr_repository`, CloudWatch log group, IAM execution role and job
  role. Job role gets `bedrock:InvokeModel` scoped to the resolved model ARN
  when the job calls a model, plus least-privilege policies for whatever the
  job reads/writes (e.g. S3 GetObject/PutObject for bucket-scoped data).
- **Terraform must NEVER create**: VPC, subnets, NAT gateway, internet
  gateway, always-on compute resources.
- Networking: `VPC_ID`/`SUBNET_IDS` env vars → if unset, data-source the
  default VPC → if no default VPC exists, FAIL with a clear message; never
  create one. Fargate jobs run in the specified subnets with public IP
  assignment when in the default VPC (no NAT assumption).
- Image tag: `poc-<run_id>`. deploy.sh creates the ECR repo if missing
  (inside the typed-confirm section), builds, pushes.
- Smoke path: deploy.sh finishes by running `aws batch submit-job` with the
  POC job definition, then polls `aws batch describe-jobs` until the job
  reaches `SUCCEEDED` status, and prints the CloudWatch Logs command to read
  the job's output. A job definition that cannot be invoked is not a POC.
- Teardown: `terraform destroy` deregisters the job definition, deletes the
  queue and compute environment, and deletes the ECR repository. Note that
  resources that are not deletable while jobs are running — drain the queue
  first before `terraform destroy` if jobs are in-flight.
- deploy.sh guardrails: cost warning at top; typed `read -p "Type 'deploy' to
  continue"` confirmation before any resource-creating call; region and model
  id (when the job calls a model) via env vars `AWS_REGION` and
  `BEDROCK_MODEL_ID`; NO credentials embedded; volatile CLI flags carry
  `TODO: verify` unless MCP-verified this run.
- Secrets: API keys, tokens, or sensitive configuration go in SSM Parameter
  Store (SecureString) or Secrets Manager, referenced in the job definition
  via `secrets` — never inline in the job definition or Terraform.

## Composite (multi-unit) layout

With >1 unit in design.json, nest per-unit POCs under `poc/<unit-id>/`, each applying
its own runtime shape. A top-level `poc/README.md` orchestrates: deploy ORDER, per-unit
deploy.sh pointers, env-var interconnects only. Single unit collapses to today's flat
layout. See poc.md Step 3 UNIT DISPATCH as the authority.

## Temporal worker POC (used by poc.md Step 3 unit dispatch for temporal_worker_poll units)

**Base shape follows the unit's `effective_runtime`, NOT always ECS:**

- `effective_runtime == "ecs"` (or `serverless_workers`, which is Public Preview and smoke-deploys
  on ecs) → reuse the **ecs** shape's Terraform allowlist/never-list and guardrails, with the
  Temporal deltas below.
- `effective_runtime == "eks"` → reuse the **eks** shape's cluster model (kubectl + existing
  cluster, NO Terraform, unique `agent-advisor-poc-<run_id>` namespace) but OVERRIDE its
  artifacts for a worker (NOT the generic HTTP shape — a Temporal worker exposes NO HTTP
  endpoint, so there is NO `service.yaml`, NO `ClusterIP`, and NO `kubectl port-forward` + curl
  smoke):
  - Artifacts: `Dockerfile` (COPYs `smoke_worker.py`), `smoke_worker.py`, `k8s/namespace.yaml`,
    `k8s/deployment.yaml` (runs `smoke_worker.py worker`, long-poll), `k8s/smoke-job.yaml` (the
    one-shot starter `Job` running `smoke_worker.py start`), `deploy.sh`, `README.md`. NO
    `service.yaml`.
  - Smoke: apply `k8s/smoke-job.yaml` (a one-shot `Job`, NOT an ECS `run-task`); the proof is the
    starter's printed result, verified via `kubectl logs job/<name>`, NOT an HTTP curl.
  - Secrets: the API key/cert material is loaded into a **Kubernetes Secret** created by
    `deploy.sh` from env/files (`kubectl create secret`) — do NOT commit connection material into
    a generated `secret.yaml`. Scalar values (e.g. `TEMPORAL_API_KEY`) are injected as env vars
    via `secretKeyRef`. But the `TEMPORAL_TLS_CA_PATH` / `TEMPORAL_TLS_CERT_PATH` /
    `TEMPORAL_TLS_KEY_PATH` vars are FILE PATHS — mount the cert Secret keys as a **volume**
    (`volumeMounts` at, e.g., `/tmp/temporal-tls/`) and set those `*_PATH` env vars to the mounted
    file paths; do NOT `secretKeyRef` cert contents into the path variables (that puts PEM bytes
    where `smoke_worker.py` expects a filename, and it fails opening the path).
  - Teardown: `kubectl delete -f k8s/` (+ the one-shot starter pod/Job) — NEVER `terraform
    destroy` (this base creates no Terraform).
    The task queue is still `poc-smoke-<run_id>` and the connection env contract is identical. An
    EKS-selected worker therefore gets a Kubernetes worker POC, not an ECS Fargate one.

Temporal deltas (apply on whichever base shape the effective_runtime selected):

- The container runs `smoke_worker.py worker` (long-poll worker); the smoke
  is a SEPARATE one-off starter of `smoke_worker.py start` — on the **ECS**
  base an `aws ecs run-task` (or local run), on the **EKS** base a one-shot
  `Job` (`k8s/smoke-job.yaml`). Deploy succeeding proves nothing by itself —
  the starter's printed result is the proof.
- Task queue: `poc-smoke-<run_id>` — never the user's real queues.
- **Connection env contract (explicit — never inferred):**

  Connection via the full env contract — `TEMPORAL_ADDRESS`,
  `TEMPORAL_NAMESPACE`, `TEMPORAL_TLS`, `TEMPORAL_API_KEY`,
  `TEMPORAL_TLS_SERVER_NAME`, `TEMPORAL_TLS_CA_PATH`,
  `TEMPORAL_TLS_CERT_PATH`, `TEMPORAL_TLS_KEY_PATH` — mapped EXPLICITLY to
  `Client.connect(tls=TLSConfig(...))`; `TEMPORAL_TLS` is never inferred
  from other vars.

| Env                                                | Meaning                              |
| -------------------------------------------------- | ------------------------------------ |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`           | always required                      |
| `TEMPORAL_TLS`                                     | `off` / `tls` / `mtls`               |
| `TEMPORAL_API_KEY`                                 | Cloud API-key auth (with `tls`)      |
| `TEMPORAL_TLS_SERVER_NAME`                         | SNI override (self-hosted behind LB) |
| `TEMPORAL_TLS_CA_PATH`                             | custom root CA (self-hosted TLS)     |
| `TEMPORAL_TLS_CERT_PATH` / `TEMPORAL_TLS_KEY_PATH` | client cert/key (`mtls`)             |

- Secrets material (API key, cert/key) is never inline: on **ECS** it comes from SSM Parameter
  Store (SecureString) or Secrets Manager via task-definition `secrets`; on **EKS** it comes from
  a Kubernetes Secret mounted into the pod. `run_local.sh` reads local file paths.
- Teardown wording follows the base: on **ECS**, `terraform destroy` stops the worker; on
  **EKS**, `kubectl delete -f k8s/` (plus the one-shot starter pod/Job) — never `terraform
  destroy` on the EKS base. Either way, Temporal **task queues are not deletable resources** —
  the `poc-smoke-<run_id>` queue metadata ages out on its own and never touches production queues.
