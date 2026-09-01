"""
Entrypoint: finds open disk tickets and resolves them via Ansible.
Run this on a cron/systemd timer, e.g. every 5 minutes.
"""

import logging
from logging_setup import configure_logging

configure_logging("ansible_agent.log")
logger = logging.getLogger(__name__)

from services import disk_ticket_service  # noqa: E402  (after logging setup)

if __name__ == "__main__":
    logger.info("=== Ansible disk-ticket agent run starting ===")
    try:
        disk_ticket_service.run()
    except Exception as e:
        logger.exception(f"Unhandled error in ansible agent run: {e}")
    logger.info("=== Ansible disk-ticket agent run finished ===")
