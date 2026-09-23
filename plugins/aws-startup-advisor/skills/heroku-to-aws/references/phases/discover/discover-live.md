---
_fragment: live
_of_phase: discover
_contributes:
  - heroku-resource-inventory.json (resource entries, apps, metadata, live_metadata sections)
---

# Discover Phase: Live Discovery (Parse Captured CLI Output)

> Self-contained live-discovery fragment. Reads the raw CLI captures that
> `discover-live-capture.md` wrote to `$MIGRATION_DIR/live-capture/` and maps them
> to inventory entries. **Parse-only**: this fragment runs inside the dispatched
> worker — it has no shell and MUST NOT run any `heroku` command, prompt the user,
> or re-capture anything. If `live-capture/manifest.json` does not exist, exit
> cleanly with no output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Read the Manifest

Read `$MIGRATION_DIR/live-capture/manifest.json`. It indexes every capture file with
a `status` of `ok`, `failed`, or `skipped`. Process only `ok` captures. Carry every
`failed`/`skipped` entry forward into `live_metadata.capture_warnings`.

## Step 1: Map Apps — `apps.json` + `app-<app>.json`

For each app in `apps.json` that is in the manifest's `apps_selected`:

| Capture field | Inventory field (`apps[]` entry)                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `name`        | `app_name`                                                                                                                      |
| `id`          | `app_id` (real UUID — live discovery always has this)                                                                           |
| `space.name`  | `space` (or `null`)                                                                                                             |
| `stack.name`  | feeds `heroku_generation`: `heroku-20`/`heroku-22`/`heroku-24` → `"cedar"`; contains `fir` or `cnb` → `"fir"`; else `"unknown"` |

Set `generation_action: "detect_only"`, `discovery_status: "success"`. An app whose
per-app captures all failed (manifest `failed`) gets `discovery_status:
"discovery_failed"` with `failure_reason` from the manifest note — it still gets an
`apps[]` entry and still counts in `metadata.total_apps_discovered` (it was
discovered; its details were not).

## Step 2: Map Formations — `ps-<app>.json`

Group the dyno list by `type`:

| Derivation                                              | Inventory field (`formation` config)               |
| ------------------------------------------------------- | -------------------------------------------------- |
| dyno `type`                                             | `process_type`                                     |
| count of dynos of that type                             | `quantity`                                         |
| dyno `size`, lowercased (`Standard-1X` → `standard-1x`) | `dyno_type` — normalize to match the sizing tables |
| dyno `command`                                          | `command`                                          |

Resource entry: `resource_id: "formation:{app_name}:{process_type}"`,
`resource_type: "formation"`, `source: "live"`.

**Known limitation:** `heroku ps` shows running dynos only — a process type scaled
to zero is invisible to live discovery. Record the limitation string
`"formations scaled to zero are not visible to live discovery"` once in
`live_metadata.limitations`. (When Terraform or a Procfile also ran, the assembler
recovers those process types from that source.)

## Step 3: Map Add-ons — `addons.json` (+ `pg/redis/kafka` info captures)

For each add-on attached to a selected app:

