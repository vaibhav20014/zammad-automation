"""
Thin HTTP wrapper around the Zammad REST API. No business logic here -
just requests in, parsed JSON out.
"""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({
    "Authorization": f"Token token={settings.zammad_token}",
    "Content-Type": "application/json",
})


def search_tickets(query: str, limit: int = 20) -> list[dict]:
    resp = _session.get(
        f"{settings.zammad_url}/api/v1/tickets/search",
        params={"query": query, "limit": limit},
    )
    resp.raise_for_status()
    return resp.json()


def get_ticket_with_articles(ticket_id: int) -> dict:
    """
    Fetches the ticket's own top-level fields (state, group, etc.).
    NOTE: despite the name, this does NOT reliably return article
    bodies - expand=true expands relational fields, not article
    content. Use get_ticket_articles() for article data.
    """
    resp = _session.get(
        f"{settings.zammad_url}/api/v1/tickets/{ticket_id}",
        params={"expand": "true"},
    )
    resp.raise_for_status()
    return resp.json()


def get_ticket_articles(ticket_id: int) -> list[dict]:
    """
    Fetches the actual list of articles for a ticket via Zammad's
    dedicated articles endpoint.
    """
    resp = _session.get(f"{settings.zammad_url}/api/v1/ticket_articles/by_ticket/{ticket_id}")
    resp.raise_for_status()
    articles = resp.json()
    logger.debug(
        "get_ticket_articles(%s): got %d article(s). Details: %s",
        ticket_id,
        len(articles),
        [
            {
                "created_by_id": a.get("created_by_id"),
                "from": a.get("from"),
                "created_at": a.get("created_at"),
                "body_preview": (a.get("body") or "")[:80],
            }
            for a in articles
        ],
    )
    return articles


def get_first_article_body(ticket_id: int) -> str | None:
    articles = get_ticket_articles(ticket_id)
    if not articles:
        return None
    return articles[0].get("body")


def get_full_ticket_text(ticket_id: int) -> str:
    articles = get_ticket_articles(ticket_id)
    parts = []
    for article in articles:
        body = (article.get("body") or "").strip()
        if not body:
            continue
        sender = article.get("from") or "Unknown"
        created_at = article.get("created_at", "")
        parts.append(f"[{created_at}] {sender}:\n{body}")
    return "\n\n---\n\n".join(parts)


def reply_to_ticket(ticket_id: int, text: str, close: bool = False) -> bool:
    payload = {
        "ticket_id": ticket_id,
        "body": text,
        "internal": False,
        # no "type": "email" here - that requires email-channel metadata
        # a web-created ticket doesn't have, which caused a 422 earlier
    }
    resp = _session.post(f"{settings.zammad_url}/api/v1/ticket_articles", json=payload)
    if not resp.ok:
        logger.error("reply_to_ticket failed for #%s: %s %s", ticket_id, resp.status_code, resp.text)
        return False

    if close:
        return update_ticket(ticket_id, note=None, close=True)
    return True


def update_ticket(ticket_id: int, note: str | None, close: bool = False, group: str | None = None) -> bool:
    if note:
        _session.post(
            f"{settings.zammad_url}/api/v1/ticket_articles",
            json={"ticket_id": ticket_id, "body": note, "internal": True},
        )

    payload = {}
    if close:
        payload["state_id"] = 4
    if group:
        payload["group"] = group

    if not payload:
        return True

    resp = _session.put(f"{settings.zammad_url}/api/v1/tickets/{ticket_id}", json=payload)
    if not resp.ok:
        logger.error("update_ticket failed for #%s: %s %s", ticket_id, resp.status_code, resp.text)
        return False
    return True


def tag_ticket(ticket_id: int, tag: str) -> bool:
    resp = _session.post(
        f"{settings.zammad_url}/api/v1/tags/add",
        json={"object": "Ticket", "o_id": ticket_id, "item": tag},
    )
    if not resp.ok:
        logger.error("tag_ticket failed for #%s: %s %s", ticket_id, resp.status_code, resp.text)
        return False
    return True


def create_ticket(title: str, group: str, customer_id: str, body: str) -> dict | None:
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
    resp = _session.post(f"{settings.zammad_url}/api/v1/tickets", json=payload)
    if not resp.ok:
        logger.error("create_ticket failed: %s %s %s", title, resp.status_code, resp.text)
        return None
    return resp.json()


def get_current_user_id() -> int | None:
    """
    Returns the Zammad user id this API token belongs to (our
    automation account). Used to tell our own replies apart from
    customer replies on a ticket.
    """
    resp = _session.get(f"{settings.zammad_url}/api/v1/users/me")
    if not resp.ok:
        logger.error("get_current_user_id failed: %s %s", resp.status_code, resp.text)
        return None
    return resp.json().get("id")