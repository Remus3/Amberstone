"""File-watcher ingest - bridges the existing RC coaching JSON files
into the Phase 3 /push WebSocket stream. (Originally the stopgap while
the 2-PC Game-PC Forwarder was deferred per S12; that pre-1PC topology
is retired - this Legion-local file watcher is now the steady-state
path, ADR-011.)

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

# 2026-05-10 (s157): mirror the s150 LCU lobby/CS pre-flip into the
# WS health envelope here too. ``dashboard/_state_builder.build_state``
# already does this for the HTTP /api/state route (s153), but the
# supervisor's WS /push path reads health.json directly and broadcasts
# the raw payload - bypassing the mirror. Result: dashboard onHealth
# saw aram_mode/arena_mode/tft_mode/has_game all False during lobby
# and computed tag="client" every cadence cycle, racing onState's
# in-game env.mode for the just-completed game ("sr"). Mode pill
# flapped CLIENT <-> SR; the last-match panels flickered between in-game
# and aftergame title sets.
try:
    from dashboard._liveclient import lcu_summary as _lcu_summary
    from dashboard._state_builder import (
        apply_preflip_mirror as _apply_preflip_mirror,
        resolve_mode_key as _resolve_mode_key,
    )
    _PREFLIP_AVAILABLE = True
except Exception as _imp_exc:  # noqa: BLE001
    # Tests / dev runs without the dashboard package - fall back to
    # raw passthrough rather than failing the supervisor's startup.
    logger.warning("preflip mirror unavailable: %s", _imp_exc)
    _PREFLIP_AVAILABLE = False

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
MAX_PAYLOAD_BYTES = 128 * 1024   # sanity cap - coaching JSON ~ 1-2 KB


class FileIngest:
    def __init__(self, ws_server, on_mode_transition=None) -> None:
        """``on_mode_transition(prev, new)`` is called when
        ``health.json.mode`` changes - supervisor wires this to the
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
        # Health first - panels need current mode before anything else.
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

        # s157: mirror the LCU lobby/CS pre-flip into health envelopes so
        # the dashboard's onHealth tag resolution agrees with onState. Run
        # the (sync, sub-100ms-local) HTTP fetch in the default executor so
        # we don't block the supervisor's event loop.
        lcu_snapshot: dict | None = None
        if (envelope_type == "health"
                and _PREFLIP_AVAILABLE
                and isinstance(data, dict)):
            try:
                loop = asyncio.get_running_loop()
                lcu_snapshot = await loop.run_in_executor(None, _lcu_summary)
                mode_key, preflip_active = _resolve_mode_key(data, lcu_snapshot)
                if preflip_active:
                    data = _apply_preflip_mirror(data, mode_key, preflip_active)
            except Exception as e:  # noqa: BLE001
                logger.debug("preflip mirror skipped: %s", e)

        envelope: dict[str, Any] = {
            "type": envelope_type,
            "source": source,
            "mtime": mtime,
            "mode": mode,
            "payload": data,
        }
        await self._ws.broadcast_push(envelope)

        # Game-start trigger (charter): health.json.mode transition
        # client -> game/in_progress fires the mode-transition hook.
        #
        # s171.8 (pre-1PC origin): in the retired 2-PC split the LCU
        # lockfile wasn't visible on Legion (it lived on Game-PC), so the
        # main RC wrote health.mode="client" through the entire
        # ChampSelect + GameStart window - the supervisor only saw the
        # transition once LiveClient finally fired (well into InProgress),
        # and Warm Agent 7 missed the early-game prime window. Post-1PC
        # (ADR-011) LCU is local so the lockfile is visible directly, but
        # the LCU-phase overlay is kept as a defensive fallback: it makes
        # the transition hook fire on ChampSelect / GameStart entries too,
        # mirroring what core/decision_detector + game_reader already do
        # via the relay-age fallback.
        if envelope_type == "health" and isinstance(data, dict):
            lcu_phase = None
            if isinstance(lcu_snapshot, dict):
                lcu_phase = lcu_snapshot.get("phase")
            new_mode = self._compute_effective_mode(data, lcu_phase)
            prev_mode = self._last_mode
            if new_mode != prev_mode:
                self._last_mode = new_mode
                if self._on_mode_transition is not None and prev_mode is not None:
                    try:
                        self._on_mode_transition(prev_mode, new_mode)
                    except Exception as e:               # noqa: BLE001
                        logger.warning("on_mode_transition raised: %s", e)

    @staticmethod
    def _compute_effective_mode(health: dict, lcu_phase: str | None) -> str | None:
        """Combine health.mode + LCU phase into an effective mode tag.

        Trust health.mode when it's already in-game (LiveClient is the
        authoritative signal). Otherwise overlay LCU phase so the
        supervisor's mode-transition hook fires for ChampSelect and
        GameStart even when health.mode is briefly stuck at "client".
        (Pre-1PC this gap came from Legion not seeing Game-PC's LCU
        lockfile; post-1PC ADR-011 LCU is local, so this overlay is now a
        defensive fallback rather than load-bearing.)
        """
        health_mode = str(health.get("mode") or "").lower() or None
        if health_mode in ("game", "in_progress"):
            return health_mode
        if lcu_phase == "ChampSelect":
            return "champ_select"
        if lcu_phase in ("GameStart", "InProgress"):
            return "game"
        return health_mode
