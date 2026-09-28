# Canonical ARM type vocabulary (`azurerm_*` → `Microsoft.*`)

Every mapping table in this skill keys off an **ARM resource type string**
(`Microsoft.Web/sites`), never a Terraform type. Four of the five discovery sources
— Bicep, ARM templates, live `az`, and RDfA — speak ARM natively. Only Terraform
needs translating, and this file governs that translation. It is applied inside
`discover-iac.md`, so nothing downstream ever sees an `azurerm_*` string.

gcp-to-aws did not face this because it had one IaC dialect and could key tables off
Terraform types directly.

> ## This file is an EXCEPTION LIST, not a coverage list
>
> **[REDESIGNED 2026-09-07.]** It used to try to enumerate the provider surface. That is
> not achievable and was never the right shape: the `azurerm` provider carries past a
> thousand resource types and ships every couple of weeks, so a table chasing completeness
> decays continuously and was at **13%** when this was measured.
>
> Measured against the 132 rows here: **105 (79%) have a resource segment a pattern
> derives**, and 104 of those also have a namespace already declared in
> `fast-path-services.json` → `namespace_routing`. So four fifths of the file was
> restating a rule. Only **27 rows carry information a pattern cannot produce** — and
> those are the traps below plus a handful more.
>
> So the default path is **derivation** (§ Deriving a type that is not listed), and the
> table's job is to hold the cases where derivation would be **wrong**.
>
> This is the same selection rule the fixture oracles already use — _pin only facts where
> a plausible improvisation and the correct answer diverge_ — applied to the table for the
> first time.
>
> **The derivable rows present today are a CLOSED CORE.** They are verified and cost
> nothing at runtime, so they stay. But adding another derivable row means the file is
> growing toward completeness again. **The count of derivable rows is capped and must never
> rise** — see § Admission test for what makes a row admissible.
>
> **`azapi_resource` does not use this table.** The AzAPI provider states the canonical
> ARM type in its own `type` argument (`Microsoft.Consumption/budgets@2023-05-01`), so
> there is nothing to translate and no row to add. See `extract-terraform.md`
> § Step 2a. Do not add `azapi_*` names here — a row for them would never be consulted,
> and its presence would imply the translation is needed.

## Rules

1. **A listed type is authoritative; an unlisted type is DERIVED, never dropped.** Check
   this table FIRST — that ordering is what makes derivation safe, because the cases where
   a guess goes wrong are enumerated here (§ Traps). A type absent from the table is
   resolved by § Deriving a type that is not listed, and the resource keeps its place in
   `resources[]` with `azure_type_provenance: "derived"`. It is **not** silently dropped:
   dropping it was what made 87% of the provider surface a hard stop and what forced Design
   to treat every unnamed resource as cost-bearing by default.
2. **Matching folds case; emission follows this file.** ARM compares resource type
   strings case-insensitively, so every lookup in this skill — fast-path, Skip
   Mappings, `index.md` routing, rubric selection — MUST fold case before comparing.
   A mis-cased type must never fall through to the unknown-type policy. Emit the
   spelling used in this file, which is a **convention** adopted so `azure_id` strings
   join by exact match — not a claim about ARM. See § Casing is a convention, not a fact.
3. **Child types keep their full path.** `Microsoft.Sql/servers/databases` is three
   segments, and it is not interchangeable with `Microsoft.Sql/servers`.
4. **Deprecated provider names are listed alongside their replacements.** A real
   repository may carry either; both translate to the same ARM type.

## Traps

These are the rows where a plausible guess and the correct answer diverge. They are
the reason this file exists rather than relying on the pattern.

| Trap                                                                                                                                                                        | Wrong                                                 | Right                                    |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------- |
| **Function apps are not their own type.** `Microsoft.Web/functionApps` does not exist. A function app is a `sites` resource with `kind` containing `functionapp`.           | `Microsoft.Web/functionApps`                          | `Microsoft.Web/sites`                    |
| **`serverFarmId` is a property, not a type name.** The camelCase `serverFarmId` on a site is the pointer _to_ its plan; the plan's own type is `Microsoft.Web/serverfarms`. | `serverFarmId` used as a type                         | `Microsoft.Web/serverfarms`              |
| **Cosmos DB's provider is `DocumentDB`.** The product was renamed; the ARM provider never was.                                                                              | `Microsoft.CosmosDB/accounts`                         | `Microsoft.DocumentDB/databaseAccounts`  |
| **Azure OpenAI has no provider of its own.** It is a Cognitive Services account whose `kind` is `OpenAI`.                                                                   | `Microsoft.OpenAI/accounts`                           | `Microsoft.CognitiveServices/accounts`   |
| **A resource group's own ID has no `/providers/` segment.** See § Reconstructing `azure_id`.                                                                                | `.../providers/Microsoft.Resources/resourceGroups/rg` | `/subscriptions/<sub>/resourceGroups/rg` |

