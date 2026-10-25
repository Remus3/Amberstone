"""Focus board live adapter (RM-844): the live roster scored by the DS focus board.

PURPOSE
    Map the dashboard's Live Client summary (``liveclient_summary()`` in
    ``dashboard/_liveclient.py``) to the ``(champion_id, level, item_ids)``
    fighters that ``agents.daemon_slayer.focus_board.compute_focus_board``
    takes (RM-841), call it IN-PROCESS (no HTTP; the ``/focus-board`` route is
    RM-843), and return a small JSON-able result. SHADOW-ONLY: the one
    consumer is ``core.arena_coach_shadow`` (a jsonl column). Nothing here
    reaches a served field, and the existing ``target_priority`` rule stays
    authoritative.

WHICH LIST (the RM-844 "per-enemy level missing" block, re-measured)
    ``lc["players"]`` (``out["players"]``) carries position / team /
    creep_score / is_active only. ``lc["allPlayers"]`` (``_lean_roster``)
    carries ``championName`` / ``rawChampionName`` / ``team`` / ``level`` /
    ``items`` (``itemID``) for every player, and ``lc["activePlayer"]`` the
    identity used to find me. This module reads ``allPlayers``. My own level
    prefers ``lc["level"]`` (the activePlayer level); ``_lean_roster`` turns a
    missing level into 0, which is read as "no level" (the board then skips
    that fighter with a note) rather than a fabricated level 1.

CHAMPION IDS
    The board takes snapshot ids ("MonkeyKing", "Kaisa"); the Live Client
    gives display names ("Wukong", "Kai'Sa") plus ``rawChampionName``
    ("game_character_displayname_MonkeyKing"). First hit wins: the raw name
    (prefix stripped), then the display name, each matched case- and
    punctuation-insensitively against the snapshot's ids and names. An
    unresolved name passes through unchanged, so the board's own "unknown
    champion id" note names it and skips that fighter.

TEAMS
    Allies = my ``team`` minus me; enemies = every other non-blank team. In
    Arena that makes my partner the one ally, so ``team_ttk_s`` is the 2v2
    team TTK (the focus_board docstring: "pass the partner as the one ally").
    The team spelling is read from the frame, never assumed. NOT live-verified
    yet: the gated GATE 5 row owns that.

COST (measured 2026-10-24 on Legion)
    DS import about 0.35 s once, snapshot load about 0.04 s, a 10-enemy board
    about 7 ms warm (about 50 ms on the first call). So:
    * the engine loads on a daemon thread; until it is up a call returns
      ``warming`` at once, and the cold import never lands on the caller;
    * a board is cached per roster signature (the same inputs give the same
      board), and a NEW compute happens at most once per
      ``MIN_COMPUTE_INTERVAL_S``; inside that window a changed roster returns
      ``throttled``.

OFF THE STATE THREAD (RM-854)
    ``board_for_lc(..., background=True)`` is the state-builder read (the
    shadow calls it from ``dashboard/_state_builder.py`` via
    ``shadow_log_arena_coach``): it maps the roster (cheap), returns a cached
    board on a hit, and on a miss hands the roster to ONE daemon worker
    (``WORKER_THREAD_NAME``) and returns ``pending`` at once - it never
    computes and never waits. The worker's queue is one slot: a newer roster
    replaces a queued one (latest wins), so it can never grow. The throttle
    still caps the worker at one compute per ``MIN_COMPUTE_INTERVAL_S``; the
    worker waits a throttled job out instead of dropping it, so a background
    read never sees ``throttled``. A worker failure is logged and cached as an
    ``error`` board for that roster (never re-tried per tick, never raised);
    the kill switch drops a queued job. ``prefetch`` is the same read without
    a result (the shadow's dedup ticks feed the worker the latest roster, so
    the next written row usually finds its board ready). The default
    ``board_for_lc`` (``background=False``) is the old synchronous compute.
    ``TRANSIENT_STATUSES`` (warming / throttled / pending) are the not-yet-
    ready answers the shadow re-logs once (``core.arena_coach_shadow``).

NO ARAM ``fight_rule`` COLUMN (RM-854 c, decided 2026-10-25: NOT BUILT)
    ARAM ``fight_rule`` comes from ``core.aram_fight_risk`` over the enemy-CC
    threat line (``core.enemy_cc_threat_context.enemy_cc_threat_line``, ranked
    by total CC seconds): it names a CC threat, not a target. The board has no
    CC axis - ``kill_order`` is by focus value (my TTK), ``danger_order`` by
    their TTK on me - so any comparison (e.g. the board's rank of the named
    threat) sets a CC ranking against a damage ranking, and a disagreement
    would say nothing about whether the rule is right; such a column could
    never inform a flip. The Arena column it would copy is not live-verified
    yet either (GATE 5). Reverses if: the board gains a per-enemy CC /
    lockdown term, or ARAM gains a target-naming rule (a ``target_priority``
    analogue) to compare against.

DEGRADE (never raises; every no-board result carries a note)
    No roster / me not found -> ``no_roster`` (checked BEFORE the engine is
    touched). DS import or load failure -> ``unavailable``, retried after
    ``ENGINE_RETRY_S`` and warned once per failure streak (FailedLoadGate). My
    champion unresolved, every enemy skipped, or the engine raising ->
    ``no_board``, logged once per roster (the result is cached). Notes never
    carry exception text (RM-835), only the class name. Kill switch:
    ``RC_FOCUS_BOARD_SHADOW=0`` -> ``disabled``.
"""

