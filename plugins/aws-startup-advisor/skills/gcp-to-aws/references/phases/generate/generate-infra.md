# Generate Phase: Infrastructure Migration Plan

> Loaded by generate.md when estimation-infra.json exists.

**Execute ALL steps in order. Do not skip or optimize.**

## Prerequisites

Read the following artifacts from `$MIGRATION_DIR/`:

- `aws-design.json` (REQUIRED) — AWS architecture design from Phase 3
- `estimation-infra.json` (REQUIRED) — Cost estimates from Phase 4
- `gcp-resource-clusters.json` (REQUIRED) — Cluster dependency graph from Phase 1
- `preferences.json` (REQUIRED) — User migration preferences from Phase 2

If any required file is missing: **STOP**. Output: "Missing required artifact: [filename]. Complete the prior phase that produces it."

## Part 1: Migration Timeline

> **Before building the timeline, load `references/shared/migration-complexity.md` and classify the migration tier using inputs from `aws-design.json`, `gcp-resource-clusters.json`, `estimation-infra.json`, and `preferences.json`.**

Build a timeline using the **Infrastructure Path** ranges for the determined tier. Also consider:

- **Cluster count** from `gcp-resource-clusters.json` — more clusters = longer infrastructure phase
- **Dependency depth** from `creation_order` — deeper graphs need more sequential work
- **Service complexity** from `aws-design.json` — databases and stateful services take longer
- **Cutover strategy** from `preferences.json` — maintenance window vs. blue-green affects timeline

### Small Tier

Compressed setup. PoC is a 2-day smoke test integrated into deployment. No data migration stage (small tier excludes databases by definition).

#### Stage 1: Setup

- Provision VPC, subnets, routing, IAM, monitoring baseline
- Set up CI/CD pipeline for Terraform deployments

#### Stage 2: Deploy + Smoke Test

- Deploy all clusters (few services, shallow dependency graph)
- Validate application connectivity and performance
- Run integration tests
- Confirm cost tracking matches `estimation-infra.json` projections
- **Go/No-Go checkpoint**: If smoke test fails acceptance criteria, stop and reassess

#### Stage 3: Cutover

- Execute cutover per `preferences.json` cutover_strategy
- Monitor for 24-48 hours post-cutover
- Keep GCP resources running as hot standby

#### Stage 4: Validation + Cleanup

- Monitor AWS performance for 1 week
- Compare actual costs against projections
- Begin GCP teardown planning (execute teardown after 2-week stability period)

### Medium Tier

Standard phased plan. Apply the data-migration skip rule below.

#### Stage 1: Setup

- Finalize AWS account structure and billing alerts
- Provision foundational infrastructure: VPC, subnets, routing, NAT gateways
- Configure IAM roles and policies per cluster requirements
- Establish GCP-to-AWS connectivity (VPN or Direct Connect for data migration)
- Set up CI/CD pipeline for Terraform deployments
- Configure monitoring baseline (CloudWatch, alarms)

#### Stage 2: Proof of Concept

- Deploy the **shallowest-depth cluster** (lowest `creation_order_depth`) to AWS
- Validate application connectivity and performance
- Test data pipeline from GCP to AWS (database replication, storage sync)
- Measure baseline latency and throughput
- Confirm cost tracking matches `estimation-infra.json` projections
- **Go/No-Go checkpoint**: If PoC fails acceptance criteria, stop and reassess

#### Stage 3: Infrastructure Deployment

- Deploy remaining clusters in `creation_order` sequence (depth-first)
- For each cluster:
  - Deploy infrastructure per `aws-design.json` resource mappings
  - Configure cross-cluster networking and security groups
  - Validate service health checks
  - Run integration tests
- Implement monitoring and logging per cluster
- Establish backup and restore procedures

#### Stage 4: Data Migration

**Include this phase ONLY if `aws-design.json` contains database or storage resources
(see resource detection rules in generate-artifacts-scripts.md Step 1).**
**If no data migration is needed, drop that stage: Cutover
and Validation move up in sequence. Note the dropped stage as a duration driver.**

- **Databases**: Set up continuous replication (Cloud SQL to RDS/Aurora)
  - Initial full snapshot transfer
  - Enable ongoing replication (DMS or native replication)
  - Validate data integrity (row counts, checksums)
