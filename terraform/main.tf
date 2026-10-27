# Root module = the shared "landing zone" for the R&D pod: resource group, logging,
# and the Container Apps environment. Each service the pod ships is one call to a
# service module, so the next idea gets the same safe defaults for free.

locals {
  tags = merge(var.tags, {
    environment = var.environment
    managed_by  = "terraform"
    owner       = "rnd-platform"
  })
}

resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-rnd-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-rnd-${var.environment}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  logs_destination           = "log-analytics" # stdout JSON logs -> Log Analytics
  tags                       = local.tags
}

module "orders_service" {
  source = "./modules/orders_service"

  name                         = "orders"
  environment                  = var.environment
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  image                        = var.image
  acr_id                       = var.acr_id
  acr_login_server             = var.acr_login_server
  db_password_version          = var.db_password_version
  tags                         = local.tags
}
