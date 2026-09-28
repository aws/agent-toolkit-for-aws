# Discover Phase: IaC (Terraform) Discovery

> Self-contained IaC discovery sub-file. Scans for IaC files, extracts Terraform resources, classifies, builds dependency graphs, clusters, and generates output files.
> If no IaC files are found, exits cleanly with no output.

**Execute ALL steps in order. Do not skip or optimize.**

## Step 0: Self-Scan for IaC Files

Recursively scan the entire target directory tree for infrastructure files:

**Terraform:**

- `**/*.tf`, `**/*.tf.json` — resource definitions
- `**/*.tfvars`, `**/*.auto.tfvars` — variable values
- `**/*.tfstate` — state files (read-only, if present)
- `**/.terraform.lock.hcl` — lock files
- `**/modules/*/` — module directories and nested modules

**Contextual files** (recorded but not processed — useful for future discovery phases):

- **Kubernetes:** `**/k8s/*.yaml`, `**/kubernetes/*.yaml`, `**/manifests/*.yaml`
- **Docker:** `**/Dockerfile`, `**/docker-compose*.yml`
- **CI/CD:** `**/cloudbuild.yaml`, `**/.github/workflows/*.yml`, `**/.gitlab-ci.yml`, `**/Jenkinsfile`

Record file paths and types for all files found.

**Exit gate:** If NO Terraform files (`.tf`, `.tfvars`, `.tfstate`, `.terraform.lock.hcl`) are found, **exit cleanly**. Return no output artifacts. Other sub-discovery files may still produce artifacts.

**Secret hygiene (HARD — no exceptions):** `.tfstate` and `.tfvars` files may contain database passwords, API keys, TLS private keys, and certificate material in plaintext.

When `.tfstate` or `.tfvars` files are found:

1. **Warn the user immediately:** "Found [N] Terraform state/variable file(s). These may contain secrets. They will be read for resource discovery only — raw values will NOT be copied into any migration artifact."
2. **Redact sensitive attributes** before writing to `gcp-resource-inventory.json`. For any `config` field whose key matches a sensitive pattern (password, secret, key, token, credential, private_key, client_secret, access_key, api_key), replace the value with `"[REDACTED]"`.
3. **Never write raw secret values** into `gcp-resource-inventory.json`, `gcp-resource-clusters.json`, or any other output artifact.

Sensitive key patterns to redact (case-insensitive): `password`, `passwd`, `secret`, `api_key`, `apikey`, `access_key`, `private_key`, `client_secret`, `token`, `credential`, `auth`.

## Step 1: Extract Resources from Terraform

