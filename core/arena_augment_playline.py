# arch: deterministic Arena augment play-line | section=core | frozen=no
"""Deterministic "play your current augment this way" line for Arena.

PURPOSE
    ``coaches/arena_coach.py:171`` asks the live Haiku call for two things
    under one field:

        Augment advice: <if augment select: take X - why.
                         Else: play your current augment this way>

    The SELECT half already has a deterministic owner
    (``core.augment_recommender``). The PLAY half had none, which is why
    ``core/arena_deterministic_coach.py`` hardcoded ``augment_advice`` to ""
    as a documented v1 degrade. That degrade is now closed: the augments the
    player actually owns arrive on every tick as apiNames in
    ``state["augments"]`` (set at ``coaches/arena_coach.py:459``, persisted
    apiName-mapped at ``:943``), and Riot's own effect text for all 225 of
    them ships on disk in ``data/daemon_slayer/<patch>/arena_augments.json``.

    Naming an owned augment and restating its real effect is a lookup, not a
    guess - which is the bar this module has to clear, because a precompute
    that is WRONG is worse than a Haiku call.

CORRECT-BY-CONSTRUCTION, NEVER INVENTED
    127 of the 225 ``desc`` strings carry unresolved ``@Placeholder@``
    variables whose real values live in a per-rarity ``dataValues`` array.
    Guessing which rarity tier is live would manufacture wrong numbers, so
    this module never tries: it drops any SENTENCE still holding a
    placeholder and keeps the rest. 126 augments retain real effect text;
    the remaining 99 degrade to a name-only line. A broken ``@Var@`` or a
    fabricated number can therefore never reach the player.

NO LLM, NO NETWORK, NO SERVED-OUTPUT CHANGE
    Pure disk read plus string work. The live Arena Haiku call is untouched;
    wiring this into the deterministic block only fills a column that was
    previously always empty, for the operator to shadow-compare before any
    flip is considered.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DS_DIR = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_AUGMENT_FILE = "arena_augments.json"

SEPARATOR = " | "

_MAX_AUGMENTS = 3
_MAX_EFFECT_LEN = 180

_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_ROWS_CACHE: list[dict] | None = None
_INDEX_CACHE: dict[str, dict] | None = None


def reset_cache() -> None:
    """Drop the memoised augment table (used by tests and patch rollovers)."""
    global _ROWS_CACHE, _INDEX_CACHE
    _ROWS_CACHE = None
    _INDEX_CACHE = None


def _resolve_patch() -> str | None:
    try:
        return (_DS_DIR / "current.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _rows() -> list[dict]:
    """The active patch's augment rows; ``[]`` fail-soft."""
    global _ROWS_CACHE
    if _ROWS_CACHE is not None:
        return _ROWS_CACHE
    rows: list[dict] = []
    patch = _resolve_patch()
    if patch:
        try:
            raw = (_DS_DIR / patch / _AUGMENT_FILE).read_text(encoding="utf-8")
            loaded = json.loads(raw).get("augments")
            if isinstance(loaded, list):
                rows = [r for r in loaded if isinstance(r, dict)]
        except (OSError, ValueError, TypeError, AttributeError):
            rows = []
    _ROWS_CACHE = rows
    return rows


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _load_index() -> dict[str, dict]:
    """norm(apiName) and norm(name) -> augment row. Memoised; ``{}`` fail-soft.

    apiName is written first and never overwritten, so a display name that
    happens to normalise onto another row's apiName cannot shadow it.
    """
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    index: dict[str, dict] = {}
    rows = _rows()
    for row in rows:
        key = _norm(row.get("apiName"))
        if key and key not in index:
            index[key] = row
    for row in rows:
        key = _norm(row.get("name"))
        if key and key not in index:
            index[key] = row
    _INDEX_CACHE = index
    return index


def _clean_text(raw: object) -> str:
    """Strip Riot markup, normalise spacing, and drop placeholder sentences."""
    text = _TAG_RE.sub(" ", str(raw or ""))
    text = " ".join(text.split())
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    # A sentence still holding @Var@ has no honest value here - see module
    # docstring on why the per-rarity dataValues array is not resolved.
    kept = [s for s in _SENTENCE_SPLIT_RE.split(text) if s and "@" not in s]
    out = " ".join(kept).strip()
    # SEPARATOR is the caller's field delimiter, so it must not appear inside
    # a segment or a consumer splitting on it would mis-count augments.
    out = out.replace("|", "/")
    if len(out) > _MAX_EFFECT_LEN:
        out = out[:_MAX_EFFECT_LEN].rstrip() + "..."
    return out


def _segment(row: dict) -> str:
    name = str(row.get("name") or "").strip()
    if not name:
        return ""
    effect = _clean_text(row.get("desc"))
    if not effect:
        return f"Playing {name}."
    return f"Playing {name}: {effect}"


def play_line(owned_augments: object = None, *, max_augments: int = _MAX_AUGMENTS) -> str:
    """Deterministic play-guidance line for the augments the player owns.

    Args:
        owned_augments: apiNames (as ``state["augments"]`` carries) and/or
            display names (as vision HUD resolution may carry). A bare string
            is treated as ONE augment, never iterated per character. Entries
            that do not resolve are skipped rather than guessed at.
        max_augments: how many owned augments to describe, in input order.

    Returns:
        ``"Playing <Name>: <effect>"`` segments joined by ``SEPARATOR``, or
        ``""`` when nothing resolves. NEVER raises.
    """
    try:
        if owned_augments is None:
            return ""
        if isinstance(owned_augments, str):
            entries: list[object] = [owned_augments]
        else:
            entries = list(owned_augments)
        try:
            cap = int(max_augments)
        except (TypeError, ValueError):
            cap = _MAX_AUGMENTS
        if cap <= 0:
            return ""
        index = _load_index()
        segments: list[str] = []
        for entry in entries:
            if len(segments) >= cap:
                break
            if not isinstance(entry, str):
                continue
            row = index.get(_norm(entry))
            if row is None:
                continue
            segment = _segment(row)
            if segment:
                segments.append(segment)
        return SEPARATOR.join(segments)
    except (TypeError, ValueError, AttributeError):
        return ""


__all__ = ["play_line", "reset_cache", "SEPARATOR"]
