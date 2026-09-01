"""
Workflow: log into Zabbix -> fetch open problems -> for any not already
processed, resolve the hostname and create a Zammad ticket -> record it
as processed so we don't duplicate tickets on the next run.
"""

import logging
from datetime import datetime, timezone

from clients import zabbix_client, zammad_client
from state import processed_events_store
from config import settings

logger = logging.getLogger(__name__)


def _create_ticket_for_problem(hostname: str, problem_name: str) -> dict | None:
    title = f"Disk space warning on {hostname}"
    return zammad_client.create_ticket(
        title=title,
        group=settings.l1_group_name,
        customer_id="guess:zabbix@yourdomain.com",
        body=f"Zabbix alert: {problem_name} on host {hostname}.",
    )


def run() -> None:
    auth_token = zabbix_client.login()
    if not auth_token:
        logger.error("Zabbix login failed; aborting this run.")
        return

    problems = zabbix_client.get_problems(auth_token)
    processed = processed_events_store.load()

    new_count = 0
    for p in problems:
        event_id = p["eventid"]
        if event_id in processed:
            continue

        hostname = zabbix_client.get_hostname_for_trigger(auth_token, p["objectid"])
        problem_name = p.get("name", "Disk issue")
        logger.info("New Zabbix event %s: host=%s problem=%s", event_id, hostname, problem_name)

        ticket = _create_ticket_for_problem(hostname, problem_name)

        processed[event_id] = {
            "hostname": hostname,
            "problem_name": problem_name,
            "ticket_number": ticket.get("number") if ticket else None,
            "ticket_id": ticket.get("id") if ticket else None,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "ticket_created": ticket is not None,
        }
        new_count += 1

    processed_events_store.save(processed)
    logger.info("Processed %d new Zabbix problem(s).", new_count)
