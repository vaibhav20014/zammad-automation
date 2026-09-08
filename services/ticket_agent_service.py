"""
Decision center workflow:
  optional Git catalog sync -> vector KB retrieve -> orchestrate
  -> apply kb / ansible / terraform / L1-L3 -> feedback log (+ Zabbix ack).
"""

import logging

from ai import ticket_agent
from catalogs import loader
from clients import git_scm_client, zammad_client
from config import settings
from kb import knowledge_base_client, vector_store
from services import escalation_service, feedback_service, ticket_queue_service
from services.disk_ticket_service import load_known_servers

logger = logging.getLogger(__name__)


def _tag_handled(ticket_id: int) -> None:
    zammad_client.tag_ticket(ticket_id, settings.agent_handled_tag)


def apply_decision(ticket_id: int, ticket_number: str, decision: dict) -> bool:
    action = decision["action"]
    public_reply = decision.get("public_reply") or ticket_agent.HOLDING_REPLY
    internal_note = decision.get("internal_note") or decision.get("reasoning") or ""

    if action == "kb_answer":
        if internal_note:
            zammad_client.update_ticket(ticket_id, internal_note, close=False)
        success = zammad_client.reply_to_ticket(ticket_id, public_reply, close=True)
        logger.info("Ticket #%s KB-answered and closed.", ticket_number)
        return success

    if action == "ansible_resolved":
        host = decision.get("ansible_host") or "unknown host"
        playbook_id = decision.get("ansible_playbook_id") or "playbook"
        note = internal_note or (
            f"Automated Ansible job '{playbook_id}' on {host} confirmed resolution."
        )
        success = zammad_client.update_ticket(ticket_id, note, close=True)
        logger.info(
            "Ticket #%s Ansible-resolved and closed (playbook=%s host=%s).",
            ticket_number, playbook_id, host,
        )
        return success

    if action == "terraform_resolved":
        module_id = decision.get("terraform_module_id") or "module"
        note = internal_note or f"Terraform apply succeeded for module '{module_id}'."
        success = zammad_client.update_ticket(ticket_id, note, close=True)
        logger.info("Ticket #%s Terraform-resolved and closed (module=%s).", ticket_number, module_id)
        return success

    if action == "terraform_needs_approval":
        module_id = decision.get("terraform_module_id") or "module"
        size = decision.get("terraform_instance_type") or ""
        note = internal_note or (
            f"Terraform plan ready for module '{module_id}' {size}. "
            "Apply is disabled; L2 must review and apply."
        )
        zammad_client.reply_to_ticket(ticket_id, ticket_agent.HOLDING_REPLY, close=False)
        success = zammad_client.update_ticket(
            ticket_id, note, close=False, group=settings.l2_group_name,
        )
        logger.warning(
            "Ticket #%s Terraform plan waiting on L2 (module=%s size=%s).",
            ticket_number, module_id, size or "-",
        )
        return success

    if action in {"escalate_l1", "escalate_l2", "escalate_l3"}:
        level = action.split("_", 1)[1]
        group = escalation_service.group_for_level(level)
        canned = {
            "l1": ticket_agent.L1_INTERNAL_NOTE,
            "l2": ticket_agent.L2_INTERNAL_NOTE,
            "l3": ticket_agent.L3_INTERNAL_NOTE,
        }[level]
        zammad_client.reply_to_ticket(ticket_id, ticket_agent.HOLDING_REPLY, close=False)
        if internal_note and internal_note != canned:
            zammad_client.update_ticket(ticket_id, internal_note, close=False)
        success = zammad_client.update_ticket(ticket_id, canned, close=False, group=group)
        logger.warning("Ticket #%s assigned to %s (%s).", ticket_number, group, action)
        return success

    logger.error("Unknown action %s for ticket #%s; escalating to L2.", action, ticket_number)
    zammad_client.reply_to_ticket(ticket_id, ticket_agent.HOLDING_REPLY, close=False)
    return zammad_client.update_ticket(
        ticket_id, ticket_agent.L2_INTERNAL_NOTE, close=False, group=settings.l2_group_name,
    )


def handle_ticket(
    ticket_id: int,
    ticket_number: str,
    title: str,
    kb_titles: list[dict],
    known_servers: set[str],
    vector_top_k: int,
) -> None:
    ticket_text = zammad_client.get_ticket_text(ticket_id, fallback_title=title)
    if not ticket_text.strip():
        logger.info("Ticket #%s has no usable text; escalating to L1.", ticket_number)
        decision = {
            "action": "escalate_l1",
            "public_reply": ticket_agent.HOLDING_REPLY,
            "internal_note": ticket_agent.L1_INTERNAL_NOTE,
            "used_article_ids": [],
            "ansible_host": "",
            "ansible_playbook_id": "",
            "terraform_module_id": "",
            "confidence": "low",
            "reasoning": "Empty ticket body.",
        }
        success = apply_decision(ticket_id, ticket_number, decision)
        if success:
            _tag_handled(ticket_id)
            feedback_service.record_decision(
                ticket_id, ticket_number, decision["action"], decision, ticket_text
            )
        return

    retrieved = vector_store.search(ticket_text, kb_titles, top_k=vector_top_k)
    logger.info("Orchestrating ticket #%s: %s", ticket_number, title[:80])
    decision = ticket_agent.resolve_ticket(
        ticket_text=ticket_text,
        title=title,
        kb_titles=retrieved,
        known_servers=known_servers,
    )
    success = apply_decision(ticket_id, ticket_number, decision)
    if success:
        _tag_handled(ticket_id)
        feedback_service.record_decision(
            ticket_id, ticket_number, decision["action"], decision, ticket_text
        )
        feedback_service.ack_zabbix_if_resolved(
            ticket_text, decision["action"], ticket_number
        )


def run() -> None:
    git_scm_client.sync_all()
    agent_cfg = loader.agent_config()
    kb_titles = knowledge_base_client.list_all_answers()
    known_servers = load_known_servers()

    tickets = ticket_queue_service.find_candidate_tickets()
    if not tickets:
        logger.info("No candidate tickets found for the ticket agent.")
        return

    logger.info("Found %d candidate ticket(s) for the ticket agent.", len(tickets))
    for t in tickets:
        handle_ticket(
            t["id"],
            t["number"],
            t.get("title", ""),
            kb_titles,
            known_servers,
            vector_top_k=int(agent_cfg.get("vector_top_k", 8)),
        )
