"""
KB answer generation. Given ticket text and the list of published KB
titles, lets the model browse titles and pull full content on demand
(via get_kb_answer_content) before deciding on a reply. Mirrors the
ticket-routing agent's tool-calling pattern, scoped to just KB lookups.
"""

import logging
import json
from langchain.agents import create_agent
from langchain_core.tools import tool
from kb import knowledge_base_client
from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are answering a support ticket using only the company's knowledge "
    "base. You will be given the ticket text and a list of KB article "
    "titles with their ids. Decide which title(s), if any, are likely to "
    "answer the ticket, then call get_kb_answer_content with that id to "
    "read the full article before answering - do not guess an answer from "
    "the title alone. You may look up more than one article if unsure. "
    "When ready, respond with ONLY a JSON object, no other text, in this "
    "exact shape: "
    '{"can_answer": true/false, "confidence": "high"/"medium"/"low", '
    '"reply_text": "...", "reasoning": "..."}. '
    "reply_text should be a direct, customer-facing answer written in your "
    "own words - do not just paste the KB article verbatim. If nothing in "
    "the KB is relevant, set can_answer to false and explain why in "
    "reasoning."
)


@tool
def get_kb_answer_content(answer_id: int) -> dict:
    """Fetch the full title and body text of one KB answer by its id.
    Use this before answering from a KB article - titles alone are not
    enough to write an accurate reply."""
    content = knowledge_base_client.get_answer_content(answer_id)
    if not content:
        return {"error": f"Could not fetch content for answer_id={answer_id}"}
    return content


def _extract_text(content) -> str:
    """LangChain message content can be a plain string, or (with Gemini's
    thought-signature metadata attached) a list of content blocks like
    [{'type': 'text', 'text': '...', 'extras': {...}}]. Normalize both
    into a single string before attempting JSON parsing."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def resolve_ticket(ticket_text: str, kb_titles: list[dict]) -> dict:
    agent = create_agent(
        model=settings.model,
        tools=[get_kb_answer_content],
        system_prompt=SYSTEM_PROMPT,
    )

    titles_block = "\n".join(f"- id={t['id']}: {t['title']}" for t in kb_titles)
    prompt = f"Ticket text:\n{ticket_text}\n\nAvailable KB titles:\n{titles_block}"

    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})

    final_message = _extract_text(result["messages"][-1].content)
    try:
        parsed = json.loads(final_message)
    except (json.JSONDecodeError, TypeError):
        logger.error("Could not parse answer_generator output as JSON: %s", final_message)
        return {"can_answer": False, "confidence": "low", "reply_text": "", "reasoning": "Failed to parse model output."}

    return parsed