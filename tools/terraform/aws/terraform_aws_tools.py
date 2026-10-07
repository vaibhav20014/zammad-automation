"""
Terraform tools for common AWS provisioning requests - EC2 instances,
VPCs, subnets, security groups. Native CrewAI tools, same pattern as
tools/linux/ansible_tools.py.

IMPORTANT - unconfirmed assumptions:
  - Assumes each workspace directory already has a configured
    provider "aws" {} block (region, auth via env vars or a shared
    credentials file) - these tools only add resource blocks.
  - destroy_aws_resource is deliberately NOT in get_tools() - see
    tools/terraform_common.py-adjacent note in the Azure file too.
    Add only once you've decided how destructive actions should be
    gated (human_input, separate confirmation, etc.).
  - Sanitizes `name` into a Terraform-safe resource identifier and a
    filename, but does not check for collisions across calls with
    similar names - two requests naming things too similarly could
    overwrite each other's .tf file. Worth hardening later.
"""

import re
from crewai.tools import tool
from tools.terraform.terraform_common import write_resource_file, apply_after_write, run_terraform


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())


# --- VPC ---------------------------------------------------------------

@tool("create_aws_vpc")
def create_aws_vpc(workspace: str, name: str, cidr_block: str = "10.0.0.0/16") -> str:
    """
    Creates an AWS VPC with the given name and CIDR block. Call
    check_terraform_plan (in tools/terraform_common consumers) or just
    review this tool's own apply output before treating the ticket as
    resolved.
    """
    rid = _safe_id(name)
    content = f'''
resource "aws_vpc" "{rid}" {{
  cidr_block = "{cidr_block}"
  tags = {{
    Name = "{name}"
  }}
}}

output "{rid}_vpc_id" {{
  value = aws_vpc.{rid}.id
}}
'''
    write_resource_file(workspace, f"vpc_{rid}.tf", content)
    return apply_after_write(workspace)


@tool("create_aws_subnet")
def create_aws_subnet(workspace: str, name: str, vpc_resource_name: str, cidr_block: str, availability_zone: str) -> str:
    """
    Creates a subnet inside an existing VPC managed in the same
    workspace. vpc_resource_name must match the `name` used when that
    VPC was created via create_aws_vpc (so the Terraform reference
    resolves correctly).
    """
    rid = _safe_id(name)
    vpc_rid = _safe_id(vpc_resource_name)
    content = f'''
resource "aws_subnet" "{rid}" {{
  vpc_id            = aws_vpc.{vpc_rid}.id
  cidr_block        = "{cidr_block}"
  availability_zone = "{availability_zone}"
  tags = {{
    Name = "{name}"
  }}
}}

output "{rid}_subnet_id" {{
  value = aws_subnet.{rid}.id
}}
'''
    write_resource_file(workspace, f"subnet_{rid}.tf", content)
    return apply_after_write(workspace)


# --- Security Group ------------------------------------------------------

@tool("create_aws_security_group")
def create_aws_security_group(workspace: str, name: str, vpc_resource_name: str, description: str = "Managed by automation") -> str:
    """
    Creates a security group in the given VPC, allowing outbound
    traffic by default and no inbound rules - inbound rules should be
    added as a follow-up once the specific access requirement is
    known, rather than opening broad access by default.
    """
    rid = _safe_id(name)
    vpc_rid = _safe_id(vpc_resource_name)
    content = f'''
resource "aws_security_group" "{rid}" {{
  name        = "{name}"
  description = "{description}"
  vpc_id      = aws_vpc.{vpc_rid}.id

  egress {{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  tags = {{
    Name = "{name}"
  }}
}}

output "{rid}_sg_id" {{
  value = aws_security_group.{rid}.id
}}
'''
    write_resource_file(workspace, f"sg_{rid}.tf", content)
    return apply_after_write(workspace)


# --- EC2 Instance ----------------------------------------------------------

@tool("create_aws_ec2_instance")
def create_aws_ec2_instance(
    workspace: str,
    name: str,
    ami_id: str,
    instance_type: str,
    subnet_resource_name: str,
    security_group_resource_name: str | None = None,
) -> str:
    """
    Creates an EC2 instance. ami_id must be a real, valid AMI ID for
    the workspace's configured region - this tool does not look one up
    for you. subnet_resource_name must match a subnet already created
    via create_aws_subnet in the same workspace.
    """
    rid = _safe_id(name)
    subnet_rid = _safe_id(subnet_resource_name)
    sg_block = ""
    if security_group_resource_name:
        sg_rid = _safe_id(security_group_resource_name)
        sg_block = f"vpc_security_group_ids = [aws_security_group.{sg_rid}.id]"

    content = f'''
resource "aws_instance" "{rid}" {{
  ami           = "{ami_id}"
  instance_type = "{instance_type}"
  subnet_id     = aws_subnet.{subnet_rid}.id
  {sg_block}
  tags = {{
    Name = "{name}"
  }}
}}

output "{rid}_instance_id" {{
  value = aws_instance.{rid}.id
}}

output "{rid}_public_ip" {{
  value = aws_instance.{rid}.public_ip
}}
'''
    write_resource_file(workspace, f"ec2_{rid}.tf", content)
    return apply_after_write(workspace)


# --- Read-only / verification ---------------------------------------------

@tool("check_aws_terraform_state")
def check_aws_terraform_state(workspace: str) -> str:
    """
    Lists all AWS resources currently tracked in the workspace's
    Terraform state. Read-only - call after any create_aws_* tool to
    verify the resource actually exists in state.
    """
    return run_terraform(workspace, ["state", "list"])


@tool("check_aws_terraform_outputs")
def check_aws_terraform_outputs(workspace: str) -> str:
    """
    Shows the workspace's Terraform outputs (instance IDs, public IPs,
    VPC/subnet IDs). Read-only - use to report concrete details back
    to the customer after a successful create.
    """
    return run_terraform(workspace, ["output", "-no-color"])


def get_tools() -> list:
    """
    destroy is deliberately not included - see module docstring.
    """
    return [
        create_aws_vpc,
        create_aws_subnet,
        create_aws_security_group,
        create_aws_ec2_instance,
        check_aws_terraform_state,
        check_aws_terraform_outputs,
    ]