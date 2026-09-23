# Synthetic Azure estate. Every block here exists to pin one decision the skill
# must make from a table rather than from a plausible guess. See ../README.md.

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}

provider "azurerm" {
  features {}
  # Deliberately no subscription_id: it comes from ARM_SUBSCRIPTION_ID in the
  # environment. Pins the <subscription-unknown> placeholder rule.
}

variable "prefix" {
  type    = string
  default = "contoso"
}

# --- Horizontal resource-group layout: app and data deliberately separated. ---
# Pins the cross-RG edge that later merges them into one cluster.
resource "azurerm_resource_group" "app" {
  name     = "rg-app"
  location = "westeurope"
}

resource "azurerm_resource_group" "data" {
  name     = "rg-data"
  location = "westeurope"
}

# rg-shared holds two UNRELATED workloads with no edges between them.
# Pins the split.
resource "azurerm_resource_group" "shared" {
  name     = "rg-shared"
  location = "westeurope"
}

# A registry module whose source IS on disk under .terraform/modules/. Its two resources
# must be discovered, each carrying config.tf_module. Contrast module "cdn" in
# unsupported.tf, whose source is NOT on disk and which must warn instead.
module "naming" {
  source              = "Azure/naming/azurerm"
  version             = "0.4.0"
  resource_group_name = azurerm_resource_group.app.name
}

# An ASSOCIATION-ONLY resource: it has no ARM type at all, because Terraform needs a
# separate addressable resource where ARM has a field. It must become an EDGE and must NOT
# be reported as an untranslated type — reporting it as untranslated would claim a gap in
# this skill and bury the real gaps, since associations outnumber missing types on an
# IaC-heavy repo.
resource "azurerm_subnet_route_table_association" "apps" {
  subnet_id      = azurerm_subnet.apps.id
  route_table_id = module.naming.route_table_id
}
