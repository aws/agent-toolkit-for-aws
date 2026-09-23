# Compute

Pass-2 rubric for every compute type `index.md` routes here. Loaded only when the
inventory contains one.

**Outcome is `confidence: inferred`**, or `measured` when observed utilization backed the
sizing. Never `deterministic` — that tier is reserved for `fast-path-services.json` rows,
and no compute decision is architecture-invariant.

## 1. Eliminators — hard technical blockers

Checked first, before any preference. An eliminator is physics or a product boundary, not
a judgement, so it removes a candidate outright.

| Candidate          | Eliminated when                                                                                                                                                                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **AWS App Runner** | **ALWAYS. It is not a candidate for anything.** No longer accepting new customers as of April 2026. Do not offer it, do not mention it as a forward-look, do not put it in a candidate list. ECS Express Mode may be mentioned only as a forward-look on the Fargate path |
| Lambda             | the workload runs longer than **15 minutes** per invocation — a hard ceiling, not a quota                                                                                                                                                                                 |
| Lambda             | the function is a **Durable Function** (an orchestrator, entity, or activity binding). Durable's state machine has no Lambda equivalent; it maps to Step Functions plus Lambda, which is a re-architecture and therefore a rubric decision, not a like-for-like           |
| Lambda             | the plan is **not** a consumption plan and `always_on` is true — a warm always-on process is not what Lambda is                                                                                                                                                           |
| Lambda             | the app needs a **writable local filesystem** beyond `/tmp`, or persistent local state                                                                                                                                                                                    |
| Elastic Beanstalk  | the workload is **Windows Containers**. EB supports Windows Server platforms and Linux Docker, not Windows containers                                                                                                                                                     |
| Elastic Beanstalk  | more than one **distinct process type** must scale independently. EB scales an environment, not a process within it — this is heroku-to-aws's non-web-formation finding, and it applies identically here                                                                  |
| Fargate            | the workload needs **GPU**. Fargate has none — route to EC2 and `gpu-hpc.md`                                                                                                                                                                                              |
| Fargate            | the workload needs a **privileged container**, a kernel module, or a custom kernel                                                                                                                                                                                        |
| EKS                | never eliminated, but never selected without a signal — see criterion 2                                                                                                                                                                                                   |
| EC2                | never eliminated. It is the floor: anything can run on EC2                                                                                                                                                                                                                |

## 2. The six criteria, in order, first match wins

Do not weigh these. Apply them in sequence and stop at the first that fires. Adding a
seventh, or reordering, breaks the property that makes the outcome reproducible.

### 2.1 Eliminators

Section 1. Whatever survives is the candidate set.

### 2.2 Operational model

What the source workload _is_ decides more than anything the customer could tell us.

| Source                                                                                                   | Target                                                                   |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `Microsoft.ContainerService/managedClusters`                                                             | **EKS** — fast-path row, never reaches this file                         |
| `Microsoft.Web/serverfarms` whose hosted sites are all functions on a **consumption** plan (`Y1`, `FC1`) | **Lambda**                                                               |
| `Microsoft.Web/serverfarms` hosting web apps                                                             | **Elastic Beanstalk**                                                    |
| `Microsoft.App/containerApps` / `managedEnvironments`                                                    | **Fargate**                                                              |
| `Microsoft.ContainerInstance/containerGroups`                                                            | **Fargate** — a one-shot task becomes a Fargate task, not a service      |
| `Microsoft.Compute/virtualMachines`                                                                      | **EC2**, MGN-based cutover                                               |
| `Microsoft.Compute/virtualMachineScaleSets`                                                              | **EC2 Auto Scaling group**                                               |
| `Microsoft.Web/staticSites`                                                                              | **S3 + CloudFront**, plus Lambda + API Gateway for its managed functions |

**Elastic Beanstalk is the App Service Plan default, and the reason is posture not
preference.** App Service is a managed platform the customer already pays for: AWS
manages deployments, scaling, patching, and health. Fargate hands them a container
lifecycle they did not previously own. Moving a PaaS workload to containers _during_ a
cloud migration changes two variables at once, and when it goes wrong there is no way to
tell which one caused it.

### 2.3 User preference

`preferences.json` → `design_constraints.compute_target` **overrides 2.2**, per-resource
overrides beating the global default. This is the criterion the customer's own answer
lives in, and it sits above feature parity deliberately: a team that has decided to run
containers has decided, and re-deriving Elastic Beanstalk from the source shape would be
overruling them.

Recognised values: `elastic_beanstalk`, `ecs-fargate`, `eks-managed`, `ec2`, `lambda`.
An absent preference is not a preference — fall through, do not default here.

### 2.4 Feature parity

Only reached when 2.2 and 2.3 disagree with what the workload can actually do.

