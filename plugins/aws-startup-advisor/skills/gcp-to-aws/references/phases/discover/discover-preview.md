# Migration Preview Heuristic

> Loaded by `discover.md` Step 3 to compute a lightweight preview signal and rough cost
> estimate from discovery artifacts alone — before Clarify, Design, or Estimate run.
> This is NOT the full complexity tier (that lives in `migration-complexity.md` and requires
> preferences + billing). This is a fast, honest "at a glance" for the user.

---

## Route Detection

Before executing Steps 1–6, determine which route applies:

```
IF gcp-resource-inventory.json does NOT exist
   AND ai-workload-profile.json exists
THEN route = "ai_only"

ELSE
  route = "infra"   // covers infra-only, hybrid infra+AI, and billing-only
END
```

**AI-only route** executes Steps 1A–6A below.
**Infra route** executes Steps 1–6 below (original behavior, unchanged).

---

## AI-Only Route (Steps 1A–6A)

> Used when only `ai-workload-profile.json` exists — no Terraform, no billing data.
> Infrastructure stays on GCP; only AI/LLM calls move to AWS Bedrock.

### Step 1A: Compute AI complexity_signal

Read from `ai-workload-profile.json`:

| Input                     | Source                     | Key                                                                                |
| ------------------------- | -------------------------- | ---------------------------------------------------------------------------------- |
| `model_count`             | `ai-workload-profile.json` | Count of distinct entries in `models[]`                                            |
| `is_agentic`              | `ai-workload-profile.json` | `agentic_profile.is_agentic == true`                                               |
| `has_multi_model_routing` | `ai-workload-profile.json` | `integration.gateway_type` is `"openrouter"`, `"litellm"`, `"kong"`, or `"apigee"` |
| `has_multiple_providers`  | `ai-workload-profile.json` | `summary.ai_source == "both"` or distinct provider values across `models[]` > 1    |
| `capability_count`        | `ai-workload-profile.json` | Count of `true` values in `integration.capabilities_summary`                       |

**Classify (first match wins, top to bottom):**

```
IF is_agentic == true
   OR has_multi_model_routing == true
   OR model_count > 3
   OR has_multiple_providers == true
THEN ai_complexity_signal = "complex"

ELSE IF model_count == 1
        AND is_agentic != true
        AND has_multi_model_routing != true
        AND capability_count <= 2
THEN ai_complexity_signal = "likely_simple"

ELSE
  ai_complexity_signal = "standard"
END
```

**Fast-path eligibility:** Always `false` for AI-only route — AI profiles always route to full Clarify.

```
eligible_for_clarify_fast_path = false
```

---

### Step 2A: Build per-token price comparison

**Purpose:** Show the user what their models map to on Bedrock and whether the per-token
price is higher, lower, or roughly equivalent. Do NOT compute a monthly dollar total —
usage volume is unknown at Discover time and will be collected in Clarify (AI-only Q3
for spend, AI-only Q7 for usage volume).

For each model in `models[]` of `ai-workload-profile.json`, map to the closest Bedrock
equivalent using the table below, then look up both source and Bedrock per-token prices
from `references/shared/pricing-cache.md` (Source Provider Pricing + Bedrock Models sections).

**Source model → Bedrock equivalent mapping:**

**Same-model rows first.** OpenAI's proprietary GPT models run on Bedrock, so these sources map to themselves and
the comparison is a ~10% premium (Bedrock in-region is at OpenAI's data-residency tier, 1.10x standard — see
`references/shared/openai-on-bedrock.md`). Match these before falling through to the cross-family rows.

| Source model pattern                   | Bedrock equivalent | Bedrock model ID       |
| -------------------------------------- | ------------------ | ---------------------- |
| `gpt-5.6-sol`, `gpt-5.6` flagship      | GPT-5.6 Sol        | `openai.gpt-5.6-sol`   |
| `gpt-5.6-terra`                        | GPT-5.6 Terra      | `openai.gpt-5.6-terra` |
| `gpt-5.6-luna`                         | GPT-5.6 Luna       | `openai.gpt-5.6-luna`  |
| `gpt-5.5` (not `-pro`)                 | GPT-5.5            | `openai.gpt-5.5`       |
| `gpt-5.4` (not `-pro`/`-mini`/`-nano`) | GPT-5.4            | `openai.gpt-5.4`       |

