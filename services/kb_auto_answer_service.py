"""
Workflow: load all published KB titles once -> find open tickets not yet
checked -> pull the ticket's real text -> hand off (ticket text + full KB
title list) to the agentic AI resolver -> reply/escalate accordingly.
"""

import logging
from clients import zammad_client
from kb import knowledge_base_client
from ai import answer_generator

logger = logging.getLogger(__name__)

KB_CHECKED_TAG = "kb-auto-checked"


def find_candidate_tickets() -> list[dict]:
    query = f'state.name:(new OR open) AND NOT tags:{KB_CHECKED_TAG}'
    return zammad_client.search_tickets(query, limit=20)


def handle_ticket(ticket_id: int, ticket_number: str, title: str, kb_titles: list[dict]) -> None:
    ticket_text = zammad_client.get_first_article_body(ticket_id) or title

    if not ticket_text.strip():
        logger.info("Ticket #%s has no usable text, tagging as checked.", ticket_number)
        zammad_client.tag_ticket(ticket_id, KB_CHECKED_TAG)
        return

    logger.info("Checking ticket #%s against KB: %s", ticket_number, ticket_text[:80])

    if not kb_titles:
        holding_message = (
            "Thanks for reaching out - we're looking into this and will "
            "follow up shortly."
        )
        zammad_client.reply_to_ticket(ticket_id, holding_message, close=False)
        zammad_client.tag_ticket(ticket_id, KB_CHECKED_TAG)
        logger.info("Ticket #%s: no KB answers available, sent holding reply.", ticket_number)
        return

    result = answer_generator.resolve_ticket(ticket_text, kb_titles)

    if result.get("can_answer") and result.get("confidence") == "high":
        success = zammad_client.reply_to_ticket(ticket_id, result["reply_text"], close=True)
        logger.info("Ticket #%s auto-answered from KB and closed.", ticket_number)
        if success:
            zammad_client.tag_ticket(ticket_id, KB_CHECKED_TAG)
        return

    if result.get("reply_text"):
        zammad_client.reply_to_ticket(ticket_id, result["reply_text"], close=False)

    zammad_client.update_ticket(
        ticket_id,
        f"Automation: KB check inconclusive (confidence={result.get('confidence')}). "
        f"Reasoning: {result.get('reasoning')}",
        close=False,
    )
    zammad_client.tag_ticket(ticket_id, KB_CHECKED_TAG)
    logger.info("Ticket #%s: KB check inconclusive, left for human review.", ticket_number)


def run() -> None:
    kb_titles = knowledge_base_client.list_all_answers()

    tickets = find_candidate_tickets()
    if not tickets:
        logger.info("No candidate tickets found for KB auto-answer.")
        return

    logger.info("Found %d candidate ticket(s) for KB check.", len(tickets))
    for t in tickets:
        handle_ticket(t["id"], t["number"], t.get("title", ""), kb_titles)