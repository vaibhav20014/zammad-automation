"""
Unified ticket queue: new/open tickets the agent has not finished.

Customer email/portal tickets are ingested by Zammad itself. Zabbix
tickets are created by zabbix_poll_service. This module is the shared
queue reader for the decision center.
"""

import logging

from clients import zammad_client
from config import settings

logger = logging.getLogger(__name__)

KB_CHECKED_TAG = "kb-auto-checked"
_OPEN_STATE_IDS = {1, 2}
_OPEN_STATE_NAMES = {"new", "open"}


def _skip_tags() -> set[str]:
    return {
        settings.agent_handled_tag.lower(),
        settings.processed_tag.lower(),
        KB_CHECKED_TAG.lower(),
    }


def _state_name(ticket: dict) -> str:
    state = ticket.get("state")
    if isinstance(state, dict):
        return str(state.get("name") or "").strip().lower()
    return str(state or "").strip().lower()


def _is_open(ticket: dict) -> bool:
    state_id = ticket.get("state_id")
    try:
        if int(state_id) in _OPEN_STATE_IDS:
            return True
    except (TypeError, ValueError):
        pass
    return _state_name(ticket) in _OPEN_STATE_NAMES


def _ticket_tags(ticket: dict) -> set[str]:
    raw = ticket.get("tags") or []
    tags = {str(t).lower() for t in raw if t}
    if tags:
        return tags
    ticket_id = ticket.get("id")
    if not ticket_id:
        return set()
    return {t.lower() for t in zammad_client.get_ticket_tags(int(ticket_id))}


def _not_already_handled(ticket: dict) -> bool:
    return _ticket_tags(ticket).isdisjoint(_skip_tags())


def find_candidate_tickets(limit: int = 20) -> list[dict]:
    query = "state.name:new OR state.name:open"
    tickets = zammad_client.search_tickets(query, limit=100)
    tickets = [t for t in tickets if _is_open(t) and _not_already_handled(t)]

    if not tickets:
        logger.info(
            "Search found no unhandled new/open tickets; listing via REST as a fallback."
        )
        listed = []
        page = 1
        while page <= 10:
            batch = zammad_client.list_tickets(page=page, per_page=100)
            if not batch:
                break
            listed.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        open_tickets = [t for t in listed if _is_open(t)]
        tagged = [t for t in open_tickets if not _not_already_handled(t)]
        tickets = [t for t in open_tickets if _not_already_handled(t)]
        logger.info(
            "REST list: %d ticket(s) total, %d new/open, %d already tagged, %d candidates.",
            len(listed),
            len(open_tickets),
            len(tagged),
            len(tickets),
        )
        if not listed:
            logger.info(
                "Zammad has no tickets the API can see. Zabbix warnings are not "
                "tickets until you run: python ./run_zabbix_agent.py"
            )
        elif not open_tickets:
            logger.info("Zammad has tickets, but none are in state new/open.")
        elif not tickets:
            logger.info(
                "Open tickets exist but are tagged %s / %s / %s, so the agent skips them.",
                settings.agent_handled_tag,
                settings.processed_tag,
                KB_CHECKED_TAG,
            )

    tickets = tickets[:limit]
    logger.info("Ticket queue returned %d candidate(s).", len(tickets))
    return tickets