`kind` is therefore load-bearing, not decoration: it is the only thing separating a
web app from a function app, and a Cognitive Services account from Azure OpenAI.
`discover-iac.md` must carry it into `config.kind` for every `Microsoft.Web/sites`
and `Microsoft.CognitiveServices/accounts` entry.

## Compute

| Terraform type                                                                                                                                                                             | Canonical ARM type                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| `azurerm_linux_web_app`, `azurerm_windows_web_app`, `azurerm_app_service` (deprecated)                                                                                                     | `Microsoft.Web/sites`                                   |
| `azurerm_linux_function_app`, `azurerm_windows_function_app`, `azurerm_function_app` (deprecated)                                                                                          | `Microsoft.Web/sites` (`kind` contains `functionapp`)   |
| `azurerm_linux_web_app_slot`, `azurerm_windows_web_app_slot`                                                                                                                               | `Microsoft.Web/sites/slots`                             |
| `azurerm_service_plan`, `azurerm_app_service_plan` (deprecated)                                                                                                                            | `Microsoft.Web/serverfarms`                             |
| `azurerm_static_site`                                                                                                                                                                      | `Microsoft.Web/staticSites`                             |
| `azurerm_linux_virtual_machine`, `azurerm_windows_virtual_machine`, `azurerm_virtual_machine` (deprecated)                                                                                 | `Microsoft.Compute/virtualMachines`                     |
| `azurerm_linux_virtual_machine_scale_set`, `azurerm_windows_virtual_machine_scale_set`, `azurerm_orchestrated_virtual_machine_scale_set`, `azurerm_virtual_machine_scale_set` (deprecated) | `Microsoft.Compute/virtualMachineScaleSets`             |
| `azurerm_managed_disk`                                                                                                                                                                     | `Microsoft.Compute/disks`                               |
| `azurerm_availability_set`                                                                                                                                                                 | `Microsoft.Compute/availabilitySets`                    |
| `azurerm_kubernetes_cluster`                                                                                                                                                               | `Microsoft.ContainerService/managedClusters`            |
| `azurerm_kubernetes_cluster_node_pool`                                                                                                                                                     | `Microsoft.ContainerService/managedClusters/agentPools` |
| `azurerm_container_registry`                                                                                                                                                               | `Microsoft.ContainerRegistry/registries`                |
| `azurerm_container_app`                                                                                                                                                                    | `Microsoft.App/containerApps`                           |
| `azurerm_container_app_environment`                                                                                                                                                        | `Microsoft.App/managedEnvironments`                     |
| `azurerm_container_group`                                                                                                                                                                  | `Microsoft.ContainerInstance/containerGroups`           |
| `azurerm_virtual_machine_extension`                                                                                                                                                        | `Microsoft.Compute/virtualMachines/extensions`          |
| `azurerm_snapshot`                                                                                                                                                                         | `Microsoft.Compute/snapshots`                           |
| `azurerm_image`                                                                                                                                                                            | `Microsoft.Compute/images`                              |
| `azurerm_shared_image_gallery`                                                                                                                                                             | `Microsoft.Compute/galleries`                           |
| `azurerm_shared_image`                                                                                                                                                                     | `Microsoft.Compute/galleries/images`                    |
| `azurerm_proximity_placement_group`                                                                                                                                                        | `Microsoft.Compute/proximityPlacementGroups`            |

## Data

