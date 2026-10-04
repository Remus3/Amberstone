"""
core/live_session_recorder.py - RM-605 / X-05 (external reference F, clean-room).

Records normalized Live Client (:2999 /allgamedata, as relayed through
core/liveclient_cache.py) snapshots, plus data/vision_state.json when it is
fresh, to ``logs/sessions/<gameId>.jsonl`` so a real match can be replayed
later through tools/replay_session.py (headless UI work, fixtures, PGR
development without a live game).

Flag
----
DEFAULT OFF. Enabled only when the environment variable ``RC_SESSION_RECORDER``
is truthy ("1" / "true" / "yes" / "on"), the same house pattern as
``RC_CAPGAP_SHADOW`` / ``RC_RANK_TIER_LIVE``. When off, no listener is
installed and nothing is written.

File format (schema is a SINGLE INTEGER, ``SCHEMA_VERSION``)
------------------------------------------------------------
  line 1   {"kind":"header","schema":1,"config_key":..,"patch":..,
            "ENGINE_VERSION":..,"mode_key":..}
  line 2+  {"kind":"frame","seq":N,"captured_at":unix_s,"game_time":s|null,
            "source_ts":unix_s(optional),"snapshot":{...},
            "vision_state":{...}(optional)}

  - The header describes the CAPTURE CONFIG, never results: it is built from
    an allowlist (``HEADER_KEYS``) so a result-shaped field cannot leak in.
  - Adding an OPTIONAL field needs no schema bump. Removing or repurposing a
    field DOES. Readers (``read_session``) reject a schema newer than they
    understand (``SchemaTooNewError``) and a non-integer schema.
  - Captured payloads name other players: ``logs/`` is gitignored
    (.gitignore ``logs/``), so recordings never enter the public tree.

Single writer
-------------
Windows does not make O_APPEND writes atomic across handles, so many threads
appending to one file can interleave bytes. ``record()`` only serializes the
snapshot (in the caller's thread, so later caller mutation cannot change what
was captured) and enqueues it. ONE daemon thread (``WRITER_THREAD_NAME``) owns
every file handle, resolves the game id, builds the header and writes whole
lines. The log is append-only by nature, so the tmp+replace atomic-write rule
for runtime state files does not apply; each line is written whole and
flushed, and ``read_session`` tolerates only a torn FINAL line (crash mid-write).

Wiring
------
``install_if_enabled()`` registers ``on_liveclient_snapshot`` on
``core.liveclient_cache.add_listener`` (core/liveclient_cache.py:118, the same
tap core/ward_producer.py:359 uses). It is called from
``core.liveclient_cache.start()`` via ``_install_optional_taps()``, so no
frozen file (main.py) and neither game_reader/poller.py nor
dashboard/_liveclient.py is touched.

Numeric constants here are our own choices, not measurements from any
external source: see the comment on each.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

_log = logging.getLogger("rc.live_session_recorder")

SCHEMA_VERSION = 1
FLAG_ENV = "RC_SESSION_RECORDER"
WRITER_THREAD_NAME = "rc-session-recorder-writer"

_PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SESSIONS_DIR = _PROJECT_DIR / "logs" / "sessions"
_VISION_STATE_PATH = _PROJECT_DIR / "data" / "vision_state.json"
_DS_INIT_PATH = _PROJECT_DIR / "agents" / "daemon_slayer" / "__init__.py"
_DS_PATCH_PATH = _PROJECT_DIR / "data" / "daemon_slayer" / "current.txt"
_LCU_RELAY_URL = "http://127.0.0.1:8889/latest-lcu"

HEADER_KEYS = ("config_key", "patch", "ENGINE_VERSION", "mode_key")

_TRUTHY = ("1", "true", "yes", "on")

# Our choice: a gameTime fall larger than this means a NEW game started without
# a no-game gap in between (the relay can skip the 404 window between games).
# Small backwards wobble from relay reordering stays inside one session.
_REWIND_NEW_SESSION_S = 5.0

# Our choice: vision_state.json is attached only if written within this many
# seconds of the frame, so a stale file from a previous game is never stamped
# onto a new one. vision_tracker writes it on its own cadence (seconds).
_VISION_FRESH_S = 10.0

# Our choice: bounded queue so a wedged disk cannot grow memory without limit
# (0.5s poll -> 4096 frames is ~34 minutes of backlog). Overflow drops frames.
_QUEUE_MAX = 4096

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SessionFormatError(ValueError):
    """The file is not a well-formed session recording."""


class SchemaTooNewError(SessionFormatError):
    """The file's schema integer is newer than this reader understands."""


# -- flag -------------------------------------------------------------------

def is_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(FLAG_ENV, "0")).strip().lower() in _TRUTHY


# -- header -----------------------------------------------------------------

def build_header(fields: Mapping[str, Any]) -> Dict[str, Any]:
    """Header from an ALLOWLIST of capture-config keys. Never results."""
    header: Dict[str, Any] = {"kind": "header", "schema": SCHEMA_VERSION}
    for k in HEADER_KEYS:
        v = fields.get(k) if isinstance(fields, Mapping) else None
        header[k] = v if isinstance(v, (str, int, float)) and not isinstance(v, bool) else None
    return header


