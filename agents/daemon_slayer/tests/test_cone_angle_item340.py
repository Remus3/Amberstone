"""cone-spread ANGLE accessor - schema lift item 340 (2026-06-07).

A NEW forward-marker accessor ``spell_cone_angle`` exposing the CDragon
``cone_angle`` geometry datum as a first-class comparable MAGNITUDE - the
angular SPREAD (degrees) of a cone spell. The angle governs ease-of-landing
and overlap density (a tight 20deg Ashe Volley vs a wide 40deg Cassiopeia R
petrify) and was structurally inexpressible: ``geometry.py`` reads
``cone_angle`` ONLY as a non-null presence flag (the cone -> shape
classifier, line 90 ``geometry.get("cone_angle") is not None``) and
``missile._distance_from_geometry`` reads only ``cone_distance`` /
``cast_radius``, never the angle. No module exposed the numeric angle, so
the magnitude was discarded.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/
cdragon_spell_stats.json`` via ``DataSnapshot.load().spell_geometry``
(ground-truth probed 2026-06-07; 66 spells carry a numeric cone_angle,
24 with a real >0 angle, the other 42 are 0.0 sentinels):

* Annie W (Incinerate)        cone_angle=24.76
* Ashe W (Volley)             cone_angle=20.0  (tight)
* Cassiopeia R (Petrifying Gaze) cone_angle=40.0  (wide)
* Chogath W (Feral Scream)    cone_angle=28.0
* Corki E (Gatling Gun)       cone_angle=28.0
* Darius E (Apprehend)        cone_angle=25.0

None / sentinel cases:
* Lux Q (line skillshot, cone_angle=None)        -> None
* Aatrox Q (no geometry block at all)            -> None
* AurelionSol Q (cone_angle=0.0 sentinel)        -> None (<=0 guard)

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes
``spell_cone_angle`` at ship - it mirrors how the item-338
``spell_missile_width`` / item-232 geometry accessors were exposed
(snapshot-accessor idiom, reading the already-loaded sidecar; no data
duplication, patch-refresh-safe) and the item-336 / 337 / 338 / 339
forward-marker contract (no consumer -> byte-identical -> ENGINE_VERSION
does NOT bump). ``classify_spell_shape`` / ``spell_aoe_multiplier`` and
every serialized surface are untouched, so live DS output is byte-identical.
In particular AurelionSol Q (cone_angle=0.0) still classifies as ``"cone"``
(classify is presence-blind to magnitude) while the accessor returns None -
the lift exposes the magnitude WITHOUT perturbing classification.

Coverage classes:
* ``ConeAngleValuePinsTests`` - exact angle per seed from 16.11.1.
* ``ConeAngleShapeTests`` - the accessor returns a float for a seeded cone.
* ``ConeAngleAbsentTests`` - None for a geometry-present-no-cone spell
  (Lux Q line), a no-geometry spell (Aatrox Q), the 0.0 sentinel
  (AurelionSol Q), and unknown champ / slot.
* ``ConeAngleHygieneTests`` - non-positive / non-numeric / empty-geometry
  / absent-sidecar angles fall to None (byte-identical fallback) via stubs.
* ``ByteIdenticalClassifyTests`` - ``classify_spell_shape`` /
  ``spell_aoe_multiplier`` are UNCHANGED for the seeds (the angle lift did
  not touch shape classification).
* ``ForwardMarkerNoConsumerTests`` - no production module other than the
  definition (``geometry.py``) references ``spell_cone_angle`` - a pure
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
from agents.daemon_slayer.geometry import (
    classify_spell_shape,
    spell_aoe_multiplier,
    spell_cone_angle,
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
    ("Annie", "W"): 24.76,
    ("Ashe", "W"): 20.0,
    ("Cassiopeia", "R"): 40.0,
    ("Chogath", "W"): 28.0,
    ("Corki", "E"): 28.0,
    ("Darius", "E"): 25.0,
}


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot", "angle"), [
    ("Annie", "W", 24.76),
    ("Ashe", "W", 20.0),
    ("Cassiopeia", "R", 40.0),
    ("Chogath", "W", 28.0),
    ("Corki", "E", 28.0),
    ("Darius", "E", 25.0),
])
def test_seed_angle(
    snap: DataSnapshot, champ: str, slot: str, angle: float
) -> None:
    assert spell_cone_angle(snap, champ, slot) == angle


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_returns_float_for_cone_spell(snap: DataSnapshot) -> None:
    a = spell_cone_angle(snap, "Annie", "W")
    assert isinstance(a, float)
    assert a > 0.0


def test_all_seeds_present_and_positive(snap: DataSnapshot) -> None:
    for (champ, slot), expected in _SEEDS.items():
        got = spell_cone_angle(snap, champ, slot)
        assert got == expected, f"{champ} {slot}: {got!r} != {expected!r}"
        assert isinstance(got, float)


# ---------------------------------------------------------------------------
# absent / None / sentinel cases
# ---------------------------------------------------------------------------


def test_none_for_geometry_present_no_cone_angle(snap: DataSnapshot) -> None:
    # Lux Q: geometry present (line) but cone_angle is None.
    assert (snap.spell_geometry("Lux", "Q") or {}).get("cone_angle") is None
    assert spell_cone_angle(snap, "Lux", "Q") is None


def test_none_for_no_geometry_block(snap: DataSnapshot) -> None:
    # Aatrox Q: no geometry block at all.
    assert snap.spell_geometry("Aatrox", "Q") is None
    assert spell_cone_angle(snap, "Aatrox", "Q") is None


def test_none_for_zero_sentinel(snap: DataSnapshot) -> None:
    # AurelionSol Q: cone_angle=0.0 sentinel -> None via the <=0 guard.
    assert (snap.spell_geometry("AurelionSol", "Q") or {}).get("cone_angle") == 0.0
    assert spell_cone_angle(snap, "AurelionSol", "Q") is None


def test_none_for_unknown_champ(snap: DataSnapshot) -> None:
    assert spell_cone_angle(snap, "NotAChampion", "Q") is None


def test_none_for_unknown_slot(snap: DataSnapshot) -> None:
    assert spell_cone_angle(snap, "Annie", "Z") is None


# ---------------------------------------------------------------------------
# hygiene / fallback (stubs)
# ---------------------------------------------------------------------------


def test_none_geometry_stub() -> None:
    assert spell_cone_angle(_StubSnapshot(None), "X", "W") is None


def test_empty_geometry_stub() -> None:
    assert spell_cone_angle(_StubSnapshot({}), "X", "W") is None


def test_cone_angle_none_stub() -> None:
    assert spell_cone_angle(_StubSnapshot({"cone_angle": None}), "X", "W") is None


def test_cone_angle_zero_rejected_stub() -> None:
    assert spell_cone_angle(_StubSnapshot({"cone_angle": 0.0}), "X", "W") is None


def test_cone_angle_negative_rejected_stub() -> None:
    assert spell_cone_angle(_StubSnapshot({"cone_angle": -5.0}), "X", "W") is None


def test_cone_angle_non_numeric_rejected_stub() -> None:
    assert spell_cone_angle(_StubSnapshot({"cone_angle": "wide"}), "X", "W") is None


def test_cone_angle_numeric_string_coerced_stub() -> None:
    # float("20") works -> coerced to 20.0 (defensive parse, mirrors missile.py).
    assert spell_cone_angle(_StubSnapshot({"cone_angle": "20"}), "X", "W") == 20.0


# ---------------------------------------------------------------------------
# byte-identical: shape classification / aoe multiplier untouched
# ---------------------------------------------------------------------------


def test_classify_unchanged_cone_seed(snap: DataSnapshot) -> None:
    assert classify_spell_shape(snap.spell_geometry("Annie", "W")) == "cone"
    assert classify_spell_shape(snap.spell_geometry("Cassiopeia", "R")) == "cone"


def test_classify_unchanged_line(snap: DataSnapshot) -> None:
    # Lux Q stays a line - the cone-angle lift never touches line classification.
    assert classify_spell_shape(snap.spell_geometry("Lux", "Q")) == "line"


def test_classify_zero_sentinel_still_cone(snap: DataSnapshot) -> None:
    # AurelionSol Q cone_angle=0.0: classify is presence-blind (0.0 is not None)
    # so it stays "cone" while the accessor returns None - the lift exposes the
    # magnitude WITHOUT perturbing classification.
    assert classify_spell_shape(snap.spell_geometry("AurelionSol", "Q")) == "cone"
    assert spell_cone_angle(snap, "AurelionSol", "Q") is None


def test_aoe_multiplier_unchanged_cone_seed(snap: DataSnapshot) -> None:
    # spell_aoe_multiplier is fail-soft >= 1.0 and ignores cone_angle magnitude.
    m = spell_aoe_multiplier(snap, "Annie", "W", 3)
    assert isinstance(m, float)
    assert m >= 1.0


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only geometry.py (definition) may reference spell_cone_angle.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "geometry.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "spell_cone_angle" in text:
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


def test_geometry_module_pure_ascii() -> None:
    src = (
        pathlib.Path(__file__).resolve().parent.parent / "geometry.py"
    ).read_text(encoding="utf-8")
    bad = [c for c in src if ord(c) > 127]
    assert bad == [], f"non-ASCII chars in geometry.py: {bad!r}"


def test_this_test_file_pure_ascii() -> None:
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    bad = [c for c in src if ord(c) > 127]
    assert bad == [], f"non-ASCII chars in test file: {bad!r}"
