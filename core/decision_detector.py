"""
core/decision_detector.py - coachable-moment detection + recording.

Watches live game state (Live Client snapshots via the relay + vision_tracker
output) and emits "decisions" - moments where the player has a meaningful
choice to make (contest/give an objective, force/disengage a fight, etc.).
The dashboard surfaces pending decisions and records the player's choice
for later postmortem.

Architecture
------------
- DECISION_REGISTRY: list of detector functions (snapshot, vision_state) -> Decision | None.
  Each new decision type is a function appended to the registry. No central
  switch statements; types are purely additive.
- DecisionStore: atomic file-backed queue of pending decisions
  (data/decisions_pending.json) + append-only history log
  (data/decisions_log.jsonl).
- DecisionLoop: daemon thread that polls state every ~1s, evaluates
  detectors, dedupes by decision id, writes the pending list.

V1 ships with one detector: `detect_objective_contest_with_missing` -
fires when an objective spawns within ~60s and >=2 enemies are missing.

Data sources (1-PC, ADR-011)
----------------------------
Live Client data arrives via the shared snapshot cache
(core/liveclient_cache.py), which reads the Legion-local relay at
http://127.0.0.1:8889/latest-liveclient (self-healing: the relay falls
back to an in-process :2999 read when the relayed snapshot is stale).
Vision state is read from data/vision_state.json. If the snapshot ages
out, detectors stop firing and pending decisions are cleared.
"""
from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

import portalocker

from core.polled_json import atomic_write_json

_log = logging.getLogger("rc.decision_detector")
_APP_DIR = Path(__file__).parent.parent

# Stale-snapshot threshold - anything older than this is treated as
# "no game" and clears any pending decisions.
_RELAY_MAX_AGE_S  = 8.0
_VISION_STATE     = _APP_DIR / "data" / "vision_state.json"
_PENDING_PATH     = _APP_DIR / "data" / "decisions_pending.json"
_LOG_PATH         = _APP_DIR / "data" / "decisions_log.jsonl"
_LOCK_PATH        = _APP_DIR / "ops" / "runtime" / "decisions.lock"
# ADR-007 (s169): heartbeat is file-backed because the DecisionLoop lives
# in the Phase 3 supervisor process while the dashboard reads it from the
# RC main process - same cross-process pattern as DecisionStore.
_HEARTBEAT_PATH   = _APP_DIR / "data" / "decisions_heartbeat.json"

_DEFAULT_POLL_S   = 1.0
_LOCK_TIMEOUT_S   = 2.0
# Cap on the heartbeat's last_detector_error string. It is served over
# /api/decisions/heartbeat and an exception message can quote snapshot
# fields, so it is bounded the way routes_diag bounds its own notes.
_MAX_ERR_CHARS    = 200

# Tier 3 #15 (2026-05-01): the DecisionLoop now runs in agents/supervisor.py
# while record_choice() is invoked from the dashboard handler in the RC
# main process. The threading.Lock alone no longer serializes the two
# read-modify-write paths on data/decisions_pending.json - pair it with
# a portalocker file lock for cross-process safety. Same best-effort
# pattern as core.coaching_data_lock: 2s timeout, fall through with TL
# only if the file lock can't be acquired.
_TL_DECISIONS = threading.Lock()


@contextlib.contextmanager
def _decisions_critical_section() -> Iterator[None]:
    """Process-local + cross-process lock for decisions_pending.json
    read-modify-writes. File-lock is best-effort with a 2s timeout."""
    with _TL_DECISIONS:
        fl: portalocker.Lock | None = None
        try:
            _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            fl = portalocker.Lock(
                str(_LOCK_PATH), mode="a+b", timeout=_LOCK_TIMEOUT_S,
            )
            fl.acquire()
        except portalocker.LockException:
            fl = None
        except Exception:  # noqa: BLE001
            fl = None
        try:
            yield
        finally:
            if fl is not None:
                try:
                    fl.release()
                except Exception:  # noqa: BLE001
                    pass

# Global rate cap (per-game): never spam more than _MAX_PER_GAME total
# decisions, never less than _MIN_GAP_S between two NEW decision ids
# entering the pending list. Re-fires of an id already in pending don't
# count - those just keep the existing decision alive.
_MAX_PER_GAME     = 5
_MIN_GAP_S        = 30.0


# -- Data shape ----------------------------------------------------------------

@dataclass
class Decision:
    """A coachable moment surfaced to the player.

    `id` MUST be deterministic per (game, decision instance) so re-firing
    detectors don't create duplicates. Convention: "<type>:<key>" where
    key is enough to identify the same situation across polls (e.g.
    objective name + integer spawn time).
    """
    id: str
    type: str
    title: str
    subtitle: str
    options: list[str]
    created_at_unix: float
    created_at_game_time: float
    expires_at_game_time: float
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# -- Detector registry ---------------------------------------------------------

DetectorFn = Callable[[dict, dict], Optional[Decision]]
DECISION_REGISTRY: list[DetectorFn] = []


def register_detector(fn: DetectorFn) -> DetectorFn:
    """Decorator (or plain call) to add a detector to the registry."""
    DECISION_REGISTRY.append(fn)
    return fn


# -- Helpers -------------------------------------------------------------------
# SR epic-objective spawn timings (first-spawn / respawn). ONE cited source:
# imported from core.event_callouts so the served callout path and this
# vision-gated detector can never drift apart (L3 reconciliation).
# Atakhan currently replaces Herald - skipped here pending mode-aware logic.
from core.event_callouts import (  # noqa: E402
    SR_BARON_FIRST_S as _BARON_FIRST_S,
    SR_BARON_RESPAWN_S as _BARON_RESPAWN_S,
    SR_DRAGON_FIRST_S as _DRAGON_FIRST_S,
    SR_DRAGON_RESPAWN_S as _DRAGON_RESPAWN_S,
)


