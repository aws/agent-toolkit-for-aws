---
_fragment: compute
_of_phase: clarify
_contributes:
  - preferences.json (design_constraints section, app_service_plans[])
---

# Clarify — Compute

> **Fragment unit.** See `clarify.md` for how it is composed into the phase.
>
> **This fragment asks nothing.** It reads the inventory, resolves what it can, assigns a
> disposition per row, and returns rows. `clarify-assemble.md` presents them.

Fires when the inventory contains any compute resource. Category C, the Azure analogue of
gcp's Compute Model category.

## Step 1: Extract before proposing

Resolve from the inventory first — a DETECTED row costs the user nothing to confirm, and a
question that discovery could have answered is a question that should not have been asked.

| Read from the inventory                                                         | Resolves                                      |
| ------------------------------------------------------------------------------- | --------------------------------------------- |
| every `Microsoft.Web/serverfarms` entry's `sku_name`, `worker_count`, `os_type` | the compute unit and its current capacity     |
| the `hosted_on` edges into each plan                                            | how many apps share it — the input to Q-C2    |
| any site's `linux_fx_version` containing `DOCKER\|`                             | the workload is already containerised         |
| every VM / VMSS `os_type` and `image_publisher`                                 | whether Windows is present, which forces Q-C4 |
| `Microsoft.ContainerService/managedClusters` present                            | Kubernetes is already in use                  |

## Step 2: The rows

### Q-C1 — Compute target

**N/A when `clarify-global.md`'s Q-A1d (multi-cloud portability) already forced
`design_constraints.compute_target` to `eks`** — check that row first; if
`forced_by: "multi_cloud_required"` is set, emit this row as N/A with that reason and do
not ask Q-C1 at all. Portability is an estate-wide decision, not a per-workload one.

**Disposition (otherwise):** DETECTED when an AKS cluster is the only compute in the estate
(Kubernetes is already the answer); PROPOSED otherwise.
**Default:** `elastic_beanstalk`.

```
Where should your App Service workloads run on AWS?

[A] Elastic Beanstalk — closest to App Service: AWS manages deployment,
    scaling, patching and health checks                        (default)
[B] ECS Fargate — you own the container lifecycle, and get direct
    control over task definitions and scaling
[C] EKS — only if your team already runs Kubernetes
```

**Consequence line for the sheet:** _Assuming Elastic Beanstalk → the managed-platform
posture you already pay for is preserved. Choose Fargate for direct container control, or
EKS only if you already operate Kubernetes._

Why EB is the default and not Fargate: moving a PaaS workload to containers **during** a
cloud migration changes two variables at once, and when something breaks afterwards there
is no way to tell which one caused it. Fargate is the better destination for many teams —
it is just a bad thing to decide implicitly.

**Override:** if Step 1 found a site with a `DOCKER|` image, set the default to
`ecs-fargate` and say why in the row — the app is already a container, so the argument
above does not apply to it.

### Q-C2 — App Service Plan isolation (one row per plan hosting more than one app)

**Disposition:** PROPOSED. **Default:** `false` — no split.

```
Plan asp-contoso-web (S1 x2) hosts 5 apps: storefront, admin, checkout,
docs, webhooks. On Azure they share the plan's capacity and cost one S1.

[A] Keep them together — one Elastic Beanstalk environment  (default)
[B] Split into separate environments per app
```

**Consequence line:** _Keeping them together mirrors what you pay for today. Splitting
gives each app its own environment and its own failure domain — and multiplies the compute
line by the number of apps._

**N/A** for a plan hosting zero or one app. A zero-app plan gets no isolation row at all;
it gets the idle-capacity finding instead.

This row exists because it is the single largest estimate swing in the phase and it is
**not inferable** — nothing in the configuration distinguishes "these five apps are one
product" from "these five apps must never share a host."

### Q-C3 — CPU architecture

**Disposition:** DETECTED (`x86_64`, not a choice) when Windows or .NET Framework is
present anywhere in the estate; PROPOSED otherwise.
**Default:** `x86_64`.

```
[A] x86_64 — broadest compatibility                          (default)
[B] Graviton (arm64) — roughly 20% cheaper for equivalent capacity
```

**Consequence line:** _x86_64 is the default here because Azure estates carry Windows and
.NET routinely. If your workloads are Linux with no x86-only dependency, Graviton reduces
compute cost for the same capacity._

**This default diverges from every other skill in this repo, deliberately** — gcp and
heroku default to Graviton. `references/shared/graviton.md`'s escape path (Windows, .NET
Framework, GPU/CUDA, RDS SQL Server) fires routinely on Azure fleets, and a recommendation
that has to be withdrawn costs more trust than one never made. When the row is DETECTED,
say _which_ resource forced it.

### Q-C4 — Traffic pattern

**Disposition:** PROPOSED. **Default:** `steady`.

