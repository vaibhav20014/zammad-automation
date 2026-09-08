"""
Tool for the escalation specialist agent. Thin wrapper around
services/escalation_service.py - always a valid terminal action.
"""

from crewai.tools import tool
from services import escalation_service


@tool("escalate_to_l2")
def escalate_to_l2(ticket_id: int, ticket_number: str, reason: str) -> dict:
    """Escalate the ticket to L2 support with a clear, specific reason.
    Use when no other specialist could resolve the ticket - missing
    information, failed remediation, or something requiring human
    judgment."""
    return escalation_service.handle(ticket_id, ticket_number, reason)


def get_tools() -> list:
    return [escalate_to_l2]