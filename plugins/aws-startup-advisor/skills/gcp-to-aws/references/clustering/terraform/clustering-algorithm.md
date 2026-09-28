# Terraform Clustering: Deterministic Algorithm

Groups resources into named clusters using priority-ordered rules.

## Input

All resources with fields:

- `address`, `type`, `classification` (PRIMARY/SECONDARY)
- `secondary_role` (if SECONDARY)
- `typed_edges[]`, `depth`, `serves[]`

## Algorithm: Apply Rules in Priority Order

### Rule 1: Networking Cluster

**IF** `google_compute_network` resource exists:

- Group: `google_compute_network` + ALL network_path secondaries (subnetworks, firewalls, routers)
- Cluster ID: `networking_vpc_{gcp_region}_001` (e.g., `networking_vpc_us-central1_001`)
- **Reasoning**: Network is shared infrastructure; groups all config together

**Output**: 1 cluster (or 0 if no networks found)

**Mark these resources as clustered; remove from unassigned pool.**

### Rule 2: Same-Type Grouping (GROUP ALL INTO ONE CLUSTER PER TYPE)

**CRITICAL: Create ONE cluster per resource type, NOT one cluster per resource.**

**Process:**

1. **Identify all resource types with 2+ PRIMARY resources**
   - Example: 4× `google_pubsub_topic`, 3× `google_storage_bucket`, 2× `google_sql_database_instance`

2. **For EACH resource type with 2+ primaries: Create ONE cluster containing ALL of them**
   - Do NOT create separate clusters for each resource
   - Create ONE cluster with ALL matching resources

3. **Cluster ID format**: `{service_category}_{service_type}_{gcp_region}_{sequence:001}`
   - `messaging_pubsubtopic_us-central1_001` (contains ALL 4 pubsub topics)
   - `storage_bucket_us-central1_001` (contains ALL 3 storage buckets)
   - `database_sql_us-central1_001` (contains ALL 2 SQL instances)

4. **Primary resources in cluster**: List ALL matching resources
   - Example cluster `messaging_pubsubtopic_us-central1_001`:
     - primary_resources:
       - `google_pubsub_topic.order_events`
       - `google_pubsub_topic.inventory_events`
       - `google_pubsub_topic.user_events`
       - `google_pubsub_topic.dead_letter`

5. **Secondary resources**: Collect ALL secondaries that `serve` ANY of the grouped primaries
   - All subscriptions for all grouped topics
   - All IAM bindings for all grouped resources
   - All supporting resources

**Correct Examples (ONE cluster per type):**

- 4× `google_pubsub_topic` → 1 cluster: `messaging_pubsubtopic_us-central1_001`
- 3× `google_storage_bucket` → 1 cluster: `storage_bucket_us-central1_001`
- 2× `google_sql_database_instance` → 1 cluster: `database_sql_us-central1_001`
- 3× `google_container_cluster` → 1 cluster: `compute_gke_us-central1_001` (NOT `k8s_001`, `k8s_002`, `k8s_003`)

**INCORRECT Examples (DO NOT DO THIS):**

- ❌ 4× `google_pubsub_topic` → 4 clusters (`compute_pubsubtopic_001`, `compute_pubsubtopic_002`, etc.)
- ❌ 3× `google_storage_bucket` → 3 clusters (`compute_storagebucket_001`, `compute_storagebucket_002`, etc.)
- ❌ 3× `google_container_cluster` → 3 clusters (`k8s_001`, `k8s_002`, `k8s_003`)

**Output**: ONE cluster per resource type (not per resource)

**Reasoning**: Identical workloads of the same GCP service type migrate together, share operational characteristics, and are managed as a unit.

**Mark all resources of this type as clustered; remove from unassigned pool.**

### Rule 3: Seed Clusters

**FOR EACH** remaining PRIMARY resource (unassigned):

- Create cluster seeded by this PRIMARY
- Add all SECONDARY resources in its `serves[]` array
- Cluster ID: `{service_type}_{gcp_region}_{sequence}` (e.g., `cloudrun_us-central1_001`)
- **Reasoning**: Primary + its supports = deployment unit

**Output**: N clusters (one per remaining PRIMARY)

**Mark all included resources as clustered.**

### Rule 4: Merge on Dependencies

