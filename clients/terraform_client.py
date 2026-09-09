"""
Terraform plan/apply against a catalog module directory.

Apply is opt-in (catalog auto_apply AND TERRAFORM_AUTO_APPLY). Plan-only
runs still return structured output so the router can escalate for approval.
"""

import logging
import os
import subprocess
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


def resolve_instance_type(module: dict, vcpu, memory_gb) -> str | None:
    try:
        want_cpu = int(vcpu)
        want_mem = int(memory_gb)
    except (TypeError, ValueError):
        return None
    for size in module.get("allowed_sizes") or []:
        try:
            if int(size.get("vcpu")) == want_cpu and int(size.get("memory_gb")) == want_mem:
                return str(size.get("instance_type") or "")
        except (TypeError, ValueError):
            continue
    return None


def run_module(
    module_rel_path: str,
    auto_apply: bool = False,
    tf_vars: dict | None = None,
) -> dict:
    module_dir = Path(settings.terraform_dir) / module_rel_path
    if not module_dir.is_dir():
        return {
            "ok": False,
            "applied": False,
            "planned": False,
            "error": f"Terraform module directory not found: {module_dir}",
        }

    var_args = _var_args(tf_vars or {})
    init = _run(["init", "-input=false", "-no-color"], module_dir)
    if init["returncode"] != 0:
        return {
            "ok": False,
            "applied": False,
            "planned": False,
            "error": "terraform init failed",
            "stderr": init["stderr"][-2000:],
        }

    plan = _run(
        ["plan", "-input=false", "-no-color", "-detailed-exitcode", *var_args],
        module_dir,
    )
    if plan["returncode"] not in (0, 2):
        return {
            "ok": False,
            "applied": False,
            "planned": False,
            "error": "terraform plan failed",
            "stderr": plan["stderr"][-2000:],
            "stdout": plan["stdout"][-4000:],
            "vars": tf_vars or {},
        }

    result = {
        "ok": True,
        "applied": False,
        "planned": True,
        "has_changes": plan["returncode"] == 2,
        "plan_stdout": plan["stdout"][-4000:],
        "vars": tf_vars or {},
    }

    should_apply = auto_apply and settings.terraform_auto_apply
    if not should_apply:
        result["error"] = (
            "Plan succeeded; apply skipped (set catalog auto_apply and "
            "TERRAFORM_AUTO_APPLY=true to apply)."
        )
        return result

    apply = _run(
        ["apply", "-input=false", "-auto-approve", "-no-color", *var_args],
        module_dir,
    )
    if apply["returncode"] != 0:
        return {
            "ok": False,
            "applied": False,
            "planned": True,
            "error": "terraform apply failed",
            "stderr": apply["stderr"][-2000:],
            "stdout": apply["stdout"][-4000:],
            "vars": tf_vars or {},
        }
    result["applied"] = True
    result["apply_stdout"] = apply["stdout"][-4000:]
    result.pop("error", None)
    return result

def apply_module(module_rel_path: str, tf_vars: dict | None = None) -> dict:
    """Apply a module directly. Only call this after explicit human approval
    (e.g. a ticket tagged approved-for-apply) — it bypasses the AI-path's
    auto_apply gate on purpose, since the approval tag *is* the gate here.
    """
    module_dir = Path(settings.terraform_dir) / module_rel_path
    if not module_dir.is_dir():
        return {"ok": False, "applied": False, "error": f"Terraform module directory not found: {module_dir}"}

    var_args = _var_args(tf_vars or {})
    init = _run(["init", "-input=false", "-no-color"], module_dir)
    if init["returncode"] != 0:
        return {"ok": False, "applied": False, "error": "terraform init failed", "stderr": init["stderr"][-2000:]}

    apply = _run(["apply", "-input=false", "-auto-approve", "-no-color", *var_args], module_dir)
    if apply["returncode"] != 0:
        return {"ok": False, "applied": False, "error": "terraform apply failed",
                "stderr": apply["stderr"][-2000:], "stdout": apply["stdout"][-4000:]}

    return {"ok": True, "applied": True, "apply_stdout": apply["stdout"][-4000:],
            "outputs": get_outputs(module_dir)}


def get_outputs(module_dir: Path) -> dict:
    result = _run(["output", "-json", "-no-color"], module_dir)
    if result["returncode"] != 0:
        return {}
    try:
        import json
        return json.loads(result["stdout"])
    except (ValueError, KeyError):
        return {}

def _var_args(tf_vars: dict) -> list[str]:
    args = []
    for key, value in tf_vars.items():
        if value is None or value == "":
            continue
        args.extend(["-var", f"{key}={value}"])
    return args


def _run(args: list[str], cwd: Path) -> dict:
    cmd = [settings.terraform_bin, *args]
    logger.info("Running %s in %s", " ".join(cmd), cwd)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=600,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        logger.error("terraform binary not found: %s", settings.terraform_bin)
        return {"returncode": 127, "stdout": "", "stderr": "terraform not found"}
    except subprocess.TimeoutExpired:
        logger.error("terraform timed out: %s", cmd)
        return {"returncode": 124, "stdout": "", "stderr": "timeout"}
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }
