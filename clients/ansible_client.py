"""
Wraps the ansible-playbook subprocess call. Nothing here knows about
Zammad or tickets — it just runs a playbook against a host and returns
parsed JSON output (or None on failure).
"""

import json
import logging
import os
import subprocess
from config import settings

logger = logging.getLogger(__name__)


def run_disk_check(target_host: str) -> dict | None:
    env = os.environ.copy()
    env["ANSIBLE_STDOUT_CALLBACK"] = "json"

    cmd = [
        "ansible-playbook",
        "-i", "inventory.ini",
        "--limit", target_host,
        settings.playbook_name,
    ]
    logger.info("Running ansible-playbook against host=%s", target_host)

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
        logger.error("Ansible run timed out for host=%s", target_host)
        return None

    if result.returncode != 0:
        logger.error(
            "Ansible run failed for host=%s (rc=%s): %s",
            target_host, result.returncode, result.stderr.strip(),
        )
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.exception("Could not parse Ansible JSON output for host=%s", target_host)
        logger.debug("Raw stdout: %s", result.stdout)
        return None
