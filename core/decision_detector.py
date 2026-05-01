"""
core/decision_detector.py — coachable-moment detection + recording.

Watches live game state (Live Client snapshots via the relay + vision_tracker
output) and emits "decisions" — moments where the player has a meaningful
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

V1 ships with one detector: `detect_objective_contest_with_missing` —
fires when an objective spawns within ~60s and ≥2 enemies are missing.

2-PC dependency note
--------------------
Live Client data arrives via the Legion-local relay endpoint
http://127.0.0.1:8889/latest-liveclient. The relay is fed by the Game-PC
liveclient agent (TODO: hard 2-PC dependency — if Game-PC goes offline,
detectors stop firing because the snapshot ages out). Vision state is
read from data/vision_state.json on Legion (same path). No Game-PC paths
are referenced from this module.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

_log = logging.getLogger("rc.decision_detector")
_APP_DIR = Path(__file__).parent.parent

# Endpoints + paths (all Legion-local; no Game-PC hardcoded paths).
_RELAY_URL        = "http://127.0.0.1:8889/latest-liveclient"
_RELAY_TIMEOUT    = 2.0
_RELAY_MAX_AGE_S  = 8.0
_VISION_STATE     = _APP_DIR / "data" / "vision_state.json"
_PENDING_PATH     = _APP_DIR / "data" / "decisions_pending.json"
_LOG_PATH         = _APP_DIR / "data" / "decisions_log.jsonl"

_DEFAULT_POLL_S   = 1.0

# Global rate cap (per-game): never spam more than _MAX_PER_GAME total
# decisions, never less than _MIN_GAP_S between two NEW decision ids
# entering the pending list. Re-fires of an id already in pending don't
# count — those just keep the existing decision alive.
_MAX_PER_GAME     = 5
_MIN_GAP_S        = 30.0


# ── Data shape ────────────────────────────────────────────────────────────────

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


# ── Detector registry ─────────────────────────────────────────────────────────

DetectorFn = Callable[[dict, dict], Optional[Decision]]
DECISION_REGISTRY: list[DetectorFn] = []


def register_detector(fn: DetectorFn) -> DetectorFn:
    """Decorator (or plain call) to add a detector to the registry."""
    DECISION_REGISTRY.append(fn)
    return fn


# ── Helpers ───────────────────────────────────────────────────────────────────
# Approximate spawn timings for SR (2026 patch). First-spawn / respawn pairs.
# Atakhan currently replaces Herald — skipped here pending mode-aware logic.

_DRAGON_FIRST_S    = 300.0
_DRAGON_RESPAWN_S  = 300.0
_BARON_FIRST_S     = 1200.0
_BARON_RESPAWN_S   = 360.0


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
        return first_at if game_time < first_at else first_at  # not yet killed
    return last_kill_t + respawn


# ── Detector: objective contest with missing enemies ──────────────────────────

@register_detector
def detect_objective_contest_with_missing(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """Trigger when a major objective spawns within ~60s AND ≥2 enemies
    are missing per vision_tracker. Player decides contest vs give."""
    game_data = snapshot.get("gameData") or {}
    game_time = float(game_data.get("gameTime", 0.0))
    events = (snapshot.get("events") or {}).get("Events") or []

    # Skip non-SR modes — Dragon/Baron only exist there.
    mode = str(game_data.get("gameMode", "")).upper()
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

    enemies = (vision_state or {}).get("enemies") or {}
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
    title = f"{name} {when} — {len(missing)} enemies missing"
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


# ── Detector: low HP, time to back? ───────────────────────────────────────────

@register_detector
def detect_low_hp_backable(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """Self HP <40% and alive ≥45s past last respawn → back vs push.

    Bucket the id to 60-second windows so a single drawn-out low-HP
    episode doesn't re-prompt every tick."""
    active = snapshot.get("activePlayer") or {}
    stats = active.get("championStats") or {}
    cur = float(stats.get("currentHealth") or 0.0)
    mx = float(stats.get("maxHealth") or 0.0)
    if mx <= 0:
        return None
    pct = cur / mx
    if pct >= 0.40:
        return None

    game_data = snapshot.get("gameData") or {}
    game_time = float(game_data.get("gameTime", 0.0))
    if game_time < 90:        # nothing to back to in the first 90s
        return None

    # Find self in allPlayers to confirm alive + measure time since last death.
    self_name = active.get("summonerName") or active.get("riotIdGameName")
    all_players = snapshot.get("allPlayers") or []
    me = None
    for p in all_players:
        nm = p.get("summonerName") or p.get("riotIdGameName")
        if nm == self_name:
            me = p
            break
    if not me or me.get("isDead"):
        return None

    # Walk events for our deaths; require ≥45s alive.
    events = (snapshot.get("events") or {}).get("Events") or []
    last_death_t = 0.0
    for ev in events:
        if (ev.get("EventName") == "ChampionKill"
                and ev.get("VictimName") == self_name):
            t = ev.get("EventTime")
            if isinstance(t, (int, float)) and t > last_death_t:
                last_death_t = float(t)
    alive_for = game_time - last_death_t
    if alive_for < 45:
        return None

    bucket = int(game_time // 60)
    pct_int = int(round(pct * 100))
    return Decision(
        id=f"low_hp_back:{bucket}",
        type="low_hp_back",
        title=f"{pct_int}% HP — back or stay?",
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


# ── Detector: lane roam window (≥2 enemies missing, no objective in window) ──

@register_detector
def detect_lane_roam_window(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """≥2 enemies missing 12s+ AND no objective contest is the right
    framing (deferred to detect_objective_contest_with_missing) → the
    player has a roam-or-push window. Bucketed to 90s windows."""
    game_data = snapshot.get("gameData") or {}
    game_time = float(game_data.get("gameTime", 0.0))
    if game_time < 240:    # roams matter past ~4min
        return None
    mode = str(game_data.get("gameMode", "")).upper()
    if mode and mode != "CLASSIC":
        return None     # ARAM has no roams

    # If a major objective is in the contest window, the contest detector
    # owns this signal — don't double-prompt.
    events = (snapshot.get("events") or {}).get("Events") or []
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

    enemies = (vision_state or {}).get("enemies") or {}
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
        title=f"{len(missing_long)} enemies missing — roam or push?",
        subtitle="Missing: " + ", ".join(missing_long),
        options=["roam", "push"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=game_time + 25,
        context={"missing": missing_long},
    )


# ── Detector: post-fight objective opportunity ────────────────────────────────

@register_detector
def detect_postfight_objective(
    snapshot: dict, vision_state: dict
) -> Optional[Decision]:
    """In the last 20s of game time, ally team has a +3 (or better) kill
    differential AND a major objective is alive within ~30s. Player has
    to choose: take the objective with tempo, or cross-map for towers."""
    game_data = snapshot.get("gameData") or {}
    game_time = float(game_data.get("gameTime", 0.0))
    if game_time < 600:    # post-fight objectives are mid+ game
        return None
    mode = str(game_data.get("gameMode", "")).upper()
    if mode and mode != "CLASSIC":
        return None

    active = snapshot.get("activePlayer") or {}
    self_name = active.get("summonerName") or active.get("riotIdGameName")
    all_players = snapshot.get("allPlayers") or []
    self_team = None
    for p in all_players:
        if (p.get("summonerName") or p.get("riotIdGameName")) == self_name:
            self_team = p.get("team")
            break
    if not self_team:
        return None

    # Walk events: count ally kills minus ally deaths in the last 20s.
    events = (snapshot.get("events") or {}).get("Events") or []
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
        # Resolve the killer's team. The Live Client gives KillerName as a
        # summoner; cross-reference allPlayers.
        killer = ev.get("KillerName")
        victim = ev.get("VictimName")
        for p in all_players:
            nm = p.get("summonerName") or p.get("riotIdGameName")
            if nm == killer:
                diff += (1 if p.get("team") == self_team else -1)
                break
        for p in all_players:
            nm = p.get("summonerName") or p.get("riotIdGameName")
            if nm == victim:
                diff += (-1 if p.get("team") == self_team else 1)
                break
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
        title=f"+{diff} fight, {obj_name} live — take or cross-map?",
        subtitle=f"ally kill diff {diff:+d} in last 20s · {obj_name} window open",
        options=["take", "cross-map"],
        created_at_unix=time.time(),
        created_at_game_time=game_time,
        expires_at_game_time=game_time + 35,
        context={"kill_diff": diff, "objective": obj_name},
    )


# ── Store ─────────────────────────────────────────────────────────────────────

class DecisionStore:
    """Atomic file-backed pending list + append-only history log."""

    def __init__(self, pending_path: Path = _PENDING_PATH,
                 log_path: Path = _LOG_PATH):
        self._pending_path = pending_path
        self._log_path = log_path
        self._lock = threading.Lock()

    def list_pending(self) -> list[dict]:
        try:
            return json.loads(self._pending_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        except Exception as exc:
            _log.debug("pending read failed: %s", exc)
            return []

    def _write_pending(self, items: list[dict]) -> None:
        try:
            self._pending_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._pending_path.with_suffix(self._pending_path.suffix + ".tmp")
            tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
            tmp.replace(self._pending_path)
        except Exception as exc:
            _log.debug("pending write failed: %s", exc)

    def reconcile(self, fresh: list[Decision], game_time: float) -> None:
        """Merge newly-detected decisions into the pending list:
          - keep any pending decision whose id appears in `fresh` (still triggering)
          - drop pending decisions whose expires_at_game_time < game_time
          - drop pending decisions whose id no longer appears in `fresh`
            (condition lifted — e.g., enemies became visible again)
          - add new ids from `fresh`
        """
        fresh_ids = {d.id for d in fresh}
        with self._lock:
            current = self.list_pending()
            cur_by_id = {d["id"]: d for d in current}
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

    def record_choice(self, decision_id: str, choice: str,
                      extra: Optional[dict] = None) -> Optional[dict]:
        """Move a pending decision to the log with the player's choice.
        Returns the recorded entry or None if id not found."""
        with self._lock:
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
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as exc:
                _log.warning("decisions_log append failed: %s", exc)
            self._write_pending(remaining)
            return entry


# ── Loop ──────────────────────────────────────────────────────────────────────

class DecisionLoop:
    """Daemon thread: poll state, run detectors, reconcile pending."""

    def __init__(self, store: Optional[DecisionStore] = None,
                 poll_interval_s: float = _DEFAULT_POLL_S):
        self._store = store or DecisionStore()
        self._poll_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Per-game rate-cap state (reset on game-time reversal).
        self._game_decisions = 0
        self._last_new_t = 0.0          # unix time of most recent NEW emit
        self._prev_game_time = 0.0      # for new-game detection

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
        try:
            from core.vision_token import get_vision_token
            req = Request(_RELAY_URL, headers={"X-RC-Token": get_vision_token()})
            with urlopen(req, timeout=_RELAY_TIMEOUT) as r:
                wrap = json.loads(r.read())
        except Exception:
            return None, 0.0
        if not isinstance(wrap, dict):
            return None, 0.0
        data = wrap.get("data")
        ts = float(wrap.get("ts") or 0)
        if not isinstance(data, dict):
            return None, 0.0
        age = max(0.0, time.time() - ts) if ts else 0.0
        return data, age

    def _read_vision_state(self) -> dict:
        try:
            return json.loads(_VISION_STATE.read_text(encoding="utf-8"))
        except Exception:
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
                kept.append(d)            # already pending — pass through
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
                    # No game (or stale) — clear any stale pending and idle.
                    if self._store.list_pending():
                        self._store.reconcile([], game_time=10**9)
                    self._stop.wait(self._poll_s)
                    continue
                vs = self._read_vision_state()
                game_time = float((snap.get("gameData") or {}).get("gameTime", 0.0))
                # Reset per-game cap on a backwards game-time jump
                # (new match) or a resync from 0.
                if game_time + 5 < self._prev_game_time:
                    self._game_decisions = 0
                    self._last_new_t = 0.0
                self._prev_game_time = game_time
                fresh: list[Decision] = []
                for fn in DECISION_REGISTRY:
                    try:
                        d = fn(snap, vs)
                        if d is not None:
                            fresh.append(d)
                    except Exception as exc:
                        _log.debug("detector %s failed: %s", fn.__name__, exc)
                fresh = self._apply_rate_cap(fresh)
                self._store.reconcile(fresh, game_time)
            except Exception as exc:
                _log.debug("decision_detector loop: %s", exc)
            self._stop.wait(self._poll_s)


# Module singleton
_singleton: Optional[DecisionLoop] = None


def get_loop() -> DecisionLoop:
    global _singleton
    if _singleton is None:
        _singleton = DecisionLoop()
    return _singleton
