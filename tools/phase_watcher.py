"""phase_watcher.py - LCU WAMP push-event capture watcher.

Item 207 implementation of docs/_archive/LCU_PHASE_CAPTURE_WATCHER_PLAN.md.
Runs Legion-local (1-PC, ADR-011) alongside the LCU polling agent.
This file is event-driven: subscribes to LCU push events via WAMP-JSON v2
and fires DXGI capture on phase transitions. The polling agent stays as
the dashboard's primary state push; this watcher is additive.

Operator scope-fork answers (session 2026-05-27):
- Q1 capture target: BOTH monitors per event (game 1920x1080 + dashboard
  1920x1280; matched by RESOLUTION not index per
  reference_gamepc_monitor_index_volatility memory)
- Q2 debounce: 1 capture per (topic, sub_phase, queue_id) per gameflow
  cycle. reset_cycle() called on Lobby -> EndOfGame transition.
- Q3 frame format: JPEG q75 (inherits screen_agent.py contract)
- Q4 Cherry urgency: standard per-tuple debounce; operator can flip
  CHERRY_NO_DEBOUNCE = True later if they need every available[] change
  per Arena game.
  (The RC<->Peer cross-Claude bridge was decommissioned 2026-06-24; the
  former kind=ui_capture envelope emit is removed. Captures land via the
  /upload-frame vision pipeline + the JSON sidecar only.)

Deploy (one-time):
  1. Copy this file to C:\\RC-Agent\\
  2. $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m pip install websocket-client (optional; falls back to
     periodic re-poll if the WAMP socket import fails - the watcher
     stays alive but degrades to 5s polling cadence)
  3. $env:LOCALAPPDATA/Programs/Python/Python314/python.exe C:\\RC-Agent\\phase_watcher.py
  4. Register scheduled task via tools/phase_watcher_install.ps1
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# Vision-relay base. LOOPBACK by default (RM-150) - same reasoning as
# tools/lcu_agent.py and the tools/liveclient_relay._upload_url precedent:
# post-ADR-011 both ends are this machine, so the LAN hop bought nothing and a
# DHCP change would have killed the watcher silently under pythonw.
LEGION_VISION = os.environ.get("RC_VISION_BASE", "http://127.0.0.1:8889")
DEFAULT_TIMEOUT = 4.0


def _resolve_auth_token() -> str:
    env = os.environ.get("RC_VISION_TOKEN")
    if env:
        return env.strip()
    # RM-154: the canonical token is config/vision_token.txt (the same file
    # core.vision_token and the dashboard read). Only the tools-sibling copy
    # used to be searched, so an in-repo run resolved "" even with a valid
    # token on disk - which the new tokenless guard below would then read as
    # a genuine misconfiguration. The sibling stays first-class because the
    # deployed copy at C:\RC-Agent\ has no repo above it.
    _here = Path(__file__).resolve().parent
    for cfg in (_here.parent / "config" / "vision_token.txt",
                _here / "vision_token.txt"):
        try:
            if cfg.exists():
                line = cfg.read_text(encoding="utf-8").splitlines()[0].strip()
                if line:
                    return line
        except OSError:
            pass
    # Lane 8 audit 2026-08-03: a hardcoded 32-hex token used to be
    # returned here. It was DEAD (it did not match the live token) but
    # dashboard/routes_static.py serves this file's SOURCE at
    # /agent/phase_watcher.py with no auth on a "::" bind, so the literal was
    # published to the LAN and tailnet - and a missing config silently
    # produced a WRONG token, 401ing every request with no report.
    # Return "" so the caller can fail loudly. Never reintroduce it.
    return ""


AUTH_TOKEN = _resolve_auth_token()

LOCKFILE_PATHS = [
    Path(r"C:\Riot Games\League of Legends\lockfile"),
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"D:\Riot Games\League of Legends\lockfile"),
]

# Q3: inherit screen_agent.py JPEG q75 contract (plan said
# inherit; the plan doc cited q75 even though the screen agent's
# constant is 85 - the plan's intent is explicit q75 to keep
# event-capture payload smaller than per-2s polling payload).
USE_JPEG = True
JPEG_QUALITY = 75

# Q1: BOTH monitors captured per event. Indices may swap across reboots,
# so the helper classifies by RESOLUTION (1080 = game, 1280 = dashboard).
GAME_MONITOR_HEIGHT = 1080
DASH_MONITOR_HEIGHT = 1280

# On-demand DXGI capture only. The continuous screen-agent loop is
# retired in favor of the in-process self-grab relay (1-PC, ADR-011);
# the polling agent uses bettercam with explicit release and this watcher
# reuses that helper module on-demand only.
SUBSCRIBED_TOPICS = (
    "/lol-gameflow/v1/gameflow-phase",
    "/lol-champ-select/v1/session",
    "/lol-cherry-game-intra-event/v1/augments",
    "/lol-cherry-game-intra-event/v1/augment-select",
    "/lol-lobby/v2/lobby",
)

# Gameflow phases that trigger a capture. Other phases (Lobby /
# Matchmaking / ReadyCheck / EndOfGame / WaitingForStats / None) return
# None from the classifier - they're either captured via another topic
# (Lobby), uninteresting for UI audit (Matchmaking / ReadyCheck), or
# unreliable to capture (WaitingForStats fires at the game-end resolution
# swap, 1920x1080 <-> 1440p, so a DXGI grab there is unreliable).
# DO NOT re-add WaitingForStats. PGR captures must come from a trigger
# that fires AFTER the resolution swap settles (e.g. dashboard
# /api/state debounce), not from the WAMP edge.
_CAPTURED_GAMEFLOW_PHASES = frozenset({
    "ChampSelect", "InProgress",
})

# Delay (seconds) between the InProgress WAMP edge and the actual capture
# fire. The Matchmaking -> InProgress transition coincides with the game-
# start resolution swap (Windows native 1440p -> game 1920x1080), the same
# unreliable-capture window as the WaitingForStats game-end swap. Sleep
# past the swap before binding a DXGI surface. Tests monkey-patch to 0.
INPROGRESS_CAPTURE_DELAY_S = 15.0

# Cherry: if operator later wants every available[] transition captured
# (item 187 Slice C live verification), flip to True.
CHERRY_NO_DEBOUNCE = False

# WAMP reconnect ladder. A session has to SURVIVE STABLE_SESSION_SECONDS
# before the backoff returns to the floor: a handshake proves the port
# answered, not that the connection is usable, so resetting on connect alone
# pins a flapping socket at the floor forever and it never reaches the 30s
# cap. Same root cause as RM-348 in core/lcu_events.py, swept here with it.
BACKOFF_MIN_S = 1.0
STABLE_SESSION_SECONDS = 30.0

# RM-154. basicConfig without handlers= installs a StreamHandler on stderr,
# and the RC-PhaseWatcher task runs this under pythonw.exe where stderr is
# None - so every record this module emitted went nowhere. Pass explicit
# handlers. Precedent: tools/liveclient_relay.py:41-51.
_LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "phase_watcher.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(_LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("phase_watcher")

_ssl_ctx_lcu = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_ssl_ctx_lcu.check_hostname = False
_ssl_ctx_lcu.verify_mode = ssl.CERT_NONE

_lcu = {"port": None, "pwd": None}
_lcu_lock = threading.Lock()


# -- Lockfile (mirrors gamepc_lcu_agent.read_lockfile shape) ----------------

def read_lockfile() -> tuple[str | None, str | None]:
    for p in LOCKFILE_PATHS:
        if p.exists():
            try:
                parts = p.read_text(encoding="utf-8").strip().split(":")
                if len(parts) >= 5:
                    return parts[2], parts[3]
            except Exception:  # noqa: BLE001
                pass
    return None, None


def ensure_lcu() -> bool:
    port, pwd = read_lockfile()
    with _lcu_lock:
        if not port or not pwd:
            _lcu["port"] = _lcu["pwd"] = None
            return False
        if port != _lcu["port"] or pwd != _lcu["pwd"]:
            _lcu["port"] = port
            _lcu["pwd"] = pwd
            log.info("lockfile read; port=%s", port)
    return True


# -- WAMP-JSON v2 framing ---------------------------------------------------

def build_subscribe_frame(uri_path: str) -> str:
    """Build a WAMP-JSON v2 SUBSCRIBE frame.

    LCU expects ``[5, "OnJsonApiEvent_<uri-with-underscores>"]`` where the
    URI uses underscores instead of slashes. Strips any leading slash so
    both ``/lol-x/v1/y`` and ``lol-x/v1/y`` inputs work.
    """
    clean = uri_path.lstrip("/").replace("/", "_")
    return json.dumps([5, f"OnJsonApiEvent_{clean}"])


def parse_wamp_event(raw: str | bytes) -> tuple[str, str, object] | None:
    """Decode a WAMP-JSON v2 EVENT message.

    Returns (topic_with_slashes, event_type, data) or None when the
    message isn't a type-8 EVENT or fails JSON parse. Garbage in -> None
    out so the dispatcher stays alive on protocol drift.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not raw:
        return None
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(msg, list) or len(msg) < 3:
        return None
    if msg[0] != 8:
        return None
    payload = msg[2] if isinstance(msg[2], dict) else {}
    topic = payload.get("uri") or ""
    event_type = payload.get("eventType") or ""
    data = payload.get("data")
    return (topic, event_type, data)


