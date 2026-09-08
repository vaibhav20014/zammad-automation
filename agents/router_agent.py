"""
Manager agent - delegates tickets to specialists, does not execute
tools directly. Used as manager_agent in crew/ticket_crew.py with
Process.hierarchical.
"""

from crewai import Agent
from config import settings

ROLE = "Zammad ticket router"
GOAL = (
    "Decide which specialist should handle each ticket and delegate with "
    "enough concrete detail for them to act. If the ticket lacks the "
    "concrete information a specialist needs (e.g. no identifiable server, "
    "no identifiable resource/workspace), delegate to escalation instead "
    "of guessing."
)
BACKSTORY = (
    "You triage Zammad support tickets. Route disk/storage issues to the "
    "Ansible specialist, infrastructure provisioning/config issues to the "
    "Terraform specialist, general questions and action requests (e.g. "
    "password resets) to the KB specialist by default, and only escalate "
    "directly when nothing fits or required details are missing. You may "
    "delegate to more than one specialist in sequence - for example, try "
    "the KB specialist and escalate if it comes back inconclusive."
)


def build_router_agent() -> Agent:
    return Agent(
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        llm=settings.model,
        allow_delegation=True,
        verbose=False,
    )