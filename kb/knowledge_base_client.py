"""
STUB for future work: connecting to Zammad's Knowledge Base to
auto-answer tickets.

Planned flow (not yet implemented):
  1. search_kb(query) -> hits Zammad's KB search API for relevant articles
  2. build_answer(ticket_text, kb_hits) -> uses an LLM to draft a reply
     grounded in the retrieved articles
  3. Wire this into a new services/auto_answer_service.py that:
       - pulls new/open tickets (reuse zammad_client.search_tickets)
       - calls search_kb() with the ticket's text
       - if confidence is high enough, calls zammad_client.update_ticket()
         with the drafted reply (internal=True first, for human review)
       - otherwise escalates, same pattern as disk_ticket_service._escalate()

Keeping this as its own client module means the disk-ticket and
zabbix-poll workflows never need to change when this lands.
"""

import logging
from config import settings

logger = logging.getLogger(__name__)


def search_kb(query: str, limit: int = 5) -> list[dict]:
    """
    TODO: implement against Zammad's KB search endpoint, e.g.
    GET {ZAMMAD_URL}/api/v1/knowledge_bases/{id}/search?query=...
    """
    logger.warning("search_kb() is not yet implemented. query=%s", query)
    return []
