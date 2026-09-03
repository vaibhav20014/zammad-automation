"""
L2 escalation. Shared terminal outcome for both the disk and KB paths
when neither can resolve the ticket.
"""

import logging
from clients import zammad_client
from config import settings

logger = logging.getLogger(__name__)


def handle(ticket_id: int, ticket_number: str, reason: str) -> dict:
    zammad_client.update_ticket(
        ticket_id,
        f"Automation: escalating to L2. Reason: {reason}",
        close=False,
        group=settings.l2_group_name,
    )
    logger.warning("Ticket #%s escalated to L2: %s", ticket_number, reason)
    return {"resolved": True, "reason": reason}