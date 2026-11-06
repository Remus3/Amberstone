"""Decide which corpus matches are fit to mine coaching rules from.

A rule mined from a game somebody AFK'd in is noise wearing a number, so the
mining corpus needs a filter. This module is deliberately conservative: it
excludes only what is MEASURED, and states the contamination it cannot remove
rather than pretending the corpus is clean.

MEASURED 2026-07-26 over all 407 archived .rofl games (4070 player-rows):

    games with at least one WAS_AFK player .......  9 of 407  (2.2 pct)
    of those, detectable from Match-V5 alone ......  3        (they are remakes)
    UNDETECTABLE from Match-V5 ....................  6        (1.5 pct of games)

    remakes, duration < 300 s .....................  3
    gameEndedInEarlySurrender .....................  0
    WAS_LEAVER player-rows ........................  6 of 4070

**MATCH-V5 HAS NO AFK FLAG. The .rofl stats sidecar does.** That is one of the
few things the replay corpus knows that the API does not, and it only covers
games we hold a .rofl for.

NO AFK PROXY IS PROVIDED, and that is a measurement not an omission. Two
candidates were tested against the sidecar ground truth:

    timePlayed < 0.9 * gameDuration ... caught  0 of 10 AFK rows
    damage per minute < 100 ........... caught  2 of 10, 0.42 pct false positives

`timePlayed` is not a disconnect measure - it tracks game length even for an
AFK player. The AFK medians ARE lower across damage, gold, cs and timePlayed
(3625 vs 17808 damage, 77 vs 185 cs), but the distributions overlap and n=10
is far too small to fit a classifier to. Do not build one on this evidence; if
a proxy is wanted, gather more ground truth first by growing the .rofl corpus.

CONSEQUENCE for the mining corpus: roughly 1.5 pct of timeline-only games carry
an undetectable AFK. That is a bounded, known contamination rate. State it
alongside any mined rate rather than implying the corpus is clean.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# A game shorter than this is a remake, not a match.
REMAKE_MAX_SECONDS = 300

# A gameDuration above this cannot be seconds (16.7 hours): pre-11.20
# Match-V5 blobs carry MILLISECONDS, so such a value is divided by 1000.
# Same threshold as tools/mine_event_patterns.py _minutes (RM-1927).
MILLISECONDS_ABOVE = 60000

# Measured share of games carrying an AFK that Match-V5 cannot see. Report it
# with any mined rate so the reader can size the noise floor.
UNDETECTABLE_AFK_RATE = 0.015

# Only these spellings CLEAR the early-surrender flag. Any other set value
# (including junk) excludes the match, because the source set it. Same set
# and rule as core.resolved_wr (RM-1920 there, RM-1929 here).
_FLAG_FALSE_STRINGS = frozenset({"", "0", "false", "no", "n", "off"})

_AFK_KEYS = ("WAS_AFK", "WAS_LEAVER")


@dataclass(frozen=True)
class Verdict:
    include: bool
    reason: str = ""


def _finite_number(value: Any) -> float | None:
    """*value* as a finite float, or None. Bools are not numbers here."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return None
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _duration_seconds(value: Any) -> int | None:
    """gameDuration as whole seconds, or None when it is UNKNOWN.

    Unknown = missing, bool, non-numeric, non-finite, negative or under one
    second (RM-1925 / RM-1926): an unknown duration is never read as a
    remake. A value above MILLISECONDS_ABOVE is milliseconds (RM-1927).
    """
    number = _finite_number(value)
    if number is None:
        return None
    if number > MILLISECONDS_ABOVE:
        number /= 1000.0
    if number < 1:
        return None
    return int(number)


def _flag_set(value: Any) -> bool:
    """True unless *value* is missing or an explicit false (RM-1929)."""
    if value is None or value is False:
        return False
    if isinstance(value, str) and value.strip().lower() in _FLAG_FALSE_STRINGS:
        return False
    number = _finite_number(value)
    if number is not None:
        return number != 0
    # True, NaN, inf or any other type: not an explicit false.
    return True


