terraform {
  # 1.11+: write-only arguments, so the DB password never lands in plan or state.
  required_version = ">= 1.11"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.23" # 4.21 added administrator_password_wo, 4.23 added key_vault_secret value_wo
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7" # 3.7 added the ephemeral random_password
    }
  }

  # Remote state, one blob per environment, selected at init time:
  #   terraform init -backend-config=envs/dev.backend.hcl
  # CI runs `init -backend=false`, so nothing here needs credentials.
  backend "azurerm" {}
}

provider "azurerm" {
  features {
    key_vault {
      # Never let `terraform destroy` permanently purge secrets: soft-delete + purge
      # protection are the safety net for a fat-fingered apply.
      purge_soft_delete_on_destroy = false
    }
  }
  # Auth comes from the environment: in the pipeline, OIDC workload identity
  # federation (ARM_USE_OIDC=true), so there is no client secret anywhere.
}
