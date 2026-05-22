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
table is hand-curated at module load - it mirrors the 53-entry
``_PER_SPELL_CC_DURATIONS`` seed exactly so any registry add owes a
matching hint add or the chunk degrades to a generic "CC" word.
"""

from __future__ import annotations

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
# Total = 53 entries / 44 champs at patch 16.10.1 (matches registry).
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
}


def _kind(champion: str, spell_key: str) -> str:
    """Lookup the CC kind word; fallback to 'CC' for unregistered shapes.

    The registry SHOULD cover every (champion, spell_key) the engine
    seam returns (the 53-entry seed is the source of truth). The
    fallback is a defense against a future patch adding spells before
    the hint table catches up.
    """
    return _CC_KIND_HINTS.get((champion, spell_key), "CC")


def enemy_cc_threat_line(
    enemies: list[str | None] | tuple[str | None, ...] | None,
    mode: str | None,
    *,
    limit: int = 3,
) -> str:
    """Render a one-line ENEMY CC threat context for the coach user prompt.

    Reads ``compute_cc_pressure(champion, mode)`` for each enemy; ranks
    by descending ``total_cc_seconds`` (alphabetical tiebreak), takes
    the top ``limit`` (default 3), formats each as
    ``{champion} {duration:.1f}s {kind} ({spell_key})`` where the
    spell with the highest duration is picked from
    ``result.spells``.

    Returns "" when:
      * mode is None / blank
      * limit is non-positive
      * enemies is None / empty / contains only champs with no CC

    Mode-agnostic: SR / ARAM / KIWI / Arena / Brawl all flow through
    ``compute_cc_pressure``. ARAM uses tenacity-lengthened durations;
    other modes use the base.
    """
    if not mode:
        return ""
    if limit is None or limit <= 0:
        return ""
    if not enemies:
        return ""

    candidates: list[tuple[str, float, str, float]] = []
    for name in enemies:
        if not name:
            continue
        try:
            result = compute_cc_pressure(name, mode)
        except Exception:
            continue
        if result is None:
            continue
        try:
            total = float(getattr(result, "total_cc_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if total <= 0.0:
            continue
        spells = getattr(result, "spells", ()) or ()
        if not spells:
            continue
        # Pick the highest-duration spell of this champion. Use the
        # post-tenacity value when ARAM/KIWI mode pumps it; SR mode
        # returns the same value (identity at tenacity=1.0).
        best_spell_key = ""
        best_spell_dur = 0.0
        for sp in spells:
            sp_key = getattr(sp, "spell_key", "") or ""
            try:
                sp_dur = float(
                    getattr(sp, "duration_post_tenacity_s", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                sp_dur = 0.0
            if sp_dur > best_spell_dur:
                best_spell_dur = sp_dur
                best_spell_key = sp_key
        if not best_spell_key or best_spell_dur <= 0.0:
            continue
        candidates.append((name, total, best_spell_key, best_spell_dur))

    if not candidates:
        return ""

    # Sort: descending total, alphabetical tiebreak on champion name.
    candidates.sort(key=lambda c: (-c[1], c[0]))
    top = candidates[:limit]

    chunks: list[str] = []
    for name, _total, sp_key, sp_dur in top:
        kind = _kind(name, sp_key)
        chunks.append(f"{name} {sp_dur:.1f}s {kind} ({sp_key})")

    return "Enemy CC threats: " + ", ".join(chunks)


__all__ = [
    "enemy_cc_threat_line",
]
