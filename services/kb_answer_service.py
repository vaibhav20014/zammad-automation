"""
KB-based ticket answering. In the CrewAI architecture, agents/kb_agent.py
does the actual title-selection/content-fetch/reply-drafting as part of
its own task execution - this function only takes that already-produced
result and applies it to the ticket (reply, close, or leave for review).
No longer calls a nested agent itself.
"""

import logging
from clients import zammad_client

logger = logging.getLogger(__name__)


def handle(ticket_id: int, ticket_number: str, kb_result: dict) -> dict:
    """kb_result is the already-parsed output from the KB agent's task
    (via ai.answer_generator.parse_kb_result), not raw ticket text/titles
    anymore - kb_agent.py owns that reasoning now."""
    if kb_result.get("can_answer") and kb_result.get("confidence") == "high":
        zammad_client.reply_to_ticket(ticket_id, kb_result["reply_text"], close=True)
        logger.info("Ticket #%s auto-answered from KB and closed.", ticket_number)
        return {"resolved": True, "reason": "Answered from KB."}

    if kb_result.get("reply_text"):
        zammad_client.reply_to_ticket(ticket_id, kb_result["reply_text"], close=False)

    zammad_client.update_ticket(
        ticket_id,
        f"Automation: KB check inconclusive (confidence={kb_result.get('confidence')}). "
        f"Reasoning: {kb_result.get('reasoning')}",
        close=False,
    )
    return {"resolved": False, "reason": kb_result.get("reasoning", "Inconclusive.")}