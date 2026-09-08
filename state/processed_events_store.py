"""
Small wrapper around the "processed events" JSON file, so the service
code doesn't do raw file I/O directly. Swap this for a SQLite/Redis
store later without touching zabbix_poll_service.py.
"""

import json
import logging
import os
from config import settings

logger = logging.getLogger(__name__)


def load() -> dict:
    path = settings.processed_events_file
    if not os.path.exists(path):
        logger.info("No processed-events file yet at %s; starting fresh.", path)
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
            logger.debug("Loaded %d processed event(s) from %s", len(data), path)
            return data
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read processed-events file at %s; starting fresh.", path)
        return {}


def save(events: dict) -> None:
    path = settings.processed_events_file
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(events, f, indent=2)
        logger.debug("Saved %d processed event(s) to %s", len(events), path)
    except OSError:
        logger.exception("Failed to write processed-events file at %s", path)
