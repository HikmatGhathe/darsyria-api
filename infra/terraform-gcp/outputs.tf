output "project_id" {
  description = "Google Cloud project containing the new infrastructure."
  value       = var.project_id
}

output "vm_name" {
  description = "Compute Engine VM name."
  value       = google_compute_instance.darsyria.name
}

output "zone" {
  description = "Compute Engine VM zone."
  value       = var.zone
}

output "public_ip_address" {
  description = "Static IPv4 address. Update DNS only after database migration and verification."
  value       = google_compute_address.darsyria.address
}

output "ssh_command" {
  description = "SSH through IAP with your Google identity; the public SSH port is closed."
  value       = "gcloud compute ssh ${google_compute_instance.darsyria.name} --project=${var.project_id} --zone=${var.zone} --tunnel-through-iap"
}
