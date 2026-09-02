"""
Agentic KB resolution: the model sees ticket text + KB titles, and
decides for itself whether to fetch full article content before
answering. It can call get_answer_content one or more times, then
must call submit_final_response to finish.

This replaces the old fixed select-then-generate pipeline with a real
tool-use loop, so the model — not our code — decides which titles are
worth opening.
"""

import json
import logging
import os
from google import genai
from google.genai import types
from kb import knowledge_base_client

logger = logging.getLogger(__name__)

MODEL = os.getenv("KB_ANSWER_MODEL", "gemini-2.5-flash")
MAX_TOOL_ITERATIONS = 4

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_SYSTEM_PROMPT = """You are a support-ticket triage assistant with access to a
Knowledge Base search index. You will be given a customer's ticket text and a
list of KB article titles that were returned by a search on that ticket.

You decide what to do:
- If one or more titles look like they plausibly answer the customer's
  specific question, call get_answer_content on that article's id to read
  the full text before deciding anything.
- You may call get_answer_content on more than one article if several
  titles look promising, but don't fetch titles that clearly don't match.
- If NO titles look relevant at all, don't fetch anything — just submit a
  short, friendly holding reply (e.g. "Thanks for reaching out — we're
  looking into this and will follow up shortly.") with can_answer=false.
- Only draft a real answer (can_answer=true) using information you
  actually read via get_answer_content. Never state something as fact
  that wasn't in a fetched article.
- When you're done, call submit_final_response exactly once with your
  decision — that ends the task."""

_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_answer_content",
        description="Fetch the full title+body of a KB article by its id, to check if it actually answers the ticket.",
        parameters={
            "type": "object",
            "properties": {"answer_id": {"type": "integer"}},
            "required": ["answer_id"],
        },
    ),
    types.FunctionDeclaration(
        name="submit_final_response",
        description="Finish the task with your final decision.",
        parameters={
            "type": "object",
            "properties": {
                "can_answer": {"type": "boolean"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "reply_text": {
                    "type": "string",
                    "description": "The reply to send — either a grounded answer, or a short holding message if can_answer is false.",
                },
                "used_article_ids": {"type": "array", "items": {"type": "integer"}},
                "reasoning": {"type": "string"},
            },
            "required": ["can_answer", "confidence", "reply_text", "used_article_ids", "reasoning"],
        },
    ),
])


def _execute_tool_call(name: str, args: dict) -> dict:
    if name == "get_answer_content":
        content = knowledge_base_client.get_answer_content(args["answer_id"])
        if not content:
            return {"error": f"Could not fetch article id={args['answer_id']}."}
        return {
            "id": args["answer_id"],
            "title": content.get("title", ""),
            "body": content.get("body", ""),
        }
    return {"error": f"Unknown tool: {name}"}


def resolve_ticket(ticket_text: str, titled_hits: list[dict]) -> dict:
    """
    titled_hits: list of {"id": ..., "title": ...} from knowledge_base_client.search_kb().
    Returns the submit_final_response payload, or a safe fallback on failure.
    """
    if not titled_hits:
        return {
            "can_answer": False,
            "confidence": "low",
            "reply_text": "Thanks for reaching out — we're looking into this and will follow up shortly.",
            "used_article_ids": [],
            "reasoning": "No KB hits were returned for this ticket.",
        }

    titles_block = "\n".join(f"[id={h['id']}] {h['title']}" for h in titled_hits)
    contents = [
        types.Content(role="user", parts=[types.Part(text=(
            f"Customer ticket:\n{ticket_text}\n\nKB search results (titles only):\n{titles_block}"
        ))])
    ]

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = _client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    tools=[_TOOLS],
                ),
            )
        except Exception:
            logger.exception("Gemini call failed during agentic KB resolution")
            break

        candidate = response.candidates[0]
        contents.append(candidate.content)  # keep the model's turn in history

        function_calls = [
            part.function_call for part in candidate.content.parts
            if part.function_call is not None
        ]

        if not function_calls:
            logger.warning("Model returned no tool call on iteration %d; stopping.", iteration)
            break

        submitted = None
        function_response_parts = []

        for call in function_calls:
            if call.name == "submit_final_response":
                submitted = dict(call.args)
                continue
            logger.info("Model called %s(%s)", call.name, dict(call.args))
            result = _execute_tool_call(call.name, dict(call.args))
            function_response_parts.append(
                types.Part(function_response=types.FunctionResponse(
                    name=call.name, response=result
                ))
            )

        if submitted is not None:
            logger.info(
                "Agentic KB resolution finished: can_answer=%s confidence=%s articles_used=%s",
                submitted.get("can_answer"), submitted.get("confidence"),
                submitted.get("used_article_ids"),
            )
            return submitted

        # Feed tool results back for the next turn
        contents.append(types.Content(role="user", parts=function_response_parts))

    logger.warning("Agentic KB resolution hit max iterations or failed without a final response.")
    return {
        "can_answer": False,
        "confidence": "low",
        "reply_text": "Thanks for reaching out — we're looking into this and will follow up shortly.",
        "used_article_ids": [],
        "reasoning": "Model did not produce a final decision within the allowed steps.",
    }