| Terraform type                                         | Canonical ARM type                                              |
| ------------------------------------------------------ | --------------------------------------------------------------- |
| `azurerm_postgresql_flexible_server`                   | `Microsoft.DBforPostgreSQL/flexibleServers`                     |
| `azurerm_postgresql_server` (deprecated Single Server) | `Microsoft.DBforPostgreSQL/servers`                             |
| `azurerm_mysql_flexible_server`                        | `Microsoft.DBforMySQL/flexibleServers`                          |
| `azurerm_mysql_server` (deprecated Single Server)      | `Microsoft.DBforMySQL/servers`                                  |
| `azurerm_mssql_server`                                 | `Microsoft.Sql/servers`                                         |
| `azurerm_mssql_database`                               | `Microsoft.Sql/servers/databases`                               |
| `azurerm_mssql_elasticpool`                            | `Microsoft.Sql/servers/elasticPools`                            |
| `azurerm_mssql_managed_instance`                       | `Microsoft.Sql/managedInstances`                                |
| `azurerm_cosmosdb_account`                             | `Microsoft.DocumentDB/databaseAccounts`                         |
| `azurerm_redis_cache`                                  | `Microsoft.Cache/Redis`                                         |
| `azurerm_redis_enterprise_cluster`                     | `Microsoft.Cache/redisEnterprise`                               |
| `azurerm_storage_account`                              | `Microsoft.Storage/storageAccounts`                             |
| `azurerm_storage_container`                            | `Microsoft.Storage/storageAccounts/blobServices/containers`     |
| `azurerm_storage_share`                                | `Microsoft.Storage/storageAccounts/fileServices/shares`         |
| `azurerm_storage_queue`                                | `Microsoft.Storage/storageAccounts/queueServices/queues`        |
| `azurerm_storage_table`                                | `Microsoft.Storage/storageAccounts/tableServices/tables`        |
| `azurerm_storage_management_policy`                    | `Microsoft.Storage/storageAccounts/managementPolicies`          |
| `azurerm_postgresql_flexible_server_database`          | `Microsoft.DBforPostgreSQL/flexibleServers/databases`           |
| `azurerm_postgresql_flexible_server_firewall_rule`     | `Microsoft.DBforPostgreSQL/flexibleServers/firewallRules`       |
| `azurerm_mysql_flexible_database`                      | `Microsoft.DBforMySQL/flexibleServers/databases`                |
| `azurerm_mssql_firewall_rule`                          | `Microsoft.Sql/servers/firewallRules`                           |
| `azurerm_cosmosdb_sql_database`                        | `Microsoft.DocumentDB/databaseAccounts/sqlDatabases`            |
| `azurerm_cosmosdb_sql_container`                       | `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers` |
| `azurerm_cosmosdb_mongo_database`                      | `Microsoft.DocumentDB/databaseAccounts/mongodbDatabases`        |
| `azurerm_cosmosdb_cassandra_keyspace`                  | `Microsoft.DocumentDB/databaseAccounts/cassandraKeyspaces`      |
| `azurerm_app_configuration`                            | `Microsoft.AppConfiguration/configurationStores`                |
| `azurerm_recovery_services_vault`                      | `Microsoft.RecoveryServices/vaults`                             |
| `azurerm_backup_policy_vm`                             | `Microsoft.RecoveryServices/vaults/backupPolicies`              |

Note that `azurerm_storage_share` is what makes the Azure Files → EFS-or-FSx routing
decision reachable: its `enabled_protocol` (`SMB` or `NFS`) is the discriminator, so
carry it into `config.enabled_protocol`.

## Networking