- **Object storage**: Sync GCS buckets to S3
  - Use AWS DataSync or `gsutil`/`aws s3 sync` for bulk transfer
  - Enable ongoing sync for new objects
- **Secrets**: Migrate secrets from Secret Manager to AWS Secrets Manager
- Establish dual-write pattern for production data

#### Stage 5: Cutover

- Pre-cutover validation:
  - All clusters deployed and healthy on AWS
  - Data replication lag < 1 second
  - All integration tests passing
  - Rollback procedures tested
- Execute cutover per `preferences.json` cutover_strategy:
  - **maintenance-window**: Schedule downtime, switch DNS, validate
  - **blue-green**: Gradual traffic shift (10% → 50% → 100%)
- Monitor for 24-48 hours post-cutover
- Keep GCP resources running as hot standby

#### Stage 6: Validation and Cleanup

- Monitor AWS performance for 1 full week
- Compare actual costs against `estimation-infra.json` projections
- Run final data integrity checks
- Document any drift or issues
- Begin GCP teardown planning (execute teardown after 2-week stability period)

### Large Tier

Extended timeline for complex migrations. Extra time for multi-cluster orchestration, large data volumes, and extended validation. Apply the data-migration skip rule from Stage 4.

#### Stage 1: Setup

Same as Medium.

#### Stage 2: Proof of Concept

Same as Medium.

#### Stage 3: Infrastructure Deployment

Extended scope: additional clusters and complex cross-cluster networking.

- Deploy remaining clusters in `creation_order` sequence (depth-first)
- For each cluster:
  - Deploy infrastructure per `aws-design.json` resource mappings
  - Configure cross-cluster networking and security groups
  - Validate service health checks
  - Run integration tests
- Implement monitoring and logging per cluster
- Establish backup and restore procedures

#### Stage 4: Data Migration

**Include this phase ONLY if `aws-design.json` contains database or storage resources.**
**If no data migration is needed, drop that stage: Cutover
and Validation move up in sequence. Note the dropped stage as a duration driver.**

Extended for large data volumes and complex replication topologies.

- **Databases**: Set up continuous replication (Cloud SQL to RDS/Aurora)
  - Initial full snapshot transfer
  - Enable ongoing replication (DMS or native replication)
  - Validate data integrity (row counts, checksums)
- **Object storage**: Sync GCS buckets to S3
  - Use AWS DataSync or `gsutil`/`aws s3 sync` for bulk transfer
  - Enable ongoing sync for new objects
- **Secrets**: Migrate secrets from Secret Manager to AWS Secrets Manager
- Establish dual-write pattern for production data

#### Stage 5: Cutover

Same structure as Medium.

#### Stage 6: Validation and Cleanup

Extended monitoring before GCP teardown.

- Monitor AWS performance for 2 full weeks
- Compare actual costs against `estimation-infra.json` projections
- Run final data integrity checks
- Document any drift or issues
- Begin GCP teardown planning (execute teardown after 2-week stability period)

## Part 2: Risk Assessment

Build a risk matrix from the discovered infrastructure and migration complexity.

### Risk Categories

For each risk, assess:

- **Probability**: `"high"` (>60%), `"medium"` (30-60%), `"low"` (<30%)
- **Impact**: `"critical"` (service outage), `"high"` (degraded service), `"medium"` (delayed timeline), `"low"` (minor inconvenience)
- **Mitigation**: Specific action to reduce probability or impact

### Standard Risks

| Risk                             | Probability | Impact   | Mitigation                                                                                      |
| -------------------------------- | ----------- | -------- | ----------------------------------------------------------------------------------------------- |
| Data loss during migration       | low         | critical | Dual-write for 2 weeks before cutover; full backup before migration; checksums on all transfers |
| Performance regression on AWS    | medium      | high     | PoC testing before deployment; load testing before cutover; performance baseline comparison     |
| Extended downtime during cutover | medium      | high     | Practice cutover in staging; automate DNS switch; rollback procedure on standby                 |
| Cost overrun vs estimates        | medium      | medium   | Set billing alerts at 80% and 100% of projected; weekly cost review                             |
| Cross-region latency             | low         | medium   | Validate latency in PoC phase; consider same-region deployment for latency-sensitive services   |
| Terraform state corruption       | low         | high     | Remote state with locking (S3 + DynamoDB); state backups before each apply                      |

### Dynamic Risks

Add additional risks based on discovered infrastructure:

