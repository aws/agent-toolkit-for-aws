# Graviton (ARM64) Cost Optimization

> **Conditionally loaded.** Load this file during Design, Estimate, and Generate when the inventory contains compute, database, or cache resources, OR when a `graviton_profile` is present in discovery output. Do not load for billing-only or AI-only runs.

AWS Graviton (ARM64) instances cost **~15–20% less per hour** than same-spec x86 instances and are the default target for eligible workloads. This file is the single source of truth for Graviton compatibility tiering, instance mapping, and per-phase behavior. Other files reference it; they do not duplicate its tables.

---

## Savings model (keep the two mechanisms separate)

| Mechanism                                     | Magnitude                                           | Modeled in Estimate?                                                                                                      |
| --------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Instance-hour price discount**              | 15–20% lower per hour vs x86 at same vCPU/memory    | **Yes** — this is the only savings counted in automated math                                                              |
| **Performance uplift** (may allow downsizing) | workload-dependent, up to ~25% more throughput/vCPU | **No** — mention in Design narrative only ("validate with load test; you may be able to downsize further"); never counted |

**Why vCPU ≠ capacity:** Graviton vCPUs are physical cores; x86 vCPUs are typically hyperthreaded logical cores. The instance mapping below is a _starting point_, not a capacity guarantee. Right-sizing requires benchmarking.

---

## Compatibility tiers

Discover assigns each compute service a `tier`. Design and Estimate branch on it.

| Tier           | Meaning                                                                                                                          | Design behavior                                                                          |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `ready`        | arm64-native, no code changes (Python, Node.js, Go, PHP, Ruby, pure-JVM Java, .NET 6+ on Linux)                                  | Default to Graviton; no Clarify question needed                                          |
| `conditional`  | likely fine but needs verification (JNI deps, niche C extensions, Rust/C/C++ recompile, native gem extensions, vendor AMIs)      | Default to Graviton **with caveat noted**; surface in Clarify if risk signals are strong |
| `incompatible` | cannot run on Graviton (Windows/.NET Framework, GPU/CUDA → route to G5/G6, RDS SQL Server, heavy SSE/AVX SIMD without NEON port) | Keep x86; never recommend Graviton                                                       |
| `unknown`      | architecture not determinable (IaC-only or billing-only signal)                                                                  | Treat as `conditional`; ask in Clarify before defaulting                                 |

### Managed services (instance-family swap only — no code impact)

RDS (MySQL/PostgreSQL/MariaDB), Aurora, ElastiCache, OpenSearch, and MSK all support Graviton node/instance families and are **`ready`** by default. ECS Fargate and Lambda support ARM64 via a single config setting. **RDS SQL Server is `incompatible`**; RDS Oracle is `conditional` (version-dependent).

---

## GCP → Graviton instance mapping (starting point)

| GCP machine type              | AWS x86 equivalent       | AWS Graviton equivalent |
| ----------------------------- | ------------------------ | ----------------------- |
| e2-standard-4 / n2-standard-4 | m5.xlarge / m6i.xlarge   | m7g.xlarge              |
| e2-standard-8 / n2-standard-8 | m5.2xlarge / m6i.2xlarge | m7g.2xlarge             |
| c2-standard-8                 | c5.2xlarge / c6i.2xlarge | c7g.2xlarge             |
| n2-highmem-4                  | r5.xlarge / r6i.xlarge   | r7g.xlarge              |
| e2-micro / e2-small           | t3.micro / t3.small      | t4g.micro / t4g.small   |
| e2-medium                     | t3.medium                | t4g.medium              |

Verify exact pricing per target via `pricing-cache.md` (dev-tier rows); set `pricing_source: "unavailable"` for any family/size not cached.

---

## Phase touchpoints

### Discover (`discover-app-code.md`, `discover-iac.md`)

Emit a `graviton_profile` per compute service (schema in `schema-graviton.md`). Populate `tier`, `signals[]`, and `caveats[]` from the detection signals in `schema-graviton.md`. GPU/CUDA → `tier: "incompatible"`, caveat `"route to G5/G6"`.

### Clarify (`clarify-compute.md`)

**Default-when-compatible:** if ALL compute services are `tier: ready`, do NOT ask — default to Graviton (consistent with existing `db.t4g` defaults). Only ask the Graviton question when any service is `conditional`/`unknown` with risk signals. Question wording lives in `clarify-compute.md`.

### Design (`design-refs/compute.md`)

