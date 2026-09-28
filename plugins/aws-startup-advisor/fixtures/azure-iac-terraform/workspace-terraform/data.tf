# --- Database in rg-data while its app is in rg-app. ---
# The cross-RG edge is what later merges them into one cluster; RG-seeded
# clustering alone would leave them apart.
resource "azurerm_postgresql_flexible_server" "store" {
  name                   = "pg-${var.prefix}-store"
  resource_group_name    = azurerm_resource_group.data.name
  location               = azurerm_resource_group.data.location
  version                = "16"
  sku_name               = "GP_Standard_D2s_v3"
  storage_mb             = 65536
  backup_retention_days  = 14
  zone                   = "1"

  high_availability {
    mode                      = "ZoneRedundant"
    standby_availability_zone = "2"
  }
}

# Redis: pins the ElastiCache direct mapping and the sku/family/capacity carry-through.
resource "azurerm_redis_cache" "session" {
  name                = "redis-${var.prefix}-session"
  resource_group_name = azurerm_resource_group.data.name
  location            = azurerm_resource_group.data.location
  sku_name            = "Standard"
  family              = "C"
  capacity            = 1
}

# Cosmos with the Mongo capability: pins per-API routing (Mongo -> DocumentDB,
# NOT DynamoDB) and the Microsoft.DocumentDB provider name.
resource "azurerm_cosmosdb_account" "catalog" {
  name                = "cosmos-${var.prefix}-catalog"
  resource_group_name = azurerm_resource_group.data.name
  location            = azurerm_resource_group.data.location
  offer_type          = "Standard"
  kind                = "MongoDB"

  capabilities { name = "EnableMongo" }

  consistency_policy { consistency_level = "Session" }

  geo_location {
    location          = "westeurope"
    failover_priority = 0
  }
}

resource "azurerm_storage_account" "assets" {
  name                     = "st${var.prefix}assets"
  resource_group_name      = azurerm_resource_group.app.name
  location                 = azurerm_resource_group.app.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  static_website {
    index_document = "index.html"
  }
}

# An SMB file share: pins the EFS-vs-FSx discriminator (SMB -> FSx).
resource "azurerm_storage_share" "reports" {
  name               = "reports"
  storage_account_id = azurerm_storage_account.assets.id
  quota              = 512
  enabled_protocol   = "SMB"
}

# Event Hubs with Kafka enabled: pins the MSK-vs-Kinesis discriminator.
resource "azurerm_eventhub_namespace" "telemetry" {
  name                = "evhns-${var.prefix}-telemetry"
  resource_group_name = azurerm_resource_group.data.name
  location            = azurerm_resource_group.data.location
  sku                 = "Standard"
  capacity            = 2
  kafka_enabled       = true
}