from __future__ import annotations

import copy
import logging
import math
import os
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from core.failed_load_gate import FailedLoadGate

log = logging.getLogger("rc.focus_board_live")

KILL_SWITCH_ENV = "RC_FOCUS_BOARD_SHADOW"
MIN_COMPUTE_INTERVAL_S = 2.0
ENGINE_RETRY_S = 60.0
_CACHE_MAX = 8

STATUS_OK = "ok"
STATUS_NO_ROSTER = "no_roster"
STATUS_NO_BOARD = "no_board"
STATUS_WARMING = "warming"
STATUS_UNAVAILABLE = "unavailable"
STATUS_THROTTLED = "throttled"
STATUS_DISABLED = "disabled"
STATUS_ERROR = "error"
STATUS_PENDING = "pending"

# RM-854: the answers that mean "no board YET" (a later tick can have one).
TRANSIENT_STATUSES = frozenset({STATUS_WARMING, STATUS_THROTTLED, STATUS_PENDING})

WORKER_THREAD_NAME = "rc-focus-board-worker"

_RAW_PREFIX = "game_character_displayname_"
_MODE_BY_KEY = {"arena": "ARENA", "aram": "ARAM", "sr": "SR"}
# Per-row fields kept in the result (the full FocusRow is wider; the shadow
# row only needs what the ordering was computed from).
_ROW_FIELDS = (
    "champion_id", "level", "my_ttk_s", "team_ttk_s", "their_ttk_on_me_s",
    "combo_lethal_hp_pct", "focus_value",
)

# A fighter as compute_focus_board takes it: (champion_id, level, item_ids).
Fighter = tuple


@dataclass(frozen=True)
class LiveRoster:
    """The live roster as focus-board fighters (hashable: it is the cache key)."""

    me: Fighter
    allies: tuple
    enemies: tuple


def enabled() -> bool:
    """False only when ``RC_FOCUS_BOARD_SHADOW`` is ``0``."""
    return os.environ.get(KILL_SWITCH_ENV, "1").strip() != "0"


# -- mapping ------------------------------------------------------------------

def _norm(text: Any) -> str:
    """Case- and punctuation-insensitive key ("Kai'Sa" -> "kaisa")."""
    if not isinstance(text, str):
        return ""
    return "".join(ch for ch in text.casefold() if ch.isalnum())


_INDEX_LOCK = threading.Lock()
_INDEX: Optional[tuple] = None  # (champions mapping, {norm key: champion id})


def _champion_index(champions: Mapping[str, Any]) -> dict:
    """norm(id) and norm(name) -> snapshot id, built once per snapshot."""
    global _INDEX
    with _INDEX_LOCK:
        if _INDEX is not None and _INDEX[0] is champions:
            return _INDEX[1]
    idx: dict = {}
    for cid, rec in champions.items():
        if not isinstance(cid, str) or not cid:
            continue
        idx.setdefault(_norm(cid), cid)
        name = rec.get("name") if isinstance(rec, dict) else None
        if isinstance(name, str) and name:
            idx.setdefault(_norm(name), cid)
    idx.pop("", None)
    with _INDEX_LOCK:
        _INDEX = (champions, idx)
    return idx


