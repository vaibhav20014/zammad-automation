"""
Ingest Zabbix problems into Zammad as generic incident tickets.

Dedupes via processed_events_file so the same eventid is not ticketed twice.
"""

import logging
from datetime import datetime, timezone

from clients import zabbix_client, zammad_client
from state import processed_events_store
from config import settings

logger = logging.getLogger(__name__)


def _ticket_body(hostname: str, problem: dict) -> str:
    event_id = problem.get("eventid", "")
    severity = zabbix_client.severity_label(problem.get("severity"))
    name = problem.get("name", "Zabbix problem")
    return (
        f"Zabbix alert: {name}\n"
        f"Host: {hostname}\n"
        f"Event ID: {event_id}\n"
        f"Severity: {severity}\n"
        f"Trigger ID: {problem.get('objectid', '')}\n"
    )


def _create_ticket_for_problem(hostname: str, problem: dict) -> dict | None:
    name = problem.get("name", "Zabbix problem")
    title = f"[Zabbix] {name} on {hostname}"
    return zammad_client.create_ticket(
        title=title[:200],
        group=settings.l1_group_name,
        customer_id=settings.zabbix_customer_id,
        body=_ticket_body(hostname, problem),
    )


def run() -> None:
    if not settings.zabbix_url:
        logger.error("ZABBIX_URL is not set; aborting this run.")
        return

    auth_token = zabbix_client.login()
    if not auth_token:
        logger.error("Zabbix login failed; aborting this run.")
        return

    problems = zabbix_client.get_problems(auth_token)
    processed = processed_events_store.load()

    new_count = 0
    for p in problems:
        event_id = str(p["eventid"])
        if event_id in processed:
            continue

        hostname = zabbix_client.get_hostname_for_trigger(auth_token, p["objectid"])
        problem_name = p.get("name", "Zabbix problem")
        logger.info("New Zabbix event %s: host=%s problem=%s", event_id, hostname, problem_name)

        ticket = _create_ticket_for_problem(hostname, p)

        processed[event_id] = {
            "hostname": hostname,
            "problem_name": problem_name,
            "severity": zabbix_client.severity_label(p.get("severity")),
            "ticket_number": ticket.get("number") if ticket else None,
            "ticket_id": ticket.get("id") if ticket else None,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "ticket_created": ticket is not None,
        }
        new_count += 1

    processed_events_store.save(processed)
    logger.info("Processed %d new Zabbix problem(s).", new_count)
