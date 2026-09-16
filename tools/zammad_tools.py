"""
Zammad-facing tools - native CrewAI tools. Each tool tags the ticket
with the outcome that actually happened, since parsing the crew's
final text summary to figure out what really occurred is unreliable.
"""

import logging
from crewai.tools import tool
from clients import zammad_client

logger = logging.getLogger(__name__)

AWAITING_REPLY_TAG = "awaiting-customer-reply"
AUTOMATION_DONE_TAG = "automation-processed"


@tool("ask_for_more_details")
def ask_for_more_details(ticket_id: int, question: str) -> str:
    """
    Sends a public reply to the ticket asking the customer for the
    specific missing information needed to proceed. Use this INSTEAD
    of guessing a value. Does not close the ticket - it will be
    re-checked automatically once the customer replies.
    """
    logger.info("ask_for_more_details CALLED for ticket #%s: %s", ticket_id, question)
    success = zammad_client.reply_to_ticket(ticket_id, question, close=False)
    if success:
        zammad_client.tag_ticket(ticket_id, AWAITING_REPLY_TAG)
        logger.info("ask_for_more_details SUCCEEDED for ticket #%s, tagged awaiting reply", ticket_id)
        return f"Ticket #{ticket_id}: sent clarification request; will re-check once customer replies."
    logger.error("ask_for_more_details FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to send clarification request - do not assume it was received."


@tool("post_kb_answer")
def post_kb_answer(ticket_id: int, answer_text: str, close: bool) -> str:
    """
    Posts a drafted answer back to the ticket as a public reply. Set
    close=True only if confident the answer fully resolves the ticket.
    """
    logger.info("post_kb_answer CALLED for ticket #%s (close=%s)", ticket_id, close)
    success = zammad_client.reply_to_ticket(ticket_id, answer_text, close=close)
    if success:
        zammad_client.tag_ticket(ticket_id, AUTOMATION_DONE_TAG)
        logger.info("post_kb_answer SUCCEEDED for ticket #%s", ticket_id)
        return f"Ticket #{ticket_id}: answer posted (closed={close})."
    logger.error("post_kb_answer FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to post answer - do not assume it was received."


def get_tools() -> list:
    return [ask_for_more_details, post_kb_answer]