On the mantle endpoint these are in-region only (us-east-1, us-east-2; us-west-2 additionally for Terra, Luna,
and GPT-5.4; AWS GovCloud us-gov-west-1 / us-gov-east-1 for Terra and Luna, us-gov-west-1 also for GPT-5.4).
GPT-5.6 additionally reaches most commercial regions via `bedrock-runtime` CRIS ids; GPT-5.5 / GPT-5.4 have no
CRIS. At Discover time the target region may not be known — record the same-model mapping and let Design apply
the region gate. See `references/shared/openai-on-bedrock.md`.

**Cross-family rows** — for sources with no Bedrock equivalent:

| Source model pattern                                    | Bedrock equivalent               | Bedrock model ID                           |
| ------------------------------------------------------- | -------------------------------- | ------------------------------------------ |
| `gpt-4o`, `gpt-4.1`, `gpt-5`/`5.1`/`5.2`                | Claude Sonnet 5                  | `anthropic.claude-sonnet-5`                |
| `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-5.*-mini`           | Claude Haiku 4.5                 | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| `gpt-3.5-turbo`, `gpt-4.1-nano`, `gpt-5.*-nano`         | Amazon Nova Micro                | `amazon.nova-micro-v1:0`                   |
| `gpt-*-pro` (GPT-5.x Pro), `o1-pro`, `o3-pro`           | Amazon Nova 2 Pro                | `amazon.nova-2-pro-v1:0`                   |
| `o3`, `o4-mini`, reasoning models                       | Claude Sonnet 5                  | `anthropic.claude-sonnet-5`                |
| `gemini-2.5-pro`, `gemini-3.*-pro`                      | Claude Sonnet 5                  | `anthropic.claude-sonnet-5`                |
| `gemini-2.5-flash`, `gemini-2.0-flash`                  | Claude Haiku 4.5                 | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| `gemini-2.0-flash-lite`                                 | Amazon Nova Lite                 | `amazon.nova-lite-v1:0`                    |
| `claude-3-5-sonnet`, `claude-sonnet-*`                  | Claude Sonnet 5                  | `anthropic.claude-sonnet-5`                |
| `claude-3-5-haiku`, `claude-haiku-*`                    | Claude Haiku 4.5                 | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| `claude-3-opus`, `claude-opus-*`                        | Claude Opus 4.6                  | `anthropic.claude-opus-4-6-v1`             |
| `text-embedding-*`, `*-embedding-*`                     | Amazon Titan Embeddings v2       | `amazon.titan-embed-text-v2:0`             |
| `dall-e-*`, `gpt-image-*`, `imagen-*`, image generation | Stability AI — Stable Image Core | `stability.stable-image-core-v1:0`         |
| `whisper-*`, speech-to-text                             | Amazon Transcribe                | (non-token service — note separately)      |
| `tts-*`, text-to-speech                                 | Amazon Polly                     | (non-token service — note separately)      |
| Unknown / other                                         | Amazon Nova Pro                  | `amazon.nova-pro-v1:0`                     |

For each mapped model pair, record `source_model`, `bedrock_equivalent`, both per-token
prices, and `cost_direction` (`"higher"`, `"lower"`, or `"comparable"` — Bedrock relative
to source) in the `bedrock_targets[]` entry (Step 5A schema).

**Chat display rule:** In the preview summary shown to the user, present each mapping
with its **direction only** — e.g. "gpt-4o → Claude Sonnet 4.6 (slightly higher per
token)" — do NOT show monthly dollar totals or computed spend figures. Full cost
analysis belongs in the Estimate phase where usage volume context is available.

---

### Step 3A: Build key_decisions_ahead

Generate 2-4 bullets based on what was detected in `ai-workload-profile.json`:

| Signal                               | Decision bullet                                                                 |
| ------------------------------------ | ------------------------------------------------------------------------------- |
| Always                               | "Bedrock model selection for [list detected model IDs, max 3, then '+ N more']" |
| `is_agentic == true`                 | "Agentic migration path (retarget / AgentCore Harness / Strands)"               |
| `has_multi_model_routing == true`    | "Multi-model routing strategy on Bedrock (LiteLLM adapter vs native routing)"   |
| `has_multiple_providers == true`     | "Re-embedding requirements and cascade pair testing across providers"           |
| `integration.pattern == "streaming"` | "Streaming transport layer (Bedrock streaming vs current SDK)"                  |