1. Read all `.tf`, `.tfvars`, and `.tfstate` files in working directory (recursively)
2. Extract all resources matching `google_*` pattern (e.g., `google_compute_instance`, `google_sql_database_instance`)
3. For each resource, capture exactly:
   - `address` (e.g., `google_compute_instance.web`)
   - `type` (e.g., `google_compute_instance`)
   - `name` (resource name component, e.g., `web`)
   - `config` (object with key attributes: `machine_type`, `name`, `region`, etc.)
     - **For `google_app_engine_standard_app_version` / `google_app_engine_flexible_app_version`**, the App Engine → Elastic Beanstalk mapping reads these attributes — capture them into `config` when present: `service`, `version_id`, `runtime`, `instance_class`, `serving_status`, `project`, the scaling block that is present (`automatic_scaling` / `basic_scaling` / `manual_scaling`), `env_variables`, and (Flexible only) `resources` and `flexible_runtime_settings`.
   - `raw_hcl` (raw HCL text for this resource, needed for Step 4)
   - `depends_on` (array of addresses this resource depends on)

   **Cloud SQL normalization (`google_sql_database_instance`)** — Clarify auto-resolves Q6/Q12/Q13/Q13b from these fields, so write them with canonical names at the top level of `config`:
   - `config.disk_size_gb` — from Terraform `settings.disk_size` (attribute name in HCL is `disk_size`; normalize to `disk_size_gb`). Omit when not set in Terraform — do not guess.
   - `config.disk_autoresize` — from Terraform `settings.disk_autoresize`, ONLY when the attribute is explicitly present in HCL. Omit when absent — do not write the provider default (`true`); absence is not an authored choice.
   - `config.availability_type` — from Terraform `settings.availability_type` (`ZONAL` or `REGIONAL`). Omit when not set.
   - `config.tier` — from Terraform `settings.tier` (e.g. `db-f1-micro`).
   - `config.database_version` — from Terraform `database_version` (e.g. `POSTGRES_15`).

   **Cloud Run normalization (`google_cloud_run_v2_service` / `google_cloud_run_service`)** — the discover-preview.md authored-size gate compares a single `min_instance_count`, but v1 and v2 express it differently. Write the canonical field at the top level of `config` regardless of which form is present:
   - `config.min_instance_count` — from the v2 service-level `scaling.min_instance_count` OR the v2 revision-level `template.scaling.min_instance_count` (a v2 service can set the minimum on either; read whichever is present), OR from whichever v1 annotation is present: `template.metadata.annotations["autoscaling.knative.dev/minScale"]` or `metadata.annotations["run.googleapis.com/minScale"]` (parse the annotation's string value to an integer). Omit when none of these are set — do not guess.

   **GKE node pool normalization (`google_container_cluster` / `google_container_node_pool`)** — a pool sizes itself via a fixed count OR one of two mutually exclusive autoscaling forms. Capture whichever is present into `config` under its own name (do not collapse them into one field — the preview gate compares all of them). Node pools can be declared **standalone** (a separate `google_container_node_pool` resource) **or inline** inside `google_container_cluster` as one or more `node_pool { ... }` blocks (and the cluster's own default-pool `node_config` / `initial_node_count`). Inline `node_pool` blocks are **not** separate resources, so traverse every inline block and capture its sizing fields too — a 20-node inline pool must be gated exactly like a standalone one:
   - `config.node_count` / `config.initial_node_count` — from the matching Terraform attribute (top-level on a standalone pool, or inside each inline `node_pool` block), when present.
   - `config.min_node_count` / `config.max_node_count` — from `autoscaling.min_node_count` / `autoscaling.max_node_count` (per-zone form), when present.
   - `config.total_min_node_count` / `config.total_max_node_count` — from `autoscaling.total_min_node_count` / `autoscaling.total_max_node_count` (cluster-wide form), when present.
   - `config.machine_type` — from `node_config.machine_type` (standalone pool, inline `node_pool.node_config`, or the cluster default-pool `node_config`), when present.
   - `config.node_locations` — the effective per-pool zone list (`node_locations` on the pool, else the cluster's `node_locations`); capture the **count** of zones so the preview gate can convert per-zone counts to totals. Omit when not authored.
   - For a cluster with inline `node_pool` blocks, record **one sizing entry per inline pool** (keyed by the pool's `name`) rather than a single cluster-level number, so no authored-large pool is lost.

4. Also extract provider and backend configuration (for region detection)
5. Report total resources found to user (e.g., "Parsed 50 GCP resources from 12 Terraform files")

## Step 2: Flag AI Signals

Scan all `.tf` files for AI-relevant patterns. For each match, record the pattern, file location, and confidence score.

| Pattern             | What to look for                                                                                                                                                     | Confidence |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Vertex AI resources | `google_vertex_ai_*` resource types (`_model`, `_endpoint`, `_training_pipeline`, `_custom_job`, `_index`, `_featurestore`, `_tensorboard`, `_batch_prediction_job`) | 95%        |
| BigQuery ML         | `google_bigquery_ml_*` resource types                                                                                                                                | 85%        |
| Cloud AI Services   | `google_cloud_document_ai_*`, `google_cloud_vision_*`, `google_cloud_speech_*`, `google_cloud_translation_*`, `google_cloud_dialogflow_*`                            | 80%        |
| AI module usage     | Module names containing `*ai*`, `*ml*`, `*model*`, `*prediction*`; variable values referencing `vertex-ai`, `bigquery-ml`                                            | 70%        |
| Variable references | Variable/local names matching `*vertex*`, `*prediction*`, `*model*`, `*ml*`; values containing `vertex-ai`, `bigquery`, `gemini`, `palm`                             | 60%        |

Record all signals for the `ai_detection` section in `gcp-resource-inventory.json`. If any signal has confidence >= 70%, set `has_ai_workload: true`.

**Note:** This step only detects signals from Terraform. Full AI workload profiling (code analysis, billing data) is handled by `discover-app-code.md`.

## Step 2.5: Complexity Assessment

Count the unique GCP resource types extracted in Step 1 that are PRIMARY candidates
(compute, database, storage, messaging services — not IAM, firewall rules, or project services).
Use the Priority 1 list from classification-rules.md as reference:

**Primary types:** google_cloud_run_v2_service, google_cloud_run_service, google_cloudfunctions_function,
google_cloudfunctions2_function, google_compute_instance, google_container_cluster,
google_app_engine_application, google_sql_database_instance, google_spanner_instance,
google_firestore_database, google_bigtable_instance, google_bigquery_dataset,
google_redis_instance, google_storage_bucket, google_filestore_instance,
google_pubsub_topic, google_cloud_tasks_queue

Count resources matching these types. This is the **primary resource count**.

- **If primary resource count ≤ 8:** Use **simplified discovery** (Step 3S below). Skip Steps 3-6.
- **If primary resource count > 8:** Use **full discovery** (Steps 3-6, unchanged).

## Step 2.6: Graviton (ARM64) Signal Scan

From IaC alone, architecture compatibility can only be inferred coarsely. **Load** `references/shared/schema-graviton.md` for the IaC signal table and `graviton_profile` schema.

For each compute resource extracted in Step 1 (`google_compute_instance`, `google_cloud_run_service`/`_v2_`, `google_container_cluster`, `google_app_engine_application`), emit a coarse `graviton_profile` entry with `source: "iac"`:

- Default `tier: "conditional"` and record the GCP `machine_type` (or Cloud Run CPU) as a `signal` — Design maps it to the Graviton equivalent via the table in `graviton.md`.
- If a Windows AMI data source or a `.csproj` targeting `net48` is present → `tier: "incompatible"`, caveat `"Windows/.NET Framework — not supported on Graviton"`.
- If architecture cannot be inferred at all → `tier: "unknown"` (Clarify will ask Q11b).

If `discover-app-code.md` already emitted a `graviton_profile` for the same service (`source: "app_code"`, higher fidelity), do **not** overwrite it — app-code signals win. IaC profiles fill gaps only.

## Step 3S: Simplified Discovery (≤ 8 primary resources)

For small projects, skip the full clustering pipeline. Instead:

0. **Exclude Priority 0 resources** before classification. Remove any resources matching the
   Excluded Resources list in `classification-rules.md` (Priority 0). These include:
   - `google_identity_platform_*` — Auth provider (keep existing, do not migrate)
   - `google_firebase_auth_*` — Auth provider (keep existing, do not migrate)
     Log each excluded resource: "Auth provider detected — excluded from migration scope. Keep your existing auth solution."
     Do NOT include excluded resources in `gcp-resource-inventory.json` or any cluster.

1. **Classify resources** using only Priority 1 hardcoded rules from the PRIMARY types list above.
   - Resources matching the list → PRIMARY
   - All other resources → SECONDARY with role inferred from type:
     - `google_service_account*`, `google_project_iam*` → role: identity
     - `google_compute_firewall`, `google_compute_network`, `google_compute_subnetwork`,
       `google_compute_global_address`, `google_compute_router*`, `google_dns*` → role: network_path
     - `google_secret_manager*`, `google_kms*` → role: encryption
     - `google_project_service` → role: configuration
     - Everything else → role: configuration
   - Set `confidence: 0.99` for all

2. **Build simple dependency edges:**
   - For each SECONDARY resource, find which PRIMARY resource it serves by checking
     Terraform reference expressions (e.g., `google_cloud_run_v2_service.X.name` referenced
     in a service account → that SA serves that Cloud Run service)
   - Edge type: `serves` for all edges (skip typed-edge classification)
   - If no reference found, attach to the nearest PRIMARY resource by file proximity

3. **Create clusters** using simple grouping:
   - **Networking cluster:** All `google_compute_network`, `google_compute_subnetwork`,
     `google_compute_firewall`, `google_compute_router*`, `google_compute_global_address`,
     `google_dns*` resources → 1 cluster
   - **Per-primary clusters:** Each PRIMARY resource + its SECONDARY `serves` dependents → 1 cluster
   - `google_project_service` resources → attach to the cluster of the service they enable
   - Naming: `{category}_{type}_{region}_{sequence}` (same convention as full clustering)

4. **Set depth:** Networking cluster = depth 0. All other clusters = depth 1. (No Kahn's algorithm needed.)

5. **Load** `references/shared/schema-discover-iac.md` and write output files
   (`gcp-resource-inventory.json`, `gcp-resource-clusters.json`) using the same schema.
   Add to metadata: `"clustering_mode": "simplified"`.

6. **Proceed to Step 7** (same as full path).

**Note:** The simplified path produces the SAME output schema as the full path. Downstream
phases (clarify, design, estimate, generate) work identically regardless of clustering mode.

## Step 3: Classify Resources (PRIMARY vs SECONDARY)

1. Read `references/clustering/terraform/classification-rules.md` completely
2. For EACH resource from Step 1, apply classification rules in priority order:
   - **Priority 0**: Check if in Excluded Resources list → **remove from resource list entirely**. Do not classify, cluster, or include in output. Log: "Auth provider detected — excluded from migration scope."
   - **Priority 1**: Check if in PRIMARY list → mark `classification: "PRIMARY"`, assign `tier`, continue
   - **Priority 2**: Check if type matches SECONDARY patterns → mark `classification: "SECONDARY"` with `secondary_role` (one of: `identity`, `access_control`, `network_path`, `configuration`, `encryption`, `orchestration`)
   - **Priority 3**: Apply fallback heuristics first, then LLM inference → mark as SECONDARY with `secondary_role` and `confidence` field (0.5-0.75)
   - **Default**: Mark as `SECONDARY` with `secondary_role: "configuration"` and `confidence: 0.5`
3. For each resource, also record:
   - `confidence`: `0.99` (hardcoded) or `0.5-0.75` (LLM inference)
4. Confirm ALL resources have `classification` and `confidence` fields
5. Report counts (e.g., "Classified: 12 PRIMARY, 38 SECONDARY")

## Step 4: Build Dependency Edges and Populate Serves

1. Read `references/clustering/terraform/typed-edges-strategy.md` completely
2. For EACH resource from Step 1, extract references from `raw_hcl`:
   - Extract all `google_*\.[\w\.]+` patterns
   - Classify edge type by field name/value context (see typed-edges-strategy.md)
   - Store as `{from, to, relationship_type, evidence}` in `typed_edges[]` array
   - Include both **Secondary→Primary** edges (identity, network_path, etc.) and **Primary→Primary** edges (data_dependency, cache_dependency, publishes_to, etc.)
3. For SECONDARY resources, populate `serves[]` array:
   - Trace outgoing references to PRIMARY resources
   - Trace incoming `depends_on` references from PRIMARY resources
   - Include transitive chains (e.g., IAM → SA → Cloud Run)
4. Report dependency summary (e.g., "Found 45 typed edges, 38 secondaries populated serves arrays")

## Step 5: Calculate Topological Depth

1. Read `references/clustering/terraform/depth-calculation.md` completely
2. Use Kahn's algorithm (or equivalent topological sort) to assign `depth` field:
   - Depth 0: resources with no incoming dependencies
   - Depth N: resources where at least one dependency is depth N-1
3. **Detect cycles**: If any resource cannot be assigned depth, flag error: "Circular dependency detected between: [resources]. Breaking lowest-confidence edge."
4. Confirm ALL resources have `depth` field (integer >= 0)
5. Report depth summary (e.g., "Depth 0: 8 resources, Depth 1: 15 resources, ..., Max depth: 3")

## Step 6: Apply Clustering Algorithm

1. Read `references/clustering/terraform/clustering-algorithm.md` completely
2. Apply Rules 1-6 in exact priority order:
   - **Rule 1: Networking Cluster** — `google_compute_network` + all `network_path` secondaries → 1 cluster
   - **Rule 2: Same-Type Grouping** — ALL primaries of identical type → 1 cluster (not one per resource)
   - **Rule 3: Seed Clusters** — Each remaining PRIMARY gets cluster + its `serves[]` secondaries
   - **Rule 4: Merge on Dependencies** — Merge only if single deployment unit (rare)
   - **Rule 5: Skip API Services** — `google_project_service` never gets own cluster; attach to service it enables
   - **Rule 6: Deterministic Naming** — `{service_category}_{service_type}_{gcp_region}_{sequence}` (e.g., `compute_cloudrun_us-central1_001`, `database_sql_us-central1_001`)
3. For each cluster, also populate:
   - `network` — which VPC/network the cluster's resources belong to
   - `must_migrate_together` — boolean (true for all clusters by default; set false only if resources can be migrated independently)
   - `dependencies` — array of other cluster IDs this cluster depends on (derived from Primary→Primary edges between clusters)
4. Assign `cluster_id` to EVERY resource (must match one of generated clusters)
5. Confirm ALL resources have `cluster_id` field
6. Build `creation_order` — global ordering of clusters by depth level
7. Report clustering results (e.g., "Generated 6 clusters from 50 resources")

## Step 7: Write Final Output Files

**This step is MANDATORY. Write all files with exact schemas.**

### 7a: Write gcp-resource-inventory.json

1. Create file: `$MIGRATION_DIR/gcp-resource-inventory.json`
2. Load `references/shared/schema-discover-iac.md` and write with the exact schema for `gcp-resource-inventory.json`

**CRITICAL field names (use EXACTLY these):**

- `address` (resource Terraform address)
- `type` (resource Terraform type)
- `name` (resource name component)
- `classification` (PRIMARY or SECONDARY)
- `tier` (infrastructure layer: compute, database, storage, networking, identity, etc.)
- `confidence` (classification confidence, 0.0-1.0)
- `secondary_role` (for secondaries only; one of: identity, access_control, network_path, configuration, encryption, orchestration)
- `serves` (for secondaries only; list of resources this secondary supports)
- `cluster_id` (assigned cluster)
- `depth` (topological depth, integer >= 0)

Include top-level sections:

- `metadata` — report_date, project_directory, terraform_version
- `summary` — total_resources, primary_resources, secondary_resources, total_clusters, classification_coverage
- `resources[]` — all resources with above fields
- `ai_detection` — has_ai_workload, confidence, confidence_level, signals_found, ai_services

### 7b: Write gcp-resource-clusters.json

1. Create file: `$MIGRATION_DIR/gcp-resource-clusters.json`
2. Write with the exact schema for `gcp-resource-clusters.json` (from `schema-discover-iac.md`, already loaded above)

**CRITICAL field names (use EXACTLY these):**

- `cluster_id` (matches resources' cluster_id)
- `primary_resources` (array of addresses)
- `secondary_resources` (array of addresses)
- `network` (which VPC/network this cluster belongs to)
- `creation_order_depth` (matches resource depths)
- `must_migrate_together` (boolean — whether cluster is atomic deployment unit)
- `dependencies` (array of other cluster IDs this depends on)
- `gcp_region` (GCP region for this cluster)
- `edges` (array of {from, to, relationship_type, evidence})

Include top-level `creation_order` array:

```json
"creation_order": [
  { "depth": 0, "clusters": ["networking_vpc_us-central1_001"] },
  { "depth": 1, "clusters": ["security_iam_us-central1_001"] },
  { "depth": 2, "clusters": ["database_sql_us-central1_001"] }
]
```

### 7c: Validate Output Files

1. Confirm `$MIGRATION_DIR/gcp-resource-inventory.json` exists and is valid JSON
2. Confirm `$MIGRATION_DIR/gcp-resource-clusters.json` exists and is valid JSON
3. Verify all resource addresses in inventory appear in exactly one cluster
4. Verify all cluster IDs match resource cluster_id assignments
5. Report to user: "Wrote gcp-resource-inventory.json (X resources) and gcp-resource-clusters.json (Y clusters)"

### 7d: Optional — Write `ai-workload-profile.json` (Vertex-strong Terraform only)

Run **only** when all of the following are true:

1. `gcp-resource-inventory.json` → `ai_detection.has_ai_workload` is `true`
2. **Vertex-strong:** at least one of:
   - `ai_detection.ai_services` includes `vertex_ai`, **or**
   - Any entry in `ai_detection.signals_found` references a Terraform resource type matching `google_vertex_ai_*` (see Step 2 pattern table)

Do **not** run this step for AI signals that are **only** BigQuery ML, Document AI, Vision, etc., with **no** Vertex AI service or `google_vertex_ai_*` signal — Category F is scoped to strong Vertex evidence here.

**If Vertex-strong:** Load `references/shared/schema-discover-ai.md` and write `$MIGRATION_DIR/ai-workload-profile.json` with a **minimal IaC-inferred** profile:

| Field                                        | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `metadata.profile_source`                    | `"iac_vertex"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `metadata.sources_analyzed.terraform`        | `true`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `metadata.sources_analyzed.application_code` | `false`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `metadata.sources_analyzed.billing_data`     | `false` (billing runs in the parent orchestrator after IaC; app-code or a later merge may set this)                                                                                                                                                                                                                                                                                                                                                                                                             |
| `summary.overall_confidence`                 | Copy from `ai_detection.confidence`                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `summary.confidence_level`                   | Copy from `ai_detection.confidence_level`                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `summary.total_models_detected`              | `0` if `models[]` is empty                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `summary.languages_found`                    | `[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `summary.inferred_from_iac`                  | `true`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `summary.ai_source`                          | `"gemini"` if any Vertex resource type suggests generative/RAG endpoints (e.g. `google_vertex_ai_endpoint`, `google_vertex_ai_index`, `google_vertex_ai_index_endpoint`, metadata stores commonly used with generative search). Use `"other"` if **only** traditional ML resources (e.g. `google_vertex_ai_training_pipeline`, `google_vertex_ai_custom_job`, `google_vertex_ai_batch_prediction_job`) with no generative-type resources. If mixed, prefer `"gemini"` when any generative-type resource exists. |
| `models`                                     | `[]` unless a model ID is explicitly present in Terraform config without guessing                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `integration.primary_sdk`                    | `null`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `integration.sdk_version`                    | omit or `null`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `integration.frameworks`                     | `[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `integration.languages`                      | `[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `integration.pattern`                        | `"unknown"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `integration.gateway_type`                   | `null`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `integration.capabilities_summary`           | All keys `false` unless a capability is clearly implied by resource kinds (default: all `false`)                                                                                                                                                                                                                                                                                                                                                                                                                |
| `infrastructure`                             | All `google_vertex_ai_*` resources from the inventory, with `address`, `type`, file path, and `config` as in schema                                                                                                                                                                                                                                                                                                                                                                                             |
| `current_costs`                              | Omit unless billing data was merged into this run (same rule as app-code schema)                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `detection_signals`                          | Mirror `ai_detection.signals_found` into the `detection_signals[]` shape (method `terraform`, confidence, evidence strings)                                                                                                                                                                                                                                                                                                                                                                                     |

**If `ai-workload-profile.json` already exists** in `$MIGRATION_DIR` with `metadata.profile_source` of `"application_code"` or `"merged"`, **skip Step 7d** (do not overwrite). Otherwise write or replace when Vertex-strong (including replacing a prior `"iac_vertex"` file).

Report to user when written: "Wrote ai-workload-profile.json (IaC-inferred Vertex AI)."

After generating output files (including optional Step 7d), the parent `discover.md` handles the phase status update — do not update `.phase-status.json` here.

## Output Validation Checklist

### gcp-resource-inventory.json

- Every resource has `address`, `type`, `name`, and `classification` fields
- Every resource has `confidence` field
- Every PRIMARY resource has `depth` and `tier` fields
- Every SECONDARY resource has `secondary_role` and `serves` fields
- Every resource has `cluster_id` matching one of the generated clusters
- All field names use EXACT required keys (see Step 7a)
- No duplicate resource addresses
- `ai_detection` section present with `has_ai_workload` and `confidence` fields
- If `has_ai_workload: true`, then `signals_found` array contains at least one signal with confidence >= 70%
- If `has_ai_workload: false`, then `confidence: 0` and `signals_found: []`
- `ai_services` array lists only services actually detected (vertex_ai, bigquery_ml, etc.)
- `confidence_level` is one of: "very_high" (90%+), "high" (70-89%), "medium" (50-69%), "low" (< 50%), "none" (0%)
- Output is valid JSON

### gcp-resource-clusters.json

- Every cluster has `cluster_id`, `primary_resources`, `secondary_resources`
- `primary_resources` and `secondary_resources` are non-overlapping
- `creation_order_depth` matches resource depths
- `gcp_region` is populated for every cluster
- `network` field is populated (references VPC resource or null if standalone)
- `must_migrate_together` is a boolean
- `dependencies` array contains only valid cluster IDs
- `edges` array uses `{from, to, relationship_type, evidence}` format
- `creation_order` array is topologically sorted
- All cluster dependencies exist in clusters array
- All resource addresses across all clusters account for every resource in inventory
- No duplicate cluster_ids
- No cycles in dependency graph
- Output is valid JSON

### ai-workload-profile.json (only if Step 7d executed)

- `metadata.profile_source` is `"iac_vertex"`
- `summary.inferred_from_iac` is `true`
- `integration.pattern` is `"unknown"` unless evidence supports another value
- `models` is `[]` unless Terraform explicitly exposes model IDs
- Valid JSON and matches `references/shared/schema-discover-ai.md`

---

## Design Phase Integration

The Design phase (`references/phases/design/design.md`) uses these outputs:

1. **From gcp-resource-clusters.json:**
   - `creation_order` — evaluates clusters depth-first (foundational first)
   - `primary_resources` / `secondary_resources` — knows which resources map independently vs which support others
   - `edges` — understands resource relationships and evidence
   - `network` — knows which VPC resources belong to
   - `dependencies` — understands cluster-level ordering
   - `must_migrate_together` — respects atomic deployment constraints

2. **From gcp-resource-inventory.json:**
   - `config` — looks up config values against design-ref signals
   - `classification` / `secondary_role` — handles primary/secondary differently
   - `serves` — determines if secondary's primary is mapped
   - `depth` — validates clustering logic
   - `tier` — routes to correct design-ref file (compute.md, database.md, etc.)
   - `ai_detection` — signals for inventory; when Step 7d ran, **`ai-workload-profile.json`** is the driver for AI Clarify/Design

3. **From `ai-workload-profile.json` (when Step 7d wrote it):** consumed in Phase 2+ per `schema-discover-ai.md` (`profile_source: "iac_vertex"`).

---

## Scope Boundary

**This phase covers Discover & Analysis ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Terraform generation for AWS
- Cost estimates or comparisons
- Effort estimates

**Your ONLY job: Inventory what exists in GCP. Nothing else.**
