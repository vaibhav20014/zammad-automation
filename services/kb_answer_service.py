"""
KB-based ticket answering. Takes the KB titles the router already
loaded once per run - no fetching KB data here.
"""

import logging
from clients import zammad_client
from ai import answer_generator

logger = logging.getLogger(__name__)


def handle(ticket_id: int, ticket_number: str, ticket_text: str, kb_titles: list[dict]) -> dict:
    if not kb_titles:
        zammad_client.reply_to_ticket(
            ticket_id,
            "Thanks for reaching out - we're looking into this and will follow up shortly.",
            close=False,
        )
        return {"resolved": False, "reason": "No KB answers available."}

    result = answer_generator.resolve_ticket(ticket_text, kb_titles)

    if result.get("can_answer") and result.get("confidence") == "high":
        zammad_client.reply_to_ticket(ticket_id, result["reply_text"], close=True)
        logger.info("Ticket #%s auto-answered from KB and closed.", ticket_number)
        return {"resolved": True, "reason": "Answered from KB."}

    if result.get("reply_text"):
        zammad_client.reply_to_ticket(ticket_id, result["reply_text"], close=False)

    zammad_client.update_ticket(
        ticket_id,
        f"Automation: KB check inconclusive (confidence={result.get('confidence')}). "
        f"Reasoning: {result.get('reasoning')}",
        close=False,
    )
    return {"resolved": False, "reason": result.get("reasoning", "Inconclusive.")}