| Capture field                                     | Inventory field (`addon` config)                                                                                                                                                |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plan.name` (e.g. `heroku-postgresql:standard-0`) | split into `addon_service` and `plan` (same rule as Terraform discovery)                                                                                                        |
| `addon_service.name`                              | `provider` — `"heroku"` when the service name starts with `heroku-` (first-party data add-ons), otherwise the service name itself (matches the Terraform fragment's convention) |
| `plan.price` (`cents`, `unit`)                    | `monthly_price_usd` = `cents / 100` when `unit == "month"` (optional field)                                                                                                     |

Resource entry: `resource_id: "addon:{app_name}:{addon_service}:{plan}"`,
`resource_type: "addon"`, `source: "live"`.

**Enrich from info captures** (parse the `Key: Value` text lines; on unparseable
text, keep the plan-only entry and record a warning):

- `pg-<app>.out` → `pg_version`, `data_size_gb` (convert e.g. `10.5 GB`; MB → GB),
  `table_count`, `connection_pooling` (`true` if a Connection Pooling line is
  present, `false` if absent — never omit the field). The `data_size_gb` value
  feeds downstream database-migration tool selection.
- `redis-<app>.out` → `redis_version`, `maxmemory_policy`; set `ha_enabled: true`
  when the plan tier starts with `premium` or `private`, and
  `encryption_in_transit: true` for those tiers.
- `kafka-<app>.out` → `topic_count`, `partitions_per_topic`, `replication_factor`
  when present.

## Step 4: Map Domains, Config, Pipelines, Spaces

**Domains** (`domains-<app>.json`): one entry per custom domain —
`resource_id: "domain:{app_name}:{hostname}"`, `resource_type: "domain"`, config
`{ "hostname": ..., "sni_endpoint": <sni_endpoint.name from the capture, or null> }`.
Skip default `*.herokuapp.com` hostnames — record their count as
`live_metadata.default_heroku_domains_skipped` (exact field name), not as resources.

**Config** (`config-keys-<app>.json`): `resource_id: "config:{app_name}"`,
`resource_type: "config"`, config `{ "config_var_keys": [...] }`. Keys only — if a
capture file unexpectedly contains values (objects, not a string array), DISCARD it,
do not copy any part into the inventory, and record a warning.

**Pipelines** (`pipelines.json` + `pipeline-<pipeline>.json`):
`resource_id: "pipeline:{pipeline_name}"`, `resource_type: "pipeline"`, config
`{ "pipeline_name": ..., "stages": [{ "stage": ..., "app": ... }], "review_apps_enabled": false, "detection_status": "detect-only" }`.
Populate `stages` from the per-pipeline capture; if `review_apps_enabled` is not
derivable, set it `false` and append a note to `live_metadata.capture_warnings`.

**Spaces** (`spaces.json` + `space-<space>.json` + `space-peerings-<space>.json`):
`resource_id: "space:{space_name}"`, `resource_type: "space"`, config per the schema —
`space_name`, `region`, `shield`, and `peering` filled from the peerings capture
(`detected: true` with `vpc_id`/`peer_cidr` when an active peering exists; this is
data Terraform discovery usually cannot see).

All entries: `heroku_app` = owning app name, or `"unassociated"` for spaces and
pipelines. `source: "live"` on every entry this fragment contributes.

## Step 5: Output Contribution for the Assembler

The assembler (`discover-assemble.md`) owns the inventory's structure and the merge
with Terraform-sourced entries. This fragment contributes:

- **Resources:** all entries from Steps 2–4, each with `source: "live"`.
- **Apps:** the `apps[]` entries from Step 1.
- **Discovery sources:** contribute `"live"` to `metadata.discovery_sources`.
- **Confidence:** `"full"` when every capture for the selected apps has manifest
  status `ok`; `"reduced"` otherwise (with `confidence_note` naming what failed or
  was skipped).
- **`live_metadata`:**

```json
{
  "live_metadata": {
    "found": true,
    "captured_at": "2026-07-15T18:20:00Z",
    "apps_captured": 3,
    "apps_failed": 0,
    "capture_warnings": [],
    "limitations": ["formations scaled to zero are not visible to live discovery"]
  }
}
```

---

## Error Handling

| Error Category                                | Behavior                                                                |
| --------------------------------------------- | ----------------------------------------------------------------------- |
| `manifest.json` missing                       | Exit cleanly with no output (capture never ran)                         |
| Capture file named in manifest is missing     | Record warning, skip that capture, continue                             |
| Malformed JSON in a capture file              | Record warning, skip that file, continue                                |
| Unparseable `pg/redis/kafka` info text        | Keep the plan-only addon entry, record warning, continue                |
| Config capture contains values (not key list) | Discard the file entirely, record warning, continue — never copy values |

**Key principle:** partial results are better than no results. Any single capture
failure degrades confidence; it never halts the fragment.

---

## Scope Boundary

**This fragment covers parsing of `live-capture/` files ONLY.**

FORBIDDEN — Do NOT include ANY of:

- Running `heroku` (or any shell) commands — capture already happened in the main window
- Prompting the user
- AWS service names, recommendations, or equivalents
- Migration strategies, timelines, cost estimates, or effort estimates
- Merging or de-duplicating against Terraform-sourced entries — the assembler owns the merge

**Your ONLY job: turn raw CLI captures into inventory entries. Nothing else.**

After producing entries, the assembler handles merging into the final inventory; do
NOT update `.phase-status.json` from this fragment.
