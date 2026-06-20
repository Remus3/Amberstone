"""Lane C deterministic laning verdict -> A/B coach choices adapter.

WHY: the live coach today round-trips the "should I trade / all-in / back off"
laning question through Claude Haiku. The DS matchup engine (``compute_matchup``
behind POST /v2/matchup) already answers that deterministically. This module is
the adapter that turns a matchup verdict into a list of ``CoachChoice`` the
existing chip UI already renders - no LLM, no second network call beyond the one
matchup() call. The state-builder wiring + chip UI already exist (wave 3 / prior
work); this is the deterministic SOURCE only.

Fail-soft everywhere: a missing game-state key, an engine-down matchup() (None),
or an absent build-orders file degrades to fewer choices or ``[]`` - it never
raises. The caller falls back to the existing synth path when this returns [].

Data layers (Meraki-only, all already present):
  * ``core.daemon_slayer_client.matchup`` -> the trade verdict.
  * ``data/daemon_slayer/<patch>/build_orders_<mode>.json`` -> the next item to
    buy (optional; absent file just drops the 3rd choice).
  * ``web/data/items_index.json`` byId -> item id -> display name.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Optional

from core.coach_choices import CoachChoice
from core.daemon_slayer_client import matchup
from core.precomputed_laning_coach import laning_trigger

logger = logging.getLogger("rc.core.laning_verdicts")

_SOURCE_MATCHUP = "ds-matchup"
_SOURCE_BUILD = "ds-build"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DS_DATA_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"
_ITEMS_INDEX_PATH = _PROJECT_ROOT / "web" / "data" / "items_index.json"


def _fmt_swing(net_swing: object) -> str:
    """Render net_swing as a signed percent string, e.g. ``+34% net HP``.

    net_swing is a fraction in [-1, 1] (positive = A favored). Returns '' on a
    non-numeric / missing value so the expected_outcome stays clean.
    """
    try:
        pct = round(float(net_swing) * 100)
    except (TypeError, ValueError):
        return ""
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}% net HP"


def verdict_to_choices(
    matchup_result: dict,
    *,
    build_next_item: Optional[str] = None,
    trigger: str = "",
) -> list[CoachChoice]:
    """Map a matchup verdict dict to 2 deterministic A/B CoachChoice objects.

    source_tag is ``ds-matchup`` for the A/B pair. When ``build_next_item`` is a
    non-empty name, a 3rd ``Buy <item>`` choice (source_tag ``ds-build``) is
    appended. Returns [] on a non-dict / verdict-less input (fail-soft).

    RC2 5.3: when ``trigger`` is non-empty (the live condition the lane state
    was read under, e.g. "Ezreal, lvl 6"), it is stamped onto every returned
    choice so the chip UI can show the assumed condition as a sub-line.
    """
    if not isinstance(matchup_result, dict):
        return []
    verdict = str(matchup_result.get("verdict") or "").strip().lower()
    if not verdict:
        return []

    swing = _fmt_swing(matchup_result.get("net_swing"))
    swing_clause = f" ({swing})" if swing else ""

    if verdict == "all_in":
        choices = [
            CoachChoice(
                key="A", label="All in now", confidence="high",
                expected_outcome=f"favorable - you win the trade and can kill{swing_clause}",
                source_tag=_SOURCE_MATCHUP,
            ),
            CoachChoice(
                key="B", label="Back off", confidence="low",
                expected_outcome="give up the kill window",
                source_tag=_SOURCE_MATCHUP,
            ),
        ]
    elif verdict == "trade":
        choices = [
            CoachChoice(
                key="A", label="Trade now", confidence="mid",
                expected_outcome=f"net HP swing in your favor{swing_clause}",
                source_tag=_SOURCE_MATCHUP,
            ),
            CoachChoice(
                key="B", label="Farm safe", confidence="mid",
                expected_outcome="skip the trade, take CS",
                source_tag=_SOURCE_MATCHUP,
            ),
        ]
    elif verdict == "back_off":
        choices = [
            CoachChoice(
                key="A", label="Back off", confidence="high",
                expected_outcome=f"you lose this trade - disengage{swing_clause}",
                source_tag=_SOURCE_MATCHUP,
            ),
            CoachChoice(
                key="B", label="Trade anyway", confidence="low",
                expected_outcome="risky, only if jungler/CD edge",
                source_tag=_SOURCE_MATCHUP,
            ),
        ]
    else:  # "even" and any other recognized-but-neutral verdict
        choices = [
            CoachChoice(
                key="A", label="Trade even", confidence="mid",
                expected_outcome=f"roughly even - trade for prio{swing_clause}",
                source_tag=_SOURCE_MATCHUP,
            ),
            CoachChoice(
                key="B", label="Farm", confidence="mid",
                expected_outcome="hold, scale",
                source_tag=_SOURCE_MATCHUP,
            ),
        ]

    item = (build_next_item or "").strip()
    if item:
        choices.append(
            CoachChoice(
                key="C", label=f"Buy {item}", confidence="mid",
                expected_outcome="next item this build path",
                source_tag=_SOURCE_BUILD,
            )
        )
    if trigger:
        choices = [replace(c, trigger=trigger) for c in choices]
    return choices


def _resolve_patch() -> Optional[str]:
    """Read the active DS patch from current.txt. None if absent/unreadable."""
    try:
        return _DS_DATA_DIR.joinpath("current.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _norm_item_name(name: object) -> str:
    """Lower-no-punct normalization for item-name comparison (matches the
    items_index byName key convention)."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _next_build_item(
    champion: str,
    owned: object,
    *,
    mode: str,
) -> Optional[str]:
    """Resolve the first build-order item the player does NOT already own.

    Reads ``build_orders_<mode>.json`` for the active patch. Returns the display
    name (via items_index byId) or None when the file is absent, the champion is
    missing, or every build item is already owned. Never raises - any IO/parse
    failure degrades to None so the caller just drops the build choice.
    """
    patch = _resolve_patch()
    if not patch:
        return None
    bo_path = _DS_DATA_DIR / patch / f"build_orders_{str(mode).lower()}.json"
    bo_doc = _load_json(bo_path)
    if not isinstance(bo_doc, dict):
        return None
    orders = bo_doc.get("build_orders")
    if not isinstance(orders, dict):
        return None
    champ_orders = orders.get(champion)
    if not isinstance(champ_orders, dict):
        return None
    # Prefer the "balanced" path; fall back to any non-empty path.
    id_list = champ_orders.get("balanced") or []
    if not id_list:
        for v in champ_orders.values():
            if isinstance(v, list) and v:
                id_list = v
                break
    if not id_list:
        return None

    idx_doc = _load_json(_ITEMS_INDEX_PATH) or {}
    by_id = idx_doc.get("byId") or {}
    owned_norm = {
        _norm_item_name(n) for n in (owned or []) if isinstance(n, (str, int))
    }
    for item_id in id_list:
        name = by_id.get(str(item_id))
        if not name:
            continue
        if _norm_item_name(name) in owned_norm:
            continue
        return name
    return None