- If **databases with replication** exist: Add "Replication lag during cutover" (medium/high)
- If **stateful services** (Redis, Elasticsearch): Add "State migration data loss" (low/critical)
- If **multiple regions** in GCP: Add "Cross-region dependency during migration" (medium/medium)
- If **AI workloads** coexist: Add "Model performance drift on Bedrock" (medium/high)
- If **BigQuery** resources exist (`google_bigquery_*` or `aws_service` is **`Deferred — specialist engagement`** in `aws-design.json`): Add risk **"BigQuery AWS target not yet selected"** (severity **medium**, not high) with mitigation: "Engage **AWS account team** and/or **data analytics migration partner** to evaluate the best analytics migration path; does **not** block phased migration of compute, database, and AI. Plugin does not prescribe Athena/Redshift/Glue."

## Part 3: Success Metrics

### Per-Service Metrics

For each service in `aws-design.json`, define:

| Metric       | Target                                           | Measurement                     |
| ------------ | ------------------------------------------------ | ------------------------------- |
| Availability | 99.9% uptime                                     | CloudWatch synthetic monitoring |
| Latency      | Within 10% of GCP baseline                       | P50, P95, P99 response times    |
| Error rate   | < 0.1%                                           | CloudWatch error metrics        |
| Cost         | Within 15% of `estimation-infra.json` projection | AWS Cost Explorer weekly        |

### Overall Migration Metrics

| Metric             | Target                                                                      |
| ------------------ | --------------------------------------------------------------------------- |
| Data integrity     | 100% — zero data loss confirmed by checksums                                |
| Migration sequence | Stages complete in planned order; no stage entered before its go/no-go gate |
| Rollback success   | Tested and confirmed < 1 hour RTO                                           |
| Team confidence    | Go/No-Go passed at each phase gate                                          |

## Part 4: Rollback Procedures

### Trigger Conditions

Initiate rollback if ANY of:

- Data integrity issues detected during validation (checksum mismatch)
- Performance regression > 20% vs GCP baseline (P95 latency)
- Error rate > 1% sustained for 15 minutes
- Cost overrun > 50% vs `estimation-infra.json` projections
- Critical AWS service limitation discovered that blocks functionality

### Per-Phase Rollback

| Phase                | Rollback Action                                    | RTO          |
| -------------------- | -------------------------------------------------- | ------------ |
| Setup (1-2)          | Delete AWS resources; no impact                    | < 1 hour     |
| PoC (3-4)            | Tear down PoC cluster; GCP unaffected              | < 1 hour     |
| Infrastructure (5-7) | Tear down AWS clusters; GCP still primary          | < 2 hours    |
| Data Migration (8-9) | Stop replication; GCP data is authoritative        | < 30 minutes |
| Cutover (10-11)      | Reverse DNS to GCP; resume GCP traffic             | < 1 hour     |
| Post-Cutover (12+)   | Manual restore from backup; GCP resources archived | 2-4 hours    |

### Rollback Procedure (Pre-DNS Cutover)

1. Pause dual-write replication
2. Reverse DNS records (AWS to GCP endpoints)
3. Verify GCP services receiving traffic
4. Shut down AWS workloads (keep for 1 week as standby)
5. Monitor GCP for 24 hours
6. Post-mortem: document what triggered rollback

### Rollback Procedure (Post-DNS Cutover)

1. If within 48 hours: Reverse DNS, resume GCP from replicated state
2. If beyond 48 hours: Restore GCP from backup (2-4 hour RTO)
3. Validate data integrity after restore
4. Resume GCP operations
5. Post-mortem and reassess migration approach

## Part 5: Team and Roles

### RACI Matrix

| Activity               | Migration Lead | Infrastructure Engineer | Database Engineer | Application Developer | QA Engineer |
| ---------------------- | -------------- | ----------------------- | ----------------- | --------------------- | ----------- |
| Migration planning     | A/R            | C                       | C                 | C                     | I           |
| AWS account setup      | A              | R                       | I                 | I                     | I           |
| Network infrastructure | A              | R                       | I                 | I                     | I           |
| Database migration     | A              | C                       | R                 | I                     | C           |
| Application deployment | A              | C                       | I                 | R                     | C           |
| Data validation        | A              | I                       | R                 | C                     | R           |
| Performance testing    | A              | C                       | C                 | C                     | R           |
| Cutover execution      | R              | R                       | R                 | C                     | C           |
| Rollback execution     | R              | R                       | R                 | I                     | I           |