| Terraform type                                                                                                         | Canonical ARM type                                                                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `azurerm_virtual_network`                                                                                              | `Microsoft.Network/virtualNetworks`                                                                                                                          |
| `azurerm_subnet`                                                                                                       | `Microsoft.Network/virtualNetworks/subnets`                                                                                                                  |
| `azurerm_network_security_group`                                                                                       | `Microsoft.Network/networkSecurityGroups`                                                                                                                    |
| `azurerm_network_interface`                                                                                            | `Microsoft.Network/networkInterfaces`                                                                                                                        |
| `azurerm_public_ip`                                                                                                    | `Microsoft.Network/publicIPAddresses`                                                                                                                        |
| `azurerm_lb`                                                                                                           | `Microsoft.Network/loadBalancers`                                                                                                                            |
| `azurerm_application_gateway`                                                                                          | `Microsoft.Network/applicationGateways`                                                                                                                      |
| `azurerm_nat_gateway`                                                                                                  | `Microsoft.Network/natGateways`                                                                                                                              |
| `azurerm_dns_zone`                                                                                                     | `Microsoft.Network/dnsZones`                                                                                                                                 |
| `azurerm_private_dns_zone`                                                                                             | `Microsoft.Network/privateDnsZones`                                                                                                                          |
| `azurerm_private_endpoint`                                                                                             | `Microsoft.Network/privateEndpoints`                                                                                                                         |
| `azurerm_cdn_frontdoor_profile`                                                                                        | `Microsoft.Cdn/profiles`                                                                                                                                     |
| `azurerm_frontdoor` (deprecated)                                                                                       | `Microsoft.Network/frontDoors`                                                                                                                               |
| `azurerm_route_table`                                                                                                  | `Microsoft.Network/routeTables`                                                                                                                              |
| `azurerm_route`                                                                                                        | `Microsoft.Network/routeTables/routes`                                                                                                                       |
| `azurerm_virtual_network_peering`                                                                                      | `Microsoft.Network/virtualNetworks/virtualNetworkPeerings`                                                                                                   |
| `azurerm_firewall`                                                                                                     | `Microsoft.Network/azureFirewalls`                                                                                                                           |
| `azurerm_firewall_policy`                                                                                              | `Microsoft.Network/firewallPolicies`                                                                                                                         |
| `azurerm_bastion_host`                                                                                                 | `Microsoft.Network/bastionHosts`                                                                                                                             |
| `azurerm_network_security_rule`                                                                                        | `Microsoft.Network/networkSecurityGroups/securityRules`                                                                                                      |
| `azurerm_lb_backend_address_pool`                                                                                      | `Microsoft.Network/loadBalancers/backendAddressPools`                                                                                                        |
| `azurerm_lb_probe`                                                                                                     | `Microsoft.Network/loadBalancers/probes`                                                                                                                     |
| `azurerm_lb_rule`                                                                                                      | `Microsoft.Network/loadBalancers/loadBalancingRules`                                                                                                         |
| `azurerm_private_dns_zone_virtual_network_link`                                                                        | `Microsoft.Network/privateDnsZones/virtualNetworkLinks`                                                                                                      |
| `azurerm_dns_a_record`, `azurerm_dns_cname_record`, and the other `azurerm_dns_*_record` types                         | `Microsoft.Network/dnsZones/<RECORDTYPE>`, the record type taken from the Terraform type name (`/A`, `/CNAME`, `/TXT`) — this row is a pattern, not a lookup |
| `azurerm_cdn_endpoint`                                                                                                 | `Microsoft.Cdn/profiles/endpoints`                                                                                                                           |
| `azurerm_cdn_frontdoor_endpoint`                                                                                       | `Microsoft.Cdn/profiles/afdEndpoints`                                                                                                                        |
| `azurerm_web_application_firewall_policy`                                                                              | `Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies`                                                                                         |
| `azurerm_traffic_manager_profile`                                                                                      | `Microsoft.Network/trafficManagerProfiles`                                                                                                                   |
| `azurerm_nat_gateway_public_ip_association`, `azurerm_subnet_route_table_association`, and every other `*_association` | **no type of its own** — see § Association-only resources                                                                                                    |

## Identity, secrets, messaging

| Terraform type                                                                                                    | Canonical ARM type                                                              |
| ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `azurerm_key_vault`                                                                                               | `Microsoft.KeyVault/vaults`                                                     |
| `azurerm_key_vault_secret`                                                                                        | `Microsoft.KeyVault/vaults/secrets`                                             |
| `azurerm_user_assigned_identity`                                                                                  | `Microsoft.ManagedIdentity/userAssignedIdentities`                              |
| `azurerm_role_assignment`                                                                                         | `Microsoft.Authorization/roleAssignments`                                       |
| `azurerm_servicebus_namespace`                                                                                    | `Microsoft.ServiceBus/namespaces`                                               |
| `azurerm_servicebus_queue`                                                                                        | `Microsoft.ServiceBus/namespaces/queues`                                        |
| `azurerm_servicebus_topic`                                                                                        | `Microsoft.ServiceBus/namespaces/topics`                                        |
| `azurerm_eventhub_namespace`                                                                                      | `Microsoft.EventHub/namespaces`                                                 |
| `azurerm_eventhub`                                                                                                | `Microsoft.EventHub/namespaces/eventhubs`                                       |
| `azurerm_api_management`                                                                                          | `Microsoft.ApiManagement/service`                                               |
| `azurerm_signalr_service`                                                                                         | `Microsoft.SignalRService/SignalR`                                              |
| `azurerm_key_vault_key`                                                                                           | `Microsoft.KeyVault/vaults/keys`                                                |
| `azurerm_key_vault_certificate`                                                                                   | `Microsoft.KeyVault/vaults/certificates`                                        |
| `azurerm_federated_identity_credential`                                                                           | `Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials` |
| `azurerm_servicebus_subscription`                                                                                 | `Microsoft.ServiceBus/namespaces/topics/subscriptions`                          |
| `azurerm_eventhub_consumer_group`                                                                                 | `Microsoft.EventHub/namespaces/eventhubs/consumergroups`                        |
| `azurerm_eventhub_authorization_rule`                                                                             | `Microsoft.EventHub/namespaces/eventhubs/authorizationRules`                    |
| `azurerm_eventgrid_topic`                                                                                         | `Microsoft.EventGrid/topics`                                                    |
| `azurerm_eventgrid_system_topic`                                                                                  | `Microsoft.EventGrid/systemTopics`                                              |
| `azurerm_eventgrid_event_subscription`                                                                            | `Microsoft.EventGrid/eventSubscriptions`                                        |
| `azurerm_logic_app_workflow`                                                                                      | `Microsoft.Logic/workflows`                                                     |
| `azurerm_management_lock`                                                                                         | `Microsoft.Authorization/locks`                                                 |
| `azurerm_policy_assignment`, `azurerm_resource_group_policy_assignment`, `azurerm_subscription_policy_assignment` | `Microsoft.Authorization/policyAssignments`                                     |

