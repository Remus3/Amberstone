"""File-watcher ingest — bridges the existing RC coaching JSON files
into the Phase 3 /push WebSocket stream while the Game-PC Forwarder is
still deferred (§12 of the spec).

The supervisor owns one ``FileIngest`` instance. It polls a small set of
known files every ``POLL_SEC`` seconds; when an mtime advances it reads,
parses, and calls ``WSServer.broadcast_push({...})``.

Broadcast envelope::

    {
      "type": "state",
      "source": "aram_coaching_data.json",
      "mtime": 1776861234.567,
      "mode": "aram",            # derived from the filename
      "payload": { ...parsed JSON... }
    }

Health snapshots are distinct::

    {"type": "health", "mtime": ..., "payload": { ...health.json... }}

Failure modes: missing file = skipped silently; bad JSON = logged at
WARNING + skipped that tick; file unchanged = no broadcast (noise-free).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent2.file_ingest")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# (source-label, path, mode-tag) tuples. The mode-tag is what the UI
# checks to decide which panel to populate.
WATCHED: tuple[tuple[str, Path, str], ...] = (
    ("coaching_data.json",        _PROJECT_ROOT / "coaching_data.json",             "sr"),
    ("aram_coaching_data.json",   _PROJECT_ROOT / "data" / "aram_coaching_data.json",   "aram"),
    ("arena_coaching_data.json",  _PROJECT_ROOT / "data" / "arena_coaching_data.json",  "arena"),
    ("brawl_coaching_data.json",  _PROJECT_ROOT / "data" / "brawl_coaching_data.json",  "brawl"),
    ("tft_coaching_data.json",    _PROJECT_ROOT / "data" / "tft_coaching_data.json",    "tft"),
    ("tft_live_data.json",        _PROJECT_ROOT / "data" / "tft_live_data.json",        "tft"),
    ("comp_state.json",           _PROJECT_ROOT / "data" / "comp_state.json",           "any"),
)
HEALTH_PATH = _PROJECT_ROOT / "ops" / "runtime" / "health.json"

POLL_SEC = 0.5          # matches the existing :8888 dashboard cadence
MAX_PAYLOAD_BYTES = 128 * 1024   # sanity cap — coaching JSON ≈ 1-2 KB


class FileIngest:
    def __init__(self, ws_server, on_mode_transition=None) -> None:
        """``on_mode_transition(prev, new)`` is called when
        ``health.json.mode`` changes — supervisor wires this to the
        warm Agent 7 session (charter: "warm starts when game begins").
        """
        self._ws = ws_server
        self._mtimes: dict[str, float] = {}
        self._last_mode: str | None = None
        self._on_mode_transition = on_mode_transition
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="file-ingest")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as e:           # noqa: BLE001
                logger.exception("file_ingest tick raised: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_SEC)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        # Health first — panels need current mode before anything else.
        await self._check_one(HEALTH_PATH, "health", mode="any",
                              envelope_type="health")
        for label, path, mode in WATCHED:
            await self._check_one(path, label, mode=mode,
                                  envelope_type="state")

    async def _check_one(self, path: Path, source: str, *,
                         mode: str, envelope_type: str) -> None:
        try:
            st = path.stat()
        except FileNotFoundError:
            return
        except OSError as e:
            logger.debug("stat %s: %s", path, e)
            return
        if st.st_size > MAX_PAYLOAD_BYTES:
            logger.warning("skip %s: size %d > cap %d",
                           source, st.st_size, MAX_PAYLOAD_BYTES)
            return
        mtime = st.st_mtime
        prev = self._mtimes.get(source)
        if prev is not None and mtime == prev:
            return    # no change

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning("parse %s: %s", source, e)
            return
        self._mtimes[source] = mtime

        envelope: dict[str, Any] = {
            "type": envelope_type,
            "source": source,
            "mtime": mtime,
            "mode": mode,
            "payload": data,
        }
        await self._ws.broadcast_push(envelope)

        # Game-start trigger (charter): health.json.mode transition
        # client → game/in_progress fires the mode-transition hook.
        if envelope_type == "health" and isinstance(data, dict):
            new_mode = str(data.get("mode") or "").lower() or None
            prev_mode = self._last_mode
            if new_mode != prev_mode:
                self._last_mode = new_mode
                if self._on_mode_transition is not None and prev_mode is not None:
                    try:
                        self._on_mode_transition(prev_mode, new_mode)
                    except Exception as e:               # noqa: BLE001
                        logger.warning("on_mode_transition raised: %s", e)
