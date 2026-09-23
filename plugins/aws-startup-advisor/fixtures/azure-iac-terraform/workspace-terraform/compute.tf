# --- ONE App Service Plan, FIVE apps on it. ---
# The 5x cost trap: a naive per-app mapping emits five compute line items.
# The plan carries the SKU and worker_count; the apps share its capacity.
resource "azurerm_service_plan" "web" {
  name                = "asp-${var.prefix}-web"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  os_type             = "Linux"
  sku_name            = "S1"
  worker_count        = 2
}

resource "azurerm_linux_web_app" "storefront" {
  name                = "app-${var.prefix}-storefront"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  service_plan_id     = azurerm_service_plan.web.id
  https_only          = true

  site_config { application_stack { node_version = "20-lts" } }

  app_settings = {
    # Value must NEVER reach the inventory. Name must.
    "DATABASE_URL"        = "postgres://FIXTURE_SENTINEL_MUST_NOT_APPEAR@example.invalid/store"
    "STRIPE_SECRET_KEY"   = "FIXTURE_SENTINEL_MUST_NOT_APPEAR"
    "CACHE_ENDPOINT"      = azurerm_redis_cache.session.hostname
    # A real reference to the database, which lives in a DIFFERENT resource group.
    # This is the app-to-data edge that later merges rg-app and rg-data into one
    # cluster. Without it the horizontal-RG case is not actually expressed.
    "DATABASE_HOST"       = azurerm_postgresql_flexible_server.store.fqdn
    "VAULT_TOKEN"         = "@Microsoft.KeyVault(SecretUri=https://kv-contoso.vault.azure.net/secrets/api-token/)"
  }
}

resource "azurerm_linux_web_app" "admin" {
  name                = "app-${var.prefix}-admin"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  service_plan_id     = azurerm_service_plan.web.id
  site_config {}
}

resource "azurerm_linux_web_app" "checkout" {
  name                = "app-${var.prefix}-checkout"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  service_plan_id     = azurerm_service_plan.web.id
  site_config {}
}

resource "azurerm_linux_web_app" "docs" {
  name                = "app-${var.prefix}-docs"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  service_plan_id     = azurerm_service_plan.web.id
  site_config {}
}

resource "azurerm_linux_web_app" "webhooks" {
  name                = "app-${var.prefix}-webhooks"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  service_plan_id     = azurerm_service_plan.web.id
  site_config {}
}

# --- A function app. Pins Microsoft.Web/sites + kind, NOT Microsoft.Web/functionApps. ---
resource "azurerm_service_plan" "func" {
  name                = "asp-${var.prefix}-func"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  os_type             = "Linux"
  sku_name            = "Y1"
  worker_count        = 1
}

resource "azurerm_linux_function_app" "imageresize" {
  name                       = "func-${var.prefix}-imageresize"
  resource_group_name        = azurerm_resource_group.app.name
  location                   = azurerm_resource_group.app.location
  service_plan_id            = azurerm_service_plan.func.id
  storage_account_name       = azurerm_storage_account.assets.name
  storage_account_access_key = azurerm_storage_account.assets.primary_access_key
  site_config {}
}

# --- An IDLE plan: zero apps. Pins the cost-optimization finding. ---
resource "azurerm_service_plan" "legacy" {
  name                = "asp-${var.prefix}-legacy"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  os_type             = "Windows"
  sku_name            = "P1v3"
  worker_count        = 1
}

# --- A Windows VM in rg-shared, unrelated to everything else. ---
# Pins the split (no edges to the legacy plan) and the licensing gate.
resource "azurerm_windows_virtual_machine" "reporting" {
  name                = "vm-${var.prefix}-reporting"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  size                = "Standard_D4s_v5"
  admin_username      = "azureuser"
  admin_password      = "FIXTURE_SENTINEL_MUST_NOT_APPEAR"
  network_interface_ids = [azurerm_network_interface.reporting.id]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
  }

  source_image_reference {
    publisher = "MicrosoftWindowsServer"
    offer     = "WindowsServer"
    sku       = "2022-datacenter-azure-edition"
    version   = "latest"
  }
}