def _resolve_enemy_laner(game_state: dict, *, mode: str) -> Optional[str]:
    """Pick the opposing laner from game_state.

    SR: same-role opponent when a ``role`` is known, else the first enemy in
    ``enemy_comp``. ARAM/other: highest-threat enemy (first in ``enemy_comp``
    for v1). Returns None when no enemy is resolvable.
    """
    enemy_comp = game_state.get("enemy_comp") or []
    if not isinstance(enemy_comp, list) or not enemy_comp:
        return None

    if str(mode).upper() in ("SR", "CLASSIC"):
        role = str(game_state.get("role") or "").strip().lower()
        roles = game_state.get("enemy_roles")
        # Same-role pick only when BOTH my role + a parallel enemy_roles map are
        # present; otherwise fall back to the first enemy (v1 contract).
        if role and isinstance(roles, dict):
            for champ, r in roles.items():
                if str(r).strip().lower() == role and champ in enemy_comp:
                    return str(champ)
    return str(enemy_comp[0])


def laning_choices(
    game_state: dict,
    *,
    mode: str = "SR",
    apply_cv: bool = False,
    hp_fraction: Optional[float] = None,
    vision_state: Optional[dict] = None,
) -> list[CoachChoice]:
    """Deterministic laning A/B (+optional buy) choices from the DS matchup engine.

    Resolves my champ + level + items + the enemy laner from ``game_state``,
    calls ``matchup()``, and maps the verdict. Returns [] when the engine is down
    (matchup -> None) so the caller falls back to the existing synth path, or when
    a required piece (my champ / enemy laner) is missing.

    v1 limitations (documented, intentional): enemy level defaults to my level
    when unknown, and enemy item ids are empty (no live enemy-build feed on this
    seam). Both are honest lower-fidelity inputs to the deterministic verdict, not
    fabricated values.

    RC2 P5.2 (default OFF): when ``apply_cv`` is True, the resolved enemy laner's
    live CV status (``data/vision_state.json``: dead/missing) + my ``hp_fraction``
    can OVERRIDE the static matchup chips via ``core.laning_cv_overrides``. Off ->
    byte-identical. The served-flip is operator/Gemini-gated
    (``docs/LIVE_GAME_GATED_SYNC.md``); ``vision_state`` is a test seam.
    """
    if not isinstance(game_state, dict):
        return []

    my_champ = (
        game_state.get("my_champion")
        or game_state.get("champion")
        or ""
    )
    my_champ = str(my_champ).strip()
    if not my_champ:
        return []

    enemy = _resolve_enemy_laner(game_state, mode=mode)
    if not enemy:
        return []

    try:
        my_level = int(game_state.get("level") or game_state.get("my_level") or 1) or 1
    except (TypeError, ValueError):
        my_level = 1

    owned = game_state.get("items") or game_state.get("my_items") or []
    my_item_ids = game_state.get("my_item_ids") or []

    # v1: enemy level mirrors mine when unknown; enemy items unmodeled.
    result = matchup(
        my_champ,
        enemy,
        level_a=my_level,
        level_b=my_level,
        item_ids_a=[str(i) for i in my_item_ids if i],
        item_ids_b=[],
        mode=mode,
    )
    if result is None:
        return []

    build_item = _next_build_item(my_champ, owned, mode=mode)
    # RC2 5.3: name the live condition on each served chip (lean - this seam
    # knows the enemy laner + my level, not the mana/cd discrete state).
    trigger = laning_trigger(enemy, my_level)
    choices = verdict_to_choices(
        result, build_next_item=build_item, trigger=trigger,
    )
    if apply_cv:
        # Lazy import avoids a core import cycle (laning_cv_overrides imports
        # coach_choices, which laning_verdicts already binds at module load).
        from core.laning_cv_overrides import apply_cv_to_choices
        choices = apply_cv_to_choices(
            choices, enemy, hp_fraction,
            base_verdict=result.get("verdict"),
            vision_state=vision_state,
        )
    return choices
