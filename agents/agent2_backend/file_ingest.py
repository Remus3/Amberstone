"""File-watcher ingest - bridges the existing RC coaching JSON files
into the Phase 3 /push WebSocket stream. (Originally the stopgap while
the 2-PC Game-PC Forwarder was deferred per S12; that pre-1PC topology
is retired - this Legion-local file watcher is now the steady-state
path, ADR-011.)

The supervisor owns one ``FileIngest`` instance. It polls a small set of
known files every ``POLL_SEC`` seconds; when a file's version changes it reads,
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

Failure modes: missing file = skipped silently; bad, hostile or oversize
JSON = logged at WARNING ONCE per file version (DEBUG on the retries) and
retried every tick; file unchanged = no broadcast (noise-free). A version
is (st_mtime_ns, st_size), so a same-mtime rewrite of a new size still
counts as a change. A version is marked delivered only after the broadcast
returns, so a fanout that raises is retried next tick instead of lost. One
source failing never stops the others: each is checked in its own guard.
NaN / Infinity / -Infinity and overflowing floats (1e999) become null,
because the dashboard's JSON.parse rejects the bare tokens json.dumps
would re-emit and would drop the whole envelope. The read is capped at
MAX_PAYLOAD_BYTES even if the file grew after the stat; a UTF-8 BOM is
accepted.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
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
        apply_standalone_tft_mirror as _apply_standalone_tft_mirror,
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


def _stat_blocking(path: Path) -> os.stat_result:
    """``path.stat()``; _check_one runs it in the default executor, never on the loop."""
    return path.stat()


class PayloadTooLarge(Exception):
    """The file holds more than MAX_PAYLOAD_BYTES at read time."""


def _read_text_blocking(path: Path) -> str:
    """UTF-8 (BOM tolerated) read of ``path``, at most MAX_PAYLOAD_BYTES.

    _check_one runs it in the default executor, never on the loop. The stat
    size cap alone is a check-then-use race: a file that grows after the stat
    would otherwise be read whole, so the read itself is bounded and raises
    PayloadTooLarge past the cap.
    """
    with path.open("rb") as fh:
        raw = fh.read(MAX_PAYLOAD_BYTES + 1)
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise PayloadTooLarge(f"more than {MAX_PAYLOAD_BYTES} bytes at read time")
    return raw.decode("utf-8-sig")


def _null_constant(_token: str) -> None:
    """json parse_constant: NaN / Infinity / -Infinity are not JSON; read as null."""
    return None


def _finite_float(text: str) -> float | None:
    """json parse_float: a literal that overflows to +-inf (1e999) reads as null."""
    value = float(text)
    return value if math.isfinite(value) else None


def _parse_json(text: str) -> Any:
    """Strict-JSON-safe parse: the result always re-serialises with allow_nan=False."""
    return json.loads(text, parse_constant=_null_constant, parse_float=_finite_float)


# What a malformed or hostile payload can raise from read + parse. JSONDecodeError
# and the int-digit limit are ValueErrors; deep nesting is a RecursionError.
_PARSE_ERRORS = (ValueError, RecursionError, OSError, PayloadTooLarge)


class FileIngest:
    def __init__(self, ws_server, on_mode_transition=None) -> None:
        """``on_mode_transition(prev, new)`` is called when
        ``health.json.mode`` changes - supervisor wires this to the
        warm Agent 7 session (charter: "warm starts when game begins").
        """
        self._ws = ws_server
        # source -> (st_mtime_ns, st_size) of the version last DELIVERED.
        self._versions: dict[str, tuple[int, int]] = {}
        # source -> key of the failure last logged at WARNING (log once
        # per file version / error, DEBUG on the 0.5 s retries).
        self._warned: dict[str, object] = {}
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
            except Exception:
                logger.exception("file_ingest tick raised")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_SEC)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        # Health first - panels need current mode before anything else.
        # Each source in its own guard: one raising source must not starve
        # the rest of the tick (a health.json fault used to silence every
        # coaching file for as long as it lasted).
        sources = [(HEALTH_PATH, "health", "any", "health")]
        sources += [(path, label, mode, "state") for label, path, mode in WATCHED]
        for path, source, mode, envelope_type in sources:
            try:
                await self._check_one(path, source, mode=mode,
                                      envelope_type=envelope_type)
            except Exception as e:  # noqa: BLE001 - isolate one source's fault
                self._warn_once(source, ("check", type(e), str(e)),
                                "check %s raised: %r", source, e,
                                exc_info=True)

    def _warn_once(self, source: str, key: object, msg: str, *args: Any,
                   exc_info: bool = False) -> None:
        """WARNING the first time ``key`` is seen for ``source``, DEBUG after."""
        if self._warned.get(source) == key:
            logger.debug(msg, *args)
            return
        self._warned[source] = key
        logger.warning(msg, *args, exc_info=exc_info)

    async def _check_one(self, path: Path, source: str, *,
                         mode: str, envelope_type: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            st = await loop.run_in_executor(None, _stat_blocking, path)
        except FileNotFoundError:
            return
        except OSError as e:
            logger.debug("stat %s: %s", path, e)
            return
        version = (st.st_mtime_ns, st.st_size)
        if st.st_size > MAX_PAYLOAD_BYTES:
            self._warn_once(source, ("size", version),
                            "skip %s: size %d > cap %d",
                            source, st.st_size, MAX_PAYLOAD_BYTES)
            return
        if self._versions.get(source) == version:
            return    # no change
        mtime = st.st_mtime

        try:
            data = _parse_json(
                await loop.run_in_executor(None, _read_text_blocking, path))
        except _PARSE_ERRORS as e:
            self._warn_once(source, ("parse", version),
                            "parse %s: %s: %s", source, type(e).__name__, e)
            return

        # s157: mirror the LCU lobby/CS pre-flip into health envelopes so
        # the dashboard's onHealth tag resolution agrees with onState. Run
        # the (sync, sub-100ms-local) HTTP fetch in the default executor so
        # we don't block the supervisor's event loop.
        lcu_snapshot: dict | None = None
        if (envelope_type == "health"
                and _PREFLIP_AVAILABLE
                and isinstance(data, dict)):
            try:
                lcu_snapshot = await loop.run_in_executor(None, _lcu_summary)
                # S134 P0: same standalone-TFT mirror as /api/state, so the
                # WS health envelope agrees with onState during the match.
                # Executor, not the loop: in game it may walk the process
                # table (cached, tens of ms).
                data = await loop.run_in_executor(
                    None, _apply_standalone_tft_mirror, data, lcu_snapshot)
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
        # The version is recorded only once the fanout returns: recording it
        # first (the old order) turned one raising fanout into a lost update,
        # since the file then read as unchanged on every later tick.
        try:
            await self._ws.broadcast_push(envelope)
        except Exception as e:  # noqa: BLE001 - retried next tick
            delivered = False
            self._warn_once(source, ("push", version, type(e)),
                            "push %s failed, retrying: %r", source, e,
                            exc_info=True)
        else:
            delivered = True

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

        if delivered:
            self._versions[source] = version
            self._warned.pop(source, None)

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

        Only a str mode counts: str() of a bool / number / container
        (mode=True read as "true") would fire a bogus mode transition. A
        non-str phase already matches no branch (== / tuple membership).
        """
        raw_mode = health.get("mode")
        health_mode = (raw_mode.lower() or None) if isinstance(raw_mode, str) else None
        if health_mode in ("game", "in_progress"):
            return health_mode
        if lcu_phase == "ChampSelect":
            return "champ_select"
        if lcu_phase in ("GameStart", "InProgress"):
            return "game"
        return health_mode
