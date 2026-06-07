"""skillshot missile-WIDTH accessor - schema lift item 338 (2026-06-07).

A NEW forward-marker accessor ``spell_missile_width`` exposing the CDragon
``line_width`` geometry datum as a first-class comparable MAGNITUDE - the
perpendicular HITBOX WIDTH (game units) of a line skillshot. The width
dimension governs ease-of-landing (a narrow 40u Nidalee spear vs a wide 100u
Xerath bolt) and was structurally inexpressible: ``geometry.py`` reads
``line_width`` ONLY as a non-null presence flag (line -> shape classifier,
line 84) and ``missile._distance_from_geometry`` explicitly REJECTS it
("a perpendicular width, not a travel length, so it is never used here").
No module exposed the numeric width, so the magnitude was discarded.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/
cdragon_spell_stats.json`` via ``DataSnapshot.load().spell_geometry``
(ground-truth probed 2026-06-07; 243 spells carry a numeric line_width,
30 distinct values):

* Blitzcrank Q (Rocket Grab) line_width=70.0
* Lux Q (Light Binding)      line_width=80.0
* Lux W (Prismatic Barrier)  line_width=150.0
* Aatrox W (Infernal Chains) line_width=80.0
* Morgana Q (Dark Binding)   line_width=70.0
* Nidalee Q (Javelin Toss)   line_width=40.0  (narrow)
* Xerath Q (Arcanopulse)     line_width=100.0 (wide)

None cases (not a line skillshot):
* Lux E (geometry present, line_width=None - cone/circle) -> None
* Aatrox Q (no geometry block at all)                     -> None

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes
``spell_missile_width`` at ship - it mirrors how the item-233
``spell_travel_time`` / item-232 geometry accessors were exposed
(snapshot-accessor idiom, reading the already-loaded sidecar; no data
duplication, patch-refresh-safe) and the item-336 / item-337 forward-marker
contract (no consumer -> byte-identical -> ENGINE_VERSION does NOT bump).
``is_projectile`` / ``spell_travel_time`` / ``_distance_from_geometry`` and
every serialized surface are untouched, so live DS output is byte-identical.

Coverage classes:
* ``MissileWidthValuePinsTests`` - exact width per seed from 16.11.1.
* ``MissileWidthShapeTests`` - the accessor returns a float for a seeded
  line skillshot.
* ``MissileWidthAbsentTests`` - None for a geometry-present-no-line spell
  (Lux E), a no-geometry spell (Aatrox Q), and unknown champ / slot.
* ``MissileWidthHygieneTests`` - non-positive / non-numeric / empty-geometry
  / absent-sidecar widths fall to None (byte-identical fallback) via stubs.
* ``ByteIdenticalTravelTimeTests`` - ``is_projectile`` / ``spell_travel_time``
  are UNCHANGED for the seeds (the width lift did not touch travel-time).
* ``ForwardMarkerNoConsumerTests`` - no production module other than the
  definition (``missile.py``) references ``spell_missile_width`` - a pure
  forward-marker.
* ``EngineVersionUnchangedTests`` - ENGINE_VERSION stays >= 1.120.0
  (byte-identical, no bump).
* ``AsciiHygieneTests`` - the new accessor block + this test file are
  pure-ASCII (no em/en-dash, no smart quotes per CLAUDE.md hard rule).
"""

from __future__ import annotations

import pathlib

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.missile import (
    is_projectile,
    spell_missile_width,
    spell_travel_time,
)


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


# ---------------- stubs (hygiene / fallback paths) ----------------


class _StubSnapshot:
    """Minimal snapshot exposing only ``spell_geometry`` (the sole call)."""

    def __init__(self, geometry: "dict | None") -> None:
        self._geometry = geometry

    def spell_geometry(self, champ_id: str, slot: str) -> "dict | None":
        return self._geometry


# ---------------- expected seed set ----------------

_SEEDS: dict[tuple[str, str], float] = {
    ("Blitzcrank", "Q"): 70.0,
    ("Lux", "Q"): 80.0,
    ("Lux", "W"): 150.0,
    ("Aatrox", "W"): 80.0,
    ("Morgana", "Q"): 70.0,
    ("Nidalee", "Q"): 40.0,
    ("Xerath", "Q"): 100.0,
}


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot", "width"), [
    ("Blitzcrank", "Q", 70.0),
    ("Lux", "Q", 80.0),
    ("Lux", "W", 150.0),
    ("Aatrox", "W", 80.0),
    ("Morgana", "Q", 70.0),
    ("Nidalee", "Q", 40.0),
    ("Xerath", "Q", 100.0),
])
def test_seed_width(
    snap: DataSnapshot, champ: str, slot: str, width: float
) -> None:
    assert spell_missile_width(snap, champ, slot) == width


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_returns_float_for_line_skillshot(snap: DataSnapshot) -> None:
    w = spell_missile_width(snap, "Lux", "Q")
    assert isinstance(w, float)
    assert w > 0.0


