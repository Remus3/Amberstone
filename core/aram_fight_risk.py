"""Deterministic ARAM fight-risk projection (Stage 1, Tier-1).

Pure PROJECTION (not prediction) of the single most dangerous enemy
ability into two short coach strings. Part of the correct-by-construction
ARAM coach surface that will later replace the ARAM per-tick Haiku call.
LIVE: ``core.aram_deterministic_coach`` and ``core.arena_deterministic_coach``
call both functions from their block builders, which
``dashboard/_deterministic_coaching.py`` runs over the
``enemy_cc_threat_line`` it renders for the ARAM and Arena enemy rosters.

GROUNDED INPUT SHAPE: the enemy CC/threat ranking produced by
``core.enemy_cc_threat_context.enemy_cc_threat_line`` (contract read
from ``enemy_cc_threat_line`` and its ``_kind`` fallback in
``core/enemy_cc_threat_context.py``). That helper ranks
enemies DESCENDING by ``total_cc_seconds`` (alphabetical tiebreak), and
for each picks the highest-duration spell, rendering one chunk per enemy
as ``{champion} {duration:.1f}s {kind} ({spell_key})`` joined with ", "
behind the literal prefix "Enemy CC threats: ". Because the ranking is
already applied upstream, the TOP (first) entry is the threat to respect.

This module therefore consumes that same ranked input in EITHER form
and reads only the first entry:

  * the pre-formatted ``enemy_cc_threat_line`` string, e.g.
    "Enemy CC threats: Ashe 3.0s stun (R), Annie 1.5s stun (R)" - we
    parse the prefix off and split on ", " (a champion display name has
    no comma in the DDragon set), then read the first chunk; OR
  * a ranked iterable of entries, each a mapping or an object exposing a
    champion name (key/attr ``champion`` or ``name``), a CC-kind word
    (``kind``), and a spell key (``spell_key``). A duration field
    (``duration_s`` / ``duration`` / ``duration_post_tenacity_s``) is
    read when present but is not required to emit a string.

Why build on the formatted string at all: ``enemy_cc_threat_line`` is
the existing, unit-tested surface that already does the ranking + the
per-champion best-spell pick + the kind-word lookup. Re-deriving that
here would duplicate the engine seam. Accepting its output lets a later
wiring stage pass the line straight through, while the structured path
keeps this module usable directly against the ranked entries.

Both functions are FAIL-SOFT: any empty / malformed / None / unexpected
input returns "" and NEVER raises.

FIELD RULES (s144 true-audit). Each field is validated on its own, so one
junk field degrades only itself:

  * champion - the minimum: a str with no control / format / surrogate /
    private-use / unassigned character outside whitespace, whitespace
    collapsed to single spaces, 1..64 chars after that, else no threat.
  * spell_key - the producer's vocabulary, exactly one of Q / W / E / R
    (``agents/daemon_slayer/cc_pressure.py`` iterates ``_SPELL_ORDER``);
    anything else is dropped from the string, never echoed.
  * kind - one ASCII word (letters, inner hyphens), 1..16 chars, else
    dropped. The producer's words are the ``_CC_KIND_HINTS`` values plus
    the "CC" fallback.
  * duration - optional. A finite real number (not a bool) reads; anything
    else is unknown and never blanks the threat. A structured entry whose
    duration is a real number <= 0 states the champion has no CC on that
    spell and is not a threat. The formatted line is exempt: its producer
    emits only durations > 0 rounded to one decimal, so "0.0s" there is a
    short CC, not none.

The emitted strings are single-spaced: whitespace is always collapsed, not
only when the word clamp bites.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping

# Prefix emitted by enemy_cc_threat_line; stripped before chunk parse.
_LINE_PREFIX = "Enemy CC threats:"

# Parse a single formatted chunk: "Ashe 3.0s stun (R)".
#   group 1 champion (greedy up to the duration token)
#   group 2 duration seconds (float)
#   group 3 kind word
#   group 4 spell key (inside parens)
# re.ASCII: the producer formats with ``:.1f``, so a Unicode digit (U+0663)
# is not its grammar even though float() would accept one.
_CHUNK_RE = re.compile(
    r"^\s*(?P<champion>.+?)\s+(?P<dur>\d+(?:\.\d+)?)s\s+"
    r"(?P<kind>\S+)\s+\((?P<key>[^)]+)\)\s*$",
    re.ASCII,
)

# The producer's spell keys (cc_pressure._SPELL_ORDER).
_SPELL_KEYS = frozenset(("Q", "W", "E", "R"))

# One CC-kind word: "stun", "knockup", "CC", ... (ASCII, inner hyphens).
_KIND_RE = re.compile(r"[A-Za-z](?:[A-Za-z-]{0,14}[A-Za-z])?", re.ASCII)

# Longest champion display name coached (the same bound
# core/heal_threat.py _CHAMP_NAME_MAX puts on a roster name).
_MAX_CHAMPION_LEN = 64

# Unicode categories never coached: controls, format (zero-width and bidi
# marks), surrogates, private use, unassigned. Whitespace is exempt from the
# check because it is collapsed instead.
_REFUSED_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Co", "Cn"))


def _clean_champion(value):
    """A coachable champion name, or None."""
    if not isinstance(value, str):
        return None
    # Collapse first so the category scan below runs over at most 64 chars.
    name = " ".join(value.split())
    if not name or len(name) > _MAX_CHAMPION_LEN:
        return None
    for ch in name:
        if ch != " " and unicodedata.category(ch) in _REFUSED_CATEGORIES:
            return None
    return name


def _clean_spell_key(value):
    """One of Q / W / E / R, or None (dropped, never echoed)."""
    if not isinstance(value, str):
        return None
    key = value.strip()
    return key if key in _SPELL_KEYS else None


def _clean_kind(value):
    """One short ASCII CC-kind word, or None (dropped, never echoed)."""
    if not isinstance(value, str):
        return None
    kind = value.strip()
    return kind if _KIND_RE.fullmatch(kind) else None


def _clean_duration(value):
    """A finite real-number duration, or None when unknown. Never raises."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        dur = float(value)
    except Exception:  # noqa: BLE001 - an unusable duration is unknown
        return None
    return dur if math.isfinite(dur) else None


