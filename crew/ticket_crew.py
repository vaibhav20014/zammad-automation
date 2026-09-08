"""
Assembles the full ticket-routing crew: one manager (router) agent
delegating to four specialists, using Process.hierarchical. Replaces
the old orchestrator/ticket_agent.py as the single entry point
run_ticket_agent.py calls.

Built once per run via build_crew(), reused for every candidate ticket -
each ticket gets its own Task, but the agents/crew wiring is shared.
"""

import logging
from crewai import Task, Crew, Process

from agents.router_agent import build_router_agent
from agents.ansible_agent import build_ansible_agent
from agents.terraform_agent import build_terraform_agent
from agents.kb_agent import build_kb_agent
from agents.escalation_agent import build_escalation_agent
from ai.answer_generator import kb_output_guardrail

logger = logging.getLogger(__name__)

_crew = None
_router = None
_ansible = None
_terraform = None
_kb = None
_escalation = None


def build_crew():
    """
    Builds all specialist agents plus the manager once per run. Call
    this before route_ticket(). Terraform apply-type operations aren't
    gated with human_input yet - that's a follow-up once
    tools/terraform_tools.py exists and we've confirmed which tool
    names actually need that gate.
    """
    global _crew, _router, _ansible, _terraform, _kb, _escalation

    _router = build_router_agent()
    _ansible = build_ansible_agent()
    _terraform = build_terraform_agent()
    _kb = build_kb_agent()
    _escalation = build_escalation_agent()

    _crew = Crew(
        agents=[_ansible, _terraform, _kb, _escalation],
        tasks=[],  # tasks are built per-ticket in route_ticket()
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
        "Decide which specialist should handle this ticket and delegate to "
        "them with enough concrete detail to act. If required information "
        "is missing or ambiguous (e.g. no identifiable server or resource), "
        "delegate to the escalation specialist instead of guessing. Pass "
        "ticket_id and ticket_number exactly as given to whichever tool "
        "ends up being called."
    )

    task = Task(
        description=description,
        expected_output=(
            "Confirmation of which specialist handled the ticket, which "
            "tool was called, and the terminal outcome (resolved, "
            "answered, or escalated)."
        ),
        guardrail=kb_output_guardrail,
    )

    logger.info("Routing ticket #%s", ticket["number"])

    _crew.tasks = [task]
    result = _crew.kickoff()

    logger.debug("Ticket #%s crew result: %s", ticket["number"], result)
    return result