| Signal                                                                   | Consequence                                                                                                 |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| the plan runs **containers** (`linux_fx_version` is a `DOCKER\|…` image) | Fargate over Elastic Beanstalk — the app is already a container, so the PaaS argument in 2.2 does not apply |
| **VNet integration** is configured on the site                           | any target, but the design must place it in private subnets and say so                                      |
| an app runs `WEBSITE_RUN_FROM_PACKAGE`                                   | EB source bundles are equivalent; no target change, worth a note                                            |
| a **deployment slot** exists                                             | EB blue-green via swap URL, or a weighted target group on Fargate                                           |
| `always_on = false` on a non-consumption plan                            | the customer is tolerating cold starts; Lambda becomes viable if 2.2 pointed at EB                          |

### 2.5 Cluster context

Read the cluster's other members via `azure-resource-clusters.json` and its
`pattern_id`. **A pattern may narrow the candidate set; it may never override a
`deterministic` mapping** — and it never reaches this file for one, because a fast-path
row does not run a rubric.

The useful case is homogeneity: a function app inside a cluster whose primary is a
Fargate-bound container workload probably belongs on Fargate rather than Lambda, because
one runtime is cheaper to operate than two. When the cluster's `pattern_status` is
`catalog_absent` or `unclassified`, this criterion has nothing to say — skip it rather
than inventing an architecture.

### 2.6 Simplicity

The tiebreak, and it has a direction: **prefer the target with fewer moving parts the
customer has to operate.** EB over Fargate over EKS, all else equal. If two candidates
survive to here, they are genuinely equivalent for this workload and the operational
burden is the only remaining difference.

## 3. The App Service Plan fan-in

Enforced in `design-infra.md`; restated here only as the thing that makes sizing
correct. **The plan is the compute unit. Its apps are deployments onto it.** Five web
apps on one S1 plan cost one S1. Size from the plan's `sku_name` and `worker_count`,
never from the app count, and emit exactly one compute entry per plan carrying
`hosted_app_azure_ids` and `sizing_source`.

## 4. CPU architecture

**Default `x86_64`. This diverges from the rest of the repo deliberately.** Graviton is
the default in gcp-to-aws and heroku-to-aws; here it is an offered optimization with its
own savings line.

The reason is base rates, not capability: Azure fleets carry Windows and .NET far more
often than GCP or Heroku fleets, and `references/shared/graviton.md`'s escape path
(Windows, .NET Framework, GPU/CUDA, RDS SQL Server) fires routinely. Defaulting to
Graviton would mean walking the recommendation back on a large fraction of real estates,
and a recommendation that gets withdrawn costs more trust than one that was never made.

Offer Graviton when **all** hold: Linux, no .NET Framework (modern .NET on Linux is
fine), no GPU requirement, and no x86-only binary dependency in the app-code signals.

## 5. Right-sizing — post-selection, not a criterion

Runs **after** a service is chosen. It is not a seventh criterion, because the six select
a service and never touch capacity; adding one would break first-match-wins.

- **No utilization data** → dev-tier default from `knowledge/design/appservice-eb-sizing.json`
  (or `vm-ec2-sizing.json` for VMs), `confidence: inferred`.
- **P95 utilization available** (RDfA rollup or `az monitor metrics list`) → apply the
  bands and the aggressiveness slider in `knowledge/estimate/rightsizing-thresholds.json`,
  and stamp `confidence: measured` citing the evidence.
- **Metrics window under ~14 days** → size from them but keep `confidence: inferred`, and
  say why. A short window over a quiet fortnight is how a workload gets sized for a
  trough it will leave.

Sizing never revisits the service choice. If the right size for the chosen service does
not exist, that is a finding for the report, not a reason to re-run the rubric.

## 6. Output

Per `schema-design-aws.md` § `services[]`: `aws_service`, `aws_config` (instance type or
task size, count, scaling bounds, platform), `confidence`, `rubric_applied: "compute.md"`,
and a `rationale` naming **which criterion fired**. "Elastic Beanstalk, because the source
is a managed App Service Plan (criterion 2.2) and no compute-target preference was
recorded" is auditable. "Elastic Beanstalk is a good fit" is not.

## Status — build step 5

Implemented for App Service Plans, VMs, VMSS, container apps, container instances, and
static sites. The sizing tables now exist: `knowledge/design/appservice-eb-sizing.json`
for App Service plans and `knowledge/design/vm-ec2-sizing.json` for VMs and scale sets,
with `knowledge/estimate/rightsizing-thresholds.json` for the measured path. Look the size
up and stamp `sizing_provenance: "table"`.

If a SKU is not in the table, stamp **`sizing_provenance: "model_prior"`**, add a
`warnings[]` entry naming the SKU, and say in the rationale that the number is not sourced.
Do not write `table` for a row you did not find. The earlier instruction here — "state the
dev-tier default and say the table is absent rather than inventing a number" — was
unsatisfiable: with no table, the default WAS the invented number, and every size in the
committed golden turned out to be a pretrained association. `gpu-hpc.md` is still to land;
GPU sizes are decisions with named options in `vm-ec2-sizing.json`, not lookups.
