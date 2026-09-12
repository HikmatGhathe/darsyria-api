variable "subscription_id" {
  description = "Azure subscription that contains the existing DarSyria resources."
  type        = string
}

variable "resource_group_name" {
  description = "Name of the existing DarSyria Azure resource group."
  type        = string
  default     = "darsyria-rg"
}

variable "resource_group_location" {
  description = "Azure metadata location of the existing resource group."
  type        = string
  default     = "germanywestcentral"
}

variable "location" {
  description = "Azure region that contains the DarSyria compute and network resources."
  type        = string
  default     = "polandcentral"
}

variable "vm_name" {
  description = "Name of the existing DarSyria Linux virtual machine."
  type        = string
  default     = "darsyria-vm"
}

variable "admin_username" {
  description = "Administrator username configured on the Linux VM."
  type        = string
  default     = "azureuser"
}

variable "admin_ssh_public_key" {
  description = "Existing SSH public key configured on the VM. Store it only in terraform.tfvars."
  type        = string
}

variable "ssh_source_address_prefix" {
  description = "CIDR allowed to connect over SSH. It is currently open to match the existing NSG."
  type        = string
  default     = "*"
}
