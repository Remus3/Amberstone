"""GET/POST /api/bridge/cadence — bridge-watcher polling-mode sentinel.

The watcher reads ops/runtime/bridge_watcher_mode.json each poll cycle to
decide its next sleep interval:
  active  → _DEFAULT_POLL_S (15s)
  sleep   → _SLEEP_POLL_S   (300s)
  auto    → 15s while tasks arrive; drops to 300s after 15 min idle

GET  /api/bridge/cadence     — return current sentinel (or default if absent)
POST /api/bridge/cadence     — body {"mode": "active"|"sleep"|"auto"}
                               writes sentinel atomically; watcher picks it
                               up on its next poll cycle

Only ships on Legion (the node with a dashboard). Game-PC/Peer stay in
active mode until cross-node cadence control is added later.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from dashboard._dispatch import equals

log = logging.getLogger("rc.routes_bridge_cadence")

_APP_DIR   = Path(__file__).parent.parent
_MODE_PATH = _APP_DIR / "ops" / "runtime" / "bridge_watcher_mode.json"
_VALID_MODES = frozenset({"active", "sleep", "auto"})


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    last_exc: Exception | None = None
    for delay in (0, 0.025, 0.050, 0.200):
        if delay:
            time.sleep(delay)
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_exc = exc
    if last_exc:
        raise last_exc


def _serve_get(h) -> None:
    if not _MODE_PATH.exists():
        h._send(200,
                json.dumps({"mode": "active", "source": "default",
                            "note": "no sentinel file; watcher defaults to active"}).encode(),
                "application/json")
        return
    try:
        data = json.loads(_MODE_PATH.read_text(encoding="utf-8"))
        h._send(200, json.dumps(data).encode(), "application/json")
    except (OSError, json.JSONDecodeError) as exc:
        h._send(500,
                json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_post(h, body) -> None:
    mode = str(body.get("mode", "")).strip().lower()
    if mode not in _VALID_MODES:
        h._send(400,
                json.dumps({"error": "invalid mode",
                            "valid": sorted(_VALID_MODES)}).encode(),
                "application/json")
        return
    payload = {"mode": mode, "since": time.time(), "set_by": "api"}
    try:
        _atomic_write(_MODE_PATH, payload)
    except OSError as exc:
        log.warning("cadence write failed: %s", exc)
        h._send(500,
                json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")
        return
    log.info("cadence set mode=%s", mode)
    h._send(200,
            json.dumps({"ok": True, "mode": mode,
                        "note": "watcher picks up change on next poll cycle"}).encode(),
            "application/json")


GET_ROUTES  = [(equals("/api/bridge/cadence"), _serve_get)]
POST_ROUTES = [(equals("/api/bridge/cadence"), _serve_post)]
