# The module's contract: what a service needs from the platform. Everything
# service-specific (identity, vault, database, app, migration job) lives inside.

variable "name" {
  type        = string
  description = "Short service name used in resource names, e.g. \"orders\"."

  validation {
    # kv-<name>-<env>-<5 char suffix> must fit Key Vault's 24-char limit even for "staging".
    condition     = can(regex("^[a-z][a-z0-9]{1,6}$", var.name))
    error_message = "name must be 2-7 lowercase alphanumerics (Key Vault names cap at 24 chars)."
  }
}

variable "environment" {
  type        = string
  description = "dev, staging or prod."
}

variable "resource_group_name" {
  type        = string
  description = "Resource group to deploy into (owned by the caller)."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "container_app_environment_id" {
  type        = string
  description = "Shared Container Apps environment the app and migration job run in."
}

variable "image" {
  type        = string
  description = "Image reference, pinned by digest. The app and migration job use the SAME image."
}

variable "acr_id" {
  type        = string
  description = "Container registry resource ID (for the AcrPull role assignment)."
}

variable "acr_login_server" {
  type        = string
  description = "Container registry login server."
}

variable "db_password_version" {
  type        = number
  description = "Bump to rotate the DB password (write-only args are only re-sent on change)."
}

variable "postgres_version" {
  type        = string
  description = "PostgreSQL major version. Matches CI and docker-compose so migrations are tested on the same engine."
  default     = "16"
}

variable "db_sku_name" {
  type        = string
  description = "Flexible Server SKU. Burstable for dev; General Purpose + HA for prod."
  default     = "B_Standard_B1ms"
}

variable "min_replicas" {
  type        = number
  description = "Minimum app replicas. 2+ in prod so a single replica restart isn't an outage."
  default     = 1
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to every resource."
  default     = {}
}
