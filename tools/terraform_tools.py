"""
Terraform MCP connection config + tool filtering. Placeholder shape -
same pattern as tools/ansible_tools.py, but the actual server
command/args and real tool names are still unconfirmed (no global
Terraform MCP server identified yet, unlike Ansible's).

apply-type tools are excluded from allowed_tool_names until a stricter
gate (guardrail or human_input on the Task level) is designed - do not
widen this list to include apply/destroy operations without that gate
in place first.
"""

from crewai.mcp import MCPServerStdio
from crewai.mcp.filters import create_static_tool_filter

TERRAFORM_MCP = MCPServerStdio(
    command="terraform-mcp-server",   # <- placeholder, confirm real command
    args=[],
    env={},
    tool_filter=create_static_tool_filter(
        allowed_tool_names=["terraform_plan", "terraform_show"],
        blocked_tool_names=["terraform_apply", "terraform_destroy"],
    ),
    cache_tools_list=True,
)


def get_mcps() -> list:
    return [TERRAFORM_MCP]