"""
Terraform specialist - plan/apply/state operations via MCP tools.
Apply-type operations should be gated (guardrail or human_input) at the
Task level in crew/ticket_crew.py, not here - this agent just executes
what it's given.
"""

from crewai import Agent
from tools import terraform_tools
from config import settings

ROLE = "Terraform infrastructure specialist"
GOAL = "Run the correct Terraform operation against a real, known workspace/resource and report the outcome"
BACKSTORY = (
    "You manage infrastructure via Terraform - plan, apply, and state "
    "inspection. Only ever act against a workspace or resource that has "
    "been validated as real. Treat apply operations as high-risk: always "
    "produce a plan first and clearly state what will change before "
    "applying anything."
)


def build_terraform_agent() -> Agent:
    return Agent(
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=terraform_tools.get_tools(),
        llm=settings.model,
        verbose=False,
    )