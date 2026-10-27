# TODO (you): express the service's Azure footprint as Terraform.
#
# We're reading your HCL - structure, module/variable boundaries, and how you
# reason about state and secrets - NOT a running environment. `terraform validate`
# only; no Azure account, no `apply`.
#
# A sensible minimal footprint for the orders service:
#   - a resource group (azurerm_resource_group)
#   - compute to run the container (azurerm_container_app + environment, or AKS)
#   - a managed database (azurerm_postgresql_flexible_server) - think about how
#     the migration job connects to it
#   - Key Vault (azurerm_key_vault) for the DB connection string / secrets, and
#     how the app reads them (managed identity vs a secret baked into config)
#
# Keep it small and well-reasoned. One or two resources wired correctly, with
# variables and a clear state/secrets story, beats a broad half-built sketch.
#
# Example starting point (delete this comment and write real HCL):
#
# resource "azurerm_resource_group" "main" {
#   name     = var.resource_group_name
#   location = var.location
# }
