"""
Central logging configuration.

Import `configure_logging()` once from each entrypoint script
(run_ansible_agent.py, run_zabbix_agent.py). Every other module just does:

    import logging
    logger = logging.getLogger(__name__)

and gets timestamps, levels, and rotation for free.
"""

import logging
import logging.handlers
import os
from dotenv import load_dotenv
load_dotenv()
LOG_DIR = os.getenv("LOG_DIR", "/home/ubuntu/zammad-automation/logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(log_filename: str) -> None:
    """
    Call once per process, from the entrypoint script only.

    log_filename: e.g. "ansible_agent.log" or "zabbix_agent.log"
    Keeps logs separate per agent so they don't interleave in one file.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, log_filename)

    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)

    # Avoid duplicate handlers if configure_logging() gets called twice
    if root.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    logging.getLogger(__name__).info(
        "Logging configured. level=%s file=%s", LOG_LEVEL, log_path
    )
