"""circle cast RADIUS accessor - schema lift item 342 (2026-06-07).

A NEW forward-marker accessor ``spell_cast_radius`` exposing the CDragon
``cast_radius`` geometry datum as a first-class comparable MAGNITUDE - the
RADIUS (units) of a circular / point-blank AoE spell.  This is the LAST unlifted
geometry magnitude in ``cdragon_spell_stats.json`` (``line_width`` shipped item
338, ``cone_angle`` item 340, ``cone_distance`` item 341).  The radius was
structurally inexpressible as a queryable magnitude: ``classify_spell_shape``
reads ``cast_radius`` ONLY as the "circle" presence flag (geometry.py line 102,
``cast_radius is not None AND NOT conflated AND not a sentinel``) and
``missile._distance_from_geometry`` reads it ONLY as a travel-distance input that
it folds into ``dist / speed`` to produce a travel TIME - the raw radius itself
was never surfaced.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/cdragon_spell_stats.json``
via ``DataSnapshot.load().spell_geometry`` (ground-truth probed 2026-06-07; the
``cast_radius`` field distributes as 331 real radii / 192 conflated-flag
(123 at 210.0 + 69 at 100.0) / 0 non-conflated sentinels / 96 null / 64 with no
geometry block at all):

* Aurora R (The Weight of Worlds) cast_radius=750.0  (circle)
* Fiora Q (Lunge)                 cast_radius=360.0  (circle)
* Gangplank E (Powder Keg)        cast_radius=325.0  (circle)
* Gwen W (Hallowed Mist)          cast_radius=500.0  (circle)
* Neeko Q (Blooming Burst)        cast_radius=250.0  (circle)
* Seraphine Q (High Note)         cast_radius=350.0  (circle)
* Swain R (Demonic Ascension)     cast_radius=600.0  (circle)
* Viego R (Heartbreaker)          cast_radius=300.0  (circle)

None / conflated cases:
* Ahri E (Charm, cast_radius=210.0 conflated=True) -> None  (classifies "line")
* Alistar W (cast_radius=100.0 conflated=True)     -> None  (classifies "cone")
* AurelionSol Q (cast_radius=None)                 -> None
* Aatrox Q (no geometry block at all)              -> None

TRIPLE guard (the key difference from item-341 cone_distance, whose guard is the
dual sentinel only, and item-340 cone_angle, whose guard is ``<= 0`` only):
``cast_radius`` rejects to None via (a) the purpose-built
``cast_radius_conflated`` BOOL FLAG - the LIVE discriminator (192 conflated
spells at 16.11.1 carry the flag), (b) the existing module-scope
``_CONFLATED_RADIUS_SENTINELS = frozenset({210.0, 100.0})`` set (belt-and-suspenders;
0 non-conflated sentinels live, but a defensive guard), and (c) the
``<= 0`` / bool / non-numeric guard.  The flag is PRIMARY because CDragon stores a
conflated radius WITH the flag set (not as a bare sentinel), so unlike
cone_distance the sentinel set alone is insufficient - a conflated flag rejects
even a real-looking magnitude (a 250.0 with conflated=True is still None).

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes ``spell_cast_radius``
at ship - it reuses the snapshot-accessor idiom of the item-232 / 340 / 341
geometry accessors (reads the already-loaded sidecar, no data duplication,
patch-refresh-safe) and the item-336 / 337 / 338 / 339 / 340 / 341 forward-marker
contract (no consumer -> byte-identical -> ENGINE_VERSION does NOT bump).
``classify_spell_shape`` / ``spell_aoe_multiplier`` / ``spell_cone_angle`` /
``spell_cone_distance`` and every serialized surface are untouched, so live DS
output is byte-identical.  A conflated radius (Alistar W=100.0) still classifies
exactly as before while the accessor returns None - the lift exposes the
magnitude WITHOUT perturbing classification.

Coverage classes:
* ``CastRadiusValuePinsTests`` - exact radius per seed from 16.11.1.
* ``CastRadiusShapeTests`` - the accessor returns a float for a seeded circle.
* ``CastRadiusCircleClassifyTests`` - the seeds classify "circle" (the accessor
  reads the same datum the circle classifier gates on).
* ``CastRadiusConflatedTests`` - the conflated flag rejects to None live + via
  stub even for a non-sentinel real-looking value (the flag is the discriminator).
* ``CastRadiusAbsentTests`` - None for a null cast_radius (AurelionSol Q), a
  no-geometry spell (Aatrox Q), and unknown champ / slot.
* ``CastRadiusHygieneTests`` - non-positive / sentinel / non-numeric / bool /
  empty-geometry / absent-sidecar radii fall to None (byte-identical fallback)
  via stubs; numeric strings coerce (float idiom) but a "210" string still
  rejects as the sentinel.
* ``ByteIdenticalTests`` - ``classify_spell_shape`` / ``spell_aoe_multiplier`` /
  ``spell_cone_angle`` / ``spell_cone_distance`` are UNCHANGED for the seeds.
* ``ForwardMarkerNoConsumerTests`` - no production module other than the
  definition (``geometry.py``) references ``spell_cast_radius``.
* ``EngineVersionUnchangedTests`` - ENGINE_VERSION stays >= 1.120.0.
* ``AsciiHygieneTests`` - the new accessor block + this test file are pure-ASCII.
"""

