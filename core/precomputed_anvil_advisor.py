# arch: arena item-anvil deterministic substrate | section=core | frozen=no
"""core/precomputed_anvil_advisor.py - deterministic arena item-anvil substrate.

The do-not-flip-blind precompute twin of the Tier-1 arena item-anvil Haiku call
(coaches/arena_coach.py purpose="arena_anvil"). The live coach still answers via
Haiku; this module ranks each OFFERED anvil choice against the rule-based ideal
build path (coaches._arena_item_advisor.recompute_arena_build) so the precompute
path can be validated against real games offline before any flip. It serves
nothing live - core.anvil_shadow records its output alongside the Haiku take.

We rank by position in the ideal path (earliest = best) rather than re-scoring,
because recompute_arena_build already encodes the anti-tank / anti-heal pivots
and the curated per-champion ordering; the anvil decision is "which offered item
is furthest up my real build", which is exactly that position.

Name matching is normalized (lower-case, strip non-alphanumerics) so a vision /
display variant of an item name still binds to the canonical build-path entry
without an id-resolution dependency. An exact normalized name anywhere in the
path wins; only then does the equal-or-substring tolerance apply (earliest path
entry first), and only when the shorter side has at least _MIN_SUBSTRING chars,
so an OCR fragment or a character of a bare-string offer never binds. The
helpers are copied locally rather than imported from core.anvil_shadow: sharing
private names across modules couples two fail-soft surfaces that must stay
independently editable.

Trust boundary: every input comes from a vision model reply or coach state, so
each is normalised here before use (s144 true-audit cycle 136). A choices /
owned / opponents value is read only from a non-string, non-mapping iterable,
for at most a bounded number of entries, keeping stripped non-blank strings of a
bounded length; a non-str or blank champion skips the build lookup; hp_pct is an
int clamped to 0..100 (anything unreadable is 100) and gold a non-negative int.
"""
from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from itertools import islice
from typing import Iterable

from coaches._arena_item_advisor import recompute_arena_build

log = logging.getLogger("rc.precomputed_anvil_advisor")

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# A normalized name shorter than this binds only by exact equality.
_MIN_SUBSTRING = 4
# An anvil offers 2-4 cards and a build path is at most a handful of items; the
# caps bound the work on a malformed vision reply, not a real game.
_MAX_OFFERED = 16
_MAX_LIST = 64
_MAX_NAME_LEN = 96


def _norm(name: str) -> str:
    return _NON_ALNUM.sub("", name.lower())


def _names_match(a: str, b: str) -> bool:
    # Equal-or-substring tolerates display variants without id resolution; the
    # substring half needs the shorter side to be at least _MIN_SUBSTRING long.
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < _MIN_SUBSTRING:
        return False
    return a in b or b in a


def _names(value: object, cap: int) -> list[str]:
    """Stripped non-blank str entries of an iterable, in order, reading at most
    ``cap`` entries. A str / bytes (would iterate by character), a mapping
    (would iterate by key) or a non-iterable reads as empty; a non-str entry or
    one longer than _MAX_NAME_LEN after stripping is dropped."""
    if value is None or isinstance(value, (str, bytes, bytearray, Mapping)):
        return []
    try:
        entries = list(islice(iter(value), cap))
    except Exception:  # noqa: BLE001 - a hostile iterable is no input
        return []
    out = []
    for c in entries:
        if isinstance(c, str):
            # str.strip, not c.strip: a str subclass may override strip, and the
            # base method also hands back a plain str for _norm.
            s = str.strip(c)
            if s and len(s) <= _MAX_NAME_LEN:
                out.append(s)
    return out


def _clamp_int(value: object, lo: int, hi: int | None, default: int) -> int:
    """A real number (not a bool) truncated to int and clamped, else default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if isinstance(value, float) and not math.isfinite(value):
        return default
    try:
        n = int(value)
    except (OverflowError, ValueError):
        return default
    if hi is not None and n > hi:
        return hi
    return max(lo, n)


def _rank_in_path(nn: str, norm_path: list[str]) -> int | None:
    """1-based rank of a normalized offered name inside the normalized ideal
    path, or None when it does not appear (an off-build anvil item). An exact
    match anywhere wins; else the earliest substring match."""
    if not nn:
        return None
    for i, np in enumerate(norm_path):
        if nn == np:
            return i + 1
    for i, np in enumerate(norm_path):
        if _names_match(nn, np):
            return i + 1
    return None


def _low_conf(offered: list[str]) -> dict:
    """The fail-soft shape: every offered choice present, no rank, ideal empty.
    Used when recompute_arena_build yields nothing or raises - a no-match result
    is still a real validation signal, never an exception on the live path."""
    return {
        "take": None,
        "take_rank": None,
        "n_matches": 0,
        "conf": "low",
        "ranked": [
            {"name": c, "rank": None, "in_ideal_path": False} for c in offered
        ],
        "ideal_path": [],
    }


def compute_anvil_pick(
    champion: str,
    current_items: Iterable[str],
    anvil_choices: Iterable[str],
    alive_opponents: Iterable[str],
    hp_pct: int,
    gold: int = 0,
) -> dict:
    """Rank the offered anvil choices against the ideal arena build path.

    Returns a dict: take (offered name with the earliest rank in the ideal path,
    or None), take_rank (int|None), n_matches (offered items found in the path),
    conf ("ok" when n_matches>=1 else "low"), ranked (per-offered name/rank/
    in_ideal_path), ideal_path. Offered names are reported stripped; a non-str,
    blank or over-long choice is dropped. Fail-soft: an unusable champion, an
    empty or raising recompute, or no offered choice yields a low-conf dict and
    never raises."""
    offered = _names(anvil_choices, _MAX_OFFERED)
    champ = str.strip(champion) if isinstance(champion, str) else ""
    if not champ:
        return _low_conf(offered)
    try:
        raw_path = recompute_arena_build(
            champ,
            _names(current_items, _MAX_LIST),
            _clamp_int(gold, 0, None, 0),
            _names(alive_opponents, _MAX_LIST),
            _clamp_int(hp_pct, 0, 100, 100),
        )
    except Exception:  # fail-soft on the live coach path
        log.debug("recompute_arena_build failed for the anvil substrate",
                  exc_info=True)
        return _low_conf(offered)

    # A str path would iterate by character; only a list / tuple is a path.
    ideal_path = (
        _names(raw_path, _MAX_LIST) if isinstance(raw_path, (list, tuple)) else []
    )
    if not ideal_path or not offered:
        return _low_conf(offered)

    norm_path = [_norm(p) for p in ideal_path]

    ranked: list[dict] = []
    best_name = None
    best_rank: int | None = None
    n_matches = 0
    for choice in offered:
        rank = _rank_in_path(_norm(choice), norm_path)
        ranked.append({
            "name": choice,
            "rank": rank,
            "in_ideal_path": rank is not None,
        })
        if rank is not None:
            n_matches += 1
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_name = choice

    return {
        "take": best_name,
        "take_rank": best_rank,
        "n_matches": n_matches,
        "conf": "ok" if n_matches >= 1 else "low",
        "ranked": ranked,
        "ideal_path": ideal_path,
    }
