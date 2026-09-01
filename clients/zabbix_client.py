"""
All Zabbix JSON-RPC calls live here.
"""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)


def login() -> str | None:
    payload = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {"username": settings.zabbix_user, "password": settings.zabbix_password},
        "id": 1,
    }
    try:
        response = requests.post(settings.zabbix_url, json=payload, timeout=15)
        response.raise_for_status()
        token = response.json().get("result")
        if not token:
            logger.error("Zabbix login returned no token: %s", response.text)
        return token
    except requests.RequestException:
        logger.exception("Zabbix login request failed")
        return None


def get_problems(auth_token: str) -> list[dict]:
    payload = {
        "jsonrpc": "2.0",
        "method": "problem.get",
        "params": {"output": "extend", "recent": False},
        "auth": auth_token,
        "id": 2,
    }
    try:
        response = requests.post(settings.zabbix_url, json=payload, timeout=15)
        response.raise_for_status()
        problems = response.json().get("result", [])
        logger.info("Fetched %d open Zabbix problem(s).", len(problems))
        return problems
    except requests.RequestException:
        logger.exception("Failed to fetch Zabbix problems")
        return []


def get_hostname_for_trigger(auth_token: str, trigger_id: str) -> str:
    payload = {
        "jsonrpc": "2.0",
        "method": "trigger.get",
        "params": {"output": ["triggerid", "description"], "triggerids": trigger_id},
        "auth": auth_token,
        "id": 3,
    }
    try:
        response = requests.post(settings.zabbix_url, json=payload, timeout=15)
        response.raise_for_status()
        result = response.json().get("result", [])
        if result:
            return result[0].get("description", "unknown-host")
        logger.warning("No trigger found for trigger_id=%s", trigger_id)
        return "unknown-host"
    except requests.RequestException:
        logger.exception("Failed to fetch hostname for trigger_id=%s", trigger_id)
        return "unknown-host"
