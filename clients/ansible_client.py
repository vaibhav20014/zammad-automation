"""
Wraps ansible-playbook. Callers pass a catalog playbook name and host;
this module does not decide whether the ticket is resolved.
"""

import json
import logging
import os
import subprocess
from config import settings

logger = logging.getLogger(__name__)


def run_playbook(playbook_name: str, target_host: str | None = None) -> dict | None:
    env = os.environ.copy()
    env["ANSIBLE_STDOUT_CALLBACK"] = "json"

    cmd = [
        "ansible-playbook",
        "-i", "inventory.ini",
        playbook_name,
    ]
    if target_host:
        cmd.extend(["--limit", target_host])

    logger.info(
        "Running ansible-playbook playbook=%s host=%s",
        playbook_name, target_host or "*",
    )

    try:
        result = subprocess.run(
            cmd,
            cwd=settings.playbook_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        logger.error("Ansible run timed out for playbook=%s host=%s", playbook_name, target_host)
        return None
    except FileNotFoundError:
        logger.error("ansible-playbook is not installed or not on PATH")
        return None

    if result.returncode != 0:
        logger.error(
            "Ansible run failed playbook=%s host=%s (rc=%s): %s",
            playbook_name, target_host, result.returncode, result.stderr.strip(),
        )
        # JSON callback still often prints a parseable play on stdout
        parsed = _parse_json(result.stdout)
        if parsed:
            parsed["_returncode"] = result.returncode
            parsed["_stderr"] = result.stderr[-2000:]
            return parsed
        return None

    return _parse_json(result.stdout)


def run_disk_check(target_host: str) -> dict | None:
    return run_playbook(settings.playbook_name, target_host=target_host)


def _parse_json(stdout: str) -> dict | None:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.exception("Could not parse Ansible JSON output")
        logger.debug("Raw stdout: %s", stdout)
        return None
