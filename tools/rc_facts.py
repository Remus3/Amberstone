"""rc_facts.py — print live ground truth for the RC stack.

Designed to be invoked as a Claude Code SessionStart hook on Legion.
Output (markdown to stdout) is injected as additional context, so the
session starts with current state instead of relying on possibly-stale
memory entries.

Probes (all should complete within ~3s total):
  - Legion: health.json (pid, alive, mode, rc_version), listener ports
    8888/8889, RC scheduled tasks state, last boot.
  - Game-PC: /api/state's lcu block freshness (proves the LCU agent is
    posting), /api/health for vision server alive, plus a quick curl to
    192.168.8.237:8892/health (MCP listener) — flags any silently-down
    component.
  - Anomaly summary: anything unexpected, listed first.

Cheap and idempotent. Caller (the hook) gets stdout; non-zero exit just
means "couldn't probe" and is non-blocking.

Run manually any time:  py tools/rc_facts.py
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
_HEALTH = _APP / "ops" / "runtime" / "health.json"
_LEGION_BASE = "https://legion-rc:8888"
_GAMEPC_MCP_HEALTH = "http://gamepc-rc:8892/health"
_GAMEPC_TOKEN = "8e8f131e212b329438218eca27372dde"
_TIMEOUT = 2.5

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


def _http_get_json(url: str, headers: dict | None = None) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _http_get_status(url: str, headers: dict | None = None) -> int | None:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def _port_listening(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _legion_tasks() -> list[dict]:
    """Return [{name, state, last_result}, ...] for RC-* tasks via PowerShell."""
    cmd = (
        "Get-ScheduledTask | Where-Object TaskName -like 'RC-*' | "
        "ForEach-Object { $i = Get-ScheduledTaskInfo $_; "
        "@{ name = $_.TaskName; state = [string]$_.State; "
        "last_result = $i.LastTaskResult } } | ConvertTo-Json -Compress"
    )
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=4.0, text=True,
            encoding="utf-8", errors="replace",
        )
        if p.returncode != 0 or not p.stdout.strip():
            return []
        data = json.loads(p.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []


def _last_boot_iso() -> str | None:
    cmd = "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')"
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=2.0, text=True,
            encoding="utf-8", errors="replace",
        )
        if p.returncode == 0:
            return p.stdout.strip() or None
    except Exception:
        pass
    return None


def main() -> int:
    out = []
    out.append("# RC live state (rc_facts.py)\n")
    out.append(f"_probed at {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")

    anomalies: list[str] = []

    # ── Legion ──────────────────────────────────────────────────────────
    out.append("## Legion (legion-rc · 100.70.22.55 · 192.168.8.230)\n")
    health = {}
    try:
        health = json.loads(_HEALTH.read_text(encoding="utf-8"))
    except Exception:
        anomalies.append("Legion: ops/runtime/health.json unreadable")
    pid = health.get("pid")
    alive = bool(health.get("alive"))
    mode = health.get("mode") or "?"
    rc_version = health.get("rc_version") or "?"
    last_reload_ok = health.get("last_reload_ok")
    out.append(
        f"- RC: pid={pid} alive={alive} mode={mode} version={rc_version} "
        f"last_reload_ok={last_reload_ok}"
    )
    if not alive:
        anomalies.append(f"Legion: RC not alive (pid={pid})")
    if last_reload_ok is False:
        anomalies.append("Legion: last RC reload failed")

    # Listener ports
    p_dash = _port_listening(8888)
    p_vis = _port_listening(8889)
    out.append(f"- Listeners: :8888 dashboard={p_dash}  :8889 vision={p_vis}")
    if not p_dash:
        anomalies.append("Legion: dashboard :8888 not listening")
    if not p_vis:
        anomalies.append("Legion: vision server :8889 not listening")

    # Scheduled tasks
    tasks = _legion_tasks()
    if tasks:
        running = [t for t in tasks if str(t.get("state")) in ("Running", "4", "Ready")]
        out.append(f"- Scheduled tasks ({len(tasks)} RC-*):")
        for t in tasks:
            n = t.get("name")
            s = t.get("state")
            r = t.get("last_result")
            mark = "" if r in (0, 267009, 267011) else f"  ⚠ result={r}"
            out.append(f"  - {n}: state={s}{mark}")
            if r not in (0, 267009, 267011, None):
                anomalies.append(
                    f"Legion: scheduled task {n} last_result={r} (probably failing)"
                )

    # Last boot
    lb = _last_boot_iso()
    if lb:
        out.append(f"- Last boot: {lb}")

    # ── Game-PC ─────────────────────────────────────────────────────────
    out.append("\n## Game-PC (gamepc-rc · 100.95.66.128 · 192.168.8.237)\n")

    # LCU agent freshness via Legion's /api/state
    state = _http_get_json(f"{_LEGION_BASE}/api/state") or {}
    lcu = (state or {}).get("lcu") or {}
    lcu_ts = float(lcu.get("ts") or 0)
    lcu_age = int(time.time() - lcu_ts) if lcu_ts else None
    lcu_phase = lcu.get("phase") or "?"
    if lcu_age is not None:
        out.append(f"- LCU agent: phase={lcu_phase} age={lcu_age}s")
        if lcu_age > 30:
            anomalies.append(f"Game-PC: LCU agent stale ({lcu_age}s old)")
    else:
        out.append("- LCU agent: NO RECENT POST")
        anomalies.append("Game-PC: LCU agent not posting")

    # Liveclient block from /api/state
    lc = state.get("liveclient") or {}
    lc_ts = float(lc.get("ts") or 0) if isinstance(lc, dict) else 0
    if lc_ts:
        lc_age = int(time.time() - lc_ts)
        out.append(f"- Liveclient relay: age={lc_age}s")
    else:
        out.append("- Liveclient relay: empty (no game in progress)")

    # MCP server
    mcp_status = _http_get_status(
        _GAMEPC_MCP_HEALTH, headers={"Authorization": f"Bearer {_GAMEPC_TOKEN}"}
    )
    out.append(f"- MCP server :8892: HTTP {mcp_status}")
    if mcp_status != 200:
        anomalies.append(f"Game-PC: MCP /health returned {mcp_status}")

    # ── Bridge auto-flow loop liveness (best-effort) ────────────────────
    out.append("\n## Cross-Claude bridge\n")
    bridge_log = _APP / "ops" / "runtime" / "bridge_log.jsonl"
    if bridge_log.exists():
        last_result_age = None
        try:
            for line in reversed(bridge_log.read_text(encoding="utf-8").splitlines()[-50:]):
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if j.get("kind") == "result" and j.get("source") == "gamepc":
                    last_result_age = int(time.time() - float(j.get("ts") or 0))
                    break
        except Exception:
            pass
        if last_result_age is not None:
            out.append(f"- Last gamepc bridge result: {last_result_age}s ago")
            if last_result_age > 3600:
                anomalies.append(
                    f"Bridge: last gamepc result {last_result_age}s ago — auto-flow loop may be dead"
                )
        else:
            out.append("- No recent gamepc bridge results in tail")

    # ── Anomaly summary first if any ────────────────────────────────────
    if anomalies:
        head = "## ⚠ Anomalies\n\n" + "\n".join(f"- {a}" for a in anomalies) + "\n\n"
        sys.stdout.write(head)
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
