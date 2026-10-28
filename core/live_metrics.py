"""Shared live-metrics streaming gate + per-coach streamer dispatch.

RC live-metrics capture writes metric snapshots to data/match_metrics.db on
milestone boundaries (game_start / 10-15-20-25-30 min marks / L6-11-16 spikes
/ game_end) plus 60s periodic sampling, via core.metric_streamer.MetricStreamer.

Two enable switches, OR'd:
  1. env RC_LIVE_METRICS=1          - legacy contract; read once at import,
                                        so a change needs a supervisor restart.
  2. config/coach_settings.json
     "live_metrics_enabled": true   - re-read live on every tick, so a flip
                                        crosses processes with NO restart. This
                                        mirrors the spend-gate toggle mechanism
                                        in core.cost_tracker (same config file).
                                        Only JSON true enables it: a string
                                        "false", a 1 or a list stays OFF. A
                                        UTF-8 BOM is accepted; an unreadable,
                                        oversized or non-object file fails
                                        closed and warns once per streak.

Both default OFF, so the in-code default is byte-identical to no-capture; the
local coach_settings.json (gitignored) is where the operator flips it on.

Wire-in (coach side): after a coach writes coaching_data.json, call

    from core import live_metrics
    live_metrics.stream(self, cur, state, mode)

where `cur` is the just-written coaching_data dict (carries game_time_s /
level / champion) and `state` is the raw game-state dict (carries game_id).
The per-match streamer is stashed on the coach as `holder._streamer` and is
error-wrapped: it can never crash the coach (a failure is logged at WARNING
once per fault streak, then at DEBUG, and swallowed).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from pathlib import Path

logger = logging.getLogger("rc.live_metrics")

_APP_DIR = Path(__file__).resolve().parent.parent
_COACH_CFG = _APP_DIR / "config" / "coach_settings.json"
_CFG_KEY = "live_metrics_enabled"
# The file is re-read on every coach tick, so the read is bounded. The real
# file is well under 1 KiB.
_CFG_MAX_BYTES = 1 << 20
# Once-per-streak latch for a present-but-unusable config file; a good read
# (or the file going away) ends the streak.
_cfg_warned = False

# env switch read once at import (legacy contract).
_ENV_ENABLED = os.environ.get("RC_LIVE_METRICS", "0") == "1"

# Many live modes (ARAM among them) never surface a game_id - the Live Client
# /allgamedata payload rarely exposes it (see item 211). Without a match key
# the streamer cannot group a match, so we synthesise a per-match id from the
# coach holder + game clock: a new id is minted on the first tick and again
# whenever game_time_s drops by more than this many seconds (a new game reset).
_NEW_GAME_CLOCK_DROP_S = 30.0
# A clock outside 0..this is junk, not a game time (a day is far past any
# real game), and is treated exactly like a missing clock.
_MAX_CLOCK_S = 86400.0
_synthetic_seq = 0
# Coach ticks arrive from multiple worker threads; the seq increment is a
# read-modify-write, so two concurrent mints could otherwise share an id
# (merging two matches' metric rows under one synthetic match_id).
_seq_lock = threading.Lock()

# A Riot game id is a positive integer; the shape check also admits short
# alphanumeric ids (first char alphanumeric, so "-1" sentinels are refused)
# and bounds the length, because the id is embedded in every metric row.
_GAME_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_GAME_ID_MAX_INT = 10 ** 20
_CHAMP_MAX_LEN = 64

# Once-per-streak latch for stream() faults: the exception type name of the
# current streak, None when the last tick succeeded.
_stream_fault = None

# Lazy MetricStreamer import - only attempted when first needed, cached after.
_MetricStreamer = None
_import_attempted = False


def _resolve_streamer():
    """Import core.metric_streamer.MetricStreamer lazily; cache the result
    (including a failed import as None) so we attempt it at most once."""
    global _MetricStreamer, _import_attempted
    if _MetricStreamer is not None or _import_attempted:
        return _MetricStreamer
    _import_attempted = True
    try:
        from core.metric_streamer import MetricStreamer
        _MetricStreamer = MetricStreamer
    except Exception as exc:  # pragma: no cover - import-environment specific  # noqa: BLE001
        logger.warning("live-metrics import failed: %s", exc)
        _MetricStreamer = None
    return _MetricStreamer


def _config_enabled() -> bool:
    """True only if config/coach_settings.json sets live_metrics_enabled to
    JSON true. Re-read on every call (tiny file, bounded read) so a flip takes
    effect without restart. An absent file is the quiet default (OFF); a
    present file that cannot be read, is oversized, is not a JSON object or
    does not parse fails closed and warns once per streak, naming the file
    kind and the error type only."""
    global _cfg_warned
    try:
        if not _COACH_CFG.is_file():
            _cfg_warned = False
            return False
        with _COACH_CFG.open("rb") as fh:
            raw = fh.read(_CFG_MAX_BYTES + 1)
        if len(raw) > _CFG_MAX_BYTES:
            raise ValueError("file over the size cap")
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
    except (OSError, ValueError, RecursionError) as exc:
        if not _cfg_warned:
            _cfg_warned = True
            logger.warning(
                "live-metrics: coach_settings.json unusable (%s); capture "
                "stays off until it reads cleanly", type(exc).__name__)
        return False
    _cfg_warned = False
    return data.get(_CFG_KEY) is True


def enabled() -> bool:
    """True when either the env switch (import-time) or the config switch
    (live) is on."""
    return _ENV_ENABLED or _config_enabled()


def _clock_s(cur: dict, state: dict):
    """The tick's game clock in seconds, or None when no field carries one.

    Same precedence as the historical ``a or b or c`` chain: the first
    non-zero clock among cur.game_time_s, state.game_time_s and
    state.game_seconds wins, and 0.0 comes back only when a field really
    read 0. A bool, non-number, non-finite, negative or absurd value is
    skipped like a missing field, so one junk tick can never pose as a
    clock reset."""
    seen_zero = False
    for raw in (cur.get("game_time_s"), state.get("game_time_s"),
                state.get("game_seconds")):
        if raw is None or isinstance(raw, bool):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(val) or val < 0.0 or val > _MAX_CLOCK_S:
            continue
        if val == 0.0:
            seen_zero = True
            continue
        return val
    return 0.0 if seen_zero else None


def _coerce_game_id(raw) -> str:
    """A usable game id as text, or "" when the value is absent or junk
    (bool, float, container, zero, negative, sentinel, oversized)."""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        return str(raw) if 0 < raw < _GAME_ID_MAX_INT else ""
    if not isinstance(raw, str):
        return ""
    gid = raw.strip()
    if not _GAME_ID_RE.fullmatch(gid):
        return ""
    if gid.isdigit() and int(gid) == 0:
        return ""
    return gid


def _real_game_id(state: dict) -> str:
    for raw in (state.get("game_id"), state.get("gameId")):
        gid = _coerce_game_id(raw)
        if gid:
            return gid
    return ""


def _champ_token(cur: dict, state: dict) -> str:
    """The champion name for a synthetic session id: a short printable
    ASCII string from cur, else from state, else "champ"."""
    for raw in (cur.get("champion"), state.get("champion")):
        if isinstance(raw, str):
            name = raw.strip()
            if (name and len(name) <= _CHAMP_MAX_LEN and name.isascii()
                    and name.isprintable()):
                return name
    return "champ"


def _resolve_match_id(holder, cur: dict, state: dict, mode: str) -> str:
    """Return a stable per-match id. Prefer a real game_id; otherwise mint a
    synthetic per-match session stamped on the holder, refreshed whenever the
    game clock resets (a new game). Tracks the last game clock on the holder
    so the existing-streamer comparison in stream() recreates on a new game.

    A tick with no readable clock never resets anything and does not move the
    tracked clock. A tick whose game_id is transiently empty (the snapshot
    drops it when its tick budget is spent) keeps the last real id until the
    clock resets, so one match never flips between a live_ and a sess_ key."""
    gt = _clock_s(cur, state)
    last_gt = getattr(holder, "_lm_last_gt", None)
    reset = (gt is not None and last_gt is not None
             and gt + _NEW_GAME_CLOCK_DROP_S < last_gt)

    game_id = _real_game_id(state)
    if game_id:
        holder._lm_session = None  # real id wins; drop any synthetic session
        live_id = f"live_{game_id}"
        holder._lm_live_id = live_id
        if gt is not None:
            holder._lm_last_gt = gt
        return live_id

    live_id = getattr(holder, "_lm_live_id", None)
    if live_id and not reset:
        if gt is not None:
            holder._lm_last_gt = gt
        return live_id
    if live_id:
        holder._lm_live_id = None

    global _synthetic_seq
    session = getattr(holder, "_lm_session", None)
    if session is None or reset:
        with _seq_lock:
            _synthetic_seq += 1
            seq = _synthetic_seq
        session = f"sess_{mode}_{_champ_token(cur, state)}_{seq}"
        holder._lm_session = session
    if gt is not None:
        holder._lm_last_gt = gt
    return session


def match_key(holder, cur: dict, state: dict, mode: str) -> str:
    """Public, fail-soft wrapper over ``_resolve_match_id`` (D-01b).

    The DS calibration log needs the SAME per-match key the metric streamer
    uses, so ARAM / Arena rows - which never carry a Live Client game_id - stop
    being permanently unjoinable. This is deliberately a thin wrapper and NOT a
    second minting implementation: one seam, one key, so a calibration row and
    a metric row for the same tick agree.

    Two shapes come back:
      ``live_<gameId>``               a real game_id was present (SR)
      ``sess_<mode>_<champ>_<seq>``   synthesised, stable for the whole game

    Unlike ``stream()`` this is NOT gated on ``enabled()`` - calibration keys
    must be minted whether or not metric capture is switched on.

    Returns ``""`` on any failure. Calibration logging is best-effort and must
    never be able to take down a coach tick, so the caller can pass the result
    straight through without its own guard.
    """
    try:
        return _resolve_match_id(holder, cur or {}, state or {}, mode)
    except Exception as exc:  # noqa: BLE001
        logger.debug("live-metrics match_key error (%s): %s", mode, exc)
        return ""


def stream(holder, cur: dict, state: dict, mode: str) -> int:
    """Feed one coach tick to a per-match MetricStreamer stashed on `holder`.

    Returns the number of metric rows buffered this tick (0 when disabled,
    when the streamer cannot be imported, or on any error). Never raises - a
    streaming fault must not take down the coach. The first fault of a streak
    is logged at WARNING by exception type only (the message can carry a DB
    path); repeats of the same type log at DEBUG until a tick succeeds.
    """
    global _stream_fault
    if not enabled():
        return 0
    streamer_cls = _resolve_streamer()
    if streamer_cls is None:
        return 0
    try:
        state = state or {}
        cur = cur or {}
        match_id = _resolve_match_id(holder, cur, state, mode)
        existing = getattr(holder, "_streamer", None)
        if existing is None or getattr(existing, "match_id", None) != match_id:
            holder._streamer = streamer_cls(
                match_id=match_id,
                champion=cur.get("champion") or state.get("champion"),
                mode=mode,
            )
        rows = holder._streamer.on_state(cur)
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        if name != _stream_fault:
            _stream_fault = name
            logger.warning(
                "live-metrics capture failed (%s): %s; repeats log at debug "
                "until a tick succeeds", mode, name)
        else:
            logger.debug("live-metrics stream error (%s): %s", mode, exc)
        return 0
    _stream_fault = None
    return rows
