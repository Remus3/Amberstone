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

Input shape (s144 true-audit, S144-T-604). The caller
(dashboard/_deterministic_coaching.py ``_compute_uncached``) runs this under
ONE try for the whole deterministic fan-out, so a raise here blanked the
callouts, build and objective rows too. Every value is now checked at use:
a champion name is a printable str of 1-64 characters after strip; an item id
sent to the engine is a positive non-bool int or 1-7 ASCII digits; a
build_orders path must be a list and an items_index name a valid name; a
level is 1-100 (the liveclient cap) else the next source, else 1; the mode is
1-16 ASCII letters, digits or underscore, else no choices; the verdict is one
of the four the DS
engine emits (agents/daemon_slayer/matchup.py ``_classify``), else no choices,
never the old "even" stand-in for an unknown verdict; ``net_swing`` is a finite
non-bool number in [-1, 1], else the swing clause is left out. The patch read
from current.txt and the mode are single path segments, so neither can name a
build_orders file outside the patch directory.
"""
from __future__ import annotations

import json
import logging
import math
import re
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

# The four verdicts the DS engine emits (agents/daemon_slayer/matchup.py
# _classify). Anything else is a malformed result, not a neutral one.
_VERDICTS = frozenset({"all_in", "trade", "back_off", "even"})

_MAX_NAME_LEN = 64
# dashboard/_liveclient.py _MAX_LEVEL: the feed already refuses anything above.
_MIN_LEVEL, _MAX_LEVEL = 1, 100
_MODE_RE = re.compile(r"[A-Za-z0-9_]{1,16}")
_ITEM_ID_RE = re.compile(r"[0-9]{1,7}")
_LEVEL_STR_RE = re.compile(r"[0-9]{1,3}")
# One path segment: DS patch dirs are "16.11.1"-shaped; no separator, no NUL.
_PATCH_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")
_ASCII_BLANKS = " \t\r\n\x0b\x0c"


def _name(value: object) -> Optional[str]:
    """A champion / item display name, or None when the value is not one.

    A str that is 1-64 printable characters after stripping ASCII blanks
    (localised names stay valid: str.isprintable is Unicode-aware). A dict,
    None, a number or a control character never becomes a "name" via str().
    """
    if not isinstance(value, str):
        return None
    s = value.strip(_ASCII_BLANKS)
    if not s or len(s) > _MAX_NAME_LEN or not s.isprintable():
        return None
    return s


def _item_id(value: object) -> Optional[str]:
    """An item id as its decimal str, or None (bool, 0, negative, junk)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if 0 < value < 10 ** 7 else None
    if isinstance(value, str):
        s = value.strip(_ASCII_BLANKS)
        if _ITEM_ID_RE.fullmatch(s) and int(s) > 0:
            return s
    return None


def _level(value: object) -> Optional[int]:
    """A champion level in 1..100, or None. A float is truncated like int()
    did; a str must be ASCII digits; bool, non-finite and out-of-range values
    are None so the caller moves to its next source."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        value = int(value)
    elif isinstance(value, str):
        s = value.strip(_ASCII_BLANKS)
        if not _LEVEL_STR_RE.fullmatch(s):
            return None
        value = int(s)
    if isinstance(value, int) and _MIN_LEVEL <= value <= _MAX_LEVEL:
        return value
    return None


def _mode_ok(mode: object) -> bool:
    return isinstance(mode, str) and _MODE_RE.fullmatch(mode) is not None


def _fmt_swing(net_swing: object) -> str:
    """Render net_swing as a signed percent string, e.g. ``+34% net HP``.

    net_swing is a fraction in [-1, 1] (positive = A favored). Returns '' on a
    missing value, a bool, a str, a non-finite number or one outside [-1, 1]
    (the engine contract), so the expected_outcome stays clean and never
    reads "+5000%" or raises on inf.
    """
    if isinstance(net_swing, bool) or not isinstance(net_swing, (int, float)):
        return ""
    # A NaN fails both comparisons; an int too large for float compares fine.
    if not (-1 <= net_swing <= 1):
        return ""
    pct = round(net_swing * 100)
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
    appended. Returns [] on a non-dict input, or a verdict that is not one of
    the four the engine emits (fail-soft: the caller falls back to its synth
    path rather than serving a made-up "even" pair).

    RC2 5.3: when ``trigger`` is a non-empty str (the live condition the lane
    state was read under, e.g. "Ezreal, lvl 6"), it is stamped onto every
    returned choice so the chip UI can show the assumed condition as a
    sub-line. A non-str trigger or build item is ignored.
    """
    if not isinstance(matchup_result, dict):
        return []
    raw_verdict = matchup_result.get("verdict")
    if not isinstance(raw_verdict, str):
        return []
    verdict = raw_verdict.strip(_ASCII_BLANKS).lower()
    if verdict not in _VERDICTS:
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
    else:  # "even" (the only verdict left in _VERDICTS)
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

    item = _name(build_next_item)
    if item:
        choices.append(
            CoachChoice(
                key="C", label=f"Buy {item}", confidence="mid",
                expected_outcome="next item this build path",
                source_tag=_SOURCE_BUILD,
            )
        )
    if isinstance(trigger, str) and trigger:
        choices = [replace(c, trigger=trigger) for c in choices]
    return choices


