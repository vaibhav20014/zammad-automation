"""
Tracks which Zabbix event IDs have already had a Zammad ticket created
for them, so repeated polling runs don't create duplicates. Backed by a
simple JSON file - swap for a real DB later if volume grows.
"""

import json
import logging
import os
from config import settings

logger = logging.getLogger(__name__)

_cache: set[str] | None = None


def _load() -> set[str]:
    global _cache
    if _cache is not None:
        return _cache

    if not os.path.exists(settings.processed_events_path):
        _cache = set()
        return _cache

    try:
        with open(settings.processed_events_path, "r") as f:
            _cache = set(json.load(f))
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read processed events store, starting empty.")
        _cache = set()

    return _cache


def _save() -> None:
    if _cache is None:
        return
    try:
        with open(settings.processed_events_path, "w") as f:
            json.dump(list(_cache), f)
    except OSError:
        logger.exception("Failed to write processed events store.")


def is_processed(event_id: str) -> bool:
    return str(event_id) in _load()


def mark_processed(event_id: str) -> None:
    _load().add(str(event_id))
    _save()