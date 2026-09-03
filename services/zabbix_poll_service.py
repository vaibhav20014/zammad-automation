"""
Polls Zabbix for active problems and creates a Zammad ticket for each
one not already seen, using processed_events_store to avoid duplicates
across runs.
"""

import logging
from clients import zabbix_client, zammad_client
from state import processed_events_store
from config import settings

logger = logging.getLogger(__name__)


def _build_ticket_payload(problem: dict) -> dict:
    host = problem.get("hosts", [{}])[0].get("name", "unknown host")
    title = f"[Zabbix] {problem.get('name', 'Unknown problem')} on {host}"
    body = (
        f"Zabbix problem detected.\n\n"
        f"Host: {host}\n"
        f"Severity: {problem.get('severity')}\n"
        f"Time: {problem.get('clock')}\n"
        f"Event ID: {problem.get('eventid')}"
    )
    return {
        "title": title,
        "group": settings.default_group_name,
        "customer_id": settings.default_customer_id,
        "body": body,
    }


def run() -> None:
    problems = zabbix_client.get_active_problems()
    if not problems:
        logger.info("No active Zabbix problems found.")
        return

    new_count = 0
    for problem in problems:
        event_id = problem.get("eventid")
        if processed_events_store.is_processed(event_id):
            continue

        payload = _build_ticket_payload(problem)
        created = zammad_client.create_ticket(**payload)
        if created:
            processed_events_store.mark_processed(event_id)
            new_count += 1
        else:
            logger.error("Failed to create ticket for Zabbix event %s", event_id)

    logger.info("Created %d new ticket(s) from %d active problem(s).", new_count, len(problems))