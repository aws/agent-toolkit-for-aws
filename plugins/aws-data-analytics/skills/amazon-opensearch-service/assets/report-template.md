<!--
Source-agnostic master template. The Source/Risks blocks below branch on
{{ fingerprint.source_engine }}. For the engine-specific renderings (full
section-by-section structure with the right schema/query columns) see
solr-report-template.md (Solr) and elasticsearch-report-template.md (ES / OS).
Use whichever matches the source; this master is the shared skeleton they share.
-->
# Migration Assessment Report — {{ fingerprint.source_engine }} {{ fingerprint.version | default:'(version unknown)' }} → Amazon OpenSearch

**Date**: {{ date }}  
**Skill**: amazon-opensearch-service v{{ skill_version }}  
**Persona**: {{ persona }}  
**Source**: {{ fingerprint.source_engine | default:'unknown' }} {{ fingerprint.version | default:'(version not provided)' }}  
**Target**: {{ migration_path.decision_inputs.target | default:'managed' }}  
**Recommended migration tool**: {{ migration_path.recommended }}  

---

## Executive Summary

This assessment evaluates a {{ fingerprint.source_engine }} workload for migration to **Amazon OpenSearch {{ migration_path.decision_inputs.target | default:'Service' }}** in **{{ sizing.region | default:'us-east-1' }}**.

### Key findings

- **Migration readiness score**: **{{ readiness.overall_score }}/100** ({{ readiness.tier }})
- **Recommended migration tool**: **{{ migration_path.recommended }}**
- **Sizing**: see Sizing section below; plug values into <https://calculator.aws> for monthly cost
- **Confidence**: see Risks section below

A green tier (≥80) means you SHOULD proceed with the planned migration; yellow tier (60–79) means you SHOULD run a PoC + spike on the lowest-scoring dimension; red tier (<60) means you MUST NOT commit until the risk-blocker findings are reduced because the readiness score is below the safe-migration threshold.

---

## Source

<!-- Template note: rows are conditionally included based on fingerprint data availability -->

| Field | Value |
|---|---|
| Engine | {{ fingerprint.source_engine \| default:'unknown' }} |
| Version | {{ fingerprint.version \| default:'unknown' }} |
| Indexes | {{ fingerprint.summary.index_count }} |
| Total docs | {{ fingerprint.summary.total_docs }} |
| Total GB | {{ fingerprint.summary.total_gb }} |
| Health | {{ fingerprint.summary.health_status }} |
| Plugins | {{ fingerprint.summary.plugin_count }} |
| Nodes | {{ fingerprint.summary.node_count }} |
| Schema fields (Solr) | {{ fingerprint.summary.field_count }} |
| Dynamic fields (Solr) | {{ fingerprint.summary.dynamic_field_count }} |
| Unique key (Solr) | {{ fingerprint.summary.unique_key }} |
| Custom plugin JARs (Solr) | {{ fingerprint.summary.custom_lib_count }} |
| DIH in use | {{ fingerprint.summary.dih_used }} |
| Velocity Response Writer | YES (deprecated/removed in modern Solr; no OpenSearch equivalent) |
| XSLT Response Writer | YES (no OpenSearch equivalent) |
| Auth class | {{ fingerprint.summary.auth_class }} |

### Source artifacts collected

```
{{ fingerprint.files_provided | json }}
```

<details>
<summary>Full fingerprint (click to expand)</summary>

```json
{{ fingerprint | json }}
```

</details>

---

## Target

**Recommended deployment**: {{ migration_path.decision_inputs.target | default:'managed' }}

{% if sizing.compute.data_node_instance %}- Compute: {{ sizing.compute.data_node_count }}× {{ sizing.compute.data_node_instance }}

- Cluster managers: {{ sizing.compute.cluster_manager_count }}× {{ sizing.compute.cluster_manager_instance }}
- Storage: {{ sizing.storage.gb_per_node }} GB per node ({{ sizing.storage.type }})
- Region: {{ sizing.region }}
{% endif %}{% if sizing.compute.indexing_ocu_min %}- Indexing OCUs (minimum): {{ sizing.compute.indexing_ocu_min }}
- Search OCUs (minimum): {{ sizing.compute.search_ocu_min }}
- Redundancy: {{ sizing.compute.redundancy }}
- Storage: {{ sizing.storage.gb }} GB ({{ sizing.storage.type }})
- Region: {{ sizing.region }}
{% endif %}

For target-shape reasoning (managed vs Serverless NextGen) see [`assessment-workflow.md`](../references/assessment-workflow.md). Sizing math: [`sizing.md`](../references/sizing.md).

---

## Migration Path

**Recommended tool**: **{{ migration_path.recommended }}**

### Ranked options