def _resolve_patch() -> Optional[str]:
    """Read the active DS patch from current.txt. None if absent, unreadable
    or not one path segment ("..", a separator, a NUL), so the patch can never
    point the build_orders read outside the DS data dir."""
    try:
        raw = _DS_DATA_DIR.joinpath("current.txt").read_text(encoding="utf-8")
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
        return None
    patch = raw.strip(_ASCII_BLANKS)
    if not _PATCH_RE.fullmatch(patch) or not patch.strip("."):
        return None
    return patch


def _load_json(path: Path) -> object:
    """Parsed JSON or None on an IO / decode / parse failure. The caller
    checks the shape: a valid JSON list or scalar is returned as is."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    # RecursionError: a deeply nested document; not a ValueError.
    except (OSError, ValueError, RecursionError):
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
    failure or wrong-shaped document degrades to None so the caller just drops
    the build choice. ``owned`` is a list / tuple of names; anything else reads
    as nothing owned (a str is not iterated per character).
    """
    if not isinstance(champion, str) or not _mode_ok(mode):
        return None
    patch = _resolve_patch()
    if not patch:
        return None
    bo_path = _DS_DATA_DIR / patch / f"build_orders_{mode.lower()}.json"
    bo_doc = _load_json(bo_path)
    if not isinstance(bo_doc, dict):
        return None
    orders = bo_doc.get("build_orders")
    if not isinstance(orders, dict):
        return None
    champ_orders = orders.get(champion)
    if not isinstance(champ_orders, dict):
        return None
    # Prefer the "balanced" path; fall back to any non-empty LIST path (a str
    # or dict path is not a build order and is never iterated).
    id_list = champ_orders.get("balanced")
    if not isinstance(id_list, list) or not id_list:
        id_list = next(
            (v for v in champ_orders.values() if isinstance(v, list) and v), None,
        )
    if not id_list:
        return None

    idx_doc = _load_json(_ITEMS_INDEX_PATH)
    by_id = idx_doc.get("byId") if isinstance(idx_doc, dict) else None
    if not isinstance(by_id, dict):
        return None
    owned_list = owned if isinstance(owned, (list, tuple)) else ()
    owned_norm = {
        _norm_item_name(n) for n in owned_list
        if isinstance(n, (str, int)) and not isinstance(n, bool)
    }
    for item_id in id_list:
        # str() of any JSON value is hashable; a non-id entry just misses.
        name = _name(by_id.get(str(item_id)))
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
    for v1). Returns None when no enemy is resolvable. Only valid names count
    (``_name``): a None / blank / dict entry is skipped, never sent to the
    engine as "None" or a dict repr.
    """
    enemy_comp = game_state.get("enemy_comp")
    if not isinstance(enemy_comp, (list, tuple)):
        return None
    names = [n for n in (_name(c) for c in enemy_comp) if n]
    if not names:
        return None

    if str(mode).upper() in ("SR", "CLASSIC"):
        role = _name(game_state.get("role"))
        roles = game_state.get("enemy_roles")
        # Same-role pick only when BOTH my role + a parallel enemy_roles map are
        # present; otherwise fall back to the first enemy (v1 contract).
        if role and isinstance(roles, dict):
            role = role.lower()
            for champ, r in roles.items():
                champ_name = _name(champ)
                r_name = _name(r)
                if (champ_name and r_name and r_name.lower() == role
                        and champ_name in names):
                    return champ_name
    return names[0]


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
    if not isinstance(game_state, dict) or not _mode_ok(mode):
        return []

    my_champ = _name(game_state.get("my_champion")) or _name(game_state.get("champion"))
    if not my_champ:
        return []

    enemy = _resolve_enemy_laner(game_state, mode=mode)
    if not enemy:
        return []

    # First valid level wins (level, then my_level), else 1. A bool, a
    # non-finite or an out-of-range value is not a level.
    my_level = _level(game_state.get("level")) or _level(game_state.get("my_level")) or 1

    owned = game_state.get("items") or game_state.get("my_items") or []
    raw_ids = game_state.get("my_item_ids")
    if not isinstance(raw_ids, (list, tuple)):
        raw_ids = ()
    my_item_ids = [i for i in (_item_id(r) for r in raw_ids) if i]

    # v1: enemy level mirrors mine when unknown; enemy items unmodeled.
    result = matchup(
        my_champ,
        enemy,
        level_a=my_level,
        level_b=my_level,
        item_ids_a=my_item_ids,
        item_ids_b=[],
        mode=mode,
    )
    # matchup() returns a dict or None; anything else is a malformed result.
    if not isinstance(result, dict):
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
