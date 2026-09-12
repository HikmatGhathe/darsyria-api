resource "azurerm_resource_group" "darsyria" {
  name     = var.resource_group_name
  location = var.resource_group_location

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_virtual_network" "darsyria" {
  name                = "${var.vm_name}VNET"
  location            = var.location
  resource_group_name = azurerm_resource_group.darsyria.name
  address_space       = ["10.0.0.0/16"]
}

resource "azurerm_subnet" "darsyria" {
  name                            = "${var.vm_name}Subnet"
  resource_group_name             = azurerm_resource_group.darsyria.name
  virtual_network_name            = azurerm_virtual_network.darsyria.name
  address_prefixes                = ["10.0.0.0/24"]
  default_outbound_access_enabled = true
}

resource "azurerm_network_security_group" "darsyria" {
  name                = "${var.vm_name}NSG"
  location            = var.location
  resource_group_name = azurerm_resource_group.darsyria.name

  security_rule {
    name                       = "open-port-80_443"
    priority                   = 900
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "default-allow-ssh"
    priority                   = 1000
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ssh_source_address_prefix
    destination_address_prefix = "*"
  }
}

resource "azurerm_public_ip" "darsyria" {
  name                = "${var.vm_name}PublicIP"
  location            = var.location
  resource_group_name = azurerm_resource_group.darsyria.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_interface" "darsyria" {
  name                = "${var.vm_name}VMNic"
  location            = var.location
  resource_group_name = azurerm_resource_group.darsyria.name

  ip_configuration {
    name                          = "ipconfig${var.vm_name}"
    subnet_id                     = azurerm_subnet.darsyria.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.darsyria.id
  }
}

resource "azurerm_network_interface_security_group_association" "darsyria" {
  network_interface_id      = azurerm_network_interface.darsyria.id
  network_security_group_id = azurerm_network_security_group.darsyria.id
}

resource "azurerm_linux_virtual_machine" "darsyria" {
  name                            = var.vm_name
  computer_name                   = var.vm_name
  location                        = var.location
  resource_group_name             = azurerm_resource_group.darsyria.name
  size                            = "Standard_D2s_v3"
  admin_username                  = var.admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.darsyria.id]

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    name                 = "${var.vm_name}_disk1_6134e52ee4b2447d84a3597c94c22aed"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  lifecycle {
    prevent_destroy = true
  }
}
