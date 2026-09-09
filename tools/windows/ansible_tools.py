"""
Ansible MCP connection config + tool filtering. Uses the global Ansible
MCP server (already installed/available as a command) via stdio
transport - CrewAI starts/stops the process per agent lifecycle, no
manual connection management needed here.
"""

from crewai.mcp import MCPServerStdio
from crewai.mcp.filters import create_static_tool_filter

# TODO: confirm the actual command/args for your global Ansible MCP
# server - this is a placeholder shape (e.g. if it's an npx package,
# a pip-installed console script, or a binary on PATH).
ANSIBLE_MCP = MCPServerStdio(
    command="ansible-mcp-server",   # <- replace with your actual global command
    args=[],
    env={},
    tool_filter=create_static_tool_filter(
        # Start restrictive - only allow what disk remediation actually
        # needs. Widen this list as you confirm which tool names the
        # server actually exposes (print them once via a quick manual
        # connection test before locking this down for real).
        allowed_tool_names=["run_playbook", "check_disk_usage"],
    ),
    cache_tools_list=True,
)


def get_mcps() -> list:
    """Returns the MCP server config list for the Ansible agent's `mcps=` field."""
    return [ANSIBLE_MCP]