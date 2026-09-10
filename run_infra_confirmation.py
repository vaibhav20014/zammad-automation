#!/usr/bin/env python
"""
Entrypoint: customer-confirmation gate for infra-creation tickets.
Run this BEFORE run_ticket_agent.py in your cron schedule.
"""

import logging
from logging_setup import configure_logging

configure_logging("infra_confirmation.log")
logger = logging.getLogger(__name__)

from services import infra_confirmation_service  # noqa: E402

if __name__ == "__main__":
    logger.info("=== Infra confirmation gate run starting ===")
    infra_confirmation_service.run()
    logger.info("=== Infra confirmation gate run finished ===")