# -- Envelope coercion (RM-318) ------------------------------------------------
# The six detectors read the Live Client envelope positionally and used
# `or {}` as their only guard. `or {}` defends against a MISSING or FALSY
# value and against nothing else: a truthy value of the WRONG TYPE passes
# straight through it and raises on the next `.get(...)` or `float(...)`.
#
# MEASURED at 8d4173c31, driving each detector from a snapshot that makes
# it fire and retyping one field (raises / 6 detectors): a str `gameData`
# 6/6, a str `gameTime` 6/6, a None `gameTime` 6/6, a str `activePlayer`
# 4/6, a str or non-dict-bearing `events.Events` 3/6, a malformed
# `vision_state` / `enemies` 3/6, a leading non-dict `allPlayers` row 2/6.
#
# The loop catches those per-detector, so none of them is a crash. Each is
# a detector that is silently dead for a whole game while the heartbeat
# pill counts up - which is exactly the failure the cycle-12 heartbeat was
# built to make VISIBLE. RM-318 prevents it.
#
# These readers coerce; they do NOT swallow. A blanket try/except around a
# detector would suppress a genuine logic bug too, and would re-blind the
# `detector_errors` counter that cycle 12 added. Anything these functions
# cannot type-check is still free to raise into DecisionLoop._loop, where
# it is counted and surfaced.

def _as_dict(value: object) -> dict:
    """`value` when it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def _as_float(value: object, default: float = 0.0) -> float:
    """`value` as a float when it is a real number, else `default`.

    bool is excluded deliberately: `True` is an int to Python but never a
    game time, an HP value or an event timestamp on the wire."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _as_str(value: object, default: str = "") -> str:
    """`value` when it is a str, else `default`. Used where the old code
    wrote `x.get(k) or ""` and would have concatenated a non-str."""
    return value if isinstance(value, str) else default


def _game_data(snapshot: dict) -> dict:
    return _as_dict(_as_dict(snapshot).get("gameData"))


def _game_time(snapshot: dict) -> float:
    return _as_float(_game_data(snapshot).get("gameTime"), 0.0)


def _game_mode(snapshot: dict) -> str:
    mode = _game_data(snapshot).get("gameMode")
    return str(mode).upper() if isinstance(mode, str) else ""


def _active_player(snapshot: dict) -> dict:
    return _as_dict(_as_dict(snapshot).get("activePlayer"))


def _self_name(snapshot: dict) -> Optional[str]:
    active = _active_player(snapshot)
    for key in ("summonerName", "riotIdGameName"):
        nm = active.get(key)
        if isinstance(nm, str) and nm:
            return nm
    return None


def _all_players(snapshot: dict) -> list[dict]:
    """allPlayers, dict rows only. Dropping a malformed row rather than
    tolerating it in place matters: the two detectors that scan this list
    `break` on their match, so a bad row's POSITION decided whether the
    old code raised at all - a trailing one measured clean and a leading
    one measured broken, on the same payload."""
    raw = _as_dict(snapshot).get("allPlayers")
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def _events(snapshot: dict) -> list[dict]:
    """events.Events, dict rows only. The `(x or {}).get("Events") or []`
    idiom this replaces was already guarded for a LIST `events` - that arm
    is a green control and is unchanged by RM-318."""
    raw = _as_dict(_as_dict(snapshot).get("events")).get("Events")
    if not isinstance(raw, list):
        return []
    return [ev for ev in raw if isinstance(ev, dict)]


def _enemies(vision_state: object) -> dict:
    """vision_tracker's enemies map, dict values only."""
    enemies = _as_dict(_as_dict(vision_state).get("enemies"))
    return {k: v for k, v in enemies.items() if isinstance(v, dict)}


def _next_objective_spawn(events: list, game_time: float, *,
                          name: str, first_at: float, respawn: float,
                          kill_event: str) -> Optional[float]:
    """Return absolute game_time when the next instance of this objective
    spawns, or None if it can't spawn again this game."""
    last_kill_t = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("EventName") == kill_event:
            t = ev.get("EventTime")
            if isinstance(t, (int, float)):
                if last_kill_t is None or t > last_kill_t:
                    last_kill_t = t
    if last_kill_t is None:
        # Not yet killed: first_at is the (only) known spawn time, whether
        # the clock is before it (upcoming) or past it (still up, untaken).
        return first_at
    return last_kill_t + respawn


# -- Detector: objective contest with missing enemies --------------------------

