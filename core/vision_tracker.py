"""
core/vision_tracker.py - fog-of-war state derivation from Live Client.

The Live Client API only updates a champion's `position` when YOUR team
has vision on them. Position freezes when they enter fog. By watching
which positions tick vs. stall frame-to-frame, we can derive a complete
visibility model with last-seen timestamps and zones - strictly free
data the coach prompts and minimap overlay can both consume.

Output: data/vision_state.json (atomic write). Polled by the dashboard
overlay layer and read by coach prompt builders.

Run as a background daemon thread; see VisionTracker.start_background().
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("rc.vision_tracker")
_APP_DIR = Path(__file__).parent.parent

# Position delta below this counts as "did not move" (in League map units).
# Champions almost never stay perfectly still in real games - AAs and kiting
# generate constant micro-movement when in vision - so a small threshold is
# a reliable proxy for "engine update happened."
_POS_EPSILON = 5.0

# Seconds of position-stall before we flip `visible` to False. Short enough
# to catch a champ slipping into a brushed bush, long enough to tolerate
# the natural ~1s relay polling cadence.
_VISIBILITY_STALL_S = 2.5

# Stale-snapshot threshold - anything older than this is treated as
# "no game / relay dead" and triggers a tracked-state reset.
_RELAY_MAX_AGE_S = 8.0

# Default poll interval when running as background daemon. Matches the
# Game-PC liveclient relay's own ~1s cadence - going faster wastes CPU
# without surfacing new data.
_DEFAULT_POLL_S = 0.75

# Modes with shared lane vision - every alive enemy is map-visible by design,
# so position tracking can't derive fog (and Live Client emits position="NONE"
# anyway). KIWI is the internal name for ARAM Mayhem.
_SHARED_VISION_MODES = frozenset({"ARAM", "KIWI"})


# -- Zone labelling ------------------------------------------------------------
# League SR map is roughly 14800x14800 game units, origin at Order/Blue base
# corner. These zone bounds are coarse on purpose - the goal is a human-readable
# label for prompts ("last seen at mid_river"), not pinpoint accuracy.

def _sr_zone(x: float, z: float) -> str:
    if x < 3500 and z < 3500:
        return "blue_base"
    if x > 11000 and z > 11000:
        return "red_base"
    # Diagonal corridors
    if abs(x - z) < 2200:
        if x < 6000:
            return "blue_mid"
        if x > 9000:
            return "red_mid"
        return "mid"
    # Top lane = high z, low x
    if z > 10000 and x < 4500:
        return "top_lane"
    # Bot lane = low z, high x
    if x > 10000 and z < 4500:
        return "bot_lane"
    # River (anti-diagonal): x + z ~ 14800, +/- band
    if abs((x + z) - 14800) < 2400:
        if x < 7400:
            return "top_river"
        return "bot_river"
    # Objective pits (approximate)
    if 4000 < x < 6500 and 9500 < z < 11500:
        return "baron_pit"
    if 9500 < x < 11500 and 4000 < z < 6500:
        return "dragon_pit"
    # Jungle quadrants - fall through
    if x < 7400 and z > 7400:
        return "blue_top_jungle"
    if x < 7400 and z < 7400:
        return "blue_bot_jungle"
    if x > 7400 and z > 7400:
        return "red_top_jungle"
    return "red_bot_jungle"


def _aggregator_k(x: float, z: float) -> str:
    # Howling Abyss is one diagonal lane. Position progression along the
    # bridge maps cleanly to "near my base / mid bridge / near enemy base"
    # but we don't know which side the viewer is on at zone-time, so just
    # report bridge position as a percent of map traversal.
    pct = max(0, min(100, int((x + z) / 296)))   # 14800/50 ~ 296
    if pct < 25:
        return "blue_side_bridge"
    if pct > 75:
        return "red_side_bridge"
    return "mid_bridge"


_ZONE_FN = {
    "CLASSIC":  _sr_zone,
    "ARAM":     _aggregator_k,
    "KIWI":     _aggregator_k,   # ARAM Mayhem
    "URF":      _sr_zone,
    "ULTBOOK":  _sr_zone,
    "ONEFORALL": _sr_zone,
    "NEXUSBLITZ": _sr_zone,
    "PRACTICETOOL": _sr_zone,
}


def _zone_for(mode: str, x: float, z: float) -> str:
    fn = _ZONE_FN.get(mode.upper(), _sr_zone)
    return fn(x, z)


# -- Tracker -------------------------------------------------------------------

class VisionTracker:
    """Stateful derivation: ingest Live Client snapshots, emit fog-of-war
    visibility per enemy. Output via atomic write to vision_state.json."""

    def __init__(self, output_path: Optional[Path] = None,
                 poll_interval_s: float = _DEFAULT_POLL_S) -> None:
        self._out = Path(output_path) if output_path else _APP_DIR / "data" / "vision_state.json"
        self._poll_s = poll_interval_s
        self._state: dict = {}              # last published state
        self._tracked: dict = {}            # internal per-enemy state
        self._active_team: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[Any] = None  # asyncio.Task / Future
        self._lock = threading.Lock()

    # -- Public API --------------------------------------------------------

    def ingest(self, snapshot: dict, t_now: Optional[float] = None) -> None:
        """Process one Live Client snapshot. Updates internal state and
        the public `state()` dict; does NOT write to disk (start_background
        handles disk writes on its own cadence)."""
        if not isinstance(snapshot, dict):
            return
        if t_now is None:
            t_now = time.time()

        game_data = snapshot.get("gameData") or {}
        game_time = float(game_data.get("gameTime", 0.0))
        game_mode = str(game_data.get("gameMode", "CLASSIC"))

        active = snapshot.get("activePlayer") or {}
        all_players = [p for p in (snapshot.get("allPlayers") or []) if isinstance(p, dict)]

        active_team = self._identify_team(active, all_players)
        if active_team:
            self._active_team = active_team

        enemies = self._compute_enemies(all_players, game_time, game_mode)

        summary = {
            "visible_count": sum(1 for e in enemies.values() if e["visible"] and not e["is_dead"]),
            "missing_count": sum(1 for e in enemies.values() if not e["visible"] and not e["is_dead"]),
            "dead_count":    sum(1 for e in enemies.values() if e["is_dead"]),
            "total":         len(enemies),
        }

        with self._lock:
            self._state = {
                "t_now":         t_now,
                "game_time":     game_time,
                "game_mode":     game_mode,
                "active_team":   self._active_team,
                "enemies":       enemies,
                "summary":       summary,
            }

    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def reset(self) -> None:
        """Clear all tracked state (call between games)."""
        with self._lock:
            self._tracked.clear()
            self._state = {}
            self._active_team = None

    def start_background(self) -> None:
        """Launch the relay poller. Prefers spawning on the main AppLoop;
        falls back to a daemon thread when no loop exists."""
        if (self._thread and self._thread.is_alive()) or self._task is not None:
            return
        self._stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:  # noqa: BLE001
            _sched = None
        if _sched is not None:
            self._task = _sched.spawn_task(self._loop_async())
            _log.info("vision_tracker started (poll=%.2fs, out=%s, async)", self._poll_s, self._out)
        else:
            self._thread = threading.Thread(target=self._loop, name="vision-tracker", daemon=True)
            self._thread.start()
            _log.info("vision_tracker started (poll=%.2fs, out=%s, thread)", self._poll_s, self._out)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass  # noqa: BLE001
            self._task = None

    # -- Internals ---------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap, age = self._fetch_snapshot()
                if snap is None:
                    self._stop.wait(self._poll_s)
                    continue
                if age > _RELAY_MAX_AGE_S:
                    # Game ended or relay dead - reset so we don't carry
                    # stale tracked positions into the next game.
                    if self._tracked:
                        _log.info("vision_tracker: relay stale (%.1fs), resetting tracked state", age)
                        self.reset()
                    self._stop.wait(self._poll_s)
                    continue
                self.ingest(snap)
                self._write_atomic()
            except Exception as exc:  # noqa: BLE001
                _log.debug("vision_tracker loop: %s", exc)
            self._stop.wait(self._poll_s)

    async def _loop_async(self) -> None:
        # _fetch_snapshot reads from the in-memory liveclient_cache (fast);
        # ingest + _write_atomic are dict transforms + a tmp-file replace
        # (also fast). All inline - no to_thread needed.
        while not self._stop.is_set():
            try:
                snap, age = self._fetch_snapshot()
                if snap is None:
                    pass
                elif age > _RELAY_MAX_AGE_S:
                    if self._tracked:
                        _log.info("vision_tracker: relay stale (%.1fs), resetting tracked state", age)
                        self.reset()
                else:
                    self.ingest(snap)
                    self._write_atomic()
            except Exception as exc:  # noqa: BLE001
                _log.debug("vision_tracker loop: %s", exc)
            try:
                await asyncio.sleep(self._poll_s)
            except asyncio.CancelledError:
                return

    def _fetch_snapshot(self) -> tuple[Optional[dict], float]:
        # 2026-05-01: pulled off direct HTTP onto the shared liveclient_cache
        # (core/liveclient_cache.py) so a single background poll feeds all
        # consumers instead of each thread hitting the relay on its own.
        from core.liveclient_cache import get as _lc_get
        snap = _lc_get()
        if snap.data is None:
            return None, 0.0
        return snap.data, snap.age_s

    def _identify_team(self, active: dict, all_players: list) -> Optional[str]:
        """Return 'ORDER' or 'CHAOS' for the active player."""
        # Try direct match by various name fields
        candidates = set()
        for k in ("riotIdGameName", "summonerName", "riotIdPlusTagLine"):
            v = active.get(k)
            if isinstance(v, str) and v:
                candidates.add(v.lower().strip())
        active_champ = active.get("championName", "")
        for p in all_players:
            for k in ("riotIdGameName", "summonerName", "riotIdPlusTagLine"):
                pv = p.get(k)
                if isinstance(pv, str) and pv.lower().strip() in candidates:
                    return p.get("team", "ORDER")
            if active_champ and p.get("championName") == active_champ:
                return p.get("team", "ORDER")
        return None

    def _compute_enemies(self, all_players: list, game_time: float,
                         game_mode: str) -> dict:
        if not self._active_team:
            return {}
        enemies = [p for p in all_players if p.get("team") and p.get("team") != self._active_team]
        shared_vision = game_mode.upper() in _SHARED_VISION_MODES
        out: dict = {}
        for p in enemies:
            champ = p.get("championName") or "?"
            key = champ  # Champion name is unique within a match
            # Live Client emits `position: "NONE"` (string) in ARAM and on
            # dead/loading players in SR - `or {}` doesn't catch it because
            # the string is truthy. isinstance guard keeps `pos.get(...)`
            # below from raising "'str' object has no attribute 'get'".
            pos = p.get("position")
            if not isinstance(pos, dict):
                pos = {}
            x = float(pos.get("x", 0.0))
            z = float(pos.get("z", 0.0))
            is_dead = bool(p.get("isDead", False))
            level = int(p.get("level", 0) or 0)

            tracked = self._tracked.setdefault(key, {
                "last_pos": None,         # (x, z) of last accepted broadcast
                "last_seen_t": None,      # game_time at last position-tick
                "last_seen_zone": None,
                "last_visible": False,
            })

            visible = False
            if is_dead:
                # Death is its own state; don't update last_seen on respawn-pos jumps
                visible = False
            elif shared_vision:
                # ARAM-style: every alive enemy is on-map by design; position
                # data is "NONE" so we can't derive a real zone, but stamp a
                # constant label + current game_time so consumers (minimap
                # caption, coach prompts) see meaningful "alive on bridge"
                # state instead of None.
                visible = True
                tracked["last_seen_t"] = game_time
                tracked["last_seen_zone"] = "on_bridge"
            else:
                if tracked["last_pos"] is None:
                    # First sighting of this champion
                    if x != 0.0 or z != 0.0:
                        tracked["last_pos"] = (x, z)
                        tracked["last_seen_t"] = game_time
                        tracked["last_seen_zone"] = _zone_for(game_mode, x, z)
                        visible = True
                else:
                    lx, lz = tracked["last_pos"]
                    moved = ((x - lx) ** 2 + (z - lz) ** 2) ** 0.5 >= _POS_EPSILON
                    if moved:
                        tracked["last_pos"] = (x, z)
                        tracked["last_seen_t"] = game_time
                        tracked["last_seen_zone"] = _zone_for(game_mode, x, z)
                        visible = True
                    else:
                        # Position frozen - if recent, still call it visible;
                        # if stale, fog of war.
                        elapsed = game_time - (tracked["last_seen_t"] or game_time)
                        visible = elapsed < _VISIBILITY_STALL_S

            tracked["last_visible"] = visible

            missing_for_s = None
            if not visible and tracked["last_seen_t"] is not None:
                missing_for_s = max(0.0, game_time - tracked["last_seen_t"])

            respawn_in_s = None
            if is_dead:
                rt = p.get("respawnTimer")
                if isinstance(rt, (int, float)) and rt > 0:
                    respawn_in_s = float(rt)

            last_pos = tracked["last_pos"]
            out[key] = {
                "champion":       champ,
                "summoner_name":  p.get("summonerName") or p.get("riotIdGameName") or "",
                "team":           p.get("team", ""),
                "level":          level,
                "is_dead":        is_dead,
                "respawn_in_s":   respawn_in_s,
                "visible":        visible,
                "missing_for_s":  round(missing_for_s, 1) if missing_for_s is not None else None,
                "last_seen_pos":  {"x": last_pos[0], "z": last_pos[1]} if last_pos else None,
                "last_seen_t":    tracked["last_seen_t"],
                "last_seen_zone": tracked["last_seen_zone"],
            }
        return out

    def _write_atomic(self) -> None:
        try:
            tmp = self._out.with_suffix(self._out.suffix + ".tmp")
            self._out.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self.state(), indent=2), encoding="utf-8")
            tmp.replace(self._out)
        except Exception as exc:  # noqa: BLE001
            _log.debug("vision_state write failed: %s", exc)


# Module-level singleton + convenience launcher
_singleton: Optional[VisionTracker] = None


def get_tracker() -> VisionTracker:
    global _singleton
    if _singleton is None:
        _singleton = VisionTracker()
    return _singleton
