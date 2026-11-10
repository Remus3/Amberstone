# arch: deterministic champ-select pick-advisor | section=core | frozen=no
"""core/champ_select_advisor_deterministic.py - deterministic champ-select pick-advisor (NO Haiku).

PRIMARY north-star Haiku-elimination Tier-2. The pick-advisor surface
(coaches/champ_select_coach.coach_pick -> /api/champ-select-coach) is the last
champ-select Haiku call: the champ-select BRIEF was flipped off Haiku 2026-06-06
(items 273/276/280/283) but the pick-advisor has no deterministic substrate.
This composes a v1 candidate from surfaces RC already trusts - core.aram_comp_verdict
(the ARAM bench swap + comp-balance factors, itself a Haiku-elimination module)
and the archetype-tag map - so the precompute path can be shadow-validated against
the live Haiku output (core.champ_select_shadow) before any flip. Do-not-flip-blind:
this module changes NO live output.

advise_pick(state) mirrors the advice fields of coach_pick:
    {"advice": str, "swap": str, "summoners": str, "watchout": str}
Every value is a str of at most 100 characters. Empty shape on unusable input
(no usable my_champion) or an unexpected error - same fail-soft contract as the
Haiku path so callers need not guard. Pure import-only reuse; NO Anthropic call,
NO new dependency.

Input contract (s144 true-audit S144-T-727). The route hands over coach_pick's
own view (dashboard/routes_coach.py `_pick_view`), but this module does not
trust its caller for shape:
- my_champion: a str; stripped; refused when blank, longer than the prompt
  sanitiser's cap, or carrying a control character.
- their_team: only a list or tuple counts (a str would iterate by character, a
  dict by key); at most _MAX_ENEMIES entries are READ; non-str entries dropped.
- is_aram: only a real True takes the ARAM branch ("false" is truthy).
- A failing ARAM verdict degrades the advice to the stay line; it never blanks
  the summoners and watchout already computed.
A failure is logged as its exception type and scrubbed text, never the raw
champion name, at WARNING once per failure streak and DEBUG after.
"""
from __future__ import annotations

import logging
from itertools import islice

from core.log_scrub import scrub_log
from core.prompt_sanitize import DEFAULT_MAX_LEN

logger = logging.getLogger("rc.core.champ_select_advisor")

_EMPTY: dict = {"advice": "", "swap": "", "summoners": "", "watchout": ""}

# Every output field is clipped to this many characters (coach_pick's lines
# are one short sentence each).
_MAX_FIELD = 100

# Entries of their_team READ per call; matches coach_pick's _MAX_NAMES so the
# work for one request is bounded the same way on both paths.
_MAX_ENEMIES = 16

# A name longer than this is refused. It is the prompt sanitiser's cap, the
# longest name coach_pick's `_name` can hand over, so no route-view name is
# refused here.
_MAX_NAME = DEFAULT_MAX_LEN

# Threat rank for the "watchout" call: the enemy whose PRIMARY archetype is the
# one to track at pick time. Assassin / burst-mage > sustained marksman > bruiser
# dive > tank / enchanter. Lower index = higher threat.
_THREAT_ORDER = ("assassin", "mage", "carry", "bruiser", "tank", "enchanter")

# Friendly label for the archetype name in the watchout string (RC's "carry"
# scorer is the marksman class - say "marksman" to the player).
_ARCH_LABEL = {
    "carry": "marksman", "mage": "mage", "assassin": "assassin",
    "bruiser": "bruiser", "tank": "tank", "enchanter": "enchanter",
}

# Summoner default per primary archetype. Conservative mode-agnostic v1; the
# shadow lane validates this against Haiku before any flip is considered.
_SUMMONER_BY_ARCH = {
    "carry": "Flash + Heal",
    "enchanter": "Flash + Heal",
    "mage": "Flash + Barrier",
    "assassin": "Flash + Ignite",
    "bruiser": "Flash + Ignite",
    "tank": "Flash + Ignite",
}

