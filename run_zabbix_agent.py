"""
Entrypoint: polls Zabbix for open problems and creates Zammad tickets.
Run this on a cron/systemd timer, e.g. every minute.
"""

import logging
from logging_setup import configure_logging

configure_logging("zabbix_agent.log")
logger = logging.getLogger(__name__)

from services import zabbix_poll_service  # noqa: E402  (after logging setup)

if __name__ == "__main__":
    logger.info("=== Zabbix poll agent run starting ===")
    try:
        zabbix_poll_service.run()
    except Exception as e:
        logger.exception(f"Unhandled error in zabbix agent run: {e}")
    logger.info("=== Zabbix poll agent run finished ===")
