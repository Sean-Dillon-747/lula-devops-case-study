# terraform init -backend-config=envs/dev.backend.hcl
# The state storage account is bootstrapped once, outside this config (chicken and egg),
# with versioning + soft delete on the container and access via Entra ID RBAC only.
resource_group_name  = "rg-tfstate"
storage_account_name = "sttfstaterndpod"
container_name       = "tfstate"
key                  = "orders/dev.tfstate"
use_azuread_auth     = true