def _engine_version() -> Optional[str]:
    # Regex-read instead of importing the DS package into the live process.
    try:
        text = _DS_INIT_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r'^ENGINE_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return m.group(1) if m else None


def _patch() -> Optional[str]:
    try:
        val = _DS_PATCH_PATH.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:  # noqa: BLE001
        return None
    return val or None


def _config_key() -> str:
    try:
        from core.hud_settings import read_hud_settings
        return str(read_hud_settings().get("config_key") or "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def _mode_key(snapshot: Any) -> Optional[str]:
    try:
        gm = (snapshot.get("gameData") or {}).get("gameMode")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(gm, str) or not gm:
        return None
    try:
        from core.game_snapshot import mode_from_game_mode_string
        return mode_from_game_mode_string(gm).lower()
    except Exception:  # noqa: BLE001
        return None


def default_header_fields(snapshot: Any) -> Dict[str, Any]:
    return {
        "config_key": _config_key(),
        "patch": _patch(),
        "ENGINE_VERSION": _engine_version(),
        "mode_key": _mode_key(snapshot),
    }


# -- providers --------------------------------------------------------------

def default_game_id_provider() -> str:
    """gameId from the LCU relay on the vision server, '' when unknown."""
    try:
        from urllib.request import Request, urlopen
        from core.vision_token import get_vision_token
        req = Request(_LCU_RELAY_URL, headers={"X-RC-Token": get_vision_token()})
        with urlopen(req, timeout=1.0) as r:
            wrap = json.loads(r.read())
        return str(((wrap or {}).get("data") or {}).get("game_id") or "")
    except Exception:  # noqa: BLE001
        return ""


def default_vision_provider() -> Optional[dict]:
    try:
        st = _VISION_STATE_PATH.stat()
        if time.time() - st.st_mtime > _VISION_FRESH_S:
            return None
        data = json.loads(_VISION_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def _game_time(snapshot: Any) -> Optional[float]:
    try:
        gt = (snapshot.get("gameData") or {}).get("gameTime")
    except Exception:  # noqa: BLE001
        return None
    if isinstance(gt, bool) or not isinstance(gt, (int, float)):
        return None
    return float(gt)


def _open_append(path: Path):
    return open(path, "a", encoding="utf-8", newline="\n")


# -- recorder ---------------------------------------------------------------

_END = object()
_FLUSH = object()
_STOP = object()


class LiveSessionRecorder:
    """Thread-safe front end; one writer thread owns all file I/O."""

    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        *,
        header_fields: Optional[Callable[[Any], Mapping[str, Any]]] = None,
        game_id_provider: Optional[Callable[[], str]] = None,
        vision_provider: Optional[Callable[[], Optional[dict]]] = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._dir = Path(sessions_dir) if sessions_dir is not None else DEFAULT_SESSIONS_DIR
        self._header_fields = header_fields or default_header_fields
        self._game_id_provider = game_id_provider or default_game_id_provider
        self._vision_provider = vision_provider or default_vision_provider
        self._wall_clock = wall_clock
        self._q: "queue.Queue[Any]" = queue.Queue(maxsize=_QUEUE_MAX)
        self._clock_lock = threading.Lock()
        self._dropped = 0
        # Writer-thread-only state below.
        self._fh = None
        self._seq = 0
        self._last_game_time: Optional[float] = None
        self._thread = threading.Thread(
            target=self._run, name=WRITER_THREAD_NAME, daemon=True)
        self._thread.start()

    # public API (any thread) ------------------------------------------------

    def record(self, snapshot: Any, ts: Optional[float] = None) -> bool:
        """Enqueue one normalized snapshot. ``None`` ends the session."""
        if snapshot is None:
            self.end_session()
            return False
        try:
            snap_json = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            _log.debug("session recorder: unserializable snapshot dropped: %s", exc)
            return False
        with self._clock_lock:
            captured_at = float(self._wall_clock())
        item = (snap_json, _game_time(snapshot), captured_at, ts, snapshot)
        try:
            self._q.put_nowait(item)
        except queue.Full:
            self._dropped += 1
            return False
        return True

    def end_session(self) -> None:
        try:
            self._q.put_nowait(_END)
        except queue.Full:
            pass

    def flush(self, timeout: float = 10.0) -> bool:
        ev = threading.Event()
        self._q.put((_FLUSH, ev))
        return ev.wait(timeout)

    def close(self, timeout: float = 10.0) -> None:
        if self._thread.is_alive():
            self._q.put(_STOP)
            self._thread.join(timeout)

    @property
    def dropped(self) -> int:
        return self._dropped

    # writer thread ----------------------------------------------------------

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is _STOP:
                    self._close_file()
                    return
                if item is _END:
                    self._close_file()
                    continue
                if isinstance(item, tuple) and item and item[0] is _FLUSH:
                    if self._fh is not None:
                        self._fh.flush()
                    item[1].set()
                    continue
                self._write_frame(*item)
            except Exception as exc:  # noqa: BLE001
                _log.warning("session recorder writer: %s", exc)

    def _close_file(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
        self._fh = None
        self._seq = 0
        self._last_game_time = None

    def _start_session(self, snapshot: Any, captured_at: float) -> None:
        gid = ""
        try:
            gid = str(self._game_id_provider() or "")
        except Exception:  # noqa: BLE001
            gid = ""
        if not _SAFE_ID.match(gid):
            gid = f"nogameid-{int(captured_at)}"
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / (gid + ".jsonl")
        fh = _open_append(path)
        try:
            fields = self._header_fields(snapshot)
        except Exception:  # noqa: BLE001
            fields = {}
        if fh.tell() == 0:
            fh.write(json.dumps(build_header(fields), separators=(",", ":")) + "\n")
        self._fh = fh
        self._seq = 0

    def _write_frame(self, snap_json: str, game_time: Optional[float],
                     captured_at: float, ts: Optional[float], snapshot: Any) -> None:
        if (self._fh is not None and game_time is not None
                and self._last_game_time is not None
                and game_time < self._last_game_time - _REWIND_NEW_SESSION_S):
            self._close_file()
        if self._fh is None:
            self._start_session(snapshot, captured_at)
        if game_time is not None:
            self._last_game_time = game_time
        meta: Dict[str, Any] = {
            "kind": "frame", "seq": self._seq,
            "captured_at": captured_at, "game_time": game_time,
        }
        if isinstance(ts, (int, float)) and not isinstance(ts, bool):
            meta["source_ts"] = float(ts)
        line = json.dumps(meta, separators=(",", ":"))[:-1] + ',"snapshot":' + snap_json
        vision = None
        try:
            vision = self._vision_provider()
        except Exception:  # noqa: BLE001
            vision = None
        if isinstance(vision, dict):
            try:
                line += ',"vision_state":' + json.dumps(
                    vision, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                pass
        self._fh.write(line + "}\n")
        self._fh.flush()
        self._seq += 1


# -- reader -----------------------------------------------------------------

def read_session(path: Path, max_schema: int = SCHEMA_VERSION
                 ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return (header, frames). Rejects a newer or non-integer schema."""
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise SessionFormatError("empty session file")
    try:
        header = json.loads(lines[0])
    except ValueError as exc:
        raise SessionFormatError(f"header is not JSON: {exc}") from None
    if not isinstance(header, dict) or header.get("kind") != "header":
        raise SessionFormatError("first line is not a header")
    schema = header.get("schema")
    if type(schema) is not int:
        raise SessionFormatError(f"schema must be an integer, got {schema!r}")
    if schema > max_schema:
        raise SchemaTooNewError(
            f"session schema {schema} is newer than supported {max_schema}")
    frames: List[Dict[str, Any]] = []
    last = len(lines) - 1
    for i, raw in enumerate(lines[1:], start=1):
        try:
            obj = json.loads(raw)
        except ValueError:
            if i == last:
                break  # torn final line from a crash mid-write
            raise SessionFormatError(f"line {i + 1} is not JSON") from None
        if isinstance(obj, dict) and obj.get("kind") == "frame":
            frames.append(obj)
    return header, frames


# -- live wiring ------------------------------------------------------------

_recorder: Optional[LiveSessionRecorder] = None
_recorder_lock = threading.Lock()
_installed = False


def get_recorder() -> LiveSessionRecorder:
    global _recorder
    with _recorder_lock:
        if _recorder is None:
            _recorder = LiveSessionRecorder()
        return _recorder


def on_liveclient_snapshot(snap: Any) -> None:
    """liveclient_cache listener. Cheap and fail-soft; flag re-checked per call."""
    if not is_enabled():
        return
    data = getattr(snap, "data", None)
    rec = get_recorder()
    if data is None:
        if getattr(snap, "no_game", False):
            rec.end_session()
        return
    rec.record(data, ts=getattr(snap, "ts", None))


def install_if_enabled() -> bool:
    """Register the listener once, only when the flag is on."""
    global _installed
    if not is_enabled():
        return False
    with _recorder_lock:
        if _installed:
            return False
        try:
            from core import liveclient_cache
            liveclient_cache.add_listener(on_liveclient_snapshot)
        except Exception as exc:  # noqa: BLE001
            _log.warning("session recorder install failed: %s", exc)
            return False
        _installed = True
    _log.info("live session recorder enabled -> %s", DEFAULT_SESSIONS_DIR)
    return True


def _set_recorder_for_tests(rec: Optional[LiveSessionRecorder]) -> None:
    global _recorder
    with _recorder_lock:
        _recorder = rec


def _reset_for_tests() -> None:
    global _recorder, _installed
    with _recorder_lock:
        old = _recorder
        _recorder = None
        _installed = False
    if old is not None:
        old.close()
