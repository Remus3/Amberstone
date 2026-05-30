"""
lcu/lcu_pregame.py - Pre-game LCU helpers for champion select.

Covers:
  - Champion icon loading from LCU local asset server
  - Champion pick (action complete)
  - Bench swap (no cooldown - direct API bypasses client 5s delay)
  - Summoner spell writing (idempotent when caller provides current_pair)
  - Per-role spell defaults (Phase 8 step 4 - SR draft)
  - Champ select session parsing for ARAM
"""
from __future__ import annotations

import io
import json
import logging
import ssl
import urllib.request
from typing import Optional

_log = logging.getLogger("rc.lcu.pregame")

# ── Summoner spell IDs ────────────────────────────────────────────────────────
SPELL = {
    "flash":     4,
    "exhaust":   3,
    "heal":      7,
    "barrier":   21,
    "ghost":     6,
    "cleanse":   1,
    "teleport":  12,
    "ignite":    14,
    "smite":     11,
    "snowball":  32,   # ARAM: Mark / Snowball
    "clarity":   13,
}

# Preset spell combos
SPELL_FLASH_SNOWBALL = (SPELL["flash"], SPELL["snowball"])
SPELL_FLASH_EXHAUST  = (SPELL["flash"], SPELL["exhaust"])


# ── Role-keyed defaults for SR (Phase 8 step 4) ──────────────────────────────
# Conservative pairs that match the most common build for each role. The
# engine generator in `coaches/sr_draft_profile.py` has its own (tunable)
# table in sr_draft_presets.json; this one is the LCU-layer fallback used
# when no profile is being applied (e.g. operator clicks "default spells"
# in the dashboard before any beam result arrives).
SPELLS_BY_ROLE: dict[str, tuple[int, int]] = {
    "TOP":     (SPELL["flash"], SPELL["teleport"]),
    "JUNGLE":  (SPELL["flash"], SPELL["smite"]),
    "MIDDLE":  (SPELL["flash"], SPELL["ignite"]),
    "BOTTOM":  (SPELL["flash"], SPELL["heal"]),
    "UTILITY": (SPELL["flash"], SPELL["ignite"]),
}

# Aliases the LCU + champ-select session sometimes emit.
_ROLE_ALIASES: dict[str, str] = {
    "MID":     "MIDDLE",
    "BOT":     "BOTTOM",
    "ADC":     "BOTTOM",
    "SUPPORT": "UTILITY",
    "SUP":     "UTILITY",
    "JG":      "JUNGLE",
}


def spells_for_role(role: Optional[str]) -> tuple[int, int]:
    """Return (d_spell_id, f_spell_id) for the given lane.

    Coerces aliases (MID/BOT/ADC/SUP/JG) to canonical names. Falls back
    to BOTTOM Flash+Heal when role is unknown - safest default since
    Heal can't grief teammates the way Smite or TP would.
    """
    if not isinstance(role, str):
        return SPELLS_BY_ROLE["BOTTOM"]
    r = role.strip().upper()
    r = _ROLE_ALIASES.get(r, r)
    return SPELLS_BY_ROLE.get(r, SPELLS_BY_ROLE["BOTTOM"])


def _aram_mode(mode: str) -> bool:
    return mode.upper() in ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM")


# ── LcuPregame mixin / helper ─────────────────────────────────────────────────

