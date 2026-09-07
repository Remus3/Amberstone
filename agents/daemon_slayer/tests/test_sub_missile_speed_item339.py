"""secondary / sibling_missile speed accessor - schema lift item 339 (2026-06-07).

A NEW forward-marker accessor ``DataSnapshot.spell_sub_missile_speed`` exposing
the CDragon ``missile_sub_record`` datum as a first-class comparable MAGNITUDE -
the speed (units/s) of a spell's SECOND missile phase (a return boomerang, a
recast bolt, a split / follow-up projectile). This is a DISTINCT axis from the
item-233 ``spell_missile_speed`` (the resolved PRIMARY missile speed): the
extractor surfaces ``missile_sub_record`` as the best sibling
``<Ability>/...Missile`` record speed, but the resolver only ever consumed it as
a placeholder-fallback to FILL the primary, so the sibling's own speed was
structurally discarded.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/cdragon_spell_stats.json``
via ``DataSnapshot.load()`` (ground-truth probed 2026-06-07; 91 spells carry a
numeric ``missile_sub_record``, of which 52 DIFFER from their resolved primary
speed - i.e. it is genuinely a second magnitude, not a restatement):

* Caitlyn R (Ace in the Hole)   primary 1500 -> sub 3200.0
* Jinx W (Zap!)                 primary 1200 -> sub 3300.0
* Gnar Q (Boomerang Throw)      primary 1200 -> sub 2500.0
* Kalista Q (Pierce)            primary 1200 -> sub 3000.0
* Braum Q (Winter's Bite)       primary 1100 -> sub 1700.0
* Cassiopeia W (Miasma)         primary 1500 -> sub 3000.0

None cases (present spell, no sibling missile record):
* Lux Q / Annie Q / Garen Q -> None ; unknown champ / slot -> None

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes
``spell_sub_missile_speed`` at ship - it mirrors the item-233
``spell_missile_speed`` sibling accessor (snapshot-method idiom reading the
already-loaded sidecar; no data duplication, patch-refresh-safe) and the
item-336 / 337 / 338 forward-marker contract (no consumer -> byte-identical ->
ENGINE_VERSION does NOT bump). The resolved primary ``spell_missile_speed`` /
``is_projectile`` and every serialized surface are untouched, so live DS output
is byte-identical.

Coverage classes:
* value pins - exact sub-speed per seed from 16.11.1.
* distinct-axis - sub differs from the item-233 primary for the differing seeds.
* shape - the accessor returns a positive float for a seeded spell.
* absent - None for a no-sibling spell (Lux/Annie/Garen Q) and unknown
  champ / slot.
* hygiene / fallback - absent-sidecar / missing-key / bool / non-numeric /
  numeric-string fall to None; int / float coerce to float (SAME guard as the
  item-233 ``spell_missile_speed`` sibling).
* byte-identical - ``spell_missile_speed`` (primary) and ``is_projectile`` are
  UNCHANGED for the seeds (the sub-speed lift touched neither).
* forward-marker - no production module other than the definition
  (``data_loader.py``) references ``spell_sub_missile_speed``.
* engine version - ENGINE_VERSION stays >= 1.120.0 (byte-identical, no bump).
* ASCII hygiene - the new accessor block + this test file are pure-ASCII.
"""

from __future__ import annotations

import pathlib

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.missile import is_projectile


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


# ---------------- stub (hygiene / fallback paths) ----------------


def _stub(snap: DataSnapshot, css: dict) -> DataSnapshot:
    """A DataSnapshot copy carrying only a crafted cdragon_spell_stats.

    spell_sub_missile_speed touches ONLY self.cdragon_spell_stats, so reusing
    the loaded snapshot's other fields and swapping the sidecar dict exercises
    the guard without rebuilding the full constructor.
    """
    import dataclasses

    return dataclasses.replace(snap, cdragon_spell_stats=css)


# ---------------- expected seed set ----------------

_SEEDS: dict[tuple[str, str], float] = {
    ("Caitlyn", "R"): 3200.0,
    ("Jinx", "W"): 3300.0,
    ("Gnar", "Q"): 2500.0,
    ("Kalista", "Q"): 3000.0,
    ("Braum", "Q"): 1700.0,
    ("Cassiopeia", "W"): 3000.0,
}


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot", "speed"), [
    ("Caitlyn", "R", 3200.0),
    ("Jinx", "W", 3300.0),
    ("Gnar", "Q", 2500.0),
    ("Kalista", "Q", 3000.0),
    ("Braum", "Q", 1700.0),
    ("Cassiopeia", "W", 3000.0),
])
def test_seed_sub_speed(
    snap: DataSnapshot, champ: str, slot: str, speed: float
) -> None:
    assert snap.spell_sub_missile_speed(champ, slot) == speed


