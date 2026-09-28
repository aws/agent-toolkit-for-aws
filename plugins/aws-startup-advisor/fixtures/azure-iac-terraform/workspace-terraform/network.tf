resource "azurerm_virtual_network" "core" {
  name                = "vnet-${var.prefix}-core"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  address_space       = ["10.20.0.0/16"]
}

resource "azurerm_subnet" "apps" {
  name                 = "snet-apps"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.core.name
  address_prefixes     = ["10.20.1.0/24"]
}

resource "azurerm_subnet" "data" {
  name                 = "snet-data"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.core.name
  address_prefixes     = ["10.20.2.0/24"]
}

resource "azurerm_network_interface" "reporting" {
  name                = "nic-${var.prefix}-reporting"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.apps.id
    private_ip_address_allocation = "Dynamic"
  }
}

# A private endpoint fronting the Postgres server. It is an edge-bearing config
# source, NOT a mapping target: the app-to-data edge comes from its
# private_connection_resource_id, and the endpoint itself is skipped with a warning.
resource "azurerm_private_endpoint" "store" {
  name                = "pe-${var.prefix}-store"
  resource_group_name = azurerm_resource_group.data.name
  location            = azurerm_resource_group.data.location
  subnet_id           = azurerm_subnet.data.id

  private_service_connection {
    name                           = "psc-store"
    is_manual_connection           = false
    private_connection_resource_id = azurerm_postgresql_flexible_server.store.id
    subresource_names              = ["postgresqlServer"]
  }
}

resource "azurerm_key_vault" "main" {
  name                = "kv-${var.prefix}"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  tenant_id           = "00000000-0000-0000-0000-000000000000"
  sku_name            = "standard"
}

# Observability: both land in Skip Mappings with a CloudWatch fallback note,
# but must still be inventoried and translated.
resource "azurerm_log_analytics_workspace" "core" {
  name                = "log-${var.prefix}-core"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_application_insights" "storefront" {
  name                = "appi-${var.prefix}-storefront"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  workspace_id        = azurerm_log_analytics_workspace.core.id
  application_type    = "web"
}
