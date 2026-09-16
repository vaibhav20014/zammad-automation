"""
Entrypoint: finds candidate Zammad tickets and routes each one through
the ticket-routing crew. Handles two ticket populations each run:
  1. Brand new tickets (no tags at all) - only the first article/title
     is used, since there's no prior thread yet.
  2. Tickets tagged awaiting-customer-reply - full article thread is
     fetched only for these, to check if the customer's last message
     is new and re-route with full context if so.
Run this on a cron/systemd timer, e.g. every 5 minutes.
"""

import logging
from logging_setup import configure_logging

configure_logging("ticket_agent.log")
logger = logging.getLogger(__name__)

from clients import zammad_client                                     # noqa: E402
from crew import ticket_crew                                           # noqa: E402
from tools.zammad_tools import AWAITING_REPLY_TAG, AUTOMATION_DONE_TAG, SPAM_TAG  # noqa: E402

_OUR_USER_ID = None


def find_new_tickets() -> list[dict]:
    query = f'state.name:(new OR open) AND NOT tags:{AUTOMATION_DONE_TAG} AND NOT tags:{AWAITING_REPLY_TAG} AND NOT tags:{SPAM_TAG}'
    return zammad_client.search_tickets(query, limit=20)


def find_awaiting_reply_tickets() -> list[dict]:
    query = f'state.name:(new OR open) AND tags:{AWAITING_REPLY_TAG}'
    return zammad_client.search_tickets(query, limit=20)


def _process_ticket(t: dict, ticket_text: str) -> None:
    try:
        result = ticket_crew.route_ticket(t, ticket_text)
        outcome = getattr(result, "raw", result)
        logger.info("Ticket #%s outcome: %s", t["number"], outcome)
    except Exception:
        logger.exception("Failed routing ticket #%s", t["number"])


def run() -> None:
    global _OUR_USER_ID
    _OUR_USER_ID = zammad_client.get_current_user_id()
    if _OUR_USER_ID is None:
        logger.error("Could not resolve our own Zammad user id - skipping this run.")
        return
    
    ticket_crew.build_crew()

    # --- Phase 1: brand new tickets - first article only ---
    new_tickets = find_new_tickets()
    logger.info("Found %d new candidate ticket(s).", len(new_tickets))
    for t in new_tickets:
        ticket_text = zammad_client.get_first_article_body(t["id"]) or t.get("title", "")
        if not ticket_text.strip():
            logger.info("Ticket #%s has no usable text, skipping.", t["number"])
            continue
        _process_ticket(t, ticket_text)

    # --- Phase 2: awaiting-customer-reply tickets - full thread only here ---
    awaiting_tickets = find_awaiting_reply_tickets()
    logger.info("Found %d ticket(s) awaiting customer reply.", len(awaiting_tickets))
    for t in awaiting_tickets:
        articles = zammad_client.get_ticket_articles(t["id"])
        if not articles:
            continue

        last_article = articles[-1]
        last_author_id = last_article.get("created_by_id")

        if last_author_id == _OUR_USER_ID:
            logger.info("Ticket #%s: still waiting, last article is ours.", t["number"])
            continue

        full_text = zammad_client.get_full_ticket_text(t["id"])
        logger.info("Ticket #%s: new reply detected, re-routing.", t["number"])
        _process_ticket(t, full_text)


if __name__ == "__main__":
    logger.info("=== Ticket router agent run starting ===")
    try:
        run()
    except Exception:
        logger.exception("Unhandled error in ticket router run")
    logger.info("=== Ticket router agent run finished ===")