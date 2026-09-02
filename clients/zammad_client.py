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

def get_ticket_with_articles(ticket_id: int) -> dict | None:
    """
    Fetches full ticket detail including its articles (needed to get
    the actual customer message body, not just the title).
    """
    url = f"{settings.zammad_url}/api/v1/tickets/{ticket_id}"
    params = {"expand": "true"}  # includes articles in response
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        logger.exception("Failed to fetch ticket #%s with articles", ticket_id)
        return None


def get_first_article_body(ticket_id: int) -> str:
    """
    Convenience: pulls the first (usually the opening customer message)
    article body as plain-ish text for feeding to the AI model.
    """
    ticket = get_ticket_with_articles(ticket_id)
    if not ticket:
        return ""
    articles = ticket.get("articles", [])
    if not articles:
        return ""
    return articles[0].get("body", "")

def reply_to_ticket(ticket_id: int, message: str, close: bool = False) -> bool:
    """
    Posts a PUBLIC (customer-visible) reply to a ticket.
    Distinct from update_ticket() which always posts internal notes.
    """
    url = f"{settings.zammad_url}/api/v1/tickets/{ticket_id}"
    payload = {"article": {"body": message, "internal": False}}
    if close:
        payload["state_id"] = 4

    try:
        response = requests.put(url, headers=HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        logger.info("Public reply posted to ticket #%s (close=%s).", ticket_id, close)
        return True
    except requests.RequestException:
        logger.exception("Failed to post public reply to ticket #%s", ticket_id)
        return False