def _first_chunk_fields(text: str):
    """Parse the first formatted threat chunk from a line.

    Returns (champion, duration, kind, spell_key) or None if the text is
    not a parseable ``enemy_cc_threat_line`` (or has no chunks).
    """
    if not isinstance(text, str):
        return None
    body = text.strip()
    if not body:
        return None
    if body.startswith(_LINE_PREFIX):
        body = body[len(_LINE_PREFIX):].strip()
    if not body:
        return None
    # The line is already ranked; the first comma-separated chunk is top.
    first = body.split(",", 1)[0].strip()
    m = _CHUNK_RE.match(first)
    if not m:
        return None
    champ = _clean_champion(m.group("champion"))
    if champ is None:
        return None
    try:
        dur = _clean_duration(float(m.group("dur")))
    except (TypeError, ValueError, OverflowError):
        dur = None
    return (champ, dur, _clean_kind(m.group("kind")),
            _clean_spell_key(m.group("key")))


def _entry_get(entry, *keys):
    """Read the first present, truthy field from a mapping or object."""
    for key in keys:
        val = None
        if isinstance(entry, Mapping):
            val = entry.get(key)
        else:
            val = getattr(entry, key, None)
        if val is not None and val != "":
            return val
    return None


def _first_entry_fields(threats):
    """Resolve (champion, duration, kind, spell_key) from ranked input.

    Accepts the pre-formatted line OR a ranked iterable of dict/object
    entries. Returns None when nothing usable (a champion name is the
    minimum) can be read. Never raises.
    """
    try:
        # Pre-formatted line form.
        if isinstance(threats, str):
            return _first_chunk_fields(threats)

        # Reject obvious non-iterables (numbers, bools, None) early.
        if threats is None or isinstance(threats, (int, float, bool)):
            return None

        # Mapping passed directly (not a list of entries) is malformed
        # for our purposes unless it itself looks like one entry.
        if isinstance(threats, Mapping):
            entry = threats
        else:
            iterator = iter(threats)
            entry = next(iterator, None)

        if entry is None:
            return None

        # A bare string entry inside the list could be one formatted
        # chunk; try to parse it, else treat as unusable.
        if isinstance(entry, str):
            return _first_chunk_fields(entry)

        champion = _clean_champion(_entry_get(entry, "champion", "name"))
        if champion is None:
            return None
        # The optional duration is read under its own guard: an unusable one
        # is unknown and must not blank the champion it rides with.
        try:
            dur = _clean_duration(_entry_get(
                entry, "duration_s", "duration", "duration_post_tenacity_s"
            ))
        except Exception:  # noqa: BLE001 - an unusable duration is unknown
            dur = None
        if dur is not None and dur <= 0.0:
            return None
        kind = _clean_kind(_entry_get(entry, "kind"))
        spell_key = _clean_spell_key(_entry_get(entry, "spell_key", "key"))
        return (champion, dur, kind, spell_key)
    except Exception:  # noqa: BLE001 - hard fail-soft contract
        return None


def fight_rule(threats) -> str:
    """Return a <=12-word engage condition naming the top threat to respect.

    Example: "Respect Ashe R (stun) before you commit". Empty / malformed
    / no-data input returns "". Never raises.
    """
    fields = _first_entry_fields(threats)
    if fields is None:
        return ""
    champion, _dur, kind, spell_key = fields
    if not champion:
        return ""

    # "Respect Ashe R (stun) before you commit" - clamp to <=12 words.
    ability = champion
    if spell_key:
        ability = f"{ability} {spell_key}"
    if kind:
        ability = f"{ability} ({kind})"
    out = f"Respect {ability} before you commit"
    return _clamp_words(out, 12)


def risk(threats) -> str:
    """Return a <=10-word string naming the single most dangerous ability.

    Example: "Ashe R - long-range stun engage" (kept terse). Empty /
    malformed / no-data input returns "". Never raises.
    """
    fields = _first_entry_fields(threats)
    if fields is None:
        return ""
    champion, _dur, kind, spell_key = fields
    if not champion:
        return ""

    # "Ashe R stun - top CC threat" - clamp to <=10 words.
    head = champion
    if spell_key:
        head = f"{head} {spell_key}"
    if kind:
        head = f"{head} {kind}"
    out = f"{head} - top CC threat"
    return _clamp_words(out, 10)


def _clamp_words(text: str, max_words: int) -> str:
    """Trim to at most ``max_words`` whitespace-delimited words.

    Always re-joined on single spaces, so a whitespace run never reaches the
    coach string whether or not the clamp bites.
    """
    return " ".join(text.split()[:max_words])


__all__ = ["fight_rule", "risk"]
