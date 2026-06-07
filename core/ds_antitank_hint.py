# core/ds_antitank_hint.py | section=core | frozen=no
"""Anti-tank build-hint generator (A3 slice 1, item TBD).

Pure read-only consumer of the DS antitank scorer and archetype registry.
No engine files are modified. Deterministic, never raises.
"""
from __future__ import annotations

import logging

_log = logging.getLogger("rc.ds_antitank_hint")

# --- Tunable constants -------------------------------------------------------

# Minimum number of tanky (tank or bruiser archetype) enemies required before
# the hint fires at all. Below this the comp is not "high-HP" enough to warrant
# an anti-tank call-out.
HIGH_HP_ENEMY_MIN: int = 2

# antitank_score at or above which the champion's OWN KIT already melts tanks
# well enough that the hint is "lean into your kit / prioritize uptime" rather
# than "buy anti-tank items". Calibrated so Vayne (~0.95) and Fiora (~0.90)
# clear it while pure-flat-damage champions (Lux 0.0, Ezreal 0.0) do not.
# Chosen at 0.8 to include all dedicated anti-tank carries (Vayne/Fiora/Gwen)
# while excluding champions that merely have one incidental %HP mechanic.
ANTITANK_STRONG: float = 0.8

# --- Tanky archetype set -----------------------------------------------------

_TANKY_ARCHETYPES: frozenset[str] = frozenset({"tank", "bruiser"})


def build_antitank_hint(
    my_champion: str,
    enemy_champions: list[str] | None,
    mode: str = "SR",
) -> dict:
    """Return an anti-tank build hint dict for a given match-up.

    Parameters
    ----------
    my_champion:
        DDragon champion id for the local player (e.g. "Vayne"). Blank or None
        -> applies=False with zeroed fields, no raise.
    enemy_champions:
        List of DDragon champion ids for the five enemies. None -> treated as
        []. Blank / None entries are skipped. Unknown ids are treated as
        non-tanky (never raises for a single bad entry).
    mode:
        Game mode string passed through to compute_antitank (default "SR").

    Returns
    -------
    dict with keys:
        applies (bool)                 - True when the comp qualifies as tanky.
        my_champion (str)
        mode (str)
        my_antitank_score (float)      - rounded to 4 decimal places.
        my_top_kind (str)              - strongest anti-tank mechanism kind.
        shreds_resist (bool)
        tanky_enemy_count (int)
        tanky_enemies (list[str])      - ids classified as tank or bruiser.
        lean_in (bool)                 - True when kit already shreds tanks.
        recommend_antitank_items (bool)- True when comp is tanky + kit is not.
        hint (str)                     - coaching string, ASCII, "" when N/A.
    """
    # --- fail-soft on blank my_champion -------------------------------------
    safe_champion = (my_champion or "").strip()
    if not safe_champion:
        return _zero_result("", mode)

    safe_mode = mode if mode else "SR"

    # --- antitank score for local player ------------------------------------
    from agents.daemon_slayer.antitank import compute_antitank  # local import keeps tests fast
    my = compute_antitank(safe_champion, safe_mode)

    # --- classify enemies ---------------------------------------------------
    if enemy_champions is None:
        enemy_champions = []

    from core.archetype_picks import get_archetype_for  # local import avoids circular risk
    tanky_enemies: list[str] = []
    for champ in enemy_champions:
        safe_ec = (champ or "").strip()
        if not safe_ec:
            continue
        try:
            info = get_archetype_for(safe_ec)
            primary = info.get("primary", "") if isinstance(info, dict) else ""
            if primary in _TANKY_ARCHETYPES:
                tanky_enemies.append(safe_ec)
        except Exception:  # noqa: BLE001 - never break the hint
            _log.debug("ds_antitank_hint: get_archetype_for(%r) raised - skipping", safe_ec)

    tanky_enemy_count = len(tanky_enemies)
    applies = tanky_enemy_count >= HIGH_HP_ENEMY_MIN
    lean_in = applies and my.antitank_score >= ANTITANK_STRONG
    recommend_antitank_items = applies and not lean_in

    # --- hint string --------------------------------------------------------
    if not applies:
        hint = ""
    elif lean_in:
        hint = (
            f"Enemy comp tanky ({tanky_enemy_count}); "
            f"your kit shreds ({my.top_kind}) - prioritize uptime."
        )
    else:
        hint = (
            f"Enemy comp tanky ({tanky_enemy_count}); "
            "itemize anti-tank (%max-HP / armor pen)."
        )

    return {
        "applies": applies,
        "my_champion": safe_champion,
        "mode": safe_mode,
        "my_antitank_score": round(my.antitank_score, 4),
        "my_top_kind": my.top_kind,
        "shreds_resist": my.shreds_resist,
        "tanky_enemy_count": tanky_enemy_count,
        "tanky_enemies": tanky_enemies,
        "lean_in": lean_in,
        "recommend_antitank_items": recommend_antitank_items,
        "hint": hint,
    }


def _zero_result(champion: str, mode: str) -> dict:
    """Return an all-zero/false hint dict for a blank or invalid champion."""
    return {
        "applies": False,
        "my_champion": champion,
        "mode": mode if mode else "SR",
        "my_antitank_score": 0.0,
        "my_top_kind": "",
        "shreds_resist": False,
        "tanky_enemy_count": 0,
        "tanky_enemies": [],
        "lean_in": False,
        "recommend_antitank_items": False,
        "hint": "",
    }


__all__ = ["build_antitank_hint", "HIGH_HP_ENEMY_MIN", "ANTITANK_STRONG"]
