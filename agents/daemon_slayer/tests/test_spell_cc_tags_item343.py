"""per-spell CC trait-tag accessor - schema lift item 343 (2026-06-07).

A NEW forward-marker accessor ``DataSnapshot.spell_cc_tags`` exposing the CDragon
``cc_tags`` datum as a first-class queryable SET - a MACHINE-VERIFIED hard-CC
class flag extracted straight from the spell's CDragon bin, the direct sidecar
complement to the hand-authored ``_per_spell_cc`` registry.  The list was loaded
into ``cdragon_spell_stats`` for every spell (alongside ``ammo`` / ``geometry`` /
``missile_speed`` / ``missile_sub_record``) but no accessor ever surfaced it - a
caller had to reach into the raw sidecar dict to learn whether a spell carries an
immobilizing-CC trait.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/cdragon_spell_stats.json``
via ``DataSnapshot.load()`` (ground-truth probed 2026-06-07; 186 of 683 spells
carry a CC tag - 174 ``Trait_ImmobilizingCCSpell`` + 12
``Trait_SwapsIntoImmobilizingCCSpell``):

* Lux Q (Light Binding)       -> {Trait_ImmobilizingCCSpell}  (root)
* Morgana Q (Dark Binding)    -> {Trait_ImmobilizingCCSpell}  (root)
* Ahri E (Charm)              -> {Trait_ImmobilizingCCSpell}  (charm)
* Leona E (Zenith Blade)      -> {Trait_ImmobilizingCCSpell}  (root + dash)
* Aphelios Q (Weapon Q)       -> {Trait_SwapsIntoImmobilizingCCSpell}  (form-gated)

Empty / absent cases (returns an EMPTY frozenset, never None, never raises):
* Sett W / Lux E / Ezreal Q -> frozenset()  (cc_tags is [] - slow / damage only)
* Aatrox P -> frozenset()  (cc_tags is None for that slot record)
* unknown champ / slot -> frozenset()

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes ``spell_cc_tags`` at
ship - it mirrors the item-233 ``spell_missile_speed`` / item-339
``spell_sub_missile_speed`` sibling accessors (snapshot-method idiom reading the
already-loaded sidecar; no data duplication, patch-refresh-safe) and the
item-336 / 337 / 338 / 339 / 340 / 341 / 342 forward-marker contract (no consumer
-> byte-identical -> ENGINE_VERSION does NOT bump).  ``spell_ammo`` /
``spell_geometry`` / ``spell_missile_speed`` and every serialized surface are
untouched, so live DS output is byte-identical.

The EMPTY-FROZENSET fallback (not None) is the deliberate delta from the
float|None sibling accessors: a CC-tag query is a membership test, and an empty
list (no tag) and an absent record both mean the same thing - "no CC tag" - so
collapsing both to ``frozenset()`` removes the None-vs-empty sentinel ambiguity
and lets a caller write ``IMMOB in snap.spell_cc_tags(champ, slot)`` directly.

Coverage classes:
* ``ValuePinsTests`` - exact tag set per seed from 16.11.1.
* ``DistinctTagsTests`` - immobilizing vs swaps-into-immobilizing are distinct.
* ``EmptyTests`` - empty frozenset for slow/damage spells + absent champ/slot.
* ``HygieneTests`` - absent-sidecar / missing-key / None / non-list (a bare
  string is NOT char-iterated) / non-str element filtered / tuple coerced / dedup,
  via a crafted sidecar (``dataclasses.replace``).
* ``ByteIdenticalTests`` - ``spell_missile_speed`` / ``spell_geometry`` /
  ``spell_ammo`` are UNCHANGED for the seeds (the cc-tag lift touched none).
* ``ForwardMarkerNoConsumerTests`` - no production module other than the
  definition (``data_loader.py``) references ``spell_cc_tags``.
* ``EngineVersionUnchangedTests`` - ENGINE_VERSION stays >= 1.120.0 (no bump).
* ``AsciiHygieneTests`` - the accessor block + this test file are pure-ASCII.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot

IMMOB = "Trait_ImmobilizingCCSpell"
SWAP = "Trait_SwapsIntoImmobilizingCCSpell"


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


# ---------------- stub (hygiene / fallback paths) ----------------


def _stub(snap: DataSnapshot, css: dict) -> DataSnapshot:
    """A DataSnapshot copy carrying only a crafted cdragon_spell_stats.

    spell_cc_tags touches ONLY self.cdragon_spell_stats, so reusing the loaded
    snapshot's other fields and swapping the sidecar dict exercises the guard
    without rebuilding the full constructor (same idiom as item 339).
    """
    return dataclasses.replace(snap, cdragon_spell_stats=css)


# ---------------- expected seed set ----------------

_IMMOB_SEEDS = [("Lux", "Q"), ("Morgana", "Q"), ("Ahri", "E"), ("Leona", "E")]
_SWAP_SEEDS = [("Aphelios", "Q")]
_EMPTY_SEEDS = [("Sett", "W"), ("Lux", "E"), ("Ezreal", "Q"), ("Aatrox", "P")]


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot"), _IMMOB_SEEDS)
def test_immobilizing_seed(snap: DataSnapshot, champ: str, slot: str) -> None:
    assert snap.spell_cc_tags(champ, slot) == frozenset({IMMOB})


@pytest.mark.parametrize(("champ", "slot"), _SWAP_SEEDS)
def test_swap_seed(snap: DataSnapshot, champ: str, slot: str) -> None:
    assert snap.spell_cc_tags(champ, slot) == frozenset({SWAP})


def test_returns_frozenset(snap: DataSnapshot) -> None:
    tags = snap.spell_cc_tags("Lux", "Q")
    assert isinstance(tags, frozenset)
    assert IMMOB in tags


def test_membership_query_idiom(snap: DataSnapshot) -> None:
    # The headline use case: a direct membership test, no None guard needed.
    assert IMMOB in snap.spell_cc_tags("Morgana", "Q")
    assert IMMOB not in snap.spell_cc_tags("Sett", "W")


# ---------------------------------------------------------------------------
# distinct tags: immobilizing vs swaps-into-immobilizing
# ---------------------------------------------------------------------------


def test_swap_is_distinct_from_immob(snap: DataSnapshot) -> None:
    # Aphelios Q is form-gated (swaps-into), NOT a plain immobilizing tag.
    aph = snap.spell_cc_tags("Aphelios", "Q")
    assert SWAP in aph
    assert IMMOB not in aph


def test_coverage_floor_both_tags_present(snap: DataSnapshot) -> None:
    # Soft floor (patch-robust): both trait strings appear across the roster and
    # immobilizing dominates.  Exact 174/12 counts are pinned in the docstring
    # for 16.11.1 but asserted softly here to survive a patch refresh.
    immob = swap = 0
    for champ, rec in snap.cdragon_spell_stats.items():
        if champ.startswith("_"):
            continue
        spells = (rec or {}).get("spells") or {}
        for slot in spells:
            tags = snap.spell_cc_tags(champ, slot)
            immob += IMMOB in tags
            swap += SWAP in tags
    assert immob >= 100, f"expected many immobilizing spells, got {immob}"
    assert swap >= 5, f"expected some swap-into spells, got {swap}"


# ---------------------------------------------------------------------------
# empty / absent cases -> empty frozenset (never None)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot"), _EMPTY_SEEDS)
def test_empty_for_non_cc_spell(snap: DataSnapshot, champ: str, slot: str) -> None:
    assert snap.spell_cc_tags(champ, slot) == frozenset()


def test_empty_for_unknown_champ(snap: DataSnapshot) -> None:
    assert snap.spell_cc_tags("NotAChampion", "Q") == frozenset()


def test_empty_for_unknown_slot(snap: DataSnapshot) -> None:
    assert snap.spell_cc_tags("Lux", "Z") == frozenset()


def test_never_returns_none(snap: DataSnapshot) -> None:
    for champ, slot in _EMPTY_SEEDS + [("NotAChampion", "Q")]:
        assert snap.spell_cc_tags(champ, slot) is not None


# ---------------------------------------------------------------------------
# hygiene / fallback (crafted sidecar)
# ---------------------------------------------------------------------------


def test_absent_sidecar(snap: DataSnapshot) -> None:
    assert _stub(snap, {}).spell_cc_tags("Lux", "Q") == frozenset()


def test_missing_key(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"missile_speed": 1200.0}}}}
    assert _stub(snap, css).spell_cc_tags("X", "Q") == frozenset()


def test_cc_tags_none(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"cc_tags": None}}}}
    assert _stub(snap, css).spell_cc_tags("X", "Q") == frozenset()


def test_cc_tags_empty_list(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"cc_tags": []}}}}
    assert _stub(snap, css).spell_cc_tags("X", "Q") == frozenset()


def test_bare_string_not_char_iterated(snap: DataSnapshot) -> None:
    # A bare string must NOT be treated as an iterable of chars; reject to empty.
    css = {"X": {"spells": {"Q": {"cc_tags": IMMOB}}}}
    assert _stub(snap, css).spell_cc_tags("X", "Q") == frozenset()


def test_non_str_elements_filtered(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"cc_tags": [IMMOB, 1, True, None]}}}}
    assert _stub(snap, css).spell_cc_tags("X", "Q") == frozenset({IMMOB})


def test_tuple_coerced(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"cc_tags": (IMMOB, SWAP)}}}}
    assert _stub(snap, css).spell_cc_tags("X", "Q") == frozenset({IMMOB, SWAP})


def test_duplicate_tags_deduped(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"cc_tags": [IMMOB, IMMOB]}}}}
    assert _stub(snap, css).spell_cc_tags("X", "Q") == frozenset({IMMOB})


# ---------------------------------------------------------------------------
# byte-identical: sibling sidecar accessors untouched
# ---------------------------------------------------------------------------


def test_missile_speed_unchanged(snap: DataSnapshot) -> None:
    assert snap.spell_missile_speed("Lux", "Q") == 1200.0


def test_geometry_unchanged(snap: DataSnapshot) -> None:
    geo = snap.spell_geometry("Lux", "Q")
    assert geo is not None
    assert geo.get("line_width") is not None  # Lux Q is a line skillshot


def test_ammo_accessor_unchanged(snap: DataSnapshot) -> None:
    # Lux Q carries no charge model -> None (byte-identical to pre-lift).
    assert snap.spell_ammo("Lux", "Q") is None


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only data_loader.py (definition) may reference spell_cc_tags.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "data_loader.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "spell_cc_tags" in text:
            offenders.append(path.name)
    assert offenders == [], f"unexpected consumers: {offenders}"


# ---------------------------------------------------------------------------
# engine version unchanged (byte-identical, no bump)
# ---------------------------------------------------------------------------


def test_engine_version_at_least_1_120_0() -> None:
    parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
    assert parts >= (1, 120, 0)


# ---------------------------------------------------------------------------
# ASCII hygiene
# ---------------------------------------------------------------------------


def test_data_loader_module_pure_ascii() -> None:
    src = (
        pathlib.Path(__file__).resolve().parent.parent / "data_loader.py"
    ).read_text(encoding="utf-8")
    bad = [c for c in src if ord(c) > 127]
    assert bad == [], f"non-ASCII chars in data_loader.py: {bad!r}"


def test_this_test_file_pure_ascii() -> None:
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    bad = [c for c in src if ord(c) > 127]
    assert bad == [], f"non-ASCII chars in test file: {bad!r}"
