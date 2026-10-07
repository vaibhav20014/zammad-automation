"""
tools/terraform_common.py

Shared subprocess + file-writing helpers for the AWS and Azure
Terraform tool files. Not registered as an agent tool itself.
"""

import os
import subprocess

from config import settings


def workspace_dir(workspace: str) -> str:
    return os.path.join(settings.terraform_workspaces_dir, workspace)


def run_terraform(workspace: str, args: list, timeout: int = 300) -> str:
    workdir = workspace_dir(workspace)
    if not os.path.isdir(workdir):
        os.makedirs(workdir, exist_ok=True)

    cmd = ["terraform"] + args
    try:
        result = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Terraform command against workspace '{workspace}' timed out."

    output = result.stdout.strip() or result.stderr.strip()
    if result.returncode != 0:
        return f"Terraform command against '{workspace}' failed:\n{output}"
    return output


def write_resource_file(workspace: str, filename: str, content: str) -> None:
    """
    Writes (overwrites) one resource's .tf definition as its own file
    inside the workspace, so each resource can be added/removed
    independently without touching a shared monolithic file.
    """
    workdir = workspace_dir(workspace)
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, filename)
    with open(path, "w") as f:
        f.write(content)


def apply_after_write(workspace: str) -> str:
    """
    Runs init (safe if already initialized) then apply -auto-approve,
    returning apply's output.
    """
    init_result = run_terraform(workspace, ["init", "-no-color"], timeout=120)
    if "failed" in init_result.lower():
        return f"Init failed, apply not attempted:\n{init_result}"
    return run_terraform(workspace, ["apply", "-auto-approve", "-no-color"], timeout=600)