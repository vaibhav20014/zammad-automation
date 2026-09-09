#!/usr/bin/env python
"""
Entrypoint: apply Terraform plans for tickets an L2 human has explicitly
approved (tagged "approved-for-apply" in the Zammad UI).

Run this on its own cron/systemd timer, separate from run_ticket_agent.py.
It never applies anything the AI decided on its own — the approval tag,
added by a human, is the only thing that triggers an apply here.
"""

import logging
from logging_setup import configure_logging

configure_logging("terraform_apply.log")
logger = logging.getLogger(__name__)

from services import terraform_apply_service  # noqa: E402  (after logging setup)

if __name__ == "__main__":
    logger.info("=== Terraform apply run starting ===")
    terraform_apply_service.run()
    logger.info("=== Terraform apply run finished ===")