# Failure-streak flags: True once the streak's WARNING has been written.
_WARNED = {"advise": False, "tags": False, "verdict": False}

# Normalised-name index over the tag map, rebuilt when the map object changes.
# One (source map, index) tuple, swapped in a single store, so a concurrent
# reader never pairs a new source with an old index.
_NORM_CACHE: dict = {"pair": (None, {})}


def _reset_warn_state() -> None:
    """Re-arm every WARNING and drop the normalised index (tests)."""
    for key in _WARNED:
        _WARNED[key] = False
    _NORM_CACHE["pair"] = (None, {})


def _log_failure(key: str, what: str, exc: BaseException) -> None:
    """WARNING for the first failure of a streak, DEBUG after. The line is the
    exception type and its control-escaped text, never a caller value."""
    level = logging.DEBUG if _WARNED[key] else logging.WARNING
    _WARNED[key] = True
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001 - a broken __str__ must not hide the cause
        text = "<exception text unavailable>"
    logger.log(level, "%s failed: %s: %s", what, type(exc).__name__,
               scrub_log(text[:200]))


def _norm(name: str) -> str:
    """Letters and digits only, lower-cased - core.aram_comp_verdict's rule."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _clean_name(value: object) -> str:
    """The stripped name in `value`, or "" when it cannot be a champion name:
    not a str, blank, longer than _MAX_NAME, or carrying a control character
    (C0, DEL or C1)."""
    if not isinstance(value, str):
        return ""
    name = str.strip(value)  # plain str even for a subclass overriding strip
    if not name or len(name) > _MAX_NAME:
        return ""
    if any(ch < " " or "\x7f" <= ch <= "\x9f" for ch in name):
        return ""
    return name


def _enemy_names(value: object) -> list:
    """Usable names from a list field: only a list or tuple counts, at most
    _MAX_ENEMIES entries are read, unusable entries are dropped."""
    if not isinstance(value, (list, tuple)):
        return []
    return [n for n in map(_clean_name, islice(value, _MAX_ENEMIES)) if n]


def _tags_for(tags_map: dict, champ: str):
    """The tag list for `champ`: the exact key first, then the normalised one."""
    tags = tags_map.get(champ)
    if tags is not None:
        return tags
    key = _norm(champ)
    if not key:
        return None
    src, index = _NORM_CACHE["pair"]
    if src is not tags_map:
        index = {}
        for k, v in tags_map.items():
            if isinstance(k, str):
                index.setdefault(_norm(k), v)
        _NORM_CACHE["pair"] = (tags_map, index)
    return index.get(key)


def _primary_archetype(champ: str) -> str:
    """First-tag archetype for a champion name, or "" when unresolved. A name
    resolves in its exact DDragon spelling or normalised (case, spaces and
    punctuation ignored), as core.aram_comp_verdict resolves it."""
    try:
        from core.archetype_picks import _load_champion_tags, tag_to_archetype
        tags_map = _load_champion_tags()
    except Exception as exc:  # noqa: BLE001 - best-effort; never breaks the advisor
        _log_failure("tags", "champion tag source", exc)
        return ""
    _WARNED["tags"] = False
    if not isinstance(tags_map, dict) or not isinstance(champ, str):
        return ""
    tags = _tags_for(tags_map, champ)
    if not isinstance(tags, (list, tuple)) or not tags:
        return ""
    first = tags[0]
    if not isinstance(first, str) or not first.strip():
        return ""
    return tag_to_archetype(first)


def _summoners(champ: str) -> str:
    return _SUMMONER_BY_ARCH.get(_primary_archetype(champ), "Flash + Heal")


def _watchout(enemies: list) -> str:
    """Name the highest-threat enemy by primary archetype. Falls back to the
    first named enemy when no tag resolves; "" when there is no enemy at all."""
    best, best_rank, best_arch = "", len(_THREAT_ORDER), ""
    for name in enemies:
        arch = _primary_archetype(name)
        if not arch:
            continue
        try:
            rank = _THREAT_ORDER.index(arch)
        except ValueError:
            continue
        if rank < best_rank:
            best, best_rank, best_arch = name, rank, arch
    if not best:
        first = next((e for e in enemies if e), "")
        return f"Watch {first}." if first else ""
    return f"Watch {best} ({_ARCH_LABEL.get(best_arch, best_arch)})."


def _enemy_lean(enemies: list) -> str:
    """Armor-vs-MR clause from the enemy damage-type distribution. Fires only
    with >= 3 resolvable enemies AND a clear mono lean; "" otherwise."""
    try:
        from core.aram_comp_verdict import compute_factors
        f = compute_factors(enemies or [])
        if f.get("n", 0) >= 3:
            ad, ap = f.get("ad_count", 0), f.get("ap_count", 0)
            if ad and not ap:
                return "enemy AD-heavy, prioritize armor"
            if ap and not ad:
                return "enemy AP-heavy, prioritize MR"
    except Exception as exc:  # best-effort  # noqa: BLE001
        logger.debug("enemy_lean: %s", type(exc).__name__)
    return ""


def _stay(my: str, lean: str) -> str:
    return f"Stay {my} - {lean}." if lean else f"Stay {my} - solid into this comp."


def _trim(s) -> str:
    """A verdict reason without its trailing full stop; "" for a non-str."""
    if not isinstance(s, str):
        return ""
    return s.rstrip(". ").strip()


def _with_reason(head: str, reason) -> str:
    why = _trim(reason)
    return f"{head} - {why}" if why else f"{head}."


def _clip(s: str) -> str:
    return s[:_MAX_FIELD]


def _aram_advice(state: dict, my: str, lean: str) -> tuple:
    """(advice, swap) from core.aram_comp_verdict. A junk or failing verdict
    is the stay line and no swap."""
    try:
        from core.aram_comp_verdict import comp_verdict
        advice, swap = _read_verdict(comp_verdict(state), my, lean)
    except Exception as exc:  # noqa: BLE001 - degrade to stay, keep the other fields
        _log_failure("verdict", "aram comp verdict", exc)
        return _stay(my, lean), ""
    _WARNED["verdict"] = False
    return advice, swap


def _read_verdict(v, my: str, lean: str) -> tuple:
    """(advice, swap) from one comp_verdict result; junk is the stay line."""
    if not isinstance(v, dict):
        return _stay(my, lean), ""
    rec = v.get("recommendation")
    rec = rec if isinstance(rec, str) else ""
    swap_to = _clean_name(v.get("swap_to"))
    if len(swap_to) > _MAX_FIELD:
        swap_to = ""  # a clipped name would be a wrong name
    if rec == "swap" and swap_to:
        return _with_reason(f"Swap to {swap_to}", v.get("reason")), swap_to
    if rec == "variant" and v.get("variant_to"):
        return _with_reason(f"Stay {my}, shift build", v.get("reason")), ""
    return _stay(my, lean), ""


def advise_pick(state: dict) -> dict:
    """Deterministic pick advice mirroring coach_pick's advice fields. Returns
    the EMPTY shape on unusable input or an unexpected error (fail-soft, never
    raises)."""
    if not isinstance(state, dict):
        return dict(_EMPTY)
    try:
        my = _clean_name(state.get("my_champion"))
        if not my:
            return dict(_EMPTY)
        enemies = _enemy_names(state.get("their_team"))
        summoners = _summoners(my)
        watchout = _watchout(enemies)
        lean = _enemy_lean(enemies)
        if state.get("is_aram") is True:
            advice, swap = _aram_advice(state, my, lean)
        else:
            advice, swap = _stay(my, lean), ""
        out = {"advice": advice, "swap": swap,
               "summoners": summoners, "watchout": watchout}
        out = {k: _clip(v) if isinstance(v, str) else "" for k, v in out.items()}
    except Exception as exc:  # noqa: BLE001 - fail-soft: never raise into the route
        _log_failure("advise", "advise_pick", exc)
        return dict(_EMPTY)
    _WARNED["advise"] = False
    return out
