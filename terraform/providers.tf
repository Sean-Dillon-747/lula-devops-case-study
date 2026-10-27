terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  # This exercise is `terraform validate` only - no real Azure credentials are
  # used and nothing is applied. If you bump the provider version, that's fine.
}
