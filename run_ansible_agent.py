#!/usr/bin/env python
"""
Entrypoint: finds open disk tickets and resolves them via Ansible.
Run this on a cron/systemd timer, e.g. every 5 minutes.

DEPRECATED as a separate owner: this now runs the unified ticket agent
(KB + Ansible + L2 + L1). Prefer run_ticket_agent.py. Kept so existing
cron entries do not race a second disk-only worker.
"""

import logging
from logging_setup import configure_logging

configure_logging("ansible_agent.log")
logger = logging.getLogger(__name__)

from services import ticket_agent_service  # noqa: E402  (after logging setup)

if __name__ == "__main__":
    logger.info("=== Ansible disk-ticket agent run starting (delegates to ticket agent) ===")
    try:
        ticket_agent_service.run()
    except Exception as e:
        logger.exception("Unhandled error in ansible agent run: %s", e)
    logger.info("=== Ansible disk-ticket agent run finished ===")
