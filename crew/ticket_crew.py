"""
Assembles the ticket-routing crew: one manager (router) agent
delegating to specialists, using Process.hierarchical. Replaces the
old orchestrator/ticket_agent.py as the single entry point
run_ticket_agent.py calls.


NOTE: the per-task guardrail (kb_output_guardrail) is removed for now
- see prior comment history for why. Per-specialist Tasks with their
own guardrails is the real fix, not done yet.

Built once per run via build_crew(), reused for every candidate ticket -
each ticket gets its own Task, but the agents/crew wiring is shared.
"""

import logging
from crewai import Task, Crew, Process
from agents.categorization_agent import build_categorization_agent
from clients import zammad_client
from tools.zammad_tools import SPAM_TAG

from agents.router_agent import build_router_agent
from agents.ansible_agent import build_ansible_agent
from agents.kb_agent import build_kb_agent
from agents.escalation_agent import build_escalation_agent
from agents.classification_agent import build_spam_agent

logger = logging.getLogger(__name__)

_crew = None
_router = None
_ansible = None
_kb = None
_escalation = None
_spam = None
_categorization = None
_categorization_crew = None


def build_crew():
    global _crew, _router, _ansible, _kb, _escalation, _spam
    global _categorization, _categorization_crew

    _router = build_router_agent()
    _ansible = build_ansible_agent()
    _kb = build_kb_agent()
    _escalation = build_escalation_agent()
    _spam = build_spam_agent()
        # Separate crew: categorization is not part of the router's delegation.
    _categorization = build_categorization_agent()
    _categorization_crew = Crew(
        agents=[_categorization],
        tasks=[],
        process=Process.sequential,
        verbose=True,
    )
    _crew = Crew(
        agents=[_ansible, _kb, _escalation, _spam],
        tasks=[],
        process=Process.hierarchical,
        manager_agent=_router,
        verbose=True,
    )
    return _crew

def _categorize_ticket(ticket: dict, ticket_text: str) -> None:
    """
    Categorize a ticket as Incident / Service Request / Change Request.
    Skips spam. Never raises: a categorization problem must not break routing.
    """
    if _categorization_crew is None:
        logger.warning("Categorization crew not built - skipping ticket #%s", ticket["number"])
        return

    try:
        tags = zammad_client.get_ticket_tags(ticket["id"])
        if SPAM_TAG in tags:
            logger.info("Ticket #%s is spam - skipping categorization", ticket["number"])
            return

        task = Task(
            description=(
                f"ticket_id: {ticket['id']}\n"
                f"ticket_number: {ticket['number']}\n"
                f"Title: {ticket.get('title', '')}\n"
                f"Body: {ticket_text}\n\n"
                "Read the full ticket conversation, classify the ticket as "
                "Incident, Service Request, or Change Request, and apply the "
                "matching tag using the tag_ticket tool with the ticket_id "
                "exactly as given."
            ),
            expected_output=(
                "The category chosen, the tag applied, whether tag_ticket "
                "succeeded, and a brief explanation."
            ),
            agent=_categorization,
        )

        logger.info("Categorizing ticket #%s", ticket["number"])
        _categorization_crew.tasks = [task]
        result = _categorization_crew.kickoff()
        logger.debug("Ticket #%s categorization result: %s", ticket["number"], result)

    except Exception:
        logger.exception("Categorization failed for ticket #%s (routing result unaffected)", ticket["number"])


def route_ticket(ticket: dict, ticket_text: str) -> dict:
    if _crew is None:
        raise RuntimeError("Crew not built - call build_crew() once per run before routing tickets.")

    description = (
        f"ticket_id: {ticket['id']}\n"
        f"ticket_number: {ticket['number']}\n"
        f"Title: {ticket.get('title', '')}\n"
        f"Body: {ticket_text}\n\n"
        "Decide which specialist's domain this ticket falls under "
        "(Ansible operations, Knowledge Base question, spam, or "
        "something else) and delegate to that specialist, even if the "
        "ticket is missing details like a hostname - that specialist "
        "has its own tool to ask the customer for whatever's missing, "
        "so let them handle it rather than deciding on their behalf. "
        "Pass ticket_id and ticket_number exactly as given to whichever "
        "tool ends up being called.\n\n"
        "If the ticket is clearly spam, unsolicited advertising, or "
        "has no genuine support request in it, delegate to the spam "
        "classification specialist instead of any operational "
        "specialist.\n\n"
        "Only delegate directly to the escalation specialist yourself if "
        "the ticket clearly doesn't fit any specialist's domain at all "
        "(e.g. a billing question, a non-technical request), or if a "
        "specialist you delegated to reports back that it's still stuck "
        "after asking for clarification."
    )

    task = Task(
        description=description,
        expected_output=(
            "Confirmation of which specialist handled the ticket, which "
            "tool was called, and the terminal outcome (resolved, "
            "answered, clarification requested, or escalated)."
        ),
    )

    logger.info("Routing ticket #%s", ticket["number"])

    _crew.tasks = [task]
    result = _crew.kickoff()

    logger.debug("Ticket #%s crew result: %s", ticket["number"], result)

    # Runs after routing so the spam specialist has already had its chance.
    _categorize_ticket(ticket, ticket_text)

    return result