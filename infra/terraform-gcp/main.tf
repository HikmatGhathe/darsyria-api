locals {
  labels = {
    application = "darsyria"
    managed_by  = "terraform"
  }

  required_services = toset([
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iap.googleapis.com",
    "oslogin.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_services
  project  = var.project_id
  service  = each.value

  # Other resources in this existing project may also use these APIs.
  disable_on_destroy = false
}

resource "google_compute_network" "darsyria" {
  name                    = "${var.vm_name}-network"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "darsyria" {
  name                     = "${var.vm_name}-subnet"
  region                   = var.region
  network                  = google_compute_network.darsyria.id
  ip_cidr_range            = "10.20.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_firewall" "web" {
  name          = "${var.vm_name}-web"
  network       = google_compute_network.darsyria.name
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.vm_name]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

resource "google_compute_firewall" "iap_ssh" {
  name          = "${var.vm_name}-iap-ssh"
  network       = google_compute_network.darsyria.name
  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags   = [var.vm_name]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_address" "darsyria" {
  name         = "${var.vm_name}-ip"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
  labels       = local.labels

  depends_on = [google_project_service.required]
}

# The VM receives no project roles. App credentials are transferred separately,
# not put in Terraform state, instance metadata, or startup scripts.
resource "google_service_account" "vm" {
  account_id   = "${var.vm_name}-vm"
  display_name = "DarSyria VM"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "admin" {
  for_each = toset([
    "roles/compute.osAdminLogin",
    "roles/iap.tunnelResourceAccessor",
  ])
  project = var.project_id
  role    = each.value
  member  = "user:${var.admin_email}"

  depends_on = [google_project_service.required]
}

resource "google_service_account_iam_member" "admin" {
  service_account_id = google_service_account.vm.name
  role               = "roles/iam.serviceAccountUser"
  member             = "user:${var.admin_email}"
}

resource "google_compute_resource_policy" "daily_snapshot" {
  name   = "${var.vm_name}-daily-snapshot"
  region = var.region

  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "04:00"
      }
    }

    retention_policy {
      max_retention_days    = var.snapshot_retention_days
      on_source_disk_delete = "APPLY_RETENTION_POLICY"
    }

    snapshot_properties {
      storage_locations = [var.region]
      labels            = local.labels
      guest_flush       = false
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_compute_disk" "boot" {
  name   = "${var.vm_name}-boot"
  zone   = var.zone
  type   = "pd-balanced"
  size   = var.boot_disk_size_gb
  image  = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
  labels = local.labels

  lifecycle {
    prevent_destroy = true
    # Use the family only on first creation. A newer Ubuntu image must not
    # replace the disk containing the production database and Docker volumes.
    ignore_changes = [image]

    precondition {
      condition     = startswith(var.zone, "${var.region}-")
      error_message = "The selected zone must be in the selected region."
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_compute_disk_resource_policy_attachment" "daily_snapshot" {
  name = google_compute_resource_policy.daily_snapshot.name
  disk = google_compute_disk.boot.name
  zone = var.zone
}

resource "google_compute_instance" "darsyria" {
  name                      = var.vm_name
  zone                      = var.zone
  machine_type              = var.machine_type
  deletion_protection       = true
  allow_stopping_for_update = false
  tags                      = [var.vm_name]
  labels                    = local.labels

  boot_disk {
    source      = google_compute_disk.boot.id
    auto_delete = false
  }

  network_interface {
    subnetwork = google_compute_subnetwork.darsyria.id

    access_config {
      nat_ip       = google_compute_address.darsyria.address
      network_tier = "PREMIUM"
    }
  }

  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    # Metadata updates do not replace the VM. The script runs on boot; to
    # apply a changed script immediately, run google_metadata_script_runner.
    startup-script = replace(file("${path.module}/startup.sh"), "\r\n", "\n")
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [
    google_project_iam_member.admin,
    google_service_account_iam_member.admin,
  ]
}
