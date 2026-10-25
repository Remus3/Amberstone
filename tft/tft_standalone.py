# arch: standalone Unreal TFT client live source (no :2999) | section=tft | frozen=no
"""tft.tft_standalone - live source for the standalone Unreal TFT client.

Measured live 2026-10-25 (S134 P0; probe notes in the gitignored
ops/runtime/tft_qa/TFT_CLIENT_PROBE.md):

- TFT now runs as its own process ``TFTClient-Win64-Shipping.exe`` (Unreal,
  window class ``UnrealWindow``, title ``TFT``, borderless fullscreen), started
  by a ``TFTClient.exe`` launcher that the League client spawns.
- NOTHING listens on :2999. The game process owns no TCP listener at all (one
  UDP game socket), so the Riot Live Client API that every RC reader polls is
  simply absent for TFT. RC fell back to mode ``client`` and served Summoner's
  Rift callouts during the game.
- The LCU is still up: ``/lol-gameflow/v1/gameflow-phase`` reads
  ``InProgress`` and ``/lol-gameflow/v1/session`` carries the TFT queue.
- The client rewrites ``%LOCALAPPDATA%/TFT/Saved/Logs/TFTEoGStats.json`` once
  per round (observed at each planning phase: gameLengthSeconds 650 -> 828).
  It holds all 8 players: health, ffaStanding, boardPieces (unit, star level,
  items), and ``isInteractable`` marks the local player. That is a real,
  passive, per-round board feed - read-only, no injection, no network call.

This module turns those signals into an allgamedata-SHAPED dict so the
existing TFT pipeline (game_reader -> mode_router.tft_minimal_state ->
mode_from_game_mode_string -> TftWorker -> TftStateReader) runs unchanged,
with no frozen file touched. Every function is fail-soft: a probe error reads
as "no standalone game", never an exception into a poll loop.

Privacy: no Riot id, summoner name, puuid or account id leaves this module;
the local player is carried under the fixed token ``LOCAL_NAME``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

_log = logging.getLogger("rc.tft.standalone")

GAME_IMAGE = "tftclient-win64-shipping.exe"   # owns the "TFT" UnrealWindow
LAUNCHER_IMAGE = "tftclient.exe"              # windowless launcher
STANDALONE_IMAGES = frozenset({GAME_IMAGE, LAUNCHER_IMAGE})

SOURCE_TAG = "tft_standalone"
LOCAL_NAME = "__rc_local__"

# LCU gameflow phases during which a TFT match is actually being played.
IN_GAME_PHASES = frozenset({"GameStart", "InProgress", "Reconnect"})

# A round (planning + combat) is ~30-60 s and the carousel a little longer;
# 300 s tolerates a slow round or two without treating a finished game's file
# as live.
EOG_MAX_AGE_S = 300.0
_PROC_CACHE_TTL_S = 3.0
LCU_RELAY_URL = "http://127.0.0.1:8889/latest-lcu"
LCU_RELAY_MAX_AGE_S = 20.0

_cache_lock = threading.Lock()
_proc_cache: dict = {"ts": 0.0, "running": False, "create_time": None}


def _reset_caches_for_tests() -> None:
    with _cache_lock:
        _proc_cache.update({"ts": 0.0, "running": False, "create_time": None})


# -- process detection ---------------------------------------------------------

def _process_snapshot() -> dict:
    """Seam: ONE process-table walk -> {lower-cased image name: create time}.

    The only place this module touches the live process table (tests/conftest
    patches it to {} so no test can see the operator's real client).
    """
    import psutil
    out: dict = {}
    for p in psutil.process_iter(["name", "create_time"]):
        try:
            n = (p.info.get("name") or "").lower()
            ct = p.info.get("create_time")
        except Exception:  # noqa: BLE001
            continue
        if n:
            out[n] = float(ct) if ct else None
    return out


def _refresh_proc_cache() -> None:
    """Walk the process table at most once per ``_PROC_CACHE_TTL_S``."""
    now = time.monotonic()
    with _cache_lock:
        if now - _proc_cache["ts"] < _PROC_CACHE_TTL_S:
            return
    try:
        snap = _process_snapshot()
        running = GAME_IMAGE in snap
        create_time = snap.get(GAME_IMAGE) if running else None
    except Exception as exc:  # noqa: BLE001
        _log.debug("standalone TFT process probe failed: %s", exc)
        running, create_time = False, None
    with _cache_lock:
        _proc_cache.update({"ts": now, "running": running,
                            "create_time": create_time})


def _game_create_time() -> float | None:
    """Epoch create time of the TFT game process (from the cached walk)."""
    _refresh_proc_cache()
    with _cache_lock:
        return _proc_cache["create_time"]


def standalone_client_running(names=None) -> bool:
    """True when the standalone TFT game binary is running.

    Keys on the Unreal shipping binary only: the launcher alone owns no game
    window. ``names`` injects a process list (tests); otherwise one cached
    process walk serves ``_PROC_CACHE_TTL_S`` so the 2 Hz dashboard build does
    not walk the process table every tick. Callers gate on an in-game LCU
    phase (or a fresh per-round file) BEFORE asking, so idle and lobby ticks
    never walk it at all.
    """
    if names is not None:
        return any((n or "").lower() == GAME_IMAGE for n in names)
    _refresh_proc_cache()
    with _cache_lock:
        return bool(_proc_cache["running"])


# -- EoG per-round file ----------------------------------------------------------

def eog_stats_path() -> Path:
    """Seam: the per-round stats file the standalone client rewrites."""
    override = os.environ.get("RC_TFT_EOG_PATH", "").strip()
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA", "")
    return Path(base) / "TFT" / "Saved" / "Logs" / "TFTEoGStats.json"


def read_eog(now: float | None = None, max_age_s: float = EOG_MAX_AGE_S):
    """Return the parsed per-round file when it is FRESH and a TFT game,
    else None (missing, stale, unreadable, torn, non-TFT)."""
    now = time.time() if now is None else now
    try:
        p = eog_stats_path()
        st = p.stat()
        if now - st.st_mtime > max_age_s:
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(d, dict) or "TFT" not in str(d.get("gameMode") or ""):
        return None
    d["_mtime"] = st.st_mtime
    return d


_DA_PREFIX = re.compile(r"^DA_(?:\d+_)?")
_SET_SUFFIX = re.compile(r"\d+(?:_[A-Za-z0-9]+)?$")


def clean_unit_name(raw) -> str:
    """``DA_18_Yorick`` -> ``Yorick``; ``DA_Gromp18_AP`` -> ``Gromp``."""
    if not isinstance(raw, str) or not raw:
        return ""
    s = _DA_PREFIX.sub("", raw)
    s = _SET_SUFFIX.sub("", s)
    return s or raw


def _int(v, default=0) -> int:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f == f and abs(f) != float("inf") else default


def _board(pieces) -> list:
    out = []
    for pc in pieces if isinstance(pieces, list) else []:
        if not isinstance(pc, dict):
            continue
        name = clean_unit_name(pc.get("championName"))
        if not name:
            continue
        raw_items = pc.get("itemNames")
        items = ([i for i in raw_items if isinstance(i, str)]
                 if isinstance(raw_items, list) else [])
        out.append({"name": name, "star": _int(pc.get("starLevel"), 1),
                    "items": items})
    return out


def _players(eog: dict) -> list:
    sb = eog.get("statsBlock") if isinstance(eog, dict) else None
    pl = sb.get("players") if isinstance(sb, dict) else None
    return [p for p in pl if isinstance(p, dict)] if isinstance(pl, list) else []


# -- LCU (read-only, via the vision relay the LCU agent already feeds) ----------

def relay_lcu_snapshot():
    """Seam: the LCU agent snapshot cached on the vision server, or None when
    stale / unreachable. GET only, plain http + X-RC-Token (loopback)."""
    try:
        import urllib.request

        from core.relay_age import is_stale
        from core.vision_token import get_vision_token
        req = urllib.request.Request(
            LCU_RELAY_URL, headers={"X-RC-Token": get_vision_token()})
        with urllib.request.urlopen(req, timeout=1.0) as r:
            wrap = json.loads(r.read())
        if is_stale(wrap.get("ts", 0), LCU_RELAY_MAX_AGE_S):
            return None
        data = wrap.get("data")
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


_UNSET = object()


def lcu_tft_verdict(lcu):
    """What the LCU snapshot says about a live TFT match: True / False, or
    None when it cannot say (no snapshot / no phase).

    - A known phase outside ``IN_GAME_PHASES`` is False (lobby, champ select,
      end of game) so a client left open post-game never reads as live.
    - In game, the queue decides when the snapshot carries it:
      ``lcu/snapshot_shape.py`` stamps ``game_queue_mode`` / ``game_queue_id``
      from the gameflow session it already reads at GameStart / InProgress,
      so an SR / ARAM game can never read as TFT even if the TFT binary
      lingers. An older LCU agent omits both keys; the phase then stands.
    """
    if not isinstance(lcu, dict) or lcu.get("phase") is None:
        return None
    phase = str(lcu.get("phase") or "")
    if phase not in IN_GAME_PHASES:
        return False
    qmode = str(lcu.get("game_queue_mode") or "")
    if qmode:
        return "TFT" in qmode.upper()
    qid = lcu.get("game_queue_id")
    if qid:
        try:
            from core.queue_modes import mode_key_from_queue_id
            mk = mode_key_from_queue_id(qid)
        except Exception:  # noqa: BLE001
            mk = None
        if mk is not None:
            return mk == "tft"
    if phase == "Reconnect":
        # An LCU agent older than S134 stamps no queue (or game id) in
        # Reconnect: unknown, and the caller then requires a FRESH per-round
        # file (an SR / ARAM reconnect with a lingering TFT binary has none;
        # a TFT reconnect mid-match does). The current snapshot_shape stamps
        # the queue in Reconnect too, which the branches above decide.
        return None
    return True


def standalone_in_game(lcu, running=None, eog=_UNSET) -> bool:
    """True when the standalone TFT client is running AND a match is live.

    ``lcu`` is an LCU snapshot dict or None when the LCU is unavailable; see
    ``lcu_tft_verdict``. With no LCU at all, a FRESH per-round file is the
    confirmation. Cheapest checks first: the process walk runs only after the
    LCU (or the file) already says a TFT match is live.
    """
    verdict = lcu_tft_verdict(lcu)
    if verdict is False:
        return False
    if verdict is None:
        if eog is _UNSET:
            eog = read_eog()
        if eog is None:
            return False
        # A known LCU game id that the file does not carry = the file is an
        # earlier game's (e.g. an SR reconnect minutes after a TFT match).
        gid = str(lcu.get("game_id") or "") if isinstance(lcu, dict) else ""
        if gid and str(eog.get("gameId") or "") not in ("", gid):
            return False
    if running is None:
        running = standalone_client_running()
    return bool(running)


def _round_state(lcu, eog, now: float) -> dict:
    """The local player's round state from a fresh, same-game EoG file."""
    game_id = str((lcu or {}).get("game_id") or "") if isinstance(lcu, dict) else ""
    out = {"eog": False, "local": {}, "players_alive": None,
           "players_total": None, "game_length_s": None, "eog_age_s": None,
           "game_id": game_id, "queue_id": None, "set": None}
    if not isinstance(eog, dict):
        return out
    eog_gid = str(eog.get("gameId") or "")
    if game_id and eog_gid and eog_gid != game_id:
        return out  # a previous game's file: never mix its board in
    players = _players(eog)
    sb = eog.get("statsBlock") if isinstance(eog.get("statsBlock"), dict) else {}
    local = next((p for p in players if p.get("isInteractable") is True), None)
    out.update({
        "eog": True,
        "game_id": game_id or eog_gid,
        "queue_id": eog.get("queueId"),
        "set": sb.get("setCoreName"),
        "players_total": len(players),
        "players_alive": sum(1 for p in players if _int(p.get("health")) > 0),
        "game_length_s": _int(sb.get("gameLengthSeconds")),
        "eog_age_s": max(0.0, now - float(eog.get("_mtime") or now)),
    })
    if local is not None:
        out["local"] = {
            "health": _int(local.get("health"), 100),
            "standing": _int(local.get("ffaStanding")),
            "board": _board(local.get("boardPieces")),
        }
    return out


def synth_allgamedata(*, lcu=_UNSET, running=None, eog=_UNSET,
                      now: float | None = None):
    """An allgamedata-shaped dict for a live standalone TFT match, or None.

    Shape matches what the Live Client API would have served closely enough
    for ``snapshot_normalizer._process_game`` (TFT early exit) and
    ``TftStateReader._parse``; the RC-only ``rc_source`` / ``rc_standalone``
    keys carry the honest provenance (``live_api`` False). Never raises: a
    malformed per-round file or snapshot reads as "no standalone game".
    """
    try:
        return _synth_allgamedata(lcu=lcu, running=running, eog=eog, now=now)
    except Exception as exc:  # noqa: BLE001
        _log.debug("standalone TFT synth failed: %s", exc)
        return None


def _synth_allgamedata(*, lcu, running, eog, now):
    now = time.time() if now is None else now
    # Cheapest gates first: the SR/ARAM poller reaches this on every no-game
    # tick. An explicit running=False ends it; otherwise the loopback LCU
    # relay read (or, with no LCU, a stat of the per-round file) must say
    # "TFT match live" before the process table is walked at all.
    if running is False:
        return None
    if lcu is _UNSET:
        lcu = relay_lcu_snapshot()
    if lcu_tft_verdict(lcu) is False:
        return None
    if eog is _UNSET:
        eog = read_eog(now=now)
    if not standalone_in_game(lcu, running=running, eog=eog):
        return None
    rs = _round_state(lcu, eog, now)
    if rs["eog"] and rs["game_length_s"] is not None:
        game_time = float(rs["game_length_s"]) + float(rs["eog_age_s"] or 0.0)
    else:
        ct = _game_create_time()
        game_time = max(0.0, now - ct) if ct else 0.0
    players = []
    if rs["eog"]:
        for i, p in enumerate(_players(eog) if isinstance(eog, dict) else []):
            hp = _int(p.get("health"))
            players.append({
                "summonerName": LOCAL_NAME if p.get("isInteractable") is True
                else f"opponent-{i}",
                "health": hp,
                "isDead": hp <= 0,
                "scores": {"kills": 0, "deaths": 0},
                "items": [],
            })
    st = dict(rs)
    st["live_api"] = False
    active = {"summonerName": LOCAL_NAME}
    if rs["local"]:
        # read by mode_router.tft_minimal_state (hp_pct) on the poller path
        active["currentHP"] = rs["local"]["health"]
    return {
        "gameData": {"gameMode": "TFT", "gameTime": round(game_time, 1),
                     "mapName": "", "mapNumber": 0, "mapTerrain": "",
                     "queueId": rs["queue_id"]},
        "activePlayer": active,
        "allPlayers": players,
        "events": {"Events": []},
        "rc_source": SOURCE_TAG,
        "rc_standalone": st,
    }


# -- dashboard helpers -------------------------------------------------------------

def _clock(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60}:{t % 60:02d}"


def standalone_liveclient_summary(lcu, running=None, eog=_UNSET) -> dict:
    """A small, honest liveclient-style summary for /api/state while the
    standalone client is live, else {}. Deliberately carries no ``champion``
    (an SR consumer must not read TFT as a Rift champion)."""
    raw = synth_allgamedata(lcu=lcu, running=running, eog=eog)
    if raw is None:
        return {}
    return _summary_from_raw(raw)


def _summary_from_raw(raw: dict) -> dict:
    st = raw["rc_standalone"]
    gt = float(raw["gameData"]["gameTime"] or 0.0)
    out = {"game_mode": "TFT", "source": SOURCE_TAG, "live_api": False,
           "game_time_s": gt, "game_time": _clock(gt),
           "game_id": st.get("game_id") or ""}
    local = st.get("local") or {}
    if local:
        board = local.get("board") or []
        out["hp"] = local.get("health")
        out["standing"] = local.get("standing")
        out["board_size"] = len(board)
        if board:
            out["board_str"] = ", ".join(
                f"{u.get('name')}*{u.get('star', 1)}" for u in board)
    if st.get("players_alive") is not None:
        out["players_alive"] = st["players_alive"]
    return out


def tft_live_status(lcu, running=None, live_api: bool = False,
                    eog=_UNSET) -> dict:
    """Which TFT live source is in play, with one honest display line."""
    if live_api:
        return {"source": "live_client", "live_api": True, "eog": False,
                "line": "TFT: Live Client API connected."}
    # standalone_in_game checks the LCU phase / queue BEFORE any process walk,
    # so a TFT lobby (mode_key pre-flipped to tft) never scans.
    if not standalone_in_game(lcu, running=running, eog=eog):
        return {"source": "none", "live_api": False, "eog": False,
                "line": "TFT: no live data source."}
    if eog is _UNSET:
        eog = read_eog()
    has_eog = _round_state(lcu, eog, time.time())["eog"]
    line = ("TFT standalone client: no Live Client API - vision only, "
            "board/HP from the per-round stats file."
            if has_eog else
            "TFT standalone client: live data unavailable - vision only.")
    return {"source": SOURCE_TAG, "live_api": False, "eog": has_eog,
            "line": line}
