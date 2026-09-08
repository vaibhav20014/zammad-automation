"""
Validates and parses the KB agent's task output. No longer builds its
own nested agent - kb_agent.py now does title selection, content
fetching, and reply drafting itself as part of one CrewAI Task. This
file only owns: (1) normalizing whatever shape the LLM's output content
takes into a plain string, and (2) validating/parsing that string as
the expected JSON shape.

Used as a Task guardrail in crew/ticket_crew.py - CrewAI retries the
task automatically if the guardrail returns failure, so a malformed
response gets a second attempt before it reaches kb_answer_service.
"""

import json
import logging

logger = logging.getLogger(__name__)

REQUIRED_KEYS = {"can_answer", "confidence", "reply_text", "reasoning"}


def _extract_text(content) -> str:
    """Output content can be a plain string, or a list of content blocks
    (seen with some Gemini responses carrying thought-signature metadata).
    Normalize both into a single string before parsing."""
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


def parse_kb_result(raw_output) -> dict:
    """Best-effort parse for use after a task has already completed -
    always returns a dict, falling back to a safe 'could not answer'
    shape on failure. Used by kb_answer_service / crew glue code."""
    text = _extract_text(raw_output)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.error("Could not parse KB agent output as JSON: %s", text)
        return {"can_answer": False, "confidence": "low", "reply_text": "", "reasoning": "Failed to parse model output."}

    if not REQUIRED_KEYS.issubset(parsed.keys()):
        logger.error("KB agent output missing required keys: %s", parsed)
        return {"can_answer": False, "confidence": "low", "reply_text": "", "reasoning": "Model output missing required fields."}

    return parsed


def kb_output_guardrail(task_output) -> tuple[bool, dict | str]:
    """CrewAI Task guardrail - runs on raw task output before it's
    accepted. Returning (False, error_message) tells CrewAI to retry the
    task with that message as feedback to the agent. Returning
    (True, value) passes value through as the task's final output."""
    text = _extract_text(getattr(task_output, "raw", task_output))
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False, "Output was not valid JSON. Respond with ONLY the JSON object, no other text."

    missing = REQUIRED_KEYS - parsed.keys()
    if missing:
        return False, f"Output is missing required keys: {missing}. Include all of: {REQUIRED_KEYS}."

    return True, parsed