`azurerm_eventhub_namespace`'s `kafka_enabled` attribute is what the Event Hubs
rubric keys off (Kafka-protocol consumers → MSK, native AMQP/SDK → Kinesis), so carry
it into `config.kafka_enabled`.

## Observability, AI, analytics

| Terraform type                          | Canonical ARM type                                                          |
| --------------------------------------- | --------------------------------------------------------------------------- |
| `azurerm_application_insights`          | `Microsoft.Insights/components`                                             |
| `azurerm_log_analytics_workspace`       | `Microsoft.OperationalInsights/workspaces`                                  |
| `azurerm_monitor_diagnostic_setting`    | `Microsoft.Insights/diagnosticSettings`                                     |
| `azurerm_monitor_action_group`          | `Microsoft.Insights/actionGroups`                                           |
| `azurerm_monitor_metric_alert`          | `Microsoft.Insights/metricAlerts`                                           |
| `azurerm_cognitive_account`             | `Microsoft.CognitiveServices/accounts` (`kind` = `OpenAI` for Azure OpenAI) |
| `azurerm_cognitive_deployment`          | `Microsoft.CognitiveServices/accounts/deployments`                          |
| `azurerm_search_service`                | `Microsoft.Search/searchServices`                                           |
| `azurerm_data_factory`                  | `Microsoft.DataFactory/factories`                                           |
| `azurerm_synapse_workspace`             | `Microsoft.Synapse/workspaces`                                              |
| `azurerm_databricks_workspace`          | `Microsoft.Databricks/workspaces`                                           |
| `azurerm_monitor_autoscale_setting`     | `Microsoft.Insights/autoscaleSettings`                                      |
| `azurerm_application_insights_web_test` | `Microsoft.Insights/webtests`                                               |
| `azurerm_monitor_data_collection_rule`  | `Microsoft.Insights/dataCollectionRules`                                    |
| `azurerm_monitor_diagnostic_categories` | (data source, not a resource — no entry)                                    |
| `azurerm_batch_account`                 | `Microsoft.Batch/batchAccounts`                                             |
| `azurerm_machine_learning_workspace`    | `Microsoft.MachineLearningServices/workspaces`                              |
| `azurerm_stream_analytics_job`          | `Microsoft.StreamAnalytics/streamingjobs`                                   |
| `azurerm_dev_test_lab`                  | `Microsoft.DevTestLab/labs`                                                 |

Everything in the observability block lands in Skip Mappings — observability is
re-established on the target rather than migrated, with a CloudWatch fallback note.
They are still translated and inventoried, because `Microsoft.Insights/components`
carries an `application_type` and a workspace link that the report should mention,
and because a resource absent from the inventory cannot be reported as skipped.

## Resource groups

| Terraform type           | Canonical ARM type                   |
| ------------------------ | ------------------------------------ |
| `azurerm_resource_group` | `Microsoft.Resources/resourceGroups` |

## Association-only resources