# -- Classifiers per topic --------------------------------------------------

def classify_gameflow_phase(
        phase: str | None, *, queue_id: int | None,
) -> tuple[str, str, int | None] | None:
    if not isinstance(phase, str):
        return None
    if phase not in _CAPTURED_GAMEFLOW_PHASES:
        return None
    return ("gameflow_phase", phase, queue_id)


def classify_champ_select_session(
        payload: object, *, queue_id: int | None,
) -> tuple[str, str, int | None] | None:
    if not isinstance(payload, dict):
        return None
    timer = payload.get("timer")
    if not isinstance(timer, dict):
        return None
    phase = timer.get("phase")
    if phase in ("PLANNING", "BAN_PICK", "FINALIZATION"):
        return ("champ_select_session", phase, queue_id)
    return None


def classify_cherry_augments(
        payload: object, *, queue_id: int | None,
) -> tuple[str, str, int | None] | None:
    if not isinstance(payload, dict):
        return None
    available = payload.get("available")
    if not isinstance(available, list) or not available:
        return None
    return ("cherry_augments", "available", queue_id)


def classify_cherry_augment_select(
        payload: object, *, queue_id: int | None,
) -> tuple[str, str, int | None] | None:
    if not isinstance(payload, dict):
        return None
    # The augment-select endpoint emits on response of PATCH. Any non-
    # empty body confirms a selection landed.
    if not payload:
        return None
    return ("cherry_augment_select", "patched", queue_id)


