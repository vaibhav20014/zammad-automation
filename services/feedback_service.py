"""
Feedback loop: persist routing outcomes and ack Zabbix when automation
closes an incident ticket.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from clients import zabbix_client
from config import settings

logger = logging.getLogger(__name__)

_EVENT_RE = re.compile(r"Event ID:\s*(\d+)", re.IGNORECASE)


def extract_event_id(ticket_text: str) -> str | None:
    match = _EVENT_RE.search(ticket_text or "")
    return match.group(1) if match else None


def record_decision(
    ticket_id: int,
    ticket_number: str,
    action: str,
    decision: dict,
    ticket_text: str = "",
) -> None:
    path = Path(settings.decision_log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "ticket_id": ticket_id,
        "ticket_number": ticket_number,
        "action": action,
        "confidence": decision.get("confidence"),
        "reasoning": decision.get("reasoning"),
        "used_article_ids": decision.get("used_article_ids") or [],
        "ansible_host": decision.get("ansible_host"),
        "ansible_playbook_id": decision.get("ansible_playbook_id"),
        "terraform_module_id": decision.get("terraform_module_id"),
        "terraform_instance_type": decision.get("terraform_instance_type"),   # ADD
        "terraform_vm_name": decision.get("terraform_vm_name"),               # ADD
        "zabbix_event_id": extract_event_id(ticket_text),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        logger.exception("Failed to append decision log at %s", path)


def ack_zabbix_if_resolved(ticket_text: str, action: str, ticket_number: str) -> None:
    if action not in {"ansible_resolved", "terraform_resolved", "kb_answer"}:
        return
    event_id = extract_event_id(ticket_text)
    if not event_id:
        return
    if not settings.zabbix_url:
        return
    token = zabbix_client.login()
    if not token:
        return
    zabbix_client.acknowledge_event(
        token,
        event_id,
        f"Zammad ticket #{ticket_number} resolved by automation action={action}",
    )
