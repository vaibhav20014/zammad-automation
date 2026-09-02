"""
Zammad Knowledge Base access.

There is no flat "list all answers" REST endpoint on this instance's
Zammad version. Instead, POST /api/v1/knowledge_bases/init returns the
whole KB object graph in one call: knowledge bases, categories, answers,
and answer *translations* (which hold the actual title text). We use
that single call to build our title list, filtering to answers that are
actually published (published_at is set) so we don't surface drafts or
internal-only answers to customers.

Getting an answer's actual BODY text requires a second call with the
?include_contents={translation_id} query param -- the translation_id is
NOT the same as the answer_id, so we cache that mapping from the /init
payload and look it up automatically inside get_answer_content().

Required Zammad permission for the /init call: knowledge_base.editor
(per Zammad's own docs) -- if this 403s, the API token's role needs that
permission added under Admin > Roles.
"""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Token token={settings.zammad_token}",
    "Content-Type": "application/json",
}

# Cache the init payload + resolved kb_id + answer->translation mapping
# for the lifetime of one process run, since list_all_answers() and
# get_answer_content() both need them.
_init_cache: dict | None = None
_kb_id_cache: str | None = None
_answer_translation_map: dict[int, int] = {}


def _fetch_kb_init() -> dict:
    global _init_cache, _kb_id_cache
    if _init_cache is not None:
        return _init_cache

    url = f"{settings.zammad_url}/api/v1/knowledge_bases/init"
    try:
        response = requests.post(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        logger.debug("KB init response top-level keys: %s", list(data.keys()))
        _init_cache = data

        kb_dict = data.get("KnowledgeBase", {})
        if kb_dict:
            _kb_id_cache = next(iter(kb_dict.keys()))  # first (usually only) KB id

        return data
    except requests.RequestException:
        logger.exception("Failed to fetch KB init payload")
        return {}


def list_all_answers() -> list[dict]:
    """
    Returns published KB answers as [{"id": <answer_id>, "title": ...}, ...].
    Also populates _answer_translation_map for get_answer_content() to use.
    """
    data = _fetch_kb_init()
    if not data:
        return []

    answers = data.get("KnowledgeBaseAnswer", {})
    translations = data.get("KnowledgeBaseAnswerTranslation", {})

    result = []
    for answer_id, answer in answers.items():
        translation_ids = answer.get("translation_ids", [])
        if translation_ids:
            _answer_translation_map[int(answer_id)] = translation_ids[0]

        if not answer.get("published_at"):
            continue  # skip drafts / internal-only answers

        for translation_id in translation_ids:
            translation = translations.get(str(translation_id)) or translations.get(translation_id)
            if translation:
                result.append({
                    "id": int(answer_id),
                    "title": translation.get("title", ""),
                })

    logger.info("Loaded %d published KB answer(s) from KB init.", len(result))
    return result


def get_answer_content(answer_id: int) -> dict | None:
    """
    Fetch full title + body for one answer, using the
    ?include_contents={translation_id} parameter to get the actual
    rendered body text (the plain answer endpoint returns metadata only).
    """
    if not _answer_translation_map:
        list_all_answers()  # populates the mapping as a side effect

    translation_id = _answer_translation_map.get(int(answer_id))
    if translation_id is None:
        logger.error("No translation_id known for answer_id=%s; cannot fetch content.", answer_id)
        return None

    if not _kb_id_cache:
        logger.error("No KB id resolved yet; cannot fetch answer content.")
        return None

    url = (
        f"{settings.zammad_url}/api/v1/knowledge_bases/"
        f"{_kb_id_cache}/answers/{answer_id}"
    )
    params = {"include_contents": translation_id}

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        logger.debug(
            "Raw answer content response for id=%s (translation_id=%s): %s",
            answer_id,
            translation_id,
            data
        )

    except requests.RequestException:
        logger.exception(
            "Failed to fetch KB answer content for id=%s",
            answer_id
        )
        return None

    assets = data.get("assets", {})

    title = ""
    trans_assets = assets.get("KnowledgeBaseAnswerTranslation", {})
    translation = trans_assets.get(str(translation_id)) or trans_assets.get(translation_id)
    if translation:
        title = translation.get("title", "")

    # The exact asset key holding the body text isn't confirmed yet, so
    # search generically for any nested object carrying a "body" or
    # "content" field rather than hardcoding a guessed key name.
    body = ""
    for group_name, group in assets.items():
        if not isinstance(group, dict):
            continue
        for obj in group.values():
            if isinstance(obj, dict):
                if obj.get("body"):
                    body = obj["body"]
                    break
                if obj.get("content"):
                    body = obj["content"]
                    break
        if body:
            break

    if not body:
        logger.warning(
            "get_answer_content(%s): fetched response but found no body text in any asset. "
            "Check the debug log line above for the raw shape.",
            answer_id,
        )

    return {"title": title, "body": body}