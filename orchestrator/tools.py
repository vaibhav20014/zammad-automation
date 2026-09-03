"""
Tool definitions for the ticket-routing agent. Each tool takes ticket_id
explicitly since the agent instance is shared across tickets, not rebuilt
per ticket. Module-level state (known_servers, kb_titles) is loaded once
per run and referenced here rather than closed over.
"""

import logging
from langchain_core.tools import tool
from clients import zammad_client
from services import disk_ticket_service, kb_answer_service, escalation_service

logger = logging.getLogger(__name__)

# Set by orchestrator.ticket_agent.configure() at the start of each run,
# before the agent is invoked for any ticket.
_known_servers: set[str] = set()
_kb_titles: list[dict] = []


def configure(known_servers: set[str], kb_titles: list[dict]) -> None:
    """Configure the servers list for run disk check tool and kb titles for the answer for kb tool."""
    global _known_servers, _kb_titles
    _known_servers = known_servers
    _kb_titles = kb_titles


@tool
def run_disk_check(ticket_id: int, ticket_number: str, server_name: str) -> dict:
    """Run an Ansible disk check/cleanup on a specific server and close the
    ticket if resolved. Use when the ticket reports low disk space, cleanup
    requests, or storage warnings, and you can identify a server name from
    the ticket text. server_name must be a real hostname from the known
    inventory - if unsure, escalate instead of guessing."""
    if server_name not in _known_servers:
        return {"resolved": False, "reason": f"'{server_name}' is not a known server."}
    return disk_ticket_service.handle(ticket_id, ticket_number, server_name)


@tool
def answer_from_kb(ticket_id: int, ticket_number: str, query: str) -> dict:
    """Check the knowledge base for a matching article before deciding
    this needs escalation. Use this for anything that isn't clearly a
    disk/storage issue - including how-tos, questions, AND action
    requests that might have a documented self-service procedure (e.g.
    password resets, access requests, setup/configuration tasks). Do not
    skip this just because the ticket is phrased as a request for action
    rather than a question - many action-shaped tickets are covered by a
    KB article. Pass the user's underlying need, rephrased clearly for
    matching against KB titles."""
    ticket_text = zammad_client.get_first_article_body(ticket_id) or query
    return kb_answer_service.handle(ticket_id, ticket_number, ticket_text, _kb_titles)

@tool
def escalate_to_l2(ticket_id: int, ticket_number: str, reason: str) -> dict:
    """Escalate to L2 support. Use when nothing else fits, no server can be
    identified, disk remediation didn't resolve the issue, or the KB has no
    good answer - including as a fallback after another tool didn't
    resolve the ticket."""
    return escalation_service.handle(ticket_id, ticket_number, reason)