# DarSyria Azure infrastructure

This directory brings the existing DarSyria Azure VM and its networking under
Terraform management. It covers the resource group, VNet, subnet, network
security group, public IP, network interface, NSG association, and Linux VM.

The resources already exist, so they must be imported. Running an apply before
reviewing the import plan could modify them.

## Prerequisites

- Terraform 1.5 or newer
- Azure CLI authenticated with `az login`
- The correct subscription selected with `az account set`

Confirm that Terraform is available:

```powershell
terraform version
```

If Windows cannot find it, add the directory containing `terraform.exe` to the
user `PATH`, then open a new PowerShell window.

Create a local variables file from the example:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
```

Insert the subscription ID returned by:

```powershell
az account show --query id --output tsv
```

Set `admin_ssh_public_key` to the existing public key configured on the VM.
`terraform.tfvars` and local state files are ignored by Git.

## Adopt the existing resources

Initialize Terraform and create a saved import plan:

```powershell
terraform init
terraform plan -out=import.tfplan
```

Review the complete plan. The safe import plan must end with:

```text
Plan: 8 to import, 0 to add, 0 to change, 0 to destroy.
```

Only after verifying that result, apply that exact saved plan to import the
resources into local state:

```powershell
terraform apply import.tfplan
terraform plan
```

The final plan should report `No changes`. The import blocks are idempotent, so
they can stay in the repository as a record of how the resources were adopted.

Never commit `terraform.tfstate`, plan files, or real `.tfvars` files because
they can contain sensitive infrastructure data. Before multiple people or CI
run plans, migrate the state to a remote backend with locking.

## Normal workflow after import

```powershell
terraform fmt -check -recursive
terraform validate
terraform plan
```

Review every plan before using `terraform apply`. Docker Compose deploys the
application on the VM; Terraform manages the Azure infrastructure beneath it.
