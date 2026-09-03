"""
Disk remediation logic. No ticket discovery, no server-guessing, no
tagging here - those are the router's and tool wrapper's job. This just
does the one thing: run the check against a given server and resolve
or report back.
"""

import logging
from clients import zammad_client, ansible_client

logger = logging.getLogger(__name__)


def load_known_servers(inventory_path: str) -> set[str]:
    servers = set()
    try:
        with open(inventory_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("[") or line.startswith("#"):
                    continue
                servers.add(line.split()[0])
    except OSError:
        logger.exception("Failed to read inventory file at %s", inventory_path)
    logger.info("Loaded %d known server(s) from inventory.", len(servers))
    return servers


def handle(ticket_id: int, ticket_number: str, server_name: str) -> dict:
    output = ansible_client.run_disk_check(target_host=server_name)
    if not output:
        return {"resolved": False, "reason": f"Could not run disk check on {server_name}."}

    for play in output.get("plays", []):
        for task in play.get("tasks", []):
            task_result = task.get("hosts", {}).get(server_name, {})
            msg = task_result.get("msg", "")
            if "below threshold" in msg:
                zammad_client.update_ticket(
                    ticket_id, f"Automated check on {server_name}: {msg}", close=True
                )
                logger.info("Ticket #%s resolved and closed.", ticket_number)
                return {"resolved": True, "reason": msg}

    return {
        "resolved": False,
        "reason": f"Attempted cleanup on {server_name} but could not confirm resolution.",
    }