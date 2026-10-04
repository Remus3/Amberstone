# arch: OBS match recorder (operator-gated, default OFF) | section=core | frozen=no
"""core/obs_recorder.py - record League matches through the operator's OBS.

RM-637 (directive X-37). The binding design is
``docs/adr/ADR-016-local-match-recording.md``. Behaviour observed in external
references C/E/G/H, re-implemented clean-room; nothing is vendored and every
numeric constant below is RC's own choice (each says why).

DEFAULT OFF, twice over. Nothing happens unless BOTH hold:
  * ``obs.record.enabled`` is literally ``true`` in the gitignored
    ``config/coach_settings.json`` (the publisher's own ``obs.enabled`` is a
    different flag and does not turn recording on), AND
  * the mode / queue is opted in via ``core.feature_policy.vod_record_allowed``
    (feature ``vod_record``, itself default-off).

Rules from ADR-016, each enforced here:
  * Ownership token = the ``outputPath`` of the RecordStateChanged STARTED
    event that follows RC's own StartRecord. RC stops a recording only while
    it still owns it. If OBS is already recording when a game starts, RC
    starts nothing, never stops it, and the sidecar says ``owner=operator``.
  * Never alter the operator's OBS: no Set* request is ever sent. Probes are
    reads (GetVersion, GetProfileParameter, GetRecordDirectory, the active
    scene's item lists). Chapters only when obs-websocket >= 5.5 AND the
    profile's record format is hybrid MP4; otherwise degrade silently.
  * Refuse to start if an ENABLED game-capture input is in the active scene
    (ADR-011: hook injection trips Vanguard). An unreadable scene refuses too.
  * Start when gameflow reaches InProgress AND the Live Client answers.
    Stop on the end-of-game block, a GameEnd event, leaving the game, N
    consecutive Live Client TRANSPORT failures, N consecutive OBS transport
    failures, or a disk-guard trip. A parse error or an HTTP error status
    never ends a recording.
  * Gameflow comes from ``core/lcu_events.py`` - never the frozen
    ``app/_game_lifecycle.py``.
  * Bookmarks: Live Client events keyed by EventTime, with the EventID
    high-water mark captured at attach as the baseline (attach emits nothing).
  * Alignment: ``core/vod_alignment.py``. Stall detector: GetRecordStatus
    ``outputDuration`` delta (the G6-03 check).
  * Sidecar ``data/recordings/<matchId>.json`` (gitignored), atomic write.
  * The disk guard (``core/disk_guard.py``) runs as its own producer.

Wiring: ``install_if_enabled()`` is called from the default-off optional-tap
hook in ``core/liveclient_cache.py`` (non-frozen). With the flag off it reads
the config once and returns False.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from core import disk_guard as _dg
from core.vod_alignment import AlignmentTracker, Poll

_log = logging.getLogger("rc.obs_recorder")

_APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SIDECAR_DIR = _APP_DIR / "data" / "recordings"

SIDECAR_SCHEMA = 1

# obs-websocket v5 EventSubscription::Outputs (1 << 6): RecordStateChanged.
EVENT_SUB_OUTPUTS = 1 << 6

PHASE_IN_GAME = "InProgress"
END_PHASES = frozenset({"PreEndOfGame", "WaitingForStats", "EndOfGame"})
# Phases that prove the game is over without an end-of-game block (remake,
# dodge, crash back to client). "Reconnect" and "GameStart" are NOT here: a
# reconnect keeps the recording running.
OUT_OF_GAME_PHASES = frozenset({"None", "Lobby", "Matchmaking", "ReadyCheck",
                                "ChampSelect", "TerminatedInError"})

STARTED = "OBS_WEBSOCKET_OUTPUT_STARTED"
STOPPED = "OBS_WEBSOCKET_OUTPUT_STOPPED"

CHAPTER_MIN_WS = (5, 5, 0)
HYBRID_FORMATS = frozenset({"hybrid_mp4"})
GAME_CAPTURE_KIND = "game_capture"

# Our own defaults (configurable under obs.record):
# - liveclient_failures_to_stop 20: the cache polls every 0.5 s, so 10 s of
#   an unreachable relay; a loading-screen hiccup is far shorter.
# - obs_failures_to_stop 5: one OBS request per tick at 1 s, about 5 s.
# - stall_polls 3: three consecutive polls where outputDuration advanced by
#   less than half the wall time count as one stall episode.
# - poll_s 1.0: tick cadence; cheap read-only GetRecordStatus.
_DEFAULTS = {"liveclient_failures_to_stop": 20, "obs_failures_to_stop": 5,
             "stall_polls": 3, "poll_s": 1.0}

# Events that mark no moment worth a chapter.
_NOT_BOOKMARKS = frozenset({"GameStart", "MinionsSpawning"})

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


# -- config ------------------------------------------------------------------

def _load_obs_config() -> dict:
    """The ``obs`` block of config/coach_settings.json (read only)."""
    try:
        from core.obs_publisher import _load_obs_config as _pub_load
        cfg = _pub_load()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def record_enabled(obs_cfg: Any) -> bool:
    """True only for a literal boolean ``obs.record.enabled: true``."""
    if not isinstance(obs_cfg, dict):
        return False
    rec = obs_cfg.get("record")
    return isinstance(rec, dict) and rec.get("enabled") is True


def _int_cfg(rec: dict, key: str) -> int:
    try:
        v = int(rec.get(key, _DEFAULTS[key]))
        return v if v > 0 else int(_DEFAULTS[key])
    except (TypeError, ValueError):
        return int(_DEFAULTS[key])


def _version_tuple(v: Any) -> tuple:
    parts = []
    for p in str(v or "").split(".")[:3]:
        m = re.match(r"\d+", p)
        parts.append(int(m.group(0)) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _ok(d: Any) -> bool:
    return isinstance(d, dict) and (d.get("requestStatus") or {}).get("result") is True


def _rdata(d: Any) -> dict:
    if not isinstance(d, dict):
        return {}
    r = d.get("responseData")
    return r if isinstance(r, dict) else {}


def _mode_key(game_mode: Any) -> str:
    try:
        from core.game_snapshot import mode_from_game_mode_string
        return str(mode_from_game_mode_string(str(game_mode or ""))).lower()
    except Exception:  # noqa: BLE001
        return ""


def _default_policy(mode: str, queue_id: Any) -> bool:
    try:
        from core.feature_policy import vod_record_allowed
        return bool(vod_record_allowed(mode, queue_id))
    except Exception:  # noqa: BLE001
        return False


def _safe_match_id(raw: Any, wall: float) -> str:
    s = _SAFE_ID.sub("", str(raw if raw is not None else ""))[:64]
    return s or f"unknown-{int(wall)}"


def _atomic_write_json(path: Path, data: dict) -> None:
    """tmp + replace through core.polled_json (per-writer scratch name,
    bounded PermissionError retry, scratch cleanup on failure)."""
    from core.polled_json import atomic_write_bytes
    atomic_write_bytes(Path(path), json.dumps(data, indent=2, ensure_ascii=True).encode("ascii"))


def _fmt_clock(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


# -- transport (reuses core/obs_publisher.py's request/response lane) -------

class _WsSession:
    """One identified obs-websocket connection. Events read on the request
    lane or by ``pump`` go to ``on_event``."""

    def __init__(self, ws: Any, on_event: Callable[[dict], None]) -> None:
        self._ws = ws
        self._on_event = on_event

    async def request(self, rtype: str, data: Optional[dict] = None,
                      timeout_s: float = 2.0) -> Optional[dict]:
        from core.obs_publisher import request_response
        return await request_response(self._ws, rtype, data, timeout_s=timeout_s,
                                      on_event=self._on_event)

    async def pump(self, timeout_s: float = 0.05) -> bool:
        """Read pending frames for up to ``timeout_s``. False if the socket
        is gone."""
        deadline = time.monotonic() + max(0.01, timeout_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError):
                return True
            except Exception:  # noqa: BLE001
                return False
            try:
                msg = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(msg, dict) and msg.get("op") == 5 and isinstance(msg.get("d"), dict):
                try:
                    self._on_event(msg["d"])
                except Exception:  # noqa: BLE001
                    pass

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:  # noqa: BLE001
            pass


async def _default_session_factory(cfg: dict, on_event: Callable[[dict], None]):
    import websockets

    from core.obs_publisher import identify
    url = f"ws://{cfg.get('host', '127.0.0.1')}:{int(cfg.get('port', 4455))}"
    try:
        ws = await websockets.connect(url, open_timeout=4)
    except Exception as exc:  # noqa: BLE001
        _log.debug("OBS recorder connect failed for %s: %s", url, exc)
        return None
    if not await identify(ws, cfg.get("password", "") or "", EVENT_SUB_OUTPUTS):
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
        _log.warning("OBS recorder: obs-websocket identify failed")
        return None
    return _WsSession(ws, on_event)


# -- per-game state ----------------------------------------------------------

class _Game:
    def __init__(self, match_id: str, queue_id: Any, game_mode: Any, mode: str,
                 attach_wall: float) -> None:
        self.match_id = match_id
        self.queue_id = queue_id
        self.game_mode = game_mode
        self.mode = mode
        self.owner = "none"
        self.attach_wall = attach_wall
        self.record_start_wall: Optional[float] = None
        self.record_stop_wall: Optional[float] = None
        self.game_end_wall: Optional[float] = None
        self.start_game_time: Optional[float] = None
        self.pending_start = False
        self.owned = False
        self.stopping = False
        self.token: Optional[str] = None
        self.output_path: Optional[str] = None
        self.record_dir: Optional[str] = None
        self.chapters_supported = False
        self.chapters_off = False
        self.pending_chapters: list[str] = []
        self.event_hw: Optional[int] = None
        self.game_end_seen = False
        self.bookmarks: list[dict] = []
        self.death_count: Optional[int] = None
        self.tracker = AlignmentTracker(record_start_wall=attach_wall)
        self.last_status: Optional[dict] = None
        self.prev_duration: Optional[tuple[float, float]] = None
        self.stall_run = 0
        self.diag: dict = {
            "refused": None, "obs_version": None, "obs_websocket_version": None,
            "output_mode": None, "record_format": None,
            "chapters_supported": False, "chapters_created": 0,
            "chapters_failed": 0, "stall_count": 0, "ownership_lost": None,
            "started_event_missing": False, "obs_transport_failures": 0,
            "liveclient_transport_failures": 0, "start_free_bytes": None,
            "start_rc_recorded_bytes": None, "output_path_mismatch": False,
        }


# -- the recorder --------------------------------------------------------------

class ObsRecorder:
    """Config-gated recorder. Inputs arrive on listener callbacks (any
    thread); all OBS traffic happens inside ``tick()`` on one coroutine."""

    def __init__(self, obs_cfg: dict, *, sidecar_dir: Optional[Path] = None,
                 policy_fn: Optional[Callable[[str, Any], bool]] = None,
                 free_bytes_fn: Optional[Callable[[Any], Optional[int]]] = None,
                 rc_bytes_fn: Optional[Callable[[Path], int]] = None,
                 clock: Callable[[], float] = time.time,
                 session_factory: Optional[Callable[..., Awaitable[Any]]] = None,
                 started_timeout_s: float = 5.0) -> None:
        self._cfg = obs_cfg if isinstance(obs_cfg, dict) else {}
        rec = self._cfg.get("record") if isinstance(self._cfg.get("record"), dict) else {}
        self.enabled = record_enabled(self._cfg)
        self._lc_limit = _int_cfg(rec, "liveclient_failures_to_stop")
        self._obs_limit = _int_cfg(rec, "obs_failures_to_stop")
        self._stall_polls = _int_cfg(rec, "stall_polls")
        try:
            self.poll_s = max(0.2, float(rec.get("poll_s", _DEFAULTS["poll_s"])))
        except (TypeError, ValueError):
            self.poll_s = float(_DEFAULTS["poll_s"])
        self._sidecar_dir = Path(sidecar_dir) if sidecar_dir else DEFAULT_SIDECAR_DIR
        self._policy = policy_fn or _default_policy
        self._free = free_bytes_fn or _dg.free_bytes_for
        self._rc_bytes = rc_bytes_fn or _dg.rc_recorded_bytes
        self._clock = clock
        self._factory = session_factory or _default_session_factory
        self._started_timeout = float(started_timeout_s)
        self._lock = threading.RLock()
        self._phase: Optional[str] = None
        self._session_info: dict = {}
        self._lc_data: Optional[dict] = None
        self._lc_fail = 0
        self._obs_fail = 0
        self._sess: Any = None
        self._game: Optional[_Game] = None
        self._done: set[str] = set()
        self._disk_trip = False
        self._stop = asyncio.Event()

    # -- listener inputs (any thread) ----------------------------------------

    def on_gameflow_phase(self, payload: Any) -> None:
        if not self.enabled:
            return
        if isinstance(payload, str):
            with self._lock:
                self._phase = payload

    def on_gameflow_session(self, payload: Any) -> None:
        if not self.enabled or not isinstance(payload, dict):
            return
        gd = payload.get("gameData") if isinstance(payload.get("gameData"), dict) else {}
        q = gd.get("queue") if isinstance(gd.get("queue"), dict) else {}
        with self._lock:
            self._session_info = {"game_id": gd.get("gameId"),
                                  "queue_id": q.get("id"),
                                  "game_mode": q.get("gameMode")}
            ph = payload.get("phase")
            if isinstance(ph, str):
                self._phase = ph

    def on_liveclient_snapshot(self, snap: Any) -> None:
        if not self.enabled:
            return
        data = getattr(snap, "data", None)
        failure = getattr(snap, "failure", "") or ""
        with self._lock:
            if isinstance(data, dict):
                self._lc_data = data
                self._lc_fail = 0
            else:
                self._lc_data = None
                if failure == "transport":
                    self._lc_fail += 1
                else:
                    # A parse error or an HTTP error status proves the
                    # transport answered: it never counts toward the stop.
                    self._lc_fail = 0
            g = self._game
            if g is None or not isinstance(data, dict):
                return
            wall = self._snap_wall(snap)
            self._ingest(g, data, wall)

    def _snap_wall(self, snap: Any) -> float:
        for attr in ("ts", "fetched_at"):
            v = getattr(snap, attr, None)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return float(v)
        return float(self._clock())

    @staticmethod
    def _events(data: dict) -> list:
        evs = (data.get("events") or {}) if isinstance(data.get("events"), dict) else {}
        out = evs.get("Events") if isinstance(evs, dict) else None
        return [e for e in out if isinstance(e, dict)] if isinstance(out, list) else []

    @staticmethod
    def _event_id(e: dict) -> Optional[int]:
        v = e.get("EventID")
        if isinstance(v, bool):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _game_time(data: dict) -> Optional[float]:
        gd = data.get("gameData") if isinstance(data.get("gameData"), dict) else {}
        v = gd.get("gameTime")
        if isinstance(v, bool):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _baseline(self, g: _Game, data: Optional[dict]) -> None:
        """Attach: capture the EventID high-water mark; emit nothing."""
        hw = -1
        if isinstance(data, dict):
            for e in self._events(data):
                eid = self._event_id(e)
                if eid is not None and eid > hw:
                    hw = eid
            gt = self._game_time(data)
            if gt is not None:
                g.tracker.observe(Poll(wall=g.attach_wall, game_time=gt))
            g.death_count = self._deaths(data, g.death_count)
        g.event_hw = hw

    @staticmethod
    def _own_ids(data: dict) -> set:
        ap = data.get("activePlayer") if isinstance(data.get("activePlayer"), dict) else {}
        return {str(ap[k]) for k in ("riotId", "summonerName", "riotIdGameName")
                if ap.get(k)}

    def _deaths(self, data: dict, prev: Optional[int]) -> Optional[int]:
        ids = self._own_ids(data)
        if not ids:
            return prev
        players = data.get("allPlayers")
        if isinstance(players, list):
            for p in players:
                if not isinstance(p, dict):
                    continue
                if ids & {str(p.get(k)) for k in ("riotId", "summonerName") if p.get(k)}:
                    sc = p.get("scores") if isinstance(p.get("scores"), dict) else {}
                    try:
                        return int(sc.get("deaths"))
                    except (TypeError, ValueError):
                        break
        n = sum(1 for e in self._events(data)
                if e.get("EventName") == "ChampionKill" and str(e.get("VictimName")) in ids)
        return max(n, prev or 0)

    def _ingest(self, g: _Game, data: dict, wall: float) -> None:
        if g.event_hw is None:
            self._baseline(g, data)
            return
        gt = self._game_time(data)
        if gt is not None:
            g.tracker.observe(Poll(wall=wall, game_time=gt))
        g.death_count = self._deaths(data, g.death_count)
        ids = self._own_ids(data)
        for e in sorted(self._events(data), key=lambda x: self._event_id(x) or -1):
            eid = self._event_id(e)
            if eid is None or eid <= g.event_hw:
                continue
            g.event_hw = eid
            name = str(e.get("EventName") or "")
            try:
                et = float(e.get("EventTime"))
            except (TypeError, ValueError):
                continue
            if name == "GameEnd":
                g.game_end_seen = True
                g.game_end_wall = wall
                continue
            if name in _NOT_BOOKMARKS:
                continue
            m = g.tracker.mark(game_time=et, wall=wall, key=eid, label=name)
            bm = {"event_id": eid, "name": name, "game_time": et,
                  "video_time": m["video_time"], "provisional": m["provisional"]}
            if name == "ChampionKill":
                bm["own_death"] = str(e.get("VictimName")) in ids
            g.bookmarks.append(bm)
            if g.chapters_supported and not g.chapters_off and g.owned:
                g.pending_chapters.append(f"{name} {_fmt_clock(et)}"[:96])

    # -- OBS events -----------------------------------------------------------

    def _on_obs_event(self, ev: dict) -> None:
        if ev.get("eventType") != "RecordStateChanged":
            return
        d = ev.get("eventData") if isinstance(ev.get("eventData"), dict) else {}
        state = d.get("outputState")
        path = d.get("outputPath") if isinstance(d.get("outputPath"), str) else None
        with self._lock:
            g = self._game
            if g is None:
                return
            if state == STARTED:
                if g.pending_start:
                    g.pending_start = False
                    g.owned = True
                    g.owner = "rc"
                    g.token = path
                    g.diag["started_event_missing"] = False
                    now = float(self._clock())
                    g.record_start_wall = now
                    g.tracker = AlignmentTracker(record_start_wall=now)
                    if isinstance(self._lc_data, dict):
                        g.start_game_time = self._game_time(self._lc_data)
                elif g.owned and path != g.token:
                    g.owned = False
                    g.diag["ownership_lost"] = "restarted_externally"
            elif state == STOPPED:
                if g.owned and (path is None or g.token is None or path == g.token):
                    g.owned = False
                    g.output_path = path or g.token
                    if not g.stopping:
                        g.diag["ownership_lost"] = "stopped_externally"

    # -- OBS requests -------------------------------------------------------------

    async def _connect(self) -> Any:
        try:
            return await self._factory(self._cfg, self._on_obs_event)
        except Exception as exc:  # noqa: BLE001
            _log.debug("OBS recorder session factory failed: %s", exc)
            return None

    async def _drop_session(self) -> None:
        s, self._sess = self._sess, None
        if s is not None:
            await s.close()

    async def _req(self, rtype: str, data: Optional[dict] = None) -> Optional[dict]:
        """One request. None = TRANSPORT failure (counted). A reply carrying
        requestStatus.result false is returned as-is and is not a failure."""
        if self._sess is None:
            self._sess = await self._connect()
            if self._sess is None:
                self._obs_fail += 1
                return None
        d = await self._sess.request(rtype, data)
        if d is None:
            self._obs_fail += 1
            await self._drop_session()
            return None
        self._obs_fail = 0
        return d

    async def _pump(self, timeout_s: float = 0.05) -> None:
        if self._sess is not None and not await self._sess.pump(timeout_s):
            await self._drop_session()

    async def _probe_format(self, g: _Game) -> None:
        mode = _rdata(await self._req("GetProfileParameter", {
            "parameterCategory": "Output", "parameterName": "Mode"})).get("parameterValue")
        g.diag["output_mode"] = mode
        cat = "AdvOut" if str(mode or "").lower() == "advanced" else "SimpleOutput"
        fmt = None
        for name in ("RecFormat2", "RecFormat"):
            fmt = _rdata(await self._req("GetProfileParameter", {
                "parameterCategory": cat, "parameterName": name})).get("parameterValue")
            if fmt:
                break
        g.diag["record_format"] = fmt

    async def _game_capture_present(self) -> Optional[bool]:
        """True / False, or None when the active scene cannot be read."""
        cur = await self._req("GetCurrentProgramScene")
        if not _ok(cur):
            return None
        r = _rdata(cur)
        scene = r.get("currentProgramSceneName") or r.get("sceneName")
        if not isinstance(scene, str) or not scene:
            return None
        seen: set = set()

        async def walk(name: str, group: bool, depth: int) -> Optional[bool]:
            if depth > 6 or (name, group) in seen:
                return False
            seen.add((name, group))
            rt = "GetGroupSceneItemList" if group else "GetSceneItemList"
            d = await self._req(rt, {"sceneName": name})
            if not _ok(d):
                return None
            items = _rdata(d).get("sceneItems")
            if not isinstance(items, list):
                return None
            for it in items:
                if not isinstance(it, dict) or it.get("sceneItemEnabled") is False:
                    continue
                kind = str(it.get("inputKind") or "")
                if kind.startswith(GAME_CAPTURE_KIND):
                    return True
                child = it.get("sourceName")
                if not isinstance(child, str):
                    continue
                if it.get("isGroup") is True:
                    sub = await walk(child, True, depth + 1)
                elif it.get("sourceType") == "OBS_SOURCE_TYPE_SCENE":
                    sub = await walk(child, False, depth + 1)
                else:
                    continue
                if sub is None or sub:
                    return sub
            return False

        return await walk(scene, False, 0)

    async def _begin(self, info: dict, data: Optional[dict]) -> None:
        now = float(self._clock())
        mode = _mode_key(info.get("game_mode") or
                         ((data or {}).get("gameData") or {}).get("gameMode"))
        queue = info.get("queue_id")
        mid = _safe_match_id(info.get("game_id"), now)
        self._done.add(mid)
        try:
            allowed = bool(self._policy(mode, queue))
        except Exception:  # noqa: BLE001
            allowed = False
        if not allowed:
            _log.info("OBS recorder: %s queue %s not opted in; not recording", mode, queue)
            return
        g = _Game(mid, queue, info.get("game_mode"), mode, now)
        with self._lock:
            self._game = g
            self._lc_fail = 0
            self._baseline(g, self._lc_data)
        self._obs_fail = 0
        self._disk_trip = False

        st = await self._req("GetRecordStatus")
        if not _ok(st):
            g.diag["refused"] = "obs_unreachable" if st is None else "record_status_error"
            self._write_sidecar(g, "recording")
            return
        sd = _rdata(st)
        if sd.get("outputActive") is True:
            g.owner = "operator"
            try:
                dur = float(sd.get("outputDuration") or 0) / 1000.0
            except (TypeError, ValueError):
                dur = 0.0
            with self._lock:
                g.record_start_wall = now - dur
                g.tracker = AlignmentTracker(record_start_wall=now - dur)
            self._write_sidecar(g, "recording")
            return

        ver = _rdata(await self._req("GetVersion"))
        g.diag["obs_version"] = ver.get("obsVersion")
        g.diag["obs_websocket_version"] = ver.get("obsWebSocketVersion")
        await self._probe_format(g)
        g.chapters_supported = bool(
            _version_tuple(ver.get("obsWebSocketVersion")) >= CHAPTER_MIN_WS
            and str(g.diag["record_format"] or "").lower() in HYBRID_FORMATS)
        g.diag["chapters_supported"] = g.chapters_supported

        gc = await self._game_capture_present()
        if gc is not False:
            g.diag["refused"] = ("game_capture_in_active_scene" if gc
                                 else "scene_probe_failed")
            _log.warning("OBS recorder refused to start: %s", g.diag["refused"])
            self._write_sidecar(g, "recording")
            return

        rd = _rdata(await self._req("GetRecordDirectory")).get("recordDirectory")
        g.record_dir = rd if isinstance(rd, str) and rd else None
        free = self._free(g.record_dir) if g.record_dir else None
        try:
            rc_bytes = int(self._rc_bytes(self._sidecar_dir))
        except Exception:  # noqa: BLE001
            rc_bytes = 0
        g.diag["start_free_bytes"] = free
        g.diag["start_rc_recorded_bytes"] = rc_bytes
        ok, why = _dg.start_precondition(free, rc_bytes)
        if not ok:
            g.diag["refused"] = f"disk: {why}"
            _log.warning("OBS recorder refused to start: %s", g.diag["refused"])
            self._write_sidecar(g, "recording")
            return

        with self._lock:
            g.pending_start = True
        r = await self._req("StartRecord")
        if not _ok(r):
            with self._lock:
                g.pending_start = False
            g.diag["refused"] = "start_failed" if r is not None else "start_no_ack"
            self._write_sidecar(g, "recording")
            return
        deadline = time.monotonic() + self._started_timeout
        while time.monotonic() < deadline and self._sess is not None:
            with self._lock:
                if not g.pending_start:
                    break
            await self._pump(0.1)
        with self._lock:
            if g.pending_start:
                # Late STARTED events still claim ownership; until then RC
                # owns nothing and will never stop anything.
                g.diag["started_event_missing"] = True
        _log.info("OBS recorder: started (owner=%s token=%s)", g.owner, g.token)
        self._write_sidecar(g, "recording")

    async def _poll_status(self, g: _Game) -> None:
        st = await self._req("GetRecordStatus")
        if not _ok(st):
            return
        sd = _rdata(st)
        g.last_status = sd
        now = float(self._clock())
        try:
            dur = float(sd.get("outputDuration")) / 1000.0
        except (TypeError, ValueError):
            return
        prev, g.prev_duration = g.prev_duration, (now, dur)
        if prev is None:
            return
        dwall, dvid = now - prev[0], dur - prev[1]
        if dwall < 1.0:
            return
        if dvid < 0.5 * dwall:
            g.stall_run += 1
            if g.stall_run == self._stall_polls:
                g.diag["stall_count"] += 1
                _log.warning("OBS recorder: capture stall (duration +%.1fs over %.1fs)",
                             dvid, dwall)
        else:
            g.stall_run = 0

    async def _flush_chapters(self, g: _Game) -> None:
        with self._lock:
            names, g.pending_chapters = g.pending_chapters, []
        for name in names:
            if g.chapters_off or not g.owned:
                return
            d = await self._req("CreateRecordChapter", {"chapterName": name})
            if _ok(d):
                g.diag["chapters_created"] += 1
            elif d is not None:
                # degrade silently: the sidecar stays the source of truth
                g.diag["chapters_failed"] += 1
                g.chapters_off = True

    def _stop_reason(self, g: _Game) -> Optional[str]:
        with self._lock:
            phase, lc_fail, end_seen = self._phase, self._lc_fail, g.game_end_seen
        if self._disk_trip:
            return "disk_guard"
        if phase in END_PHASES:
            return "end_of_game"
        if end_seen:
            return "game_end_event"
        if phase in OUT_OF_GAME_PHASES:
            return "left_game"
        if lc_fail >= self._lc_limit:
            return "liveclient_transport_failures"
        if g.owner == "rc" and self._obs_fail >= self._obs_limit:
            return "obs_transport_failures"
        return None

    async def _finish(self, g: _Game, reason: str) -> None:
        g.diag["liveclient_transport_failures"] = self._lc_fail
        g.diag["obs_transport_failures"] = self._obs_fail
        if g.owner == "rc" and g.owned and reason != "obs_transport_failures":
            g.stopping = True
            r = await self._req("StopRecord")
            if _ok(r):
                p = _rdata(r).get("outputPath")
                if isinstance(p, str) and p:
                    if g.token and p != g.token:
                        g.diag["output_path_mismatch"] = True
                    g.output_path = p
                await self._pump(0.2)
                with self._lock:
                    g.owned = False
        g.record_stop_wall = float(self._clock())
        self._write_sidecar(g, "final", reason)
        with self._lock:
            self._game = None
        self._disk_trip = False
        await self._drop_session()
        _log.info("OBS recorder: finalized %s (%s)", g.match_id, reason)

    # -- sidecar -------------------------------------------------------------------

    def _write_sidecar(self, g: _Game, status: str, stop_reason: Optional[str] = None) -> None:
        with self._lock:
            res = g.tracker.resolve()
            bms = []
            for b in g.bookmarks:
                r = dict(b)
                if status == "final":
                    r["video_time"] = g.tracker.video_time_for(b["game_time"])
                    r["provisional"] = False
                bms.append(r)
            body = {
                "schema": SIDECAR_SCHEMA,
                "status": status,
                "match_id": g.match_id,
                "queue_id": g.queue_id,
                "game_mode": g.game_mode,
                "mode": g.mode,
                "owner": g.owner,
                "obs_output_path": g.output_path if g.owner == "rc" else None,
                "ownership_token": g.token,
                "game_time_offset_s": res["game_time_offset_s"],
                "alignment": {k: res[k] for k in ("proven", "method", "anchors")},
                "start_game_time_s": g.start_game_time,
                "wall": {"attach": g.attach_wall, "record_start": g.record_start_wall,
                         "record_stop": g.record_stop_wall, "game_end": g.game_end_wall},
                "stop_reason": stop_reason,
                "death_count": g.death_count,
                "bookmarks": bms,
                "diagnostics": dict(g.diag),
            }
        try:
            _atomic_write_json(self._sidecar_dir / f"{g.match_id}.json", body)
        except OSError as exc:
            _log.warning("OBS recorder sidecar write failed: %s", exc)

    # -- tick / loop -----------------------------------------------------------------

    async def tick(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            phase = self._phase
            info = dict(self._session_info)
            data = self._lc_data
            g = self._game
        if g is None:
            if phase != PHASE_IN_GAME or not isinstance(data, dict):
                return
            mid = _safe_match_id(info.get("game_id"), float(self._clock()))
            if info.get("game_id") is not None and mid in self._done:
                return
            if info.get("game_id") is None and self._done and "__nogid__" in self._done:
                return
            if info.get("game_id") is None:
                self._done.add("__nogid__")
            await self._begin(info, data)
            return
        await self._pump()
        if g.owner == "rc" and g.owned:
            await self._poll_status(g)
            await self._flush_chapters(g)
        reason = self._stop_reason(g)
        if reason:
            await self._finish(g, reason)

    # -- disk guard glue (its own producer; never touches the socket) ----------

    def ownership(self) -> tuple:
        with self._lock:
            g = self._game
            return (bool(g and g.owner == "rc" and g.owned), False)

    async def _guard_status(self) -> Optional[dict]:
        with self._lock:
            g = self._game
            return dict(g.last_status) if g and g.last_status else None

    def _guard_record_dir(self) -> Optional[str]:
        with self._lock:
            g = self._game
            return g.record_dir if g else None

    async def request_disk_stop(self, actions: dict) -> None:
        """Disk-guard stop hook. Only flags a stop for an RC-owned recording;
        the next tick sends StopRecord on the recorder's own coroutine."""
        if isinstance(actions, dict) and actions.get("stop_record") and self.ownership()[0]:
            self._disk_trip = True

    def make_disk_guard(self, **kw: Any) -> _dg.DiskGuard:
        return _dg.DiskGuard(status_fn=self._guard_status,
                             record_dir_fn=self._guard_record_dir,
                             ownership_fn=self.ownership,
                             stop_fn=self.request_disk_stop, **kw)

    def stop(self) -> None:
        self._stop.set()

    async def close(self) -> None:
        await self._drop_session()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001
                _log.warning("OBS recorder tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_s)
            except (asyncio.TimeoutError, TimeoutError):
                pass
        await self.close()


# -- production wiring -----------------------------------------------------------

_LCU_URIS = ("/lol-gameflow/v1/gameflow-phase", "/lol-gameflow/v1/session")
_LCU_RESCAN_S = 30.0

_recorder: Optional[ObsRecorder] = None
_handle: Any = None
_install_lock = threading.Lock()


def _lcu_credentials() -> Optional[tuple]:
    """(port, password) from the League lockfile, read only. Discovery paths
    and parsing are the frozen lcu/lcu_client.py's own (imported, not
    re-implemented, and its connect() is not called so its log state machine
    is untouched)."""
    try:
        from lcu.lcu_client import _LOCKFILE_PATHS, _parse_lockfile_fields
    except Exception:  # noqa: BLE001
        return None
    for lf in _LOCKFILE_PATHS:
        try:
            if lf.exists():
                return _parse_lockfile_fields(lf.read_text(encoding="utf-8"))
        except (OSError, IndexError, ValueError, UnicodeDecodeError):
            continue
    return None


async def _lcu_supervisor(rec: ObsRecorder) -> None:
    """Keep one core/lcu_events.py bus subscribed for the recorder,
    re-created when the lockfile credentials rotate."""
    from core.game_host import GAME_HOST
    from core.lcu_events import LcuEventBus
    bus = None
    task = None
    creds = None
    while not rec._stop.is_set():
        cur = _lcu_credentials()
        if cur != creds or (task is not None and task.done()):
            if bus is not None:
                bus.stop()
            bus, task, creds = None, None, cur
            if cur is not None:
                bus = LcuEventBus(GAME_HOST, cur[0], cur[1])
                bus.subscribe(_LCU_URIS[0], rec.on_gameflow_phase)
                bus.subscribe(_LCU_URIS[1], rec.on_gameflow_session)
                task = asyncio.ensure_future(bus.run())
        try:
            await asyncio.wait_for(rec._stop.wait(), timeout=_LCU_RESCAN_S)
        except (asyncio.TimeoutError, TimeoutError):
            pass
    if bus is not None:
        bus.stop()


async def _main(rec: ObsRecorder) -> None:
    guard = rec.make_disk_guard()
    try:
        await asyncio.gather(rec.run(), guard.run(), _lcu_supervisor(rec))
    finally:
        guard.stop()


def start_background(obs_cfg: Optional[dict] = None) -> bool:
    """Start the recorder if ``obs.record.enabled`` is true. Returns True when
    a recorder was started. Default OFF: returns False and does nothing."""
    global _recorder, _handle
    cfg = obs_cfg if obs_cfg is not None else _load_obs_config()
    if not record_enabled(cfg):
        return False
    with _install_lock:
        if _recorder is not None:
            return False
        rec = ObsRecorder(cfg)
        try:
            from core import liveclient_cache
            liveclient_cache.add_listener(rec.on_liveclient_snapshot)
        except Exception as exc:  # noqa: BLE001
            _log.warning("OBS recorder: liveclient listener failed: %s", exc)
            return False
        try:
            from app._loop import get_loop as _get_loop
            sched = _get_loop()
        except Exception:  # noqa: BLE001
            sched = None
        if sched is not None:
            _handle = sched.spawn_task(_main(rec))
        else:
            def _run() -> None:
                try:
                    asyncio.run(_main(rec))
                except Exception:  # noqa: BLE001
                    _log.exception("OBS recorder loop crashed")
            _handle = threading.Thread(target=_run, name="obs-recorder", daemon=True)
            _handle.start()
        _recorder = rec
    _log.info("OBS recorder enabled (sidecars -> %s)", DEFAULT_SIDECAR_DIR)
    return True


def install_if_enabled() -> bool:
    """Optional-tap entry point (core/liveclient_cache.py). Default OFF."""
    try:
        cfg = _load_obs_config()
        if not record_enabled(cfg):
            return False
        return bool(start_background(cfg))
    except Exception as exc:  # noqa: BLE001
        _log.debug("OBS recorder install failed: %s", exc)
        return False
