locals {
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
}

import {
  to = azurerm_resource_group.darsyria
  id = local.resource_group_id
}

import {
  to = azurerm_virtual_network.darsyria
  id = "${local.resource_group_id}/providers/Microsoft.Network/virtualNetworks/${var.vm_name}VNET"
}

import {
  to = azurerm_subnet.darsyria
  id = "${local.resource_group_id}/providers/Microsoft.Network/virtualNetworks/${var.vm_name}VNET/subnets/${var.vm_name}Subnet"
}

import {
  to = azurerm_network_security_group.darsyria
  id = "${local.resource_group_id}/providers/Microsoft.Network/networkSecurityGroups/${var.vm_name}NSG"
}

import {
  to = azurerm_public_ip.darsyria
  id = "${local.resource_group_id}/providers/Microsoft.Network/publicIPAddresses/${var.vm_name}PublicIP"
}

import {
  to = azurerm_network_interface.darsyria
  id = "${local.resource_group_id}/providers/Microsoft.Network/networkInterfaces/${var.vm_name}VMNic"
}

import {
  to = azurerm_network_interface_security_group_association.darsyria
  id = "${local.resource_group_id}/providers/Microsoft.Network/networkInterfaces/${var.vm_name}VMNic|${local.resource_group_id}/providers/Microsoft.Network/networkSecurityGroups/${var.vm_name}NSG"
}

import {
  to = azurerm_linux_virtual_machine.darsyria
  id = "${local.resource_group_id}/providers/Microsoft.Compute/virtualMachines/${var.vm_name}"
}
