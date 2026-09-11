"""
Customer-confirmation gate for infra-creation tickets.

Runs BEFORE run_ticket_agent.py in the cron order. It intercepts
infra-creation tickets (aws_vm etc.) before the AI router ever touches
them, proposes the values it detected to the CUSTOMER, and waits for an
explicit reply. Only once the customer confirms does it run a real
terraform plan and hand off to the existing L2-approval-to-apply flow.
"""

import logging
import re

from catalogs import loader
from clients import terraform_client, zammad_client
from config import settings
from services import feedback_service

logger = logging.getLogger(__name__)

AWAITING_TAG = "awaiting-customer-confirmation"
CONFIRMED_TAG = "customer-confirmed"
DECLINED_TAG = "confirmation-declined"
PAUSE_TAG = "agent-handled"

_YES_RE = re.compile(r"\b(yes|confirm|confirmed|approve|approved|go ahead|proceed)\b", re.IGNORECASE)
_NO_RE = re.compile(r"\b(no|cancel|stop|don't|do not|decline)\b", re.IGNORECASE)

_VCPU_RE = re.compile(r"(\d+)\s*v?cpu", re.IGNORECASE)
_MEM_RE = re.compile(r"(\d+)\s*(?:gb|g)\s*(?:ram|memory)?", re.IGNORECASE)


def _extract_size(text: str, module: dict) -> dict | None:
    vcpu_match = _VCPU_RE.search(text)
    mem_match = _MEM_RE.search(text)
    if not vcpu_match or not mem_match:
        return None
    vcpu = int(vcpu_match.group(1))
    mem = int(mem_match.group(1))
    instance_type = terraform_client.resolve_instance_type(module, vcpu, mem)
    if not instance_type:
        return None
    return {"vcpu": vcpu, "memory_gb": mem, "instance_type": instance_type}


def _matches_module_keywords(text: str, module: dict) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in module.get("keywords") or [])


def stage_propose() -> None:
    for module in loader.terraform_modules():
        if not module.get("allowed_sizes"):
            continue
        single_word_keywords = [kw for kw in (module.get("keywords") or []) if " " not in kw]
        if not single_word_keywords:
            continue
        keyword_query = " OR ".join(f'title:*{kw}*' for kw in single_word_keywords)
        query = (
            f"({keyword_query}) AND state.name:(new OR open) "
            f"AND NOT tags:{PAUSE_TAG} AND NOT tags:{AWAITING_TAG}"
        )
        tickets = zammad_client.search_tickets(query, limit=20)
        for t in tickets:
            ticket_id = int(t["id"])
            ticket_number = str(t.get("number") or ticket_id)
            text = zammad_client.get_ticket_text(ticket_id, fallback_title=t.get("title", ""))

            if not _matches_module_keywords(text, module):
                continue

            size = _extract_size(text, module)
            if not size:
                logger.info(
                    "Ticket #%s matched module %s keywords but size could not "
                    "be confidently extracted; leaving for normal routing.",
                    ticket_number, module["id"],
                )
                continue

            vm_name = f"zammad-{ticket_number}"
            message = (
                f"We understood your request as: {size['vcpu']} vCPU / "
                f"{size['memory_gb']} GB RAM ({size['instance_type']}).\n\n"
                f"Reply YES to confirm and we'll prepare this for provisioning, "
                f"or reply with corrections if this isn't right."
            )
            zammad_client.reply_to_ticket(ticket_id, message, close=False)
            zammad_client.tag_ticket(ticket_id, AWAITING_TAG)
            zammad_client.tag_ticket(ticket_id, PAUSE_TAG)

            feedback_service.record_decision(
                ticket_id, ticket_number, "awaiting_customer_confirmation",
                {
                    "terraform_module_id": module["id"],
                    "terraform_instance_type": size["instance_type"],
                    "terraform_vm_name": vm_name,
                },
                ticket_text=text,
            )
            logger.info(
                "Ticket #%s: proposed %s (%s), awaiting customer confirmation.",
                ticket_number, module["id"], size["instance_type"],
            )


def _latest_proposal_for(ticket_number: str) -> dict | None:
    from pathlib import Path
    import json

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
            if (
                str(row.get("ticket_number")) == str(ticket_number)
                and row.get("action") == "awaiting_customer_confirmation"
            ):
                match = row
    return match


def stage_check_confirmation() -> None:
    query = f"tags:{AWAITING_TAG} AND NOT tags:{CONFIRMED_TAG} AND NOT tags:{DECLINED_TAG}"
    tickets = zammad_client.search_tickets(query, limit=20)
    for t in tickets:
        ticket_id = int(t["id"])
        ticket_number = str(t.get("number") or ticket_id)

        reply = zammad_client.get_latest_customer_reply(ticket_id)
        if not reply:
            continue

        if _NO_RE.search(reply) and not _YES_RE.search(reply):
            zammad_client.update_ticket(
                ticket_id, "Customer declined or asked for changes. Leaving for manual review.",
                close=False,
            )
            zammad_client.tag_ticket(ticket_id, DECLINED_TAG)
            logger.info("Ticket #%s: customer declined.", ticket_number)
            continue

        if not _YES_RE.search(reply):
            continue

        proposal = _latest_proposal_for(ticket_number)
        if not proposal:
            logger.error("Ticket #%s: confirmed but no stored proposal found.", ticket_number)
            continue

        module = loader.module_by_id(proposal["terraform_module_id"])
        if not module:
            continue

        tf_vars = {
            "aws_region": settings.aws_region,
            "instance_type": proposal["terraform_instance_type"],
            "vm_name": proposal["terraform_vm_name"],
        }
        logger.info("Ticket #%s: customer confirmed, running terraform plan.", ticket_number)
        result = terraform_client.run_module(module["path"], auto_apply=False, tf_vars=tf_vars)

        plan_tail = (result.get("plan_stdout") or result.get("stderr") or "")[-1500:]
        note = (
            f"Customer confirmed. Terraform plan ready for module "
            f"'{module['id']}' instance_type={proposal['terraform_instance_type']}. "
            f"Apply requires L2 approval (tag 'approved-for-apply').\nPlan tail:\n{plan_tail}"
        )
        zammad_client.update_ticket(ticket_id, note, close=False, group=settings.l2_group_name)
        zammad_client.tag_ticket(ticket_id, CONFIRMED_TAG)

        feedback_service.record_decision(
            ticket_id, ticket_number, "terraform_needs_approval", proposal,
        )
        logger.info("Ticket #%s: plan posted, moved to L2 for approval.", ticket_number)


def run() -> None:
    stage_propose()
    stage_check_confirmation()