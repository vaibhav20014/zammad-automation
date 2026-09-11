"""
Entrypoint: finds candidate Zammad tickets and routes each one through
the ticket-routing crew (Ansible / Terraform / KB / Escalation
specialists, managed hierarchically by the router agent).
Run this on a cron/systemd timer, e.g. every 5 minutes.
"""

import logging
from logging_setup import configure_logging

configure_logging("ticket_agent.log")
logger = logging.getLogger(__name__)

from clients import zammad_client                                     # noqa: E402
from crew import ticket_crew                                           # noqa: E402

AUTOMATION_TAG = "automation-processed"


def find_candidate_tickets() -> list[dict]:
    query = f'state.name:(new OR open) AND NOT tags:{AUTOMATION_TAG}'
    return zammad_client.search_tickets(query, limit=20)


def run() -> None:
    ticket_crew.build_crew()

    tickets = find_candidate_tickets()
    if not tickets:
        logger.info("No candidate tickets found.")
        return

    logger.info("Found %d candidate ticket(s).", len(tickets))
    for t in tickets:
        ticket_text = zammad_client.get_first_article_body(t["id"]) or t.get("title", "")

        if not ticket_text.strip():
            logger.info("Ticket #%s has no usable text, skipping.", t["number"])
            continue

        try:
            result = ticket_crew.route_ticket(t, ticket_text)
            outcome = getattr(result, "raw", result)
            logger.info("Ticket #%s outcome: %s", t["number"], outcome)

            zammad_client.tag_ticket(t["id"], AUTOMATION_TAG)
        except Exception:
            logger.exception("Failed routing ticket #%s", t["number"])
            # left untagged, retried next run


if __name__ == "__main__":
    logger.info("=== Ticket router agent run starting ===")
    try:
        run()
    except Exception:
        logger.exception("Unhandled error in ticket router run")
    logger.info("=== Ticket router agent run finished ===")