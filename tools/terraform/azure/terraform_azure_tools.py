"""
Terraform tools for common Azure provisioning requests - VMs, VNets,
subnets, NSGs. Native CrewAI tools, same pattern as
tools/linux/ansible_tools.py and tools/terraform_aws_tools.py.

IMPORTANT - unconfirmed assumptions:
  - Assumes each workspace directory already has a configured
    provider "azurerm" {} block and a pre-created resource group
    (resource_group_name passed in must already exist) - these tools
    add resources into an existing resource group, they don't create
    resource groups themselves.
  - destroy_azure_resource is deliberately NOT in get_tools() - same
    reasoning as the AWS file: destructive actions need an explicit
    gating decision before being wired into an agent.
"""

import re
from crewai.tools import tool
from tools.terraform.terraform_common import write_resource_file, apply_after_write, run_terraform


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())


# --- Virtual Network -------------------------------------------------------

@tool("create_azure_vnet")
def create_azure_vnet(workspace: str, name: str, resource_group_name: str, location: str, address_space: str = "10.0.0.0/16") -> str:
    """
    Creates an Azure Virtual Network inside an existing resource
    group. resource_group_name must already exist in the target Azure
    subscription - this tool does not create resource groups.
    """
    rid = _safe_id(name)
    content = f'''
resource "azurerm_virtual_network" "{rid}" {{
  name                = "{name}"
  resource_group_name = "{resource_group_name}"
  location            = "{location}"
  address_space       = ["{address_space}"]
}}

output "{rid}_vnet_id" {{
  value = azurerm_virtual_network.{rid}.id
}}
'''
    write_resource_file(workspace, f"vnet_{rid}.tf", content)
    return apply_after_write(workspace)


@tool("create_azure_subnet")
def create_azure_subnet(workspace: str, name: str, resource_group_name: str, vnet_resource_name: str, address_prefix: str) -> str:
    """
    Creates a subnet inside an existing VNet managed in the same
    workspace. vnet_resource_name must match the `name` used when that
    VNet was created via create_azure_vnet.
    """
    rid = _safe_id(name)
    vnet_rid = _safe_id(vnet_resource_name)
    content = f'''
resource "azurerm_subnet" "{rid}" {{
  name                 = "{name}"
  resource_group_name  = "{resource_group_name}"
  virtual_network_name = azurerm_virtual_network.{vnet_rid}.name
  address_prefixes     = ["{address_prefix}"]
}}

output "{rid}_subnet_id" {{
  value = azurerm_subnet.{rid}.id
}}
'''
    write_resource_file(workspace, f"subnet_{rid}.tf", content)
    return apply_after_write(workspace)


# --- Network Security Group -------------------------------------------------

@tool("create_azure_nsg")
def create_azure_nsg(workspace: str, name: str, resource_group_name: str, location: str) -> str:
    """
    Creates a Network Security Group with no rules by default -
    specific inbound/outbound rules should be added as a follow-up
    once the requirement is known, rather than opening broad access.
    """
    rid = _safe_id(name)
    content = f'''
resource "azurerm_network_security_group" "{rid}" {{
  name                = "{name}"
  resource_group_name = "{resource_group_name}"
  location            = "{location}"
}}

output "{rid}_nsg_id" {{
  value = azurerm_network_security_group.{rid}.id
}}
'''
    write_resource_file(workspace, f"nsg_{rid}.tf", content)
    return apply_after_write(workspace)


# --- Virtual Machine ---------------------------------------------------

@tool("create_azure_vm")
def create_azure_vm(
    workspace: str,
    name: str,
    resource_group_name: str,
    location: str,
    vm_size: str,
    subnet_resource_name: str,
    admin_username: str,
    ssh_public_key: str,
    image_publisher: str = "Canonical",
    image_offer: str = "0001-com-ubuntu-server-jammy",
    image_sku: str = "22_04-lts",
) -> str:
    """
    Creates a Linux VM with a network interface attached to an
    existing subnet. subnet_resource_name must match a subnet already
    created via create_azure_subnet in the same workspace.
    ssh_public_key must be a real public key string - this tool does
    not generate one.
    """
    rid = _safe_id(name)
    subnet_rid = _safe_id(subnet_resource_name)
    content = f'''
resource "azurerm_network_interface" "{rid}_nic" {{
  name                = "{name}-nic"
  location            = "{location}"
  resource_group_name = "{resource_group_name}"

  ip_configuration {{
    name                          = "internal"
    subnet_id                     = azurerm_subnet.{subnet_rid}.id
    private_ip_address_allocation = "Dynamic"
  }}
}}

resource "azurerm_linux_virtual_machine" "{rid}" {{
  name                = "{name}"
  resource_group_name = "{resource_group_name}"
  location            = "{location}"
  size                = "{vm_size}"
  admin_username      = "{admin_username}"

  network_interface_ids = [
    azurerm_network_interface.{rid}_nic.id,
  ]

  admin_ssh_key {{
    username   = "{admin_username}"
    public_key = "{ssh_public_key}"
  }}

  os_disk {{
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }}

  source_image_reference {{
    publisher = "{image_publisher}"
    offer     = "{image_offer}"
    sku       = "{image_sku}"
    version   = "latest"
  }}

  tags = {{
    Name = "{name}"
  }}
}}

output "{rid}_vm_id" {{
  value = azurerm_linux_virtual_machine.{rid}.id
}}
'''
    write_resource_file(workspace, f"vm_{rid}.tf", content)
    return apply_after_write(workspace)


# --- Read-only / verification ---------------------------------------------

@tool("check_azure_terraform_state")
def check_azure_terraform_state(workspace: str) -> str:
    """
    Lists all Azure resources currently tracked in the workspace's
    Terraform state. Read-only - call after any create_azure_* tool to
    verify the resource actually exists in state.
    """
    return run_terraform(workspace, ["state", "list"])


@tool("check_azure_terraform_outputs")
def check_azure_terraform_outputs(workspace: str) -> str:
    """
    Shows the workspace's Terraform outputs. Read-only - use to report
    concrete details back to the customer after a successful create.
    """
    return run_terraform(workspace, ["output", "-no-color"])


def get_tools() -> list:
    """
    destroy is deliberately not included - see module docstring.
    """
    return [
        create_azure_vnet,
        create_azure_subnet,
        create_azure_nsg,
        create_azure_vm,
        check_azure_terraform_state,
        check_azure_terraform_outputs,
    ]