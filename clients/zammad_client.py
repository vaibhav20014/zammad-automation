"""
All Zammad API calls live here. Nothing in this file decides *what* to do
with a ticket — it only knows how to talk to Zammad.
"""
import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Token token={settings.zammad_token}",
    "Content-Type": "application/json",
}


def _article_payload(body: str, internal: bool) -> dict:
    return {
        "body": body,
        "type": "note",
        "internal": internal,
        "content_type": "text/html",
    }


def _normalize_search_results(results) -> list[dict]:
    if isinstance(results, list):
        return [t for t in results if isinstance(t, dict)]
    if not isinstance(results, dict):
        return []
    tickets = results.get("tickets")
    if isinstance(tickets, list) and tickets and isinstance(tickets[0], dict):
        return tickets
    assets = (results.get("assets") or {}).get("Ticket") or {}
    if isinstance(assets, dict) and assets:
        return list(assets.values())
    if isinstance(tickets, list) and tickets and isinstance(tickets[0], int):
        loaded = []
        for ticket_id in tickets:
            ticket = get_ticket_with_articles(ticket_id)
            if ticket:
                loaded.append(ticket)
        return loaded
    return []


def search_tickets(query: str, limit: int = 20) -> list[dict]:
    url = f"{settings.zammad_url}/api/v1/tickets/search"
    params = {"query": query, "limit": limit, "expand": "true"}
    logger.debug("Searching tickets with query=%s", query)

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        results = _normalize_search_results(response.json())
        logger.info("Ticket search returned %d result(s).", len(results))
        return results
    except requests.RequestException:
        logger.exception("Ticket search failed for query=%s", query)
        return []


def list_tickets(page: int = 1, per_page: int = 100) -> list[dict]:
    url = f"{settings.zammad_url}/api/v1/tickets"
    params = {"page": page, "per_page": per_page, "expand": "true"}
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return [t for t in data if isinstance(t, dict)]
        logger.warning("Unexpected tickets list payload type: %s", type(data).__name__)
        return []
    except requests.RequestException:
        logger.exception("Failed to list tickets page=%s", page)
        return []


def get_ticket_tags(ticket_id: int) -> list[str]:
    url = f"{settings.zammad_url}/api/v1/tags"
    params = {"object": "Ticket", "o_id": ticket_id}
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            tags = data.get("tags") or []
            return [str(t) for t in tags]
        if isinstance(data, list):
            return [str(t) for t in data]
        return []
    except requests.RequestException:
        logger.exception("Failed to fetch tags for ticket #%s", ticket_id)
        return []


def update_ticket(
    ticket_id: int, note: str, close: bool = False, group: str | None = None
) -> bool:
    url = f"{settings.zammad_url}/api/v1/tickets/{ticket_id}"
    payload = {"article": _article_payload(note, internal=True)}
    if close:
        payload["state_id"] = 4
    if group:
        payload["group"] = group

    try:
        response = requests.put(url, headers=HEADERS, json=payload, timeout=15)
        if not response.ok:
            logger.error(
                "Failed to update ticket #%s: %s %s",
                ticket_id, response.status_code, response.text,
            )
            return False
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
    params = {"expand": "true"}
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        logger.exception("Failed to fetch ticket #%s with articles", ticket_id)
        return None


def get_ticket_articles(ticket_id: int) -> list[dict]:
    url = f"{settings.zammad_url}/api/v1/ticket_articles/by_ticket/{ticket_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except requests.RequestException:
        logger.exception("Failed to fetch articles for ticket #%s", ticket_id)
        return []


def get_ticket_text(ticket_id: int, fallback_title: str = "") -> str:
    """
    Title plus article bodies for the model. expand=true on the ticket
    endpoint often omits articles, so we also call by_ticket.
    """
    ticket = get_ticket_with_articles(ticket_id) or {}
    title = (ticket.get("title") or fallback_title or "").strip()
    articles = ticket.get("articles") or []
    if not articles:
        articles = get_ticket_articles(ticket_id)
    bodies = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        body = (article.get("body") or "").strip()
        if body:
            bodies.append(body)
    parts = [p for p in [title, *bodies] if p]
    return "\n\n".join(parts)


def get_first_article_body(ticket_id: int) -> str:
    """
    Convenience: pulls the opening customer message as text for the model.
    """
    return get_ticket_text(ticket_id)


def reply_to_ticket(ticket_id: int, message: str, close: bool = False) -> bool:
    """
    Posts a PUBLIC (customer-visible) reply to a ticket.
    Distinct from update_ticket() which always posts internal notes.
    """
    url = f"{settings.zammad_url}/api/v1/tickets/{ticket_id}"
    payload = {"article": _article_payload(message, internal=False)}
    if close:
        payload["state_id"] = 4

    try:
        response = requests.put(url, headers=HEADERS, json=payload, timeout=15)
        if not response.ok:
            logger.error(
                "Failed to post public reply to ticket #%s: %s %s",
                ticket_id, response.status_code, response.text,
            )
            return False
        logger.info("Public reply posted to ticket #%s (close=%s).", ticket_id, close)
        return True
    except requests.RequestException:
        logger.exception("Failed to post public reply to ticket #%s", ticket_id)
        return False
