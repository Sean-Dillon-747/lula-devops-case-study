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
}
