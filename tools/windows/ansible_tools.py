"""
Windows Ansible tools: connection config and tool definitions,
self-contained in one file, mirroring tools/linux/ansible_tools.py.

IMPORTANT differences from the Linux version:
  - Uses the `win_shell` Ansible module (PowerShell) instead of `shell`.
  - Requires each Windows host in the inventory to have
    ansible_connection: winrm set (plus ansible_winrm_* auth vars) -
    this is an inventory-level config, not something this file controls.
  - No --become flag for privilege escalation the way Linux has sudo -
    Windows privilege elevation is handled via the connection's auth
    user and ansible_become/become_method=runas if needed; left out
    here since it depends on the inventory's specific setup.
  - Some tools are approximate equivalents, not exact ports:
      - Windows has no logrotate; "log rotation" here means managing
        Windows Event Log size/retention instead.
      - Windows has no true zombie process concept (a zombie is a
        POSIX-specific state); the closest practical equivalent is a
        process that's "Not Responding" - handled differently below.
      - OS patching here uses the PSWindowsUpdate PowerShell module,
        which must already be installed on target hosts - this file
        does not install it for you. UNCONFIRMED until tested.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings
from crewai.tools import tool


def _run_adhoc_windows(target_host: str, module_args: str, timeout: int = 120) -> str:
    """
    Runs `ansible <host> -m win_shell -a "<powershell>"` against the
    inventory. Host must have ansible_connection: winrm configured.
    """
    cmd = [
        "ansible", target_host,
        "-i", settings.inventory_path,
        "-m", "win_shell",
        "-a", module_args,
    ]

    try:
        result = subprocess.run(
            cmd, cwd=settings.playbook_dir, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Ad-hoc command against {target_host} timed out."

    if result.returncode != 0:
        return f"Ad-hoc command against {target_host} failed: {result.stderr.strip() or result.stdout.strip()}"

    return result.stdout.strip()


# --- Disk ---------------------------------------------------------------

@tool("check_disk_usage_windows")
def check_disk_usage_windows(target_host: str, drive_letter: str = "C") -> str:
    """
    Reports free vs. total space on the given drive. Read-only - call
    before clean_temp_files_windows to see if cleanup is warranted.
    """
    ps = (
        f"Get-PSDrive {drive_letter} | "
        f"Select-Object @{{N='UsedGB';E={{[math]::Round($_.Used/1GB,2)}}}}, "
        f"@{{N='FreeGB';E={{[math]::Round($_.Free/1GB,2)}}}} | Format-List"
    )
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip():
        return f"{target_host}: could not read disk usage for drive {drive_letter}."
    return f"{target_host} drive {drive_letter}: usage:\n{output}"


@tool("find_large_files_windows")
def find_large_files_windows(target_host: str, search_path: str = "C:\\", top_n: int = 10) -> str:
    """
    Reports the top_n largest files under search_path. Read-only - use
    before/after clean_temp_files_windows to verify cleanup actually
    reduced what's there. Can be slow on a large drive - prefer a
    narrower search_path (e.g. C:\\Windows\\Temp) when possible.
    """
    ps = (
        f"Get-ChildItem -Path '{search_path}' -Recurse -File -ErrorAction SilentlyContinue | "
        f"Sort-Object Length -Descending | Select-Object -First {top_n} "
        f"FullName, @{{N='SizeMB';E={{[math]::Round($_.Length/1MB,1)}}}} | Format-Table -AutoSize"
    )
    output = _run_adhoc_windows(target_host, ps, timeout=180)
    if not output.strip():
        return f"{target_host}: no files found under {search_path} (or command failed)."
    return f"{target_host} largest files under {search_path}:\n{output}"


# --- Temp file cleanup -----------------------------------------------------

@tool("clean_temp_files_windows")
def clean_temp_files_windows(target_host: str, older_than_days: int = 7) -> str:
    """
    Deletes files older than older_than_days from the system temp
    directory (C:\\Windows\\Temp) and the current user's temp
    directory. Does not touch anything outside those locations.
    """
    ps = (
        f"$cutoff = (Get-Date).AddDays(-{older_than_days}); "
        f"$paths = @('C:\\Windows\\Temp', $env:TEMP); "
        f"$removed = 0; "
        f"foreach ($p in $paths) {{ "
        f"Get-ChildItem -Path $p -Recurse -File -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.LastWriteTime -lt $cutoff }} | "
        f"ForEach-Object {{ Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue; $removed++ }} "
        f"}}; Write-Output \"Removed $removed file(s)\""
    )
    output = _run_adhoc_windows(target_host, ps, timeout=180)
    if not output.strip():
        return f"{target_host}: cleanup ran but produced no output."
    return f"{target_host}: {output}"


# --- Event log management (Windows equivalent of log rotation) ------------

@tool("check_event_log_size_windows")
def check_event_log_size_windows(target_host: str, log_name: str = "Application") -> str:
    """
    Reports the current size and max size of a Windows Event Log
    (e.g. Application, System, Security). Read-only - Windows has no
    logrotate; this is the closest equivalent check before deciding
    whether clear_event_log_windows is warranted.
    """
    ps = (
        f"Get-WinEvent -ListLog '{log_name}' | "
        f"Select-Object LogName, @{{N='SizeMB';E={{[math]::Round($_.FileSize/1MB,1)}}}}, "
        f"@{{N='MaxSizeMB';E={{[math]::Round($_.MaximumSizeInBytes/1MB,1)}}}}, RecordCount | Format-List"
    )
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip():
        return f"{target_host}: could not read event log '{log_name}' (check the log name is valid)."
    return f"{target_host} event log '{log_name}':\n{output}"


@tool("clear_event_log_windows")
def clear_event_log_windows(target_host: str, log_name: str = "Application") -> str:
    """
    Clears a Windows Event Log. This is a destructive action on that
    log's history - call check_event_log_size_windows first to confirm
    it's actually full/warranted, and again after to verify it cleared.
    """
    ps = f"Clear-EventLog -LogName '{log_name}'; Write-Output 'Cleared {log_name}'"
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip():
        return f"{target_host}: clear command ran but produced no confirmation output."
    return f"{target_host}: {output}"


# --- Unresponsive processes (closest Windows equivalent to zombies) -------

@tool("find_unresponsive_processes_windows")
def find_unresponsive_processes_windows(target_host: str) -> str:
    """
    Reports processes currently marked "Not Responding" by Windows.
    This is the closest practical equivalent to a Unix zombie process -
    Windows does not have the same parent/child defunct-process concept,
    so this instead reports hung GUI processes. Read-only - call both
    before AND after stop_process_windows to confirm a fix took effect.
    """
    ps = (
        "Get-Process | Where-Object { $_.Responding -eq $false } | "
        "Select-Object Id, ProcessName | Format-Table -AutoSize"
    )
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip():
        return f"{target_host}: no unresponsive processes found."
    return f"{target_host} unresponsive processes:\n{output}"


@tool("stop_process_windows")
def stop_process_windows(target_host: str, process_id: int) -> str:
    """
    Force-stops a specific process by PID. Use find_unresponsive_processes_windows
    first to get the PID of the process actually causing the problem -
    never guess a PID. Call find_unresponsive_processes_windows again
    afterward to confirm it's actually gone.
    """
    ps = f"Stop-Process -Id {process_id} -Force -ErrorAction Stop; Write-Output 'Stopped PID {process_id}'"
    output = _run_adhoc_windows(target_host, ps)
    if not output.strip():
        return f"{target_host}: stop command for PID {process_id} produced no confirmation - may have failed silently."
    return f"{target_host}: {output}"


# --- Patching ----------------------------------------------------------

@tool("check_pending_updates_windows")
def check_pending_updates_windows(target_host: str) -> str:
    """
    Reports how many Windows Updates are pending. Read-only - call
    before patch_os_windows to see what's outstanding, and after to
    confirm the patch run actually applied them.

    UNCONFIRMED: requires the PSWindowsUpdate PowerShell module already
    installed on the target host. If it's not installed, this will
    fail - test manually against one host before trusting this tool.
    """
    ps = (
        "Import-Module PSWindowsUpdate -ErrorAction Stop; "
        "(Get-WindowsUpdate).Count"
    )
    output = _run_adhoc_windows(target_host, ps, timeout=180)
    if not output.strip():
        return f"{target_host}: could not check pending updates (PSWindowsUpdate module may not be installed)."
    return f"{target_host}: {output.strip()} update(s) pending."


@tool("patch_os_windows")
def patch_os_windows(target_host: str) -> str:
    """
    Installs available Windows Updates. This is a real system-changing
    operation and may require a reboot to fully take effect - this
    tool does NOT reboot the host automatically. Call
    check_pending_updates_windows afterward to confirm updates applied.

    UNCONFIRMED: requires the PSWindowsUpdate PowerShell module already
    installed on the target host - test manually before trusting this.
    """
    ps = (
        "Import-Module PSWindowsUpdate -ErrorAction Stop; "
        "Install-WindowsUpdate -AcceptAll -IgnoreReboot -Confirm:$false"
    )
    output = _run_adhoc_windows(target_host, ps, timeout=1800)
    if not output.strip():
        return f"{target_host}: patch run produced no output (may have failed - check PSWindowsUpdate module is installed)."
    return f"{target_host} patch run output:\n{output}"


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
        check_pending_updates_windows,
        patch_os_windows,
    ]