def classify_lobby(
        payload: object, *, queue_id: int | None = None,
) -> tuple[str, str, int | None] | None:
    if not isinstance(payload, dict):
        return None
    cfg = payload.get("gameConfig")
    if not isinstance(cfg, dict):
        return None
    qid = cfg.get("queueId")
    if qid is None:
        return None
    try:
        qid_int = int(qid)
    except (TypeError, ValueError):
        return None
    return ("lobby", "joined", qid_int)


def dispatch_topic(
        topic: str, *, data: object, queue_id: int | None,
) -> tuple[str, str, int | None] | None:
    """Route topic -> classifier. Unknown topic returns None.

    Drift guard: a new topic the operator subscribes to but doesn't wire
    a classifier for is logged at DEBUG and silently dropped, not raised.
    """
    if topic == "/lol-gameflow/v1/gameflow-phase":
        return classify_gameflow_phase(data, queue_id=queue_id)
    if topic == "/lol-champ-select/v1/session":
        return classify_champ_select_session(data, queue_id=queue_id)
    if topic == "/lol-cherry-game-intra-event/v1/augments":
        return classify_cherry_augments(data, queue_id=queue_id)
    if topic == "/lol-cherry-game-intra-event/v1/augment-select":
        return classify_cherry_augment_select(data, queue_id=queue_id)
    if topic == "/lol-lobby/v2/lobby":
        return classify_lobby(data, queue_id=queue_id)
    return None


# -- Debounce gate ----------------------------------------------------------

class Debouncer:
    """1 capture per (topic, sub_phase, queue_id) tuple per gameflow
    cycle. reset_cycle() called on Lobby -> EndOfGame transition.
    """

    def __init__(self):
        self._fired: set[tuple[str, str, int | None]] = set()
        self._lock = threading.Lock()

    def should_fire(self, topic: str, sub_phase: str,
                    queue_id: int | None) -> bool:
        # Cherry override per scope-fork Q4 default: standard debounce.
        # If operator flips CHERRY_NO_DEBOUNCE later, augments topic
        # bypasses the gate entirely.
        if CHERRY_NO_DEBOUNCE and topic == "cherry_augments":
            return True
        key = (topic, sub_phase, queue_id)
        with self._lock:
            if key in self._fired:
                return False
            self._fired.add(key)
            return True

    def reset_cycle(self) -> None:
        with self._lock:
            self._fired.clear()


