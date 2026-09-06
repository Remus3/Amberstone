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

# -- Summoner spell IDs --------------------------------------------------------
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


# -- Role-keyed defaults for SR (Phase 8 step 4) ------------------------------
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


def _as_int(value) -> int:
    """Coerce an LCU numeric field to int, defaulting to 0.

    The champ-select session carries JSON `null` for ids the client has
    not filled in yet (pre-hover window), and `int(None)` raises. Junk
    strings coerce to 0 too - these readers document total contracts
    ("0 if none", "(0, 0)"), so nothing here may raise (RM-346).
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _phase_or_none(raw: str) -> Optional[str]:
    """Unwrap an LCU gameflow-phase body, or None when it holds no phase.

    `/lol-gameflow/v1/phase` answers a bare JSON string, so the body
    arrives quoted (`"Lobby"`) on some client versions and unquoted on
    others. An EMPTY body is not a phase name - reporting it as one
    would hand a caller a value that claims to be a live read (RM-347).
    """
    phase = raw.strip().strip('"').strip()
    return phase or None


def _aram_mode(mode: str) -> bool:
    return mode.upper() in ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM")


# -- LcuPregame mixin / helper -------------------------------------------------

class LcuPregame:
    """
    Mixin added to LcuClient.
    All methods expect self._port, self._auth, self._ssl, self._request()
    to exist (they do, inherited from LcuClient).
    """

    # -- Champion icon bytes ---------------------------------------------------

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
        except Exception as exc:  # noqa: BLE001
            _log.debug("get_champion_icon_bytes(%d): %s", champion_id, exc)
            return None

    # -- Session parsing -------------------------------------------------------

    def get_my_pick_action(self, session: dict) -> Optional[dict]:
        """
        From a champ-select session, return the pending pick action for my cell.
        Returns the action dict or None.

        Total by contract, same root cause as the readers below (RM-346):
        `dict.get(key, default)` yields the default only when the key is
        ABSENT, so a key present with a JSON `null` yields None and
        `for group in None` raises. Non-list groups and non-dict actions
        are skipped rather than raising.
        """
        my_cell = session.get("localPlayerCellId", -1)
        groups = session.get("actions") or []
        if not isinstance(groups, list):
            return None
        for group in groups:
            if not isinstance(group, list):
                continue
            for action in group:
                if not isinstance(action, dict):
                    continue
                if (action.get("actorCellId") == my_cell
                        and action.get("type") == "pick"
                        and not action.get("completed", False)):
                    return action
        return None

    def _my_team_entries(self, session: dict) -> list[dict]:
        """Return the dict entries of session["myTeam"], defensively.

        `dict.get(key, default)` yields the default only when the key is
        ABSENT - a key present with a JSON `null` yields None, and the
        LCU sends exactly that in the pre-hover window of champ select.
        Non-dict entries are dropped so callers can `.get` freely.
        """
        team = session.get("myTeam") or []
        if not isinstance(team, list):
            return []
        return [p for p in team if isinstance(p, dict)]

    def get_my_current_champion(self, session: dict) -> int:
        """Return my current championId (0 if none) from session.

        Total by contract: a null / missing / unparseable id yields 0
        rather than raising, and a null championId still falls through
        to championPickIntent (RM-346).
        """
        my_cell = session.get("localPlayerCellId", -1)
        for player in self._my_team_entries(session):
            if player.get("cellId") == my_cell:
                return (_as_int(player.get("championId"))
                        or _as_int(player.get("championPickIntent")))
        return 0

    def get_my_summoner_spells(self, session: dict) -> tuple[int, int]:
        """Return (spell1Id, spell2Id) for my slot, or (0, 0).

        Total by contract: a null / missing / unparseable spell id
        yields 0 for that slot rather than raising (RM-346).

        NOT on the spell auto-push path, despite what the RM-346 row
        claimed - that path reads the same wire fields inline at
        `lcu/lcu_rune_writer.py:879` with its own `or 0` guard and
        never calls this method. Measured 2026-09-05: this reader has
        zero in-repo callers. It is public surface on the LcuClient
        mixin, so the total contract still has to hold, but the defect
        this docstring describes was latent, not a live crash.
        """
        my_cell = session.get("localPlayerCellId", -1)
        for player in self._my_team_entries(session):
            if player.get("cellId") == my_cell:
                return (_as_int(player.get("spell1Id")),
                        _as_int(player.get("spell2Id")))
        return (0, 0)

    def get_bench_champion_ids(self, session: dict) -> list[int]:
        """Return list of bench champion IDs available for swap.

        Non-dict bench entries (the LCU sends bare ints in some payload
        versions) and unparseable ids are skipped rather than raising
        (RM-346).
        """
        bench = session.get("benchChampions")
        if not isinstance(bench, list):
            return []
        ids = [_as_int(b.get("championId")) for b in bench if isinstance(b, dict)]
        return [cid for cid in ids if cid]

    # -- Actions ---------------------------------------------------------------

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

    def get_gameflow_phase(self) -> Optional[str]:
        """
        Return the current gameflow phase string, or None if it could not
        be READ. Handles LCU versions where /phase returns a raw string.

        Returns: 'Lobby', 'ChampSelect', 'InProgress', 'EndOfGame', etc.,
        and also the literal string 'None' - which is a REAL phase, the
        one the client reports while idle at the home screen.

        Which is exactly why a failed read is Python None and never the
        string 'None' (RM-347). Collapsing the two made a transient LCU
        error - client closed mid-poll, lockfile password rotated, an
        unexpected body shape, no cached credentials - indistinguishable
        from "the operator is idle", so a caller would stop driving
        champ-select logic with nothing to retry on.

        None rather than '' (lcu_postgame_collector._get_gameflow_phase)
        or 'Unknown' (snapshot_shape.shape_snapshot) because it is the
        value the live consumer contract in dashboard/_cs_retention.py
        already treats as "unknown, do not act on it": the *string*
        'None' is an explicit clear phase there, a Python None
        deliberately is not.

        Failures stay at debug level on purpose - the sentinel is what
        makes them detectable now, and promoting this to a warning would
        spam the log once per tick for as long as the client is closed.
        A polling caller can log at its own cadence.
        """
        try:
            result = self._request("GET", "/lol-gameflow/v1/phase")
            if isinstance(result, str):
                return _phase_or_none(result)
            # Some LCU versions return a string-as-JSON
            if result is None:
                # Try raw fetch
                if not self._port or not self._auth:
                    _log.debug("get_gameflow_phase: no cached lockfile port/auth")
                    return None
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
                    return _phase_or_none(raw)
        except Exception as exc:  # noqa: BLE001
            _log.debug("get_gameflow_phase: %s", exc)
            return None
        # Neither a str nor None: a dict / int / list body is not a phase,
        # and used to fall through to the idle string without even
        # attempting the raw fetch.
        _log.debug(
            "get_gameflow_phase: unexpected body type %s", type(result).__name__
        )
        return None