**R** = Responsible, **A** = Accountable, **C** = Consulted, **I** = Informed

## Part 6: Go/No-Go Framework

Each phase gate requires explicit approval before proceeding.

### Phase Gate Criteria

| Gate | Phase Transition             | Go Criteria                                                     | No-Go Action              |
| ---- | ---------------------------- | --------------------------------------------------------------- | ------------------------- |
| G1   | Setup → PoC                  | VPC online, IAM configured, connectivity verified               | Fix infrastructure issues |
| G2   | PoC → Full Deploy            | PoC cluster healthy, latency acceptable, costs tracking         | Reassess architecture     |
| G3   | Full Deploy → Data Migration | All clusters deployed, integration tests passing                | Debug failing clusters    |
| G4   | Data Migration → Cutover     | Replication lag < 1s, data integrity confirmed, rollback tested | Fix replication issues    |
| G5   | Cutover → Validation         | DNS switched, traffic flowing, error rate < 0.1%                | Execute rollback          |
| G6   | Validation → Cleanup         | 1 week stable operation, costs within 15% of estimate           | Extend monitoring period  |

## Part 7: Post-Migration Monitoring

### 30-Day Post-Migration Plan

**Week 1 (Days 1-7)**: Intensive monitoring

- Check all CloudWatch dashboards every 4 hours
- Compare latency/throughput to GCP baseline daily
- Review AWS costs daily vs projections
- Maintain GCP hot standby

**Days 8-14**: Stabilization

- Reduce monitoring frequency to twice daily
- Begin decommissioning GCP hot standby (read-only mode)
- Address any performance tuning items
- Validate backup/restore procedures on AWS

**Days 15-30**: Optimization

- Implement cost optimization opportunities from `estimation-infra.json`
- Right-size instances based on actual usage data
- Enable Reserved Instances or Savings Plans for stable workloads
- Archive GCP resources and begin teardown
- Final cost reconciliation: actual vs projected

## Part 8: Decision Tree

### Cutover Decision Flowchart

```
START: All clusters deployed?
  NO → Continue infrastructure deployment
  YES → Data replication active?
    NO → Start data migration
    YES → Replication lag < 1 second?
      NO → Wait for replication to catch up
      YES → All integration tests passing?
        NO → Fix failing tests
        YES → Rollback procedure tested?
          NO → Execute rollback drill
          YES → READY FOR CUTOVER
            → Execute cutover per strategy
            → Monitor 24-48 hours
            → Error rate < 0.1%?
              NO → EXECUTE ROLLBACK
              YES → CUTOVER SUCCESSFUL
                → Begin 30-day monitoring
                → Plan GCP teardown (after the 30-day observation window)
```

## Part 9: Output Format

Do NOT write engineering-hour estimates anywhere in this artifact — the plugin
has no calibrated effort data, and hour figures get pasted into budgets (see
`shared/migration-complexity.md` § Provenance). Time is expressed as the
ordered stage sequence plus `duration_drivers[]` (from the tier's driver table,
adapted to this stack, binding driver first) and `tier_bound_by` (the input
that bound the tier). Do not count deferred/N/A services as drivers of
implementation work, and do not restate AI-track drivers already named by
`generation-ai.json`.

Generate `generation-infra.json` in `$MIGRATION_DIR/` with the following schema:

