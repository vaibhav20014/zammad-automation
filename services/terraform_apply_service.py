"""
Explicit human-approval apply step.

An L2 agent reviews the Terraform plan in a ticket's internal note (posted
by the ticket agent when action=terraform_needs_approval) and, if they
agree, adds the tag "approved-for-apply" to that ticket in the Zammad UI.
This script — run on its own schedule, separate from run_ticket_agent.py —
looks for tickets carrying that tag, re-applies the exact plan that was
shown to the human (read back from the decision log), and reports the
result on the ticket.

Nothing in here is triggered by the AI decision loop. The tag is the gate.
"""

import json
import logging
from pathlib import Path

from catalogs import loader
from clients import terraform_client, zammad_client
from config import settings

logger = logging.getLogger(__name__)

APPROVED_TAG = "approved-for-apply"
APPLIED_TAG = "terraform-applied"


def _find_approved_tickets(limit: int = 20) -> list[dict]:
    query = f"tags:{APPROVED_TAG} AND NOT tags:{APPLIED_TAG}"
    tickets = zammad_client.search_tickets(query, limit=limit)
    logger.info("Found %d ticket(s) tagged %s.", len(tickets), APPROVED_TAG)
    return tickets


def _latest_decision_for(ticket_number: str) -> dict | None:
    """Read the decision log backwards to find the most recent
    terraform_needs_approval entry for this ticket."""
    path = Path(settings.decision_log_file)
    if not path.exists():
        return None
    match = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("ticket_number")) == str(ticket_number) and row.get(
                "terraform_module_id"
            ):
                match = row  # keep overwriting so we end up with the latest
    return match


def apply_one(ticket: dict) -> None:
    ticket_id = int(ticket["id"])
    ticket_number = str(ticket.get("number") or ticket_id)

    decision = _latest_decision_for(ticket_number)
    if not decision:
        logger.error(
            "Ticket #%s tagged approved-for-apply but no Terraform plan "
            "found in the decision log; skipping.",
            ticket_number,
        )
        zammad_client.update_ticket(
            ticket_id,
            "Automation: could not find a recorded Terraform plan for this "
            "ticket. Please have the ticket agent re-run first.",
            close=False,
        )
        return

    module_id = decision["terraform_module_id"]
    module = loader.module_by_id(module_id)
    if not module:
        logger.error("Ticket #%s: unknown module_id '%s'.", ticket_number, module_id)
        return

    tf_vars = {"aws_region": settings.aws_region}
    if decision.get("terraform_instance_type"):
        tf_vars["instance_type"] = decision["terraform_instance_type"]
    if decision.get("terraform_vm_name"):
        tf_vars["vm_name"] = decision["terraform_vm_name"]

    logger.info(
        "Applying module=%s for ticket #%s with vars=%s",
        module_id, ticket_number, tf_vars,
    )
    result = terraform_client.apply_module(module["path"], tf_vars=tf_vars)

    if not result.get("applied"):
        note = (
            f"Terraform apply FAILED for module '{module_id}'.\n"
            f"{(result.get('stderr') or result.get('error') or '')[-1500:]}"
        )
        zammad_client.update_ticket(ticket_id, note, close=False)
        logger.error("Ticket #%s: apply failed.", ticket_number)
        return

    outputs = result.get("outputs") or {}
    outputs_lines = "\n".join(
        f"- {k}: {v.get('value')}" for k, v in outputs.items()
    ) or "(no outputs defined)"
    note = (
        f"Terraform apply succeeded for module '{module_id}'.\n"
        f"Outputs:\n{outputs_lines}"
    )
    zammad_client.update_ticket(ticket_id, note, close=True)
    zammad_client.tag_ticket(ticket_id, APPLIED_TAG)
    logger.info("Ticket #%s: applied and closed.", ticket_number)


def run() -> None:
    tickets = _find_approved_tickets()
    if not tickets:
        logger.info("No tickets awaiting approved Terraform apply.")
        return
    for t in tickets:
        apply_one(t)