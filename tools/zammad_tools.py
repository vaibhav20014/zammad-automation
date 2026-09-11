"""
Zammad-facing tools: gives any specialist agent a way to ask the
customer for missing details, rather than guessing a hostname or
skipping a ticket silently. Shared across specialists (not
Linux/Windows-specific) since any tool with required params can hit
this same "info missing" situation.

Run standalone to serve tools: python tools/zammad_tools.py
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clients import zammad_client
from crewai.tools import tool

logger = logging.getLogger(__name__)


@tool
def ask_for_more_details(ticket_id: int, question: str) -> str:
    """
    Sends a public reply to the ticket asking the customer for the
    specific missing information needed to proceed...
    """

    logger.info("ask_for_more_details CALLED for ticket #%s: %s", ticket_id, question)
    success = zammad_client.reply_to_ticket(ticket_id, question, close=False)
    if success:
        logger.info("ask_for_more_details SUCCEEDED for ticket #%s", ticket_id)
        return f"Ticket #{ticket_id}: sent clarification request to customer."
    logger.error("ask_for_more_details FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to send clarification request - do not assume it was received."

@tool
def post_kb_answer(ticket_id: int, answer_text: str, close: bool) -> str:
    """
    Posts a drafted answer back to the ticket as a public reply. Set
    close=True only if you are confident the answer fully resolves the
    ticket; set close=False if you're posting a partial or low-
    confidence answer that should still be reviewed by a human.
    """
    logger.info("post_kb_answer CALLED for ticket #%s (close=%s)", ticket_id, close)
    success = zammad_client.reply_to_ticket(ticket_id, answer_text, close=close)
    if success:
        logger.info("post_kb_answer SUCCEEDED for ticket #%s", ticket_id)
        return f"Ticket #{ticket_id}: answer posted (closed={close})."
    logger.error("post_kb_answer FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to post answer - do not assume it was received."

def get_tools() -> list:
    """Returns the tool list for the Ansible agent's `tools=` field."""
    return [
        ask_for_more_details,
        post_kb_answer
    ]