```json
{
  "phase": "generate",
  "generation_source": "infrastructure",
  "complexity_tier": "medium",
  "complexity_inputs": {
    "service_count": 5,
    "monthly_spend": 3500.00,
    "has_databases": true,
    "has_stateful_storage": false,
    "has_ai_workloads": false,
    "availability": "single-az",
    "compliance": "none",
    "multi_region": false
  },
  "timestamp": "2026-02-26T14:30:00Z",
  "migration_plan": {
    "duration_drivers": [
      "Cluster-by-cluster deployment in dependency order (binding: has_databases)",
      "Data migration with parallel-run validation"
    ],
    "tier_bound_by": "has_databases",
    "phases": [
      {
        "name": "Setup",
        "sequence": 1,
        "clusters_targeted": [],
        "key_activities": ["AWS account setup", "VPC provisioning", "IAM configuration"],
        "dependencies": [],
        "go_no_go_criteria": "VPC online, IAM configured, connectivity verified"
      }
    ],
    "services": [
      {
        "gcp_service": "Cloud Run",
        "aws_service": "Fargate",
        "cluster_id": "compute_cloudrun_us-central1_001",
        "data_migration_required": false, // derive from resource detection flags (has_databases, has_storage)
        "human_expertise_required": false // propagate from aws-design.json; true for BigQuery mappings
      }
    ],
    "critical_path": [
      "VPC setup",
      "PoC deployment",
      "Database replication",
      "DNS cutover"
    ],
    "dependencies": [
      {
        "from_cluster": "networking_vpc_us-central1_001",
        "to_cluster": "compute_cloudrun_us-central1_001",
        "type": "must_precede"
      }
    ]
  },
  "risks": [
    {
      "category": "data_loss",
      "probability": "low",
      "impact": "critical",
      "mitigation": "Dual-write for 2 weeks; full backup before cutover; checksum validation",
      "phase_affected": "Data Migration"
    }
  ],
  "success_metrics": {
    "per_service": [
      {
        "service": "Fargate",
        "availability_target": "99.9%",
        "latency_target": "within 10% of GCP baseline",
        "cost_target": "within 15% of estimation"
      }
    ],
    "overall": {
      "data_integrity": "100%",
      "sequence_adherence": "stages in planned order, gated",
      "rollback_rto": "< 1 hour"
    }
  },
  "rollback_procedures": {
    "trigger_conditions": [
      "Data integrity failure",
      "Performance regression > 20%",
      "Error rate > 1% sustained 15 min",
      "Cost overrun > 50%"
    ],
    "pre_cutover_rto": "< 1 hour",
    "post_cutover_rto": "2-4 hours",
    "rollback_window": "Reversible until 48 hours post-DNS cutover"
  },
  "go_no_go_criteria": [
    {
      "gate": "G1",
      "transition": "Setup to PoC",
      "criteria": "VPC online, IAM configured, connectivity verified"
    }
  ],
  "post_migration": {
    "monitoring_duration_days": 30,
    "gcp_teardown": "after the 30-day observation window"
  },
  "recommendation": {
    "approach": "Phased cluster-by-cluster migration",
    "confidence": "high",
    "key_risks": ["Data migration complexity", "Performance validation"]
  }
}
```

## Output Validation Checklist

- `phase` is `"generate"`
- `generation_source` is `"infrastructure"`
- `complexity_tier` is one of `"small"`, `"medium"`, `"large"`
- `complexity_inputs` object is present with all required fields (service_count, monthly_spend, has_databases, has_stateful_storage, has_ai_workloads, availability, compliance, multi_region)
- `migration_plan.duration_drivers` is a non-empty string array consistent with the tier's driver table; `migration_plan.tier_bound_by` names the binding classification input; **no `total_weeks` or hour fields anywhere in the artifact**
- `migration_plan.phases` array has at least 4 entries; stage names match the tier template from Part 1
- `migration_plan.services` covers every service from `aws-design.json`
- `migration_plan.critical_path` is non-empty
- `migration_plan.dependencies` reflect `gcp-resource-clusters.json` creation_order
- `risks` array has at least 3 entries with probability, impact, mitigation
- `success_metrics` has both `per_service` and `overall` sections
- `rollback_procedures` has trigger conditions and RTO values
- `go_no_go_criteria` has at least 2 gates (small) or 4 gates (medium/large)
- `post_migration` specifies monitoring duration and teardown timing
- `recommendation` contains no effort-hour fields; duration is communicated only via stage sequence + `duration_drivers`
- All cluster IDs reference valid clusters from `gcp-resource-clusters.json`
- Output is valid JSON

## Completion Handoff Gate (Fail Closed)

Before returning control to `generate.md`, require:

- `generation-infra.json` exists and passes the Output Validation Checklist above.

If this gate fails: STOP and output: "generate-infra did not produce a valid `generation-infra.json`; do not continue Generate Stage 2."

## Generate Phase Integration

The parent orchestrator (`generate.md`) uses `generation-infra.json` to:

1. Gate Stage 2 artifact generation — `generate-artifacts-infra.md` requires this file
2. Provide timeline context to `generate-artifacts-docs.md` for MIGRATION_GUIDE.md
3. Set phase completion status in `.phase-status.json`
