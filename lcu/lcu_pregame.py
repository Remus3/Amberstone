"""
lcu/lcu_pregame.py — Pre-game LCU helpers for champion select.

Covers:
  - Champion icon loading from LCU local asset server
  - Champion pick (action complete)
  - Bench swap (no cooldown — direct API bypasses client 5s delay)
  - Summoner spell writing
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
        URL: https://192.168.8.237:{port}/lol-game-data/assets/v1/champion-icons/{id}.png
        """
        if not self._port or not self._auth:
            return None
        url = f"https://192.168.8.237:{self._port}/lol-game-data/assets/v1/champion-icons/{champion_id}.png"
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
        Swap to bench champion — bypasses the 5-second client-side cooldown.
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

    def set_summoner_spells(self, spell1_id: int, spell2_id: int) -> bool:
        """
        Set summoner spells in champ select.
        PATCH /lol-champ-select/v1/session/my-selection
        """
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
                url = f"https://192.168.8.237:{self._port}/lol-gameflow/v1/phase"
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
