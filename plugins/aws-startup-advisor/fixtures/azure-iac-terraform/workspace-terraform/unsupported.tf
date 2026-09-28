# A COST-BEARING resource type deliberately absent from
# arm-type-canonicalization.md. It carries a sku, so it is cost-bearing on the
# unknown-type policy's own test as well as by the untranslated-type rule, and Design
# must STOP on it rather than warn-and-skip. At Discover it must be recorded as
# untranslated in warnings[], NOT guessed into a Microsoft.* string.
#
# IoT Hub is chosen for DURABLE absence. An earlier draft used azurerm_dev_test_lab,
# which was a fragile choice: the moment the canonicalization table's coverage was
# broadened for real-world repos, dev_test_lab was added and this fixture silently
# stopped testing anything. IoT is out of this skill's scope by design (it is neither
# startup-weighted nor specialist-gated), so it will not be added by a coverage pass.
resource "azurerm_iothub" "telemetry_ingest" {
  name                = "iot-${var.prefix}-ingest"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location

  sku {
    name     = "S1"
    capacity = 1
  }
}

# A module whose source is not in the workspace: its resources cannot be
# discovered, and that must produce a warning rather than silence.
module "cdn" {
  source              = "Azure/cdn/azurerm"
  version             = "3.1.0"
  resource_group_name = azurerm_resource_group.app.name
}
