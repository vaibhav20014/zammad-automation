"""
Windows Ansible tools: connection config and tool definitions,
self-contained in one file, mirroring tools/linux/ansible_tools.py.

Requirements (inventory-level, not controlled by this file):
  - Each Windows host has ansible_connection=winrm plus ansible_winrm_* vars.
  - [windows:vars] has ansible_become=false (no sudo on Windows).
  - Control node has pywinrm and the ansible.windows collection.

Differences from the Linux version:
  - Uses win_shell (PowerShell) and Windows-native Ansible modules.
  - No logrotate: "log rotation" = checking / clearing Event Logs
    (Application and System only, with an automatic backup first).
  - No zombie processes: the closest practical checks are "Not Responding"
    processes and stopped automatic services.
  - Patching uses ansible.windows.win_updates (no PSWindowsUpdate needed).

Safety: every value coming from the agent is validated before it is
placed into a PowerShell command.
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings
from crewai.tools import tool


# --- Validation helpers ----------------------------------------------------

ALLOWED_EVENT_LOGS = {"Application", "System"}  # never Security

PROTECTED_PROCESSES = {
    "system", "idle", "registry", "smss", "csrss", "wininit", "winlogon",
    "services", "lsass", "svchost", "dwm", "fontdrvhost", "memcompression",
}

PROTECTED_SERVICES = {"winrm", "rpcss", "dcomlaunch", "lsm", "samss", "eventlog"}

_PATH_RE = re.compile(r"^[A-Za-z]:\\[\w\\ .\-()]*$")
_SERVICE_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]$")


def _valid_path(path: str) -> bool:
    return bool(_PATH_RE.match(path)) and ".." not in path


# --- Ad-hoc runner ---------------------------------------------------------

def _run_adhoc_windows(
    target_host: str,
    module_args: str,
    timeout: int = 120,
    module: str = "win_shell",
) -> str:
    """
    Runs `ansible <host> -m <module> -a "<args>"` against the inventory.
    Default module is win_shell (PowerShell). Host must use WinRM.
    """
    cmd = [
        "ansible", target_host,
        "-i", settings.inventory_path,
        "-m", module,
        "-a", module_args,
        "--timeout", "30",
    ]

    env = {**os.environ, "PYTHONWARNINGS": "ignore", "ANSIBLE_NOCOLOR": "1"}

    try:
        result = subprocess.run(
            cmd,
            cwd=settings.playbook_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Ad-hoc command against {target_host} timed out."

    if result.returncode != 0:
        error = result.stdout.strip() or result.stderr.strip()
        return f"Ad-hoc command against {target_host} failed: {error}"

    # Drop ansible's "host | CHANGED | rc=0 >>" header line if present.
    lines = result.stdout.strip().splitlines()
    if lines and re.search(r"\|\s*(CHANGED|SUCCESS)\b", lines[0]):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _failed(output: str) -> bool:
    return output.startswith("Ad-hoc command")


# --- Disk ------------------------------------------------------------------

@tool("check_disk_usage_windows")
def check_disk_usage_windows(target_host: str) -> str:
    """
    Reports size, used, free and percent used for every fixed drive on
    the Windows host. Read-only - it does not clean anything. If a drive
    is above ~80%, use find_large_files_windows to see what is taking
    space, then clean_temp_files_windows, and call this tool again
    afterward to confirm usage dropped.
    """
    ps = (
        "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
        "Select-Object @{N='Drive';E={$_.DeviceID}}, "
        "@{N='SizeGB';E={[math]::Round($_.Size/1GB,1)}}, "
        "@{N='UsedGB';E={[math]::Round(($_.Size-$_.FreeSpace)/1GB,1)}}, "
        "@{N='FreeGB';E={[math]::Round($_.FreeSpace/1GB,1)}}, "
        "@{N='PercentUsed';E={[math]::Round((($_.Size-$_.FreeSpace)/$_.Size)*100)}} "
        "| Format-Table -AutoSize | Out-String -Width 200"
    )
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip() or _failed(output):
        return f"{target_host}: DISK_CHECK_FAILED - {output}"
    return f"{target_host} disk usage:\n{output}"


@tool("find_large_files_windows")
def find_large_files_windows(target_host: str, search_path: str = "C:\\Windows\\Temp", top_n: int = 10) -> str:
    """
    Reports the top_n largest files under search_path. Read-only - use
    before clean_temp_files_windows to see what is taking space, and
    again afterward to verify the cleanup reduced it. Can be slow on a
    whole drive, so prefer a narrow path (e.g. C:\\Windows\\Temp).
    """
    if not _valid_path(search_path):
        return f"{target_host}: invalid search_path '{search_path}'. Use a path like C:\\Windows\\Temp."
    top_n = max(1, min(int(top_n), 50))

    ps = (
        "Get-ChildItem -Path '" + search_path + "' -Recurse -File -ErrorAction SilentlyContinue | "
        "Sort-Object Length -Descending | Select-Object -First " + str(top_n) + " "
        "@{N='SizeMB';E={[math]::Round($_.Length/1MB,1)}}, FullName | "
        "Format-Table -AutoSize | Out-String -Width 250"
    )
    output = _run_adhoc_windows(target_host, ps, timeout=180)
    if not output.strip() or _failed(output):
        return f"{target_host}: no files found under {search_path} (or command failed). {output}"
    return f"{target_host} largest files under {search_path}:\n{output}"


# --- Temp file cleanup -----------------------------------------------------

@tool("clean_temp_files_windows")
def clean_temp_files_windows(target_host: str, older_than_days: int = 7) -> str:
    """
    Deletes files older than older_than_days from C:\\Windows\\Temp and
    the temp folder of the Ansible connection user. Does not touch
    anything outside those locations. Call check_disk_usage_windows
    afterward to verify.
    """
    days = max(1, int(older_than_days))
    ps = (
        "$cutoff = (Get-Date).AddDays(-" + str(days) + "); "
        "$paths = @('C:\\Windows\\Temp', $env:TEMP); "
        "$removed = 0; "
        "foreach ($p in $paths) { "
        "Get-ChildItem -Path $p -Recurse -File -Force -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LastWriteTime -lt $cutoff } | "
        "ForEach-Object { "
        "try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop; $removed++ } catch {} "
        "} }; "
        "Write-Output \"Removed $removed file(s)\""
    )
    output = _run_adhoc_windows(target_host, ps, timeout=180)
    if not output.strip() or _failed(output):
        return f"{target_host}: cleanup failed or produced no output. {output}"
    return f"{target_host}: {output.strip()} older than {days} day(s) from temp folders."


# --- Event log management (Windows equivalent of log rotation) -------------

@tool("check_event_log_size_windows")
def check_event_log_size_windows(target_host: str, log_name: str = "Application") -> str:
    """
    Reports the current size, max size and record count of the
    Application or System Event Log. Read-only - Windows has no
    logrotate, so this is the check before deciding whether
    clear_event_log_windows is warranted.
    """
    if log_name not in ALLOWED_EVENT_LOGS:
        return f"{target_host}: log_name must be one of {sorted(ALLOWED_EVENT_LOGS)}."

    ps = (
        "Get-WinEvent -ListLog '" + log_name + "' | "
        "Select-Object LogName, @{N='SizeMB';E={[math]::Round($_.FileSize/1MB,1)}}, "
        "@{N='MaxSizeMB';E={[math]::Round($_.MaximumSizeInBytes/1MB,1)}}, RecordCount | Format-List"
    )
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip() or _failed(output):
        return f"{target_host}: could not read event log '{log_name}'. {output}"
    return f"{target_host} event log '{log_name}':\n{output}"


@tool("clear_event_log_windows")
def clear_event_log_windows(target_host: str, log_name: str = "Application") -> str:
    """
    Backs up and then clears the Application or System Event Log. The
    Security log is deliberately not allowed. Destructive to that log's
    live history - call check_event_log_size_windows first to confirm
    it is actually full, and again afterward to verify it cleared.
    A backup is saved to C:\\Windows\\Temp\\<log>_backup.evtx first.
    """
    if log_name not in ALLOWED_EVENT_LOGS:
        return f"{target_host}: refused. log_name must be one of {sorted(ALLOWED_EVENT_LOGS)}."

    backup = "C:\\Windows\\Temp\\" + log_name + "_backup.evtx"
    ps = (
        "if (Test-Path '" + backup + "') { Remove-Item '" + backup + "' -Force }; "
        "wevtutil epl " + log_name + " '" + backup + "'; "
        "if ($LASTEXITCODE -ne 0) { Write-Output 'BACKUP_FAILED - log not cleared'; exit 0 }; "
        "wevtutil cl " + log_name + "; "
        "Write-Output 'Backed up to " + backup + " and cleared " + log_name + "'"
    )
    output = _run_adhoc_windows(target_host, ps, timeout=180)
    if not output.strip() or _failed(output):
        return f"{target_host}: clear command failed or gave no confirmation. {output}"
    return f"{target_host}: {output.strip()}"


# --- Unresponsive processes / stopped services -----------------------------

@tool("find_unresponsive_processes_windows")
def find_unresponsive_processes_windows(target_host: str) -> str:
    """
    Reports processes marked "Not Responding" by Windows (the closest
    equivalent to a Unix zombie). Only processes with a window can be
    detected, so an empty result is normal on a server. Read-only -
    call before AND after stop_process_windows.
    """
    ps = (
        "Get-Process | Where-Object { $_.Responding -eq $false } | "
        "Select-Object Id, ProcessName | Format-Table -AutoSize | Out-String -Width 200"
    )
    output = _run_adhoc_windows(target_host, ps)
    if _failed(output):
        return f"{target_host}: check failed. {output}"
    if not output.strip():
        return f"{target_host}: no unresponsive processes found."
    return f"{target_host} unresponsive processes:\n{output}"


@tool("stop_process_windows")
def stop_process_windows(target_host: str, process_id: int) -> str:
    """
    Force-stops one process by PID. Use find_unresponsive_processes_windows
    first to get the PID - never guess one. Critical system processes
    (lsass, csrss, svchost, etc.) are refused. Call
    find_unresponsive_processes_windows again afterward to confirm.
    """
    pid = int(process_id)
    if pid <= 4:
        return f"{target_host}: refused - PID {pid} is a system process."

    protected = ",".join("'" + p + "'" for p in sorted(PROTECTED_PROCESSES))
    ps = (
        "$p = Get-Process -Id " + str(pid) + " -ErrorAction Stop; "
        "if (@(" + protected + ") -contains $p.ProcessName.ToLower()) "
        "{ Write-Output ('REFUSED: ' + $p.ProcessName + ' is a protected process') } "
        "else { Stop-Process -Id " + str(pid) + " -Force -ErrorAction Stop; "
        "Write-Output ('Stopped ' + $p.ProcessName + ' PID " + str(pid) + "') }"
    )
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip() or _failed(output):
        return f"{target_host}: stop command for PID {pid} failed or gave no confirmation. {output}"
    return f"{target_host}: {output.strip()}"


@tool("find_stopped_services_windows")
def find_stopped_services_windows(target_host: str) -> str:
    """
    Lists services set to start Automatically that are not currently
    running. Read-only - call before restart_service_windows, and again
    afterward to verify the service came back.
    """
    ps = (
        "Get-CimInstance Win32_Service | "
        "Where-Object { $_.StartMode -eq 'Auto' -and $_.State -ne 'Running' } | "
        "Select-Object Name, State, ExitCode | Format-Table -AutoSize | Out-String -Width 200"
    )
    output = _run_adhoc_windows(target_host, ps)
    if _failed(output):
        return f"{target_host}: check failed. {output}"
    if not output.strip():
        return f"{target_host}: all automatic services are running."
    return f"{target_host} automatic services not running:\n{output}"


@tool("restart_service_windows")
def restart_service_windows(target_host: str, service_name: str) -> str:
    """
    Restarts one Windows service by its service name (the short Name from
    find_stopped_services_windows, e.g. Spooler). WinRM and core system
    services are refused because restarting them would cut the connection
    or destabilise the host. Call find_stopped_services_windows afterward.
    """
    if not _SERVICE_RE.match(service_name):
        return f"{target_host}: invalid service name '{service_name}'."
    if service_name.lower() in PROTECTED_SERVICES:
        return f"{target_host}: refused - '{service_name}' is a protected service."

    output = _run_adhoc_windows(
        target_host,
        f"name={service_name} state=restarted",
        timeout=120,
        module="ansible.windows.win_service",
    )
    if _failed(output):
        return f"{target_host}: restart of {service_name} failed. {output}"
    state = re.search(r'"state":\s*"(\w+)"', output)
    return f"{target_host}: service {service_name} restart finished, state={state.group(1) if state else 'unknown'}."


# --- Patching --------------------------------------------------------------

def _update_count(output: str):
    m = re.search(r'"found_update_count":\s*(\d+)', output)
    return int(m.group(1)) if m else None


@tool("check_pending_updates_windows")
def check_pending_updates_windows(target_host: str) -> str:
    """
    Reports how many Security/Critical Windows Updates are pending.
    Read-only - call before patch_os_windows, and after to confirm the
    updates applied (should be 0, or a reboot may still be pending).
    Uses ansible.windows.win_updates; no extra module needed on the host.
    """
    output = _run_adhoc_windows(
        target_host,
        "category_names=SecurityUpdates,CriticalUpdates state=searched",
        timeout=600,
        module="ansible.windows.win_updates",
    )
    if _failed(output):
        return f"{target_host}: could not check updates. {output}"
    count = _update_count(output)
    if count is None:
        return f"{target_host}: update check ran but result could not be parsed:\n{output[:500]}"
    return f"{target_host}: {count} update(s) pending."


@tool("patch_os_windows")
def patch_os_windows(target_host: str) -> str:
    """
    Installs Security and Critical Windows Updates. Real system-changing
    operation; may need a reboot to complete. This tool does NOT reboot
    the host. Call check_pending_updates_windows afterward to confirm.
    """
    output = _run_adhoc_windows(
        target_host,
        "category_names=SecurityUpdates,CriticalUpdates state=installed reboot=false",
        timeout=3600,
        module="ansible.windows.win_updates",
    )
    if _failed(output):
        return f"{target_host}: patch run failed. {output}"

    installed = re.search(r'"installed_update_count":\s*(\d+)', output)
    reboot = re.search(r'"reboot_required":\s*(true|false)', output, re.IGNORECASE)
    msg = f"{target_host}: patch run finished."
    if installed:
        msg += f" Installed {installed.group(1)} update(s)."
    if reboot and reboot.group(1).lower() == "true":
        msg += " A reboot is required to complete the patching (not done automatically)."
    return msg


def get_tools() -> list:
    """Returns the tool list for a Windows-capable agent's `tools=` field."""
    return [
        check_disk_usage_windows,
        find_large_files_windows,
        clean_temp_files_windows,
        check_event_log_size_windows,
        clear_event_log_windows,
        find_unresponsive_processes_windows,
        stop_process_windows,
        find_stopped_services_windows,
        restart_service_windows,
        check_pending_updates_windows,
        patch_os_windows,
    ]