**IF** two clusters have **bidirectional** `data_dependency` edges between their PRIMARY resources (A→B AND B→A):

- **THEN** merge clusters

**Action**: Combine into one cluster; update ID to reflect both (e.g., `web-api_us-central1_001`)

**Reasoning**: Bidirectional data dependencies indicate a tightly coupled deployment unit that must migrate together.

**Do NOT merge** when edges are unidirectional (A→B only). Unidirectional dependencies are captured in `dependencies[]` instead.

### Rule 5: Skip API Services

**IF** resource is `google_project_service`:

- Classify as orchestration secondary
- Do NOT create its own cluster
- Attach to cluster of service it enables (e.g., `google_project_service.cloud_run` attaches to Cloud Run cluster)

**Reasoning**: API enablement is prerequisite, not a deployable unit.

### Rule 6: Deterministic Naming

Apply consistent cluster naming:

- **Format**: `{service_category}_{service_type}_{gcp_region}_{sequence}`
- **service_category**: One of: `compute`, `database`, `storage`, `networking`, `messaging`, `monitoring`, `analytics`, `security`
- **service_type**: GCP service shortname (e.g., `cloudrun`, `sql`, `bucket`, `vpc`)
- **gcp_region**: Source region (e.g., `us-central1`)
- **sequence**: Zero-padded counter (e.g., `001`, `002`)

**Examples**:

- `compute_cloudrun_us-central1_001`
- `database_sql_us-west1_001`
- `storage_bucket_multi-region_001`
- `networking_vpc_us-central1_001` (rule 1 network cluster)

**Reasoning**: Names reflect deployment intent; deterministic for reproducibility.

## Post-Clustering: Populate Cluster Metadata

After all clusters are formed, populate these fields for each cluster:

### `network`

Identify which VPC/network the cluster's resources belong to. Trace `network_path` edges from resources in this cluster to find the `google_compute_network` they reference. Store the network cluster ID (e.g., `networking_vpc_us-central1_001`). Set to `null` if resources have no network association.

### `must_migrate_together`

Default: `true` for all clusters. Set to `false` only if the cluster contains resources that can be independently migrated without breaking dependencies (rare — most clusters are atomic).

### `dependencies`

Derive from Primary→Primary edges that cross cluster boundaries. If cluster A contains a resource with a `data_dependency` edge to a resource in cluster B, then cluster A depends on cluster B. Store as array of cluster IDs.

### `creation_order`

Build a global ordering of clusters by depth level:

```json
"creation_order": [
  { "depth": 0, "clusters": ["networking_vpc_us-central1_001"] },
  { "depth": 1, "clusters": ["security_iam_us-central1_001"] },
  { "depth": 2, "clusters": ["database_sql_us-central1_001", "storage_gcs_us-central1_001"] },
  { "depth": 3, "clusters": ["compute_cloudrun_us-central1_001"] }
]
```

Cluster depth = minimum depth across all primary resources in the cluster. Clusters at the same depth can be migrated in parallel.

## Output Cluster Schema

Each cluster includes:

```json
{
  "cluster_id": "compute_cloudrun_us-central1_001",
  "gcp_region": "us-central1",
  "primary_resources": ["google_cloud_run_service.app"],
  "secondary_resources": ["google_service_account.app_runner"],
  "network": "networking_vpc_us-central1_001",
  "creation_order_depth": 2,
  "must_migrate_together": true,
  "dependencies": ["database_sql_us-central1_001"],
  "edges": [
    {
      "from": "google_cloud_run_service.app",
      "to": "google_sql_database_instance.db",
      "relationship_type": "data_dependency",
      "evidence": {
        "field_path": "template.spec.containers[0].env[].value",
        "reference": "DATABASE_URL"
      }
    }
  ]
}
```

## Determinism Guarantee

Given the same classified resource inputs, the clustering algorithm produces the same cluster structure every run:

1. Rules applied in fixed order
2. Sequence counters increment deterministically
3. Naming reflects source state, not random IDs
4. All clustering heuristics are deterministic (no LLM-based decisions within the clustering algorithm itself)

**Note:** Resource classification (see `classification-rules.md`) may use LLM inference as a fallback for resource types not in the hardcoded tables. If LLM-classified resources enter the pipeline, overall reproducibility depends on the LLM producing consistent classifications.
