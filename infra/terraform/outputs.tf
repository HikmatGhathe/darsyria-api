output "public_ip_address" {
  description = "Static public IPv4 address of the DarSyria VM."
  value       = azurerm_public_ip.darsyria.ip_address
}

output "ssh_command" {
  description = "Command used to connect to the DarSyria VM."
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.darsyria.ip_address}"
}