Cap at 4 bullets.

---

### Step 4A: Build duration_hint string

No week counts — durations are uncalibrated at Discover time (and stay heuristic after; see `shared/migration-complexity.md` § Provenance). Describe the shape of the path instead:

| ai_complexity_signal | duration_hint                                                                            |
| -------------------- | ---------------------------------------------------------------------------------------- |
| `likely_simple`      | "shortest path — single model swap; confirm after Clarify"                               |
| `standard`           | "standard path — multi-model migration with per-model evaluation; confirm after Clarify" |
| `complex`            | "long path — agentic or multi-provider stack; drivers named after Design"                |

Always append "confirm after Clarify" — full classification requires preferences.

---

### Step 5A: Write migration-preview.json (AI-only)

Write `$MIGRATION_DIR/migration-preview.json`:

```json
{
  "preview_version": 1,
  "computed_at": "<ISO 8601 UTC>",
  "route": "ai_only",
  "primary_resource_count": 0,
  "complexity_signal": "standard",
  "ai_complexity_signal": "standard",
  "eligible_for_clarify_fast_path": false,
  "services_summary": [],
  "ai_summary": {
    "model_count": 2,
    "model_ids": ["gpt-4o", "text-embedding-3-small"],
    "bedrock_targets": [
      {
        "source_model": "gpt-4o",
        "source_input_per_1m": 2.50,
        "source_output_per_1m": 10.00,
        "bedrock_equivalent": "Claude Sonnet 5",
        "bedrock_model_id": "anthropic.claude-sonnet-5",
        "bedrock_input_per_1m": 3.00,
        "bedrock_output_per_1m": 15.00,
        "cost_direction": "higher"
      },
      {
        "source_model": "text-embedding-3-small",
        "source_input_per_1m": 0.02,
        "source_output_per_1m": null,
        "bedrock_equivalent": "Amazon Titan Embeddings v2",
        "bedrock_model_id": "amazon.titan-embed-text-v2:0",
        "bedrock_input_per_1m": 0.02,
        "bedrock_output_per_1m": null,
        "cost_direction": "lower"
      }
    ],
    "is_agentic": false,
    "has_multi_model_routing": false,
    "gateway_type": "direct"
  },
  "cost_preview": {
    "monthly_estimate": null,
    "monthly_estimate_note": "Monthly estimate available after Clarify (usage volume collected in Q3, Q7)",
    "disclaimer": "Per-token prices from pricing-cache.md; full cost analysis in Estimate phase"
  },
  "duration_hint": "standard path — multi-model migration with per-model evaluation; confirm after Clarify",
  "ai_detected": true,
  "key_decisions_ahead": [
    "Bedrock model selection for gpt-4o, text-embedding-3-small",
    "Streaming transport layer (Bedrock streaming vs current SDK)"
  ]
}
```

**Field rules:**

- `route` is `"ai_only"` for this path
- `primary_resource_count` is `0` for AI-only runs (no IaC)
- `complexity_signal` mirrors `ai_complexity_signal` for downstream consumers
- `services_summary` is `[]` for AI-only runs
- `ai_summary.bedrock_targets` lists one entry per distinct source model with actual per-token prices
- `cost_preview.monthly_estimate` is always `null` at Discover time — no invented token volumes
- `eligible_for_clarify_fast_path` is always `false` for AI-only route

---

### Step 6A: Build preview chat message (AI-only)

Output this block as part of `discover.md` Step 3's user message (chat only — not a file):

```
### Your AI migration at a glance *(preview — not final)*

| | |
|---|---|
| **Models detected** | [model_ids joined by ", "] |
| **Bedrock targets** | [for each bedrock_target: "source_model → bedrock_equivalent (per-token: cost_direction)" — direction word only, no dollar figures] |
| **Routing** | [if has_multi_model_routing: gateway_type + " (multi-model routing)" else "Direct SDK"] |
| **Monthly estimate** | Available after Estimate phase |
| **Path shape** | [duration_hint] |
| **Decisions ahead** | [key_decisions_ahead joined by "; "] |

*Full cost breakdown in Estimate; runnable adapter code in Generate.*
AI workload detected — full Clarify recommended for best results.
```

Do NOT write this to a file. Chat output only.

---

## Infra Route (Steps 1–6)

> Used when `gcp-resource-inventory.json` exists (infra-only, hybrid infra+AI, or billing-only).
> Original behavior — unchanged.

