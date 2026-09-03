"""
Thin HTTP wrapper around the Zabbix API for polling active problems.
Zabbix requires a user.login call to exchange username/password for a
session token before any other method works. Modern Zabbix (6.4+) wants
that token passed as an Authorization: Bearer header rather than the
older "auth" field inside the payload.
"""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

_session = requests.Session()
_auth_token: str | None = None


def _login() -> str:
    global _auth_token
    payload = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {
            "username": settings.zabbix_user,
            "password": settings.zabbix_password,
        },
        "id": 1,
    }
    resp = _session.post(f"{settings.zabbix_url}/api_jsonrpc.php", json=payload)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        logger.error("Zabbix login failed: %s", data["error"])
        raise RuntimeError(f"Zabbix login failed: {data['error']}")

    _auth_token = data["result"]
    logger.info("Zabbix login successful.")
    return _auth_token


def _call(method: str, params: dict, retry: bool = True) -> list | dict:
    global _auth_token
    if _auth_token is None:
        _login()

    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    headers = {"Authorization": f"Bearer {_auth_token}"}

    resp = _session.post(f"{settings.zabbix_url}/api_jsonrpc.php", json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        error = data["error"]
        # Session expired/invalid - log in again once and retry
        if retry and error.get("data", "").lower().startswith("session terminated"):
            logger.warning("Zabbix session expired, re-authenticating.")
            _auth_token = None
            return _call(method, params, retry=False)

        logger.error("Zabbix API error: %s", error)
        raise RuntimeError(error)

    return data.get("result", [])


def get_active_problems() -> list[dict]:
    return _call("problem.get", {
        "output": "extend",
        "sortfield": "eventid",
        "sortorder": "DESC",
        "recent": True,
    })