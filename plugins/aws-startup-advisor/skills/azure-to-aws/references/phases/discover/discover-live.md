---
_fragment: live
_of_phase: discover
_contributes:
  - azure-resource-inventory.json (resources[], live_metadata section)
  - azure-resource-clusters.json (simplified_live clustering, or merged with the IaC base)
  - ai-workload-profile.json (minimal iac_cognitive-style profile when a live Cognitive Services / Azure ML signal is present)
---

# Discover — Live Discovery (az CLI)

> **Fragment unit.** See `discover.md` for how it composes into the phase. **Read the
> execution-model note first.** Per `discover.md`, the discover phase runs under
> `_exec: { _agent: rw }` with `_interactive: false`, so a dispatched worker CANNOT
> prompt for consent or run interactive `az`. Live discovery is therefore split,
> exactly as `discover.md` prescribes:
>
> 1. **Part A — main-window pre-work (Steps 0–2).** The consent gate and the actual
>    `az` capture commands run in the interactive MAIN window, invoked from this
>    phase's `_preconditions` prose (NOT inside the dispatched worker). They write
>    raw JSON to `$MIGRATION_DIR/live-capture/` and a `manifest.json`. If `az` is
>    missing or the user declines, Part A writes nothing and records the decline.
> 2. **Part B — dispatched parse fragment (Steps 3–7, this file's `_fragment`).**
>    File-only, non-interactive: reads the `live-capture/` directory Part A wrote and
>    maps it into `azure-resource-inventory.json` / `azure-resource-clusters.json`.
>    Runs no `az` command and never prompts. If `live-capture/` is absent or empty
>    (Part A skipped/declined), it contributes nothing and exits cleanly.

Produces the SAME artifacts as `discover-iac.md`, keyed on canonical `Microsoft.*`
ARM types, so every downstream phase works identically. When IaC discovery also ran,
Part B merges live findings into the existing inventory and surfaces drift.

**Execute ALL steps in order. Do not skip or optimize.**

## Status — net-new (build step: Discover, live `az` path)

Fills the live-`az` capability `discover.md`'s Status table reserves ("the live `az`
path — security contract, capture pre-work, parsing fragment, in that order") and
that the SKILL.md description advertises. Until this fragment, a live-`az` ask had no
producer. **Live-validated (az-cli 2.90.0, real subscription):** the preflight
(`az version`, `az account show`), the fast-path (`az resource list`), and the
enrichment rows for Container Apps (4a/4b), PostgreSQL Flexible Server (7), Storage
(11), Container Registry (11a), Log Analytics (11b), and Cognitive Services accounts +
deployments (16) were all run read-only and returned the projected fields intact —
`az resource list`, `az acr`, `az monitor log-analytics`, and `az containerapp` all
worked with NO extension installed. Rows for services not present in the test
subscription (webapp, aks, vm, sql, mysql, cosmos, redis, service bus, event hubs,
vnet, key vault, ML workspace, dns) carry command shapes ported from the pattern and
should get one live pass before they are relied on.

---

## Why the parse half needs no type-translation table

The `az` CLI emits canonical `Microsoft.*` ARM type strings natively (`az resource
list` returns `"type": "Microsoft.Web/sites"`), which is the SAME key
`discover-iac.md` canonicalizes to via `arm-type-canonicalization.md`. So the live
path is a second *producer* of the identical inventory contract — not a new mapping
surface. There is no "asset type → Terraform type" translation table because the live
output already speaks the inventory's own type language.

Live discovery is offered when the workspace has no `azurerm_*`/Bicep/ARM IaC — the
common startup case — or as an accuracy upgrade alongside IaC. Part A's consent gate
is what "offers" it.

---

## Part A — Main-window pre-work (consent + capture)

> Runs in the interactive main window from the phase `_preconditions`, BEFORE the
> dispatched worker starts. NOT part of the `_fragment` body below.

---

### Security Contract (applies to every step)

1. **Exact-command allowlist.** Run ONLY commands that appear in Step 0 (preflight)
   or the Step 2 Capture Command Table. Never a mutating verb (`create`, `update`,
   `delete`, `set`, `add`, `remove`, `deploy`, `start`, `stop`, `restart`, `import`),
   never `az login` (interactive — hand off to the user), never
   `az account get-access-token` (prints a bearer token), never any
   `... show`/`list` variant that returns secret material (see rule 2).
2. **Never capture secret values.** Every capture command uses an explicit
   `--query` (JMESPath) projection that selects NAMES/metadata, never values.
   Specifically FORBIDDEN commands (they return secret material):
   - `az webapp config appsettings list` / `az functionapp config appsettings list`
     return app-setting **values** — use the projection in the table (names only) or
     skip; never write raw appsettings to a capture file.
   - `az webapp config connection-string list` — returns connection strings; skip.
   - `az keyvault secret show` / `... secret list --query "[].value"` — secret
     values; capture Key Vault **names** only (`az keyvault list`).
   - `az cognitiveservices account keys list` — Cognitive Services keys; skip.
   - `az vm show ... osProfile.customData` — cloud-init payload; never project it.
   Additionally, apply a sensitive-key redaction pass (`password`, `secret`,
   `api_key`, `access_key`, `private_key`, `client_secret`, `connectionstring`,
   `token`, `credential`, `auth` — case-insensitive) to any config field before it
   is written into an artifact: replace matched values with `"[REDACTED]"`.
3. **Always explicit scope.** Every command passes `--subscription "$AZURE_SUBSCRIPTION"`
   explicitly. Never rely on the active `az` default subscription inside capture
   commands. One subscription per run — for multiple subscriptions, run the
   migration once per subscription.
4. **Capture to files, not context.** Redirect stdout to files under
   `$MIGRATION_DIR/live-capture/`. Process any capture file larger than ~100
   resources with a throwaway extraction script — do NOT Read large raw captures
   into context (see the Scale guard in Step 2).
5. **Consent first.** No `az` command from the Step 2 table runs before the user
   answers `[A]` in Step 1. Preflight commands in Step 0 are limited to
   version/account checks that touch no resource data.

---

### Step 0: Preflight

1. **CLI installed:** run `az version --output json` (read the `azure-cli` field).
   - Missing → tell the user: "The Azure CLI (`az`) isn't installed. Install it
     (<https://learn.microsoft.com/cli/azure/install-azure-cli>) and tell me to
     continue, or skip live discovery." Wait. If skipped → exit cleanly.
2. **Authenticated + subscription:** run `az account show --output json`
   (a local token/context read — no resource data).
   - Error / not logged in → tell the user: "Your Azure CLI isn't logged in. Run
     `az login` in your terminal — it needs a browser, so I can't run it for you —
     then tell me to continue." Wait. If declined → exit cleanly.
   - Success → show `name` + `id`, then ask: "Discover subscription
     `[name] ([id])`? [Y] Yes / [N] Use a different subscription (type its id or
     name)." Set `$AZURE_SUBSCRIPTION` to the chosen subscription **id**. If the
     user names a different one, resolve it with
     `az account show --subscription "<typed>" --output json` and use its `id`.

### Step 1: Consent Gate

Output exactly, then wait for the user's choice:

```
─── Live Azure Discovery (read-only) ───

I can inventory subscription [$AZURE_SUBSCRIPTION] directly using your
authenticated az CLI. This runs LIST/SHOW commands only:

  ✓ Captured: resource names, ARM types, regions, SKU/tier/
    capacity, container images, network topology, app-setting
    NAMES, Key Vault NAMES, and tags.
  ✗ Never captured: app-setting values, connection strings,
    Key Vault secret values, database contents, VM customData,
    or access tokens. No command that creates, changes, or
    deletes anything will run.

Output is written to .migration/<run>/live-capture/ (gitignored).

[A] Proceed with live discovery
[B] Skip — use workspace files only
```

- **[A]** → continue to Step 2.
- **[B]** → exit cleanly with no output (record the decline for the orchestrator).
  **On a re-entry where `live-capture/manifest.json` already exists from a prior
  attempt** (see `discover.md`'s "Pre-dispatch main-window action," step 1): delete
  or rename that manifest before exiting — a stale manifest left in place would
  make the dispatched `live` fragment fire on data the user just declined to use
  again.

### Step 2: Capture

Create `$MIGRATION_DIR/live-capture/`.

**2a. Fast path — subscription-wide inventory (`az resource list`, one call, no
extension):**

```
az resource list --subscription "$AZURE_SUBSCRIPTION" \
  --query "[].{id:id, name:name, type:type, location:location, resourceGroup:resourceGroup, sku:sku.name, kind:kind}" \
  --output json > $MIGRATION_DIR/live-capture/resources.json
```

`az resource list` returns every resource's canonical ARM `type`, name, location,
resourceGroup, and sku/kind in one call, is **built in (no extension)**, and needs
only the **Reader** role. This is the fast-path of choice — validated live against a
real subscription: it returned `Microsoft.*` types directly (e.g.
`Microsoft.App/containerApps`, `Microsoft.DBforPostgreSQL/flexibleServers`,
`Microsoft.CognitiveServices/accounts`) that Step 3 consumes without translation.

> **Do NOT use `az graph query` as the default fast-path.** Azure Resource Graph
> lives in the `resource-graph` CLI extension. On a fresh `az` install the command
> triggers an **interactive dynamic-install prompt** (confirmed live: it hangs
> waiting for input, it does not cleanly error) — fatal inside the non-interactive
> dispatched worker, and awkward even in the main window. `az resource list` covers
> the same fast-path need with no extension and no prompt. Only if a future need
> requires Resource Graph's KQL power, offer `az extension add --name resource-graph`
> explicitly in the main window (a local CLI install, not an Azure mutation) — never
> let dynamic-install prompt.

- Success → record `method: "resource_list"` in the manifest. `az resource list`
  carries every resource's full ARM `id` (the fast-path projects `id:id`), which is
  the required `azure_id` — enrichment rows **join their extra config onto those
  entries by that same full ARM `id`, never by name+type.** Every enrichment row also
  projects `id:id` (see the REQUIRED note below), so both sides of the join already
  carry the exact key needed. `name+type` is NOT a safe join key: it is not unique
  within a subscription (e.g. `rg-dev/api` and `rg-prod/api` can both be a
  `Microsoft.Compute/virtualMachines` named `api`, with different sizes), and a
  same-name collision across resource groups would silently attach one resource's
  enrichment config to a different resource with no later step able to detect or
  repair it. `az resource list` gives types/names/locations/sku but thin per-service
  config, so then run only the **enrichment rows** (marked E) of the table below for
  the ARM types that were found — those add the config fields (app-setting names,
  container images, network wiring, versions) that edge inference and sizing need.
  If an enrichment row's captured `id` does not match any fast-path entry (a resource
  visible to one call but not the other — e.g. a permissions or propagation gap),
  keep that enrichment entry as its own inventory entry rather than dropping it or
  guessing a match; record the gap as a `warnings[]` entry with code
  `enrichment_id_unmatched` (`schema-discover-azure.md` § Warnings), naming the
  capture row and the mismatched `id` in `detail`.

- Failure → classify and branch:
  - **Permission denied** (the identity lacks Reader on the subscription) → tell the
    user briefly that live discovery needs the **Reader** role on subscription
    `$AZURE_SUBSCRIPTION` (<https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#reader>),
    then per-service fallthrough (the per-service `list` calls hit the same wall and
    record `failed`, which is honest).
  - **Other errors** → per-service fallthrough immediately.

  **Per-service fallthrough:** record `method: "per_service"` and run every applicable
  table row. Keep the failed `az resource list` entry in `captures[]` with
  `status: "failed"` and the stderr summary in `note`.

**`id:id` and `resourceGroup:resourceGroup` on every per-service row (REQUIRED).** In the
`per_service` fallthrough there is no fast-path inventory to supply them, so every table
row's top-level `--query` projects both `id:id` (→ the required `azure_id`) and
`resourceGroup:resourceGroup` (→ the required `resource_group`) — a captured resource
missing either cannot satisfy the inventory postcondition. When both the fast path and an
enrichment row cover the same resource, the fast-path values are authoritative.

**2b. Capture Command Table.** Each row redirects to the named file, always with
`--subscription "$AZURE_SUBSCRIPTION"`. On permission/"not found" errors: record the
row as `failed`/`skipped` in the manifest and continue — a missing service is normal,
never a halt. Every row uses `--query` to project NAMES/metadata only (Security
Contract rule 2). Rows marked **E** are enrichment rows run after the `az resource list`
fast path for the ARM types it found; unmarked rows run in the per-service fallthrough.

| #   | Command (always `--subscription "$AZURE_SUBSCRIPTION" --output json`)                                                                                                                                                                                                                                                                                                                                                    | Output file            | Mode | Canonical ARM type                                          |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ---- | ----------------------------------------------------------- |
| 1   | `az webapp list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, kind:kind, sku:appServicePlanId, https:httpsOnly, appSettingNames:siteConfig.appSettings[].name, linuxFxVersion:siteConfig.linuxFxVersion, vnet:virtualNetworkSubnetId}"`                                                                                                                                                                                       | `webapp.json`          | E    | `Microsoft.Web/sites`                                       |
| 2   | `az appservice plan list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, tier:sku.tier, capacity:sku.capacity, reserved:reserved}"`                                                                                                                                                                                                                                                                              | `plans.json`           | E    | `Microsoft.Web/serverfarms`                                 |
| 3   | `az functionapp list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, kind:kind, runtime:siteConfig.linuxFxVersion, appSettingNames:siteConfig.appSettings[].name, plan:appServicePlanId}"`                                                                                                                                                                                                                                     | `functionapp.json`     | E    | `Microsoft.Web/sites` (kind `functionapp`)                  |
| 4   | `az aks list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, k8sVersion:kubernetesVersion, nodePools:agentPoolProfiles[].{name:name, vmSize:vmSize, count:count, mode:mode}, network:networkProfile.networkPlugin, vnetSubnet:agentPoolProfiles[0].vnetSubnetId}"`                                                                                                                                                               | `aks.json`             | E    | `Microsoft.ContainerService/managedClusters`               |
| 4a  | `az containerapp list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, env:properties.managedEnvironmentId, image:properties.template.containers[].image, cpu:properties.template.containers[].resources.cpu, memory:properties.template.containers[].resources.memory, minReplicas:properties.template.scale.minReplicas, maxReplicas:properties.template.scale.maxReplicas, ingress:properties.configuration.ingress.external}"` | `containerapp.json`    | E    | `Microsoft.App/containerApps`                              |
| 4b  | `az containerapp env list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location}"` — the managed environment each Container App runs in (edge target for row 4a's `env`)                                                                                                                                                                                                                                                               | `containerappenv.json` | E    | `Microsoft.App/managedEnvironments`                        |
| 5   | `az vm list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, size:hardwareProfile.vmSize, os:storageProfile.osDisk.osType, image:storageProfile.imageReference, subnet:networkProfile.networkInterfaces[0].id, tags:tags}"`                                                                                                                                                                                                      | `vm.json`              | E    | `Microsoft.Compute/virtualMachines`                         |
| 6   | `az sql server list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, version:version}"` then, per server, `az sql db list --resource-group <rg> --server <name> --query "[].{id:id, resourceGroup:resourceGroup, name:name, sku:currentSku.name, tier:currentSku.tier, capacity:currentSku.capacity, maxSizeBytes:maxSizeBytes}"` (`az sql db list` requires BOTH `--resource-group` and `--server`)                                                                                                                                                                       | `sql.json`             | E    | `Microsoft.Sql/servers`, `Microsoft.Sql/servers/databases` |
| 7   | `az postgres flexible-server list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, tier:sku.tier, version:version, storageGb:storage.storageSizeGb, haMode:highAvailability.mode}"`                                                                                                                                                                                                                                | `postgres.json`        | E    | `Microsoft.DBforPostgreSQL/flexibleServers`                 |
| 8   | `az mysql flexible-server list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, tier:sku.tier, version:version, storageGb:storage.storageSizeGb}"`                                                                                                                                                                                                                                                                 | `mysql.json`           | E    | `Microsoft.DBforMySQL/flexibleServers`                      |
| 9   | `az cosmosdb list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, kind:kind, capabilities:capabilities[].name, apiKind:apiProperties.serverVersion, multiRegion:enableMultipleWriteLocations, locations:locations[].locationName}"`                                                                                                                                                                                             | `cosmos.json`          | E    | `Microsoft.DocumentDB/databaseAccounts`                     |
| 10  | `az redis list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, family:sku.family, capacity:sku.capacity, version:redisVersion, subnet:subnetId}"`                                                                                                                                                                                                                                                                | `redis.json`           | E    | `Microsoft.Cache/redis`                                     |
| 11  | `az storage account list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, kind:kind, tier:accessTier, https:enableHttpsTrafficOnly}"`                                                                                                                                                                                                                                                                             | `storage.json`         | E    | `Microsoft.Storage/storageAccounts`                         |
| 11a | `az acr list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, adminEnabled:adminUserEnabled}"` — container registry (→ Amazon ECR)                                                                                                                                                                                                                                                                                | `acr.json`             | E    | `Microsoft.ContainerRegistry/registries`                    |
| 11b | `az monitor log-analytics workspace list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, retentionDays:retentionInDays}"` — Log Analytics (→ CloudWatch Logs)                                                                                                                                                                                                                                                    | `loganalytics.json`    | E    | `Microsoft.OperationalInsights/workspaces`                  |
| 12  | `az servicebus namespace list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, tier:sku.tier}"`                                                                                                                                                                                                                                                                                                                   | `servicebus.json`      |      | `Microsoft.ServiceBus/namespaces`                           |
| 13  | `az eventhubs namespace list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, sku:sku.name, capacity:sku.capacity, kafka:kafkaEnabled}"`                                                                                                                                                                                                                                                                                        | `eventhubs.json`       | E    | `Microsoft.EventHub/namespaces`                             |
| 14  | `az network vnet list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, addressSpace:addressSpace.addressPrefixes, subnets:subnets[].{name:name, prefix:addressPrefix}}"`                                                                                                                                                                                                                                                         | `vnet.json`            | E    | `Microsoft.Network/virtualNetworks`                         |
| 15  | `az keyvault list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location}"` — vault NAMES only, never `secret show`/`secret list --query "[].value"`                                                                                                                                                                                                                                                                                   | `keyvault.json`        | E    | `Microsoft.KeyVault/vaults`                                 |
| 16  | `az cognitiveservices account list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location, kind:kind, sku:sku.name}"` then per account `az cognitiveservices account deployment list -n <name> -g <rg> --query "[].{id:id, resourceGroup:resourceGroup, name:name, model:properties.model.name, version:properties.model.version}"`                                                                                                                                         | `cognitive.json`       | E    | `Microsoft.CognitiveServices/accounts`, `.../deployments`   |
| 17  | `az ml workspace list --query "[].{id:id, resourceGroup:resourceGroup, name:name, location:location}"` — only if the `ml` extension is present (see the row-17 note below); else record `skipped`                                                                                                                                                                                                                                                             | `mlworkspace.json`     | E    | `Microsoft.MachineLearningServices/workspaces`              |
| 18  | `az network private-dns zone list --query "[].{id:id, resourceGroup:resourceGroup, name:name}"` and `az network dns zone list --query "[].{id:id, resourceGroup:resourceGroup, name:name, records:numberOfRecordSets}"`                                                                                                                                                                                                                                                                           | `dns.json`             |      | `Microsoft.Network/dnszones`, `privateDnsZones`             |

**Row 6 note (two-step):** SQL is server-then-database. List servers, then list
databases per server; skip the `master` system database. Elastic pools
(`az sql elastic-pool list`) are an enrichment row only when a server is found.

**Row 16 note (two-step):** list Cognitive Services accounts, then list deployments
per account — the deployment's captured `model`/`version` fields (the `--query`
projects `properties.model.name` into the flat string key `model` — see the
"Deployment row field note" below Step 3; it is a string, not `model.name` on an
object) are the AI signal Design's lifecycle check consumes. Never capture keys
(`az cognitiveservices account keys list` is FORBIDDEN).

**Row 17 note (extension check, non-interactive — live-validated).** Never run
`az ml workspace list` before checking for the `ml` extension: on an `az` install
without it, running the row-17 command directly triggers the SAME kind of
interactive dynamic-install prompt the "Do NOT use `az graph query`" warning above
describes for Resource Graph — confirmed live, it hangs waiting for a
Y/n answer with no clean error, which is fatal inside the dispatched worker (and
awkward in the main window too). Check first with a command that names no resource
and runs no dynamic-install path:

```
az extension list --query "[].name" --output json
```

If `"ml"` is in the result, run row 17 normally. If not, record `skipped` in the
manifest with `note: "ml extension not installed"` and move on — do NOT offer to
install it inline (unlike Resource Graph, ML workspaces are a narrow signal this
fast-path doesn't need to chase, and prompting mid-capture risks the same hang if
the offer itself is answered via a path that re-triggers dynamic install).

**Sizing caveat:** SKU capacity / `storageGb` are PROVISIONED, not actual usage.
Downstream sizing must treat them as an upper bound. (Follow-up: actual utilization
and spend come from the billing-export / RDfA path, not live `az`.)

**Scale guard:** if any capture file exceeds ~100 resources, write a throwaway
extraction script to `$MIGRATION_DIR/_extract_live.py` that projects only the fields
Step 3 needs, run it, write its JSON output next to the raw file with a
`-extracted.json` suffix, and delete the script. Never Read the oversized raw file
directly.

**2c. Write the manifest** — `$MIGRATION_DIR/live-capture/manifest.json`:

```json
{
  "captured_at": "<ISO 8601 UTC>",
  "az_version": "<azure-cli from az version>",
  "account": "<user/servicePrincipal from az account show>",
  "subscription": "<$AZURE_SUBSCRIPTION>",
  "method": "resource_list|per_service",
  "captures": [
    { "command": "<row command>", "file": "<file>", "status": "ok|failed|skipped", "note": null }
  ]
}
```

Every attempted or deliberately skipped row gets an entry.

---

## Part B — Dispatched parse fragment (`_fragment: live`)

> File-only, non-interactive. Runs `az` NEVER; only reads `$MIGRATION_DIR/live-capture/`.
> **Entry guard:** if `$MIGRATION_DIR/live-capture/manifest.json` is absent (Part A
> was skipped or the user declined), contribute nothing and exit cleanly — this is a
> normal outcome, not a failure.

### Step 3: Map Captures to Inventory Resources

The captured `type` is ALREADY a canonical `Microsoft.*` ARM string, so there is no
type-translation table — this is the key simplification over the gcp-to-aws live path.
For each captured resource, synthesize an inventory entry matching the inventory schema
in `references/shared/schema-discover-azure.md`:

- `azure_type` = the captured ARM `type` (case-folded per
  `arm-type-canonicalization.md`; kind-qualify where the table notes it — a
  `Microsoft.Web/sites` with `kind` containing `functionapp` is a Function App).
- `azure_id` = the captured `id` field (the full ARM resource id
  `/subscriptions/.../resourceGroups/.../providers/...` that `az resource list --query
  "[].{id:id,...}"` and each per-service row's `id:id` projection return). REQUIRED on
  every entry — the schema says live `az` supplies `azure_id` directly (only Terraform
  reconstructs it), and the phase postcondition rejects an entry without a full ARM id.
  One resource → one id string (exact-match join key downstream).
- `name` = the resource name.
- `resource_group` = the captured `resourceGroup`.
- `subscription_id` = `$AZURE_SUBSCRIPTION` (the schema requires it on every entry).
- `config` = the projected fields from the capture, **renamed and reshaped to the
  SAME canonical `config` keys `extract-terraform.md`'s § "Per-type attributes"
  table defines for that `azure_type`** — never the raw `--query` alias names. Every downstream reader (sizing, edge inference, AI parsing, and the drift
  comparison against an IaC-sourced entry for the same `azure_id`) reads those
  canonical keys; a live entry that kept its capture-time alias names would silently
  read as absent to all of them, and a drift comparison against an IaC-sourced
  duplicate of the same resource would never fire because the two entries would
  share no field names to compare. Redaction rules from the Security Contract apply
  before this rename, not after. The renames actually needed, by capture row:

  | Row(s)  | Captured key(s)             | Canonical `config` key(s)                | Notes                                                                                    |
  | ------- | ---------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------- |
  | 1       | `sku`, `https`, `appSettingNames`, `linuxFxVersion` | `service_plan_id`, `https_only`, `app_setting_names`, `runtime_stack` | rename all four. `kind` already matches. `vnet` has no canonical `config` counterpart — it exists only to drive the site→vnet edge in Step 4, keep it under its captured name |
  | 3       | `runtime`, `appSettingNames`, `plan` | `runtime_stack`, `app_setting_names`, `service_plan_id` | rename all three (functionapp captures no `https` field — row 1's `https_only` stays absent for row 3, do not invent it). `kind` already matches |
  | 2       | `sku`, `capacity`, `reserved` | `sku_name`, `worker_count`, `os_type`      | `reserved: true` → `os_type: "Linux"`, else `"Windows"` (App Service Plan's `reserved` flag is Azure's Linux/Windows discriminator) |
  | 4       | `k8sVersion`, `nodePools[].vmSize`, `nodePools[].count`, `network` | `kubernetes_version`, per-pool `vm_size`, per-pool `node_count`, `network_plugin` | rename all four (`nodePools[].mode` already matches `mode`'s canonical spelling; `nodePools[].name` is not itself a canonical field, keep as-is). **Preserve every captured pool** in the renamed array — do not collapse to only the first entry; a separately-declared `azurerm_kubernetes_cluster_node_pool` on the IaC side is a distinct pool and this array is live's only equivalent signal. No `min_count`/`max_count` are captured (`az aks list` returns current `count`, not autoscale bounds) — leave them absent, do not invent bounds from `count` alone. `vnetSubnet` has no canonical counterpart — it exists only to drive the AKS→vnet edge in Step 4 (see below), keep it under its captured name |
  | 4a      | `minReplicas`, `maxReplicas` | `min_replicas`, `max_replicas`             | rename both. `cpu`, `memory`, `image` already match their canonical names. `env` and `ingress` have no canonical `config` counterparts — `env` exists only to drive the container-app→environment edge in Step 4 (see below), keep both under their captured names |
  | 5       | `os`, `image`                | `os_type`, `image_publisher`/`image_offer`/`image_sku` | rename `os`; split the captured `image` object (`imageReference`'s `publisher`/`offer`/`sku`) into its three canonical fields. `size` already matches. `zone` and `os_disk` have no row-5 capture source — leave absent, do not invent them |
  | 6       | `sku` (database row), `maxSizeBytes` | `sku_name`, `max_size_gb`          | rename `sku` → `sku_name`; convert `maxSizeBytes` → `max_size_gb` by dividing by 1024³ (bytes → GB) — unit conversion, not just a rename. `tier`/`capacity` have no canonical counterpart for this type — leave under their captured names. `elastic_pool_id`/`zone_redundant` are not captured live — leave absent, do not invent them |
  | 7, 8    | `sku`, `storageGb`           | `sku_name`, `storage_mb`                   | rename `sku` → `sku_name`; multiply `storageGb` by 1024 (GB → MB) — unit conversion, not just a rename. `tier` has no canonical counterpart — leave under its captured name |
  | 7       | `haMode`                     | `high_availability.mode`                   | the canonical field is a **nested object** (`azurerm_postgresql_flexible_server`'s `high_availability` block has a `mode` sub-attribute, e.g. `"ZoneRedundant"`) — write `config.high_availability = { "mode": "<haMode value>" }`, do NOT set `config.high_availability` to the bare string. A flat scalar there would mismatch every IaC-sourced entry's shape for the same field and break a drift comparison on it. MySQL flexible server's row-8 query does not capture HA at all, so row 8 has no `high_availability` value to set — leave absent, do not invent it |
  | 9       | `apiKind`                    | (drop — not a canonical field)             | Cosmos API routing uses `kind`/`capabilities` (already correctly named); `apiKind` (`serverVersion`) is unrelated Mongo-wire-version metadata, keep under its captured name for reference only, do not alias it onto a canonical key |
  | 10      | `sku`, `family`, `capacity`  | `sku_name`, `family`, `capacity`           | rename `sku` → `sku_name` only; `family`/`capacity` already match                        |
  | 11      | `kind`, `sku`                 | `account_kind`, `account_tier` + `account_replication_type` | rename `kind` → `account_kind`. **`sku` needs splitting, not a straight rename**: a storage account's `sku.name` is a combined string like `"Standard_GRS"` or `"Premium_LRS"` — split on the first `_` into `account_tier` (`"Standard"`/`"Premium"`) and `account_replication_type` (`"LRS"`/`"GRS"`/`"RAGRS"`/`"ZRS"`/`"GZRS"`/`"RAGZRS"`). Do not alias the whole combined string onto either canonical field alone. `tier` (captured from `accessTier`, i.e. Hot/Cool/Archive) is a DIFFERENT Azure concept from `account_tier` (Standard/Premium performance tier) despite the similar name — it has no canonical counterpart, leave it under its captured name; do not confuse the two. This rename matters: `fast-path-services.json`'s FileStorage exception for `Microsoft.Storage/storageAccounts` reads `config.account_kind`, which is unreachable without it |
  | 11b     | `sku`, `retentionDays`       | `sku`, `retention_in_days`                 | `sku` already matches (this type's canonical field is literally named `sku`); rename `retentionDays` → `retention_in_days`. `daily_quota_gb` is not captured live — leave absent, do not invent it |
  | 13      | `kafka`                      | `kafka_enabled`                            | rename only; `sku`/`capacity` already match. Row 12 (`Microsoft.ServiceBus/namespaces`) already matches (`sku`) with no rename needed — its canonical `capacity` field has no row-12 capture source, leave absent |
  | 14      | `addressSpace`, `subnets`    | `address_space`, subnet `address_prefixes` | rename the top-level key; each subnet's `prefix` → `address_prefixes` (as an array)      |
  | 16      | `sku` (account row)          | `sku_name`                                 | account-level rename only; the deployment row's `model`/`version` are handled separately below, not carried into `config` under those names |

  Every row not listed above already captures under its canonical name (e.g. rows
  4b, 11a, 15, 17, 18 project `sku`/`id`/`name`/etc. that already match
  `extract-terraform.md`, or the row has no canonical `config` mapping at all).
  When a captured field has no canonical counterpart for that type (e.g. row 5's
  `subnet`, row 9's `multiRegion`), keep it in `config` under its captured name — it
  is extra context, not a contract field, and is harmless alongside the canonical
  keys.
- `source` = `"live"` on every entry.
- `azure_type_provenance` = `"table"` when the captured `Microsoft.*` type is in the
  canonicalization table; `"derived"` / `"derived_uncorroborated"` per the rule below
  when it is not. (These are the same closed provenance values `discover.md`'s
  postconditions require — `{table, derived, derived_uncorroborated, user_confirmed}`.)

A captured `type` absent from the canonicalization table is **derived, not skipped** —
follow `discover-iac.md` Step 3's derive-and-record rule (see
`arm-type-canonicalization.md` § "Deriving a type that is not listed"): keep the
resource with `azure_type_provenance: "derived"` (or `"derived_uncorroborated"` when
the derived namespace is unrecognized), and record it in `live_metadata.derived_types`.
Never silently drop a resource.

**Classification & clustering:** apply `discover-iac.md`'s PRIMARY/SECONDARY rules and
`{category}_{type}_{region}_{sequence}` cluster naming (see Step 5). Set
`metadata.confidence: "inferred"` — the confidence enum is
`deterministic | measured | inferred | billing_inferred`, and live `az` without metrics
is `inferred` (declared/observed config, no utilization rollup — see
`discover-assemble.md`). It becomes `measured` only when `az monitor metrics list`
utilization backs the sizing.

**Deployment row field note (row 16, second call).** The `--query` projection
`model:properties.model.name` flattens `properties.model.name` into a plain STRING
under the key `model` — after capture, `model` is the model name itself (e.g.
`"gpt-4.1-mini"`), not an object with a `.name` property. Every reference below to
"a deployment's `model.name`" means that captured `model` string field — reading
`model.name` on it (as if it were still nested) reads undefined. Use the captured
`model` string directly wherever this section says `model.name`.

**AI detection:** if any `Microsoft.CognitiveServices/accounts`,
`.../accounts/deployments`, or `Microsoft.MachineLearningServices/workspaces` resource
was captured, contribute to `ai-workload-profile.json` per `schema-discover-ai.md` §
profile_source and sources_analyzed and § infrastructure[], so the AI track fires.
This section may be writing the ONLY qualifying resource in the profile (live-only),
or adding a live-sourced resource alongside one `discover-iac.md` Step 4.5 already
contributed (mixed IaC+live) — the rules below hold in both cases, because
`sources_analyzed`/`inferred_from_iac` are OR'd across the whole profile, not
assigned exclusively to whichever producer ran last:

- Add one `infrastructure[]` entry per captured qualifying resource, in the
  **live-sourced shape**: `{ azure_id, type, role?, config }` — keyed by `azure_id`,
  NOT `config.tf_address` (there is no Terraform reference for a live-captured
  resource). Do not touch or remove any IaC-sourced `infrastructure[]` entry
  `discover-iac.md` already wrote — the array carries both shapes side by side.
- Add a `detection_signals[]` entry with `method: "live_az"` for each live-captured
  resource — this is what carries the live provenance, since `models[].detected_via`
  is limited to `code|terraform|billing` per the schema and has no live value.
- Set `metadata.sources_analyzed.live: true`. Set `.terraform` to whatever it already
  is (`true` if an IaC-sourced resource also qualified this run, unchanged
  otherwise) — do NOT force it to `false`; a live contribution never overrides an
  IaC contribution's truth. Same rule for `summary.inferred_from_iac`: leave it
  `true` if any IaC-sourced resource qualified, regardless of this live contribution.
- Set `metadata.profile_source` to `"iac_cognitive"` if this is the only
  infrastructure-signal producer (no app-code contribution), or leave/set it to
  `"merged"` if app-code also qualified this run — same rule `discover-iac.md`
  already follows, unaffected by whether the infrastructure signal came from
  Terraform, live `az`, or both.
- Put a captured deployment's `model` field (see the field note above — it is
  already a flat string after capture, not `model.name` on an object) in `models[]`.

`Microsoft.Search/searchServices` alone is NOT a strong signal.

> **`ai_source` keys off the DEPLOYMENT MODEL, not the account `kind`** (validated
> live). Modern accounts report `kind: "AIServices"` — an umbrella that can host
> mixed families: a real subscription returned deployments `gpt-4.1-mini` +
> `text-embedding-3-small` (OpenAI family → `ai_source: "azure_openai"`) alongside
> `Kimi-K2.6` (a partner model that is NOT Azure OpenAI). Set `ai_source:
> "azure_openai"` when any deployment's `model.name` is an OpenAI-family id
> (`gpt-*`, `text-embedding-*`, `o1*`/`o3*`, `dall-e*`); classify non-OpenAI
> deployments as `ai_source: "other"` and list them so Design can flag that a
> non-OpenAI Foundry model has no direct Bedrock equivalent. `ai_source` is drawn
> from the closed set `{azure_openai, openai, anthropic, both, other}` (never
> `gemini`), per `discover.md`. Do NOT infer the source from `kind: AIServices` alone.

### Step 4: Infer Edges from Resolved Config

Live captures carry resolved ids, which beat IaC references. Build `edges[]` using
ONLY these deterministic rules (evidence = the config field path). Every edge `type`
must appear in `schema-discover-azure.md` § Typed edges — do not invent one:

| Config field (captured)                                      | Edge                                                                                                                                                    |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| webapp/functionapp `vnet` (captured field name; row 1/3)     | site → vnet, `network` (resolve subnet id → its parent vnet id) — this edge reads the row's `vnet` capture field, which is NOT renamed (see the normalization table above; kept under its captured name, no canonical counterpart) |
| webapp/functionapp `config.service_plan_id` → plan (row 1/3 → row 2) | site → App Service Plan, `hosted_on` (the plan-cost fan-in edge; see `schema-discover-azure.md`) — read the RENAMED field (`service_plan_id`, not the row's originally-captured `sku`/`plan` key) since edges are inferred after normalization |
| AKS `config.vnetSubnet` (captured field name; row 4)         | cluster → vnet, `network` — reads the row's `vnetSubnet` capture field, kept under its captured name (no canonical counterpart, see the normalization table above) |
| Container App `config.env` (captured field name; row 4a → 4b) | container app → managed environment, `hosted_on` (the env is the shared compute host — parity with App Service Plan fan-in) — reads the row's `env` capture field, kept under its captured name (no canonical counterpart, see the normalization table above) |
| Container App `image` → registry login server (row 4a → 11a) | container app → registry, `data_ref` when the image host matches a captured `acr` login server (`<name>.azurecr.io`)                                     |
| VM `config.subnet` (captured field name; row 5)              | vm → vnet, `network` — reads the row's `subnet` capture field (the `--query` projects `networkProfile.networkInterfaces[0].id`, i.e. the NIC id, into the flat key `subnet`; despite the name it holds a NIC id, not a subnet id — resolve NIC → subnet → vnet only if the NIC/subnet was also captured; else record the NIC id in `config` and emit NO edge) |
| redis `config.subnet` (captured field name; row 10)          | redis → vnet, `network` — reads the row's `subnet` capture field (the `--query` projects `subnetId` into the flat key `subnet`; there is no `subnetId` key in `config` to read) |
| cosmos `locations[]` length > 1 or `enableMultipleWriteLocations` | annotate cosmos `config.multi_region: true` (drives DynamoDB Global Tables downstream) — not an edge                                              |

No other inference — do not guess relationships from names, tags, or app-setting
names.

### Step 5: Cluster (Simplified Mode)

Apply `discover-iac.md`'s clustering rules regardless of resource count (networking
cluster at depth 0; one cluster per PRIMARY plus its `serves` secondaries at depth 1;
same `{category}_{type}_{region}_{sequence}` naming; region from the captured
`location`). Set metadata `"clustering_mode": "simplified_live"`. If more than 25
PRIMARY resources were captured, warn that clustering is coarse at this scale and
suggest narrowing to specific resource groups or regions — but continue.

**Live-specific clustering rules:**

- **Regionless / global resources** (some DNS zones, global storage): use `"global"`
  as the region component of `cluster_id`.
- **Shared secondaries** (e.g., one vnet serving multiple primaries): assign to the
  cluster of the FIRST primary in its `serves[]`; `serves[]` still lists all.
- **Evidence-less secondaries** (no Step 4 edge and empty `serves[]`, e.g., Key
  Vaults): group into their own cluster per category+region (e.g.,
  `security_keyvault_eastus_001`) at depth 1 — never attach to an unrelated primary.

### Step 6: Merge with IaC Discovery (only if `discover-iac.md` produced output)

If `azure-resource-inventory.json` does NOT already exist, skip to Step 7 (live is the
sole source).

Otherwise the IaC inventory + clusters are the BASE. Match live↔IaC entries by
**`azure_id`** when both carry one (exact match — the reliable join), falling back to
`azure_type` + `name` + `resource_group`. Then:

1. **Matched:** keep the IaC entry (its address/id, classification, cluster, depth).
   Overwrite `config` values where live disagrees — sizing, SKU, capacity, versions,
   images (live reflects reality). Record every OVERWRITTEN field as a
   `resources[].drift` entry on that resource, in the schema shape
   (`schema-discover-azure.md` § Drift records): `{ "field": "<path>", "values": [{
   "source": "terraform", "value": <iac> }, { "source": "live", "value": <live> }],
   "won": "live" }` — `won` is `live` because live reflects current state. Set
   `source: "live+terraform"`.
2. **Live-only:** append with `unmanaged_by_iac: true`. Attach to an existing cluster
   of the same category+region when one exists; else append a new simplified cluster.
3. **IaC-only:** set `source: "terraform"` (or the IaC dialect) on every unmatched IaC
   entry. Set `not_found_live: true` ONLY if the capture covering that resource's
   service succeeded (manifest `ok`). If the relevant capture failed/was skipped, leave
   it untouched — absence of evidence is not drift.
4. **Drift summary:** the per-field disagreements live on each resource as
   `resources[].drift` (item 1). Record run-level counts in `live_metadata.drift` as
   `{ "resources_live_only": N, "resources_iac_only": M, "conflicted_resources": K }`
   (a live-only rollup for reporting — NOT the per-field record, which is
   `resources[].drift`). `resources_iac_only` counts ONLY entries with
   `not_found_live: true`, never capture-failed unknowns.
5. **Merged metadata:** set `metadata.discovery_sources` to include both sources.

Never silently resolve a disagreement — every conflict lands in the drift record. This
is the same producer-disagreement contract the assembler applies (see `discover.md` and
`discover-assemble.md`): a live source that disagrees with IaC about an `azure_id`
records drift, it does not overwrite the inventory's identity.

### Step 7: Write Output Files

Load `references/shared/schema-discover-azure.md` (if not already loaded) and
write/update:

1. `$MIGRATION_DIR/azure-resource-inventory.json` — exact schema; plus:
   - `metadata.discovery_sources`: `["live"]`, `["terraform", "live"]`, etc. — a source
     appears ONLY when it contributed at least one resource (matching the iac fragment's
     rule).
   - `metadata.discovery_timestamp`, `metadata.subscriptions_discovered: ["$AZURE_SUBSCRIPTION"]`
   - `metadata.clustering_mode`: `"simplified_live"` (live-only runs)
   - `warnings[]` present (empty is fine); every entry MUST carry a `code` from the
     **closed** vocabulary in `schema-discover-azure.md` § Warnings — the phase
     postcondition rejects any other code. That vocabulary is IaC-parse-shaped
     (`untranslated_terraform_type`, `name_expression_unresolved`, etc.); a **capture
     failure / missing Reader role is NOT one of them**, so it does NOT go in
     `warnings[]`. Record capture failures in the manifest `captures[].note` and in
     `live_metadata.capture_warnings` (a live-only field) instead. Leave `warnings[]`
     empty on a live-only run unless a genuine closed-vocabulary condition applies.
   - top-level `live_metadata`:

   ```json
   {
     "found": true,
     "captured_at": "<from manifest>",
     "subscription": "<$AZURE_SUBSCRIPTION>",
     "method": "resource_list|per_service",
     "capture_warnings": ["<failed/skipped manifest entries>"],
     "derived_types": { "<arm type>": 1 },
     "drift": { "resources_live_only": 0, "resources_iac_only": 0, "conflicted_resources": 0 }
   }
   ```

   (`drift` present only when Step 6 merged.)
2. `$MIGRATION_DIR/azure-resource-clusters.json` — exact schema (merged or fresh).
3. Validate per `discover-iac.md`'s output rules (every resource in exactly one
   cluster, ids consistent, valid JSON). Report: "Live discovery: X resources captured
   from subscription [name] (Y unmanaged by IaC, Z config conflicts)."

The parent `discover.md` owns the phase status update — do not touch
`.phase-status.json` here.

---

### Error Handling

| Error                                              | Part | Behavior                                                                                                                     |
| -------------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------- |
| `az` missing / not logged in / user declines       | A    | Write no `live-capture/`; record the decline for the orchestrator. Part B then no-ops on the missing manifest.             |
| `az resource list` fails (permission denied)       | A    | State the **Reader** role requirement + docs link; fall to per-service (agent never grants roles)                          |
| `az resource list` fails (other)                   | A    | Fall to per-service immediately                                                                                            |
| `az graph` prompts to install an extension         | A    | Do NOT use `az graph` as the fast-path (it hangs on the interactive dynamic-install prompt); `az resource list` is the fast-path |
| Individual row fails (permission, not found)       | A    | Record `failed`/`skipped` in the manifest, continue — never a halt                                                        |
| Token expired mid-capture                          | A    | Stop capturing; hand off ("run `az login`, then tell me to continue"); on resume re-run Part A Step 2 (captures overwrite) |
| `live-capture/manifest.json` absent                | B    | Contribute nothing, exit cleanly (Part A skipped/declined — normal)                                                       |
| Capture file unparseable                           | B    | Record warning in `live_metadata.capture_warnings`, skip that file, continue                                              |
| Every capture failed (manifest all `failed`)       | B    | Contribute nothing; the assembler surfaces that live discovery yielded no resources and names the **Reader** role gap     |

**Key principle:** partial results are better than no results. Record what failed;
never fabricate what wasn't captured.

### Scope Boundary

**This fragment covers live Azure discovery ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, timelines, cost estimates, or effort estimates
- Any mutating `az` command, `az login`, or token printing
- App-setting values, connection strings, Key Vault secret values, VM customData, or
  unredacted sensitive config anywhere

**Your ONLY job: inventory what exists in Azure. Nothing else.**
