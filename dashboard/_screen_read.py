"""s240 - on-demand VLM coach (AUTONOMOUS_AUDIT opportunity #3).

Operator clicks "SCREEN READ" once -> RC does ONE Sonnet vision pass
over the latest frame it ALREADY holds in the :8889 relay (pushed by
the s221-safe bettercam DXGI Game-PC agent during a live game) -> a
single tactical coaching one-liner surfaced on a dedicated dashboard
pill.

Why this is low-risk:
  - NO new screen capture. It reuses modes.shared_vision._capture_screen
    (read the relay buffer RC already has) - so it does NOT spin up a
    capture loop (that was the *continuous* PIL all-screens agent,
    retired s221; this never captures, it only reads the buffer).
  - NO new Sonnet/cost code. ScreenReadVision subclasses the audited
    GameVisionReader - the moon_proxy -> direct-SDK fallback + the
    cost_tracker daily-cap + token-bucket gating in _extract() apply
    verbatim (s173 anti-drift: one Sonnet path, not a second copy).
  - ADR-006 compliant: vision + LiveClient self-coaching only (no Riot
    Web API). The prompt yields strategic judgement, never input
    automation / decision-simulation.

Result lands in data/screen_read.json (atomic) and the state-builder
stamps it onto /api/state.screen_read - a DEDICATED field, independent
of the coach loop's auto `immediate`, so an on-demand read the operator
wants to dwell on is not clobbered by the next ~2s coach tick.
"""
from __future__ import annotations

import logging
import threading
import time

from modes.shared_vision import SONNET_MODEL, GameVisionReader

log = logging.getLogger("rc.web_dashboard")

SCREEN_READ_REL = "data/screen_read.json"

# Max chars surfaced on the pill - defensive against a verbose model;
# the prompt asks for ~22 words but we hard-cap so a runaway response
# can't blow out the panel.
_TEXT_CAP = 280

# ADR-006 / Riot "no decision-simulation": the model gives strategic
# judgement like a coach over the shoulder - NOT key presses, item-buy
# macros, or step-by-step input automation. JSON output is required
# because GameVisionReader._extract() json.loads() the response.
_PROMPT = (
    "You are a League of Legends coach watching the player's own screen "
    "during their live game. Give ONE concise tactical observation and "
    "recommendation for THIS exact moment (max ~22 words). Read the "
    "minimap, HP and mana bars, gold, level, objective timers, and any "
    "visible threats; advise on positioning, recall timing, objective "
    "contests, lane state, vision, or safety - the single highest-value "
    "thing right now. Speak as strategic judgement only, like a coach "
    "talking over the player's shoulder. Do NOT describe key presses, "
    "ability/item input macros, or step-by-step automation. If the "
    "screen is not a live game (loading, shop, lobby, menu), say that "
    "briefly instead. Respond with ONLY compact JSON, no prose, no "
    'code fence: {"note": "<your one-liner>"}'
)

# In-flight guard: the operator may double-click; one Sonnet pass at a
# time. The pending marker is written synchronously before the worker
# thread starts so the dashboard shows "reading..." within one poll.
_inflight_lock = threading.Lock()
_inflight = False


class ScreenReadVision(GameVisionReader):
    """Reuses the entire audited capture + Sonnet + cost-gate path; the
    only delta is the on-demand tactical prompt (vs the structured OCR
    extraction prompts the mode coaches use)."""

    PROMPT = _PROMPT


def _build_reader() -> GameVisionReader:
    """Construct the reader with the operator's Anthropic key (same key
    file the mode coaches use). Factored out as a seam so tests can
    inject a stub without an Anthropic client or a live relay."""
    from coaches._base_coach import read_api_key
    return ScreenReadVision(read_api_key())


def _result(status: str, *, text: str = "", error=None,
            requested_ts: float = 0.0) -> dict:
    return {
        "status": status,            # "ok" | "pending" | "error"
        "text": text,
        "error": error,              # None | short code
        "ts": time.time(),           # when this doc was produced
        "requested_ts": requested_ts,
        "model": SONNET_MODEL,
    }


def run_screen_read(requested_ts: float = 0.0) -> dict:
    """Capture-from-relay -> Sonnet -> normalized result dict. Never
    raises - every failure mode maps to a terse error code the pill
    renders. Reader outcomes:
      None              -> no_fresh_frame (relay empty/stale: no game?)
      {} / no "note"    -> empty_note
      {"note": "..."}   -> ok
      exception in read -> vision_failed
      no api key file   -> no_api_key
    """
    try:
        reader = _build_reader()
    except Exception as exc:  # noqa: BLE001
        log.warning("screen_read: reader build failed: %s", exc)
        return _result("error", error="no_api_key", requested_ts=requested_ts)
    try:
        raw = reader.read()
    except Exception as exc:  # noqa: BLE001
        log.warning("screen_read: vision read failed: %s", exc)
        return _result("error", error="vision_failed", requested_ts=requested_ts)
    if raw is None:
        # _capture_screen returned None (no frame / >30s stale / relay
        # down) OR _extract returned None (budget block / parse fail).
        # NB: must be `is None`, not falsy - an empty-dict vision result
        # is a DIFFERENT failure (got a response, no usable note) that
        # maps to empty_note below, not no_fresh_frame.
        return _result("error", error="no_fresh_frame",
                       requested_ts=requested_ts)
    note = ""
    if isinstance(raw, dict):
        note = str(raw.get("note") or "").strip()
    if not note:
        return _result("error", error="empty_note", requested_ts=requested_ts)
    return _result("ok", text=note[:_TEXT_CAP], requested_ts=requested_ts)


def _write(doc: dict) -> None:
    from dashboard._writers import atomic_write_json
    atomic_write_json(SCREEN_READ_REL, doc)


def _worker(requested_ts: float) -> None:
    global _inflight
    try:
        doc = run_screen_read(requested_ts=requested_ts)
        doc["requested_ts"] = requested_ts
        _write(doc)
    except Exception as exc:  # belt + braces - worker must never die silently  # noqa: BLE001
        log.warning("screen_read worker: %s", exc)
        try:
            _write(_result("error", error="worker_failed",
                            requested_ts=requested_ts))
        except Exception:  # noqa: BLE001
            pass
    finally:
        with _inflight_lock:
            _inflight = False


def trigger_screen_read() -> bool:
    """Operator-initiated. Writes the pending marker synchronously (so
    the pill flips to "reading..." on the next ~500ms poll) then runs
    the Sonnet pass on a daemon thread so the HTTP handler doesn't block
    the ~2-3s round trip. Returns False (no-op) if one is already
    running."""
    global _inflight
    with _inflight_lock:
        if _inflight:
            return False
        _inflight = True
    ts = time.time()
    try:
        _write(_result("pending", requested_ts=ts))
        threading.Thread(
            target=_worker, args=(ts,), daemon=True,
            name="rc-screen-read",
        ).start()
    except Exception:
        # Cycle-8 audit (slice B): if the pending write (os.replace
        # WinError 5 flake) or the thread spawn raises, the worker that
        # resets _inflight never runs - without this reset the flag
        # wedged True forever and every later trigger silently no-opped
        # until restart. Re-raise so the route 500s + logs.
        with _inflight_lock:
            _inflight = False
        raise
    return True


def _reset_inflight_for_test() -> None:
    """Test seam - clears the module-global in-flight flag so suites
    don't bleed state (mirrors the chip's _resetArchetypeNudgeSig)."""
    global _inflight
    with _inflight_lock:
        _inflight = False
