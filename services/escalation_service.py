"""Escalation rule engine: L1 review, L2 engineering, L3 vendor/expert."""

from catalogs import loader
from config import settings


def group_for_level(level: str) -> str:
    rules = loader.escalation_rules()
    key = (level or "").lower().replace("escalate_", "")
    return rules["groups"].get(key, settings.l2_group_name)


def infer_level(ticket_text: str, default: str | None = None) -> str:
    rules = loader.escalation_rules()
    text = (ticket_text or "").lower()
    if any(k in text for k in rules["l3_keywords"]):
        return "l3"
    if any(k in text for k in rules["l1_keywords"]):
        return "l1"
    return default or rules["default_level"]


def normalize_action(action: str, ticket_text: str) -> str:
    raw = (action or "").strip().lower()
    if raw in {"escalate_l1", "escalate_l2", "escalate_l3"}:
        return raw
    if raw in {"l1", "escalate"}:
        return "escalate_l1" if raw == "l1" else f"escalate_{infer_level(ticket_text)}"
    if raw in {"l2"}:
        return "escalate_l2"
    if raw in {"l3"}:
        return "escalate_l3"
    return f"escalate_{infer_level(ticket_text)}"
