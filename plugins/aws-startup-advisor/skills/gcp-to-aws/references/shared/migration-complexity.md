# Migration Complexity Tiers

Shared classification loaded by `generate-billing.md` and `generate-infra.md` to right-size migration timelines. The AI path (`generate-ai.md`) self-sizes from workload profiles and does not use this file.

## Inputs

Collect these values from prior-phase artifacts before classifying:

| Input                | Source Artifact                                   | Key                                                                                     |
| -------------------- | ------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Service count        | `aws-design-billing.json` or `aws-design.json`    | `metadata.total_services`                                                               |
| Monthly spend        | `billing-profile.json` or `estimation-infra.json` | `summary.total_monthly_spend` or `current_costs.gcp_monthly`                            |
| Has databases        | Design artifact `services[]`                      | `aws_service` in {RDS, Aurora, DynamoDB, ElastiCache, DocumentDB, MemoryDB, OpenSearch} |
| Has stateful storage | Design artifact `services[]`                      | `aws_service` in {EFS, FSx, S3} with replication or versioning hints in `sku_hints`     |
| Has AI workloads     | `estimation-ai.json` exists                       | File presence                                                                           |
| Availability         | `preferences.json`                                | `design_constraints.availability`                                                       |
| Compliance           | `preferences.json`                                | `design_constraints.compliance`                                                         |
| Multi-region         | Design artifact `services[]`                      | More than one distinct `aws_config.region` value                                        |

## Tier Definitions

Evaluate from **Large down to Small**. The first tier whose condition matches is the result (highest-matching-tier wins).

### Large

ANY of the following:

- Service count >= 9
- Monthly spend > $10,000
- Multi-region deployment (services span 2+ AWS regions)
- Compliance requirements present (`compliance` is not empty/none)

**AI isolation rule:** AI coexistence alone NEVER raises the infrastructure
tier. `generate-ai.md` independently sizes AI integration/evaluation effort,
and that work commonly runs in parallel with infrastructure. Count only
infrastructure complexity here; otherwise a one-service app with one model is
incorrectly classified Large and its effort is double-counted.

### Medium

NOT Large, and ANY of the following:

- Service count 4-8
- Monthly spend $1,000-$10,000
- Has databases
- Availability is `multi-az`

### Small

NOT Large, NOT Medium. Equivalently, ALL of:

- Service count <= 3
- Monthly spend < $1,000
- No databases or stateful storage with replication
- Availability is `single-az` or unspecified
- No compliance requirements

## Provenance (read before using any output from this file)

Tier classification, stage structure, and duration drivers are **planning heuristics derived from stack-shape thresholds — not calibrated to observed migrations**. Do NOT emit week counts or engineering-hour figures from this file into any artifact or user-facing output. Time is communicated three ways only: stage sequence (ordinal — real information), **duration drivers** (what makes THIS stack take longer), and operational time policies (watch periods, observation windows — policy choices, kept as-is). Always record `tier_bound_by` — the single input that bound the tier (e.g. `"compliance present"`, `"service_count >= 9"`) — so readers can see why the tier is what it is.

## Approach and Duration Drivers

### Billing-Only Path

| Tier   | Approach                      | Duration drivers to name (adapt to stack)                                                                  |
| ------ | ----------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Small  | `compressed`                  | Few services, no databases — discovery and provisioning overlap; cutover in one maintenance window         |
| Medium | `standard_with_discovery`     | Billing-only discovery gap (configs must be audited), database migration, parallel-run stage               |
| Large  | `conservative_with_discovery` | Extended discovery (no IaC), full parallel run, multi-region or compliance baseline, AI track when present |

### Infrastructure Path

| Tier   | Approach                   | Duration drivers to name (adapt to stack)                                                                          |
| ------ | -------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Small  | `compressed`               | Shallow dependency graph, no data-migration stage — smoke-test PoC, single cutover window                          |
| Medium | `phased_cluster_migration` | Cluster-by-cluster deployment in dependency order, data migration, parallel-run validation                         |
| Large  | `phased_cluster_migration` | Additional clusters and cross-cluster networking, large data volumes / replication topology, extended parallel run |

### Driver right-sizing

Duration drivers are the honest replacement for hour/week estimates. Name only
drivers that apply to THIS stack, and exclude calendar-only waiting,
observation windows, and parallel AI work already covered by `generate-ai.md`.

- Name the **binding** driver first (the same input recorded in
  `tier_bound_by`), then at most 2–3 secondary drivers.
- Exclude `N/A — API enablement` and `Deferred — specialist engagement` rows
  from `service_count`; they do not represent implementation work in this plan
  (deferred services may still be _named_ as a driver when their specialist
  track gates cutover).
- Never convert drivers back into hours or weeks anywhere downstream. If a
  reader asks "how long," the answer is the stage sequence + drivers + the
  operational time policies — plus the honest statement that the plugin has no
  calibrated duration data.

## Stage Templates

### Billing-Only Path

#### Small

No parallel-run stage. Discovery and provisioning overlap. Cutover uses maintenance window.

- **Stage 1: Discovery + Provisioning**
  - Quick audit of GCP infrastructure (few services, low complexity)
  - Provision AWS VPC, compute, and supporting resources
  - Configure IAM roles and security groups
- **Stage 2: Deploy + Test**
  - Deploy applications to AWS
  - Run functional and integration tests
  - Validate cost tracking against estimates
- **Stage 3: Cutover + Validation**
  - Execute cutover during maintenance window (DNS switch)
  - 24-hour intensive monitoring
  - Stabilization and GCP teardown planning

#### Medium

Shortened parallel run. Discovery is an abbreviated audit, not the extended Large-tier discovery.