```
[A] Steady — roughly constant load                            (default)
[B] Business hours — quiet overnight and at weekends
[C] Spiky — unpredictable bursts
```

**Consequence line:** _Assuming steady load → sized from your current capacity with no
scheduled scaling. Business-hours or spiky patterns change the scaling policy and can
lower the estimate materially._

### Q-C5 — Long-lived connections

**Disposition:** DETECTED when a SignalR service is in the inventory (the answer is yes);
PROPOSED otherwise. **Default:** `false`.

```
Do any of these apps hold WebSocket or other long-lived connections?

[A] No                                                        (default)
[B] Yes
```

**Consequence line:** _Assuming none → standard ALB configuration. Long-lived connections
change idle-timeout and target-group settings, and rule Lambda out for those workloads._

### Q-C6 — VM cutover strategy — **ESSENTIAL**

**Disposition:** ESSENTIAL when the inventory contains any
`Microsoft.Compute/virtualMachines` or `virtualMachineScaleSets`; **N/A** otherwise.
**No default.**

```
How should your VMs move?

[A] Replicate as-is with AWS Application Migration Service (MGN) —
    block-level replication, shortest cutover, keeps the guest exactly as it is
[B] Rebuild from a golden AMI and redeploy the application
```

There is no default because the two produce **entirely different migration runbooks** —
MGN is a replication project, a rebuild is a packaging project — and guessing wrong makes
every downstream artifact wrong, not merely imprecise. This is the direct analogue of
gcp's Q7 (cutover strategy), which is also ESSENTIAL and also never assumed.

**Hard blocker, not a question:** if any VM's `image_sku` contains `azure-edition`, MGN
will **refuse** the image until it is re-imaged to a standard Windows Server edition. Say
so as a warning on the sheet, and do not present option [A] as available for that VM.
There is nothing to weigh, so offering a choice would imply one of the answers works.

## Step 3: Rows returned

```jsonc
"design_constraints": {
  "compute_target":    { "disposition": "PROPOSED", "value": null, "default": "elastic_beanstalk" },
  "cpu_architecture":  { "disposition": "PROPOSED", "value": null, "default": "x86_64" },
  "traffic_pattern":   { "disposition": "PROPOSED", "value": null, "default": "steady" },
  "long_lived_connections": { "disposition": "PROPOSED", "value": null, "default": false },
  "vm_cutover":        { "disposition": "ESSENTIAL", "value": null, "default": null }
},
"app_service_plans": [
  { "plan_azure_id": "<azure_id of the 5-app plan>", "hosted_app_count": 5,
    "isolation_split": { "disposition": "PROPOSED", "value": null, "default": false } },
  { "plan_azure_id": "<azure_id of a 1-app plan>",  "hosted_app_count": 1,
    "isolation_split": { "disposition": "N/A", "value": null, "default": null,
                         "reason": "one app — nothing to isolate from" } },
  { "plan_azure_id": "<azure_id of a 0-app plan>",  "hosted_app_count": 0,
    "isolation_split": { "disposition": "N/A", "value": null, "default": null,
                         "reason": "no apps — idle capacity, raised as a cost finding instead" } }
]
```

**ONE ROW PER PLAN, always — including plans you do not ask about.** A plan with 0 or 1
hosted app gets a row with `isolation_split.disposition: "N/A"` and a `reason`; it does
**not** get a question, because asking whether to isolate one app from nothing is a
meaningless question in front of the user.

Emitting rows only for the plans you questioned is the trap: `design-infra.md`'s fan-in
rule and `design.md`'s `Microsoft.Web/sites` postcondition both look a plan up here, and a
plan with no row is indistinguishable from a plan the user declined to split. The count of
rows must equal the count of `Microsoft.Web/serverfarms` resources in the inventory.

`value: null` means the user has not answered. The assembler resolves it to the default and
keeps the disposition PROPOSED — **never** promote a default to a user decision, because
Design's rationale distinguishes "you chose this" from "we assumed this" and the report
prints the difference.

## Who consumes these

| Row                      | Consumer                                                                                          |
| ------------------------ | ------------------------------------------------------------------------------------------------- |
| `compute_target`         | `design-refs/compute.md` criterion 2.3, which **overrides** the operational-model default in 2.2  |
| `isolation_split`        | `design-infra.md`'s fan-in rule, and `design.md`'s postcondition on `Microsoft.Web/sites` entries |
| `cpu_architecture`       | `compute.md` § CPU Architecture, and Estimate's instance selection                                |
| `traffic_pattern`        | Estimate's scaling assumptions                                                                    |
| `long_lived_connections` | `compute.md`'s Lambda eliminator, and the ALB configuration in Generate                           |
| `vm_cutover`             | Generate's migration runbook shape                                                                |

## Status — build step 5

Implemented. The `gpu-hpc.md` branch (ND/NC/NV/HB/HX VM series) is not wired yet — a GPU
VM currently takes the ordinary EC2 path, and that is a known gap rather than a decision.
