"""
Rotating file + console logging setup. Calls load_dotenv() directly
(not relying on import order) since config.py being imported first
isn't guaranteed - this was the fix for the .env-not-loaded-before-
logging-reads-it bug from the original build.
"""

import io
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.getcwd(), "logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_configured = False


def configure_logging(log_filename: str) -> None:
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, log_filename)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # UTF-8 reconfiguration + backslashreplace fallback for Windows console
    # logging crashes on emoji/unicode in ticket text (original bug fix)
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    else:
        stream = io.TextIOWrapper(
            stream.buffer, encoding="utf-8", errors="backslashreplace"
        )
    console_handler = logging.StreamHandler(stream)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _configured = True