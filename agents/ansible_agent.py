"""
Ansible specialist - executes disk checks and other Ansible-driven
operations via the global Ansible MCP server. Tool access is restricted
via tool_filter in tools/ansible_tools.py, not by agent judgment alone.
"""

from crewai import Agent
from tools import ansible_tools
from config import settings

ROLE = "Ansible operations specialist"
GOAL = "Run the correct Ansible operation against a real, known server and report the outcome"
BACKSTORY = (
    "You execute Ansible playbooks against servers - disk checks/cleanup "
    "and other operational tasks. Only ever act against a server_name "
    "that has been validated as real; if given an unknown or ambiguous "
    "server, report that back rather than guessing or running anything. "
    "You only have access to the tools you've been given - if a task "
    "asks for something outside that scope, say so rather than trying "
    "an unavailable operation."
)


def build_ansible_agent() -> Agent:
    return Agent(
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        mcps=ansible_tools.get_mcps(),
        llm=settings.model,
        verbose=False,
    )