"""Deterministic ARAM fight-risk projection (Stage 1, Tier-1, no live wiring).

Pure PROJECTION (not prediction) of the single most dangerous enemy
ability into two short coach strings. Part of the correct-by-construction
ARAM coach surface that will later replace the ARAM per-tick Haiku call.

GROUNDED INPUT SHAPE: the enemy CC/threat ranking produced by
``core.enemy_cc_threat_context.enemy_cc_threat_line`` (contract read
from ``core/enemy_cc_threat_context.py:149-231``). That helper ranks
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
"""
from __future__ import annotations

import re

# Prefix emitted by enemy_cc_threat_line; stripped before chunk parse.
_LINE_PREFIX = "Enemy CC threats:"

# Parse a single formatted chunk: "Ashe 3.0s stun (R)".
#   group 1 champion (greedy up to the duration token)
#   group 2 duration seconds (float)
#   group 3 kind word
#   group 4 spell key (inside parens)
_CHUNK_RE = re.compile(
    r"^\s*(?P<champion>.+?)\s+(?P<dur>\d+(?:\.\d+)?)s\s+"
    r"(?P<kind>\S+)\s+\((?P<key>[^)]+)\)\s*$"
)


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
    try:
        dur = float(m.group("dur"))
    except (TypeError, ValueError):
        dur = None
    champ = m.group("champion").strip()
    if not champ:
        return None
    return (champ, dur, m.group("kind").strip(), m.group("key").strip())


def _entry_get(entry, *keys):
    """Read the first present, truthy field from a mapping or object."""
    for key in keys:
        val = None
        if isinstance(entry, dict):
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
        if isinstance(threats, dict):
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

        champion = _entry_get(entry, "champion", "name")
        if not champion or not isinstance(champion, str):
            return None
        kind = _entry_get(entry, "kind")
        spell_key = _entry_get(entry, "spell_key", "key")
        dur_raw = _entry_get(
            entry, "duration_s", "duration", "duration_post_tenacity_s"
        )
        try:
            dur = float(dur_raw) if dur_raw is not None else None
        except (TypeError, ValueError):
            dur = None
        kind = kind if isinstance(kind, str) else None
        spell_key = spell_key if isinstance(spell_key, str) else None
        return (champion.strip(), dur, kind, spell_key)
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
    """Trim to at most ``max_words`` whitespace-delimited words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


__all__ = ["fight_rule", "risk"]
