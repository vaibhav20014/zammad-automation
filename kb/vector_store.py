"""
Local vector index over Zammad KB titles.

Embeddings come from Gemini. Cosine search is pure Python so we do not
add numpy. If GEMINI_API_KEY is missing, callers fall back to the full
title list.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

from config import settings
from kb import knowledge_base_client

logger = logging.getLogger(__name__)


def _client():
    from google import genai
    api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embedding_values(item) -> list[float]:
    values = getattr(item, "values", None)
    if values:
        return list(values)
    embedding = getattr(item, "embedding", None)
    values = getattr(embedding, "values", None) if embedding is not None else None
    return list(values) if values else []


def _embed_texts(client, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    try:
        result = client.models.embed_content(
            model=settings.embedding_model,
            contents=texts if len(texts) > 1 else texts[0],
        )
        embeddings = getattr(result, "embeddings", None)
        if embeddings:
            return [_embedding_values(item) for item in embeddings]
        if getattr(result, "embedding", None) is not None:
            return [_embedding_values(result)]
        return []
    except Exception as exc:
        logger.warning(
            "Embeddings unavailable (%s). Using KB titles instead of the vector index.",
            exc,
        )
        return []


def rebuild_index(articles: list[dict] | None = None) -> int:
    client = _client()
    if client is None:
        logger.warning("Skipping vector index rebuild: GEMINI_API_KEY is not set.")
        return 0

    articles = articles if articles is not None else knowledge_base_client.list_all_answers()
    records = []
    batch_size = 16
    for i in range(0, len(articles), batch_size):
        chunk = articles[i:i + batch_size]
        texts = [f"{a.get('id')} {a.get('title', '')}" for a in chunk]
        try:
            vectors = _embed_texts(client, texts)
        except Exception:
            logger.exception("Embedding batch failed at offset %s", i)
            continue
        for article, vector in zip(chunk, vectors):
            if not vector:
                continue
            records.append({
                "id": int(article["id"]),
                "title": article.get("title", ""),
                "embedding": vector,
            })

    path = Path(settings.vector_index_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": settings.embedding_model,
        "articles": records,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    logger.info("Wrote vector index with %d article(s) to %s", len(records), path)
    return len(records)


def _load_index() -> list[dict]:
    path = Path(settings.vector_index_file)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("articles") or [])
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to read vector index at %s", path)
        return []


def ensure_index(articles: list[dict]) -> None:
    index = _load_index()
    indexed_ids = {int(a["id"]) for a in index if "id" in a}
    live_ids = {int(a["id"]) for a in articles}
    if indexed_ids != live_ids:
        logger.info("Vector index stale or missing; rebuilding.")
        rebuild_index(articles)


def search(query: str, articles: list[dict], top_k: int = 8) -> list[dict]:
    """
    Returns [{"id", "title"}, ...] ranked by similarity.
    Falls back to the full title list if embeddings are unavailable.
    """
    if not query.strip() or not articles:
        return articles[:top_k]

    client = _client()
    if client is None:
        return articles[:top_k]

    ensure_index(articles)
    index = _load_index()
    if not index:
        return articles[:top_k]

    try:
        q_vecs = _embed_texts(client, [query[:8000]])
    except Exception:
        logger.exception("Failed to embed search query")
        return articles[:top_k]
    if not q_vecs or not q_vecs[0]:
        return articles[:top_k]

    scored = []
    for row in index:
        score = _cosine(q_vecs[0], row.get("embedding") or [])
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    seen = set()
    hits = []
    for score, row in scored:
        aid = int(row["id"])
        if aid in seen:
            continue
        seen.add(aid)
        hits.append({"id": aid, "title": row.get("title", ""), "score": round(score, 4)})
        if len(hits) >= top_k:
            break
    logger.info("Vector KB search returned %d hit(s) for query=%r", len(hits), query[:80])
    return hits
