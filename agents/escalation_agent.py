"""
Escalation specialist - thin wrapper, always a valid fallback for any
ticket the router or another specialist couldn't resolve.
"""

from crewai import Agent
from tools import escalation_tools
from config import settings

ROLE = "L2 escalation specialist"
GOAL = "Escalate the ticket to L2 with a clear, accurate reason"
BACKSTORY = (
    "You hand off tickets to L2 support when no other specialist could "
    "resolve them - missing information, failed remediation, or issues "
    "requiring human judgment. Always include a specific reason."
)


def build_escalation_agent() -> Agent:
    return Agent(
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=escalation_tools.get_tools(),
        llm=settings.model,
        verbose=False,
    )