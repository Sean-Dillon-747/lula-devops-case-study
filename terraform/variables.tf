variable "resource_group_name" {
  type        = string
  description = "Name of the resource group that holds the service's Azure footprint."
}

variable "location" {
  type        = string
  description = "Azure region, e.g. \"southafricanorth\"."
  default     = "southafricanorth"
}

variable "environment" {
  type        = string
  description = "Deployment environment (e.g. dev, prod) - use it to namespace resources."
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "image" {
  type        = string
  description = "Full image reference built by CI, pinned by digest, e.g. myacr.azurecr.io/orders-api@sha256:..."
}

variable "acr_id" {
  type        = string
  description = "Resource ID of the existing (platform-owned) Azure Container Registry."
}

variable "acr_login_server" {
  type        = string
  description = "Login server of that registry, e.g. myacr.azurecr.io."
}

variable "db_password_version" {
  type        = number
  description = "Bump to rotate the DB password. Write-only values are only re-sent when this changes."
  default     = 1
}

variable "tags" {
  type        = map(string)
  description = "Extra tags merged onto every resource."
  default     = {}
}
