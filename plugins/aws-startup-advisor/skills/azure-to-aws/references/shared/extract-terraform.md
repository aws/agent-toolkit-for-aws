# Extraction rules — Terraform (`azurerm_*`)

Loaded by `discover-iac.md` only when `.tf` files containing `azurerm_*` resources are
present. One of three per-dialect refs; the others are `extract-bicep.md` and
`extract-arm.md`. Each covers surface syntax only — the artifact contract is
`schema-discover-azure.md` and the canonical type vocabulary is
`arm-type-canonicalization.md`.

## Step 1: Find the files

Glob `**/*.tf` and `**/*.tf.json`, excluding `**/node_modules/` and any path under
`$MIGRATION_DIR`. Exclude `.terraform/` too on this first pass — its `modules/`
subtree is walked deliberately in Step 3, per module, so that each module's resources
carry the right `config.tf_module` provenance rather than appearing as loose root
resources. Read each file. A `.tf` file with no `azurerm_` or
`azapi_` resource block contributes nothing and is not an error — many repos carry
provider, backend, and variable files with no resources at all.

**Do not read `terraform.tfstate`, `*.tfstate.backup`, or any `*.tfstate`.** State files
contain resolved attribute values including secrets that the configuration only
references. They are a credential-disclosure surface, and the declared configuration
is what this fragment is for. If a state file is the only thing present, say so and
recommend a live `az` capture instead — state is not a supported input.

**One exception inside `.terraform/`: `.terraform/modules/` IS read** — it holds
downloaded module source and nothing else, so it is exactly as safe as a local module
path. See Step 3, which explains why the blanket ban was over-broad and what it cost.
Everything else under `.terraform/` stays out of scope.

## Step 2: Extract each `resource` block

For every `resource "azurerm_<x>" "<local_name>" { … }`:

1. **Resolve the type** via `arm-type-canonicalization.md`, in that file's order:

   a. **Listed in the table** → use it. `azure_type_provenance: "table"`.

   b. **Not listed** → DERIVE it per that file's § Deriving a type that is not listed:
   camelCase-pluralise the Terraform suffix for the resource segment, and supply the
   namespace. Cross-check the namespace against `fast-path-services.json` →
   `namespace_routing`, which is a **signal, not a veto**:

   - recognised → `azure_type_provenance: "derived"`
   - not recognised → `azure_type_provenance: "derived_uncorroborated"`, plus a
     `type_derived_uncorroborated` warning naming the namespace

   **Either way keep the resource, with its full `config`,** and add the Terraform type
   to `iac_metadata.derived_types`. Design routes an uncorroborated namespace to a
   model-chosen category rather than halting.

   c. **You cannot say what the service is at all** → only then is it unresolvable. Record
   it in `iac_metadata.untranslated_types` and in `warnings[]` as
   `untranslated_terraform_type` with the local name, and skip the resource. This is
   rare. A type you can NAME is never untranslated.

   **Do not skip a resource merely because its type is unlisted.** Dropping it is what made
   87% of the provider surface a hard stop, and it destroyed the `sku`/`tier` evidence Design
   needs to decide whether the resource costs money. Derivation is the design, not a
   fallback — but the table is consulted FIRST, because the cases where a guess goes wrong
   are enumerated there.
2. **Resolve `name`** from the block's `name` attribute. When it is an expression
   (`"${var.prefix}-app"`, a `format()` call, a `random_*` reference), record the
   expression verbatim in `config.name_expression` and set `name` to the Terraform
   local name prefixed `tf:` **and qualified by the module address when the resource is
   inside a module** (e.g. `tf:api` at the root, `tf:module.web_east.this` for a
   `this`-named resource in module invocation `web_east`). Two invocations of the same
   module with the same expression-driven name would otherwise both reduce to `tf:this`
   in the same resource group and reconstruct the SAME `azure_id`, so the assembler
   would collapse two real resources into one and understate the estate and cost. Do
   not attempt to evaluate it. A guessed
   name breaks the drift comparison against a live capture. Add a
   `name_expression_unresolved` warning: the reconstructed `azure_id` then carries a
   `tf:` segment and is **not** a real ARM resource ID, so that resource cannot be
   matched against a live capture — and nothing else in the artifact says so.