```markdown
| Option | Score | Pros | Cons |
|---|---|---|---|
{% for r in migration_path.ranked_options %}| **{{ r.option }}** | {{ r.score }} | {{ r.pros | bullets }} | {{ r.cons | bullets }} |
{% endfor %}
```

### Decision inputs

```
{{ migration_path.decision_inputs | json }}
```

For full per-component strategy tables (Historical Data Migration / Live Traffic Migration / Application Code Rewrite) and the always-true source-engine rules, see [`assessment-workflow.md`](../references/assessment-workflow.md).

---

## Sizing — for the AWS Pricing Calculator

Region: **{{ sizing.region | default:'us-east-1' }}** · Report date: **{{ date }}**

```json
{{ sizing | json }}
```

### How to compute monthly cost

This skill produces sizing inputs only. You MUST plug them into the **AWS Pricing Calculator** at <https://calculator.aws>: add an estimate, pick **Amazon OpenSearch Service** or **Serverless NextGen**, enter the compute / storage / OCU values from the sizing block, and apply RI / Savings Plan / EDP discounts. You MUST add a separate calculator entry for migration tooling (Migration Assistant for Amazon OpenSearch Service EKS infra, OSI OCUs, S3 snapshot storage) for the one-time cost.

---

## Readiness

**Overall score**: **{{ readiness.overall_score }}/100** — Tier: **{{ readiness.tier }}**

### Per-dimension breakdown

| Dimension | Weight | Raw | Weighted |
|---|---|---|---|
| Compatibility | {{ readiness.breakdown.compatibility.weight }}% | {{ readiness.breakdown.compatibility.raw_score }} | {{ readiness.breakdown.compatibility.weighted_contribution }} |
| Operational readiness | {{ readiness.breakdown.operational_readiness.weight }}% | {{ readiness.breakdown.operational_readiness.raw_score }} | {{ readiness.breakdown.operational_readiness.weighted_contribution }} |
| Sizing fitness | {{ readiness.breakdown.sizing_fitness.weight }}% | {{ readiness.breakdown.sizing_fitness.raw_score }} | {{ readiness.breakdown.sizing_fitness.weighted_contribution }} |
| Data movement complexity | {{ readiness.breakdown.data_movement_complexity.weight }}% | {{ readiness.breakdown.data_movement_complexity.raw_score }} | {{ readiness.breakdown.data_movement_complexity.weighted_contribution }} |
| Cutover complexity | {{ readiness.breakdown.cutover_complexity.weight }}% | {{ readiness.breakdown.cutover_complexity.raw_score }} | {{ readiness.breakdown.cutover_complexity.weighted_contribution }} |
| Sizing-input completeness | {{ readiness.breakdown.cost_confidence.weight }}% | {{ readiness.breakdown.cost_confidence.raw_score }} | {{ readiness.breakdown.cost_confidence.weighted_contribution }} |
| Stakeholder alignment | {{ readiness.breakdown.stakeholder_alignment.weight }}% | {{ readiness.breakdown.stakeholder_alignment.raw_score }} | {{ readiness.breakdown.stakeholder_alignment.weighted_contribution }} |

### Tier guidance

- **GREEN (≥80)**: You MUST proceed and surface top items to flag (split across Migration specifics and Risks/blockers).
- **YELLOW (60–79)**: You MUST run a PoC + spike on the weakest dimension.
- **RED (<60)**: You MUST NOT commit because the readiness score is below the safe-migration threshold. Revisit the weakest dimension first.

---

## Risks & migration specifics

Two-table section. See [`assessment-gotchas.md`](../references/assessment-gotchas.md) for general anti-patterns and [`compatibility-rubric.md`](../references/compatibility-rubric.md) for the canonical Severity + Lane vocabulary.

For the full per-finding register use the engine-specific gap register: [`solr-gap-register.md`](solr-gap-register.md) for Solr sources, [`elasticsearch-gap-register.md`](elasticsearch-gap-register.md) for Elasticsearch / OpenSearch sources.

### Migration specifics

Items the migration plan already handles via a documented remediation. The auto-seeded rows below have a `Workaround` field by definition — every row here is a migration specific. Frame these as *"this is how the migration handles X"*.