class LcuPregame:
    """
    Mixin added to LcuClient.
    All methods expect self._port, self._auth, self._ssl, self._request()
    to exist (they do, inherited from LcuClient).
    """

    # ── Champion icon bytes ───────────────────────────────────────────────────

    def get_champion_icon_bytes(self, champion_id: int) -> Optional[bytes]:
        """
        Fetch champion square icon PNG from LCU local asset server.
        Returns raw PNG bytes or None.
        URL: https://{RC_GAME_HOST}:{port}/lol-game-data/assets/v1/champion-icons/{id}.png
        """
        if not self._port or not self._auth:
            return None
        from core.game_host import GAME_HOST
        url = f"https://{GAME_HOST}:{self._port}/lol-game-data/assets/v1/champion-icons/{champion_id}.png"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Basic {self._auth}",
                    "Accept": "image/png,image/*,*/*",
                },
            )
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ctx, timeout=3) as resp:
                return resp.read()
        except Exception as exc:
            _log.debug("get_champion_icon_bytes(%d): %s", champion_id, exc)
            return None

    # ── Session parsing ───────────────────────────────────────────────────────

    def get_my_pick_action(self, session: dict) -> Optional[dict]:
        """
        From a champ-select session, return the pending pick action for my cell.
        Returns the action dict or None.
        """
        my_cell = session.get("localPlayerCellId", -1)
        for group in session.get("actions", []):
            for action in group:
                if (action.get("actorCellId") == my_cell
                        and action.get("type") == "pick"
                        and not action.get("completed", False)):
                    return action
        return None

    def get_my_current_champion(self, session: dict) -> int:
        """Return my current championId (0 if none) from session."""
        my_cell = session.get("localPlayerCellId", -1)
        for player in session.get("myTeam", []):
            if player.get("cellId") == my_cell:
                cid = player.get("championId", 0) or player.get("championPickIntent", 0)
                return int(cid)
        return 0

    def get_my_summoner_spells(self, session: dict) -> tuple[int, int]:
        """Return (spell1Id, spell2Id) for my slot, or (0, 0)."""
        my_cell = session.get("localPlayerCellId", -1)
        for player in session.get("myTeam", []):
            if player.get("cellId") == my_cell:
                return (int(player.get("spell1Id", 0)),
                        int(player.get("spell2Id", 0)))
        return (0, 0)

    def get_bench_champion_ids(self, session: dict) -> list[int]:
        """Return list of bench champion IDs available for swap."""
        bench = session.get("benchChampions", [])
        if isinstance(bench, list):
            return [int(b.get("championId", 0)) for b in bench if b.get("championId")]
        return []

    # ── Actions ───────────────────────────────────────────────────────────────

    def pick_champion(self, action_id: int, champion_id: int,
                      completed: bool = True) -> bool:
        """
        Select/lock a champion in the pick action.
        PATCH /lol-champ-select/v1/session/actions/{id}
        completed=True to lock in; False to just hover.
        """
        result = self._request(
            "PATCH",
            f"/lol-champ-select/v1/session/actions/{action_id}",
            data={"championId": champion_id, "completed": completed},
        )
        if result is not None:
            _log.info("pick_champion: action=%d champ=%d completed=%s",
                      action_id, champion_id, completed)
            return True
        _log.warning("pick_champion: failed action=%d champ=%d", action_id, champion_id)
        return False

    def hover_champion(self, action_id: int, champion_id: int) -> bool:
        """Set champion intent without locking in (completed=False)."""
        return self.pick_champion(action_id, champion_id, completed=False)

    def bench_swap_fast(self, champion_id: int) -> bool:
        """
        Swap to bench champion - bypasses the 5-second client-side cooldown.
        POST /lol-champ-select/v1/session/bench/swap/{championId}
        """
        result = self._request(
            "POST",
            f"/lol-champ-select/v1/session/bench/swap/{champion_id}",
        )
        if result is not None:
            _log.info("bench_swap_fast: champ=%d", champion_id)
            return True
        _log.warning("bench_swap_fast: failed champ=%d", champion_id)
        return False

    def set_summoner_spells(
        self,
        spell1_id: int,
        spell2_id: int,
        *,
        current_pair: Optional[tuple[int, int]] = None,
    ) -> bool:
        """Set summoner spells in champ select.

        PATCH /lol-champ-select/v1/session/my-selection - but only when
        the target pair differs from what's already selected. Phase 8
        step 4 made this idempotent so a profile-apply round-trip
        doesn't hammer the LCU when the operator already has the right
        spells (e.g. their default lobby spells happen to match the
        primary profile's pair).

        Args:
          spell1_id: target d-spell LCU id.
          spell2_id: target f-spell LCU id.
          current_pair: optional (s1, s2) the caller already knows
            (typical: parsed from a champ-select session via
            ``get_my_summoner_spells``). If provided AND it matches
            the target, no PATCH fires and the call returns True.
            If None, PATCH is sent unconditionally - preserves the
            pre-Phase-8 contract for callers that haven't been
            updated yet.
        """
        if current_pair is not None:
            try:
                cur = (int(current_pair[0]), int(current_pair[1]))
            except (ValueError, IndexError, TypeError):
                cur = (0, 0)
            if cur == (int(spell1_id), int(spell2_id)):
                _log.debug(
                    "set_summoner_spells: idempotent skip (%d + %d already set)",
                    spell1_id, spell2_id,
                )
                return True
        result = self._request(
            "PATCH",
            "/lol-champ-select/v1/session/my-selection",
            data={"spell1Id": spell1_id, "spell2Id": spell2_id},
        )
        if result is not None:
            _log.info("set_summoner_spells: %d + %d", spell1_id, spell2_id)
            return True
        _log.warning("set_summoner_spells: failed %d + %d", spell1_id, spell2_id)
        return False

    def get_gameflow_phase(self) -> str:
        """
        Return current gameflow phase string.
        Handles LCU versions where /phase returns raw string.
        Returns: 'None', 'Lobby', 'ChampSelect', 'InProgress', etc.
        """
        try:
            result = self._request("GET", "/lol-gameflow/v1/phase")
            if isinstance(result, str):
                return result.strip('"')
            # Some LCU versions return a string-as-JSON
            if result is None:
                # Try raw fetch
                if not self._port or not self._auth:
                    return "None"
                import ssl as _ssl
                from core.game_host import GAME_HOST
                url = f"https://{GAME_HOST}:{self._port}/lol-gameflow/v1/phase"
                req = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Basic {self._auth}",
                             "Accept": "application/json"},
                )
                ctx = _ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
                with urllib.request.urlopen(req, context=ctx, timeout=2) as resp:
                    raw = resp.read().decode()
                    return raw.strip().strip('"')
        except Exception as exc:
            _log.debug("get_gameflow_phase: %s", exc)
        return "None"
