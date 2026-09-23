# Discover Phase: Live Discovery (gcloud CLI)

> Self-contained live-discovery sub-file. Inventories the user's GCP project
> directly through their authenticated `gcloud` CLI — read-only, consent-gated,
> env-var names only. Produces the SAME artifacts as `discover-iac.md`
> (`gcp-resource-inventory.json` + `gcp-resource-clusters.json`, simplified
> clustering mode), so all downstream phases work identically. When IaC discovery
> also ran, merges live findings into the existing inventory and surfaces drift.
> If the user declines consent or `gcloud` is unavailable, exits cleanly with no
> output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Exact-command allowlist.** Run ONLY commands that appear in Step 0 (preflight)
   or the Step 2 Capture Command Table. Never any mutating verb (`create`, `update`,
   `delete`, `set`, `add`, `remove`, `deploy`, `apply`, `import`, `patch`), never
   `gcloud auth login` (interactive — hand off to the user), never
   `gcloud auth print-access-token` or `print-identity-token` (prints credentials).
2. **Never capture secret values.** Every capture command uses an explicit
   `--format="json(...)"` field projection. Projections include env var **names**
   but never env var **values**, and never GCE instance `metadata.items` values.
   Additionally, apply `discover-iac.md`'s sensitive-key redaction patterns
   (`password`, `secret`, `api_key`, `access_key`, `private_key`, `client_secret`,
   `token`, `credential`, `auth` — case-insensitive) to any config field before it
   is written into an artifact: replace matched values with `"[REDACTED]"`.
3. **Always explicit scope.** Every command passes `--project="$GCP_PROJECT"`
   explicitly. Never rely on the active gcloud config inside capture commands.
4. **Capture to files, not context.** Redirect stdout to files under
   `$MIGRATION_DIR/live-capture/`. Process any capture file larger than ~100
   resources with a throwaway extraction script (same pattern as `discover.md`'s
   lightweight billing extraction) — do NOT Read large raw captures into context.
5. **Consent first.** No `gcloud` command from the Step 2 table runs before the
   user answers `[A]` in Step 1. Preflight commands in Step 0 are limited to
   version/auth/config checks that touch no project data.

---

## Step 0: Preflight

