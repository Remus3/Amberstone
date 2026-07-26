# arch: hand-authored wiki damage blocks for FORMS Meraki shipped without one | section=agents/daemon_slayer | frozen=no
"""RM-95b residual - authored damage blocks for served forms that carry none.

MEASURED POPULATION (2026-07-26), and it is 1 rather than the 3 the ROADMAP
row states. The RM-95b B2 adjudication walked a live 16.14.1 ``--full-roster``
wiki extract down to three forms that name a real damage label and carry no
``attribute_kind == "damage"`` block, then filed all three as needing a
hand-authored entry. Re-measured against the live snapshot AND the live
evaluator, only one of the three is a data gap:

* **Jayce W Hyper Charge** - NOT a gap. Meraki already ships its numbers as a
  ``Damage Modifier`` block (``[70, 78, 86, 94, 102, 110] % AD``), and the form
  the engine SERVES for Jayce W is form 0 ``Lightning Field``, which scores
  380.0 raw at L13 / rank 4. Hyper Charge is the Mercury-Cannon alternate and
  is an auto-attack rider (a percent of AD on each of three attacks), so
  crediting it on the ability clock is precisely the face-value credit the
  RM-86 spec fences. That is a modelling change on the auto clock, not a
  missing number, and it does not belong in a data registry.
* **Mel W Rebuttal** - NOT a gap. Meraki ships ``[40, 45, 50, 55, 60] %`` of
  the original damage plus ``5 % per 100 AP``. The quantity is a fraction of an
  incoming projectile whose magnitude NO registry carries. Inventing that prior
  is the same move that closed RM-90 S3 BLOCKED-UNFALSIFIABLE, so the current
  0.0 is the correct read, not an omission.
* **Quinn R Skystrike** - REAL, and the only one. Form 1 ``Skystrike`` carries
  ZERO blocks of any kind, and the form the engine serves for Quinn R (form 0,
  ``Behind Enemy Lines``) carries only a movement-speed modifier. Measured on
  the live snapshot at L13 against the sweep-standard tanky target: Quinn R
  ``raw_damage_per_cast == 0.0`` while Q scores 205.0 and E scores 40.0. Her
  ultimate is invisible to her own ability lane.

SOURCE. Fetched 2026-07-26 from ``https://wiki.leagueoflegends.com/en-us/api.php``
``action=query&prop=revisions&rvslots=main&rvprop=content`` - the same host and
endpoint ``tools/daemon_slayer_wiki_ability_extract.py:108-110`` uses. The raw
line is quoted verbatim beside the entry it produced. The page states no
missing-health amplifier and no other conditional term, so the authored block
is the whole of the wiki's damage statement, not a truncation of it.

WHICH FORM THE BLOCK LANDS ON, and why it is form 0. ``ability_dps`` resolves a
spell's form through ``_registries.get_form_index_for``, and Quinn carries NO
override, so R is read at form 0. Authoring onto form 1 - the form actually
named Skystrike - would produce a block the evaluator never reads, and routing
R to form 1 instead would swap in a form whose ``cooldown`` and ``cost`` are
both ``None``. So the block is authored onto the SERVED form and labelled
``Skystrike Physical Damage`` so its provenance stays explicit, and the test
file pins ``get_form_index_for("Quinn")`` at the default - if the form registry
ever routes Quinn R elsewhere, that guard goes RED instead of this entry going
silently unread.

BLOCK ORDER IS DAMAGE-FIRST. ``ability_dps._select_blocks`` reads
``damage_blocks[0]`` under the default ``block_strategy="first"`` and
``get_block_index_for("Quinn")`` carries no override, so the authored block is
PREPENDED. The pre-existing ``Total Movement Speed Increase`` modifier is
preserved and demoted to index 1, which is the same damage-first convention
``_ability_wiki_damage_registry`` states for its authored payloads.

LINEAR EXPANSION IS AN ASSUMPTION, and the same one every sibling registry
makes. ``{{ap|60 to 120}}`` names only the rank-1 and rank-max endpoints;
``_ramp`` expands linearly across the ability's rank count (3 for an ult),
which ``_ability_base_overrides._ramp`` calls "exactly what the wiki
``{{ap|X to Y}}`` macro means".

DEFAULT-OFF. This seam MUTATES a form the engine already serves, so OFF is the
byte-identical contract - the opposite of ``_ability_wiki_damage_registry``,
which injects champions that have no prior behavior to preserve and therefore
ships DEFAULT-ON. Flipping this one default-on is a separate, measured,
operator-gated decision.

ANTI-DOUBLE-APPLY. The entry applies ONLY when the target form carries no
``attribute_kind == "damage"`` block at all. If a future Meraki re-extract
ships Skystrike for real, the guard makes this registry silently inert with no
code change, and re-running the hook on an already-patched container is a
no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping


def _ramp(low: float, high: float, ranks: int) -> list[float]:
    """Expand a wiki ``{{ap|low to high}}`` endpoint pair over ``ranks`` ranks."""
    if ranks < 2:
        return [float(low)]
    step = (float(high) - float(low)) / (ranks - 1)
    return [round(float(low) + step * i, 6) for i in range(ranks)]


@dataclass(frozen=True)
class WikiFormDamageEntry:
    """One authored damage block, keyed to the form the evaluator serves."""

    champion_id: str
    key: str
    form_index: int
    form_name: str
    block: dict[str, Any]
    wiki_page: str
    wiki_leveling: str


WIKI_FORM_DAMAGE_ENTRIES: tuple[WikiFormDamageEntry, ...] = (
    WikiFormDamageEntry(
        champion_id="Quinn",
        key="R",
        form_index=0,
        form_name="Behind Enemy Lines",
        block={
            "attribute": "Skystrike Physical Damage",
            "attribute_kind": "damage",
            "base": _ramp(60.0, 120.0, 3),
            "bonus_ad_pct": [35.0, 35.0, 35.0],
        },
        wiki_page="Template:Data Quinn/Skystrike",
        # |leveling = {{st|Physical Damage|{{ap|60 to 120}} {{as|(+ 35% '''bonus''' AD)}}}}
        wiki_leveling=(
            "{{st|Physical Damage|{{ap|60 to 120}} "
            "{{as|(+ 35% '''bonus''' AD)}}}}"
        ),
    ),
)


def _has_damage_block(form: Mapping[str, Any]) -> bool:
    for block in form.get("damage_blocks") or ():
        if isinstance(block, Mapping) and block.get("attribute_kind") == "damage":
            return True
    return False


def apply_wiki_form_damage(data: MutableMapping[str, Any]) -> tuple[str, ...]:
    """Prepend each authored block onto its served form, in place.

    ``data`` is the raw ``champion_abilities.json`` ``data`` container, i.e. the
    same mapping ``_ability_wiki_damage_registry.inject_missing_champions``
    hooks, BEFORE ``AbilitiesSnapshot.load`` builds ``AbilityForm`` objects out
    of it.

    Returns the ``"<champion>/<key>"`` labels actually applied, so the caller
    can log them. An entry whose champion, key or form index is absent, or
    whose form already carries a damage block, is skipped - which makes this
    idempotent and makes a future upstream fix silently supersede it.
    """
    applied: list[str] = []
    for entry in WIKI_FORM_DAMAGE_ENTRIES:
        keymap = data.get(entry.champion_id)
        if not isinstance(keymap, MutableMapping):
            continue
        forms = keymap.get(entry.key)
        if not isinstance(forms, list) or len(forms) <= entry.form_index:
            continue
        form = forms[entry.form_index]
        if not isinstance(form, MutableMapping) or _has_damage_block(form):
            continue
        blocks = list(form.get("damage_blocks") or ())
        form["damage_blocks"] = [dict(entry.block), *blocks]
        applied.append(f"{entry.champion_id}/{entry.key}")
    return tuple(applied)
