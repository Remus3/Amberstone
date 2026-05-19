# arch: raw JSON → snapshot dataclass | section=vision | frozen=yes
"""
core/game_snapshot.py
Phase 1 Step 3 - Mode-aware state envelope and payload types.

Defines the authoritative GameEnvelope and four mode-specific payload types.
All types use __slots__ for memory efficiency but are NOT frozen or immutable:
callers can assign to any slot directly. Mutation safety is enforced externally
by app.get_snapshot(), which deep-copies the payload before returning it.

Single-writer rules (enforced by convention, not runtime locks):
  app.py              - owns the current GameEnvelope reference; updates it
                        on every game-state change and on mode transitions.
  game_reader.py      - primary writer of RiftSnapshot and AramSnapshot payloads
                        (via RiftSnapshot.from_state_dict / AramSnapshot.from_state_dict
                        and the three-tier factory helpers to_rift_snapshot /
                        to_aram_snapshot).
  app.py              - final emergency writer for SR/ARAM/Arena/Brawl payloads
                        when factory construction catastrophically fails (all three
                        factory tiers exhausted).  Calls
                        RiftSnapshot.emergency_raw_state_only() /
                        AramSnapshot.emergency_raw_state_only() to guarantee a
                        non-None payload for those modes.
  tft_state_reader.py - sole writer of TftSnapshot payloads
                        (via TftSnapshot.from_state_dict). Runtime wiring deferred to Step 5.
  app.py              - constructs ClientSnapshot directly for non-game state.

Consumers (coach_integration.py, ui/ panels, etc.) read payloads via
app.get_snapshot() and must not write to any snapshot field directly.

Python 3.9 compatible: no X|Y unions, no walrus, no match.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Dict, List, Optional


# AUDIT 2026-04-28 (deferred-frozen): raw_state was stored as a reference
# to the producer's dict, leaving it exposed to mutation after the
# snapshot was published. StateAuthority already deepcopies at consume
# time; this duplicates the safety at producer construction so a snapshot
# is independent the moment it leaves the factory. Marginal CPU; the
# defensive copy lives in one helper so we can swap to copy.copy()
# later if profiling justifies a shallow copy.
def _snapshot_copy(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if d is None:
        return None
    try:
        return copy.deepcopy(d)
    except Exception:
        # If a value isn't deepcopyable (e.g. a thread lock), fall back
        # to a shallow dict copy. Better than handing out the producer's
        # live reference.
        return dict(d)


# ---------------------------------------------------------------------------
# Mode constants - canonical string values used in GameEnvelope.mode
# ---------------------------------------------------------------------------

MODE_CLIENT = "client"
MODE_SR     = "SR"
MODE_ARAM   = "ARAM"
MODE_TFT    = "TFT"
MODE_ARENA  = "ARENA"
MODE_BRAWL  = "BRAWL"

# All valid mode strings
ALL_MODES = (MODE_CLIENT, MODE_SR, MODE_ARAM, MODE_TFT, MODE_ARENA, MODE_BRAWL)


def mode_from_game_mode_string(game_mode: str) -> str:
    """
    Derive the canonical mode string from a Riot game_mode string.
    Used by app.py when transitioning from client → in-game.

    Returns one of: MODE_SR, MODE_ARAM, MODE_TFT, MODE_ARENA, MODE_BRAWL.
    Defaults to MODE_SR for any unrecognised value.
    """
    gm = (game_mode or "").upper()
    if "TFT" in gm:
        return MODE_TFT
    # KIWI = ARAM Mayhem (Riot internal code name), ODIN = Dominion-era ARAM variant
    if gm in ("ARAM", "ARAM_UNRANKED_5X5", "KIWI", "ODIN") or gm.startswith("ARAM"):
        return MODE_ARAM
    if gm in ("ARENA", "CHERRY") or gm.startswith("ARENA"):
        return MODE_ARENA
    if any(gm.startswith(p) for p in (
        "NEXUSBLITZ", "NEXUS", "ULTBOOK", "URF", "ARURF",
        "GAMEMODEX", "ONEFORALL",
    )):
        return MODE_BRAWL
    return MODE_SR


# ---------------------------------------------------------------------------
# Payload types
# ---------------------------------------------------------------------------

class ClientSnapshot:
    """
    State during client / non-game mode.
    Written by app.py only.
    Fields are minimal - no game state exists in client mode.
    """
    __slots__ = ("timestamp",)

    def __init__(self, timestamp: Optional[float] = None) -> None:
        self.timestamp: float = timestamp if timestamp is not None else time.monotonic()

    def to_dict(self) -> Dict[str, Any]:
        return {"snapshot_type": "client", "timestamp": self.timestamp}


class RiftSnapshot:
    """
    Summoner's Rift game state.
    Written by game_reader.py only, via RiftSnapshot.from_state_dict().

    Fields are the subset of game_reader._process_game() output that are
    actually consumed by coaching and UI code.  The full raw dict is also
    stored in raw_state for legacy consumers that still iterate the dict.
    """
    __slots__ = (
        "timestamp",
        "game_mode",
        "game_time",
        "game_seconds",
        "champion",
        "level",
        "gold",
        "cs",
        "cs_per_min",
        "kda",
        "kills",
        "deaths",
        "assists",
        "hp_pct",
        "hp_abs",
        "hp_max",
        "mana_pct",
        "mp_abs",
        "mp_max",
        "items",
        "summoner_d",
        "summoner_f",
        "ally_comp",
        "enemy_comp",
        "ally_details",
        "enemy_details",
        "dead_enemies",
        "alive_enemies",
        "objectives",
        "obj_timers_dict",
        "risk_derived",
        "map_derived",
        "reset_derived",
        "gank_threat",
        "position_note",
        "ward_hint",
        "camp_hint",
        "ally_kills_total",
        "enemy_kills_total",
        "raw_state",
    )

    def __init__(self) -> None:
        self.timestamp:       float = 0.0
        self.game_mode:       str   = "CLASSIC"
        self.game_time:       str   = "0:00"
        self.game_seconds:    float = 0.0
        self.champion:        str   = ""
        self.level:           int   = 1
        self.gold:            int   = 0
        self.cs:              int   = 0
        self.cs_per_min:      float = 0.0
        self.kda:             str   = "0/0/0"
        self.kills:           int   = 0
        self.deaths:          int   = 0
        self.assists:         int   = 0
        self.hp_pct:          int   = 100
        self.hp_abs:          int   = 0
        self.hp_max:          int   = 1
        self.mana_pct:        int   = 100
        self.mp_abs:          int   = 0
        self.mp_max:          int   = 0
        self.items:           List[str] = []
        self.summoner_d:      str   = ""
        self.summoner_f:      str   = ""
        self.ally_comp:       List[str] = []
        self.enemy_comp:      List[str] = []
        self.ally_details:    List[Any] = []
        self.enemy_details:   List[Any] = []
        self.dead_enemies:    List[Any] = []
        self.alive_enemies:   List[Any] = []
        self.objectives:      str   = ""
        self.obj_timers_dict: Dict[str, Any] = {}
        self.risk_derived:    str   = ""
        self.map_derived:     str   = ""
        self.reset_derived:   str   = ""
        self.gank_threat:     str   = ""
        self.position_note:   str   = ""
        self.ward_hint:       str   = ""
        self.camp_hint:       str   = ""
        self.ally_kills_total:  int = 0
        self.enemy_kills_total: int = 0
        self.raw_state:       Optional[Dict[str, Any]] = None

    @classmethod
    def from_state_dict(cls, d: Dict[str, Any]) -> "RiftSnapshot":
        """
        Construct a RiftSnapshot from a game_reader._process_game() dict.
        Called only by game_reader.py.
        """
        s = cls()
        s.timestamp        = time.monotonic()
        s.game_mode        = d.get("game_mode", "CLASSIC")
        s.game_time        = d.get("game_time", "0:00")
        s.game_seconds     = float(d.get("game_seconds", 0))
        s.champion         = d.get("champion", "")
        s.level            = int(d.get("level", 1))
        s.gold             = int(d.get("gold", 0))
        s.cs               = int(d.get("cs", 0))
        s.cs_per_min       = float(d.get("cs_per_min", 0.0))
        s.kda              = d.get("kda", "0/0/0")
        s.kills            = int(d.get("kills", 0))
        s.deaths           = int(d.get("deaths", 0))
        s.assists          = int(d.get("assists", 0))
        s.hp_pct           = int(d.get("hp_pct", 100))
        s.hp_abs           = int(d.get("hp_abs", 0))
        s.hp_max           = int(d.get("hp_max", 1))
        s.mana_pct         = int(d.get("mana_pct", 100))
        s.mp_abs           = int(d.get("mp_abs", 0))
        s.mp_max           = int(d.get("mp_max", 0))
        s.items            = list(d.get("items", []))
        s.summoner_d       = d.get("summoner_d", "")
        s.summoner_f       = d.get("summoner_f", "")
        s.ally_comp        = list(d.get("ally_comp", []))
        s.enemy_comp       = list(d.get("enemy_comp", []))
        s.ally_details     = list(d.get("ally_details", []))
        s.enemy_details    = list(d.get("enemy_details", []))
        s.dead_enemies     = list(d.get("dead_enemies", []))
        s.alive_enemies    = list(d.get("alive_enemies", []))
        s.objectives       = d.get("objectives", "")
        s.obj_timers_dict  = dict(d.get("obj_timers_dict") or {})
        s.risk_derived     = d.get("risk_derived", "")
        s.map_derived      = d.get("map_derived", "")
        s.reset_derived    = d.get("reset_derived", "")
        s.gank_threat      = d.get("gank_threat", "")
        s.position_note    = d.get("position_note", "")
        s.ward_hint        = d.get("ward_hint", "")
        s.camp_hint        = d.get("camp_hint", "")
        s.ally_kills_total  = int(d.get("ally_kills_total", 0))
        s.enemy_kills_total = int(d.get("enemy_kills_total", 0))
        # AUDIT 2026-04-28 (deferred-frozen): producer-side defensive
        # copy so a snapshot is safe to publish even if the producer
        # keeps mutating its working dict.
        s.raw_state        = _snapshot_copy(d)
        return s

    @classmethod
    def emergency_raw_state_only(cls, state_dict: Dict[str, Any]) -> "RiftSnapshot":
        """
        Final-resort emergency constructor.  Produces a valid RiftSnapshot
        with raw_state set, bypassing __init__ entirely.  Called by app.py
        when all factory tiers AND the normal emergency __init__ path have
        failed (i.e. the RiftSnapshot class itself is broken).

        Two-layer internal strategy:
          Layer 1: object.__new__(cls) + normal slot assignment
          Layer 2: object.__new__(cls) + object.__setattr__()  - bypasses
                   any possible __setattr__ override on the class.

        Returns None ONLY if Python's allocator cannot produce ANY instance of
        this class - which is a fatal runtime condition, not a handled failure.
        After this method, payload=None for SR/ARAM/Arena/Brawl is impossible
        through any handled software failure path.
        """
        # AUDIT 2026-04-28 (deferred-frozen): copy here too - the
        # emergency path is rare, but if we ever take it the snapshot
        # should still be mutation-safe.
        copied = _snapshot_copy(state_dict)
        try:
            s = object.__new__(cls)
            s.raw_state = copied
            return s
        except Exception:
            pass
        try:
            s = object.__new__(cls)
            object.__setattr__(s, "raw_state", copied)
            return s
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_type":    "rift",
            "timestamp":        self.timestamp,
            "game_mode":        self.game_mode,
            "game_time":        self.game_time,
            "game_seconds":     self.game_seconds,
            "champion":         self.champion,
            "level":            self.level,
            "gold":             self.gold,
            "cs":               self.cs,
            "cs_per_min":       self.cs_per_min,
            "kda":              self.kda,
            "hp_pct":           self.hp_pct,
            "items":            self.items,
            "ally_comp":        self.ally_comp,
            "enemy_comp":       self.enemy_comp,
            "objectives":       self.objectives,
            "risk_derived":     self.risk_derived,
        }


class AramSnapshot:
    """
    ARAM / ARAM Mayhem game state.
    Written by game_reader.py only, via AramSnapshot.from_state_dict().

    ARAM shares the same Riot API data shape as SR but the coaching context
    differs. Payload is deliberately a strict subset of RiftSnapshot -
    no wave/jungle/objective-timer fields that don't apply in ARAM.
    The full raw dict is stored in raw_state for legacy consumers.
    """
    __slots__ = (
        "timestamp",
        "game_mode",
        "game_time",
        "game_seconds",
        "champion",
        "level",
        "gold",
        "cs",
        "cs_per_min",
        "kda",
        "kills",
        "deaths",
        "assists",
        "hp_pct",
        "hp_abs",
        "hp_max",
        "mana_pct",
        "items",
        "ally_comp",
        "enemy_comp",
        "ally_details",
        "enemy_details",
        "dead_enemies",
        "alive_enemies",
        "ally_kills_total",
        "enemy_kills_total",
        "risk_derived",
        "raw_state",
    )

    def __init__(self) -> None:
        self.timestamp:       float = 0.0
        self.game_mode:       str   = "ARAM"
        self.game_time:       str   = "0:00"
        self.game_seconds:    float = 0.0
        self.champion:        str   = ""
        self.level:           int   = 1
        self.gold:            int   = 0
        self.cs:              int   = 0
        self.cs_per_min:      float = 0.0
        self.kda:             str   = "0/0/0"
        self.kills:           int   = 0
        self.deaths:          int   = 0
        self.assists:         int   = 0
        self.hp_pct:          int   = 100
        self.hp_abs:          int   = 0
        self.hp_max:          int   = 1
        self.mana_pct:        int   = 100
        self.items:           List[str] = []
        self.ally_comp:       List[str] = []
        self.enemy_comp:      List[str] = []
        self.ally_details:    List[Any] = []
        self.enemy_details:   List[Any] = []
        self.dead_enemies:    List[Any] = []
        self.alive_enemies:   List[Any] = []
        self.ally_kills_total:  int = 0
        self.enemy_kills_total: int = 0
        self.risk_derived:    str   = ""
        self.raw_state:       Optional[Dict[str, Any]] = None

    @classmethod
    def from_state_dict(cls, d: Dict[str, Any]) -> "AramSnapshot":
        """
        Construct an AramSnapshot from a game_reader._process_game() dict.
        Called only by game_reader.py.
        """
        s = cls()
        s.timestamp        = time.monotonic()
        s.game_mode        = d.get("game_mode", "ARAM")
        s.game_time        = d.get("game_time", "0:00")
        s.game_seconds     = float(d.get("game_seconds", 0))
        s.champion         = d.get("champion", "")
        s.level            = int(d.get("level", 1))
        s.gold             = int(d.get("gold", 0))
        s.cs               = int(d.get("cs", 0))
        s.cs_per_min       = float(d.get("cs_per_min", 0.0))
        s.kda              = d.get("kda", "0/0/0")
        s.kills            = int(d.get("kills", 0))
        s.deaths           = int(d.get("deaths", 0))
        s.assists          = int(d.get("assists", 0))
        s.hp_pct           = int(d.get("hp_pct", 100))
        s.hp_abs           = int(d.get("hp_abs", 0))
        s.hp_max           = int(d.get("hp_max", 1))
        s.mana_pct         = int(d.get("mana_pct", 100))
        s.items            = list(d.get("items", []))
        s.ally_comp        = list(d.get("ally_comp", []))
        s.enemy_comp       = list(d.get("enemy_comp", []))
        s.ally_details     = list(d.get("ally_details", []))
        s.enemy_details    = list(d.get("enemy_details", []))
        s.dead_enemies     = list(d.get("dead_enemies", []))
        s.alive_enemies    = list(d.get("alive_enemies", []))
        s.ally_kills_total  = int(d.get("ally_kills_total", 0))
        s.enemy_kills_total = int(d.get("enemy_kills_total", 0))
        s.risk_derived     = d.get("risk_derived", "")
        # AUDIT 2026-04-28 (deferred-frozen): producer-side defensive copy.
        s.raw_state        = _snapshot_copy(d)
        return s

    @classmethod
    def emergency_raw_state_only(cls, state_dict: Dict[str, Any]) -> "AramSnapshot":
        """
        Final-resort emergency constructor.  Identical strategy to
        RiftSnapshot.emergency_raw_state_only - see that docstring.
        Returns None ONLY if Python's allocator cannot produce ANY instance
        of this class (fatal runtime condition, not a handled failure).
        """
        # AUDIT 2026-04-28 (deferred-frozen): producer-side defensive copy.
        copied = _snapshot_copy(state_dict)
        try:
            s = object.__new__(cls)
            s.raw_state = copied
            return s
        except Exception:
            pass
        try:
            s = object.__new__(cls)
            object.__setattr__(s, "raw_state", copied)
            return s
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_type":    "aram",
            "timestamp":        self.timestamp,
            "game_mode":        self.game_mode,
            "game_time":        self.game_time,
            "game_seconds":     self.game_seconds,
            "champion":         self.champion,
            "level":            self.level,
            "gold":             self.gold,
            "hp_pct":           self.hp_pct,
            "items":            self.items,
            "ally_comp":        self.ally_comp,
            "enemy_comp":       self.enemy_comp,
            "risk_derived":     self.risk_derived,
        }


class TftSnapshot:
    """
    TFT game state.
    Written by tft/tft_state_reader.py only, via TftSnapshot.from_state_dict().

    Fields match tft_state_reader._parse() output.
    TFT is NOT shaped like SR - it has stage/round/augments/traits/board/bench
    and does NOT have champion/wave/objectives/ward fields.
    The full raw dict is stored in raw_state for legacy consumers.
    """
    __slots__ = (
        "timestamp",
        "game_mode",
        "game_time_s",
        "level",
        "gold",
        "health",
        "is_dead",
        "stage",
        "round",
        "stage_round",
        "round_event",
        "is_pve",
        "is_carousel",
        "is_god_round",
        "variant",
        "streak",
        "kills",
        "deaths",
        "items",
        "items_str",
        "alive_others",
        "dead_others",
        "total_players",
        "board",
        "bench",
        "shop",
        "traits",
        "augments",
        "board_str",
        "bench_str",
        "shop_str",
        "traits_str",
        "augments_str",
        "xp_current",
        "xp_needed",
        "xp_remaining",
        "tempo_note",
        "raw_state",
    )

    def __init__(self) -> None:
        self.timestamp:    float = 0.0
        self.game_mode:    str   = "TFT"
        self.game_time_s:  float = 0.0
        self.level:        int   = 1
        self.gold:         int   = 0
        self.health:       int   = 100
        self.is_dead:      bool  = False
        self.stage:        int   = 1
        self.round:        int   = 1
        self.stage_round:  str   = "1-1"
        self.round_event:  str   = "pvp"
        self.is_pve:       bool  = False
        self.is_carousel:  bool  = False
        self.is_god_round: bool  = False
        self.variant:      str   = "standard"
        self.streak:       int   = 0
        self.kills:        int   = 0
        self.deaths:       int   = 0
        self.items:        List[str] = []
        self.items_str:    str   = "none"
        self.alive_others: int   = 0
        self.dead_others:  int   = 0
        self.total_players: int  = 8
        self.board:        List[Any] = []
        self.bench:        List[Any] = []
        self.shop:         List[Any] = []
        self.traits:       Dict[str, Any] = {}
        self.augments:     List[Any] = []
        self.board_str:    str   = "unavailable"
        self.bench_str:    str   = "unavailable"
        self.shop_str:     str   = "unavailable"
        self.traits_str:   str   = "unavailable"
        self.augments_str: str   = "unavailable"
        self.xp_current:   int   = 0
        self.xp_needed:    int   = 0
        self.xp_remaining: int   = 0
        self.tempo_note:   str   = ""
        self.raw_state:    Optional[Dict[str, Any]] = None

    @classmethod
    def from_state_dict(cls, d: Dict[str, Any]) -> "TftSnapshot":
        """
        Construct a TftSnapshot from a tft_state_reader._parse() dict.
        Called only by tft/tft_state_reader.py.
        """
        s = cls()
        s.timestamp    = time.monotonic()
        s.game_mode    = d.get("game_mode", "TFT")
        s.game_time_s  = float(d.get("game_time_s", 0))
        s.level        = int(d.get("level", 1))
        s.gold         = int(d.get("gold", 0))
        raw_health     = d.get("health")
        s.health       = int(raw_health) if raw_health is not None else 100
        s.is_dead      = bool(d.get("is_dead", False))
        s.stage        = int(d.get("stage", 1))
        s.round        = int(d.get("round", 1))
        s.stage_round  = d.get("stage_round", "1-1")
        s.round_event  = d.get("round_event", "pvp")
        s.is_pve       = bool(d.get("is_pve", False))
        s.is_carousel  = bool(d.get("is_carousel", False))
        s.is_god_round = bool(d.get("is_god_round", False))
        s.variant      = d.get("variant", "standard")
        s.streak       = int(d.get("streak", 0))
        s.kills        = int(d.get("kills", 0))
        s.deaths       = int(d.get("deaths", 0))
        s.items        = list(d.get("items", []))
        s.items_str    = d.get("items_str", "none")
        s.alive_others = int(d.get("alive_others", 0))
        s.dead_others  = int(d.get("dead_others", 0))
        s.total_players = int(d.get("total_players", 8))
        s.board        = list(d.get("board", []))
        s.bench        = list(d.get("bench", []))
        s.shop         = list(d.get("shop", []))
        s.traits       = dict(d.get("traits") or {})
        s.augments     = list(d.get("augments", []))
        s.board_str    = d.get("board_str", "unavailable")
        s.bench_str    = d.get("bench_str", "unavailable")
        s.shop_str     = d.get("shop_str", "unavailable")
        s.traits_str   = d.get("traits_str", "unavailable")
        s.augments_str = d.get("augments_str", "unavailable")
        s.xp_current   = int(d.get("xp_current", 0))
        s.xp_needed    = int(d.get("xp_needed", 0))
        s.xp_remaining = int(d.get("xp_remaining", 0))
        s.tempo_note   = d.get("tempo_note", "")
        s.raw_state    = d
        return s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_type": "tft",
            "timestamp":     self.timestamp,
            "game_mode":     self.game_mode,
            "level":         self.level,
            "gold":          self.gold,
            "health":        self.health,
            "stage_round":   self.stage_round,
            "round_event":   self.round_event,
            "variant":       self.variant,
            "items":         self.items,
            "augments":      self.augments,
            "augments_str":  self.augments_str,
        }


# ---------------------------------------------------------------------------
# GameEnvelope - common container
# ---------------------------------------------------------------------------

# Union of all payload types (type alias, 3.9 compatible)
_PayloadType = Optional[Any]  # ClientSnapshot | RiftSnapshot | AramSnapshot | TftSnapshot


class GameEnvelope:
    """
    Authoritative mode container for Riot Commander.

    mode     - one of MODE_CLIENT, MODE_SR, MODE_ARAM, MODE_TFT,
                      MODE_ARENA, MODE_BRAWL.
    payload  - the mode-specific snapshot (ClientSnapshot, RiftSnapshot,
                AramSnapshot, TftSnapshot, or None during transitions).
    timestamp - monotonic time of last envelope update.

    Written only by app.py. All other code reads via app.get_snapshot().
    """
    __slots__ = ("mode", "payload", "timestamp")

    def __init__(
        self,
        mode: str,
        payload: _PayloadType = None,
        timestamp: Optional[float] = None,
    ) -> None:
        if mode not in ALL_MODES:
            raise ValueError(f"GameEnvelope: unknown mode {mode!r}. Valid: {ALL_MODES}")
        self.mode:      str           = mode
        self.payload:   _PayloadType  = payload
        self.timestamp: float         = (
            timestamp if timestamp is not None else time.monotonic()
        )

    @classmethod
    def client(cls) -> "GameEnvelope":
        """Convenience constructor for client-mode envelope."""
        return cls(mode=MODE_CLIENT, payload=ClientSnapshot())

    def to_dict(self) -> Dict[str, Any]:
        payload_dict = self.payload.to_dict() if self.payload is not None else None
        return {
            "mode":      self.mode,
            "timestamp": self.timestamp,
            "payload":   payload_dict,
        }