```markdown
| ID | Severity | Description | Remediation (handled by the path) |
|---|---|---|---|
{% if fingerprint.source_engine == 'solr' %}{% if fingerprint.summary.dih_used %}| SOLR_DIH | HIGH | Solr Data Import Handler (DIH) was removed in Solr 9.0 | Migrate ETL to OpenSearch Ingestion (OSI), Data Prepper, AWS DMS, or Logstash |
{% endif %}{% if fingerprint.summary.velocity_response_writer %}| SOLR_VELOCITY | HIGH | Velocity Response Writer is deprecated/removed in modern Solr | Move templating into the application layer |
{% endif %}{% if fingerprint.summary.xslt_response_writer %}| SOLR_XSLT | HIGH | XSLT Response Writer has no OpenSearch equivalent | Move templating into the application layer |
{% endif %}{% endif %}{% if fingerprint.source_engine == 'elasticsearch' %}{% if fingerprint.summary.ilm_used %}| ES_ILM | HIGH | ES Index Lifecycle Management (ILM); policy JSON does not import as ISM | Rewrite policies as ISM and re-attach (see source-elasticsearch.md) |
{% endif %}{% if fingerprint.summary.watcher_used %}| ES_WATCHER | HIGH | X-Pack Watcher has no direct equivalent | Rebuild as OpenSearch Alerting monitors |
{% endif %}{% if fingerprint.summary.runtime_fields_used %}| ES_RUNTIME_FIELDS | HIGH | ES runtime (schema-on-read) fields have no OpenSearch equivalent | Pre-compute at ingest or use scripted_field; reindex |
{% endif %}{% if fingerprint.summary.source_disabled %}| ES_SOURCE_FALSE | HIGH | `_source: {enabled:false}` index — Migration Assistant for Amazon OpenSearch Service Historical Data Migration recovers documents (nugget #22) | Use Migration Assistant for Amazon OpenSearch Service Historical Data Migration; re-enable `_source` on target |
{% endif %}{% endif %}| *Add per-finding rows here* | | | |
```

### Risks / blockers

Items that genuinely constrain the migration: no known fix, capacity-plan implications, irreversible target choices, or customer-action dependencies that can fail late. These deduct from the Compatibility readiness weight per [`readiness-rubric.md`](../references/readiness-rubric.md).

```markdown
| ID | Severity | Description | What's at stake |
|---|---|---|---|
{% if fingerprint.source_engine == 'solr' and fingerprint.summary.custom_lib_count %}| SOLR_CUSTOM_PLUGIN | HIGH/BLOCKING | Custom plugin JARs ({{ fingerprint.summary.custom_lib_count }} `<lib>` directives) must port to the OpenSearch plugin API | Not supported on Serverless NextGen — constrains target choice; needs a plugin port plan or RFC |
{% endif %}{% if fingerprint.source_engine == 'elasticsearch' and fingerprint.summary.post_fork %}| ES_POST_FORK | HIGH | Source is ES ≥ 7.11 (ELv2/SSPL) — Snapshot/Restore to AOS is NOT supported (nugget #21) | Tool-choice lockout: must use Migration Assistant for Amazon OpenSearch Service Historical Data Migration (any volume) or `_reindex` from remote; flag legal review |
{% endif %}| *Add per-finding rows here* | | | |
```

### What I assumed (defaults applied for UNKNOWN inputs)

- Pricing: not estimated — the customer plugs sizing into <https://calculator.aws> for an authoritative figure
- Default replicas: 1 (per [`assumptions.md`](../references/assumptions.md))
- Default `refresh_interval`: 30s (not 1s — Skill IP: operational guidance for prod, verify against `bp.html` in [`knowledge-retrieval.md`](../references/assessment-knowledge-retrieval.md))
- Engineering hours estimate: Skill IP, derive from readiness tier
- Defaulted to managed Multi-AZ-with-Standby topology unless Serverless NextGen was clearly indicated
- For Migration Assistant for Amazon OpenSearch Service cost projections, follow the AWS Solutions cost guide cited in [`knowledge-retrieval.md`](../references/assessment-knowledge-retrieval.md) (Migration Assistant for Amazon OpenSearch Service section)

---

## Citations

The single canonical provenance record for this assessment (resolved in the Step 8 batched pass — no inline per-claim citations needed). For the canonical retrieval recipe (every URL the skill ever cites, topic → tool → URL, with browser/CLI fallbacks when the AWS MCP server is not available), see [`knowledge-retrieval.md`](../references/assessment-knowledge-retrieval.md). You MUST list, with retrieval timestamps, the version-volatile claims you actually verified — typically including:

- The specific best-practice page used for the sizing math (Amazon OpenSearch Service (managed) section)
- The AWS upgrade-path doc for any upgrade-path claim (Amazon OpenSearch Service (managed) section)
- The Migration Assistant for Amazon OpenSearch Service doc (AWS) and project doc when Migration Assistant for Amazon OpenSearch Service is the recommendation (Migration Assistant for Amazon OpenSearch Service section)
- The Serverless NextGen comparison and general reference docs for any Serverless NextGen claim (Amazon OpenSearch Serverless NextGen section)
- The AWS Pricing Calculator URL — <https://calculator.aws> — for the cost handoff

---

*Generated by amazon-opensearch-service v{{ skill_version }} on {{ date }}.*
