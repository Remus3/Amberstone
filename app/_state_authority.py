# arch: GameEnvelope + envelope update/read paths | section=orchestration | frozen=yes
"""
app/_state_authority.py - StateAuthority extracted from app/__init__.py (ARCH-001 Phase 2)

Owns the GameEnvelope (single source of truth for current game state envelope)
and the win-probability calculation.

OverlayApp delegates:
    _init_envelope()           -> self.state.init()
    get_snapshot()             -> self.state.get_snapshot()
    _update_envelope() body    -> self.state.set_envelope() + OverlayApp derives mode flags
    _process_game_state direct -> self.state.envelope.mode / self.state.set_envelope()
    _calc_win_pct()            -> StateAuthority.calc_win_pct()
"""
import copy
import logging

_log = logging.getLogger("rc.app.state")


class StateAuthority:
    """
    Owns:
      envelope   - the authoritative GameEnvelope (read via .envelope property)
      init()     - reset to client-mode envelope
      get_snapshot() - deep-copied envelope for external consumers
      set_envelope() - low-level write (no mode-flag derivation)
      calc_win_pct() - pure static win-probability estimate
    """

    def __init__(self) -> None:
        from core.game_snapshot import GameEnvelope
        self.envelope: "GameEnvelope" = GameEnvelope.client()

    # -- Public API ------------------------------------------------------------

    def init(self) -> None:
        """Reset to client-mode envelope. Called once at app start."""
        from core.game_snapshot import GameEnvelope
        self.envelope = GameEnvelope.client()

    def get_snapshot(self) -> "GameEnvelope":
        """
        Return a deep-copied envelope for external consumption.
        Callers cannot mutate any field (including nested dicts/lists) without
        affecting the authoritative internal copy.
        """
        from core.game_snapshot import GameEnvelope
        env = self.envelope
        payload = env.payload
        if payload is None:
            return GameEnvelope(mode=env.mode, payload=None, timestamp=env.timestamp)
        try:
            p_copy = copy.deepcopy(payload)
        except Exception:
            p_copy = None
        return GameEnvelope(mode=env.mode, payload=p_copy, timestamp=env.timestamp)

    def set_envelope(self, mode: str, payload) -> None:
        """
        Low-level envelope write - no mode-flag derivation.
        Used by _process_game_state for the Step C direct assignment path.
        _update_envelope() on OverlayApp calls this AND derives legacy flags.
        """
        from core.game_snapshot import GameEnvelope
        self.envelope = GameEnvelope(mode=mode, payload=payload)

    # -- Pure win-probability estimate -----------------------------------------

    @staticmethod
    def calc_win_pct(state: dict) -> float:
        """
        Heuristic win-probability estimate from game state dict.
        Pure function - no self references, independently testable.
        """
        pct = 50.0
        kd  = state.get("ally_kills_total", 0) - state.get("enemy_kills_total", 0)
        pct += min(15, max(-15, kd * 3.0))
        pct += min(10, max(-10, (state.get("cs_per_min", 0) - 7.0) * 2.5))
        hp = state.get("hp_pct", 100)
        if hp < 35:    pct -= 8
        elif hp < 60:  pct -= 3
        elif hp >= 85: pct += 4
        pct += min(12, state.get("dead_count", 0) * 4)
        # Type-clamp: keep str, decode bytes (utf-8, replace), skip int/None/dict/list - see tests/test_calc_win_pct_type_clamp.py
        items = [i for i in (j.decode("utf-8", errors="replace") if isinstance(j, bytes) else j
                             for j in state.get("items", []))
                 if isinstance(i, str) and i
                 and not any(x in i.lower()
                             for x in ("ward", "potion", "biscuit", "doran", "elixir"))]
        if len(items) >= 3:   pct += 8
        elif len(items) >= 2: pct += 4
        obj = (state.get("objectives", "") or "").lower()
        if "baron up" in obj or "drake up" in obj: pct += 3
        if "soul" in obj: pct += 6
        gpm = state.get("gold", 0) / max(1, state.get("game_seconds", 1) / 60)
        if gpm > 420:   pct += 5
        elif gpm < 280: pct -= 5
        return round(min(95, max(5, pct)), 0)
