#!/usr/bin/env python
"""
Entrypoint: one agentic pass over new/open tickets
(KB vector retrieve, Ansible catalog, Terraform catalog, L1/L2/L3).
Run this on a cron/systemd timer, e.g. every 5 minutes.

Do not also run run_kb_autoanswer_agent.py or run_ansible_agent.py on the
same tickets — those entrypoints now call this same service so a leftover
cron is safe, but prefer this script as the only decision-center job.
"""

import logging
from logging_setup import configure_logging

configure_logging("ticket_agent.log")
logger = logging.getLogger(__name__)

from services import ticket_agent_service  # noqa: E402  (after logging setup)

if __name__ == "__main__":
    logger.info("=== Ticket agent run starting ===")
    try:
        ticket_agent_service.run()
    except Exception as e:
        logger.exception("Unhandled error in ticket agent run: %s", e)
    logger.info("=== Ticket agent run finished ===")
