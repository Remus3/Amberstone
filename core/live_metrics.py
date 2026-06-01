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

Both default OFF, so the in-code default is byte-identical to no-capture; the
local coach_settings.json (gitignored) is where the operator flips it on.

Wire-in (coach side): after a coach writes coaching_data.json, call

    from core import live_metrics
    live_metrics.stream(self, cur, state, mode)

where `cur` is the just-written coaching_data dict (carries game_time_s /
level / champion) and `state` is the raw game-state dict (carries game_id).
The per-match streamer is stashed on the coach as `holder._streamer` and is
error-wrapped: it can never crash the coach (any failure is logged + swallowed).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("rc.live_metrics")

_APP_DIR = Path(__file__).resolve().parent.parent
_COACH_CFG = _APP_DIR / "config" / "coach_settings.json"
_CFG_KEY = "live_metrics_enabled"

# env switch read once at import (legacy contract).
_ENV_ENABLED = os.environ.get("RC_LIVE_METRICS", "0") == "1"

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
    except Exception as exc:  # pragma: no cover - import-environment specific
        logger.warning("live-metrics import failed: %s", exc)
        _MetricStreamer = None
    return _MetricStreamer


def _config_enabled() -> bool:
    """True if config/coach_settings.json sets live_metrics_enabled truthy.
    Re-read on every call (tiny file) so a flip takes effect without restart.
    Any read/parse error -> False (fail-closed; capture stays off)."""
    try:
        if _COACH_CFG.is_file():
            data = json.loads(_COACH_CFG.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return bool(data.get(_CFG_KEY, False))
    except Exception:
        pass
    return False


def enabled() -> bool:
    """True when either the env switch (import-time) or the config switch
    (live) is on."""
    return _ENV_ENABLED or _config_enabled()


def stream(holder, cur: dict, state: dict, mode: str) -> int:
    """Feed one coach tick to a per-match MetricStreamer stashed on `holder`.

    Returns the number of metric rows buffered this tick (0 when disabled,
    when `state` carries no game_id, or on any error). Never raises - a
    streaming fault must not take down the coach.
    """
    if not enabled():
        return 0
    streamer_cls = _resolve_streamer()
    if streamer_cls is None:
        return 0
    try:
        state = state or {}
        cur = cur or {}
        game_id = str(state.get("game_id") or state.get("gameId") or "")
        if not game_id:
            return 0
        match_id = f"live_{game_id}"
        existing = getattr(holder, "_streamer", None)
        if existing is None or existing.match_id != match_id:
            holder._streamer = streamer_cls(
                match_id=match_id,
                champion=cur.get("champion") or state.get("champion"),
                mode=mode,
            )
        return holder._streamer.on_state(cur)
    except Exception as exc:
        logger.debug("live-metrics stream error (%s): %s", mode, exc)
        return 0
