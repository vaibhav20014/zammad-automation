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
from kb import knowledge_base_client                                   # noqa: E402
from services.disk_ticket_service import load_known_servers            # noqa: E402
from crew import ticket_crew                                           # noqa: E402
from config import settings                                            # noqa: E402

# NOTE: unconfirmed -- assumes each tools/ module exposes its own
# configure() the same way the old flat tools.configure() did. If the
# real per-domain tool modules use different function/param names,
# update these two lines to match.
from tools import ansible_tools, kb_tools                              # noqa: E402

AUTOMATION_TAG = "automation-processed"


def find_candidate_tickets() -> list[dict]:
    query = f'state.name:(new OR open) AND NOT tags:{AUTOMATION_TAG}'
    return zammad_client.search_tickets(query, limit=20)


def run() -> None:
    known_servers = load_known_servers(settings.inventory_path)
    kb_titles = knowledge_base_client.list_all_answers()

    # NOTE: unconfirmed signatures -- see module-level comment above.
    ansible_tools.configure(known_servers)
    kb_tools.configure(kb_titles)

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
            # NOTE: Crew.kickoff() returns a CrewOutput object in current
            # CrewAI versions, not a plain dict -- .raw is the usual way
            # to get the underlying text/result out. Verify against your
            # installed crewai version; adjust if the attribute differs.
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