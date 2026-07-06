"""core/obs_frame_source.py - sync facade over the OBS-WS frame lane.

ZOI orchestration plan spec O (2026-07-05): OBS Game Capture is
OCCLUSION-PROOF (it captures the game surface even when the RC overlay
sits on top), so an OBS `GetSourceScreenshot` frame is a strictly better
CV input than the full-desktop GDI BitBlt. This module is the ONE sync
entry point the vision pipeline calls:

    from core.obs_frame_source import get_obs_frame
    raw = get_obs_frame()          # raw JPEG bytes or None

Config-gated via the `obs` block in config/coach_settings.json (see
core/obs_publisher.py for the full documented shape):

    "obs": { ..., "frame_source": false, "frame_source_name": "Game Capture",
             "frame_timeout_s": 1.5, "frame_width": 0, "frame_max_age_s": 3.0 }

DEFAULT OFF: with `frame_source` false or absent (or the whole obs block
absent, or the config unreadable) `get_obs_frame` returns None without
touching the network - consumers fall back to their existing GDI path
byte-identically.

Fail-soft contract (repo-wide for new pure modules): NEVER raises on any
input or environment state (OBS down, not identified, corrupt config,
malformed payloads) - degrades to None. Never blocks the caller beyond
roughly the configured timeout: the one-shot fetch runs on a daemon
worker thread that is abandoned (not joined further) if it overruns.

Fast path: when the OBS publisher loop is running with the flag on it
keeps a frame warm every tick (core.obs_publisher keep-warm slot);
`get_obs_frame` serves that slot when fresh and only pays a one-shot
connect+identify+screenshot round-trip when the slot is cold.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

_log = logging.getLogger("rc.obs_frame_source")

_DEFAULT_TIMEOUT_S = 1.5
_DEFAULT_MAX_AGE_S = 3.0
_JOIN_GRACE_S = 0.75      # extra headroom over timeout_s when joining the worker
_CFG_TTL_S = 5.0          # config re-read cadence (disk JSON is cheap but not free)

_cfg_lock = threading.Lock()
_cfg_cache: dict = {"cfg": None, "mono": 0.0}


def _get_obs_cfg() -> dict:
    """TTL-cached `obs` config block. {} on any failure (fail-soft)."""
    now = time.monotonic()
    with _cfg_lock:
        cached = _cfg_cache["cfg"]
        if cached is not None and (now - _cfg_cache["mono"]) < _CFG_TTL_S:
            return cached
    try:
        from core.obs_publisher import _load_obs_config
        cfg = _load_obs_config()
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:  # noqa: BLE001
        cfg = {}
    with _cfg_lock:
        _cfg_cache.update(cfg=cfg, mono=now)
    return cfg


def _reset_for_tests() -> None:
    """Test helper: drop the cached config so monkeypatched loaders apply."""
    with _cfg_lock:
        _cfg_cache.update(cfg=None, mono=0.0)


def obs_frame_source_enabled() -> bool:
    """True only when config `obs.frame_source` is truthy. Fail-CLOSED."""
    try:
        return bool(_get_obs_cfg().get("frame_source"))
    except Exception:  # noqa: BLE001
        return False


def get_obs_frame(timeout_s: "float | None" = None) -> "bytes | None":
    """Return the latest OBS source frame as raw image bytes (JPEG), or None.

    None when: the `obs.frame_source` flag is off/absent (DEFAULT), OBS is
    down or not identified, the request times out, or anything else goes
    wrong. Never raises; never blocks much past `timeout_s` (default from
    config `frame_timeout_s`, else 1.5s).
    """
    try:
        cfg = _get_obs_cfg()
        if not cfg.get("frame_source"):
            return None
        if timeout_s is None:
            try:
                timeout_s = float(cfg.get("frame_timeout_s", _DEFAULT_TIMEOUT_S))
            except (TypeError, ValueError):
                timeout_s = _DEFAULT_TIMEOUT_S
        try:
            max_age_s = float(cfg.get("frame_max_age_s", _DEFAULT_MAX_AGE_S))
        except (TypeError, ValueError):
            max_age_s = _DEFAULT_MAX_AGE_S
        from core import obs_publisher as _pub
        data = _pub.peek_frame(max_age_s=max_age_s)
        if data:
            return data
        return _fetch_once(cfg, timeout_s)
    except Exception:  # noqa: BLE001
        return None


def _fetch_once(cfg: dict, timeout_s: float) -> "bytes | None":
    """One-shot synchronous fetch: run the async round-trip on a private
    daemon thread with its own event loop so this works from ANY caller
    thread (including the AppLoop's own asyncio thread) and can never wedge
    the caller - an overrunning worker is abandoned, not awaited."""
    box: dict = {}

    def _worker() -> None:
        try:
            box["data"] = asyncio.run(_fetch_async(cfg, timeout_s))
        except Exception:  # noqa: BLE001
            box["data"] = None

    try:
        t = threading.Thread(target=_worker, name="obs-frame-oneshot",
                             daemon=True)
        t.start()
        t.join(timeout=max(0.05, float(timeout_s)) + _JOIN_GRACE_S)
    except Exception:  # noqa: BLE001
        return None
    return box.get("data")


async def _fetch_async(cfg: dict, timeout_s: float) -> "bytes | None":
    """Connect, identify (OBS-WS v5 handshake incl. auth), grab one
    GetSourceScreenshot. Returns raw bytes or None; a success also warms
    the keep-warm slot (inside grab_source_screenshot)."""
    try:
        import websockets

        from core import obs_publisher as _pub
        host = cfg.get("host", "127.0.0.1")
        port = int(cfg.get("port", 4455))
        password = cfg.get("password", "") or ""
        source = str(cfg.get("frame_source_name") or "Game Capture")
        try:
            width = int(cfg.get("frame_width", 0) or 0)
        except (TypeError, ValueError):
            width = 0
        url = f"ws://{host}:{port}"
        open_to = min(max(0.05, float(timeout_s)), 4.0)
        async with websockets.connect(url, open_timeout=open_to) as ws:
            ok = await asyncio.wait_for(
                _pub.OBSPublisher()._identify(ws, password),
                timeout=max(0.05, float(timeout_s)))
            if not ok:
                _log.debug("OBS frame fetch: identify failed")
                return None
            return await _pub.grab_source_screenshot(
                ws, source, image_width=width, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001
        _log.debug("OBS frame fetch failed: %s", exc)
        return None
