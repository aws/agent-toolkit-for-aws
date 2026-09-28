# IaC Discovery Schemas

Schemas for `gcp-resource-inventory.json` and `gcp-resource-clusters.json`, produced by `discover-iac.md`.

**Convention**: Values shown as `X|Y` in examples indicate allowed alternatives — use exactly one value per field, not the literal pipe character.

---

## gcp-resource-inventory.json (Phase 1 output)

Complete inventory of discovered GCP resources with classification, dependencies, and AI detection.

```json
{
  "metadata": {
    "report_date": "2026-02-26",
    "project_directory": "/path/to/terraform",
    "terraform_version": ">= 1.0.0"
  },
  "summary": {
    "total_resources": 50,
    "primary_resources": 12,
    "secondary_resources": 38,
    "total_clusters": 6,
    "classification_coverage": "100%"
  },
  "resources": [
    {
      "address": "google_cloud_run_service.orders_api",
      "type": "google_cloud_run_service",
      "name": "orders_api",
      "classification": "PRIMARY",
      "tier": "compute",
      "confidence": 0.99,
      "config": {
        "timeout": 60,
        "memory_mb": 512,
        "concurrency": 100
      },
      "depth": 3,
      "cluster_id": "compute_cloudrun_us-central1_001"
    },
    {
      "address": "google_service_account.app",
      "type": "google_service_account",
      "name": "app",
      "classification": "SECONDARY",
      "tier": "identity",
      "confidence": 0.99,
      "secondary_role": "identity",
      "serves": ["google_cloud_run_service.orders_api", "google_cloud_run_service.products_api"],
      "config": {
        "account_id": "app-sa"
      },
      "depth": 2,
      "cluster_id": "compute_cloudrun_us-central1_001"
    },
    {
      "address": "google_app_engine_standard_app_version.default_v1",
      "type": "google_app_engine_standard_app_version",
      "name": "default_v1",
      "classification": "SECONDARY",
      "tier": "compute",
      "confidence": 0.99,
      "secondary_role": "configuration",
      "serves": [],
      "config": {
        "service": "default",
        "version_id": "v1",
        "runtime": "python312",
        "instance_class": "F2",
        "serving_status": "SERVING",
        "project": "my-gcp-project",
        "automatic_scaling": {
          "standard_scheduler_settings": { "min_instances": 2, "max_instances": 10 }
        }
      },
      "depth": 1,
      "cluster_id": "compute_appengine_us-central1_001"
    },
    {
      "address": "google_compute_network.main",
      "type": "google_compute_network",
      "name": "main",
      "classification": "PRIMARY",
      "tier": "networking",
      "confidence": 0.99,
      "config": {
        "auto_create_subnetworks": false
      },
      "depth": 0,
      "cluster_id": "networking_vpc_us-central1_001"
    }
  ],
  "ai_detection": {
    "has_ai_workload": false,
    "confidence": 0,
    "confidence_level": "none",
    "signals_found": [],
    "ai_services": []
  }
}
```

**CRITICAL Field Names** (use EXACTLY these keys):

- `address` — Terraform resource address (NOT `id`, `resource_address`)
- `type` — Resource type (NOT `resource_type`)
- `name` — Resource name component (NOT `resource_name`)
- `classification` — `"PRIMARY"` or `"SECONDARY"` (NOT `class`, `category`)
- `tier` — Infrastructure layer: compute, database, storage, networking, identity, messaging, monitoring (NOT `layer`)
- `confidence` — Classification confidence 0.0-1.0 (NOT `certainty`)
- `secondary_role` — For secondaries only: identity, access_control, network_path, configuration, encryption, orchestration
- `serves` — For secondaries only: array of primary resource addresses served
- `depth` — Dependency depth (0 = foundational, N = depends on depth N-1)
- `cluster_id` — Which cluster this resource belongs to

**Canonical `config` keys for `google_sql_database_instance`** (Clarify Step 2 auto-extraction reads these — use EXACTLY these keys; do not write `disk_size` or a `gcp_config` object):