3. **Resolve `resource_group_name`.** If it is a reference
   (`azurerm_resource_group.app.name`), follow it to that block's `name`. If that is
   itself an expression, apply rule 2.

   **A CHILD resource inherits its parent's resource group.** Many child types carry no
   `resource_group_name` at all and instead reference the parent
   (`storage_account_id`, `server_id`, `namespace_name`, `virtual_network_name`):
   follow that reference and take the parent's group. Treating an absent
   `resource_group_name` as unresolvable would null out the group for storage shares
   and containers, SQL databases, Event Hubs, Service Bus queues and topics, and Cosmos
   databases — most of a real estate's child resources — and a resource with no group
   cannot be clustered, so the whole cluster seed would collapse.

   Only when neither an explicit group nor a resolvable parent exists: set
   `resource_group: null` and add a `resource_group_unresolved` warning.
4. **Resolve `location`** the same way, into `location`.
5. **Reconstruct `azure_id`** per `arm-type-canonicalization.md` § Reconstructing
   `azure_id`, including the resource-group exception, the implicit-singleton segment
   for storage sub-services, and the `<subscription-unknown>` placeholder rule. When
   the placeholder is used, add ONE `subscription_id_unresolved` warning for the run —
   not one per resource — and set `iac_metadata.subscription_id_source: "unresolved"`.
