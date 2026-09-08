#!/usr/bin/env python
"""
check and answer the tickets according to the data in the knowledgebase.

DEPRECATED as a separate owner: this now runs the unified ticket agent
(KB + Ansible + L2 + L1). Prefer run_ticket_agent.py.
"""

import logging
from logging_setup import configure_logging

configure_logging("kb_autoanswer_agent.log")
logger = logging.getLogger(__name__)

from services import ticket_agent_service  # noqa: E402  (after logging setup)

if __name__ == "__main__":
    logger.info("=== KB auto-answer agent run starting (delegates to ticket agent) ===")
    try:
        ticket_agent_service.run()
    except Exception as e:
        logger.exception("Unhandled error in KB auto-answer agent run: %s", e)
    logger.info("=== KB auto-answer agent run finished ===")