from __future__ import annotations

import pathlib

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.geometry import (
    classify_spell_shape,
    spell_aoe_multiplier,
    spell_cast_radius,
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
    ("Aurora", "R"): 750.0,
    ("Fiora", "Q"): 360.0,
    ("Gangplank", "E"): 325.0,
    ("Gwen", "W"): 500.0,
    ("Neeko", "Q"): 250.0,
    ("Seraphine", "Q"): 350.0,
    ("Swain", "R"): 600.0,
    ("Viego", "R"): 300.0,
}


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot", "radius"), [
    ("Aurora", "R", 750.0),
    ("Fiora", "Q", 360.0),
    ("Gangplank", "E", 325.0),
    ("Gwen", "W", 500.0),
    ("Neeko", "Q", 250.0),
    ("Seraphine", "Q", 350.0),
    ("Swain", "R", 600.0),
    ("Viego", "R", 300.0),
])
def test_seed_radius(
    snap: DataSnapshot, champ: str, slot: str, radius: float
) -> None:
    assert spell_cast_radius(snap, champ, slot) == radius


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_returns_float_for_circle_spell(snap: DataSnapshot) -> None:
    r = spell_cast_radius(snap, "Aurora", "R")
    assert isinstance(r, float)
    assert r > 0.0


def test_all_seeds_present_and_positive(snap: DataSnapshot) -> None:
    for (champ, slot), expected in _SEEDS.items():
        got = spell_cast_radius(snap, champ, slot)
        assert got == expected, f"{champ} {slot}: {got!r} != {expected!r}"
        assert isinstance(got, float)
        assert got > 0.0


# ---------------------------------------------------------------------------
# circle classify path: the accessor reads the same datum the classifier gates on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "slot"), list(_SEEDS.keys()))
def test_seeds_classify_circle(snap: DataSnapshot, champ: str, slot: str) -> None:
    assert classify_spell_shape(snap.spell_geometry(champ, slot)) == "circle"


# ---------------------------------------------------------------------------
# conflated: the flag (not the sentinel set) is the live discriminator
# ---------------------------------------------------------------------------


def test_none_for_conflated_ahri_e(snap: DataSnapshot) -> None:
    # Ahri E: cast_radius=210.0 with cast_radius_conflated=True -> None.
    geo = snap.spell_geometry("Ahri", "E") or {}
    assert geo.get("cast_radius") == 210.0
    assert geo.get("cast_radius_conflated") is True
    assert spell_cast_radius(snap, "Ahri", "E") is None


def test_none_for_conflated_alistar_w(snap: DataSnapshot) -> None:
    # Alistar W: cast_radius=100.0 conflated=True -> None.
    geo = snap.spell_geometry("Alistar", "W") or {}
    assert geo.get("cast_radius") == 100.0
    assert geo.get("cast_radius_conflated") is True
    assert spell_cast_radius(snap, "Alistar", "W") is None


def test_conflated_flag_rejects_non_sentinel_value_stub() -> None:
    # The KEY novelty over item-341: a conflated flag rejects even a real-looking
    # (non-sentinel) radius - the flag, not the sentinel set, is the discriminator.
    geo = {"cast_radius": 250.0, "cast_radius_conflated": True}
    assert spell_cast_radius(_StubSnapshot(geo), "X", "W") is None


def test_non_conflated_real_value_kept_stub() -> None:
    # Same value, conflated=False -> kept (the flag is the sole difference).
    geo = {"cast_radius": 250.0, "cast_radius_conflated": False}
    assert spell_cast_radius(_StubSnapshot(geo), "X", "W") == 250.0


# ---------------------------------------------------------------------------
# absent / None cases
# ---------------------------------------------------------------------------


def test_none_for_null_cast_radius(snap: DataSnapshot) -> None:
    # AurelionSol Q: cast_radius is null -> None.
    assert (snap.spell_geometry("AurelionSol", "Q") or {}).get("cast_radius") is None
    assert spell_cast_radius(snap, "AurelionSol", "Q") is None


def test_none_for_no_geometry_block(snap: DataSnapshot) -> None:
    # Aatrox Q: no geometry block at all.
    assert snap.spell_geometry("Aatrox", "Q") is None
    assert spell_cast_radius(snap, "Aatrox", "Q") is None