def _sidecar_flag(value: Any) -> bool:
    """A sidecar WAS_AFK / WAS_LEAVER value read as a measured yes.

    Values arrive as STRINGS, so they are compared numerically, never
    truthily (the string '0' is truthy). A non-finite value is junk, not a
    count (RM-1932); a JSON true is an explicit yes.
    """
    if value is True:
        return True
    number = _finite_number(value)
    return number is not None and number > 0


def sidecar_has_afk(sidecar_path) -> bool:
    """Ground truth from a .rofl stats sidecar, where one exists.

    WAS_AFK arrives as a STRING like every sidecar value, so it is compared
    numerically rather than truthily - the string '0' is truthy in Python and
    would mark every player AFK.

    Never raises. A missing, unreadable, undecodable or malformed sidecar
    supplies no ground truth and returns False (RM-1930 / RM-1933).
    """
    try:
        # utf-8-sig: a BOM-prefixed sidecar keeps its ground truth
        # (RM-1931); a plain UTF-8 file reads the same.
        blob = json.loads(Path(sidecar_path).read_text(encoding="utf-8-sig"))
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError. ValueError
    # also covers JSONDecodeError and a NUL in the path, TypeError a non-path
    # argument, RecursionError a pathologically nested file (RM-1933).
    except (OSError, ValueError, TypeError, RecursionError):
        return False
    if not isinstance(blob, Mapping):
        return False
    players = blob.get("players")
    if not isinstance(players, (list, tuple)):
        return False
    for player in players:
        if not isinstance(player, Mapping):
            continue
        if any(_sidecar_flag(player.get(key)) for key in _AFK_KEYS):
            return True
    return False


def _shape_problem(match: Any) -> str:
    """Why *match* is not a Match-V5-shaped blob, or "" when it is.

    A missing ``info`` or ``participants`` is ABSENT data and passes; a
    present one of the wrong type is malformed (RM-1928), and the miners
    that iterate ``match["info"]["participants"]`` would crash on it.
    """
    if not isinstance(match, Mapping):
        return "malformed match"
    info = match.get("info")
    if info is None:
        return ""
    if not isinstance(info, Mapping):
        return "malformed match info"
    participants = info.get("participants")
    if participants is None:
        return ""
    if not isinstance(participants, (list, tuple)) or not all(
            isinstance(p, Mapping) for p in participants):
        return "malformed participants"
    return ""


def judge(match: Any, sidecar_path=None) -> Verdict:
    """Should this match be mined?

    *sidecar_path* is optional; when present it supplies AFK ground truth that
    the match blob cannot.

    Never raises. An unknown duration is not a remake and absent data never
    excludes; a malformed blob is never mined (reason starts "malformed").
    """
    problem = _shape_problem(match)
    if problem:
        return Verdict(False, problem)
    info = match.get("info") or {}

    duration = _duration_seconds(info.get("gameDuration"))
    if duration is not None and duration < REMAKE_MAX_SECONDS:
        return Verdict(False, f"remake ({duration}s)")

    # Every seat carries the flag in Match-V5; read all of them so a seat 1
    # missing it does not hide the others (RM-1929).
    participants = info.get("participants") or ()
    if any(_flag_set(p.get("gameEndedInEarlySurrender"))
           for p in participants):
        return Verdict(False, "early surrender")

    if sidecar_path and sidecar_has_afk(sidecar_path):
        return Verdict(False, "afk or leaver (sidecar ground truth)")

    return Verdict(True, "")


def partition(items):
    """Split (match, sidecar_path) pairs into (included, excluded_with_reason)."""
    keep, drop = [], []
    for match, sidecar in items:
        v = judge(match, sidecar)
        (keep if v.include else drop).append((match, v.reason))
    return keep, drop
