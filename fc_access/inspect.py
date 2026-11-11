"""Inspect access mechanisms without exposing process commands or browser profiles."""
import json
import os
from pathlib import Path
import subprocess
import urllib.request

from .schema import utc_now

ROOT = Path(__file__).resolve().parents[1]
INSPECTION = ROOT / "docs/research/browser-access/inspection.json"
PROCESS_SCRIPT = r"""
$edge = @(Get-CimInstance Win32_Process -Filter "name = 'msedge.exe'" -ErrorAction Stop)
$ports = @($edge | ForEach-Object { if ($_.CommandLine -match '--remote-debugging-port(?:=|\s+)(\d+)') { [int]$Matches[1] } } | Sort-Object -Unique)
$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {$_.OwningProcess -in $edge.ProcessId} | ForEach-Object { @{address=$_.LocalAddress;port=$_.LocalPort} })
@{edge_process_count=$edge.Count;unreadable_command_lines=@($edge | Where-Object {-not $_.CommandLine}).Count;debug_ports=$ports;debug_pipe_process_count=@($edge | Where-Object {$_.CommandLine -match '--remote-debugging-pipe'}).Count;edge_listeners=$listeners} | ConvertTo-Json -Depth 4 -Compress
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def inspect():
    result = {"task": "task_02", "inspected_at": utc_now().isoformat()}
    try:
        process = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PROCESS_SCRIPT],
                                 capture_output=True, timeout=30, check=True)
        result["edge_processes"] = json.loads(process.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        result["edge_processes"] = {"inspection_error": "process_inventory_unavailable"}
    profile_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/User Data"
    markers = list(profile_root.glob("DevToolsActivePort")) + list(profile_root.glob("*/DevToolsActivePort"))
    ports = {9222, 9223}
    ports.update(p for p in result["edge_processes"].get("debug_ports", []) if type(p) is int and 0 < p < 65536)
    for marker in markers:
        try:
            port = int(marker.read_text().splitlines()[0])
            if 0 < port < 65536:
                ports.add(port)
        except (OSError, ValueError, IndexError):
            pass
    result["devtools_active_port_markers"] = len(markers)
    result["cdp_probes"] = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for port in sorted(ports):
        available = False
        try:
            with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                raw = json.loads(response.read(65536))
                # Never retain debugger websocket URLs (they contain browser identifiers).
                available = isinstance(raw.get("webSocketDebuggerUrl"), str) and raw["webSocketDebuggerUrl"].startswith(
                    (f"ws://127.0.0.1:{port}/", f"ws://localhost:{port}/"))
        except (OSError, ValueError):
            pass
        result["cdp_probes"].append({"address": "127.0.0.1", "port": port, "available": available})
    manifests = debugger = loopback = unreadable = 0
    for path in profile_root.glob("*/Extensions/*/*/manifest.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            permissions = data.get("permissions", []) + data.get("optional_permissions", [])
            hosts = data.get("host_permissions", []) + data.get("optional_host_permissions", []) + permissions
            manifests += 1
            debugger += "debugger" in permissions
            loopback += any(isinstance(h, str) and ("localhost" in h or "127.0.0.1" in h) for h in hosts)
        except (OSError, ValueError, TypeError):
            unreadable += 1
    result["extension_permissions"] = {"manifests": manifests, "debugger_candidates": debugger,
                                       "loopback_candidates": loopback, "unreadable": unreadable}
    result["limits"] = "Only default Edge user-data root, process debugging flags, owned listeners, and manifest permissions inspected. Custom profile paths, UI state, and enterprise policies unverified. No credentials read."
    return result


if __name__ == "__main__":
    record = inspect()
    INSPECTION.parent.mkdir(parents=True, exist_ok=True)
    INSPECTION.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))
