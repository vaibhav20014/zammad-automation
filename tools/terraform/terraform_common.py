"""
Shared Terraform helpers for the AWS and Azure tool files.
Not an agent tool itself.
"""

import logging
import os
import re
import subprocess

from config import settings

logger = logging.getLogger(__name__)

_FILENAME_RE = re.compile(r"[a-z0-9_]+\.tf")


def allowed_workspaces() -> list:
    """A workspace exists only if its folder has a provider.tf."""
    base = settings.terraform_workspaces_dir
    if not os.path.isdir(base):
        return []
    return sorted(
        d for d in os.listdir(base)
        if os.path.isfile(os.path.join(base, d, "provider.tf"))
    )


def validate_workspace(workspace: str) -> str:
    if workspace not in allowed_workspaces():
        raise ValueError(
            f"Workspace {workspace!r} is not allowed. Allowed: {allowed_workspaces()}"
        )
    return workspace


def workspace_dir(workspace: str) -> str:
    validate_workspace(workspace)
    return os.path.join(settings.terraform_workspaces_dir, workspace)


def _run(workspace: str, args: list, timeout: int) -> tuple:
    """Returns (ok, output). Never raises on a Terraform failure."""
    try:
        workdir = workspace_dir(workspace)
    except ValueError as e:
        return False, f"WORKSPACE_NOT_ALLOWED - {e}"

    try:
        result = subprocess.run(
            ["terraform"] + args,
            cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return False, "TERRAFORM_NOT_INSTALLED - the terraform command was not found on this machine."
    except subprocess.TimeoutExpired:
        return False, f"TERRAFORM_TIMEOUT - '{' '.join(args)}' did not finish in {timeout}s."

    output = (result.stdout.strip() or result.stderr.strip())
    if result.returncode != 0:
        logger.error("terraform %s failed in %s: %s", args, workspace, output[:500])
        return False, f"TERRAFORM_FAILED - {output[:1500]}"
    return True, output


def run_terraform(workspace: str, args: list, timeout: int = 300) -> str:
    """Tool-friendly wrapper: always returns a string, errors start with a label."""
    _, output = _run(workspace, args, timeout)
    return output


def write_resource_file(workspace: str, filename: str, content: str) -> None:
    """Writes one resource's .tf file into an existing, allowed workspace."""
    if not _FILENAME_RE.fullmatch(filename):
        raise ValueError(f"Invalid terraform filename: {filename!r}")
    path = os.path.join(workspace_dir(workspace), filename)
    with open(path, "w") as f:
        f.write(content)
    logger.info("Wrote %s", path)


def apply_after_write(workspace: str) -> str:
    """init (safe to repeat), then apply. Stops and reports if init fails."""
    ok, output = _run(workspace, ["init", "-input=false", "-no-color"], timeout=180)
    if not ok:
        return f"INIT_FAILED, apply not attempted: {output}"
    ok, output = _run(
        workspace, ["apply", "-auto-approve", "-input=false", "-no-color"], timeout=600
    )
    return output if ok else f"APPLY_FAILED: {output}"