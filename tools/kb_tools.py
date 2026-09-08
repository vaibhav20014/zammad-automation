"""
Tools for the KB specialist agent. Since kb_agent.py now does its own
title-selection + content-fetch + reply-drafting reasoning within one
CrewAI task (no more separate nested agent), it needs both the title
listing and the content-fetch as tools available to it directly.
"""

from crewai.tools import tool
from kb import knowledge_base_client


@tool("list_kb_titles")
def list_kb_titles() -> list[dict]:
    """List all published knowledge base article titles with their ids.
    Call this first to see what's available before deciding which
    article(s), if any, might answer the ticket."""
    return knowledge_base_client.list_all_answers()


@tool("get_kb_answer_content")
def get_kb_answer_content(answer_id: int) -> dict:
    """Fetch the full title and body text of one KB answer by its id.
    Always call this before answering from an article - titles alone
    are not enough to draft an accurate reply."""
    content = knowledge_base_client.get_answer_content(answer_id)
    if not content:
        return {"error": f"Could not fetch content for answer_id={answer_id}"}
    return content


def get_tools() -> list:
    return [list_kb_titles, get_kb_answer_content]