Branch on `preferences.design_constraints.cpu_architecture`:

- `graviton` (or absent + all-ready): emit Graviton instance types in every eligible mapping; Lambda `arm64`; Fargate ARM64; managed-service Graviton families.
- `conditional` services: emit Graviton **and** record caveats + "validate after migration" in the design.
- `incompatible` services: emit x86, record why.
- Containers default to **arm64-only** builds (multi-arch only when the user chose per-service or has x86 holdouts).
  Add the `graviton` block (schema in `schema-graviton.md`) to each compute service in `aws-design.json`.

### Estimate (`estimate-infra.md`)

Model **only** the hourly price discount. Use `pricing-cache.md` Graviton rows when present; otherwise set `pricing_source: "unavailable"` for the affected rows. Emit an `architecture_comparison` block (schema in `schema-graviton.md`). Do **not** add Graviton as a fourth pricing tier — it is the architecture within Balanced/Premium/Optimized. Balanced tier uses Graviton pricing when selected.

### Known limitations (v1 — tracked follow-ups)

- **Database/cache opt-out not yet propagated.** Only `design-refs/compute.md` branches on `cpu_architecture`. Managed databases and caches already default to Graviton families (`db.t4g`, `cache.t4g`) regardless, so there is **no compatibility risk** — but an explicit `x86`/`mixed` choice does not yet flow into `design-refs/database.md` or the cache mapping. Follow-up: have those refs honor `cpu_architecture` for full consistency. (Graviton on managed DB/cache has no code impact, so this is a consistency gap, not a correctness one.)
- **Billing-only Discover** does not yet emit `graviton_profile` (see `schema-graviton.md` § Billing only). The Q11b decision table covers billing-sourced compute by asking when no profile exists.

### Report rendering (follow-up — not yet implemented)

The cost report should surface Graviton savings, but the report generator and its validator (`generate-artifacts-report.md`, `shared/validate-migration-report.md`, `scripts/validate-migration-report.py`) do not cover `architecture_comparison` today. A follow-up should:

- Render `architecture_comparison` in the report's cost breakdown / decision summary (a "Graviton savings" line: `graviton_monthly` vs `x86_equivalent_monthly`, `savings_percent`), reusing the report generator's existing section-ID and table conventions.
- Add a numeric assertion to `validate-migration-report.py` that the rendered Graviton savings match `estimation-infra.json` → `architecture_comparison` (`savings_amount` / `savings_percent`). That validator is intentionally structural-only today, so this is a net-new check, not a modification of existing behavior.

Until then, numeric agreement between report and `architecture_comparison` is a manual self-check.

### Generate (`generate-artifacts-infra.md`)

Emit ARM64 in Terraform:

- EC2: `instance_type = "m7g.xlarge"` (etc.)
- ECS Fargate: `runtime_platform { cpu_architecture = "ARM64", operating_system_family = "LINUX" }`
- Lambda: `architectures = ["arm64"]`
- EKS: arm64 AMI node group (single-arch on dev; note optional mixed-cluster module for prod)
- Docker build step in the runbook: `docker build --platform linux/arm64` (not multi-arch by default)
  Include a "Graviton Migration Notes" section in the output docs: services moved to arm64, any `conditional` caveats, and the recommendation to validate with a load test post-migration.

---

## Recommendation rules

**Default to Graviton (no Clarify question)** when ALL services are `ready` — containerized Python/Node/Go/PHP/Ruby/pure-JVM Java, Lambda with no native binary layer, or a Graviton-supported managed service, and the user has not opted out.

**Ask in Clarify** when any service is `conditional` with risk signals (JNI, niche C extensions, native gems, vendor AMIs, recompile-required languages).

**Never recommend Graviton** for Windows/.NET Framework, GPU/CUDA (route to G5/G6), RDS SQL Server, or x86-only native dependencies without an arm64 alternative — or when the user opted out in Clarify.

---

## Tooling references (for narrative/docs, not automated math)

- [Porting Advisor for Graviton](https://aws.amazon.com/blogs/compute/using-porting-advisor-for-graviton/) — source scan for arm64 compatibility issues
- [AWS Graviton Getting Started](https://github.com/aws/aws-graviton-getting-started) — language-specific guides, ISV compatibility list
- [AWS Compute Optimizer Graviton guidance](https://aws.amazon.com/blogs/compute/aws-compute-optimizer-supports-aws-graviton-migration-guidance/) — per-instance migration effort ratings (existing AWS customers)
