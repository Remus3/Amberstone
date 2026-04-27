"""
core/moon_sync.py — DEPRECATED (2026-04-22).

Moon-PC was decommissioned 2026-04-19 per CLAUDE.md §Topology. This
module's MOON_PC_BRIDGE target was patched to 127.0.0.1 at migration
time but the sync logic still assumes Moon-PC is a separate peer and
no live code imports this module (grep confirms zero callers). Retained
in-tree so historical git blame stays useful; safe to delete in a
future cleanup pass.

Do NOT import this module. For cross-machine writes, use
``agents.agent2_backend.smb_push.push()`` instead (Phase 3 replacement).

----------------------------------------------------------------------
Original docstring below this line for historical reference.
----------------------------------------------------------------------
core/moon_sync.py — Bidirectional low-latency file sync between Game-PC and Moon-PC.

Game-PC pushes: coaching data, comp state, restart triggers → Moon-PC
Moon-PC pushes: vision results, OCR results → Game-PC (via existing lan_bridge on 8888)

The sync folder is C:\\Riot Commander\\data\\moon_sync\\
Files written here are polled and forwarded every 500ms.
"""
import json
import logging
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

log = logging.getLogger("rc.moon_sync")

GAME_PC_BRIDGE = "http://192.168.8.237:8888"   # existing lan_bridge.py
MOON_PC_BRIDGE = "http://127.0.0.1:8889"        # vision server (local on Legion since 2026-04-19)

SYNC_DIR   = Path(r"C:\Riot Commander\data\moon_sync")
POLL_MS    = 500
TIMEOUT_S  = 4

# Files Game-PC pushes to Moon-PC on change
PUSH_TO_MOON = [
    "data/comp_state.json",
    "data/tft_coaching_data.json",
    "data/tft_live_data.json",
]


class MoonSync:
    """Bidirectional sync: push key files to Moon-PC, receive results back."""

    def __init__(self, root: Path):
        self._root     = root
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._mtimes: dict = {}
        SYNC_DIR.mkdir(parents=True, exist_ok=True)

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="MoonSync")
        self._thread.start()
        log.info("MoonSync started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._push_changed_files()
                self._poll_moon_inbox()
            except Exception as e:
                log.debug("MoonSync loop: %s", e)
            time.sleep(POLL_MS / 1000)

    def _push_changed_files(self):
        """Push files that changed since last push to Moon-PC /sync endpoint."""
        for rel in PUSH_TO_MOON:
            fp = self._root / rel
            if not fp.exists():
                continue
            mtime = fp.stat().st_mtime
            if self._mtimes.get(rel) == mtime:
                continue
            self._mtimes[rel] = mtime
            try:
                data = fp.read_bytes()
                req = urllib.request.Request(
                    f"{MOON_PC_BRIDGE}/sync/{rel}",
                    data=data,
                    method="PUT",
                    headers={"Content-Type": "application/octet-stream"},
                )
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                    if r.status == 200:
                        log.debug("Pushed %s to Moon-PC", rel)
            except Exception as e:
                log.debug("Push %s failed: %s", rel, e)

    def _poll_moon_inbox(self):
        """Check Moon-PC sync inbox for new files to pull back."""
        try:
            req = urllib.request.Request(f"{MOON_PC_BRIDGE}/sync/list")
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                files = json.loads(r.read().decode()).get("files", [])
            for fname in files:
                self._pull_from_moon(fname)
        except Exception:
            pass  # Moon-PC offline — silent

    def _pull_from_moon(self, fname: str):
        """Download a file from Moon-PC sync inbox to local data/moon_sync/."""
        try:
            req = urllib.request.Request(f"{MOON_PC_BRIDGE}/sync/get/{fname}")
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = r.read()
            out = SYNC_DIR / fname
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(out)
            log.debug("Pulled %s from Moon-PC", fname)
        except Exception as e:
            log.debug("Pull %s failed: %s", fname, e)


# Module-level instance
moon_sync: Optional[MoonSync] = None

def start_sync(root: Path):
    global moon_sync
    moon_sync = MoonSync(root)
    moon_sync.start()
    return moon_sync
