"""
Workflow: find open disk-related Zammad tickets -> figure out which
server they're about -> run the Ansible disk-check/cleanup playbook ->
update/close the ticket accordingly.
"""

import logging
from clients import zammad_client, ansible_client
from config import settings

logger = logging.getLogger(__name__)


def load_known_servers(inventory_path: str = None) -> set[str]:
    path = inventory_path or settings.inventory_path
    servers = set()
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("[") or line.startswith("#"):
                    continue
                servers.add(line.split()[0])
    except OSError:
        logger.exception("Failed to read inventory file at %s", path)
    logger.info("Loaded %d known server(s) from inventory.", len(servers))
    return servers


def extract_server_name(title: str, body: str, known_servers: set[str]) -> str | None:
    text = f"{title} {body}".lower()
    for server in known_servers:
        if server.lower() in text:
            return server
    return None


def find_open_disk_tickets() -> list[dict]:
    query = (
        f'(title:*disk* OR title:*server*) AND state.name:(new OR open) '
        f'AND NOT tags:{settings.processed_tag}'
    )
    return zammad_client.search_tickets(query, limit=20)


def _escalate(ticket_id: int, ticket_number: str, message: str) -> None:
    success = zammad_client.update_ticket(
        ticket_id, message, close=False, group=settings.l2_group_name
    )
    logger.warning("Ticket #%s escalated to L2: %s", ticket_number, message)
    if success:
        zammad_client.tag_ticket(ticket_id, settings.processed_tag)


def handle_disk_ticket(
    ticket_id: int, ticket_number: str, title: str, body: str, known_servers: set[str]
) -> None:
    logger.info("Processing ticket #%s: %s", ticket_number, title)

    server = extract_server_name(title, body, known_servers)
    if not server:
        _escalate(
            ticket_id, ticket_number,
            "Automation: could not determine which server this ticket refers to. "
            "Escalating to L2 for manual triage.",
        )
        return

    output = ansible_client.run_disk_check(target_host=server)
    if not output:
        _escalate(
            ticket_id, ticket_number,
            f"Automation error: could not run disk check on {server}. Escalating to L2.",
        )
        return

    for play in output.get("plays", []):
        for task in play.get("tasks", []):
            task_result = task.get("hosts", {}).get(server, {})
            msg = task_result.get("msg", "")
            if "below threshold" in msg:
                success = zammad_client.update_ticket(
                    ticket_id, f"Automated check on {server}: {msg}", close=True
                )
                logger.info("Ticket #%s resolved and closed.", ticket_number)
                if success:
                    zammad_client.tag_ticket(ticket_id, settings.processed_tag)
                return

    _escalate(
        ticket_id, ticket_number,
        f"Automation attempted cleanup on {server} but could not confirm resolution. "
        f"Escalating to L2.",
    )


def run() -> None:
    known_servers = load_known_servers()
    tickets = find_open_disk_tickets()

    if not tickets:
        logger.info("No open disk-related tickets found.")
        return

    logger.info("Found %d disk-related ticket(s).", len(tickets))
    for t in tickets:
        handle_disk_ticket(
            t["id"], t["number"], t.get("title", ""), t.get("note", ""), known_servers
        )
