variable "project_id" {
  description = "Existing Google Cloud project with billing enabled. This configuration does not change billing."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use the Google Cloud project ID, not its display name or billing account ID."
  }
}

variable "admin_email" {
  description = "Google user account granted OS Login administrator access and permission to use the IAP SSH tunnel."
  type        = string

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.admin_email)) && var.admin_email != "you@example.com"
    error_message = "Set admin_email to your Google login email, replacing the example address."
  }
}

variable "region" {
  description = "Google Cloud region. Confirm regional pricing before applying."
  type        = string
  default     = "europe-west3"
}

variable "zone" {
  description = "Compute zone within region."
  type        = string
  default     = "europe-west3-a"
}

variable "vm_name" {
  description = "Name prefix for the VM, network, disk, and service account."
  type        = string
  default     = "darsyria-gcp"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,23}[a-z0-9]$", var.vm_name))
    error_message = "Use 6 to 25 lowercase letters, digits, or hyphens; start with a letter and end with a letter or digit."
  }
}

variable "machine_type" {
  description = "Initial VM size; e2-standard-2 has 2 vCPUs and 8 GiB RAM. Measure application usage before resizing."
  type        = string
  default     = "e2-standard-2"
}

variable "boot_disk_size_gb" {
  description = "Persistent boot disk capacity in GB. Holds the OS, Docker images, Postgres volumes, and embedding cache."
  type        = number
  default     = 50

  validation {
    condition     = var.boot_disk_size_gb >= 50 && floor(var.boot_disk_size_gb) == var.boot_disk_size_gb
    error_message = "Use an integer disk size of at least 50 GB; increase it if the source data needs more space."
  }
}

variable "snapshot_retention_days" {
  description = "Retention for scheduled crash-consistent disk snapshots. These do not replace tested PostgreSQL backups."
  type        = number
  default     = 7

  validation {
    condition     = var.snapshot_retention_days >= 1 && var.snapshot_retention_days <= 365 && floor(var.snapshot_retention_days) == var.snapshot_retention_days
    error_message = "Snapshot retention must be a whole number from 1 to 365 days."
  }
}
