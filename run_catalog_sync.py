#!/usr/bin/env python
"""
Optional Git pull of Ansible/Terraform catalogs, then rebuild the KB vector index.
Run on a slower timer than the ticket agent (e.g. hourly).
"""

import logging
from logging_setup import configure_logging

configure_logging("catalog_sync.log")
logger = logging.getLogger(__name__)

from clients import git_scm_client  # noqa: E402
from kb import knowledge_base_client, vector_store  # noqa: E402

if __name__ == "__main__":
    logger.info("=== Catalog sync starting ===")
    try:
        git_scm_client.sync_all()
        count = vector_store.rebuild_index(knowledge_base_client.list_all_answers())
        logger.info("Vector index now has %d article(s).", count)
    except Exception as e:
        logger.exception("Unhandled error in catalog sync: %s", e)
    logger.info("=== Catalog sync finished ===")
