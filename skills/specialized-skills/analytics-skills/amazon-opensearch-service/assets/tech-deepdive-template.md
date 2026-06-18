# Migration Assessment — Technical Deep Dive

**Date**: {{ date }}  
**Skill**: amazon-opensearch-service v{{ skill_version }}  
**Persona**: {{ persona }}  
**Source**: {{ fingerprint.source_engine | default:'unknown' }} {{ fingerprint.version | default:'(version not provided)' }}  
**Target**: Amazon OpenSearch {{ migration_path.decision_inputs.target | default:'Service' }}

---

## Executive Summary (one-line)

Migrate from {{ fingerprint.source_engine }} {{ fingerprint.version | default:'?' }} to OpenSearch {{ migration_path.decision_inputs.target | default:'Managed' }} via **{{ migration_path.recommended }}**. Readiness score **{{ readiness.overall_score }}/100** ({{ readiness.tier }}); see the Sizing section for compute, storage, and OCU recommendations the customer plugs into <https://calculator.aws>.

---

## Source — full fingerprint

```json
{{ fingerprint | json }}
```

### Notable observations

{% if fingerprint.summary.dih_used %}- **DIH in use** — Solr 9.0 removed DIH. Migrate ingest pipelines to OSI / DMS / Logstash before cutover.{% endif %}
{% if fingerprint.summary.velocity_response_writer %}- **Velocity Response Writer** — deprecated/removed in modern Solr; OpenSearch has no equivalent. Move templating into the application layer.{% endif %}
{% if fingerprint.summary.xslt_response_writer %}- **XSLT Response Writer** — same as Velocity. App-layer templating.{% endif %}

---

## Target — Managed Domain or Serverless NextGen

Recommended: **{{ migration_path.decision_inputs.target | default:'managed' }}**.

### Topology (Managed Domain)

{% if sizing.compute.data_node_instance %}

- Data nodes: {{ sizing.compute.data_node_count }}× {{ sizing.compute.data_node_instance }}
- Cluster managers: {{ sizing.compute.cluster_manager_count }}× {{ sizing.compute.cluster_manager_instance }}
- Storage: {{ sizing.storage.gb_per_node }} GB {{ sizing.storage.type }} per node
- Region: {{ sizing.region }}
{% endif %}

### Sizing rationale + Auth + Tiering

For the formulas, shard rules, JVM thresholds, k-NN engine selection, OCU model, and security details, see [`sizing.md`](../references/sizing.md), [`vector-knn.md`](../references/vector-knn.md), and [`security.md`](../references/security.md). You MUST NOT duplicate those tables here because divergent copies will drift out of sync with the canonical files. You MUST cite them.

---

## Migration Path — full ranking

```json
{{ migration_path | json }}
```

### Step-by-step plan ({{ migration_path.recommended }})

1. **Discovery + assessment** (this report)
2. **PoC**: you MUST stand up a small cluster in target region, restore a sample shard, and validate top-N queries
3. **Schema/query rewrite**: see source-specific reference
4. **Data movement**:
   - For Migration Assistant for Amazon OpenSearch Service: you MUST deploy via CloudFormation (EKS recommended), configure Historical Data Migration for backfill, and configure Capture Proxy if zero-downtime
   - For Snapshot/Restore: you MUST register S3 repo on source and target, snapshot, then restore
   - For OSI: you MUST create the pipeline via blueprint
   - For Reindex from Remote: you MUST pre-create the destination, configure the destination's `reindex.remote.allowlist`, then trigger reindex
5. **Validation**: doc-count parity, top-N query parity (Jaccard ≥95%), p99 latency parity
6. **Cutover**: read-only on source, drain in-flight, flip clients
7. **Decommission**: you MUST schedule source teardown after the rollback window

---

## Sizing — recommendations the customer plugs into the AWS Pricing Calculator

```json
{{ sizing | json }}
```

### How to get a dollar figure

You MUST plug the sizing JSON above into the **AWS Pricing Calculator** at <https://calculator.aws>. You MUST add a separate calculator entry for migration tooling (Migration Assistant for Amazon OpenSearch Service EKS infra, OSI OCUs, S3 snapshot storage) for the one-time cost. RI / Savings Plan / EDP discounts apply only there.

---

## Readiness — full breakdown

```json
{{ readiness | json }}
```

---

## Risks & migration specifics (full register)

Two-table section. Items with a documented remediation that the migration plan already handles go under **Migration specifics** — frame as *"this is how the migration handles X"*, not as risks. Items that genuinely constrain the migration (no fix, capacity implications, target-choice or customer-action dependencies) go under **Risks/blockers**. Within each table: BLOCKING → HIGH → MEDIUM → LOW. See [`compatibility-rubric.md`](../references/compatibility-rubric.md) for the canonical Severity + Lane vocabulary and [`assessment-gotchas.md`](../references/assessment-gotchas.md) for general anti-patterns.

---

## Validation gates before cutover

- [ ] Index counts match between source and target
- [ ] Doc counts within 0.1%
- [ ] Top-N query parity ≥ 95% Jaccard
- [ ] p50/p99 latency within 1.2× of source
- [ ] Shard health green; 0 unassigned
- [ ] ISM policies migrated and attached
- [ ] Role mappings + SAML/OIDC tested
- [ ] Saved objects (dashboards, viz) imported and rendering
- [ ] CloudWatch alarms updated to new metric names
- [ ] CloudWatch Alarm SNS topics encrypted with KMS (`KmsMasterKeyId`); subscribers verified as authorized personnel
- [ ] CloudTrail enabled and logging OpenSearch Service control-plane API calls
- [ ] VPC Flow Logs enabled on the target domain's subnets (if VPC-deployed)
- [ ] Slow log thresholds configured per index
- [ ] Backup snapshot taken before cutover
- [ ] Client libraries upgraded (`opensearch-py` etc.)
- [ ] Cost actuals within 10% of forecast
- [ ] Runbook owner assigned + on-call set
- [ ] Source decommission plan + rollback window documented

---

## Citations

For the canonical retrieval recipe + URL/CLI fallback see [`knowledge-retrieval.md`](../references/assessment-knowledge-retrieval.md). You MUST cite, with retrieval timestamps, the specific `bp-*` page used for sizing math, `version-migration.html` for upgrade-path claims, the Migration Assistant for Amazon OpenSearch Service doc when Migration Assistant for Amazon OpenSearch Service is the recommendation, the relevant Serverless NextGen page when targeting Serverless NextGen, and <https://calculator.aws> for the cost handoff.

---

*Generated by amazon-opensearch-service v{{ skill_version }} on {{ date }}.*