@register_detector
def detect_objective_contest_with_missing(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """Trigger when a major objective spawns within ~60s AND >=2 enemies
    are missing per vision_tracker. Player decides contest vs give."""
    game_time = _game_time(snapshot)
    events = _events(snapshot)

    # Skip non-SR modes - Dragon/Baron only exist there.
    mode = _game_mode(snapshot)
    if mode and mode != "CLASSIC":
        return None

    # Pick the soonest of (Dragon, Baron) within the alert window.
    candidates = []
    for name, first_at, respawn, kill_event in (
        ("Dragon", _DRAGON_FIRST_S, _DRAGON_RESPAWN_S, "DragonKill"),
        ("Baron",  _BARON_FIRST_S,  _BARON_RESPAWN_S,  "BaronKill"),
    ):
        spawn_t = _next_objective_spawn(
            events, game_time, name=name, first_at=first_at,
            respawn=respawn, kill_event=kill_event,
        )
        if spawn_t is None:
            continue
        time_to_spawn = spawn_t - game_time
        if -5 <= time_to_spawn <= 60:   # 5s grace post-spawn for "still up"
            candidates.append((time_to_spawn, name, spawn_t))
    if not candidates:
        return None
    candidates.sort()
    time_to_spawn, name, spawn_t = candidates[0]

    enemies = _enemies(vision_state)
    missing = []
    for nm, e in enemies.items():
        if e.get("is_dead"):
            continue
        if e.get("visible"):
            continue
        zone = e.get("last_seen_zone") or "?"
        ago = e.get("missing_for_s")
        if isinstance(ago, (int, float)):
            missing.append(f"{nm} ({int(ago)}s, {zone})")
        else:
            missing.append(f"{nm} ({zone})")
    if len(missing) < 2:
        return None

    when = "spawning now" if time_to_spawn <= 0 else f"in {int(time_to_spawn)}s"
    title = f"{name} {when} - {len(missing)} enemies missing"
    subtitle = "Missing: " + ", ".join(missing)

    return Decision(
        id=f"objective_contest:{name}:{int(spawn_t)}",
        type="objective_contest",
        title=title,
        subtitle=subtitle,
        options=["contest", "give"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=spawn_t + 90,   # auto-clear 90s after spawn
        context={
            "objective": name,
            "time_to_spawn_s": round(time_to_spawn, 1),
            "missing_enemies": missing,
        },
    )


# -- Detector: low HP, time to back? -------------------------------------------

@register_detector
def detect_low_hp_backable(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """Self HP <25% and alive >=90s past last respawn -> back vs push.

    ADR-007 tightening (s169): operator complained the 40%/45s threshold
    fired mid-fight when the warning was too late to act on. Bumped HP
    threshold to 25% (you're committed to back, not deciding) and
    alive_for to 90s (post-respawn pre-fight has stable framing).
    Bucket the id to 60-second windows so a single drawn-out low-HP
    episode doesn't re-prompt every tick."""
    stats = _as_dict(_active_player(snapshot).get("championStats"))
    cur = _as_float(stats.get("currentHealth"), 0.0)
    mx = _as_float(stats.get("maxHealth"), 0.0)
    if mx <= 0:
        return None
    pct = cur / mx
    if pct >= 0.25:
        return None

    game_time = _game_time(snapshot)
    if game_time < 90:        # nothing to back to in the first 90s
        return None

    # Find self in allPlayers to confirm alive + measure time since last death.
    self_name = _self_name(snapshot)
    all_players = _all_players(snapshot)
    me = None
    for p in all_players:
        nm = p.get("summonerName") or p.get("riotIdGameName")
        if nm == self_name:
            me = p
            break
    if not me or me.get("isDead"):
        return None

    # Walk events for our deaths; require >=90s alive.
    events = _events(snapshot)
    last_death_t = 0.0
    for ev in events:
        if (ev.get("EventName") == "ChampionKill"
                and ev.get("VictimName") == self_name):
            t = ev.get("EventTime")
            if isinstance(t, (int, float)) and t > last_death_t:
                last_death_t = float(t)
    alive_for = game_time - last_death_t
    if alive_for < 90:
        return None

    bucket = int(game_time // 60)
    pct_int = int(round(pct * 100))
    return Decision(
        id=f"low_hp_back:{bucket}",
        type="low_hp_back",
        title=f"{pct_int}% HP - back or stay?",
        subtitle=f"alive {int(alive_for)}s since last death",
        options=["back", "push"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=game_time + 30,
        context={
            "hp_pct": round(pct, 3),
            "alive_for_s": round(alive_for, 1),
        },
    )


# -- Detector: lane roam window (>=2 enemies missing, no objective in window) --

@register_detector
def detect_lane_roam_window(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """>=2 enemies missing 12s+ AND no objective contest is the right
    framing (deferred to detect_objective_contest_with_missing) -> the
    player has a roam-or-push window. Bucketed to 90s windows."""
    game_time = _game_time(snapshot)
    if game_time < 240:    # roams matter past ~4min
        return None
    mode = _game_mode(snapshot)
    if mode and mode != "CLASSIC":
        return None     # ARAM has no roams

    # If a major objective is in the contest window, the contest detector
    # owns this signal - don't double-prompt.
    events = _events(snapshot)
    for name, first_at, respawn, kill_event in (
        ("Dragon", _DRAGON_FIRST_S, _DRAGON_RESPAWN_S, "DragonKill"),
        ("Baron",  _BARON_FIRST_S,  _BARON_RESPAWN_S,  "BaronKill"),
    ):
        spawn_t = _next_objective_spawn(
            events, game_time, name=name, first_at=first_at,
            respawn=respawn, kill_event=kill_event,
        )
        if spawn_t is not None and -5 <= (spawn_t - game_time) <= 60:
            return None

    enemies = _enemies(vision_state)
    missing_long = []
    for nm, e in enemies.items():
        if e.get("is_dead") or e.get("visible"):
            continue
        ago = e.get("missing_for_s")
        if isinstance(ago, (int, float)) and ago >= 12:
            zone = e.get("last_seen_zone") or "?"
            missing_long.append(f"{nm} ({int(ago)}s, {zone})")
    if len(missing_long) < 2:
        return None

    bucket = int(game_time // 90)
    return Decision(
        id=f"lane_roam:{bucket}",
        type="lane_roam",
        title=f"{len(missing_long)} enemies missing - roam or push?",
        subtitle="Missing: " + ", ".join(missing_long),
        options=["roam", "push"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=game_time + 25,
        context={"missing": missing_long},
    )


# -- Detector: post-fight objective opportunity --------------------------------

def _team_of(all_players: list, name: Optional[str]) -> Optional[str]:
    """Resolve a Live Client participant name to its team ("ORDER"/"CHAOS"),
    or None when the name is absent from allPlayers - which is the normal
    case for a turret/minion `KillerName`."""
    if not name:
        return None
    for p in all_players:
        if not isinstance(p, dict):
            continue
        if (p.get("summonerName") or p.get("riotIdGameName")) == name:
            return p.get("team")
    return None

@register_detector
def detect_postfight_objective(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """In the last 20s of game time, ally team has a +3 (or better) kill
    differential AND a major objective is alive within ~30s. Player has
    to choose: take the objective with tempo, or cross-map for towers."""
    game_time = _game_time(snapshot)
    if game_time < 600:    # post-fight objectives are mid+ game
        return None
    mode = _game_mode(snapshot)
    if mode and mode != "CLASSIC":
        return None

    self_name = _self_name(snapshot)
    all_players = _all_players(snapshot)
    # _team_of isinstance-guards each row; the hand-rolled loop this
    # replaced raised on a non-dict allPlayers entry before ever reaching
    # the guarded lookup below (lane-8 cycle 12).
    self_team = _team_of(all_players, self_name)
    if not self_team:
        return None

    # Walk events: count ally kills minus ally deaths in the last 20s.
    events = _events(snapshot)
    window_start = game_time - 20
    last_event_t = 0.0
    diff = 0
    for ev in events:
        if ev.get("EventName") != "ChampionKill":
            continue
        t = ev.get("EventTime")
        if not isinstance(t, (int, float)) or t < window_start:
            continue
        last_event_t = max(last_event_t, float(t))
        # Count each kill exactly ONCE. Prefer the killer's team; a turret
        # or minion execute has no KillerName in allPlayers, so fall back
        # to the victim's side.
        #
        # Lane-8 cycle 12: this resolved BOTH the killer AND the victim and
        # added a point for each, so every event moved `diff` by +/-2. The
        # "+3 (or better)" gate above therefore fired at a TRUE +2, and the
        # title rendered double the real number to the player ("+4 fight"
        # for a 2-kill swing). Pinned by
        # tests/test_decision_detector_lane8_cycle12.py.
        killer_team = _team_of(all_players, ev.get("KillerName"))
        victim_team = _team_of(all_players, ev.get("VictimName"))
        if (killer_team is not None and victim_team is not None
                and killer_team == victim_team):
            continue        # same-team kill: one kill, one death, net zero
        if killer_team is not None:
            diff += 1 if killer_team == self_team else -1
        elif victim_team is not None:
            diff += -1 if victim_team == self_team else 1
    if diff < 3:
        return None

    # Is a major objective live or imminent?
    obj_window = []
    for name, first_at, respawn, kill_event in (
        ("Dragon", _DRAGON_FIRST_S, _DRAGON_RESPAWN_S, "DragonKill"),
        ("Baron",  _BARON_FIRST_S,  _BARON_RESPAWN_S,  "BaronKill"),
    ):
        spawn_t = _next_objective_spawn(
            events, game_time, name=name, first_at=first_at,
            respawn=respawn, kill_event=kill_event,
        )
        if spawn_t is None:
            continue
        if -10 <= (spawn_t - game_time) <= 30:
            obj_window.append((name, spawn_t))
    if not obj_window:
        return None

    obj_name = obj_window[0][0]
    return Decision(
        id=f"postfight_objective:{int(last_event_t)}",
        type="postfight_objective",
        title=f"+{diff} fight, {obj_name} live - take or cross-map?",
        subtitle=f"ally kill diff {diff:+d} in last 20s - {obj_name} window open",
        options=["take", "cross-map"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=game_time + 35,
        context={"kill_diff": diff, "objective": obj_name},
    )


# -- Detector: jungler gank-likely (ADR-007 s169) ------------------------------

def _enemy_has_smite(p: dict) -> bool:
    """Live Client summonerSpells shape: each spell carries displayName,
    rawDescription and rawDisplayName. Smite is displayName 'Smite',
    rawDisplayName 'GeneratedTip_SummonerSpell_SummonerSmite_DisplayName'
    and rawDescription '..._SummonerSmite_Description'. Any one of the
    three is accepted.

    Lane-8 cycle 12: the docstring already claimed the raw name was read,
    but the code read only displayName + rawDescription, so a payload
    carrying the cited rawDisplayName alone returned False. Both raw keys
    are now read."""
    spells = _as_dict(_as_dict(p).get("summonerSpells"))
    for slot in ("summonerSpellOne", "summonerSpellTwo"):
        s = _as_dict(spells.get(slot))
        nm = _as_str(s.get("displayName")).lower()
        raw = (_as_str(s.get("rawDescription"))
               + _as_str(s.get("rawDisplayName"))).lower()
        if "smite" in nm or "summonersmite" in raw:
            return True
    return False


def _is_enemy_jungle_zone(zone: str, enemy_team: str) -> bool:
    """SR only. Order team's jungle is blue_*; CHAOS is red_*. Callers
    gate on mode (CLASSIC) - ARAM has no jungle, Arena/Brawl have
    unrelated layouts. A zone is the enemy's own jungle when the prefix
    matches their team."""
    z = (zone or "").lower()
    t = (enemy_team or "").upper()
    if t == "ORDER":   # enemy is on Order team -> their jungle is blue_
        return z.startswith("blue_") and "jungle" in z
    if t == "CHAOS":   # enemy is on Chaos team -> their jungle is red_
        return z.startswith("red_") and "jungle" in z
    # Unknown team: treat any *_jungle as enemy-side (conservative - won't fire).
    return False


@register_detector
def detect_jungler_gank_likely(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """ADR-007 s169: enemy jungler missing >=20s AND last seen outside their
    own jungle quadrant (likely pathing to a lane). Identifies the JG by
    Smite summoner spell. SR only - ARAM has no jungle, Arena/Brawl have
    no Smite.

    Bucketed to 90-second windows so a stationary missing JG doesn't
    re-fire every tick. Skips while a major objective is in the contest
    window - `detect_objective_contest_with_missing` owns that case."""
    game_time = _game_time(snapshot)
    mode = _game_mode(snapshot)
    if mode and mode != "CLASSIC":
        return None
    if game_time < 180:   # ganks usually past 3min
        return None

    # Defer to objective_contest if drake/baron is imminent.
    events = _events(snapshot)
    for name, first_at, respawn, kill_event in (
        ("Dragon", _DRAGON_FIRST_S, _DRAGON_RESPAWN_S, "DragonKill"),
        ("Baron",  _BARON_FIRST_S,  _BARON_RESPAWN_S,  "BaronKill"),
    ):
        spawn_t = _next_objective_spawn(
            events, game_time, name=name, first_at=first_at,
            respawn=respawn, kill_event=kill_event,
        )
        if spawn_t is not None and -5 <= (spawn_t - game_time) <= 60:
            return None

    # Resolve self team so we know which side is "enemy".
    self_name = _self_name(snapshot)
    all_players = _all_players(snapshot)
    # _team_of isinstance-guards each row; the hand-rolled loop this
    # replaced raised on a non-dict allPlayers entry before ever reaching
    # the guarded lookup below (lane-8 cycle 12).
    self_team = _team_of(all_players, self_name)
    if not self_team:
        return None
    enemy_team = "CHAOS" if self_team == "ORDER" else "ORDER"

    # Find the enemy JG: enemy-team player with Smite.
    enemy_jg_name = None
    for p in all_players:
        if p.get("team") != enemy_team:
            continue
        if _enemy_has_smite(p):
            enemy_jg_name = (p.get("summonerName")
                             or p.get("riotIdGameName")
                             or p.get("championName"))
            break
    if not enemy_jg_name:
        return None

    # Pull the JG's vision state. Key shape from vision_tracker._compute_enemies
    # uses summonerName-or-riotIdGameName as the key.
    enemies = _enemies(vision_state)
    jg = enemies.get(enemy_jg_name)
    if not jg:
        # Try a champion-keyed fallback for short-form keys.
        for nm, e in enemies.items():
            if e.get("summoner_name") == enemy_jg_name:
                jg = e
                break
    if not jg or jg.get("is_dead") or jg.get("visible"):
        return None
    missing_for = jg.get("missing_for_s")
    if (isinstance(missing_for, bool)
            or not isinstance(missing_for, (int, float))
            or missing_for < 20):
        return None
    last_zone = _as_str(jg.get("last_seen_zone"))
    # Likely-ganking signal: last seen OUTSIDE their own jungle.
    if _is_enemy_jungle_zone(last_zone, enemy_team):
        return None

    bucket = int(game_time // 90)
    return Decision(
        id=f"jungler_gank:{bucket}",
        type="jungler_gank",
        title=f"Enemy JG missing {int(missing_for)}s - gank or invade?",
        subtitle=f"{jg.get('champion') or 'Jungler'} last seen {last_zone}",
        options=["safe", "punish"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=game_time + 25,
        context={
            "jungler_name": enemy_jg_name,
            "missing_for_s": round(float(missing_for), 1),
            "last_seen_zone": last_zone,
        },
    )


# -- Detector: throwing-lead (ADR-007 s169) ------------------------------------

@register_detector
def detect_throwing_lead(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """ADR-007 s169: player previously ahead, now losing tempo. Heuristic:
    self has >=2 deaths in the last 90s AND the death events were within a
    cluster (<=45s between first and last). Bucketed to 120s windows.

    Stateless: relies only on the events list in `snapshot`. Doesn't need
    a gold-history tracker - death-cluster IS the throwing signal."""
    game_time = _game_time(snapshot)
    if game_time < 480:   # 8 min - early-game deaths happen, not "throwing"
        return None

    self_name = _self_name(snapshot)
    if not self_name:
        return None

    events = _events(snapshot)
    window_start = game_time - 90
    my_deaths_t: list[float] = []
    for ev in events:
        if ev.get("EventName") != "ChampionKill":
            continue
        if ev.get("VictimName") != self_name:
            continue
        t = ev.get("EventTime")
        if isinstance(t, (int, float)) and t >= window_start:
            my_deaths_t.append(float(t))

    if len(my_deaths_t) < 2:
        return None

    my_deaths_t.sort()
    spread = my_deaths_t[-1] - my_deaths_t[0]
    if spread > 45:
        # Two deaths >45s apart isn't a cluster - just bad luck.
        return None

    bucket = int(game_time // 120)
    return Decision(
        id=f"throwing_lead:{bucket}",
        type="throwing_lead",
        title=f"{len(my_deaths_t)} deaths in {int(spread)}s - reset?",
        subtitle="Two deaths inside a 45s window. Stop chasing, freeze lane,"
                 " group with team.",
        options=["reset", "force"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=game_time + 60,
        context={
            "death_count": len(my_deaths_t),
            "death_spread_s": round(spread, 1),
            "last_death_at_s": round(my_deaths_t[-1], 1),
        },
    )


# -- Store ---------------------------------------------------------------------

class DecisionStore:
    """Atomic file-backed pending list + append-only history log.

    `reconcile()` and `record_choice()` use `_decisions_critical_section()`
    (threading.Lock + portalocker file lock) because the loop runs in the
    Phase 3 supervisor process while record_choice runs in the RC dashboard
    handler - see Tier 3 #15."""

    def __init__(self, pending_path: Path = _PENDING_PATH,
                 log_path: Path = _LOG_PATH) -> None:
        self._pending_path = pending_path
        self._log_path = log_path

    def list_pending(self) -> list[dict]:
        """Pending decisions, always a list of dicts carrying a string id.

        Lane-8 cycle 12: this returned whatever the file parsed to. Every
        one of its five consumers (reconcile, record_choice, _apply_rate_cap,
        dashboard/routes_diag.py, dashboard/routes_metrics.py) assumes a list
        of id-carrying dicts, so a file holding any other JSON - `{}`, `null`,
        a bare string, a list of ints - wedged reconcile() with a TypeError
        on `d["id"]` INSIDE the loop's broad except, on every tick, forever,
        without ever repairing the file. To be accurate about WHY that is
        worth guarding, since the first draft of this note overstated it:
        `_write_pending` is the SOLE writer in the tree, so a bad shape can
        only arrive from outside it - a hand edit, a truncated or restored
        file, a half-copied data/ directory. Rare, but the failure it caused
        was permanent and silent, which is the combination worth a cheap
        filter. Filtering here (rather than raising) also repairs the bad
        state: the next reconcile() writes a well-formed list back over it."""
        try:
            raw = json.loads(self._pending_path.read_text(encoding="utf-8"))
        # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        except OSError as exc:
            _log.debug("pending read failed: %s", exc)
            return []
        if not isinstance(raw, list):
            _log.warning("pending file is %s, not a list - treating as empty",
                         type(raw).__name__)
            return []
        items = [d for d in raw
                 if isinstance(d, dict) and isinstance(d.get("id"), str)]
        if len(items) != len(raw):
            _log.warning("pending file: dropped %d malformed entr%s",
                         len(raw) - len(items),
                         "y" if len(raw) - len(items) == 1 else "ies")
        return items

    def _write_pending(self, items: list[dict]) -> bool:
        # Lane-8 cycle 12: this used a bare `tmp.replace()`. On Windows that
        # raises PermissionError (WinError 5) while a reader holds the
        # destination open, and PermissionError IS an OSError, so the write
        # was swallowed below at debug level. decisions_pending.json is read
        # cross-process by dashboard/routes_diag.py and routes_metrics.py, so
        # that contention is routine BY DESIGN. The measured consequence was
        # in record_choice(): the JSONL entry was appended and the decision
        # then silently stayed pending, so one decision logged twice and
        # never cleared. core.polled_json.atomic_write_json is the canonical
        # answer already in the tree (bounded backoff, ~275 ms, then raise).
        try:
            atomic_write_json(self._pending_path, items)
            return True
        # mkdir / write_text / os.replace raise OSError; json.dumps raises
        # TypeError on a non-serializable decision field and ValueError on a
        # circular ref or out-of-range float; with_suffix raises ValueError on
        # a malformed suffix. Those are every raising statement.
        except (OSError, TypeError, ValueError) as exc:
            # WARNING, not debug: a dropped write means the pending list on
            # disk no longer matches reality, and record_choice() depends on
            # the return value to stay consistent.
            _log.warning("pending write failed: %s", exc)
            return False

    def reconcile(self, fresh: list[Decision], game_time: float) -> None:
        """Merge newly-detected decisions into the pending list:
          - keep any pending decision whose id appears in `fresh` (still triggering)
          - drop pending decisions whose expires_at_game_time < game_time
          - drop pending decisions whose id no longer appears in `fresh`
            (condition lifted - e.g., enemies became visible again)
          - add new ids from `fresh`
        """
        fresh_ids = {d.id for d in fresh}
        with _decisions_critical_section():
            current = self.list_pending()
            # 1) keep + drop
            kept: list[dict] = []
            for d in current:
                if d["id"] not in fresh_ids:
                    continue   # condition no longer holds
                if d.get("expires_at_game_time", 0) < game_time:
                    continue   # auto-expired
                kept.append(d)
            kept_ids = {d["id"] for d in kept}
            # 2) add new
            for d in fresh:
                if d.id not in kept_ids:
                    kept.append(d.to_dict())
            self._write_pending(kept)

    def record_coach_choice(self, *, choice_key: str, choice_label: str,
                            confidence: str, source_tag: str,
                            game_context: dict | None = None) -> dict:
        """Append a coach A/B tutoring choice to the decision log.

        Coach choices have no pending-state lifecycle (the user clicks one
        and it is logged immediately for post-game replay); they share the
        same JSONL ledger as objective-contest decisions, distinguished by
        ``type="coach_choice"``. Returns the recorded entry."""
        entry = {
            "type": "coach_choice",
            "ts_unix": time.time(),
            "choice_key": choice_key,
            "choice_label": choice_label,
            "confidence": confidence,
            "source_tag": source_tag,
            "game_context": game_context or {},
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:  # noqa: BLE001
            _log.warning("coach_choice log append failed: %s", exc)
        return entry

    def record_choice(self, decision_id: str, choice: str,
                      extra: Optional[dict] = None) -> Optional[dict]:
        """Move a pending decision to the log with the player's choice.
        Returns the recorded entry or None if id not found."""
        with _decisions_critical_section():
            current = self.list_pending()
            match = None
            remaining = []
            for d in current:
                if d["id"] == decision_id and match is None:
                    match = d
                else:
                    remaining.append(d)
            if match is None:
                return None
            entry = {
                **match,
                "choice": choice,
                "decided_at_unix": time.time(),
                "extra": extra or {},
            }
            # Lane-8 cycle 12: the JSONL append used to run FIRST, and the
            # pending write's failure was swallowed. Under a concurrent
            # reader that produced the worst of both - the choice was logged
            # AND the decision stayed pending, so the next click logged it a
            # second time. Removing it from pending is what makes the choice
            # final, so that has to succeed before anything is recorded.
            #
            # The invariant both orderings must preserve: a decision is
            # either STILL PENDING (retryable) or LOGGED EXACTLY ONCE. Never
            # both, and never neither. So a failed pending write records
            # nothing, and a failed log append puts the decision BACK - the
            # adversarial pass on this slice caught the version that returned
            # `entry` after a failed append, which silently satisfied
            # "neither" and reported success to the caller.
            if not self._write_pending(remaining):
                _log.warning("record_choice %s: pending write failed, "
                             "choice not recorded", decision_id)
                return None
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError as exc:
                _log.warning("decisions_log append failed: %s - restoring %s "
                             "to pending", exc, decision_id)
                if not self._write_pending(current):
                    # Both writes failed: the decision is gone from disk and
                    # unlogged. Nothing further can be done here, but it must
                    # not be reported as a recorded choice.
                    _log.error("record_choice %s: log append AND pending "
                               "restore both failed - choice LOST", decision_id)
                return None
            return entry


# -- Loop ----------------------------------------------------------------------

class DecisionLoop:
    """Daemon thread: poll state, run detectors, reconcile pending."""

    def __init__(self, store: Optional[DecisionStore] = None,
                 poll_interval_s: float = _DEFAULT_POLL_S) -> None:
        self._store = store or DecisionStore()
        self._poll_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Per-game rate-cap state (reset on game-time reversal).
        self._game_decisions = 0
        self._last_new_t = 0.0          # unix time of most recent NEW emit
        self._prev_game_time = 0.0      # for new-game detection
        # ADR-007 (s169): heartbeat counter - increments on each successful
        # eval-with-fresh-state, resets when a new game is detected. Exposed
        # via heartbeat() for the dashboard #trigger-pill so the operator
        # can glance over and confirm the loop is alive even when it's
        # silently deciding not to fire.
        self._eval_count = 0
        self._last_eval_unix = 0.0
        # Lane-8 cycle 12: detector exceptions were swallowed per-detector at
        # DEBUG while the pill went on reporting alive with a cleanly rising
        # counter. Measured: an upstream shape change (events.Events arriving
        # as a str) crashed 2 of 6 detectors on EVERY tick and nothing in the
        # heartbeat could say so. The pill exists precisely so the operator
        # can tell "alive and deciding not to fire" from dead - it must also
        # separate that from "alive and crashing".
        self._detector_errors = 0
        self._last_detector_error: Optional[str] = None
        # Log-spam control for the above - see _loop.
        self._last_logged_error_sig: Optional[tuple] = None
        self._last_error_log_m = 0.0
        self._heartbeat_lock = threading.Lock()

    def store(self) -> DecisionStore:
        return self._store

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="decision-detector", daemon=True)
        self._thread.start()
        _log.info("decision_detector started (poll=%.2fs, detectors=%d)",
                  self._poll_s, len(DECISION_REGISTRY))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _fetch_snapshot(self) -> tuple[Optional[dict], float]:
        # 2026-05-01: pulled off direct HTTP onto the shared liveclient_cache
        # (core/liveclient_cache.py) so a single background poll feeds all
        # consumers instead of each thread hitting the relay on its own.
        from core.liveclient_cache import get as _lc_get
        snap = _lc_get()
        if snap.data is None:
            return None, 0.0
        return snap.data, snap.age_s

    def _read_vision_state(self) -> dict:
        try:
            return json.loads(_VISION_STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _apply_rate_cap(self, fresh: list[Decision]) -> list[Decision]:
        """Drop NEW decision ids past the per-game cap or before the
        min-gap window. Existing pending ids pass through unconditionally
        so an active decision never gets evicted by the cap."""
        if not fresh:
            return fresh
        existing_ids = {d["id"] for d in self._store.list_pending()}
        kept: list[Decision] = []
        now = time.time()
        for d in fresh:
            if d.id in existing_ids:
                kept.append(d)            # already pending - pass through
                continue
            if self._game_decisions >= _MAX_PER_GAME:
                _log.debug("rate-cap: dropping %s (per-game max)", d.id)
                continue
            if (now - self._last_new_t) < _MIN_GAP_S:
                _log.debug("rate-cap: dropping %s (min-gap)", d.id)
                continue
            kept.append(d)
            self._game_decisions += 1
            self._last_new_t = now
        return kept

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap, age = self._fetch_snapshot()
                if snap is None or age > _RELAY_MAX_AGE_S:
                    # No game (or stale) - clear any stale pending and idle.
                    if self._store.list_pending():
                        self._store.reconcile([], game_time=10**9)
                    self._stop.wait(self._poll_s)
                    continue
                vs = self._read_vision_state()
                # RM-318: same coercion the detectors use. This read sat
                # OUTSIDE the per-detector try/except, so a retyped
                # gameTime raised into the loop's own broad handler and
                # skipped the whole tick - reconcile included - rather
                # than costing one detector.
                game_time = _game_time(snap)
                # Reset per-game cap on a backwards game-time jump
                # (new match) or a resync from 0.
                if game_time + 5 < self._prev_game_time:
                    self._game_decisions = 0
                    self._last_new_t = 0.0
                    # ADR-007 (s169): also reset heartbeat counter on new
                    # match so the dashboard pill starts from 0 each game.
                    with self._heartbeat_lock:
                        self._eval_count = 0
                        self._detector_errors = 0
                        self._last_detector_error = None
                self._prev_game_time = game_time
                fresh: list[Decision] = []
                errors = 0
                last_error: Optional[str] = None
                for fn in DECISION_REGISTRY:
                    try:
                        d = fn(snap, vs)
                        if d is not None:
                            fresh.append(d)
                    except Exception as exc:  # noqa: BLE001
                        errors += 1
                        # Truncated: this string is served by
                        # /api/decisions/heartbeat, and an exception message
                        # can quote snapshot data (a Riot ID in a KeyError).
                        last_error = (
                            f"{fn.__name__}: {type(exc).__name__}: "
                            f"{exc}"[:_MAX_ERR_CHARS]
                        )
                        _log.debug("detector %s failed: %s", fn.__name__, exc)
                if errors:
                    # A detector crashing is a shape change upstream, not a
                    # debug detail - but the loop ticks at 1 Hz, so logging
                    # every failing eval would write ~3600 WARNING lines an
                    # hour for one persistent breakage. Log on CHANGE of
                    # signature, then at most once a minute after that.
                    sig = (errors, last_error)
                    now_m = time.monotonic()
                    if (sig != self._last_logged_error_sig
                            or now_m - self._last_error_log_m >= 60.0):
                        _log.warning(
                            "%d/%d detectors failed this eval (last: %s)",
                            errors, len(DECISION_REGISTRY), last_error)
                        self._last_logged_error_sig = sig
                        self._last_error_log_m = now_m
                elif self._last_logged_error_sig is not None:
                    _log.info("detectors recovered - all %d evaluating again",
                              len(DECISION_REGISTRY))
                    self._last_logged_error_sig = None
                fresh = self._apply_rate_cap(fresh)
                self._store.reconcile(fresh, game_time)
                # Heartbeat: bump AFTER a successful eval cycle, then
                # persist so the dashboard (RC main process) can read it.
                with self._heartbeat_lock:
                    self._eval_count += 1
                    self._last_eval_unix = time.time()
                    self._detector_errors = errors
                    self._last_detector_error = last_error
                self._write_heartbeat()
            except Exception as exc:  # noqa: BLE001
                _log.debug("decision_detector loop: %s", exc)
            self._stop.wait(self._poll_s)

    def _write_heartbeat(self) -> None:
        """Persist heartbeat to data/decisions_heartbeat.json so the
        dashboard handler in the RC main process can read it without
        IPC into the Phase 3 supervisor. Atomic via tmp + replace."""
        # Same WinError-5 hazard as DecisionStore._write_pending - the
        # dashboard polls this file at ~2 Hz from the RC main process, so a
        # bare replace dropped heartbeats whenever a poll overlapped a write.
        try:
            atomic_write_json(_HEARTBEAT_PATH, self.heartbeat())
        except (OSError, TypeError, ValueError) as exc:
            _log.debug("heartbeat write failed: %s", exc)

    def heartbeat(self) -> dict:
        """ADR-007 (s169): glanceable liveness snapshot for the dashboard
        pill. Pure read; safe to call from the dashboard handler thread.

        Returns:
            counter:             eval cycles in current match (resets on new game)
            last_eval_unix:      wall-clock time of most recent eval
            age_s:               seconds since last eval (None if never ran)
            alive:               bool - true when age_s < 5
            game_time:           last observed game_time (0 when no game)
            detectors:           count of registered detectors
            detector_errors:     detectors that raised during the last eval
            last_detector_error: "<fn>: <ExcType>: <msg>" for the last one
        """
        with self._heartbeat_lock:
            count = self._eval_count
            last = self._last_eval_unix
            game_t = self._prev_game_time
            errors = self._detector_errors
            last_err = self._last_detector_error
        now = time.time()
        age_s = (now - last) if last > 0 else None
        alive = age_s is not None and age_s < 5.0
        return {
            "counter": count,
            "last_eval_unix": last if last > 0 else None,
            "age_s": round(age_s, 2) if age_s is not None else None,
            "alive": alive,
            "game_time": round(game_t, 1),
            "detectors": len(DECISION_REGISTRY),
            "detector_errors": errors,
            "last_detector_error": last_err,
        }


# Module singleton
_singleton: Optional[DecisionLoop] = None


def get_loop() -> DecisionLoop:
    global _singleton
    if _singleton is None:
        _singleton = DecisionLoop()
    return _singleton


def read_heartbeat() -> dict:
    """ADR-007 (s169): file-backed heartbeat read for the dashboard
    handler (RC main process - separate from the Phase 3 supervisor
    process that owns the loop singleton).

    Returns the same shape as DecisionLoop.heartbeat(); when the file
    doesn't exist yet (no eval has run since boot) returns a sentinel
    with alive=False so the dashboard pill still renders something
    meaningful.

    Recomputes age_s + alive at read time so the dashboard can detect
    the supervisor stopping (stale file, alive flips False) without the
    loop re-writing on every tick."""
    def _sentinel() -> dict:
        return {
            "counter": 0,
            "last_eval_unix": None,
            "age_s": None,
            "alive": False,
            "game_time": 0.0,
            "detectors": len(DECISION_REGISTRY),
            "detector_errors": 0,
            "last_detector_error": None,
        }

    try:
        raw = json.loads(_HEARTBEAT_PATH.read_text(encoding="utf-8"))
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        return _sentinel()
    except OSError as exc:
        _log.debug("heartbeat read failed: %s", exc)
        return _sentinel()
    if not isinstance(raw, dict):
        _log.warning("heartbeat file is %s, not a dict", type(raw).__name__)
        return _sentinel()
    # A file written by a pre-cycle-12 loop carries neither new key; the
    # dashboard route reads this shape directly, so backfill rather than
    # let it KeyError.
    raw.setdefault("detector_errors", 0)
    raw.setdefault("last_detector_error", None)
    last = raw.get("last_eval_unix")
    if isinstance(last, (int, float)) and last > 0:
        age_s = time.time() - float(last)
        raw["age_s"] = round(age_s, 2)
        raw["alive"] = age_s < 5.0
    else:
        raw["age_s"] = None
        raw["alive"] = False
    return raw