6. **Set `source: "terraform"`** and record provenance in `config.tf_file`,
   `config.tf_resource_name`, and `config.tf_address`. Provenance is the reason IaC
   stays a first-class source even where live capture is authoritative for state: it
   is what lets Generate emit replacement Terraform that resembles what the customer
   already maintains.

   **`config.tf_address` is the FULL module-qualified address**:
   `<azurerm_type>.<local_name>` at the root, and
   `module.<invocation>[.module.<nested>].<azurerm_type>.<local_name>` for a resource
   inside a module (matching `terraform plan`'s address form). It is the identity field
   — `tf_resource_name` alone is NOT unique, and neither is the un-prefixed
   `<type>.<local_name>`. Terraform namespaces local names per type, so a single module
   routinely contains `azurerm_resource_group.data` and `azurerm_subnet.data`; and TWO
   invocations of the same module each contain `azurerm_service_plan.this`, distinct
   only by their `module.<invocation>` prefix. Anything keyed on the bare local name or
   the module-less `<type>.<local_name>` silently collapses those into one. Keep
   `config.tf_module` as provenance, but the module prefix MUST also be part of
   `tf_address` (and of the `tf:` unresolved-name segment in rule 2) so the
   reconstructed identity of two module invocations stays distinct.
7. **Copy the sizing and routing attributes** the mapping tables need — see § Per-type
   attributes.
8. **Extract edges** — see § Edges.

Count `count` and `for_each` as **one** inventory entry, with
`config.multiplicity_expression` set to the expression,
`config.multiplicity_resolved: false`, and a `multiplicity_unresolved` warning. Do not
fan out into N entries: the count is usually a variable, so fanning out invents
resources. Flag it, because a `for_each` over a map of five apps is exactly the case
where the estimate is otherwise five times wrong in the other direction.

## Step 2a: `azapi_resource` states its ARM type outright

The AzAPI provider (`Azure/azapi`) addresses the ARM REST API directly, and a real repo
reaches for it whenever the `azurerm` provider lags an API version or a resource has no
`azurerm` implementation at all. It is common in modern Azure Terraform and must not be
skipped.

```hcl
resource "azapi_resource" "orders_budget" {
  type      = "Microsoft.Consumption/budgets@2023-05-01"
  name      = "orders-monthly"
  parent_id = azurerm_resource_group.platform.id
  body      = { properties = { amount = 2500 } }
}
```

**This is the easiest extraction in the file, and the reason is worth stating: `type`
already carries the canonical ARM type.** No canonicalization lookup is needed and none
must be attempted.

1. **Split `type` on `@`.** The left half is `azure_type` verbatim —
   `Microsoft.Consumption/budgets`. The right half is the ARM API version; keep it in
   `config.azapi_api_version`, because it is the only place a reader can see which API
   surface the customer targeted.
2. **`azure_type` is used AS GIVEN.** Do not look it up in
   `arm-type-canonicalization.md`, do not normalise it toward a row in that table, and do
   not record it as an untranslated type. The table exists to translate `azurerm_*` names;
   an AzAPI resource has already skipped that problem. Casing folds on comparison per that
   file's § Casing is a convention, not a fact, so a `type` whose casing differs from the
   table's spelling is still the same type.
3. **`parent_id` is the containment parent**, so `azure_id` is
   `<parent_id>/<type-last-segment>/<name>`. Containment is derivable by truncation and is
   **not** an edge (13.3f). When `parent_id` is an unresolved reference, apply the same
   `<subscription-unknown>` rule as everywhere else.
4. **Read `body` for routing attributes only, and never for values.** `body` is an
   arbitrary ARM payload, so it can contain anything — including secrets. Extract only the
   attributes the § Per-type attributes table names for that ARM type; if the type has no
   row there, extract `sku`, `tier` and `capacity` if present and nothing else. The secret
   boundary in § Secrets applies to `body` in full.
5. **Set `config.declared_via: "azapi"`.** Design needs it: an AzAPI resource is evidence
   the customer is already working around an `azurerm` gap, which is a useful signal for
   the report, and it explains why the type may be absent from the canonicalization table
   while still being perfectly well identified.

**`azapi_update_resource` and `azapi_resource_action` emit no inventory entry.** They
mutate a resource declared elsewhere — the AzAPI analogue of the association-only class
(13.2d) — so they are not resources and are not untranslated types. Record nothing, warn
nothing.

**A cost-bearing AzAPI type with no disposition still STOPs Design**, exactly as any other
type would. Naming a resource is not the same as knowing what it maps to: the untranslated
STOP is about the _type vocabulary_, and the unknown-type policy (§ 7a.4) is about the
_disposition_. AzAPI clears the first and not the second.

## Step 3: Modules are boundaries, not resources

A `module` block is not a resource and gets no inventory entry. Resolve its source in
this order, and stop at the first that works:

1. **Local path** (`./modules/network`, `../shared`) — recurse into it and extract its
   resources, recording the module address in `config.tf_module`.
2. **Already downloaded** — a registry or git module that has been `terraform init`-ed
   is on disk under `.terraform/modules/<key>/`. **Read it.** Resolve the key via
   `.terraform/modules/modules.json`, which maps each module's `Key` and `Source` to its
   `Dir`. Recurse exactly as for a local path, and set `config.tf_module_source` to the
   registry address so the report can say where the resources came from.
3. **Not on disk** — add one `module_not_resolved` warning naming the module and stating
   that its resources were not discovered.

> **Reading `.terraform/modules/` is explicitly ALLOWED, and it is the single highest-value
> exception in this file.** Step 1 bans `.terraform/` wholesale to keep state files out,
> and that ban is correct for state — but `.terraform/modules/` holds nothing except
> _downloaded module source code_, which is exactly as safe to read as the local module
> source in case 1 and carries no resolved values at all. The blanket ban was
> over-broad.
>
> The cost of getting this wrong is large and silent. Modern Azure Terraform leans hard
> on registry modules — Azure Verified Modules (`Azure/avm-*`), `Azure/naming`,
> `Azure/vnet` — so a repo can declare almost its entire estate through modules. Under
> the blanket ban such a repo yields a nearly empty inventory plus a handful of warnings,
> and every downstream phase then reasons confidently about a fraction of the estate.
> `module_not_resolved` is still the honest fallback, but it should be the LAST resort
> rather than the normal outcome.
>
> Still banned, for the original reason: `.terraform/terraform.tfstate`,
> `.terraform.lock.hcl` (no resources in it), and any `*.tfstate` anywhere. If a module
> directory somehow contains a state file, skip that file, not the directory.

A silently missing module is a silently missing third of the estate, and it remains the
most common reason a Terraform-only inventory is incomplete — which is why
`iac_metadata.modules_unresolved` and the warning both name the module rather than
reporting a count.

## Per-type attributes

Only what a downstream table actually reads. Everything else stays out of `config`.

**Omit, do not null.** An attribute the configuration does not set is left OUT of
`config`. Writing `"zone_balancing_enabled": null` for every unset attribute in every
row below turns `config` into mostly noise, and it makes "the customer did not set this"
indistinguishable from "the extractor found nothing to read."

**A type with no row here still gets an entry** — `azure_id`, `azure_type`,
`resource_group`, `subscription_id`, `source`, and the `config.tf_*` provenance are
unconditional. A missing row means "no downstream table reads a sizing or routing
attribute from this type", never "skip the resource".

> **EXCEPTION, and it is load-bearing: always extract `sku`, `tier` and `capacity`.**
> Whatever the per-type rows below say, if the block sets `sku`, `sku_name`, `tier`,
> `capacity` or `size`, carry it into `config`. This applies to **every** type, listed or
> not, and especially to a **derived** type (§ Step 2b), which by definition has no row here.
>
> Without it the two halves of the skill contradict each other and the failure is silent:
> `design-infra.md` § 3 decides cost-bearing-ness by asking whether `config` has "a
> SKU/tier/capacity property", and a derived resource whose SKU was dropped because it had
> no row is then **guaranteed to look benign**. That is the precise failure decision 13.1d
> exists to prevent — an unnamed resource silently understating the estate — reintroduced
> from the other end.
>
> Capability run 4 hit exactly this: `azurerm_iothub` has no row, carries
> `sku { name = "S1", capacity = 1 }`, and the run carried the SKU anyway while recording
> that no rule authorised it. It only escaped mattering because the namespace gate fired
> first. On any estate whose derived type lands in a _rubric_ namespace it would have
> understated a cost-bearing resource.
>
> § Step 2a already states the right rule for AzAPI — "extract `sku`, `tier` and `capacity`
> if present and nothing else". This is that rule, generalised.

**If a type below is missing an attribute a mapping table needs, the row is the bug.**
The failure is silent and expensive: the extraction is correct by its own ref, the
inventory passes every shape assertion, and the attribute is simply absent when Design
or Estimate reaches for it. Four rows in this table (Key Vault, Log Analytics, private
endpoints, App Insights) were added after exactly that happened.

| Canonical type                                               | Carry into `config`                                                                                                                                                                                                                    | Why                                                                                                                                                                           |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.Web/serverfarms`                                  | `sku_name`, `worker_count`, `os_type`, `zone_balancing_enabled`                                                                                                                                                                        | the plan is the compute unit and its SKU + instance count is what is being paid for                                                                                           |
| `Microsoft.Web/sites`                                        | `kind`, `service_plan_id`, `runtime_stack`, `app_setting_names`, `https_only`                                                                                                                                                          | `kind` separates web app from function app; the plan link drives the fan-in                                                                                                   |
| `Microsoft.Compute/virtualMachines`                          | `size`, `os_type`, `image_publisher`, `image_offer`, `image_sku`, `zone`, **`os_disk`**                                                                                                                                                | size drives right-sizing; the image drives licensing and the Windows x86 path; `os_disk` is the ROOT VOLUME — see § Inline blocks that are not resources                      |
| `Microsoft.Compute/virtualMachineScaleSets`                  | `sku`, `instances`, `os_type`, `image_*`, **`os_disk`**                                                                                                                                                                                | as above, plus the ASG mapping and the launch template's root volume                                                                                                          |
| `Microsoft.Compute/disks`                                    | `storage_account_type`, `disk_size_gb`, `disk_iops_read_write`                                                                                                                                                                         | the gp3 → io2 breakpoint                                                                                                                                                      |
| `Microsoft.ContainerService/managedClusters`                 | `kubernetes_version`, `default_node_pool` (`vm_size`, `node_count`, `min_count`, `max_count`), `network_plugin`                                                                                                                        | EKS node sizing                                                                                                                                                               |
| `Microsoft.ContainerService/managedClusters/agentPools`      | `vm_size`, `node_count`, `min_count`, `max_count`, `mode` (System/User), `node_taints`                                                                                                                                                 | a separately-declared `azurerm_kubernetes_cluster_node_pool` is a distinct EKS node group; its capacity would otherwise be lost, understating cluster sizing                  |
| `Microsoft.DBforPostgreSQL/flexibleServers` / `...MySQL/...` | `sku_name`, `storage_mb`, `version`, `high_availability`, `zone`, `backup_retention_days`                                                                                                                                              | RDS vs Aurora, and the availability override gate                                                                                                                             |
| `Microsoft.Sql/servers/databases`                            | `sku_name`, `max_size_gb`, `elastic_pool_id`, `zone_redundant`                                                                                                                                                                         | an `elastic_pool_id` routes to the specialist gate                                                                                                                            |
| `Microsoft.DocumentDB/databaseAccounts`                      | `kind`, `capabilities`, `consistency_level`, `throughput`, `geo_locations`                                                                                                                                                             | `kind` + `capabilities` select the per-API target (Core/Mongo/Cassandra/Gremlin/Table)                                                                                        |
| `Microsoft.Cache/Redis`                                      | `sku_name`, `family`, `capacity`, `shard_count`                                                                                                                                                                                        | ElastiCache node sizing                                                                                                                                                       |
| `Microsoft.Storage/storageAccounts`                          | `account_tier`, `account_replication_type`, `account_kind`, `static_website`                                                                                                                                                           | S3 mapping; `static_website` is a `static-site-api` pattern signal                                                                                                            |
| `Microsoft.Storage/.../fileServices/shares`                  | `enabled_protocol`, `quota`                                                                                                                                                                                                            | **the EFS-vs-FSx discriminator** — `NFS` → EFS, `SMB` → FSx for Windows File Server                                                                                           |
| `Microsoft.EventHub/namespaces`                              | `sku`, `capacity`, `kafka_enabled`, `partition_count`                                                                                                                                                                                  | **the MSK-vs-Kinesis discriminator** — `kafka_enabled` → MSK                                                                                                                  |
| `Microsoft.ServiceBus/namespaces`                            | `sku` (Basic/Standard/Premium), `capacity`                                                                                                                                                                                             | Premium is the 100 MB / VNet tier; the SKU bounds message size and routing                                                                                                    |
| `Microsoft.ServiceBus/namespaces/queues`                     | `requires_session`, `max_message_size_in_kilobytes`, `default_message_ttl`, `requires_duplicate_detection`, `duplicate_detection_history_time_window`, `max_delivery_count`                                                            | `requires_session` → SQS FIFO (session id → message group id); the size/TTL/dedup fields drive the SQS vs Amazon MQ vs claim-check eliminators in `messaging.md`              |
| `Microsoft.ServiceBus/namespaces/topics`                     | `requires_duplicate_detection`, `max_message_size_in_kilobytes`, `default_message_ttl`, subscription count                                                                                                                             | a topic with subscriptions is the SNS-vs-EventBridge decision; the same size/TTL boundaries apply as for queues                                                               |
| `Microsoft.CognitiveServices/accounts`                       | `kind`, `sku_name`                                                                                                                                                                                                                     | `kind: OpenAI` is the Azure OpenAI signal, routed to the shared OpenAI→Bedrock guide                                                                                          |
| `Microsoft.CognitiveServices/accounts/deployments`           | `cognitive_account_id`, inline `model` (`format`, `name`, `version`), inline `sku` (`name`, `capacity`)                                                                                                                                | the model name is the IaC-only AI profile's model evidence; the account link establishes Azure OpenAI provenance                                                              |
| `Microsoft.MachineLearningServices/workspaces`               | `sku_name`, `application_insights_id`, `key_vault_id`, `storage_account_id`, `container_registry_id`, `identity` type                                                                                                                  | workspace presence is a strong custom-ML signal; linked infrastructure explains the migration boundary                                                                        |
| `Microsoft.Search/searchServices`                            | `sku`, `replica_count`, `partition_count`, `semantic_search_sku`                                                                                                                                                                       | supporting RAG/search infrastructure; not an AI signal by itself                                                                                                              |
| `Microsoft.Network/virtualNetworks`                          | `address_space`, `dns_servers`                                                                                                                                                                                                         | VPC CIDR planning                                                                                                                                                             |
| `Microsoft.Network/virtualNetworks/subnets`                  | `address_prefixes`, `service_endpoints`, `delegation`                                                                                                                                                                                  | subnet layout; a delegation is a hard placement constraint                                                                                                                    |
| `Microsoft.KeyVault/vaults`                                  | `sku_name`, `purge_protection_enabled`, `soft_delete_retention_days`                                                                                                                                                                   | `sku_name: premium` means HSM-backed keys, which is a KMS custom-key-store decision rather than plain Secrets Manager — and it is a price difference                          |
| `Microsoft.OperationalInsights/workspaces`                   | `sku`, `retention_in_days`, `daily_quota_gb`                                                                                                                                                                                           | the Skip Mapping still needs these: retention and ingest volume are what the CloudWatch Logs fallback costs                                                                   |
| `Microsoft.Insights/components`                              | `application_type`, `workspace_id`                                                                                                                                                                                                     | the report names the app type and the workspace link; `workspace_id` is config, NOT an edge (see `schema-discover-azure.md` § Typed edges)                                    |
| `Microsoft.Network/privateEndpoints`                         | `subresource_names`                                                                                                                                                                                                                    | names WHICH sub-resource is fronted (`postgresqlServer`, `blob`, `vault`), which is what makes the `private_link` edge specific rather than "something connects to something" |
| `Microsoft.Storage/.../blobServices/containers`              | `container_access_type`                                                                                                                                                                                                                | `blob` or `container` means public read, which becomes an S3 public-access-block decision                                                                                     |
| `Microsoft.Network/networkSecurityGroups`                    | inline `security_rule[]` → `config.security_rules[]` (each: `name`, `priority`, `direction`, `access`, `protocol`, `source_port_range(s)`, `destination_port_range(s)`, `source_address_prefix(es)`, `destination_address_prefix(es)`) | the SG ingress/egress rules the target security group is built from — inline blocks with NO address, see § Inline blocks that are not resources                               |
| `Microsoft.App/containerApps`                                | from the inline `template` / `container` blocks: `cpu`, `memory`, `min_replicas`, `max_replicas`, and container `image`                                                                                                                | Fargate/App Runner task sizing + scaling, and the `image` drives platform detect — inline blocks, see § Inline blocks that are not resources                                  |

## Inline blocks that are not resources

Some Azure infrastructure is declared as a **block inside another resource**, not as a
resource of its own. Terraform gives it no address, so there is nothing to iterate and it is
invisible to a `resource`-block walk — which is exactly how it gets lost.

**`os_disk` on a virtual machine or scale set is the case that costs money.**

```hcl
resource "azurerm_windows_virtual_machine" "reporting" {
  size = "Standard_D4s_v5"
  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
  }
}
```

There is no `azurerm_managed_disk` here and therefore no `Microsoft.Compute/disks`
resource — but the VM absolutely has a root volume and it is absolutely billed. Extract the
block into `config.os_disk`, keeping `storage_account_type`, `disk_size_gb` and `caching`.

Design maps it to the instance's **root volume** in `aws_config`, never to a `services[]`
entry of its own (`knowledge/design/disk-ebs-sizing.json` § os_disk_vs_data_disk — counting
it twice is the commonest way a VM estate's storage cost gets inflated).

**When `disk_size_gb` is absent, the size is the image's default and you do not know it.**
Record `disk_size_gb: null` and let Design carry `size_source: "image_default_unstated"`.
Do **not** substitute a number from your own knowledge of Windows or Linux image defaults:
a silently invented 127 GiB is indistinguishable from a measured one, and Estimate would
price it as fact. A stated unknown is worth more than a plausible number.

Capability run 4 found this: the corpus VM's root volume was **entirely absent** from the
design, and the run recorded a prose note because no rule let it do anything better. Every
VM estate was being understated.

**Inline `security_rule {}` blocks on a network security group have no address either, and
MUST be extracted into `config.security_rules[]`.**

```hcl
resource "azurerm_network_security_group" "app" {
  security_rule {
    name                       = "allow-https"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}
```

A `resource`-block walk sees the NSG but not its rules — they are exactly the os_disk case,
one level down. Carry each rule (the fields in the § Per-type row) into
`config.security_rules[]`, because they are what Design turns into the target security
group's ingress/egress. Two neighbours look similar but are NOT the same:
`azurerm_subnet_network_security_group_association` stays **association-only** (13.2d — no
inventory entry, not an untranslated type), while a standalone `azurerm_network_security_rule`
resource is **not its own mapping target**: follow its `network_security_group_id` to the
parent NSG and fold it into that NSG's `config.security_rules[]`, exactly as a child resource
resolves its parent group.

**A Container App's sizing lives in inline `template` / `container` blocks, not on the
resource itself.**

```hcl
resource "azurerm_container_app" "api" {
  template {
    min_replicas = 1
    max_replicas = 10
    container {
      image  = "myregistry.azurecr.io/api:latest"
      cpu    = 0.5
      memory = "1Gi"
    }
  }
}
```

Same caveat as os_disk and security_rule: a resource-only walk records the app but misses its
size and scale entirely. Extract `cpu`, `memory`, `min_replicas`, `max_replicas` and the
container `image` into `config` (the image is what platform detection reads). Without them the
Fargate/App Runner target is sized from defaults rather than from what the customer declared —
the same silent understatement the VM root volume caused.

## Secrets: names only, never values

**This is a hard boundary, and Terraform makes it easy to cross by accident.**

- `app_settings` and `connection_string` blocks: extract **keys only**, into
  `config.app_setting_names` as a sorted array of strings. Never the values.
- `azurerm_key_vault_secret`: inventory the resource, record its `name`, never its
  `value`.
- A literal-looking value anywhere (a connection string, an account key, a password,
  a token) is **discarded**, not recorded and not redacted-in-place — a redacted
  placeholder still tells a reader the field existed and how long it was.
- A `value` that is a Key Vault reference (`@Microsoft.KeyVault(...)`) is retained as
  an **edge** (`secret_ref`), not as a value: the reference is architecture, the
  secret is not.

The phase's postcondition asserts this against the produced artifact, so a slip is a
gate failure rather than a review finding.

## Edges

Terraform expresses relationships as interpolated references, so the edge set comes
from the reference graph rather than from resolved ARM IDs (which the source does not
contain). Resolve each reference to the target's reconstructed `azure_id`.

| Terraform attribute                                                                                        | Edge `type`         | Notes                                                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `service_plan_id` / `app_service_plan_id` on a site                                                        | `hosted_on`         | **The edge that prevents the 5× App Service Plan cost error.** Always extract it.                                                                                                                                                              |
| `subnet_id`, `virtual_network_subnet_id`                                                                   | `network`           | VNet colocation                                                                                                                                                                                                                                |
| `private_service_connection.private_connection_resource_id` on a private endpoint                          | `private_link`      | the app-to-data edge; see below                                                                                                                                                                                                                |
| `@Microsoft.KeyVault(...)` in an app setting, or a `key_vault_id`                                          | `secret_ref`        | value is never recorded, only the reference                                                                                                                                                                                                    |
| a reference to a data resource's `fqdn` / `hostname` / `endpoint` / `.id` from a compute resource's config | `data_ref`          | **the app-to-data edge.** The commonest real form is an app setting interpolating a database or cache address. It is the edge that merges an app and its database when they sit in different resource groups, so dropping it defeats the merge |
| `principal_id` + `scope` on an `azurerm_role_assignment`                                                   | `identity_grant`    | "app X reads storage Y" — cleaner than GCP exposes it                                                                                                                                                                                          |
| `tags` containing `app` or `workload`                                                                      | `declared_affinity` | declared intent when present; tag KEYS are safe to keep verbatim                                                                                                                                                                               |

Set `via` on each edge to the attribute name it came from, so the Clarify assumption
sheet can explain _why_ two resources were called one workload.

**Private endpoints are edge-bearing config sources, not mapping targets.** Inventory
the endpoint (a resource absent from the inventory cannot be reported as skipped), but
also emit the `private_link` edge from the endpoint's _consumer_ to the resource it
fronts, and add one `warnings[]` entry per consumed endpoint naming the edge it
produced. Structurally this is the same case as gcp's `*_app_version` resources.

**Cross-resource-group edges are the important ones.** An app in `rg-app` referencing
a database in `rg-data` is exactly the horizontal-resource-group layout that
resource-group-seeded clustering gets wrong on its own, so the edge is what later
merges them. Never drop an edge because it crosses a group boundary.

## Validation before returning

- [ ] Every entry's `azure_type` is EITHER a row in `arm-type-canonicalization.md` (then
      `azure_type_provenance: "table"`) OR was derived per § Step 2b with its namespace
      corroborated by `namespace_routing` (then `"derived"`). A derived type NOT appearing
      in that file is correct and expected — the file is an exception list, not a coverage list.
- [ ] No entry's `azure_type` starts with `azurerm_`.
- [ ] Every `azure_id` is unique, and matches the standard form (or the resource-group exception).
- [ ] Every entry carries `config.tf_address`, and every `tf_address` is unique.
- [ ] Every site with a `service_plan_id` has a `hosted_on` edge.
- [ ] `config.app_setting_names` contains only strings; no `app_settings` values appear anywhere in the contribution.
- [ ] No `tfstate` file was read.
- [ ] Every `module` block resolved to a local path, to `.terraform/modules/`, or to a `module_not_resolved` warning — none silently ignored.
- [ ] No `*_association` resource produced an inventory entry, and none was reported as an untranslated type.
- [ ] Every unresolvable module and every untranslated type has a `warnings[]` entry.
- [ ] Every warning's `code` is from the closed vocabulary in `schema-discover-azure.md` § Warnings.
- [ ] Every `Microsoft.CognitiveServices/accounts/deployments` entry carries its inline
      `model.format`/`model.name`/`model.version` and `sku.name`/`sku.capacity` when declared;
      model names are routing evidence and are never replaced by deployment names.
- [ ] Every entry whose block sets `sku`, `sku_name`, `tier`, `capacity` or `size` carries it in
      `config` — including derived types with no per-type row. Design's cost-bearing test reads it.
- [ ] Every `Microsoft.Network/networkSecurityGroups` entry whose block declares an inline
      `security_rule` carries those rules in `config.security_rules[]`.
- [ ] Every `Microsoft.App/containerApps` entry carries the `cpu`/`memory`/`min_replicas`/
      `max_replicas`/`image` its inline `template`/`container` blocks declare.
- [ ] No `config` key holds `null` — an attribute the configuration does not set is omitted.
