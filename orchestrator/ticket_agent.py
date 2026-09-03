"""
The ticket-routing agent. Built once per run via build_agent(), reused
for every candidate ticket. Tools take ticket_id/ticket_number explicitly
since the agent instance isn't rebuilt per ticket.
"""

import logging
from langchain.agents import create_agent
from orchestrator import tools
from config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You triage Zammad support tickets. For each ticket, decide whether to "
    "run a disk check, answer from the knowledge base, or escalate to L2. "
    "You will be given the ticket_id and ticket_number - pass them exactly "
    "as given to whichever tool you call.\n\n"
    "Default to checking the knowledge base (answer_from_kb) for any ticket "
    "that isn't clearly a disk/storage issue - this includes tickets phrased "
    "as action requests (password resets, access requests, setup tasks), not "
    "just questions. The KB may have a documented self-service procedure even "
    "when the ticket reads like a request for someone else to do something. "
    "Only skip straight to escalation, without trying the KB first, when the "
    "ticket is a disk issue you can't identify a server for, or clearly "
    "requires human judgment (e.g. account/billing disputes, HR matters).\n\n"
    "You may call more than one tool in sequence - for example, try a disk "
    "check and then escalate if it didn't resolve the issue, or try the KB "
    "and then escalate if the KB check comes back inconclusive. Always end "
    "by calling exactly one tool that produces a terminal outcome for the "
    "ticket. Do not answer in plain text without calling a tool."
)

_agent = None


def build_agent():
    global _agent
    _agent = create_agent(
        model=settings.model,
        tools=[tools.run_disk_check, tools.answer_from_kb, tools.escalate_to_l2],
        system_prompt=SYSTEM_PROMPT,
    )
    return _agent


def route_ticket(ticket: dict, ticket_text: str) -> dict:
    if _agent is None:
        raise RuntimeError("Agent not built - call build_agent() once per run before routing tickets.")

    prompt = (
        f"ticket_id: {ticket['id']}\n"
        f"ticket_number: {ticket['number']}\n"
        f"Title: {ticket.get('title', '')}\n"
        f"Body: {ticket_text}"
    )
    logger.info("Routing ticket #%s", ticket["number"])

    result = _agent.invoke({"messages": [{"role": "user", "content": prompt}]})

    logger.debug("Ticket #%s agent transcript: %s", ticket["number"], result)
    return result