def resolve_champion_id(player: Mapping[str, Any], champions: Mapping[str, Any]) -> str:
    """Snapshot champion id for one roster entry; the raw name if unresolved."""
    idx = _champion_index(champions)
    raw = player.get("rawChampionName")
    raw_s = raw.strip() if isinstance(raw, str) else ""
    if raw_s.lower().startswith(_RAW_PREFIX):
        raw_s = raw_s[len(_RAW_PREFIX):]
    name = player.get("championName")
    name_s = name.strip() if isinstance(name, str) else ""
    for cand in (raw_s, name_s):
        hit = idx.get(_norm(cand))
        if hit:
            return hit
    return name_s or raw_s


def _level(value: Any) -> Optional[int]:
    """A usable level (>= 1), or None. ``_lean_roster`` reads a missing
    level as 0, so 0 is "no level", never a fabricated level 1."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float) and math.isfinite(value) and value >= 1:
        return int(value)
    return None


def _non_inventory_ids() -> frozenset:
    """The shared trinket / consumable set (``liveclient_summary`` filters my
    own ids with it). Fail-soft: an import failure filters nothing."""
    try:
        from core.daemon_slayer_resolver import NON_INVENTORY_IDS  # lazy
        return frozenset(NON_INVENTORY_IDS)
    except Exception:  # noqa: BLE001 - fail-soft: keep every id
        return frozenset()


def _item_ids(player: Mapping[str, Any], skip: frozenset) -> tuple:
    items = player.get("items")
    if not isinstance(items, list):
        return ()
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = it.get("itemID")
        if iid is None or isinstance(iid, bool):
            continue
        key = str(iid).strip()
        if key and key != "0" and key not in skip:
            out.append(key)
    return tuple(out)


def _team(player: Mapping[str, Any]) -> str:
    team = player.get("team")
    if team is None or isinstance(team, bool):
        return ""
    return str(team).strip()


def _find_me(players: list, lc: Mapping[str, Any]) -> Optional[int]:
    """Index of my roster entry: activePlayer identity (full Riot id first,
    then the game-name part), else a unique ``championName == lc["champion"]``."""
    ap = lc.get("activePlayer")
    ap = ap if isinstance(ap, dict) else {}
    ids = {v.strip() for v in (ap.get("summonerName"), ap.get("riotIdGameName"))
           if isinstance(v, str) and v.strip()}
    if ids:
        parts = {v.split("#")[0] for v in ids}
        for match in (lambda v: v in ids, lambda v: v.split("#")[0] in parts):
            for i, p in enumerate(players):
                for k in ("summonerName", "riotIdGameName"):
                    v = p.get(k)
                    if isinstance(v, str) and v.strip() and match(v.strip()):
                        return i
    champ = lc.get("champion")
    if isinstance(champ, str) and champ.strip():
        hits = [i for i, p in enumerate(players)
                if p.get("championName") == champ.strip()]
        if len(hits) == 1:
            return hits[0]
    return None


def _players(lc: Any) -> list:
    if not isinstance(lc, dict):
        return []
    raw = lc.get("allPlayers")
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def roster_from_lc(
    lc: Any, champions: Mapping[str, Any],
) -> tuple[Optional[LiveRoster], list]:
    """Map ``liveclient_summary()`` to focus-board fighters. Never raises.

    Returns ``(None, notes)`` when there is no usable roster: no
    ``allPlayers``, me not found, my team blank, or no enemy players.
    """
    players = _players(lc)
    if not players:
        return None, ["no live roster: allPlayers missing or empty"]
    me_i = _find_me(players, lc)
    if me_i is None:
        return None, ["no live roster: my player not found in allPlayers"]
    me_p = players[me_i]
    my_team = _team(me_p)
    if not my_team:
        return None, ["no live roster: my team is blank"]

    skip = _non_inventory_ids()
    me_level = _level(lc.get("level"))
    if me_level is None:
        me_level = _level(me_p.get("level"))
    me = (resolve_champion_id(me_p, champions), me_level, _item_ids(me_p, skip))

    notes: list = []
    allies: list = []
    enemies: list = []
    for i, p in enumerate(players):
        if i == me_i:
            continue
        team = _team(p)
        if not team:
            notes.append(f"player {i}: blank team - skipped")
            continue
        fighter = (resolve_champion_id(p, champions), _level(p.get("level")),
                   _item_ids(p, skip))
        (allies if team == my_team else enemies).append(fighter)
    if not enemies:
        return None, notes + ["no live roster: no enemy players"]
    return LiveRoster(me, tuple(allies), tuple(enemies)), notes


# -- the engine (loaded off the caller's thread) --------------------------------

_ENGINE_LOCK = threading.Lock()
_ENGINE: Optional[tuple] = None  # (DataSnapshot, compute_focus_board)
_ENGINE_GATE = FailedLoadGate(retry_after_s=ENGINE_RETRY_S)
_WARM_THREAD: Optional[threading.Thread] = None


def _load_engine() -> tuple:
    """Import the DS engine and load the patch snapshot. May raise."""
    from agents.daemon_slayer.data_loader import DataSnapshot  # lazy
    from agents.daemon_slayer.focus_board import compute_focus_board  # lazy

    return DataSnapshot.load(), compute_focus_board


def _warm() -> None:
    global _ENGINE
    try:
        eng = _load_engine()
    except Exception as exc:  # noqa: BLE001 - fail-soft: no board, never raise
        if _ENGINE_GATE.record_failure():
            log.warning(
                "focus_board_live: DS engine could not load (%s) - no focus "
                "board; retry in %.0fs", type(exc).__name__, ENGINE_RETRY_S,
            )
        return
    with _ENGINE_LOCK:
        _ENGINE = eng
    _ENGINE_GATE.record_success()


def _engine(wait: bool) -> tuple[Optional[tuple], str]:
    """``(engine, status)``. Without ``wait`` it never blocks: a cold engine
    starts the daemon warm thread and reports ``warming``."""
    global _WARM_THREAD
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE, STATUS_OK
        thread = _WARM_THREAD
        warming = thread is not None and thread.is_alive()
        if not warming:
            if not _ENGINE_GATE.should_attempt():
                return None, STATUS_UNAVAILABLE
            if not wait:
                _WARM_THREAD = threading.Thread(
                    target=_warm, name="rc-focus-board-warm", daemon=True,
                )
                _WARM_THREAD.start()
                return None, STATUS_WARMING
    if not wait:
        return None, STATUS_WARMING
    if warming and thread is not None:
        thread.join()
    else:
        _warm()
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE, STATUS_OK
    return None, STATUS_UNAVAILABLE


# -- the board ------------------------------------------------------------------

_STATE_LOCK = threading.Lock()
_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_LAST_COMPUTE_AT: Optional[float] = None


def _mode(mode_key: Any) -> str:
    key = str(mode_key or "").strip()
    return _MODE_BY_KEY.get(key.lower(), key.upper() or "SR")


def _result(status: str, mode: str, **fields: Any) -> dict:
    out: dict = {
        "status": status,
        "mode": mode,
        "apply_mode_modifiers": False,
        "me": "",
        "me_level": 0,
        "allies": [],
        "kill_order": [],
        "kill_order_names": [],
        "danger_order": [],
        "top_kill": None,
        "rows": [],
        "notes": [],
    }
    out.update(fields)
    return out


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3)
    return value


def _board_boilerplate() -> frozenset:
    """The three fixed LIMITS notes every board carries; elided per row (they
    are the module's documented limits, not facts about this roster)."""
    mod = sys.modules.get("agents.daemon_slayer.focus_board")
    names = ("_FULL_HP_NOTE", "_DPS_NOTE", "_ORDERING_NOTE")
    return frozenset(v for v in (getattr(mod, n, None) for n in names)
                     if isinstance(v, str))


def _compute(compute: Callable[..., Any], snapshot: Any, roster: LiveRoster,
             mode: str, notes: list) -> dict:
    try:
        board = compute(
            snapshot, roster.me, list(roster.enemies), list(roster.allies),
            mode=mode, apply_mode_modifiers=False,
        )
        d = board.to_dict()
    except Exception as exc:  # noqa: BLE001 - fail-soft: no board, never raise
        # DS fail-soft idiom: a FIXED note naming the class only (RM-835), the
        # cause to the log repr()-escaped so an engine bug is reported.
        log.warning("focus_board_live: compute_focus_board raised %s: %r - no "
                    "board", type(exc).__name__, str(exc)[:200])
        return _result(STATUS_NO_BOARD, mode, notes=notes + [
            f"engine raised ({type(exc).__name__}) - no board, see logs"])

    boiler = _board_boilerplate()
    notes = notes + [n for n in (d.get("notes") or []) if n not in boiler]
    rows = [r for r in (d.get("rows") or []) if isinstance(r, dict)]
    names = {r.get("champion_id"): r.get("champion_name") for r in rows}
    kill = [str(c) for c in (d.get("kill_order") or [])]
    if not d.get("me") or not kill:
        log.info("focus_board_live: no %s board for this roster (%d note(s))",
                 mode, len(notes))
        return _result(STATUS_NO_BOARD, mode, me=str(d.get("me") or ""),
                       notes=notes)
    return _result(
        STATUS_OK, mode,
        apply_mode_modifiers=bool(d.get("apply_mode_modifiers")),
        me=str(d.get("me")),
        me_level=d.get("me_level") or 0,
        allies=[str(a) for a in (d.get("allies") or [])],
        kill_order=kill,
        kill_order_names=[str(names.get(c) or c) for c in kill],
        danger_order=[str(c) for c in (d.get("danger_order") or [])],
        top_kill={"champion_id": kill[0],
                  "champion_name": str(names.get(kill[0]) or kill[0])},
        rows=[{k: _round(r.get(k)) for k in _ROW_FIELDS} for r in rows],
        notes=notes,
    )


def _roster_sig(mode: str, roster: LiveRoster) -> tuple:
    return (mode, roster.me, roster.allies, roster.enemies)


def _store(sig: tuple, result: dict) -> None:
    with _STATE_LOCK:
        _CACHE[sig] = result
        _CACHE.move_to_end(sig)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _prepare(lc: Any, mode_key: Any, wait_engine: bool
             ) -> tuple[Optional[dict], Optional[tuple]]:
    """The cheap front half shared by both reads: ``(early result, None)``
    when there is nothing to compute, else ``(None, job)`` with
    ``job = (mode, roster, notes, snapshot, compute)``."""
    mode = _mode(mode_key)
    if not enabled():
        return _result(STATUS_DISABLED, mode,
                       notes=[f"{KILL_SWITCH_ENV}=0 - focus board off"]), None
    # Cheap roster pre-check BEFORE the engine: a tick with no roster never
    # starts the DS import.
    if not _players(lc):
        return _result(STATUS_NO_ROSTER, mode, notes=[
            "no live roster: allPlayers missing or empty"]), None
    eng, est = _engine(wait_engine)
    if eng is None:
        note = ("DS engine still loading - no board yet" if est == STATUS_WARMING
                else "DS engine unavailable - no board, see logs")
        return _result(est, mode, notes=[note]), None
    snapshot, compute = eng
    roster, notes = roster_from_lc(lc, snapshot.champions)
    if roster is None:
        return _result(STATUS_NO_ROSTER, mode, notes=notes), None
    return None, (mode, roster, notes, snapshot, compute)


def _board_for_roster(compute: Callable[..., Any], snapshot: Any,
                      roster: LiveRoster, mode: str, notes: list,
                      now: Optional[float]) -> dict:
    """A cached board, a ``throttled`` answer, or a fresh compute (cached).
    Returns a copy. Computes on the CALLER's thread."""
    global _LAST_COMPUTE_AT
    sig = _roster_sig(mode, roster)
    t = time.monotonic() if now is None else float(now)
    with _STATE_LOCK:
        hit = _CACHE.get(sig)
        if hit is not None:
            _CACHE.move_to_end(sig)
            return copy.deepcopy(hit)
        if (_LAST_COMPUTE_AT is not None
                and t - _LAST_COMPUTE_AT < MIN_COMPUTE_INTERVAL_S):
            return _result(STATUS_THROTTLED, mode, notes=[
                f"roster changed within {MIN_COMPUTE_INTERVAL_S:g}s of the last "
                "board - not recomputed"])
        _LAST_COMPUTE_AT = t
    result = _compute(compute, snapshot, roster, mode, notes)
    _store(sig, result)
    return copy.deepcopy(result)


def _board_for_lc(lc: Any, mode_key: Any, now: Optional[float],
                  wait_engine: bool) -> dict:
    early, job = _prepare(lc, mode_key, wait_engine)
    if early is not None:
        return early
    mode, roster, notes, snapshot, compute = job
    return _board_for_roster(compute, snapshot, roster, mode, notes, now)


# -- the worker (RM-854: the compute never runs on the state-builder thread) -----

_WORKER_COND = threading.Condition()
_JOB: Optional[tuple] = None          # the ONE queued job; a newer one replaces it
_WORKER_BUSY = False
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP: Optional[threading.Event] = None
# Test seam (_set_engine_for_tests): run a background read's compute inline.
_WORKER_INLINE = False


def _submit(job: tuple) -> None:
    """Queue ``job`` (latest wins) and make sure the daemon worker is up."""
    global _JOB, _WORKER_THREAD, _WORKER_STOP
    with _WORKER_COND:
        _JOB = job
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            stop = threading.Event()
            thread = threading.Thread(target=_worker_loop, args=(stop,),
                                      name=WORKER_THREAD_NAME, daemon=True)
            _WORKER_STOP, _WORKER_THREAD = stop, thread
            thread.start()
        _WORKER_COND.notify_all()


def _run_job(job: tuple, stop: threading.Event) -> None:
    """Compute one queued roster, waiting out the throttle. Never raises."""
    mode, roster, notes, snapshot, compute = job
    while not stop.is_set():
        if not enabled():
            return                      # the kill switch drops a queued job
        try:
            out = _board_for_roster(compute, snapshot, roster, mode, notes, None)
        except Exception as exc:  # noqa: BLE001 - never raise into the coach loop
            # Cached as a settled ``error`` board so the read stops re-queueing
            # this roster every tick; class name only (RM-835).
            log.warning("focus_board_live: board worker failed (%s) - no board "
                        "for this roster", type(exc).__name__)
            _store(_roster_sig(mode, roster), _result(STATUS_ERROR, mode, notes=(
                notes + [f"board worker failed ({type(exc).__name__}) - no "
                         "board, see logs"])))
            return
        if out.get("status") != STATUS_THROTTLED:
            return
        with _STATE_LOCK:
            last = _LAST_COMPUTE_AT
        wait_s = (MIN_COMPUTE_INTERVAL_S - (time.monotonic() - last)
                  if last is not None else 0.0)
        if stop.wait(max(wait_s, 0.01)):
            return
        with _WORKER_COND:
            if _JOB is not None:
                return                  # a newer roster is queued: it wins


def _worker_loop(stop: threading.Event) -> None:
    global _JOB, _WORKER_BUSY
    while True:
        with _WORKER_COND:
            while _JOB is None and not stop.is_set():
                _WORKER_COND.wait()
            if stop.is_set():
                return
            job, _JOB = _JOB, None
            _WORKER_BUSY = True
        try:
            _run_job(job, stop)
        except Exception:  # noqa: BLE001 - the worker never dies on a job
            log.warning("focus_board_live: board worker job failed",
                        exc_info=True)
        finally:
            with _WORKER_COND:
                _WORKER_BUSY = False
                _WORKER_COND.notify_all()


def _background_board(lc: Any, mode_key: Any, want_result: bool
                      ) -> Optional[dict]:
    """The state-thread read: a cached board, or queue the roster and say
    ``pending``. Never computes and never waits (unless the test seam
    ``_WORKER_INLINE`` is on)."""
    early, job = _prepare(lc, mode_key, False)
    if early is not None:
        return early
    mode, roster, notes, snapshot, compute = job
    if _WORKER_INLINE:
        return _board_for_roster(compute, snapshot, roster, mode, notes, None)
    sig = _roster_sig(mode, roster)
    with _STATE_LOCK:
        hit = _CACHE.get(sig)
        if hit is not None:
            _CACHE.move_to_end(sig)
            return copy.deepcopy(hit) if want_result else None
    _submit(job)
    if not want_result:
        return None
    return _result(STATUS_PENDING, mode, notes=notes + [
        "board computing off the state thread - not ready yet"])


def board_for_lc(lc: Any, mode_key: Any, *, now: Optional[float] = None,
                 wait_engine: bool = False, background: bool = False) -> dict:
    """The focus board for the live roster in ``lc``, as a JSON-able dict.

    ``lc`` is ``liveclient_summary()``; ``mode_key`` the dashboard mode key
    ("arena" / "aram" / "sr"). Always returns the full key set (``status``,
    ``mode``, ``kill_order`` / ``kill_order_names`` / ``danger_order`` as
    lists, ``top_kill`` as ``{"champion_id", "champion_name"}`` or None,
    compact ``rows``, ``notes``). ``background=True`` (RM-854, the
    state-builder read) never computes: a cached board, else ``pending`` with
    the roster handed to the daemon worker; ``now`` / ``wait_engine`` are
    ignored there. Without it the board is computed on the caller's thread
    (``now`` in monotonic seconds and ``wait_engine`` are test seams). Never
    raises.
    """
    try:
        if background:
            return _background_board(lc, mode_key, True)
        return _board_for_lc(lc, mode_key, now, wait_engine)
    except Exception as exc:  # noqa: BLE001 - hard fail-soft contract
        log.warning("focus_board_live: adapter failed (%s) - no board",
                    type(exc).__name__)
        return _result(STATUS_ERROR, _mode(mode_key), notes=[
            f"adapter failed ({type(exc).__name__}) - no board, see logs"])


def prefetch(lc: Any, mode_key: Any) -> None:
    """Hand the worker the latest roster when its board is not cached (the
    shadow's dedup ticks). Non-blocking, no result, never raises."""
    try:
        _background_board(lc, mode_key, False)
    except Exception as exc:  # noqa: BLE001 - hard fail-soft contract
        log.debug("focus_board_live: prefetch failed (%s)", type(exc).__name__)


# -- test seams -----------------------------------------------------------------

def _set_engine_for_tests(engine: Optional[tuple], *,
                          inline_worker: bool = True) -> None:
    """Install a ready engine. ``inline_worker`` (default True, what the
    RM-844 one-tick tests rely on) runs a background read's compute on the
    caller, synchronously, until ``reset_for_tests``; False exercises the real
    daemon worker (the RM-854 tests)."""
    global _ENGINE, _WORKER_INLINE
    with _ENGINE_LOCK:
        _ENGINE = engine
    _WORKER_INLINE = bool(inline_worker) and engine is not None


def _join_warm_for_tests(timeout: float) -> None:
    thread = _WARM_THREAD
    if thread is not None:
        thread.join(timeout)


def _wait_worker_idle_for_tests(timeout: float) -> bool:
    """True once no job is queued or running (False on timeout)."""
    end = time.monotonic() + timeout
    with _WORKER_COND:
        while _JOB is not None or _WORKER_BUSY:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            _WORKER_COND.wait(remaining)
    return True


def _stop_worker_for_tests(timeout: float) -> None:
    global _JOB, _WORKER_THREAD, _WORKER_STOP, _WORKER_BUSY
    with _WORKER_COND:
        stop, thread = _WORKER_STOP, _WORKER_THREAD
        _JOB = None
        if stop is not None:
            stop.set()
        _WORKER_COND.notify_all()
    if thread is not None:
        thread.join(timeout)
    with _WORKER_COND:
        _WORKER_THREAD = None
        _WORKER_STOP = None
        _WORKER_BUSY = False


def reset_for_tests() -> None:
    """Stop the worker; drop the engine, the cache, the throttle clock, the
    failure gate and the inline seam."""
    global _ENGINE, _WARM_THREAD, _LAST_COMPUTE_AT, _INDEX, _WORKER_INLINE
    _stop_worker_for_tests(5.0)
    _join_warm_for_tests(5.0)
    with _ENGINE_LOCK:
        _ENGINE = None
        _WARM_THREAD = None
    _WORKER_INLINE = False
    _ENGINE_GATE.reset()
    with _STATE_LOCK:
        _CACHE.clear()
        _LAST_COMPUTE_AT = None
    with _INDEX_LOCK:
        _INDEX = None


__all__ = [
    "KILL_SWITCH_ENV",
    "LiveRoster",
    "MIN_COMPUTE_INTERVAL_S",
    "TRANSIENT_STATUSES",
    "WORKER_THREAD_NAME",
    "board_for_lc",
    "enabled",
    "prefetch",
    "resolve_champion_id",
    "roster_from_lc",
]
