"""
All Zammad API calls live here. Nothing in this file decides *what* to do
with a ticket — it only knows how to talk to Zammad.

This is the module you'll reuse later for the knowledge-base auto-answer
feature (e.g. add `post_public_reply()` or `get_ticket_full_text()`).
"""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Token token={settings.zammad_token}",
    "Content-Type": "application/json",
}


def search_tickets(query: str, limit: int = 20) -> list[dict]:
    url = f"{settings.zammad_url}/api/v1/tickets/search"
    params = {"query": query, "limit": limit}
    logger.debug("Searching tickets with query=%s", query)

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        results = response.json()
        logger.info("Ticket search returned %d result(s).", len(results))
        return results
    except requests.RequestException:
        logger.exception("Ticket search failed for query=%s", query)
        return []


def update_ticket(
    ticket_id: int, note: str, close: bool = False, group: str | None = None
) -> bool:
    url = f"{settings.zammad_url}/api/v1/tickets/{ticket_id}"
    payload = {"article": {"body": note, "internal": True}}
    if close:
        payload["state_id"] = 4
    if group:
        payload["group"] = group

    try:
        response = requests.put(url, headers=HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        logger.info("Ticket #%s updated (close=%s, group=%s).", ticket_id, close, group)
        return True
    except requests.RequestException:
        logger.exception("Failed to update ticket #%s", ticket_id)
        return False


def tag_ticket(ticket_id: int, tag: str) -> bool:
    url = f"{settings.zammad_url}/api/v1/tags/add"
    payload = {"object": "Ticket", "o_id": ticket_id, "item": tag}

    try:
        response = requests.post(url, headers=HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        logger.info("Tagged ticket #%s with '%s'.", ticket_id, tag)
        return True
    except requests.RequestException:
        logger.exception("Failed to tag ticket #%s with '%s'", ticket_id, tag)
        return False


def create_ticket(title: str, group: str, customer_id: str, body: str) -> dict | None:
    url = f"{settings.zammad_url}/api/v1/tickets"
    payload = {
        "title": title,
        "group": group,
        "customer_id": customer_id,
        "article": {
            "subject": title,
            "body": body,
            "type": "note",
            "internal": True,
        },
    }

    try:
        response = requests.post(url, headers=HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        logger.info("Created ticket #%s: %s", data.get("number"), title)
        return data
    except requests.RequestException:
        logger.exception("Failed to create ticket: %s", title)
        return None