1. **CLI installed:** run `gcloud --version` (first line only).
   - Missing → tell the user: "The gcloud CLI isn't installed. Install it
     (https://cloud.google.com/sdk/docs/install) and tell me to continue, or skip
     live discovery." Wait. If skipped → exit cleanly.
2. **Project:** run `gcloud config get-value project` (a local config read — no
   credentials needed, which is why this step precedes the auth check).
   - Show the result and ask: "Discover project `[project-id]`? [Y] Yes /
     [N] Use a different project (type its ID)". Set `$GCP_PROJECT` accordingly.
     If the value is empty, ask the user to type the project ID. One project per
     run — for multiple projects, run the migration once per project.
3. **Authenticated:** run `gcloud auth list --filter=status:ACTIVE --format="value(account)"`.
   - Empty → do NOT hand off yet: credentials may come from ADC
     (`GOOGLE_APPLICATION_CREDENTIALS`) or service-account impersonation, which
     `auth list` does not show. Probe read-only with the project just resolved:
     `gcloud projects describe "$GCP_PROJECT" --format="value(projectId)"`.
     Probe succeeds → proceed (record `account: "adc"` in the manifest).
     Probe fails → tell the user: "Your gcloud CLI has no usable credentials.
     Run `gcloud auth login` in your terminal — it needs a browser, so I can't
     run it for you — then tell me to continue." Wait. If declined → exit cleanly.

## Step 1: Consent Gate

Output exactly, then wait for the user's choice:

```
─── Live GCP Discovery (read-only) ───

I can inventory project [$GCP_PROJECT] directly using your
authenticated gcloud CLI. This runs LIST/DESCRIBE commands only:

  ✓ Captured: resource names, types, regions, machine/instance
    sizing, container images, network topology, env var NAMES,
    secret NAMES, and labels.
  ✗ Never captured: env var values, secret values, database
    contents, instance metadata values, access tokens, or source
    code. No command that creates, changes, or deletes anything
    will run.

Output is written to .migration/<run>/live-capture/ (gitignored).

[A] Proceed with live discovery
[B] Skip — use workspace files only
```

- **[A]** → continue to Step 2.
- **[B]** → exit cleanly with no output (record the decline for the orchestrator).

## Step 2: Capture

Create `$MIGRATION_DIR/live-capture/`.

**2a. Fast path — Cloud Asset Inventory (one call, whole project):**

```
gcloud asset search-all-resources --scope="projects/$GCP_PROJECT" \
  --format=json > $MIGRATION_DIR/live-capture/assets.json
```

(`--scope` is the documented scoping flag for asset search — do not rely on the
active project. No `--asset-types` filter on purpose: unfiltered results feed
`live_metadata.unmapped_asset_types`, which tells the user what ELSE lives in
the project; the Step 2 scale guard handles large outputs.)

- Success → record `method: "asset_search"` in the manifest, then run only the
  **enrichment rows** (marked E) of the table below for asset types that were
  found (asset search returns names/types/locations but thin config). The cheap
  networking/secrets/identity lists (rows 8, 9, 11, 12) are E rows precisely so
  edge inference and name inventories keep full fidelity on this path.

  > **Why not `gcloud asset list --content-type=resource` (full metadata, one
  > call)?** Deliberate. Full `resource.data` includes env var VALUES (Cloud
  > Run, Functions) and instance metadata values — writing it to
  > `live-capture/` would put secret material on disk and break this file's
  > "values never captured" contract. Thin search + the projected enrichment
  > rows below keep values out of the captures entirely. The same applies to
  > `search-all-resources --read-mask` with resource data. Do NOT "optimize"
  > this into a full-metadata dump.
- Failure → classify the error, then branch:

  **API not enabled** (stderr matches `SERVICE_DISABLED`, "has not been used",
  "is not enabled", or "API [has not been / is not] enabled" — the common
  startup case; Cloud Asset API is off by default):

  Offer **once** (user-driven enable — never run `gcloud services enable` or
  IAM mutations yourself):

  ```
  ─── Cloud Asset Inventory not enabled ───

  The Cloud Asset API is not enabled on [$GCP_PROJECT]. Enabling it gives a
  fuller inventory in one call (including resources outside the per-service
  list). I will not change your project for you.

  1. Enable the API (pick one):

       gcloud services enable cloudasset.googleapis.com --project="$GCP_PROJECT"

     Or console: APIs & Services → Library → search "Cloud Asset API" → Enable.
     Propagation can take up to a minute.

  2. IAM — your identity also needs Cloud Asset Viewer on the project
     (`roles/cloudasset.viewer`). Owner/Editor usually already include enough
     access; otherwise ask an admin to grant that role. Docs:
     https://docs.cloud.google.com/asset-inventory/docs/view-assets

  [Y] I've enabled it (and have access) — retry Cloud Asset Inventory
  [N] Continue with per-service fallback
  ```

  - **[Y]** → wait for the user, then re-run the asset-search command **once**.
    Success → continue as the Success path above; record
    `cai_enable_offered: true`, `cai_enable_accepted: true` in the manifest.
    Still failing → tell the user briefly (if 403/PERMISSION_DENIED, mention
    `roles/cloudasset.viewer` again), then fall through to per-service (same
    as [N]); record `cai_enable_accepted: true` and the retry failure note.
  - **[N]** / no response treated as decline → fall through to per-service;
    record `cai_enable_offered: true`, `cai_enable_accepted: false`.

  **Permission denied** (403 / `PERMISSION_DENIED` without the disable signals
  above — API may already be on, but the identity lacks Cloud Asset access):

  Offer **once** (IAM guidance only — never grant roles yourself):

  ```
  ─── Cloud Asset Inventory permission denied ───

  The Cloud Asset API appears enabled, but this identity cannot search assets
  on [$GCP_PROJECT]. Grant Cloud Asset Viewer (`roles/cloudasset.viewer`) on
  the project (or a role that includes `cloudasset.assets.searchAllResources` /
  list permissions), then retry. Docs:
  https://docs.cloud.google.com/asset-inventory/docs/view-assets

  [Y] I've updated IAM — retry Cloud Asset Inventory
  [N] Continue with per-service fallback
  ```

  Same [Y]/[N] recording rules as the enable soft-ask
  (`cai_enable_offered` / `cai_enable_accepted` — here "enable" means "CAI
  access remediation offered").

  **Other errors** (network, unexpected failures): do **not** soft-ask.
  Fall through to per-service immediately; record `cai_enable_offered: false`.

  **Per-service fallthrough:** record `method: "per_service"` and run every
  applicable table row below. Always keep the failed asset-search entry in
  `captures[]` with `status: "failed"` and the stderr summary in `note`.

**2b. Capture Command Table.** Each row redirects to the named file. On
"API not enabled" / permission errors: record the row as `failed` or `skipped`
in the manifest and continue — a missing service is normal, never a halt.
(Unlike the CAI fast path, do **not** soft-ask to enable individual service
APIs — too many rows, and "service not deployed" vs "API disabled" is ambiguous
from list errors alone.)

| #  | Command (always with `--project="$GCP_PROJECT"`)                                                                                                                                                                                                                                                                                                                                                         | Output file             | Mode |
| -- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ---- |
| 1  | `gcloud run services list --format="json(metadata.name, metadata.labels, metadata.annotations, spec.template.metadata.annotations, spec.template.spec.serviceAccountName, spec.template.spec.containers[].image, spec.template.spec.containers[].resources.limits, spec.template.spec.containers[].env[].name, spec.template.spec.containerConcurrency, spec.template.spec.timeoutSeconds, status.url)"` | `run.json`              | E    |
| 2  | `gcloud sql instances list --format="json(name, region, databaseVersion, settings.tier, settings.availabilityType, settings.dataDiskSizeGb, settings.ipConfiguration.privateNetwork, settings.ipConfiguration.ipv4Enabled, settings.backupConfiguration.enabled)"`                                                                                                                                       | `sql.json`              | E    |
| 3  | `gcloud container clusters list --format="json(name, location, currentNodeCount, currentMasterVersion, network, subnetwork, autopilot.enabled, nodePools[].name, nodePools[].config.machineType, nodePools[].initialNodeCount)"`                                                                                                                                                                         | `gke.json`              | E    |
| 4  | `gcloud functions list --format="json(name, environment, runtime, entryPoint, availableMemoryMb, serviceConfig.availableMemory, serviceConfig.runtime, serviceConfig.timeoutSeconds, eventTrigger.eventType, serviceConfig.serviceAccountEmail)"`                                                                                                                                                        | `functions.json`        | E    |
| 5  | `gcloud storage buckets list --format="json(name, location, storageClass, timeCreated, iamConfiguration.uniformBucketLevelAccess.enabled, versioning.enabled)"`                                                                                                                                                                                                                                          | `buckets.json`          | E    |
| 6  | `gcloud pubsub topics list --format="json(name, labels)"`                                                                                                                                                                                                                                                                                                                                                | `pubsub.json`           |      |
| 7  | `gcloud compute instances list --format="json(name, zone, machineType, status, networkInterfaces[].network, networkInterfaces[].subnetwork, disks[].diskSizeGb, serviceAccounts[].email, labels)"`                                                                                                                                                                                                       | `gce.json`              | E    |
| 8  | `gcloud compute networks list --format="json(name, autoCreateSubnetworks, subnetworks)"`                                                                                                                                                                                                                                                                                                                 | `networks.json`         | E    |
| 9  | `gcloud compute networks subnets list --format="json(name, region, network, ipCidrRange)"`                                                                                                                                                                                                                                                                                                               | `subnets.json`          | E    |
| 10 | `gcloud redis instances list --region=<each walk region — see the region-walk note below> --format="json(name, tier, memorySizeGb, redisVersion, authorizedNetwork, locationId)"`                                                                                                                                                                                                                        | `redis-<region>.json`   | E    |
| 11 | `gcloud secrets list --format="json(name, replication, createTime)"` — secret NAMES only, never `versions access`                                                                                                                                                                                                                                                                                        | `secrets.json`          | E    |
| 12 | `gcloud iam service-accounts list --format="json(email, displayName, disabled)"`                                                                                                                                                                                                                                                                                                                         | `sa.json`               | E    |
| 13 | `gcloud dns managed-zones list --format="json(name, dnsName, visibility)"`                                                                                                                                                                                                                                                                                                                               | `dns.json`              |      |
| 14 | `gcloud spanner instances list --format="json(name, config, nodeCount, processingUnits)"`                                                                                                                                                                                                                                                                                                                | `spanner.json`          |      |
| 15 | `gcloud firestore databases list --format="json(name, type, locationId)"`                                                                                                                                                                                                                                                                                                                                | `firestore.json`        |      |
| 16 | `gcloud ai endpoints list --region=<each walk region — see the region-walk note below> --format="json(name, displayName, deployedModels[].model)"` — only if asset search found `aiplatform.googleapis.com/*` assets or per-service mode                                                                                                                                                                 | `vertex-<region>.json`  | E    |
| 17 | `bq ls --project_id="$GCP_PROJECT" --format=json` — dataset names/locations only (the `bq` CLI ships with the Cloud SDK; if unavailable, record `skipped` — BigQuery presence then requires the asset-search path)                                                                                                                                                                                       | `bq.json`               | E    |
| 18 | `gcloud compute firewall-rules list --format="json(name, network, direction, priority)"` — deliberately minimal projection (no source ranges or target tags; the IaC path carries full rule config when Terraform exists)                                                                                                                                                                                | `firewalls.json`        | E    |
| 19 | `gcloud compute networks vpc-access connectors describe <connector-id> --region=<from the connector id> --format="json(name, network)"` — ONLY for each distinct `run.googleapis.com/vpc-access-connector` annotation value seen in row 1 output; resolves connector → VPC for edge inference                                                                                                            | `connector-<name>.json` | E    |
| 20 | `gcloud compute regions list --format="json(name)"` — per-service mode only: enumerates the region walk for rows 10 and 16 (region names only; one cheap call)                                                                                                                                                                                                                                           | `regions.json`          |      |

**Row 1 note:** managed Cloud Run lists services across ALL regions when
`--region` is omitted — do not pass a `--region` flag (a `--region=-` form is
not documented).

**Region-walk note (rows 10 and 16):** Redis and Vertex endpoint lists are
per-region, so their coverage is exactly the set of regions walked. Determine it
by mode:

- **Asset-search mode:** walk the regions of the matching assets in
  `assets.json` (`redis.googleapis.com/*` locations for row 10,
  `aiplatform.googleapis.com/*` locations for row 16). Asset search is
  project-wide, so no region can hide an instance from this walk.
- **Per-service mode:** walk EVERY region from row 20's `regions.json`. Do NOT
  derive the walk from regions seen in other rows' output — that heuristic
  fails in both directions (an instance in a region with no other footprint is
  silently missed on custom-mode VPCs, while auto-mode VPC subnets inflate the
  "seen" set to every region anyway, without the honesty of saying so).
- **Row 20 failed?** Fall back to the regions seen in rows 1–9 output, and
  append to the manifest (→ `live_metadata.capture_warnings`):
  `"regions list unavailable — redis/vertex walk limited to regions observed in
  other captures; instances in other regions are not covered"`.

**Sizing caveat:** SQL `settings.dataDiskSizeGb` is PROVISIONED disk, not actual
data volume. Downstream database-migration tool selection must treat it as an
upper bound. (Follow-up: enrich with actual data size from monitoring metrics.
Also follow-up: live-only compute resources are not graviton-profiled in v1 —
`graviton_profile` entries come from the IaC path only.)

**Scale guard:** if `assets.json` (or any capture) exceeds ~100 resources, write a
throwaway extraction script to `$MIGRATION_DIR/_extract_live.py` that projects only
the fields needed by Step 3, run it, write its JSON output next to the raw file
with a `-extracted.json` suffix, and delete the script. Never Read the oversized
raw file directly.

**2c. Write the manifest** — `$MIGRATION_DIR/live-capture/manifest.json`:

```json
{
  "captured_at": "<ISO 8601 UTC>",
  "gcloud_version": "<first line of gcloud --version>",
  "account": "<active account email>",
  "project": "<$GCP_PROJECT>",
  "method": "asset_search|per_service",
  "cai_enable_offered": false,
  "cai_enable_accepted": null,
  "captures": [
    { "command": "<row command>", "file": "<file>", "status": "ok|failed|skipped", "note": null }
  ]
}
```

Every attempted or deliberately skipped row gets an entry. `cai_enable_offered` /
`cai_enable_accepted` record the Step 2a soft-ask (`accepted` is `true` /
`false` / `null` when never offered).

## Step 3: Map Captures to Inventory Resources

Synthesize Terraform-style identity so downstream design-refs (keyed on
`google_*` types) work unchanged:

- `address` = `{terraform_type}.{sanitized_resource_name}` (lowercase, `-`→`_`)
- `type` = from the mapping table below
- `name` = sanitized resource name
- `config` = the projected fields from the capture (redaction rules from the
  Security Contract apply)
- `source` = `"live"` on every entry

**Asset/CLI type → Terraform type mapping:**

| Captured type                                  | Terraform `type`                                                                                                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run.googleapis.com/Service` / row 1           | `google_cloud_run_v2_service`                                                                                                                        |
| `sqladmin.googleapis.com/Instance` / row 2     | `google_sql_database_instance`                                                                                                                       |
| `container.googleapis.com/Cluster` / row 3     | `google_container_cluster`                                                                                                                           |
| row 4 with `environment: GEN_2`                | `google_cloudfunctions2_function`                                                                                                                    |
| row 4 with `environment: GEN_1` (or unset)     | `google_cloudfunctions_function`                                                                                                                     |
| `storage.googleapis.com/Bucket` / row 5        | `google_storage_bucket`                                                                                                                              |
| `pubsub.googleapis.com/Topic` / row 6          | `google_pubsub_topic`                                                                                                                                |
| `compute.googleapis.com/Instance` / row 7      | `google_compute_instance`                                                                                                                            |
| `compute.googleapis.com/Network` / row 8       | `google_compute_network`                                                                                                                             |
| `compute.googleapis.com/Subnetwork` / row 9    | `google_compute_subnetwork`                                                                                                                          |
| `compute.googleapis.com/Firewall`              | `google_compute_firewall` (SECONDARY, role network_path — parity with IaC classification)                                                            |
| `redis.googleapis.com/Instance` / row 10       | `google_redis_instance`                                                                                                                              |
| `secretmanager.googleapis.com/Secret` / row 11 | `google_secret_manager_secret`                                                                                                                       |
| `iam.googleapis.com/ServiceAccount` / row 12   | `google_service_account` — `name` MUST be the email local-part (e.g. `app-sa` from `app-sa@…`), NEVER the display name, or IaC merge matching breaks |
| `dns.googleapis.com/ManagedZone` / row 13      | `google_dns_managed_zone`                                                                                                                            |
| `spanner.googleapis.com/Instance` / row 14     | `google_spanner_instance`                                                                                                                            |
| `firestore.googleapis.com/Database` / row 15   | `google_firestore_database`                                                                                                                          |
| `bigquery.googleapis.com/Dataset` / row 17     | `google_bigquery_dataset` (triggers the BigQuery specialist gate downstream — include it)                                                            |
| `aiplatform.googleapis.com/Endpoint` / row 16  | `google_vertex_ai_endpoint`                                                                                                                          |
| `aiplatform.googleapis.com/*` (other)          | `google_vertex_ai_*` (matching suffix)                                                                                                               |
| Any other asset type                           | Do NOT guess a mapping. Count it in `live_metadata.unmapped_asset_types` and exclude from the inventory.                                             |

**Classification:** apply `discover-iac.md` Step 3S rules — the Priority 1 PRIMARY
types list, everything else SECONDARY with role inferred from type
(`google_service_account` → identity; networks/subnets/DNS → network_path;
secrets → encryption; else configuration). `confidence: 0.99`.

**AI detection:** if any `aiplatform.googleapis.com/*` asset or Vertex endpoint was
captured, populate `ai_detection` exactly as `discover-iac.md` Step 2 would
(signal method `"live_gcloud"`, confidence 95, `ai_services: ["vertex_ai"]`,
`has_ai_workload: true`). Otherwise `has_ai_workload: false`, `confidence: 0`.

## Step 4: Infer Edges from Resolved Config

Live captures contain resolved values, which often beat HCL references. Build
`edges[]` using ONLY these deterministic rules (evidence = the config field path):

| Config field (captured)                                         | Edge                                                                                                                                                                                                                                                                                                            |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cloud Run annotation `run.googleapis.com/cloudsql-instances`    | run service → SQL instance, `data_dependency`                                                                                                                                                                                                                                                                   |
| Cloud Run annotation `run.googleapis.com/vpc-access-connector`  | run service → network, `network_membership` — ONLY via the row 19 describe: the annotation value is a CONNECTOR id, not a network; resolve `connector.network` first. If the describe failed/was skipped, record the connector id in the service's `config` and emit NO edge (never fabricate a network target) |
| `spec.template.spec.serviceAccountName` / `serviceAccountEmail` | service account → workload, `serves` (populate the SA's `serves[]`)                                                                                                                                                                                                                                             |
| SQL `settings.ipConfiguration.privateNetwork`                   | SQL instance → network, `network_membership`                                                                                                                                                                                                                                                                    |
| GCE `networkInterfaces[].network` / GKE `network`               | instance/cluster → network, `network_membership`                                                                                                                                                                                                                                                                |
| Subnet `network`                                                | subnet → network, `network_membership`                                                                                                                                                                                                                                                                          |
| Redis `authorizedNetwork`                                       | redis → network, `network_membership`                                                                                                                                                                                                                                                                           |

No other inference — do not guess relationships from names, labels, or env var
names.

> **Why not Cloud Asset Inventory relationship types?** Deliberate. CAI's
> relationship data (including `relationships.*` queries on
> `search-all-resources` — the query SYNTAX works on the standard endpoint,
> which misleads) requires the Security Command Center Premium/Enterprise tier
> or Gemini Cloud Assist, which the startups this skill targets do not have;
> without the entitlement those queries return nothing. Most relationship types
> are also unavailable in the search API entirely. Resolved-config inference
> above needs only `roles/viewer` and covers the workload-shaped edges that
> matter for migration sequencing. Do NOT add `relationships.*` queries to the
> capture set.

## Step 5: Cluster (Simplified Mode)

Apply `discover-iac.md` **Step 3S** clustering rules regardless of resource count
(networking cluster at depth 0; one cluster per PRIMARY plus its `serves`
secondaries at depth 1; same `{category}_{type}_{region}_{sequence}` naming;
region from the captured `region`/`location`/zone-derived-region). Set metadata
`"clustering_mode": "simplified_live"`. If more than 25 PRIMARY resources were
captured, warn the user that clustering is coarse at this scale and suggest
narrowing to specific services or regions — but continue.

**Live-specific clustering rules** (Step 3S assumes files, which don't exist here):

- **Regionless resources** (Pub/Sub topics, global buckets without a single
  region): use `"global"` as the region component of `cluster_id` and
  `gcp_region`.
- **Shared secondaries** (e.g., one service account serving multiple primaries):
  assign the resource to the cluster of the FIRST primary in its `serves[]`
  array; `serves[]` still lists all of them.
- **Evidence-less secondaries** (no Step 4 edge and empty `serves[]`, e.g.,
  secrets): do NOT attach them to an unrelated primary's cluster and do NOT
  fabricate a `serves` relationship. Group them into their own cluster per
  category+region (e.g., `security_secrets_global_001`) at depth 1.

## Step 6: Merge with IaC Discovery (only if `discover-iac.md` produced output)

If `gcp-resource-inventory.json` does NOT already exist, skip to Step 7 (live is
the sole source).

Otherwise the IaC inventory + clusters are the BASE. Match live↔IaC entries by
Terraform `type` + GCP resource name, treating these type pairs as EQUIVALENT
for matching (same underlying service; live always maps to the newer type):
`google_cloud_run_service` ≡ `google_cloud_run_v2_service`, and
`google_cloudfunctions_function` ≡ `google_cloudfunctions2_function` when the
GCP name matches. Without this aliasing, a v1-declared resource produces FALSE
drift (flagged both `not_found_live` and `unmanaged_by_terraform`). The merged
entry keeps the IaC address; a note in `config` (`"live_type"`) records the
newer live type. Match names as: live `name` vs the IaC resource's
`config.name` — for service accounts use `config.account_id` (the email
local-part IS the SA's GCP name; the address name component often differs) —
falling back to the address name component). Then:

1. **Matched:** keep the IaC entry (its address, classification, cluster,
   depth). Overwrite `config` values where live disagrees — sizing, capacity,
   versions, and images alike (live reflects reality). Live-only fields the IaC
   never declared are enrichment, not conflicts. Record every OVERWRITTEN field in
   `live_metadata.drift.config_conflicts[]` as
   `{ "address", "field", "terraform_value", "live_value" }`. Set
   `source: "live+terraform"`.
2. **Live-only:** append the entry with `unmanaged_by_terraform: true`. Attach it
   to an existing cluster of the same category+region when one exists; otherwise
   append a new simplified cluster (and add it to `creation_order` at its depth).
3. **IaC-only:** set `source: "terraform"` on every unmatched IaC entry. Set
   `not_found_live: true` ONLY if the capture covering that resource's service
   succeeded (manifest `ok`). If the relevant capture failed or was skipped,
   leave the entry otherwise untouched — absence of evidence is not drift.
4. **Drift summary:** `live_metadata.drift = { "resources_live_only": N,
   "resources_terraform_only": M, "config_conflicts": [...] }`.
   `resources_terraform_only` counts ONLY entries with `not_found_live: true`
   (confirmed absent), never capture-failed unknowns.
5. **Merged metadata:** keep the IaC base's `clustering_mode` (`"simplified"` or
   absent for full clustering) — `"simplified_live"` is for live-only runs. Set
   `metadata.discovery_sources` to include both sources.

Never silently resolve a disagreement — every conflict lands in the drift record.

## Step 7: Write Output Files

Load `references/shared/schema-discover-iac.md` (if not already loaded) and
write/update:

1. `$MIGRATION_DIR/gcp-resource-inventory.json` — exact schema; plus:
   - `metadata.discovery_sources`: `["live"]`, `["terraform", "live"]`, etc.
   - `metadata.clustering_mode`: `"simplified_live"` (live-only runs)
   - top-level `live_metadata`:

   ```json
   {
     "found": true,
     "captured_at": "<from manifest>",
     "project": "<$GCP_PROJECT>",
     "method": "asset_search|per_service",
     "cai_enable_offered": false,
     "cai_enable_accepted": null,
     "capture_warnings": ["<failed/skipped manifest entries>"],
     "unmapped_asset_types": { "<asset type>": 2 },
     "drift": { "resources_live_only": 0, "resources_terraform_only": 0, "config_conflicts": [] }
   }
   ```

   Copy `cai_enable_offered` / `cai_enable_accepted` from the manifest. (`drift`
   present only when Step 6 merged.)

2. `$MIGRATION_DIR/gcp-resource-clusters.json` — exact schema (merged or fresh).
3. Validate per `discover-iac.md` Step 7c (every resource in exactly one cluster,
   IDs consistent, valid JSON). Report: "Live discovery: X resources captured from
   project [id] (Y unmanaged by Terraform, Z config conflicts)."

The parent `discover.md` owns the phase status update — do not touch
`.phase-status.json` here.

---

## Error Handling

| Error                                              | Behavior                                                                                                                                           |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| gcloud missing / no active account / user declines | Exit cleanly with no output (orchestrator falls back to file-based sources)                                                                        |
| Asset search fails (API not enabled)               | Soft-ask once: enable API + `roles/cloudasset.viewer` how-to + docs link; on [Y] retry once; on [N]/retry-fail → per-service (agent never mutates) |
| Asset search fails (permission denied)             | Soft-ask once: grant `roles/cloudasset.viewer` + docs link; on [Y] retry once; on [N]/retry-fail → per-service                                     |
| Asset search fails (other errors)                  | Fall back to per-service immediately — do not soft-ask                                                                                             |
| Individual row fails (API not enabled, 403)        | Record `failed`/`skipped`, continue — never a halt (no per-row enable soft-ask)                                                                    |
| Token expired mid-run                              | Stop capturing; hand off ("run `gcloud auth login`, then tell me to continue"); on resume re-run Step 2 (captures overwrite)                       |
| Capture file unparseable                           | Record warning, skip that file, continue                                                                                                           |
| Every capture failed                               | Exit with no output; tell the user which permissions are missing (`roles/viewer` covers all rows)                                                  |

**Key principle:** partial results are better than no results. Record what failed;
never fabricate what wasn't captured.

## Scope Boundary

**This sub-file covers live GCP discovery ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, timelines, cost estimates, or effort estimates
- Any mutating gcloud command, `auth login`, or token printing
- Env var values, secret values, or unredacted sensitive config anywhere

**Your ONLY job: inventory what exists in GCP. Nothing else.**