A whole class of `azurerm_*` resources exists **only in Terraform** and has no ARM type
at all. They set one property on one of the two resources they join, because Terraform
needs a separate addressable resource where ARM has a field:

`azurerm_subnet_network_security_group_association` · `azurerm_subnet_route_table_association` ·
`azurerm_network_interface_security_group_association` ·
`azurerm_network_interface_backend_address_pool_association` ·
`azurerm_nat_gateway_public_ip_association` · `azurerm_subnet_nat_gateway_association` ·
`azurerm_app_service_virtual_network_swift_connection` ·
`azurerm_key_vault_access_policy` · `azurerm_role_assignment` (see note)

**Rule: emit no inventory entry. Emit an EDGE.** Read the two IDs the association joins
and record the relationship on the appropriate resource per
`schema-discover-azure.md` § Typed edges — an NSG association is a `network` edge, a
Key Vault access policy is a `secret_ref` or `identity_grant`.

**Do NOT report these as untranslated types.** That is the trap: the untranslated
warning means "this skill has a gap", and an association is not a gap — it is a
Terraform-shaped thing that correctly has no ARM type. Filing them as untranslated
would bury the real gaps in noise, and on an IaC-heavy repo the associations outnumber
the genuinely-missing types. `azurerm_role_assignment` is the one borderline case: it
_does_ have an ARM type (`Microsoft.Authorization/roleAssignments`, a Skip Mapping), so
it gets an entry AND contributes its `identity_grant` edge.

## Casing is a convention, not a fact

Two of this file's original traps made casing a correctness axis — a capital `R` in
`Microsoft.Cache/Redis`, and all-lowercase `serverfarms`. Both were unsourced, and the
second is unsourceable: `Azure/bicep-types-az` ships **both** `Microsoft.Web/serverFarms`
and `Microsoft.Web/serverfarms` in one generated index. For the cache type, that index
and `magodo/aztft` — the mapping library behind Microsoft's supported
`Azure/aztfexport` — both render `Microsoft.Cache/redis`. The capital-R form is what
appears in **azurerm resource IDs**, which is a Terraform-provider artifact, not an ARM
type. Nine of this file's 124 externally checkable rows differ from `aztft` by casing
alone, so the discipline this file claimed to enforce was wrong about 7% of its own
content.

**Fold case to look up. Emit this file's spelling.** The spelling matters for exactly
one reason: `azure_id` strings are compared by exact match — cluster membership,
cluster keys, and the drift comparison against a live capture all require two
references to one resource to produce one string. It does not matter to ARM, and a
mis-cased type is a convention violation, never evidence that the translation was
guessed.

## Deriving a type that is not listed

The default path. Two halves with very different reliability, and the asymmetry is what
makes this safe rather than a guess.

### Step 1 — the resource segment, by pattern

Strip `azurerm_`, then convert the remainder from `snake_case` to `lowerCamelCase` and
pluralise it. Where the leading noun duplicates the parent type, drop it and derive from
the tail (`virtual_network_peering` under `virtualNetworks` → `virtualNetworkPeerings`).

This is mechanical and it accounts for 79% of the rows already in this file, so it is not
a hopeful heuristic — it is the rule the table was mostly restating.

### Step 2 — the namespace, from knowledge, then CROSS-CHECKED

The provider namespace is **not** derivable from the Terraform name: nothing in
`firewall_policy` says `Microsoft.Network`. Supply it, then **verify it against
`fast-path-services.json` → `namespace_routing`**, which declares 54 namespaces
independently of this file.

| Outcome                                     | Action                                                                                                                                                                                                                                                           |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Namespace **is** in `namespace_routing`     | An independent artefact corroborates it. `azure_type_provenance: "derived"`                                                                                                                                                                                      |
| Namespace is **not** in `namespace_routing` | **Still accept it.** `azure_type_provenance: "derived_uncorroborated"`, plus a `type_derived_uncorroborated` warning naming the namespace. Design routes it to a model-chosen category (`fast-path-services.json` → `namespace_routing._unrecognised_namespace`) |

Either way the resource keeps its place in `resources[]` with its full `config`, and the
Terraform type goes into `iac_metadata.derived_types`.

**The cross-check is a SIGNAL, not a veto.** It records whether a second artefact agreed;
it does not decide whether the resource exists. `Microsoft.Maps/accounts` is unambiguous
and `Microsoft.Maps` is not in the 55-entry list — vetoing it would be refusing to name a
thing the skill can name perfectly well.