def test_none_for_unknown_champ(snap: DataSnapshot) -> None:
    assert spell_cast_radius(snap, "NotAChampion", "Q") is None


def test_none_for_unknown_slot(snap: DataSnapshot) -> None:
    assert spell_cast_radius(snap, "Aurora", "Z") is None


# ---------------------------------------------------------------------------
# hygiene / fallback (stubs)
# ---------------------------------------------------------------------------


def test_none_geometry_stub() -> None:
    assert spell_cast_radius(_StubSnapshot(None), "X", "W") is None


def test_empty_geometry_stub() -> None:
    assert spell_cast_radius(_StubSnapshot({}), "X", "W") is None


def test_cast_radius_none_stub() -> None:
    assert spell_cast_radius(_StubSnapshot({"cast_radius": None}), "X", "W") is None


def test_cast_radius_210_sentinel_rejected_stub() -> None:
    # 210.0 with conflated absent (default False) still rejects via the sentinel
    # set - belt-and-suspenders (this case is count 0 live but defensive).
    assert spell_cast_radius(_StubSnapshot({"cast_radius": 210.0}), "X", "W") is None


def test_cast_radius_100_sentinel_rejected_stub() -> None:
    assert spell_cast_radius(_StubSnapshot({"cast_radius": 100.0}), "X", "W") is None


def test_cast_radius_negative_rejected_stub() -> None:
    assert spell_cast_radius(_StubSnapshot({"cast_radius": -5.0}), "X", "W") is None


def test_cast_radius_zero_rejected_stub() -> None:
    assert spell_cast_radius(_StubSnapshot({"cast_radius": 0.0}), "X", "W") is None


def test_cast_radius_bool_rejected_stub() -> None:
    # bool is an int subclass; float(True) == 1.0 would slip past a bare float()
    # guard, so it is rejected explicitly (matches the item-339 / 341 guard).
    assert spell_cast_radius(_StubSnapshot({"cast_radius": True}), "X", "W") is None


def test_cast_radius_non_numeric_rejected_stub() -> None:
    assert spell_cast_radius(_StubSnapshot({"cast_radius": "wide"}), "X", "W") is None


def test_cast_radius_numeric_string_coerced_stub() -> None:
    # float("360") works -> coerced to 360.0 (defensive parse, mirrors the family).
    assert spell_cast_radius(_StubSnapshot({"cast_radius": "360"}), "X", "W") == 360.0


def test_cast_radius_numeric_string_sentinel_rejected_stub() -> None:
    # float("210") == 210.0 -> still rejected as the sentinel after coercion.
    assert spell_cast_radius(_StubSnapshot({"cast_radius": "210"}), "X", "W") is None


# ---------------------------------------------------------------------------
# byte-identical: classify / aoe multiplier / sibling accessors untouched
# ---------------------------------------------------------------------------


def test_classify_unchanged_circle_seed(snap: DataSnapshot) -> None:
    assert classify_spell_shape(snap.spell_geometry("Gwen", "W")) == "circle"
    assert classify_spell_shape(snap.spell_geometry("Swain", "R")) == "circle"


def test_classify_unchanged_conflated(snap: DataSnapshot) -> None:
    # Conflated cast_radius classifies exactly as before (Ahri E line via
    # line_width; Alistar W cone via the cone_distance sentinel) while the
    # accessor returns None - the lift never perturbs classification.
    assert classify_spell_shape(snap.spell_geometry("Ahri", "E")) == "line"
    assert classify_spell_shape(snap.spell_geometry("Alistar", "W")) == "cone"
    assert spell_cast_radius(snap, "Ahri", "E") is None
    assert spell_cast_radius(snap, "Alistar", "W") is None


def test_aoe_multiplier_unchanged_circle_seed(snap: DataSnapshot) -> None:
    # spell_aoe_multiplier is fail-soft >= 1.0 and ignores cast_radius magnitude.
    m = spell_aoe_multiplier(snap, "Gwen", "W", 3)
    assert isinstance(m, float)
    assert m >= 1.0


def test_sibling_cone_accessors_untouched_for_circle_seed(snap: DataSnapshot) -> None:
    # A circle seed carries no real cone datum, so both cone accessors stay None.
    assert spell_cone_distance(snap, "Gwen", "W") is None
    assert spell_cone_angle(snap, "Gwen", "W") is None


def test_sibling_cone_distance_still_works(snap: DataSnapshot) -> None:
    # The item-341 sibling still returns its pinned value (cast_radius lift did
    # not break it).
    assert spell_cone_distance(snap, "Annie", "W") == 600.0
    assert spell_cone_angle(snap, "Ashe", "W") == 20.0


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only geometry.py (definition) may reference spell_cast_radius.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "geometry.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "spell_cast_radius" in text:
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
