"""
Linux Ansible tools: connection config and tool definitions, self-contained in one file.

Tools use Ansible ad-hoc mode (not a playbook) via subprocess, so new
one-off maintenance operations can be added here without needing a
matching .yml file first. Read-only "check_"/"find_" tools are kept
separate from action-taking ones so the agent (and logs) can see what's
wrong before anything changes, and so the same read-only tool can be
called again AFTER an action to verify it worked - e.g. call
find_zombie_processes_linux again after kill_zombie_processes_linux to
confirm cleanup succeeded, rather than trusting the action tool's own
self-report.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings
from clients import ansible_client
from crewai.tools import tool


def _run_adhoc(target_host: str, module: str, module_args: str, become: bool = False) -> str:
    cmd = [
        "ansible", target_host,
        "-i", settings.inventory_path,
        "-m", module,
        "-a", module_args,
    ]
    if become:
        cmd.append("--become")

    try:
        result = subprocess.run(
            cmd, cwd=settings.playbook_dir, capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return f"Ad-hoc command against {target_host} timed out."

    if result.returncode != 0:
        return f"Ad-hoc command against {target_host} failed: {result.stderr.strip() or result.stdout.strip()}"

    return result.stdout.strip()


# --- Disk ---------------------------------------------------------------

@tool("check_disk_usage")
def check_disk_usage(target_host: str) -> str:
    """
    Runs the disk-check-and-clean Ansible playbook against target_host
    and returns a summary of the result.
    """
    output = ansible_client.run_disk_check(target_host=target_host)
    if not output:
        return f"Ansible run against {target_host} failed or returned no output."

    for play in output.get("plays", []):
        for t in play.get("tasks", []):
            task_result = t.get("hosts", {}).get(target_host, {})
            if "msg" in task_result:
                return f"{target_host}: {task_result['msg']}"

    return f"Ansible run against {target_host} completed but produced no readable message."


@tool("run_playbook")
def run_playbook(target_host: str) -> str:
    """
    Alias of check_disk_usage, kept as a separate tool name in case the
    router/specialist agent's prompts already reference this name.
    """
    return check_disk_usage.func(target_host)


@tool("find_large_files_linux")
def find_large_files_linux(target_host: str, search_path: str = "/", top_n: int = 10) -> str:
    """
    Reports the top_n largest files under search_path. Read-only - use
    before clean_temp_files_linux to see what's taking up space, and
    again after with search_path="/tmp" (or /var/tmp) to verify the
    cleanup actually reduced what's there.
    """
    cmd = (
        f"find {search_path} -xdev -type f -printf '%s %p\\n' 2>/dev/null "
        f"| sort -rn | head -n {top_n} "
        f"| awk '{{printf \"%.1fMB  %s\\n\", $1/1048576, $2}}'"
    )
    output = _run_adhoc(target_host, "shell", cmd)
    if not output.strip():
        return f"{target_host}: no files found under {search_path} (or command failed)."
    return f"{target_host} largest files under {search_path}:\n{output}"


# --- Log & temp cleanup --------------------------------------------------

@tool("clean_temp_files_linux")
def clean_temp_files_linux(target_host: str, older_than_days: int = 7) -> str:
    """
    Deletes files in /tmp and /var/tmp older than older_than_days.
    Does not touch anything outside those two directories.
    """
    cmd = (
        f"find /tmp /var/tmp -xdev -type f -mtime +{older_than_days} -print -delete 2>/dev/null | wc -l"
    )
    output = _run_adhoc(target_host, "shell", cmd, become=True)
    count = output.strip() or "0"
    return f"{target_host}: removed {count} file(s) older than {older_than_days} day(s) from /tmp and /var/tmp."


@tool("rotate_logs_linux")
def rotate_logs_linux(target_host: str) -> str:
    """
    Forces an immediate logrotate run using the host's existing
    logrotate config (/etc/logrotate.conf), rather than truncating logs
    directly. Call check_log_rotation_status_linux afterward to verify
    it actually ran and rotated files.
    """
    cmd = "logrotate -f /etc/logrotate.conf"
    output = _run_adhoc(target_host, "shell", cmd, become=True)
    if not output.strip():
        return f"{target_host}: logrotate ran with no output (likely succeeded silently)."
    return f"{target_host} logrotate output:\n{output}"


@tool("check_log_rotation_status_linux")
def check_log_rotation_status_linux(target_host: str) -> str:
    """
    Reports when logrotate last actually ran and rotated each log, by
    reading logrotate's own status file. Read-only - use after calling
    rotate_logs_linux to verify it took effect, since rotate_logs_linux
    can exit cleanly without actually rotating anything if nothing met
    its size/age thresholds.
    """
    cmd = "cat /var/lib/logrotate/status 2>/dev/null || cat /var/lib/logrotate.status 2>/dev/null"
    output = _run_adhoc(target_host, "shell", cmd)
    if not output.strip():
        return f"{target_host}: could not read logrotate status file (path may differ on this distro)."
    return f"{target_host} logrotate status:\n{output}"


# --- Zombie processes ------------------------------------------------------

@tool("find_zombie_processes_linux")
def find_zombie_processes_linux(target_host: str) -> str:
    """
    Reports zombie (defunct) processes on a Linux host: PID, parent PID,
    and status. Read-only - call this both BEFORE kill_zombie_processes_linux
    (to see what's wrong) and AFTER it (to verify the fix actually worked),
    rather than trusting kill_zombie_processes_linux's own report alone.
    """
    cmd = "ps -eo pid,ppid,stat,comm | awk '$3 ~ /Z/ {print $0}'"
    output = _run_adhoc(target_host, "shell", cmd)
    if not output.strip():
        return f"{target_host}: no zombie processes found."
    return f"{target_host} zombie processes (pid ppid stat comm):\n{output}"


@tool("kill_zombie_processes_linux")
def kill_zombie_processes_linux(target_host: str) -> str:
    """
    Attempts to clear zombie processes on a Linux host. A zombie is
    already dead - it can't be killed directly - so this sends SIGCHLD
    to each zombie's parent PID as a best-effort nudge to make the
    parent reap it. If zombies persist after this, the parent process
    itself likely needs to be restarted, which this tool deliberately
    does NOT do on its own. Call find_zombie_processes_linux again
    after this to independently confirm the result.
    """
    zombies = find_zombie_processes_linux.func(target_host)
    if "no zombie processes found" in zombies:
        return zombies

    cmd = (
        "for ppid in $(ps -eo pid,ppid,stat | awk '$3 ~ /Z/ {print $2}' | sort -u); "
        "do kill -s CHLD \"$ppid\" 2>/dev/null; done; "
        "ps -eo pid,ppid,stat,comm | awk '$3 ~ /Z/ {print $0}'"
    )
    after = _run_adhoc(target_host, "shell", cmd, become=True)

    if not after.strip():
        return f"{target_host}: sent SIGCHLD to parent process(es); zombies cleared."
    return (
        f"{target_host}: sent SIGCHLD to parent process(es), but some zombies remain "
        f"(their parent likely needs to be restarted manually):\n{after}"
    )


# --- Patching --------------------------------------------------------------

@tool("patch_os_linux")
def patch_os_linux(target_host: str) -> str:
    """
    Applies available OS security/package updates on a Linux host.
    Detects apt (Debian/Ubuntu) vs yum/dnf (RHEL/CentOS) automatically.
    Call check_pending_updates_linux afterward to verify updates were
    actually applied, since a partial/interrupted run can exit without
    a clear error.
    """
    detect_cmd = "command -v apt-get || command -v dnf || command -v yum"
    pkg_manager_path = _run_adhoc(target_host, "shell", detect_cmd)

    if "apt-get" in pkg_manager_path:
        update_cmd = "apt-get update -y && apt-get upgrade -y"
    elif "dnf" in pkg_manager_path:
        update_cmd = "dnf upgrade -y"
    elif "yum" in pkg_manager_path:
        update_cmd = "yum update -y"
    else:
        return f"{target_host}: could not detect a supported package manager (apt/dnf/yum)."

    output = _run_adhoc(target_host, "shell", update_cmd, become=True)
    return f"{target_host} patch run output:\n{output}"


@tool("check_pending_updates_linux")
def check_pending_updates_linux(target_host: str) -> str:
    """
    Reports how many package updates are still pending. Read-only -
    call BEFORE patch_os_linux to see what's outstanding, and AFTER to
    confirm the patch run actually applied them (should report 0
    pending, or close to it, afterward).
    """
    detect_cmd = "command -v apt-get || command -v dnf || command -v yum"
    pkg_manager_path = _run_adhoc(target_host, "shell", detect_cmd)

    if "apt-get" in pkg_manager_path:
        check_cmd = "apt list --upgradable 2>/dev/null | grep -v '^Listing' | wc -l"
    elif "dnf" in pkg_manager_path:
        check_cmd = "dnf check-update --quiet | grep -c '^[a-zA-Z]'"
    elif "yum" in pkg_manager_path:
        check_cmd = "yum check-update --quiet | grep -c '^[a-zA-Z]'"
    else:
        return f"{target_host}: could not detect a supported package manager (apt/dnf/yum)."

    output = _run_adhoc(target_host, "shell", check_cmd)
    count = output.strip() or "0"
    return f"{target_host}: {count} package update(s) pending."


def get_tools() -> list:
    """Returns the tool list for the Ansible agent's `tools=` field."""
    return [
        run_playbook,
        check_disk_usage,
        find_large_files_linux,
        clean_temp_files_linux,
        rotate_logs_linux,
        check_log_rotation_status_linux,
        find_zombie_processes_linux,
        kill_zombie_processes_linux,
        patch_os_linux,
        check_pending_updates_linux,
    ]