## Step 1: Compute complexity_signal

Read from available discovery artifacts:

| Input                    | Source                                                  | Key                                                                             |
| ------------------------ | ------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `primary_resource_count` | `gcp-resource-inventory.json`                           | Count resources where `classification: "PRIMARY"`                               |
| `has_database`           | `gcp-resource-inventory.json`                           | Any resource type matching `google_sql_*`, `google_spanner_*`, `google_redis_*` |
| `has_bigquery`           | `gcp-resource-inventory.json` or `billing-profile.json` | Any `google_bigquery_*` resource or BigQuery billing SKU                        |
| `has_ai_profile`         | File presence                                           | `ai-workload-profile.json` exists                                               |
| `is_agentic`             | `ai-workload-profile.json`                              | `agentic_profile.is_agentic == true` (if file exists)                           |
| `billing_monthly_usd`    | `billing-profile.json`                                  | `summary.total_monthly_spend` (null if absent)                                  |

**Classify (first match wins, top to bottom):**

```
IF has_bigquery
   OR is_agentic == true
   OR primary_resource_count > 8
   OR (billing_monthly_usd != null AND billing_monthly_usd > 10000)
THEN complexity_signal = "complex"
ELSE IF primary_resource_count <= 3
        AND has_database == false
        AND has_bigquery == false
        AND is_agentic != true
        AND (billing_monthly_usd == null OR billing_monthly_usd < 1000)
THEN complexity_signal = "likely_simple"
ELSE
  complexity_signal = "standard"
END
```

**Fast-path eligibility:**

```
eligible_for_clarify_fast_path =
   complexity_signal == "likely_simple"
   AND has_ai_profile == false

eligible_for_clarify_simple_path =
   complexity_signal == "likely_simple"
   AND has_ai_profile == true
   AND is_agentic != true
   AND ai_complexity_signal == "likely_simple"
```

**`ai_complexity_signal`** (compute when `ai-workload-profile.json` exists):

```
IF agentic_profile.is_agentic == true
   OR integration.frameworks is non-empty (LangChain, CrewAI, etc.)
   OR models.length > 3
THEN ai_complexity_signal = "standard"

ELSE IF integration.pattern in ("direct_sdk", "direct")
   AND models.length <= 2
   AND agentic_profile is absent
THEN ai_complexity_signal = "likely_simple"

ELSE
   ai_complexity_signal = "standard"
END
```

---

## Step 2: Compute rough AWS cost range

**Purpose:** Give the user a ballpark before Estimate runs. Always label as rough. Never invent GCP spend if billing data is absent.

### Service type -> dev-tier AWS line item mapping

For each PRIMARY resource in `gcp-resource-inventory.json`, map to a dev-tier AWS equivalent and look up its monthly cost from `references/shared/pricing-cache.md`:

| GCP Primary Type                                                     | Typical AWS Target          | Dev-tier sizing for preview      |
| -------------------------------------------------------------------- | --------------------------- | -------------------------------- |
| `google_cloud_run_v2_service` / `google_cloud_run_service`           | Fargate                     | 0.5 vCPU, 1GB RAM, 730 hrs/mo    |
| `google_cloudfunctions_function` / `google_cloudfunctions2_function` | Lambda                      | 1M requests, 128MB, 200ms avg    |
| `google_compute_instance`                                            | EC2 t4g.small               | On-demand, us-east-1             |
| `google_container_cluster`                                           | EKS (2x t4g.small nodes)    | On-demand, us-east-1             |
| `google_sql_database_instance`                                       | RDS db.t4g.micro            | Single-AZ, gp3 20GB              |
| `google_redis_instance`                                              | ElastiCache cache.t4g.micro | Single-AZ                        |
| `google_storage_bucket`                                              | S3                          | 50GB standard + 10K GET + 1K PUT |
| `google_pubsub_topic`                                                | SQS                         | 1M requests/mo                   |
| `google_filestore_instance`                                          | EFS                         | 10GB standard                    |
| `google_spanner_instance`                                            | Aurora Serverless v2        | 0.5-1 ACU                        |
| `google_bigquery_dataset`                                            | Deferred -- specialist      | $0 (not estimated)               |

Sum the dev-tier line items to get `aws_monthly_range_usd.low`. Multiply by 1.5 for `high` (accounts for NAT gateway, data transfer, CloudWatch, and sizing variance).

