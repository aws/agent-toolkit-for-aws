# DOWNLOADED registry-module source. Its resources MUST be discovered.
#
# This directory is the reason extract-terraform.md Step 3 case 2 exists. The blanket
# `.terraform/` ban was correct for state files and wrong for this: `modules/` holds
# nothing but module SOURCE, exactly as safe as a local module path. Under the old ban a
# repo built on Azure Verified Modules returned a nearly empty inventory plus a warning,
# and every downstream phase then reasoned about a fraction of the estate.
variable "resource_group_name" { type = string }

resource "azurerm_route_table" "egress" {
  name                = "rt-egress"
  resource_group_name = var.resource_group_name
  location            = "westeurope"
}

resource "azurerm_bastion_host" "jump" {
  name                = "bas-jump"
  resource_group_name = var.resource_group_name
  location            = "westeurope"
  sku                 = "Basic"
}
