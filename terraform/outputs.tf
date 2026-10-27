output "orders_url" {
  description = "Public URL of the orders API."
  value       = module.orders_service.url
}

output "orders_migration_job_name" {
  description = "Run this job (az containerapp job start) before shifting traffic to a new revision."
  value       = module.orders_service.migration_job_name
}

output "orders_key_vault_uri" {
  description = "Key Vault holding the service's secrets."
  value       = module.orders_service.key_vault_uri
}
