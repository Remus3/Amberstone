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
from dataclasses import dataclass
from pathlib import Path

# A game shorter than this is a remake, not a match.
REMAKE_MAX_SECONDS = 300

# Measured share of games carrying an AFK that Match-V5 cannot see. Report it
# with any mined rate so the reader can size the noise floor.
UNDETECTABLE_AFK_RATE = 0.015


@dataclass(frozen=True)
class Verdict:
    include: bool
    reason: str = ""


def sidecar_has_afk(sidecar_path) -> bool:
    """Ground truth from a .rofl stats sidecar, where one exists.

    WAS_AFK arrives as a STRING like every sidecar value, so it is compared
    numerically rather than truthily - the string '0' is truthy in Python and
    would mark every player AFK.
    """
    try:
        blob = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for player in blob.get("players") or []:
        for key in ("WAS_AFK", "WAS_LEAVER"):
            try:
                if float(player.get(key) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def judge(match: dict, sidecar_path=None) -> Verdict:
    """Should this match be mined?

    *sidecar_path* is optional; when present it supplies AFK ground truth that
    the match blob cannot.
    """
    info = (match or {}).get("info") or {}
    duration = int(info.get("gameDuration") or 0)
    if duration and duration < REMAKE_MAX_SECONDS:
        return Verdict(False, f"remake ({duration}s)")

    participants = info.get("participants") or []
    if participants and participants[0].get("gameEndedInEarlySurrender"):
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
