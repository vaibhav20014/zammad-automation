"""
Optional Git SCM sync for Ansible playbooks and Terraform modules.

Disabled unless GIT_SYNC_ENABLED=true and a remote is set. Never force-pushes.
"""

import logging
import subprocess
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


def sync_all() -> None:
    if not settings.git_sync_enabled:
        logger.info("Git SCM sync disabled (GIT_SYNC_ENABLED=false).")
        return
    if settings.ansible_git_remote:
        sync_repo(
            settings.playbook_dir,
            settings.ansible_git_remote,
            settings.ansible_git_branch,
        )
    if settings.terraform_git_remote:
        sync_repo(
            settings.terraform_dir,
            settings.terraform_git_remote,
            settings.terraform_git_branch,
        )


def sync_repo(path: str, remote: str, branch: str) -> bool:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git_dir = dest / ".git"
    try:
        if git_dir.is_dir():
            logger.info("git pull %s branch=%s", dest, branch)
            pull = _git(["-C", str(dest), "pull", "--ff-only", "origin", branch])
            return pull == 0
        if dest.exists() and any(dest.iterdir()):
            logger.error(
                "Refusing to clone into non-empty non-git directory: %s", dest
            )
            return False
        logger.info("git clone %s -> %s", remote, dest)
        clone = _git(["clone", "--branch", branch, "--single-branch", remote, str(dest)])
        return clone == 0
    except FileNotFoundError:
        logger.error("git is not installed or not on PATH")
        return False


def _git(args: list[str]) -> int:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        logger.error("git %s failed: %s", args, (proc.stderr or "").strip())
    return proc.returncode
