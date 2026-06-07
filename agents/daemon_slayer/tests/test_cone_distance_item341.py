"""cone reach / LENGTH accessor - schema lift item 341 (2026-06-07).

A NEW forward-marker accessor ``spell_cone_distance`` exposing the CDragon
``cone_distance`` geometry datum as a first-class comparable MAGNITUDE - the
reach / LENGTH (units) a cone spell projects from the caster.  This is a DISTINCT
axis from the item-340 ``spell_cone_angle`` (the angular SPREAD in degrees): a
spell can carry a real cone reach with NO angle (Braum E Unbreakable, reach 700,
angle None) - the two together describe the cone footprint (a long narrow cone
vs a short wide cone).  The reach was structurally inexpressible: ``geometry.py``
reads ``cone_distance`` ONLY as a non-null presence flag (the cone -> shape
classifier, line 89 ``geometry.get("cone_distance") is not None``) and
``missile._distance_from_geometry`` reads it ONLY as a travel-distance input that
it immediately folds into ``dist / speed`` to produce a travel TIME - the raw
length was never surfaced as a queryable magnitude.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/cdragon_spell_stats.json``
via ``DataSnapshot.load().spell_geometry`` (ground-truth probed 2026-06-07; the
``cone_distance`` field distributes as 23 real lengths / 45 at the 0.0 sentinel /
487 at the 100.0 sentinel / 128 absent):

* Annie W (Incinerate)            cone_distance=600.0
* Ashe W (Volley)                 cone_distance=1200.0  (long)
* Cassiopeia R (Petrifying Gaze)  cone_distance=825.0
* Chogath W (Feral Scream)        cone_distance=585.0
* Corki E (Gatling Gun)           cone_distance=725.0
* Darius E (Apprehend)            cone_distance=550.0
* Braum E (Unbreakable)           cone_distance=700.0  (reach but NO angle)

None / sentinel cases:
* Lux Q (line skillshot, cone_distance=100.0 sentinel)  -> None
* Caitlyn R (cone_distance=100.0 sentinel)              -> None
* AurelionSol Q (cone_distance=0.0 sentinel)            -> None
* Aatrox Q (no geometry block at all)                  -> None

DUAL-SENTINEL guard (the key difference from item-340 cone_angle, whose guard is
``<= 0`` only): ``cone_distance`` carries TWO CDragon placeholder values that are
NOT real lengths - 0.0 (45 spells) and 100.0 (487 spells, the extractor
210 / 100 conflation).  Both reject to None, mirroring the existing
``missile._CONE_DISTANCE_SENTINELS = frozenset({0.0, 100.0})`` constant.

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes ``spell_cone_distance``
at ship - it mirrors how the item-340 cone-angle / item-232 geometry accessors
were exposed (snapshot-accessor idiom, reading the already-loaded sidecar; no
data duplication, patch-refresh-safe) and the item-336 / 337 / 338 / 339 / 340
forward-marker contract (no consumer -> byte-identical -> ENGINE_VERSION does NOT
bump).  ``classify_spell_shape`` / ``spell_aoe_multiplier`` / ``spell_cone_angle``
and every serialized surface are untouched, so live DS output is byte-identical.
In particular AurelionSol Q (cone_distance=0.0) still classifies as ``"cone"``
(classify is presence-blind to magnitude) while the accessor returns None - the
lift exposes the magnitude WITHOUT perturbing classification.

Coverage classes:
* ``ConeDistanceValuePinsTests`` - exact length per seed from 16.11.1.
* ``ConeDistanceShapeTests`` - the accessor returns a float for a seeded cone.
* ``ConeDistanceDistinctAxisTests`` - Braum E carries a reach but NO cone_angle,
  proving cone_distance is a separate axis from the item-340 angle.
* ``ConeDistanceAbsentTests`` - None for a line spell (Lux Q, 100.0 sentinel),
  a no-geometry spell (Aatrox Q), the 0.0 sentinel (AurelionSol Q), the 100.0
  sentinel (Caitlyn R), and unknown champ / slot.
* ``ConeDistanceHygieneTests`` - non-positive / sentinel / non-numeric / bool /
  empty-geometry / absent-sidecar lengths fall to None (byte-identical fallback)
  via stubs; numeric strings coerce (float idiom) but a "100" string still
  rejects as the sentinel.
* ``ByteIdenticalTests`` - ``classify_spell_shape`` / ``spell_aoe_multiplier`` /
  ``spell_cone_angle`` are UNCHANGED for the seeds (the reach lift touched none).
* ``ForwardMarkerNoConsumerTests`` - no production module other than the
  definition (``geometry.py``) references ``spell_cone_distance`` - a pure
  forward-marker.
* ``EngineVersionUnchangedTests`` - ENGINE_VERSION stays >= 1.120.0
  (byte-identical, no bump).
* ``AsciiHygieneTests`` - the new accessor block + this test file are pure-ASCII
  (no em/en-dash, no smart quotes per CLAUDE.md hard rule).
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
    spell_cone_distance,
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
    ("Annie", "W"): 600.0,
    ("Ashe", "W"): 1200.0,
    ("Cassiopeia", "R"): 825.0,
    ("Chogath", "W"): 585.0,
    ("Corki", "E"): 725.0,
    ("Darius", "E"): 550.0,
    ("Braum", "E"): 700.0,
}


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot", "distance"), [
    ("Annie", "W", 600.0),
    ("Ashe", "W", 1200.0),
    ("Cassiopeia", "R", 825.0),
    ("Chogath", "W", 585.0),
    ("Corki", "E", 725.0),
    ("Darius", "E", 550.0),
    ("Braum", "E", 700.0),
])
def test_seed_distance(
    snap: DataSnapshot, champ: str, slot: str, distance: float
) -> None:
    assert spell_cone_distance(snap, champ, slot) == distance


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_returns_float_for_cone_spell(snap: DataSnapshot) -> None:
    d = spell_cone_distance(snap, "Annie", "W")
    assert isinstance(d, float)
    assert d > 0.0


def test_all_seeds_present_and_positive(snap: DataSnapshot) -> None:
    for (champ, slot), expected in _SEEDS.items():
        got = spell_cone_distance(snap, champ, slot)
        assert got == expected, f"{champ} {slot}: {got!r} != {expected!r}"
        assert isinstance(got, float)
        assert got > 0.0


# ---------------------------------------------------------------------------
# distinct axis: reach is separate from the item-340 angle
# ---------------------------------------------------------------------------


def test_braum_e_reach_without_angle(snap: DataSnapshot) -> None:
    # Braum E carries a real cone reach (700) but NO cone_angle - proving the
    # length is a distinct axis from the item-340 angular spread.
    assert spell_cone_distance(snap, "Braum", "E") == 700.0
    assert spell_cone_angle(snap, "Braum", "E") is None


def test_seeds_with_both_axes(snap: DataSnapshot) -> None:
    # Annie W carries BOTH a reach and an angle - the two coexist independently.
    assert spell_cone_distance(snap, "Annie", "W") == 600.0
    assert spell_cone_angle(snap, "Annie", "W") == 24.76


# ---------------------------------------------------------------------------
# absent / None / sentinel cases
# ---------------------------------------------------------------------------


def test_none_for_line_spell_sentinel(snap: DataSnapshot) -> None:
    # Lux Q: line skillshot, cone_distance is the 100.0 sentinel.
    assert (snap.spell_geometry("Lux", "Q") or {}).get("cone_distance") == 100.0
    assert spell_cone_distance(snap, "Lux", "Q") is None


def test_none_for_caitlyn_r_sentinel(snap: DataSnapshot) -> None:
    # Caitlyn R: cone_distance=100.0 sentinel -> None.
    assert (snap.spell_geometry("Caitlyn", "R") or {}).get("cone_distance") == 100.0
    assert spell_cone_distance(snap, "Caitlyn", "R") is None


def test_none_for_zero_sentinel(snap: DataSnapshot) -> None:
    # AurelionSol Q: cone_distance=0.0 sentinel -> None via the sentinel guard.
    assert (snap.spell_geometry("AurelionSol", "Q") or {}).get("cone_distance") == 0.0
    assert spell_cone_distance(snap, "AurelionSol", "Q") is None


def test_none_for_no_geometry_block(snap: DataSnapshot) -> None:
    # Aatrox Q: no geometry block at all.
    assert snap.spell_geometry("Aatrox", "Q") is None
    assert spell_cone_distance(snap, "Aatrox", "Q") is None


def test_none_for_unknown_champ(snap: DataSnapshot) -> None:
    assert spell_cone_distance(snap, "NotAChampion", "Q") is None


def test_none_for_unknown_slot(snap: DataSnapshot) -> None:
    assert spell_cone_distance(snap, "Annie", "Z") is None


# ---------------------------------------------------------------------------
# hygiene / fallback (stubs)
# ---------------------------------------------------------------------------


def test_none_geometry_stub() -> None:
    assert spell_cone_distance(_StubSnapshot(None), "X", "W") is None


def test_empty_geometry_stub() -> None:
    assert spell_cone_distance(_StubSnapshot({}), "X", "W") is None


def test_cone_distance_none_stub() -> None:
    assert spell_cone_distance(_StubSnapshot({"cone_distance": None}), "X", "W") is None


def test_cone_distance_zero_sentinel_rejected_stub() -> None:
    assert spell_cone_distance(_StubSnapshot({"cone_distance": 0.0}), "X", "W") is None


def test_cone_distance_hundred_sentinel_rejected_stub() -> None:
    assert spell_cone_distance(_StubSnapshot({"cone_distance": 100.0}), "X", "W") is None


def test_cone_distance_negative_rejected_stub() -> None:
    assert spell_cone_distance(_StubSnapshot({"cone_distance": -5.0}), "X", "W") is None


def test_cone_distance_bool_rejected_stub() -> None:
    # bool is an int subclass; float(True) == 1.0 would slip past a bare float()
    # guard, so it is rejected explicitly (matches the item-339 sub-speed guard).
    assert spell_cone_distance(_StubSnapshot({"cone_distance": True}), "X", "W") is None


def test_cone_distance_non_numeric_rejected_stub() -> None:
    assert spell_cone_distance(_StubSnapshot({"cone_distance": "far"}), "X", "W") is None


def test_cone_distance_numeric_string_coerced_stub() -> None:
    # float("600") works -> coerced to 600.0 (defensive parse, mirrors cone_angle).
    assert spell_cone_distance(_StubSnapshot({"cone_distance": "600"}), "X", "W") == 600.0


def test_cone_distance_numeric_string_sentinel_rejected_stub() -> None:
    # float("100") == 100.0 -> still rejected as the sentinel after coercion.
    assert spell_cone_distance(_StubSnapshot({"cone_distance": "100"}), "X", "W") is None


# ---------------------------------------------------------------------------
# byte-identical: shape classification / aoe multiplier / cone angle untouched
# ---------------------------------------------------------------------------


def test_classify_unchanged_cone_seed(snap: DataSnapshot) -> None:
    assert classify_spell_shape(snap.spell_geometry("Annie", "W")) == "cone"
    assert classify_spell_shape(snap.spell_geometry("Braum", "E")) == "cone"


def test_classify_unchanged_line(snap: DataSnapshot) -> None:
    # Lux Q stays a line - the cone-reach lift never touches line classification.
    assert classify_spell_shape(snap.spell_geometry("Lux", "Q")) == "line"


def test_classify_zero_sentinel_still_cone(snap: DataSnapshot) -> None:
    # AurelionSol Q cone_distance=0.0: classify is presence-blind (0.0 is not
    # None) so it stays "cone" while the accessor returns None - the lift exposes
    # the magnitude WITHOUT perturbing classification.
    assert classify_spell_shape(snap.spell_geometry("AurelionSol", "Q")) == "cone"
    assert spell_cone_distance(snap, "AurelionSol", "Q") is None


def test_aoe_multiplier_unchanged_cone_seed(snap: DataSnapshot) -> None:
    # spell_aoe_multiplier is fail-soft >= 1.0 and ignores cone_distance magnitude.
    m = spell_aoe_multiplier(snap, "Annie", "W", 3)
    assert isinstance(m, float)
    assert m >= 1.0


def test_cone_angle_unchanged_for_seeds(snap: DataSnapshot) -> None:
    # The item-340 sibling accessor is untouched by the reach lift.
    assert spell_cone_angle(snap, "Ashe", "W") == 20.0
    assert spell_cone_angle(snap, "Cassiopeia", "R") == 40.0


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only geometry.py (definition) may reference spell_cone_distance.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "geometry.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "spell_cone_distance" in text:
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