# -- DXGI capture (both monitors per Q1) -----------------------------------

def _capture_one_monitor(idx: int) -> tuple[str, str, int, int]:
    """Capture monitor at output index ``idx``. Returns (b64, fmt, w, h).

    Lifts the bettercam-or-degraded path from screen_agent.py.
    Kept as a thin wrapper here so tests can stub the import; live
    Legion deployment requires bettercam + PIL on the path.
    """
    # Import inline so tests can patch this function at the module level
    # without needing bettercam installed in the test environment.
    try:
        import bettercam  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            f"bettercam/PIL missing - cannot capture monitor {idx}: {exc}"
        ) from exc

    # Real implementation defers to bettercam.create(output_idx=idx).grab()
    # then PIL save to JPEG. Implemented in the live deployment path
    # only; the tests stub _capture_one_monitor entirely so this body
    # never runs in CI.
    from PIL import Image

    cam = bettercam.create(output_idx=idx, output_color="BGRA")
    try:
        frame = cam.grab()
        if frame is None:
            raise RuntimeError(f"monitor {idx} grab returned None")
        import numpy as np
        rgb = np.ascontiguousarray(frame[:, :, [2, 1, 0]])
        img = Image.fromarray(rgb, "RGB")
    finally:
        try:
            cam.release()
        except Exception:  # noqa: BLE001
            pass

    buf = io.BytesIO()
    if USE_JPEG:
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY,
                                optimize=True)
        fmt = "jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        fmt = "png"
    return (base64.b64encode(buf.getvalue()).decode("ascii"),
            fmt, img.width, img.height)


def _classify_monitor(width: int, height: int) -> str:
    """Map (w, h) -> 'game' or 'dashboard' by resolution per Q1 + the
    reference_gamepc_monitor_index_volatility memory. Falls back to
    'unknown' for unexpected resolutions so the upload still lands and
    the operator can grep for the orphan in sidecar JSON.
    """
    if height == GAME_MONITOR_HEIGHT:
        return "game"
    if height == DASH_MONITOR_HEIGHT:
        return "dashboard"
    return "unknown"


def capture_both_monitors() -> list[dict]:
    """Capture monitors 0 and 1 in sequence; return list of per-monitor
    dicts. Each dict has ``b64`` + ``format`` + ``width`` + ``height``
    + ``monitor`` (resolution-classified label). Failures per monitor
    log + skip; the other monitor still uploads.
    """
    out: list[dict] = []
    for idx in (0, 1):
        try:
            b64, fmt, w, h = _capture_one_monitor(idx)
        except Exception as exc:  # noqa: BLE001
            log.warning("capture monitor %d failed: %s", idx, exc)
            continue
        out.append({
            "b64": b64,
            "format": fmt,
            "width": w,
            "height": h,
            "monitor": _classify_monitor(w, h),
        })
    return out


# -- Upload + sidecar -------------------------------------------------------

def build_upload_payload(*, b64: str, fmt: str, w: int, h: int,
                         source: str, primary: bool,
                         event_meta: dict) -> dict:
    """Build /upload-frame body. Carries the standard frame fields plus
    ``event_meta`` so the Legion server can tag the frame as event-
    driven. Vision server's /upload-frame route accepts the field
    (backward-compatible; pre-extension uploads don't include it).
    """
    return {
        "image_b64": b64,
        "source": source,
        "width": w,
        "height": h,
        "format": fmt,
        "primary": primary,
        "event_meta": event_meta,
    }


def sidecar_filename(topic_or_short: str, sub_phase: str, queue_id: int | None,
                     captured_at_iso: str) -> str:
    qid = "none" if queue_id is None else str(queue_id)
    return f"{topic_or_short}_{sub_phase}_{qid}_{captured_at_iso}.json"


