"""
Zammad-facing tools - native CrewAI tools. Each tool tags the ticket
with the outcome that actually happened, since parsing the crew's
final text summary to figure out what really occurred is unreliable.
"""

import html
import logging
import re

from crewai.tools import tool
from clients import zammad_client

logger = logging.getLogger(__name__)

AWAITING_REPLY_TAG = "awaiting-customer-reply"
AUTOMATION_DONE_TAG = "automation-processed"
SPAM_TAG = "automation-spam"
CATEGORY_TAGS = {"incident_request", "service_request", "change_request"}


@tool("ask_for_more_details")
def ask_for_more_details(ticket_id: int, question: str) -> str:
    """
    Sends a public reply to the ticket asking the customer for the
    specific missing information needed to proceed. Use this INSTEAD
    of guessing a value. Does not close the ticket - it will be
    re-checked automatically once the customer replies.
    """
    logger.info("ask_for_more_details CALLED for ticket #%s: %s", ticket_id, question)
    success = zammad_client.reply_to_ticket(ticket_id, question, close=False)
    if success:
        zammad_client.tag_ticket(ticket_id, AWAITING_REPLY_TAG)
        logger.info("ask_for_more_details SUCCEEDED for ticket #%s, tagged awaiting reply", ticket_id)
        return f"Ticket #{ticket_id}: sent clarification request; will re-check once customer replies."
    logger.error("ask_for_more_details FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to send clarification request - do not assume it was received."


@tool("report_outcome")
def report_outcome(ticket_id: int, message: str, resolved: bool) -> str:
    """
    Posts the final outcome of the work to the customer as a public reply
    and marks the ticket as handled by automation. Call this as the LAST
    step after running any operational tools. Set resolved=True only if
    verification confirmed the problem is fixed (the ticket is then
    closed). Set resolved=False if the fix was partial or failed - the
    ticket stays open for a human, and your message should say exactly
    what was found, what was tried, and what still needs doing.
    """
    logger.info("report_outcome CALLED for ticket #%s (resolved=%s)", ticket_id, resolved)
    success = zammad_client.reply_to_ticket(ticket_id, message, close=resolved)
    if success:
        zammad_client.tag_ticket(ticket_id, AUTOMATION_DONE_TAG)
        logger.info("report_outcome SUCCEEDED for ticket #%s", ticket_id)
        return f"Ticket #{ticket_id}: outcome posted to customer (resolved={resolved})."
    logger.error("report_outcome FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to post outcome - do not assume the customer saw it."


@tool("post_kb_answer")
def post_kb_answer(ticket_id: int, answer_text: str, close: bool) -> str:
    """
    Posts a drafted answer back to the ticket as a public reply.
    close=False: the answer is posted and the ticket is tagged as awaiting the
    customer's reply (use this when posting a KB answer for the first time).
    close=True: use ONLY after the customer has confirmed the issue is resolved;
    the ticket is closed and marked as handled by automation.
    """
    logger.info("post_kb_answer CALLED for ticket #%s (close=%s)", ticket_id, close)
    success = zammad_client.reply_to_ticket(ticket_id, answer_text, close=close)
    if success:
        if close:
            zammad_client.tag_ticket(ticket_id, AUTOMATION_DONE_TAG)
            try:
                zammad_client.untag_ticket(ticket_id, AWAITING_REPLY_TAG)
            except Exception as exc:
                logger.warning("could not remove awaiting tag on ticket #%s (ignored): %s", ticket_id, exc)
        else:
            zammad_client.tag_ticket(ticket_id, AWAITING_REPLY_TAG)
        logger.info("post_kb_answer SUCCEEDED for ticket #%s (closed=%s)", ticket_id, close)
        return f"Ticket #{ticket_id}: answer posted (closed={close})."
    logger.error("post_kb_answer FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to post answer - do not assume it was received."


@tool("tag_as_spam")
def tag_as_spam(ticket_id: int) -> str:
    """
    Tags the ticket as spam.
    """
    logger.info("tag_as_spam CALLED for ticket #%s", ticket_id)
    success = zammad_client.tag_ticket(ticket_id, SPAM_TAG)
    if success:
        logger.info("tag_as_spam SUCCEEDED for ticket #%s", ticket_id)
        return f"Ticket #{ticket_id}: tagged as spam."
    logger.error("tag_as_spam FAILED for ticket #%s", ticket_id)
    return f"Ticket #{ticket_id}: FAILED to tag as spam."


@tool("tag_ticket")
def apply_category_tag(ticket_id: int, tag: str) -> str:
    """
    Applies the category tag to the ticket after classification.
    The tag MUST be exactly one of: incident_request (Incident),
    service_request (Service Request), or change_request (Change Request).
    Does not reply to, close, or otherwise modify the ticket.
    """
    tag = (tag or "").strip().lower()
    logger.info("tag_ticket CALLED for ticket #%s with tag '%s'", ticket_id, tag)

    if tag not in CATEGORY_TAGS:
        logger.error("tag_ticket REJECTED invalid tag '%s' for ticket #%s", tag, ticket_id)
        return (
            f"Ticket #{ticket_id}: FAILED - invalid tag '{tag}'. "
            f"Use exactly one of: {', '.join(sorted(CATEGORY_TAGS))}."
        )

    # Remove any other category tag first so a ticket never ends up with two
    # categories. A failure here is ignored on purpose: the other tag usually
    # was not on the ticket, and that must not block the tagging below.
    for other in CATEGORY_TAGS - {tag}:
        try:
            zammad_client.untag_ticket(ticket_id, other)
        except Exception as exc:
            logger.warning("untag of '%s' on ticket #%s failed (ignored): %s", other, ticket_id, exc)

    success = zammad_client.tag_ticket(ticket_id, tag)
    if success:
        logger.info("tag_ticket SUCCEEDED for ticket #%s with tag '%s'", ticket_id, tag)
        return f"Ticket #{ticket_id}: tagged as '{tag}'."
    logger.error("tag_ticket FAILED for ticket #%s with tag '%s'", ticket_id, tag)
    return f"Ticket #{ticket_id}: FAILED to apply tag '{tag}' - do not assume it was tagged."


@tool("get_ticket_conversation")
def get_ticket_conversation(ticket_id: int) -> str:
    """
    Returns the full conversation of a ticket (every message, oldest first,
    with sender and time). Use this to read the complete ticket before
    classifying it. Read-only: does not modify the ticket.
    """
    logger.info("get_ticket_conversation CALLED for ticket #%s", ticket_id)
    try:
        articles = zammad_client.get_ticket_articles(ticket_id)
    except Exception as exc:
        logger.error("get_ticket_conversation FAILED for ticket #%s: %s", ticket_id, exc)
        return f"Ticket #{ticket_id}: FAILED to read conversation: {exc}"

    if not articles:
        return f"Ticket #{ticket_id}: no messages found."

    parts = []
    for a in articles:
        body = re.sub(r"<[^>]+>", " ", a.get("body") or "")  # strip HTML tags
        body = html.unescape(body).replace("\xa0", " ")       # decode &nbsp; &amp; etc.
        body = re.sub(r"\s+", " ", body).strip()
        parts.append(
            f"[{a.get('created_at', '?')}] {a.get('from', 'unknown')} "
            f"({a.get('sender', '?')}) - {a.get('subject') or ''}\n{body}"
        )

    text = "\n\n".join(parts)
    return text[:12000]  # cap size so huge threads don't blow up the LLM context


def get_tools() -> list:
    # Original tools shared by the Ansible, KB, spam and Terraform agents.
    # Do not add categorization tools here - they would leak into those agents.
    return [
        ask_for_more_details,
        report_outcome,
        post_kb_answer,
        tag_as_spam,
    ]


def get_categorization_tools() -> list:
    # Used only by the categorization agent.
    return [
        apply_category_tag,
        get_ticket_conversation,
    ]