- **Stage 1: Discovery Refinement**
  - Audit current GCP infrastructure
  - Document instance sizes, database configs, networking topology
  - Map dependencies between services
  - Refine AWS design based on discovered configurations
- **Stage 2: Service Migration**
  - Provision AWS infrastructure
  - Deploy applications and configure CI/CD
  - Integration testing and data migration dry run
- **Stage 3: Parallel Run**
  - Run both environments simultaneously
  - Compare performance, reliability, and costs
  - Validate data consistency
- **Stage 4: Cutover and Validation**
  - Execute cutover (DNS switch, traffic migration)
  - 48-hour intensive monitoring
  - Stabilization and GCP teardown planning

#### Large

Full conservative plan. Extended discovery, full parallel run.

- **Stage 1: Discovery Refinement**
  - Manual infrastructure audit, dependency mapping, configuration documentation
  - Refine AWS design, re-estimate costs, identify services needing different AWS targets
- **Stage 2: Service Migration**
  - Provision AWS infrastructure (VPC, compute, databases, storage)
  - Deploy applications, set up CI/CD, migrate to staging
  - Integration testing, performance baseline, data migration dry run
- **Stage 3: Parallel Run**
  - Run both GCP and AWS simultaneously
  - Compare performance, reliability, and costs
  - Validate data consistency between environments
  - Monitor for 2+ weeks before cutover decision
- **Stage 4: Cutover and Validation**
  - Execute cutover (DNS switch, traffic migration)
  - 48-hour intensive monitoring
  - Stabilization and GCP teardown planning

### Infrastructure Path

#### Small

Compressed setup. PoC is a 2-day smoke test, not a 2-week phase. No data migration stage (small tier excludes databases by definition).

- **Stage 1: Setup**
  - Provision VPC, subnets, IAM, monitoring baseline
  - Set up CI/CD pipeline for Terraform
- **Stage 2: Deploy + Smoke Test**
  - Deploy all clusters (few services, shallow dependency graph)
  - Run integration tests and validate connectivity
  - Confirm cost tracking matches estimates
  - Go/No-Go checkpoint
- **Stage 3: Cutover**
  - Execute cutover per `preferences.json` strategy
  - 24-48 hour monitoring
  - Keep GCP as hot standby
- **Stage 4: Validation + Cleanup**
  - Monitor AWS performance for 1 week
  - Compare costs to projections
  - Begin GCP teardown planning

#### Medium

Standard phased plan. Same as the existing `generate-infra.md` default stages. Apply the existing data-migration skip rule: if no databases/storage, drop the data-migration stage and note its absence as a driver; Cutover and Validation move up in sequence.

#### Large

Extended infrastructure deployment. Extra time for complex dependency graphs, multi-cluster orchestration, and extended parallel validation.

- **Stage 1: Setup** — same as medium
- **Stage 2: Proof of Concept** — same as medium
- **Stage 3: Infrastructure Deployment** — extended scope: additional clusters and cross-cluster networking
- **Stage 4: Data Migration** — extended for large data volumes and complex replication topologies (skip if no databases/storage)
- **Stage 5: Cutover** — same structure as medium
- **Stage 6: Validation and Cleanup** — extended monitoring before GCP teardown

## Risk Scaling by Tier

Risk probabilities should be adjusted based on complexity tier:

| Risk Category                    | Small       | Medium | Large  |
| -------------------------------- | ----------- | ------ | ------ |
| Incorrect service sizing         | low         | medium | high   |
| Missing dependencies             | low         | medium | high   |
| Data migration complexity        | n/a (no DB) | medium | high   |
| Cost overrun                     | low         | medium | high   |
| Performance regression           | low         | medium | medium |
| Timeline overrun                 | low         | medium | high   |
| Unmapped services block progress | low         | medium | medium |

## Success Criteria Scaling by Tier

Tighter thresholds for simpler migrations (fewer unknowns, less variance).

### Billing-Only Path

| Criteria                    | Small                      | Medium                     | Large                      |
| --------------------------- | -------------------------- | -------------------------- | -------------------------- |
| Performance within baseline | Within 15% of GCP          | Within 20% of GCP          | Within 20% of GCP          |
| Monitoring stability        | 24-hour watch period       | 48-hour watch period       | 48-hour watch period       |
| Post-migration stability    | 14-day observation         | 30-day observation         | 45-day observation         |
| Cost variance               | Within 25% of mid estimate | Within 30% of mid estimate | Within 40% of mid estimate |
| Data integrity              | 100%                       | 100%                       | 100%                       |
| Service availability        | 99%                        | 99%                        | 99%                        |

### Infrastructure Path

| Criteria                    | Small                      | Medium                     | Large                      |
| --------------------------- | -------------------------- | -------------------------- | -------------------------- |
| Performance within baseline | Within 10% of GCP          | Within 10% of GCP          | Within 10% of GCP          |
| Monitoring stability        | 24-hour watch period       | 24-hour watch period       | 48-hour watch period       |
| Post-migration stability    | 14-day observation         | 30-day observation         | 30-day observation         |
| Cost variance               | Within 10% of mid estimate | Within 15% of mid estimate | Within 15% of mid estimate |
| Data integrity              | 100%                       | 100%                       | 100%                       |
| Service availability        | 99.9%                      | 99.9%                      | 99.9%                      |

## Output

After classification, the consuming generate file must include a `complexity_tier` field in its output JSON:

```json
{
  "complexity_tier": "small",
  "complexity_inputs": {
    "service_count": 2,
    "monthly_spend": 75.71,
    "has_databases": false,
    "has_stateful_storage": false,
    "has_ai_workloads": false,
    "availability": "single-az",
    "compliance": "none",
    "multi_region": false
  }
}
```

These fields go at the top level of the generation JSON (alongside `phase`, `generation_source`, etc.).
