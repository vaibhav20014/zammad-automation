"""Load Ansible / Terraform / escalation / agent catalogs from catalogs/*.json."""

import json
import logging
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


def _read(name: str) -> dict:
    path = Path(settings.catalog_dir) / name
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Catalog missing at %s", path)
        return {}
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to read catalog %s", path)
        return {}


def agent_config() -> dict:
    data = _read("agent_config.json")
    return {
        "name": data.get("name", "AI-Powered Ticket Agent & Router"),
        "max_tool_iterations": int(data.get("max_tool_iterations", 8)),
        "holding_reply": data.get(
            "holding_reply",
            "Thank you for contacting us. We are currently looking into this "
            "and will follow up with you shortly.",
        ),
        "vector_top_k": int(data.get("vector_top_k", 8)),
    }


def ansible_playbooks() -> list[dict]:
    return list(_read("ansible.json").get("playbooks") or [])


def terraform_modules() -> list[dict]:
    return list(_read("terraform.json").get("modules") or [])


def escalation_rules() -> dict:
    data = _read("escalation.json")
    groups = data.get("groups") or {}
    return {
        "default_level": data.get("default_level", "l2"),
        "groups": {
            "l1": groups.get("l1") or settings.l1_group_name,
            "l2": groups.get("l2") or settings.l2_group_name,
            "l3": groups.get("l3") or settings.l3_group_name,
        },
        "l1_keywords": [k.lower() for k in (data.get("l1_keywords") or [])],
        "l3_keywords": [k.lower() for k in (data.get("l3_keywords") or [])],
    }


def playbook_by_id(playbook_id: str) -> dict | None:
    wanted = (playbook_id or "").strip().lower()
    for item in ansible_playbooks():
        if str(item.get("id", "")).lower() == wanted:
            return item
    return None


def module_by_id(module_id: str) -> dict | None:
    wanted = (module_id or "").strip().lower()
    for item in terraform_modules():
        if str(item.get("id", "")).lower() == wanted:
            return item
    return None