`iac_metadata.untranslated_types` is therefore for one case only: **you cannot say what
the service is at all.** That is a real answer, it is rare, and it is the only route to a
halt from this file. A type you can name is never untranslated.

### What a derived type may NOT do

- **Never `confidence: deterministic`.** That tier requires a `direct_mappings` row and a
  `fast_path_row` naming it. A derived type reaching a `direct_mappings` key by luck still
  carries `inferred`, because the type itself was not verified.
- **Never a silent guess.** Every derived type is recorded in `iac_metadata.derived_types`
  with its provenance, and an uncorroborated namespace additionally warns. Deriving is
  allowed; deriving invisibly is not — the whole reason this is safe is that a reviewer can
  see which types were looked up and which were reasoned about.
- **Never overwrite a listed row.** The table is checked first, always.
- **Never invented for an `azapi_resource`** — those carry the ARM type verbatim and skip
  this whole section (§ Step 2a in `extract-terraform.md`).

## Admission test

A new row is admissible **only if derivation would produce the wrong answer.** In practice
that means one of:

- the resource segment is not a camelCase pluralisation of the Terraform suffix
  (`application_insights` → `components`, `lb` → `loadBalancers`, `api_management` →
  `service`)
- several Terraform types collapse onto one ARM type (`linux_web_app`,
  `windows_web_app`, `app_service` → `Microsoft.Web/sites`)
- the child path is not what the name suggests (`cdn_frontdoor_endpoint` →
  `profiles/afdEndpoints`)
- the namespace is one `namespace_routing` does not carry, so the cross-check would stop

**Do NOT add a row because a type is missing.** A missing type is derived, and derivation
is the design rather than a fallback. Adding derivable rows is how this file got to 132 rows
of which 104 were redundant.

**The rule, stated here because this is where it belongs:** the number of rows whose
resource segment a pattern already derives is **capped at its current level and must only
ever fall**. A row that restates the pattern is not admissible; a row that records a
divergence always is. CI enforces this, but the rule is normative whether or not anything
checks it.

If a derived type turns out **wrong** in a real run, that is exactly what a row is for:
add it, with the wrong answer recorded next to the right one, the way § Traps does.

## Reconstructing `azure_id`

Terraform source does not contain ARM resource IDs, so Terraform-sourced entries
have theirs built. Every other source supplies it directly and must never have it
rebuilt.

**Standard form** — one provider segment, then type/name pairs:

```
/subscriptions/<subscriptionId>/resourceGroups/<rg>/providers/<Provider>/<type>/<name>
```

**Child resources** append further type/name pairs to the parent's path, and the
provider appears exactly once:

```
/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Sql/servers/<server>/databases/<db>
/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/sites/<site>/slots/<slot>
```

**A storage account's four sub-services are implicit singletons named `default`.** The
Terraform resource carries no name for that segment — there is only ever one — so the
literal `default` has to be supplied when the ID is built, and it is easy to omit
because nothing in the source hints at it:

```
/…/Microsoft.Storage/storageAccounts/<acct>/blobServices/default/containers/<name>
/…/Microsoft.Storage/storageAccounts/<acct>/fileServices/default/shares/<name>
/…/Microsoft.Storage/storageAccounts/<acct>/queueServices/default/queues/<name>
/…/Microsoft.Storage/storageAccounts/<acct>/tableServices/default/tables/<name>
```

The canonical **type** strings in the tables above deliberately omit `default` — a type
has no instance names in it. Only the **ID** carries it.

**A resource group is the exception** — its own ID carries no `/providers/` segment
at all, even though its canonical type is `Microsoft.Resources/resourceGroups`:

```
/subscriptions/<sub>/resourceGroups/<rg>
```

When the subscription id is not present in the Terraform (the common case — it comes
from the provider block, a variable, or the environment), use the literal placeholder
`<subscription-unknown>` in that position and set
`iac_metadata.subscription_id_source: "unresolved"` — **`iac_metadata`, not
`metadata`**. It belongs there because it is an IaC-specific fact: only Terraform needs
the ID reconstructed at all, so only the IaC section has anything to say about where the
subscription half came from. Do **not** invent a GUID: a fabricated
subscription id makes `azure_id` non-unique across two runs of the same repo and
breaks the drift comparison against a live capture, which is the one thing the ID
exists to support.
