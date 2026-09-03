"""
Runs the disk-check/cleanup Ansible playbook and returns parsed output.
"""

import json
import logging
import subprocess
from config import settings

logger = logging.getLogger(__name__)


def run_disk_check(target_host: str) -> dict | None:
    cmd = [
        "ansible-playbook",
        settings.disk_check_playbook_path,
        "-i", settings.inventory_path,
        "--limit", target_host,
        "-e", f"target_host={target_host}",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=settings.ansible_timeout_seconds
        )
    except subprocess.TimeoutExpired:
        logger.error("Ansible run timed out for host %s", target_host)
        return None

    if result.returncode != 0:
        logger.error("Ansible run failed for host %s: %s", target_host, result.stderr)
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.error("Could not parse Ansible output for host %s", target_host)
        return None