def test_all_seeds_present_and_positive(snap: DataSnapshot) -> None:
    for (champ, slot), expected in _SEEDS.items():
        got = snap.spell_sub_missile_speed(champ, slot)
        assert got == expected, f"{champ} {slot}: {got!r} != {expected!r}"
        assert isinstance(got, float)
        assert got > 0.0


# ---------------------------------------------------------------------------
# distinct axis: sub speed differs from the item-233 resolved primary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot"), [
    ("Caitlyn", "R"),
    ("Jinx", "W"),
    ("Gnar", "Q"),
    ("Kalista", "Q"),
    ("Braum", "Q"),
    ("Cassiopeia", "W"),
])
def test_sub_differs_from_primary(snap: DataSnapshot, champ: str, slot: str) -> None:
    primary = snap.spell_missile_speed(champ, slot)
    sub = snap.spell_sub_missile_speed(champ, slot)
    assert primary is not None and sub is not None
    assert sub != primary, f"{champ} {slot}: sub {sub} should differ from primary {primary}"


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_returns_float(snap: DataSnapshot) -> None:
    s = snap.spell_sub_missile_speed("Caitlyn", "R")
    assert isinstance(s, float)
    assert s > 0.0


# ---------------------------------------------------------------------------
# absent / None cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot"), [
    ("Lux", "Q"),
    ("Annie", "Q"),
    ("Garen", "Q"),
])
def test_none_for_no_sibling_missile(snap: DataSnapshot, champ: str, slot: str) -> None:
    css = snap.cdragon_spell_stats.get(champ, {}).get("spells", {}).get(slot, {})
    assert css.get("missile_sub_record") is None
    assert snap.spell_sub_missile_speed(champ, slot) is None


def test_none_for_unknown_champ(snap: DataSnapshot) -> None:
    assert snap.spell_sub_missile_speed("NotAChampion", "Q") is None


def test_none_for_unknown_slot(snap: DataSnapshot) -> None:
    assert snap.spell_sub_missile_speed("Caitlyn", "Z") is None


# ---------------------------------------------------------------------------
# hygiene / fallback (crafted sidecar) - SAME guard as spell_missile_speed
# ---------------------------------------------------------------------------


def test_absent_sidecar(snap: DataSnapshot) -> None:
    assert _stub(snap, {}).spell_sub_missile_speed("Caitlyn", "R") is None


def test_missing_key(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"missile_speed": 1200.0}}}}
    assert _stub(snap, css).spell_sub_missile_speed("X", "Q") is None


def test_bool_rejected(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"missile_sub_record": True}}}}
    assert _stub(snap, css).spell_sub_missile_speed("X", "Q") is None


def test_non_numeric_rejected(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"missile_sub_record": "fast"}}}}
    assert _stub(snap, css).spell_sub_missile_speed("X", "Q") is None


def test_numeric_string_rejected(snap: DataSnapshot) -> None:
    # spell_missile_speed does NOT coerce strings -> sibling matches it: None.
    css = {"X": {"spells": {"Q": {"missile_sub_record": "3200"}}}}
    assert _stub(snap, css).spell_sub_missile_speed("X", "Q") is None


def test_int_coerced_to_float(snap: DataSnapshot) -> None:
    css = {"X": {"spells": {"Q": {"missile_sub_record": 3200}}}}
    got = _stub(snap, css).spell_sub_missile_speed("X", "Q")
    assert got == 3200.0
    assert isinstance(got, float)


# ---------------------------------------------------------------------------
# byte-identical: primary missile speed / projectile classification untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot", "primary"), [
    ("Caitlyn", "R", 1500.0),
    ("Jinx", "W", 1200.0),
    ("Braum", "Q", 1100.0),
])
def test_primary_missile_speed_unchanged(
    snap: DataSnapshot, champ: str, slot: str, primary: float
) -> None:
    assert snap.spell_missile_speed(champ, slot) == primary


def test_is_projectile_unchanged(snap: DataSnapshot) -> None:
    assert is_projectile(snap, "Lux", "Q") is True
    assert is_projectile(snap, "Aatrox", "E") is False


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only data_loader.py (definition) may reference spell_sub_missile_speed.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "data_loader.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "spell_sub_missile_speed" in text:
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
