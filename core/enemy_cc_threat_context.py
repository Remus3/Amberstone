"""Enemy CC threat coach-prompt consumer.

Closes item 136 carry: first coach-prompt consumer of
``agents.daemon_slayer.cc_pressure.compute_cc_pressure`` (Slice A of the
item-136 parallel drain, which exposes the 53-entry / 44-champ
``_PER_SPELL_CC_DURATIONS`` registry as a per-champion CC pressure
total).

Mirror of the s127 ``core.aram_tenacity_context.enemy_aram_tenacity_line``
pattern: a single render-side helper the coach interpolates into its
user template once per match-state tick. Mode-agnostic (works for SR /
ARAM / KIWI / Arena / Brawl); ARAM tenacity lift flows through
``compute_cc_pressure`` (which the engine seam applies per-spell), the
renderer just reads ``total_cc_seconds`` + per-spell shape.

Output line format:

    Enemy CC threats: Morgana 3.0s root (Q), Malzahar 2.5s suppress (R), Annie 1.5s stun (R)

Each chunk lists the highest-duration spell with its key + a one-word
CC kind hint (stun / root / charm / suppress / fear / silence /
knockup / knockback / sleep / polymorph / taunt) inferred from a small
``_CC_KIND_HINTS`` table indexed by (champion, spell_key) so the
operator sees what TYPE of CC matters most. A 2.5s suppress is much
worse than a 1.5s stun on a flash-target list; the hint disambiguates.

Returns "" when:
  * mode is None / blank
  * limit <= 0
  * enemies is None / empty
  * all entries have total_cc_seconds == 0.0 (no registered CC)

Patch + registry data are read once at module import inside the engine
(``agents.daemon_slayer.cc_pressure``); this consumer holds NO
champion data of its own and rebuilds nothing on call. The kind-hint
table is hand-curated at module load and must cover every
``_PER_SPELL_CC_DURATIONS`` slot (a registry add owes a matching hint
add, or the chunk degrades to a generic "CC" word);
``tests/test_enemy_cc_threat_context_hardening.py`` fails on a slot in
either set but not the other.

NAMES (s144 true-audit cycle 72)
    Every coach passes the Live Client roster, whose ``championName`` is a
    DISPLAY name ("Wukong", "Cho'Gath", "Jarvan IV"), while the registry
    and the hint table key on canonical DDragon ids ("MonkeyKing",
    "Chogath", "JarvanIV"). Each entry is resolved through
    ``core.archetype_picks.canonical_champion_id`` before the engine read
    and the hint lookup; the rendered chunk keeps the display name the
    coach prompt uses everywhere else. One champion renders once, however
    many name forms of it the roster carries.

FAIL-SOFT
    Never raises on a malformed argument: a non-str / blank ``mode``, a
    non-int (or bool) ``limit``, a roster that is not a list / tuple
    (a bare string is NOT iterated per character), a non-str entry, and a
    non-finite (NaN / inf) total or spell duration all degrade to "" or
    skip that one entry.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, Tuple

try:
    # Slice A of item 136 ships ``agents.daemon_slayer.cc_pressure``;
    # the orchestrator merges A before B. When this consumer is
    # imported standalone (parallel slice, fresh checkout, etc.) the
    # symbol still needs to exist as a patch target so unit tests can
    # monkey-patch it via unittest.mock.patch. The fallback stub
    # returns None so the renderer skips the champion (matches the
    # contract "empty result when champion not in registry").
    from agents.daemon_slayer.cc_pressure import compute_cc_pressure
except ImportError:  # pragma: no cover - exercised only pre-merge
    def compute_cc_pressure(champion: str, mode: str = "SR"):  # type: ignore[misc]
        return None

_log = logging.getLogger(__name__)

_ARAM_MODES = frozenset(
    ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "aram", "kiwi")
)

# (champion, spell_key) -> one-word CC kind hint.
#
# Wave 1 (24 champs, 30 entries; item 134 Slice B 05f2475):
#   Ahri / Annie / Ashe / Blitzcrank / Cassiopeia / Galio (W+E+R) /
#   Leona (Q+E+R) / Lissandra / Lulu / Malzahar / Maokai /
#   MonkeyKing / Morgana / Nautilus (Q+R) / Pantheon / Rakan /
#   Renekton / Sejuani / Sona / Thresh / Veigar / Vi (Q+R) / Yasuo /
#   Zoe.
#
# Wave 2 (+20 champs / +23 entries; item 135 Slice B 758756f):
#   Alistar (Q+W) / Amumu (Q+R) / Anivia / Braum / Chogath /
#   Fiddlesticks / Gnar / Gragas / Jhin / Lux / Nami /
#   Neeko (E+R) / Orianna / Poppy / Riven / Singed / Skarner /
#   Varus / Xerath / Zac.
#
# Waves 3+ (+55 entries; s144 true-audit cycle 72): every registry slot
#   seeded after item 135 had no hint and rendered the generic "CC". Each
#   word below is the CC kind the registry's OWN comment names for that
#   slot in agents/daemon_slayer/_per_spell_cc.py (the duration authority),
#   never a fresh reading of the champion's kit.
#
# Total = 108 entries / 89 champs (matches registry; guarded both ways).
# Missing-key fallback: "CC" (generic; covered by KindHintsTests).
_CC_KIND_HINTS: Dict[Tuple[str, str], str] = {
    # Wave 1
    ("Ahri", "E"): "charm",
    ("Annie", "R"): "stun",
    ("Ashe", "R"): "stun",
    ("Blitzcrank", "Q"): "stun",
    ("Cassiopeia", "R"): "stun",
    ("Galio", "W"): "taunt",
    ("Galio", "E"): "knockup",
    ("Galio", "R"): "knockup",
    ("Leona", "Q"): "stun",
    ("Leona", "E"): "root",
    ("Leona", "R"): "stun",
    ("Lissandra", "R"): "stun",
    ("Lulu", "W"): "polymorph",
    ("Malzahar", "R"): "suppress",
    ("Maokai", "R"): "root",
    ("MonkeyKing", "R"): "knockup",
    ("Morgana", "Q"): "root",
    ("Nautilus", "Q"): "root",
    ("Nautilus", "R"): "knockup",
    ("Pantheon", "W"): "stun",
    ("Rakan", "W"): "knockup",
    ("Renekton", "W"): "stun",
    ("Sejuani", "R"): "stun",
    ("Sona", "R"): "stun",
    ("Thresh", "Q"): "stun",
    ("Veigar", "E"): "stun",
    ("Vi", "Q"): "knockup",
    ("Vi", "R"): "knockup",
    ("Yasuo", "R"): "knockup",
    ("Zoe", "E"): "sleep",
    # Wave 2 (item 135)
    ("Alistar", "Q"): "knockup",
    ("Alistar", "W"): "knockup",
    ("Amumu", "Q"): "stun",
    ("Amumu", "R"): "stun",
    ("Anivia", "Q"): "stun",
    ("Braum", "R"): "knockup",
    ("Chogath", "Q"): "knockup",
    ("Fiddlesticks", "Q"): "fear",
    ("Gnar", "R"): "knockback",
    ("Gragas", "E"): "stun",
    ("Jhin", "W"): "root",
    ("Lux", "Q"): "root",
    ("Nami", "Q"): "knockup",
    ("Neeko", "E"): "root",
    ("Neeko", "R"): "stun",
    ("Orianna", "R"): "knockup",
    ("Poppy", "E"): "stun",
    ("Riven", "W"): "stun",
    ("Singed", "E"): "knockback",
    ("Skarner", "R"): "suppress",
    ("Varus", "R"): "root",
    ("Xerath", "E"): "stun",
    ("Zac", "E"): "knockup",
    # Waves 3+ (s144 true-audit cycle 72; kinds from the registry comments)
    ("AurelionSol", "R"): "stun",
    ("Bard", "R"): "stasis",
    ("Caitlyn", "W"): "root",
    ("Camille", "E"): "stun",
    ("Chogath", "W"): "silence",
    ("Diana", "R"): "knockup",
    ("Draven", "E"): "knockback",
    ("Ekko", "W"): "stun",
    ("Elise", "E"): "stun",
    ("Hecarim", "E"): "knockback",
    ("Hecarim", "R"): "fear",
    ("Heimerdinger", "E"): "stun",
    ("Irelia", "E"): "stun",
    ("Ivern", "Q"): "root",
    ("Janna", "Q"): "knockup",
    ("Jax", "E"): "stun",
    ("Jinx", "E"): "root",
    ("KSante", "R"): "knockup",
    ("Kalista", "R"): "knockup",
    ("Lillia", "R"): "sleep",
    ("Lissandra", "W"): "root",
    ("Lulu", "R"): "knockup",
    ("Malphite", "R"): "knockup",
    ("Malzahar", "Q"): "silence",
    ("Maokai", "W"): "root",
    ("Mel", "E"): "root",
    ("Mordekaiser", "E"): "pull",
    ("Nocturne", "E"): "fear",
    ("Ornn", "R"): "knockup",
    ("Pyke", "Q"): "stun",
    ("Quinn", "E"): "knockback",
    ("Rakan", "R"): "charm",
    ("Rammus", "E"): "taunt",
    ("Rell", "Q"): "root",
    ("Ryze", "W"): "root",
    ("Sejuani", "Q"): "stun",
    ("Senna", "W"): "root",
    ("Seraphine", "R"): "charm",
    ("Shaco", "W"): "fear",
    ("Shen", "E"): "taunt",
    ("Shyvana", "R"): "knockback",
    ("Sion", "Q"): "stun",
    ("Smolder", "R"): "knockup",
    ("Soraka", "E"): "root",
    ("Thresh", "E"): "knockback",
    ("Tristana", "R"): "knockback",
    ("Urgot", "E"): "knockback",
    ("Vayne", "E"): "knockback",
    ("Viego", "W"): "stun",
    ("Volibear", "E"): "knockup",
    ("XinZhao", "W"): "knockup",
    ("Yone", "R"): "knockup",
    ("Zac", "R"): "knockup",
    ("Ziggs", "W"): "knockback",
    ("Zyra", "E"): "root",
}


def _kind(champion: str, spell_key: str) -> str:
    """Lookup the CC kind word; fallback to 'CC' for unregistered shapes.

    ``champion`` is the canonical DDragon id (the table's key form). The
    registry SHOULD cover every (champion, spell_key) the engine seam
    returns (guarded both ways in the hardening tests). The fallback is a
    defense against a future patch adding spells before the hint table
    catches up.
    """
    return _CC_KIND_HINTS.get((champion, spell_key), "CC")


def _canonical_id(display: str) -> str:
    """Resolve a Live Client display name to its canonical DDragon id.

    Lazy import: ``core.archetype_picks`` costs a few tens of ms to import
    and is only needed once a roster arrives. Any failure of the resolver
    falls back to the display name itself, which is exactly the pre-fix
    behaviour (a canonical id still matches; a display form does not).
    """
    try:
        from core.archetype_picks import canonical_champion_id

        cid = canonical_champion_id(display)
    except Exception:  # noqa: BLE001 - fail-soft resolver, never break a prompt
        _log.debug("enemy_cc_threat: id resolve failed for %r", display,
                   exc_info=True)
        return display
    return cid if isinstance(cid, str) and cid else display


def _finite_float(value: object) -> float | None:
    """``float(value)`` when it is a finite number, else None."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def enemy_cc_threat_line(
    enemies: list[str | None] | tuple[str | None, ...] | None,
    mode: str | None,
    *,
    limit: int = 3,
) -> str:
    """Render a one-line ENEMY CC threat context for the coach user prompt.

    Resolves each enemy display name to its canonical DDragon id, reads
    ``compute_cc_pressure(champion_id, mode)``; ranks by descending
    ``total_cc_seconds`` (alphabetical tiebreak on the display name),
    takes the top ``limit`` (default 3), formats each as
    ``{display_name} {duration:.1f}s {kind} ({spell_key})`` where the
    spell with the highest finite duration is picked from
    ``result.spells``.

    Returns "" when:
      * mode is not a non-blank str
      * limit is not a positive int (a bool is not an int here)
      * enemies is not a list / tuple, is empty, or contains only champs
        with no CC

    Mode-agnostic: SR / ARAM / KIWI / Arena / Brawl all flow through
    ``compute_cc_pressure``. ARAM uses tenacity-lengthened durations;
    other modes use the base.
    """
    if not isinstance(mode, str) or not mode.strip():
        return ""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return ""
    if not isinstance(enemies, (list, tuple)) or not enemies:
        return ""

    candidates: list[tuple[str, float, str, float, str]] = []
    seen_ids: set[str] = set()
    for raw in enemies:
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not name:
            continue
        cid = _canonical_id(name)
        if cid in seen_ids:
            continue
        try:
            result = compute_cc_pressure(cid, mode)
        except Exception:  # noqa: BLE001 - engine seam is fail-soft by contract
            _log.debug("enemy_cc_threat: compute_cc_pressure failed for %r",
                       cid, exc_info=True)
            continue
        if result is None:
            continue
        total = _finite_float(getattr(result, "total_cc_seconds", 0.0))
        if total is None or total <= 0.0:
            continue
        spells = getattr(result, "spells", ()) or ()
        if not isinstance(spells, (list, tuple)) or not spells:
            continue
        # Pick the highest-duration spell of this champion. Use the
        # post-tenacity value when ARAM/KIWI mode pumps it; SR mode
        # returns the same value (identity at tenacity=1.0). A
        # non-finite duration is skipped, so it neither wins nor hides
        # a finite sibling.
        best_spell_key = ""
        best_spell_dur = 0.0
        for sp in spells:
            sp_key = getattr(sp, "spell_key", "") or ""
            if not isinstance(sp_key, str):
                continue
            sp_dur = _finite_float(getattr(sp, "duration_post_tenacity_s", 0.0))
            if sp_dur is not None and sp_dur > best_spell_dur:
                best_spell_dur = sp_dur
                best_spell_key = sp_key
        if not best_spell_key or best_spell_dur <= 0.0:
            continue
        seen_ids.add(cid)
        candidates.append((name, total, best_spell_key, best_spell_dur, cid))

    if not candidates:
        return ""

    # Sort: descending total, alphabetical tiebreak on champion name.
    candidates.sort(key=lambda c: (-c[1], c[0]))
    top = candidates[:limit]

    chunks: list[str] = []
    for name, _total, sp_key, sp_dur, cid in top:
        kind = _kind(cid, sp_key)
        chunks.append(f"{name} {sp_dur:.1f}s {kind} ({sp_key})")

    return "Enemy CC threats: " + ", ".join(chunks)


__all__ = [
    "enemy_cc_threat_line",
]
