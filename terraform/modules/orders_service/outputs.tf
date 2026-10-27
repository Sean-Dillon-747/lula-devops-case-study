output "url" {
  description = "Public URL of the service."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "migration_job_name" {
  description = "Name of the Container Apps Job that runs migrations."
  value       = azurerm_container_app_job.migrate.name
}

output "key_vault_uri" {
  description = "URI of the service's Key Vault."
  value       = azurerm_key_vault.main.vault_uri
}

output "identity_principal_id" {
  description = "Principal ID of the service identity (e.g. to grant it Entra DB access)."
  value       = azurerm_user_assigned_identity.app.principal_id
}
