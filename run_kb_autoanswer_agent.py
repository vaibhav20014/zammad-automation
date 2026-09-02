"""
check and answer the tickets according to the data in the knowledgebase.
"""

import logging
from logging_setup import configure_logging

configure_logging("kb_autoanswer_agent.log")
logger = logging.getLogger(__name__)

from services import kb_auto_answer_service  # noqa: E402  (after logging setup)

if __name__ == "__main__":
    logger.info("=== KB auto-answer agent run starting ===")
    try:
        kb_auto_answer_service.run()
    except Exception as e:
        logger.exception(f"Unhandled error in KB auto-answer agent run: {e}")
    logger.info("=== KB auto-answer agent run finished ===")