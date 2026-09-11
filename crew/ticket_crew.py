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

from agents.router_agent import build_router_agent
from agents.ansible_agent import build_ansible_agent
from agents.kb_agent import build_kb_agent
from agents.escalation_agent import build_escalation_agent

logger = logging.getLogger(__name__)

_crew = None
_router = None
_ansible = None
_kb = None
_escalation = None


def build_crew():
    global _crew, _router, _ansible, _kb, _escalation

    _router = build_router_agent()
    _ansible = build_ansible_agent()
    _kb = build_kb_agent()
    _escalation = build_escalation_agent()

    _crew = Crew(
        agents=[_ansible, _kb, _escalation],
        tasks=[],
        process=Process.hierarchical,
        manager_agent=_router,
        verbose=False,
    )
    return _crew


def route_ticket(ticket: dict, ticket_text: str) -> dict:
    if _crew is None:
        raise RuntimeError("Crew not built - call build_crew() once per run before routing tickets.")

    description = (
        f"ticket_id: {ticket['id']}\n"
        f"ticket_number: {ticket['number']}\n"
        f"Title: {ticket.get('title', '')}\n"
        f"Body: {ticket_text}\n\n"
        "Decide which specialist's domain this ticket falls under "
        "(Ansible operations, Knowledge Base question, or something else) "
        "and delegate to that specialist, even if the ticket is missing "
        "details like a hostname - that specialist has its own tool to "
        "ask the customer for whatever's missing, so let them handle it "
        "rather than deciding on their behalf. Pass ticket_id and "
        "ticket_number exactly as given to whichever tool ends up being "
        "called.\n\n"
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
    return result