### Authored-size gate (HARD — do not quote toy dollars)

The table above is a **development-tier stub**. Quoting that sum as "AWS cost" when Terraform authored production sizes is a trust failure (users compare it to their real bill and quit).

**Before writing any dollar range**, scan inventory `config` for **every** resource whose `type` is in the table below — **including SECONDARY**. `google_compute_instance_template`, `google_compute_*_instance_group_manager`, and `google_dataflow_job` are not Priority-1 PRIMARY types; if you only scan PRIMARY, those rows are dead letter.

Fire the gate if **any** row matches. Record every match, then keep at most 5 signals in this **fixed type order** (do not pick by “largest deviation” — units are not comparable): Cloud SQL → Redis → GKE / node pool → Cloud Run → Dataflow → instance template / MIG → others (GCE instance, Filestore, Spanner). Within a type, keep inventory order.

**Normalize before comparing thresholds** — a config field expressed in different units or forms must not let an equivalent size bypass the gate:

- **Cloud Run min instances:** `google_cloud_run_v2_service` sets the minimum on either the service-level `scaling.min_instance_count` or the revision-level `template.scaling.min_instance_count` (read whichever is present; also accept a top-level `min_instance_count`). `google_cloud_run_service` (v1) does not have that field at all — its minimum-instance setting is an annotation: `template.metadata.annotations["autoscaling.knative.dev/minScale"]` or the service-level `metadata.annotations["run.googleapis.com/minScale"]`. Read whichever is present and treat its integer value (annotation values are strings, e.g. `"50"`) as `min_instance_count` for the threshold below.
- **GKE node count:** evaluate **every** node pool, whether declared as a standalone `google_container_node_pool` resource or as an inline `node_pool { ... }` block (or the default pool) inside `google_container_cluster` — inline blocks are not separate resources, so a per-resource scan misses them. A pool can size itself three ways — fixed `node_count`/`initial_node_count` (no autoscaling block), the `autoscaling.min_node_count`/`max_node_count` form, or the `autoscaling.total_min_node_count`/`total_max_node_count` form (mutually exclusive with the min/max form). **All of these except the `total_*` fields are per-zone counts** — the Google provider defines `node_count` per instance group and `initial_node_count` (including the cluster's default pool) per zone, and `min_node_count`/`max_node_count` are per-zone limits. Only `total_min_node_count`/`total_max_node_count` are pool-wide totals. **Before comparing, convert per-zone counts to totals:** `effective_total = per_zone_count × zone_count`, where `zone_count` is the length of the pool's effective `node_locations` (the pool's own `node_locations`, else the cluster's; default to 1 only when neither is authored). Apply this multiplier to `node_count`, `initial_node_count`, `min_node_count`, and `max_node_count`; use `total_min_node_count`/`total_max_node_count` unchanged. Compare the resulting total against the threshold, so a fixed `node_count = 2` across three `node_locations` (= 6), a per-zone `max_node_count = 2` across three `node_locations` (= 6), and a cluster-wide `total_max_node_count = 6` are each judged on true node count rather than the author's chosen form.
- **Spanner capacity:** `google_spanner_instance` accepts either `num_nodes` or `processing_units`, and 1 node = 1,000 processing units (Terraform rejects setting both). Convert `processing_units` to node-equivalent (`processing_units / 1000`) before comparing, so `num_nodes = 1` and `processing_units = 1000` evaluate identically.

| Resource type                                                                               | Preview default being compared       | Fire if any authored field is true                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `google_cloud_run_v2_service` / `google_cloud_run_service`                                  | 0.5 vCPU, 1 GB, 1 instance           | Normalized `min_instance_count` (field or annotation, see above) > 1; parsed CPU **> 1** vCPU (`8000m` = 8, `4000m` = 4, bare `2` = 2); memory **> 2Gi** (`16Gi`, `8Gi`)                                                                                                                                                                       |
| `google_sql_database_instance`                                                              | `db.t4g.micro`, 20 GB, single-AZ     | `disk_size_gb` > 20; `availability_type` is `REGIONAL`; `tier` is not `db-f1-micro` or `db-g1-small`; `master_instance_name` is set (replica); `count` > 1                                                                                                                                                                                     |
| `google_redis_instance`                                                                     | `cache.t4g.micro` (~1 GB), single-AZ | `memory_size_gb` > 1; `tier` contains `HA` or is `STANDARD` / `STANDARD_HA`                                                                                                                                                                                                                                                                    |
| `google_container_cluster` / `google_container_node_pool` (each pool, standalone or inline) | 2× `t4g.small`                       | `machine_type` present and does **not** match `*micro*` or `*small*`; the pool-wide totals `total_min_node_count` / `total_max_node_count` (or `gke_node_count`) > 2; **or** any per-zone count (`node_count`, `initial_node_count`, `min_node_count`, `max_node_count`) whose zone-normalized total (`× node_locations` count, see above) > 2 |
| `google_dataflow_job`                                                                       | not stubbed (omitted service)        | **any presence** of this type fires (this is a missing stub line, not a size miss). Prefer recording `max_workers` / `machine_type` when set                                                                                                                                                                                                   |
| `google_compute_instance_template`                                                          | `t4g.small`                          | `machine_type` present and does **not** match `*micro*` or `*small*`                                                                                                                                                                                                                                                                           |
| `google_compute_instance_group_manager` / `google_compute_region_instance_group_manager`    | 1 instance                           | `target_size` > 2; or a linked `google_compute_region_autoscaler` / `google_compute_autoscaler` has `min_replicas` > 2                                                                                                                                                                                                                         |
| `google_compute_instance`                                                                   | `t4g.small`                          | `machine_type` present and does **not** match `*micro*` or `*small*`                                                                                                                                                                                                                                                                           |
| `google_filestore_instance`                                                                 | 10 GB                                | `capacity_gb` > 10                                                                                                                                                                                                                                                                                                                             |
| `google_spanner_instance`                                                                   | 0.5–1 ACU                            | Normalized capacity (`num_nodes`, or `processing_units / 1000` — see above) > 1                                                                                                                                                                                                                                                                |

**Worked normalization cases (pin these so equivalent configs fire identically):**

| Config as authored                                                                                                                             | Normalized value                | Gate fires? |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- | ----------- |
| `google_cloud_run_service` (v1) with `template.metadata.annotations["autoscaling.knative.dev/minScale"] = "50"`, no `min_instance_count` field | `min_instance_count` = 50       | Yes         |
| `google_cloud_run_service` (v1) with `metadata.annotations["run.googleapis.com/minScale"] = "50"`                                              | `min_instance_count` = 50       | Yes         |
| `google_cloud_run_v2_service` with `scaling.min_instance_count = 1` (no annotations)                                                           | `min_instance_count` = 1        | No          |
| `google_cloud_run_v2_service` with revision-level `template.scaling.min_instance_count = 50`, no service-level `scaling`                       | `min_instance_count` = 50       | Yes         |
| `google_container_node_pool` with `node_count = 20`, `machine_type = "e2-small"`, no `autoscaling` block, single zone                          | 20 × 1 zone = 20                | Yes         |
| `google_container_node_pool` with `node_count = 2` across 3 `node_locations` (regional pool), no `autoscaling`                                 | 2 × 3 zones = 6                 | Yes         |
| `google_container_node_pool` with `initial_node_count = 2` across 3 `node_locations`, no `autoscaling`                                         | 2 × 3 zones = 6                 | Yes         |
| `google_container_node_pool` with `autoscaling { total_min_node_count = 1, total_max_node_count = 20 }`                                        | total max node count = 20       | Yes         |
| Inline `google_container_cluster { node_pool { node_count = 20, node_config { machine_type = "e2-small" } } }` (not a standalone resource)     | total node count = 20           | Yes         |
| `google_container_node_pool` with `autoscaling { min_node_count = 1, max_node_count = 2 }`, single zone (no `node_locations`)                  | 2 × 1 zone = 2                  | No          |
| `google_container_node_pool` with `autoscaling { min_node_count = 1, max_node_count = 2 }` across 3 `node_locations`                           | 2 × 3 zones = 6                 | Yes         |
| `google_spanner_instance` with `num_nodes = 1`                                                                                                 | node-equivalent = 1             | No          |
| `google_spanner_instance` with `processing_units = 1000`                                                                                       | node-equivalent = 1000/1000 = 1 | No          |
| `google_spanner_instance` with `processing_units = 2000`                                                                                       | node-equivalent = 2000/1000 = 2 | Yes         |

If the gate fires:

1. **Do not** compute or store the stub sum. A suppressed quote must never appear as `aws_monthly_range_usd.low` / `.high`.
2. Set `cost_preview.aws_monthly_range_usd` to `null`.
3. Set `cost_preview.quote_suppressed` to `true`, `quote_suppressed_reason` to `"authored_sizes_exceed_preview_defaults"`, and `authored_size_signals` to the ordered list from above (`"address: field value"` format, max 5).
4. Set `cost_preview.disclaimer` to: `"Discover does not quote a monthly AWS range when Terraform sizes exceed the preview's hardcoded development defaults. Estimate after Clarify prices the authored (or user-confirmed) sizes."`
5. Still set `gcp_monthly_usd` from billing when present (that number is real). Never invent GCP spend.

If the gate does **not** fire, keep the existing stub-range behavior (`quote_suppressed: false` or omit the new fields).

**If `billing-profile.json` exists:** Set `gcp_monthly_usd` from `summary.total_monthly_spend`. Show GCP actual. Show the AWS range **only** when the authored-size gate did not fire.

**If only IaC:** Set `gcp_monthly_usd: null`. Show the AWS range **only** when the authored-size gate did not fire.

**If neither IaC nor billing:** Omit cost preview entirely (`cost_preview: null`).

---

## Step 3: Build key_decisions_ahead

Generate 2-4 bullets based on what was detected. Use only signals present in discovery artifacts:

| Signal                   | Decision bullet                                              |
| ------------------------ | ------------------------------------------------------------ |
| Any compute resource     | "Target region and deployment model (Fargate vs EKS)"        |
| `has_database == true`   | "Database migration tooling and cutover window"              |
| `has_ai_profile == true` | "Bedrock model selection for [detected model IDs]"           |
| `is_agentic == true`     | "Agentic migration path (retarget / Harness / Strands)"      |
| `has_bigquery == true`   | "BigQuery analytics target (specialist engagement required)" |

Always include "Target region" if any compute is present. Cap at 4 bullets.

---

## Step 4: Build duration_hint string

No week counts — durations are uncalibrated at Discover time (and stay heuristic after; see `shared/migration-complexity.md` § Provenance). Describe the shape of the path instead:

| complexity_signal | duration_hint                                                                               |
| ----------------- | ------------------------------------------------------------------------------------------- |
| `likely_simple`   | "shortest path — few services, shallow dependencies; confirm after Clarify"                 |
| `standard`        | "standard phased path — clusters in dependency order; confirm after Clarify"                |
| `complex`         | "long path — databases/AI/compliance extend the stage sequence; drivers named after Design" |

Always append "confirm after Clarify" -- full tier classification requires preferences.

---

## Step 5: Write migration-preview.json

Write `$MIGRATION_DIR/migration-preview.json`:

```json
{
  "preview_version": 1,
  "computed_at": "<ISO timestamp>",
  "primary_resource_count": 3,
  "complexity_signal": "likely_simple",
  "eligible_for_clarify_fast_path": true,
  "eligible_for_clarify_simple_path": false,
  "ai_complexity_signal": null,
  "services_summary": [
    { "gcp_type": "google_cloud_run_v2_service", "typical_aws_target": "Fargate" },
    { "gcp_type": "google_storage_bucket", "typical_aws_target": "S3" }
  ],
  "cost_preview": {
    "gcp_monthly_usd": 240.00,
    "aws_monthly_range_usd": { "low": 120, "high": 180 },
    "disclaimer": "Dev-tier rough estimate (+-30%); full analysis in Estimate phase"
  },
  "duration_hint": "shortest path — few services, shallow dependencies; confirm after Clarify",
  "ai_detected": false,
  "key_decisions_ahead": [
    "Target region and deployment model (Fargate vs EKS)",
    "Cutover window"
  ]
}
```

**Suppressed-quote example** (authored-size gate fired — use this shape when `quote_suppressed` is `true`):

```json
{
  "preview_version": 1,
  "computed_at": "<ISO timestamp>",
  "primary_resource_count": 5,
  "complexity_signal": "likely_complex",
  "eligible_for_clarify_fast_path": false,
  "eligible_for_clarify_simple_path": false,
  "ai_complexity_signal": null,
  "services_summary": [
    { "gcp_type": "google_sql_database_instance", "typical_aws_target": "RDS" },
    { "gcp_type": "google_redis_instance", "typical_aws_target": "ElastiCache" },
    { "gcp_type": "google_container_cluster", "typical_aws_target": "EKS" },
    { "gcp_type": "google_cloud_run_v2_service", "typical_aws_target": "Fargate" }
  ],
  "cost_preview": {
    "gcp_monthly_usd": 44000.00,
    "aws_monthly_range_usd": null,
    "quote_suppressed": true,
    "quote_suppressed_reason": "authored_sizes_exceed_preview_defaults",
    "authored_size_signals": [
      "google_sql_database_instance.main: tier db-custom-32-122880",
      "google_sql_database_instance.main: availability_type REGIONAL",
      "google_redis_instance.cache: memory_size_gb 100",
      "google_container_cluster.primary: machine_type e2-standard-16",
      "google_cloud_run_v2_service.api: min_instance_count 50"
    ],
    "disclaimer": "Discover does not quote a monthly AWS range when Terraform sizes exceed the preview's hardcoded development defaults. Estimate after Clarify prices the authored (or user-confirmed) sizes."
  },
  "duration_hint": "phased migration — high complexity; confirm after Clarify",
  "ai_detected": false,
  "key_decisions_ahead": [
    "Confirm production DB size and HA requirements before Design",
    "Target region and deployment model"
  ]
}
```

**Field rules:**

- `cost_preview` is `null` if neither IaC nor billing data was available
- `cost_preview.gcp_monthly_usd` is `null` if no billing data (IaC-only run)
- `cost_preview.aws_monthly_range_usd` is `null` when `quote_suppressed` is `true` (authored-size gate). Do not write a stub low/high "for later."
- `cost_preview.quote_suppressed` / `quote_suppressed_reason` / `authored_size_signals` / `disclaimer` are required when the authored-size gate fired; omit the first three when it did not. When suppressed, `disclaimer` is the gate sentence in step 4 (not the stub “dev-tier ±30%” line). When not suppressed, `disclaimer` stays the existing stub sentence.
- `ai_detected` is `true` if `ai-workload-profile.json` exists
- `services_summary` lists only PRIMARY resources, deduplicated by `gcp_type`
- `eligible_for_clarify_fast_path` is `false` whenever `ai_detected == true`, regardless of infra complexity
- `eligible_for_clarify_simple_path` is `true` only when `ai_detected == true`, `complexity_signal == "likely_simple"`, and `ai_complexity_signal == "likely_simple"` (non-agentic direct SDK, ≤2 models)
- `ai_complexity_signal` is `null` when no AI profile exists; otherwise `"likely_simple"` or `"standard"`

---

## Step 6: Build preview chat message

Output this block as part of `discover.md` Step 3's user message (chat only -- not a file):

```
### Your migration at a glance *(preview -- not final)*

| | |
|---|---|
| **Services** | [primary_resource_count] resources -> [services_summary as "Fargate, S3"] *(standard pairings)* |
| **AWS cost (rough)** | [COST_ROW] |
| **Path shape** | [duration_hint] |
| **AI** | [if ai_detected: "[model IDs] detected -- AI migration path will run" else "None detected"] |
| **Decisions ahead** | [key_decisions_ahead joined by "; "] |

*Full cost breakdown in Estimate; runnable Terraform in Generate.*

[if eligible_for_clarify_fast_path: "Your stack looks straightforward -- next step is 3 quick questions."]
[if eligible_for_clarify_simple_path: "Simple stack with lightweight AI detected -- next step is a short question set (~6 questions)."]
[if ai_detected and not eligible_for_clarify_simple_path and not eligible_for_clarify_fast_path: "AI workload detected -- full Clarify recommended for best results."]
```

Do NOT write this to a file. Chat output only.

**COST_ROW (HARD):** Fill the AWS cost cell from `cost_preview` — do not improvise.

- If `quote_suppressed` is true: `Not quoted at Discover — Terraform sizes are above the preview defaults (e.g. [first authored_size_signal]). Full AWS number in Estimate after you confirm sizing.` If `gcp_monthly_usd` is set, append a second sentence: `Your current GCP bill is ~$[gcp]/mo.` **Never** print `~$[low]-$[high]` or "dev-tier estimate" in this row when the quote is suppressed.
- Else: `~$[low]-$[high]/mo` [vs GCP ~$[gcp]/mo if billing present] `*(dev-tier estimate, +-30%)*`
