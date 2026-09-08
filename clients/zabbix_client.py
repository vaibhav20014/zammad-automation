"""
All Zabbix JSON-RPC calls live here.
"""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

_SEVERITY = {
    "0": "not_classified",
    "1": "information",
    "2": "warning",
    "3": "average",
    "4": "high",
    "5": "disaster",
}


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
        "params": {
            "output": "extend",
            "recent": False,
            "sortfield": ["eventid"],
            "sortorder": "DESC",
        },
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
        "params": {
            "output": ["triggerid", "description"],
            "selectHosts": ["host", "name"],
            "triggerids": trigger_id,
        },
        "auth": auth_token,
        "id": 3,
    }
    try:
        response = requests.post(settings.zabbix_url, json=payload, timeout=15)
        response.raise_for_status()
        result = response.json().get("result", [])
        if not result:
            logger.warning("No trigger found for trigger_id=%s", trigger_id)
            return "unknown-host"
        hosts = result[0].get("hosts") or []
        if hosts:
            return hosts[0].get("host") or hosts[0].get("name") or "unknown-host"
        return result[0].get("description", "unknown-host")
    except requests.RequestException:
        logger.exception("Failed to fetch hostname for trigger_id=%s", trigger_id)
        return "unknown-host"


def severity_label(raw) -> str:
    return _SEVERITY.get(str(raw), str(raw))


def acknowledge_event(auth_token: str, event_id: str, message: str) -> bool:
    """
    Acknowledge a problem and attach a message (Zabbix action bitmap: 2+4=6).
    Does not close the problem in Zabbix — Zammad owns ticket state.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "event.acknowledge",
        "params": {
            "eventids": str(event_id),
            "action": 6,
            "message": message[:2048],
        },
        "auth": auth_token,
        "id": 4,
    }
    try:
        response = requests.post(settings.zabbix_url, json=payload, timeout=15)
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            logger.error("Zabbix acknowledge failed for event %s: %s", event_id, body["error"])
            return False
        logger.info("Acknowledged Zabbix event %s", event_id)
        return True
    except requests.RequestException:
        logger.exception("Failed to acknowledge Zabbix event %s", event_id)
        return False