- `config.disk_size_gb` — allocated disk in GB, normalized from Terraform `settings.disk_size`. Omit when not set in Terraform.
- `config.disk_autoresize` — boolean, from Terraform `settings.disk_autoresize`, ONLY when explicitly set in HCL. Omit when not set — the provider default is `true`, but an omitted attribute is not evidence the author chose it, so do not synthesize the default. (Generate's disk-size cross-check treats explicit `false` as a hard allocation cap and explicit `true` as growth-possible; absent = unknown.)
- `config.availability_type` — `"ZONAL"` or `"REGIONAL"`. Omit when not set.
- `config.tier` — Cloud SQL machine tier (e.g. `"db-f1-micro"`).
- `config.database_version` — engine version string (e.g. `"POSTGRES_15"`).

Example:

```json
{
  "address": "google_sql_database_instance.db",
  "type": "google_sql_database_instance",
  "name": "db",
  "classification": "PRIMARY",
  "tier": "database",
  "confidence": 0.99,
  "config": {
    "disk_size_gb": 10,
    "availability_type": "ZONAL",
    "tier": "db-f1-micro",
    "database_version": "POSTGRES_15"
  },
  "depth": 1,
  "cluster_id": "database_sql_us-central1_001"
}
```

**Key Sections:**

- `metadata` — Report metadata (report_date, project_directory, terraform_version)
- `summary` — Aggregate statistics (total_resources, primary/secondary counts, cluster count, classification_coverage)
- `resources[]` — All discovered resources with fields above
- `ai_detection` — AI workload detection results:
  - `has_ai_workload` — boolean
  - `confidence` — 0.0-1.0
  - `confidence_level` — "very_high" (90%+), "high" (70-89%), "medium" (50-69%), "low" (< 50%), "none" (0%)
  - `signals_found[]` — array of detection signals with method, pattern, confidence, evidence
  - `ai_services[]` — list of AI services detected (vertex_ai, bigquery_ml, etc.)

### Live discovery extensions (present when `discover-live.md` ran)

Live gcloud discovery produces the same inventory/cluster schemas with these additions:

**`metadata` additional fields:**

- `discovery_sources` — string[]: which sources produced data, e.g. `["live"]` or `["terraform", "live"]`. `terraform_version` may be `null` on live-only runs.
- `clustering_mode` — `"simplified"` (IaC Step 3S; also used for merged IaC+live runs), `"simplified_live"` (live-only runs), or absent (full IaC clustering).

**`resources[]` optional fields:**

- `source` — `"terraform"`, `"live"`, or `"live+terraform"` (merged entry)
- `unmanaged_by_terraform` — `true` when live discovery found the resource but no Terraform manages it (click-ops drift)
- `not_found_live` — `true` when Terraform declares the resource but the (successful) live capture did not find it deployed

**Top-level `live_metadata` section:**

```json
{
  "live_metadata": {
    "found": true,
    "captured_at": "2026-07-20T18:20:00Z",
    "project": "acme-prod",
    "method": "asset_search",
    "cai_enable_offered": false,
    "cai_enable_accepted": null,
    "capture_warnings": [],
    "unmapped_asset_types": {},
    "drift": {
      "resources_live_only": 0,
      "resources_terraform_only": 0,
      "config_conflicts": [
        {
          "address": "google_sql_database_instance.db",
          "field": "settings.tier",
          "terraform_value": "db-f1-micro",
          "live_value": "db-custom-2-8192"
        }
      ]
    }
  }
}
```

`drift` is present only when Terraform AND live discovery both produced resources. Env var and secret VALUES must never appear anywhere in the inventory — names only, with `discover-iac.md` Step 0 redaction patterns applied.

---

## gcp-resource-clusters.json (Phase 1 output)

Resources grouped into logical clusters for migration with full dependency graph and creation order.

```json
{
  "clusters": [
    {
      "cluster_id": "networking_vpc_us-central1_001",
      "gcp_region": "us-central1",
      "primary_resources": [
        "google_compute_network.main"
      ],
      "secondary_resources": [
        "google_compute_subnetwork.app",
        "google_compute_firewall.app"
      ],
      "network": null,
      "creation_order_depth": 0,
      "must_migrate_together": true,
      "dependencies": [],
      "edges": []
    },
    {
      "cluster_id": "database_sql_us-central1_001",
      "gcp_region": "us-central1",
      "primary_resources": [
        "google_sql_database_instance.db"
      ],
      "secondary_resources": [
        "google_sql_database.main"
      ],
      "network": "networking_vpc_us-central1_001",
      "creation_order_depth": 1,
      "must_migrate_together": true,
      "dependencies": ["networking_vpc_us-central1_001"],
      "edges": [
        {
          "from": "google_sql_database_instance.db",
          "to": "google_compute_network.main",
          "relationship_type": "network_membership",
          "evidence": {
            "field_path": "settings.ip_configuration.private_network",
            "reference": "VPC membership"
          }
        }
      ]
    },
    {
      "cluster_id": "compute_cloudrun_us-central1_001",
      "gcp_region": "us-central1",
      "primary_resources": [
        "google_cloud_run_service.orders_api",
        "google_cloud_run_service.products_api"
      ],
      "secondary_resources": [
        "google_service_account.app"
      ],
      "network": "networking_vpc_us-central1_001",
      "creation_order_depth": 2,
      "must_migrate_together": true,
      "dependencies": ["database_sql_us-central1_001"],
      "edges": [
        {
          "from": "google_cloud_run_service.orders_api",
          "to": "google_sql_database_instance.db",
          "relationship_type": "data_dependency",
          "evidence": {
            "field_path": "template.spec.containers[0].env[].value",
            "reference": "DATABASE_URL"
          }
        }
      ]
    }
  ],
  "creation_order": [
    { "depth": 0, "clusters": ["networking_vpc_us-central1_001"] },
    { "depth": 1, "clusters": ["database_sql_us-central1_001"] },
    { "depth": 2, "clusters": ["compute_cloudrun_us-central1_001"] }
  ]
}
```

**Key Fields:**

- `cluster_id` — Unique cluster identifier (deterministic format: `{service_category}_{service_type}_{gcp_region}_{sequence}`)
- `gcp_region` — GCP region for this cluster
- `primary_resources` — GCP resources that map independently
- `secondary_resources` — GCP resources that support primary resources
- `network` — Which VPC cluster this cluster belongs to (cluster ID reference, or null if networking cluster itself)
- `creation_order_depth` — Depth level in topological sort (0 = foundational)
- `must_migrate_together` — Boolean indicating if cluster is an atomic deployment unit
- `dependencies` — Other cluster IDs this cluster depends on (derived from cross-cluster Primary->Primary edges)
- `edges` — Typed relationships between resources with structured evidence
- `creation_order` — Global ordering of clusters by depth level (for migration sequencing)