def write_sidecar(base_dir: Path, meta: dict, frame_meta: list[dict]) -> Path:
    """Write the JSON sidecar to ``base_dir`` (data/event_captures/).

    File contents = meta + ``frames`` list (per-monitor frame metadata,
    minus the b64 payload which lives in the vision server's frame
    cache). Atomic write via tmp + os.replace.
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    topic = meta.get("topic", "unknown")
    short = topic.lstrip("/").replace("/", "_")
    name = sidecar_filename(
        short, str(meta.get("sub_phase", "unknown")),
        meta.get("queue_id"),
        str(meta.get("captured_at", "now")).replace(":", "-"),
    )
    # The test passes the topic short-form already (e.g. "gameflow_phase");
    # detect that case and bypass the topic-derived prefix.
    if "/" not in topic and topic != "unknown":
        name = sidecar_filename(
            topic, str(meta.get("sub_phase", "unknown")),
            meta.get("queue_id"),
            str(meta.get("captured_at", "now")).replace(":", "-"),
        )
    path = base_dir / name
    body = dict(meta)
    body["frames"] = list(frame_meta)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=True, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def upload_event_frame(payload: dict, *,
                       timeout: float = DEFAULT_TIMEOUT) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{LEGION_VISION}/upload-frame", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-RC-Token": AUTH_TOKEN},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# -- Capture orchestration --------------------------------------------------

def handle_event(topic: str, data: object, queue_id: int | None, *,
                 debouncer: Debouncer,
                 sidecar_dir: Path) -> list[dict] | None:
    """End-to-end event handler. Returns the uploaded per-monitor frame
    metadata list on capture success or None when debounced / classifier
    returned None / no frames uploaded.
    """
    classified = dispatch_topic(topic, data=data, queue_id=queue_id)
    if classified is None:
        return None
    topic_short, sub_phase, qid = classified
    if not debouncer.should_fire(topic_short, sub_phase, qid):
        return None
    # InProgress edge coincides with the game-start resolution swap
    # (1440p -> game 1920x1080), so a DXGI grab there is unreliable. Sleep
    # past the swap before any DXGI bind. Other phases fire at stable
    # resolutions and need no delay.
    if topic_short == "gameflow_phase" and sub_phase == "InProgress":
        time.sleep(INPROGRESS_CAPTURE_DELAY_S)
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    captured_at_iso = captured_at.replace(":", "-")

    frames_meta: list[dict] = []
    monitors = capture_both_monitors()
    for m in monitors:
        source_label = f"game-pc-event-{m['monitor']}"
        meta = {
            "topic": topic,
            "sub_phase": sub_phase,
            "queue_id": qid,
            "captured_at": captured_at,
            "monitor": m["monitor"],
        }
        payload = build_upload_payload(
            b64=m["b64"], fmt=m["format"], w=m["width"], h=m["height"],
            source=source_label, primary=False, event_meta=meta,
        )
        try:
            upload_event_frame(payload)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            log.warning("upload monitor=%s failed: %s", m["monitor"], exc)
            continue
        frames_meta.append({
            "monitor": m["monitor"],
            "width": m["width"],
            "height": m["height"],
            "format": m["format"],
            "size": len(m["b64"]),
            "source": source_label,
        })

    if not frames_meta:
        log.warning("no frames uploaded for %s/%s; skipping sidecar",
                    topic_short, sub_phase)
        return None

    sidecar_meta = {
        "topic": topic,
        "sub_phase": sub_phase,
        "queue_id": qid,
        "captured_at": captured_at,
    }
    try:
        write_sidecar(sidecar_dir, sidecar_meta, frames_meta)
    except OSError as exc:
        log.warning("sidecar write failed: %s", exc)

    return frames_meta


# -- WAMP loop (live deployment) --------------------------------------------

def backoff_after_session(current: float, connected_at: float | None,
                          now: float) -> float:
    """Backoff to sleep after a WAMP session ended.

    Returns the floor only when the session actually LASTED
    ``STABLE_SESSION_SECONDS``; otherwise the caller's current backoff is
    handed back unchanged so the existing 1.5x escalation keeps climbing to
    the cap. ``connected_at`` is None when the handshake never completed.

    Split out of ``_wamp_loop`` because that loop is a live-deployment
    ``while True`` that tests bypass entirely, so the reconnect POLICY needs a
    seam of its own to be testable at all.
    """
    if connected_at is not None and (now - connected_at) >= STABLE_SESSION_SECONDS:
        return BACKOFF_MIN_S
    return current


def _wamp_loop(sidecar_dir: Path) -> None:
    """Connect to LCU WAMP socket + subscribe + dispatch events. Lives
    in the live deployment path only; tests bypass it entirely.

    Reconnect loop with exponential backoff capped at 30s per the plan's
    failure-modes table.
    """
    try:
        import websocket  # noqa: F401
    except ImportError:
        log.critical("websocket-client missing - install via "
                     "'$env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m pip install websocket-client'; degraded "
                     "to no-event mode (polling agent still alive)")
        return

    debouncer = Debouncer()
    backoff = BACKOFF_MIN_S

    while True:
        connected_at: float | None = None
        if not ensure_lcu():
            time.sleep(min(backoff, 10.0))
            backoff = min(backoff * 1.5, 30.0)
            continue

        port, pwd = _lcu["port"], _lcu["pwd"]
        auth = base64.b64encode(f"riot:{pwd}".encode()).decode()
        url = f"wss://127.0.0.1:{port}/"
        try:
            import websocket
            ws = websocket.WebSocket(
                sslopt={"cert_reqs": ssl.CERT_NONE,
                        "check_hostname": False},
            )
            ws.connect(
                url,
                header=[f"Authorization: Basic {auth}"],
                subprotocols=["wamp"],
            )
            for topic in SUBSCRIBED_TOPICS:
                ws.send(build_subscribe_frame(topic))
            log.info("WAMP connected; subscribed to %d topics",
                     len(SUBSCRIBED_TOPICS))
            connected_at = time.monotonic()

            while True:
                raw = ws.recv()
                parsed = parse_wamp_event(raw)
                if parsed is None:
                    continue
                topic, _event_type, data = parsed
                # Queue ID lookup is best-effort; the LCU push payload
                # for non-lobby topics often lacks queueId so we trust
                # the lobby cache.
                queue_id = _last_known_queue_id(topic, data)
                try:
                    handle_event(topic, data, queue_id,
                                 debouncer=debouncer,
                                 sidecar_dir=sidecar_dir)
                except Exception as exc:  # noqa: BLE001
                    log.warning("handle_event %s failed: %s", topic, exc)

                # Reset debouncer on EndOfGame so next cycle re-fires.
                if (topic == "/lol-gameflow/v1/gameflow-phase"
                        and data == "EndOfGame"):
                    debouncer.reset_cycle()
                    log.info("cycle reset on EndOfGame")
        except Exception as exc:  # noqa: BLE001
            backoff = backoff_after_session(backoff, connected_at, time.monotonic())
            log.warning("WAMP loop exited: %s; reconnecting in %.1fs",
                        exc, backoff)
            time.sleep(min(backoff, 30.0))
            backoff = min(backoff * 1.5, 30.0)


_last_queue_id_cache: dict = {"queue_id": None}


def _last_known_queue_id(topic: str, data: object) -> int | None:
    """Best-effort queue-id resolution. Lobby topic carries gameConfig.
    queueId explicitly; cache that for downstream topics in the same
    cycle.
    """
    if topic == "/lol-lobby/v2/lobby" and isinstance(data, dict):
        cfg = data.get("gameConfig")
        if isinstance(cfg, dict):
            qid = cfg.get("queueId")
            try:
                _last_queue_id_cache["queue_id"] = int(qid) if qid else None
            except (TypeError, ValueError):
                pass
    return _last_queue_id_cache.get("queue_id")


# -- Entrypoint -------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sidecar-dir", default=None,
                   help="Override sidecar destination (default: "
                        "<repo>/data/event_captures or "
                        "C:/RC-Agent/event_captures when deployed)")
    args = p.parse_args(argv)

    if args.sidecar_dir:
        sidecar_dir = Path(args.sidecar_dir)
    else:
        # Repo dev path; Legion deployment overrides via flag.
        sidecar_dir = (Path(__file__).resolve().parent.parent
                       / "data" / "event_captures")
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    log.info("sidecar dir: %s", sidecar_dir)
    log.info("subscribed topics: %s", list(SUBSCRIBED_TOPICS))

    try:
        _wamp_loop(sidecar_dir)
    except KeyboardInterrupt:
        log.info("interrupted - exiting")
        return 0
    return 0


if __name__ == "__main__":
    if not AUTH_TOKEN:
        # Exit non-zero so the scheduled task's Last Result is not a
        # reassuring 0 while every capture upload 401s.
        log.error("no vision token: set RC_VISION_TOKEN or create %s",
                  Path(__file__).resolve().parent.parent / "config" / "vision_token.txt")
        sys.exit(2)
    sys.exit(main())