def test_all_seeds_present_and_positive(snap: DataSnapshot) -> None:
    for (champ, slot), expected in _SEEDS.items():
        got = spell_missile_width(snap, champ, slot)
        assert got == expected, f"{champ} {slot}: {got!r} != {expected!r}"
        assert isinstance(got, float)


# ---------------------------------------------------------------------------
# absent / None cases
# ---------------------------------------------------------------------------


def test_none_for_geometry_present_no_line_width(snap: DataSnapshot) -> None:
    # Lux E: geometry present (cone/circle) but line_width is None.
    assert (snap.spell_geometry("Lux", "E") or {}).get("line_width") is None
    assert spell_missile_width(snap, "Lux", "E") is None


def test_none_for_no_geometry_block(snap: DataSnapshot) -> None:
    # Aatrox Q: no geometry block at all.
    assert snap.spell_geometry("Aatrox", "Q") is None
    assert spell_missile_width(snap, "Aatrox", "Q") is None


def test_none_for_unknown_champ(snap: DataSnapshot) -> None:
    assert spell_missile_width(snap, "NotAChampion", "Q") is None


def test_none_for_unknown_slot(snap: DataSnapshot) -> None:
    assert spell_missile_width(snap, "Lux", "Z") is None


# ---------------------------------------------------------------------------
# hygiene / fallback (stubs)
# ---------------------------------------------------------------------------


def test_none_geometry_stub() -> None:
    assert spell_missile_width(_StubSnapshot(None), "X", "Q") is None


def test_empty_geometry_stub() -> None:
    assert spell_missile_width(_StubSnapshot({}), "X", "Q") is None


def test_line_width_none_stub() -> None:
    assert spell_missile_width(_StubSnapshot({"line_width": None}), "X", "Q") is None


def test_line_width_zero_rejected_stub() -> None:
    assert spell_missile_width(_StubSnapshot({"line_width": 0.0}), "X", "Q") is None


def test_line_width_negative_rejected_stub() -> None:
    assert spell_missile_width(_StubSnapshot({"line_width": -5.0}), "X", "Q") is None


def test_line_width_non_numeric_rejected_stub() -> None:
    assert spell_missile_width(_StubSnapshot({"line_width": "wide"}), "X", "Q") is None


def test_line_width_numeric_string_coerced_stub() -> None:
    # float("70") works -> coerced to 70.0 (defensive parse, mirrors missile.py).
    assert spell_missile_width(_StubSnapshot({"line_width": "70"}), "X", "Q") == 70.0


# ---------------------------------------------------------------------------
# byte-identical: travel-time / projectile classification untouched
# ---------------------------------------------------------------------------


def test_is_projectile_unchanged(snap: DataSnapshot) -> None:
    assert is_projectile(snap, "Lux", "Q") is True
    assert is_projectile(snap, "Morgana", "Q") is True
    assert is_projectile(snap, "Aatrox", "E") is False


def test_travel_time_unchanged_lux_q(snap: DataSnapshot) -> None:
    # Lux Q speed=1200; explicit distance keeps the assertion data-stable.
    assert spell_travel_time(snap, "Lux", "Q", distance=1200.0) == 1.0


def test_travel_time_none_for_non_projectile(snap: DataSnapshot) -> None:
    # Aatrox E missile_speed=20 < 400 -> not a projectile.
    assert spell_travel_time(snap, "Aatrox", "E") is None


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only missile.py (definition) may reference spell_missile_width.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "missile.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "spell_missile_width" in text:
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


def test_missile_module_pure_ascii() -> None:
    src = (
        pathlib.Path(__file__).resolve().parent.parent / "missile.py"
    ).read_text(encoding="utf-8")
    bad = [c for c in src if ord(c) > 127]
    assert bad == [], f"non-ASCII chars in missile.py: {bad!r}"


def test_this_test_file_pure_ascii() -> None:
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    bad = [c for c in src if ord(c) > 127]
    assert bad == [], f"non-ASCII chars in test file: {bad!r}"
