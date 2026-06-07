"""auto-attack missile-speed accessor - schema lift item 344 (2026-06-07).

A NEW forward-marker accessor ``DataSnapshot.aa_missile_speed`` exposing the
wiki_stats per-champion ``missile_speed`` datum as a first-class comparable
MAGNITUDE - the projectile travel speed (units/s) of a champion's BASIC ATTACK.
This is a DISTINCT axis from the per-SPELL cdragon missiles already lifted
(item 233 ``spell_missile_speed`` / item 339 ``spell_sub_missile_speed`` are
spell-slot keyed off ``cdragon_spell_stats``); the AA missile speed is
CHAMP-keyed off ``wiki_stats`` and governs ranged auto-attack hit-delay /
kiting windows. It was loaded into ``DataSnapshot.wiki_stats`` alongside
``attack_cast_time`` (item 221) + ``mode_modifiers`` (item 232) but no accessor
ever surfaced it: the only ``wiki_stats.get`` reads are ``wiki_attack_cast_time``
(the AA windup) and ``mode_modifier`` (per-mode balance axes).

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/wiki_stats.json`` via
``DataSnapshot.load()`` (ground-truth probed 2026-06-07; 82 champs carry a
numeric ``missile_speed``, of which 77 are positive - 76 in the real
400-4999 projectile band and 1 in the >=5000 instant band - while 5 are the
0.0 no-projectile sentinel and 89 are null / absent melee champs):

* Caitlyn AA   missile_speed=2500.0
* Jinx AA      missile_speed=2750.0
* Jhin AA      missile_speed=2600.0
* Ashe AA      missile_speed=2500.0
* Vayne AA     missile_speed=2000.0
* Lux AA       missile_speed=1600.0
* Kayle AA     missile_speed=5000.0  (instant / global band, still returned)

None / sentinel cases:
* Azir / Senna / Thresh / Velkoz / Zeri  missile_speed=0.0 sentinel -> None
* Garen / Darius (melee, null missile_speed)             -> None
* unknown champ                                          -> None

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes ``aa_missile_speed``
at ship - it mirrors the item-233 ``spell_missile_speed`` / item-221
``wiki_attack_cast_time`` sibling accessors (snapshot-method idiom reading the
already-loaded sidecar; no data duplication, patch-refresh-safe) and the
item-336 / 337 / 338 / 339 / 340 / 341 / 342 / 343 forward-marker contract
(no consumer -> byte-identical -> ENGINE_VERSION does NOT bump). The
``wiki_attack_cast_time`` / ``mode_modifier`` siblings and every serialized
surface are untouched, so live DS output is byte-identical.

Guard delta from ``spell_missile_speed``: both reject bool / non-numeric and do
NOT coerce a numeric STRING (returns None), but ``aa_missile_speed`` ADDS a
``<= 0`` guard so the 0.0 no-projectile sentinel (Azir / Senna / Thresh /
Velkoz / Zeri - non-standard or no-projectile auto-attacks) returns None rather
than a nonsensical zero-speed projectile. This mirrors the geometry accessors'
``<= 0`` magnitude guard (item 340 ``spell_cone_angle``).

Coverage classes:
* value pins - exact AA speed per seed from 16.11.1.
* shape - the accessor returns a positive float for a seeded ranged champ.
* distinct-axis - the AA speed is read from wiki_stats (champ-keyed), not the
  per-spell cdragon sidecar (the item-233 primary).
* sentinel / absent - None for the 0.0 sentinel champs, melee null champs, and
  unknown champ.
* instant band - the >=5000 instant value (Kayle) is positive so it is returned
  (the forward-marker does not gate bands; that is a future consumer's job).
* hygiene / fallback - absent-sidecar / missing-key / None / bool / non-numeric
  / numeric-string fall to None; int / float coerce to float; 0.0 / negative
  reject to None (the AA-specific ``<= 0`` guard).
* byte-identical - ``wiki_attack_cast_time`` is UNCHANGED for the seeds (the AA
  missile-speed lift touched neither it nor ``mode_modifier``).
* forward-marker - no production module other than the definition
  (``data_loader.py``) references ``aa_missile_speed``.
* engine version - ENGINE_VERSION stays >= 1.120.0 (byte-identical, no bump).
* ASCII hygiene - the new accessor block + this test file are pure-ASCII.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


# ---------------- stub (hygiene / fallback paths) ----------------


def _stub(snap: DataSnapshot, ws: dict) -> DataSnapshot:
    """A DataSnapshot copy carrying only a crafted wiki_stats.

    aa_missile_speed touches ONLY self.wiki_stats, so reusing the loaded
    snapshot's other fields and swapping the sidecar dict exercises the guard
    without rebuilding the full constructor.
    """
    return dataclasses.replace(snap, wiki_stats=ws)


# ---------------- expected seed set ----------------

_SEEDS: dict[str, float] = {
    "Caitlyn": 2500.0,
    "Jinx": 2750.0,
    "Jhin": 2600.0,
    "Ashe": 2500.0,
    "Vayne": 2000.0,
    "Lux": 1600.0,
}


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "speed"), [
    ("Caitlyn", 2500.0),
    ("Jinx", 2750.0),
    ("Jhin", 2600.0),
    ("Ashe", 2500.0),
    ("Vayne", 2000.0),
    ("Lux", 1600.0),
])
def test_seed_aa_speed(snap: DataSnapshot, champ: str, speed: float) -> None:
    assert snap.aa_missile_speed(champ) == speed


def test_all_seeds_present_and_positive(snap: DataSnapshot) -> None:
    for champ, expected in _SEEDS.items():
        got = snap.aa_missile_speed(champ)
        assert got == expected, f"{champ}: {got!r} != {expected!r}"
        assert isinstance(got, float)
        assert got > 0.0


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_returns_float(snap: DataSnapshot) -> None:
    s = snap.aa_missile_speed("Caitlyn")
    assert isinstance(s, float)
    assert s > 0.0


# ---------------------------------------------------------------------------
# distinct axis: AA speed reads wiki_stats (champ-keyed), not the cdragon sidecar
# ---------------------------------------------------------------------------


def test_reads_wiki_stats_source(snap: DataSnapshot) -> None:
    # The accessor surfaces exactly the wiki_stats per-champ missile_speed.
    for champ in ("Caitlyn", "Jinx", "Ashe"):
        raw = snap.wiki_stats.get(champ, {}).get("missile_speed")
        assert snap.aa_missile_speed(champ) == raw


def test_champ_keyed_not_slot_keyed(snap: DataSnapshot) -> None:
    # aa_missile_speed takes only a champ (no slot) - it is the basic-attack
    # missile, a distinct axis from the per-spell cdragon primary.
    assert snap.aa_missile_speed("Caitlyn") == 2500.0


# ---------------------------------------------------------------------------
# instant band: >=5000 is positive so it is returned (not gated)
# ---------------------------------------------------------------------------


def test_instant_band_returned(snap: DataSnapshot) -> None:
    # Kayle AA missile_speed is 5000.0 (instant / global band). A forward-marker
    # returns the positive magnitude; band gating is a future consumer's job.
    assert snap.wiki_stats.get("Kayle", {}).get("missile_speed") == 5000.0
    assert snap.aa_missile_speed("Kayle") == 5000.0


# ---------------------------------------------------------------------------
# sentinel / absent (real data)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("champ", ["Azir", "Senna", "Thresh", "Velkoz", "Zeri"])
def test_zero_sentinel_rejected(snap: DataSnapshot, champ: str) -> None:
    # 0.0 is the no-projectile / non-standard-AA sentinel -> None via <= 0 guard.
    assert snap.wiki_stats.get(champ, {}).get("missile_speed") == 0.0
    assert snap.aa_missile_speed(champ) is None


@pytest.mark.parametrize("champ", ["Garen", "Darius"])
def test_melee_null_is_none(snap: DataSnapshot, champ: str) -> None:
    # Melee champs carry a null missile_speed -> None.
    assert snap.wiki_stats.get(champ, {}).get("missile_speed") is None
    assert snap.aa_missile_speed(champ) is None


def test_none_for_unknown_champ(snap: DataSnapshot) -> None:
    assert snap.aa_missile_speed("NotAChampion") is None


# ---------------------------------------------------------------------------
# hygiene / fallback (crafted sidecar)
# ---------------------------------------------------------------------------


def test_absent_sidecar(snap: DataSnapshot) -> None:
    assert _stub(snap, {}).aa_missile_speed("Caitlyn") is None


def test_missing_key(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_cast_time": 0.3}}
    assert _stub(snap, ws).aa_missile_speed("X") is None


def test_none_value(snap: DataSnapshot) -> None:
    ws = {"X": {"missile_speed": None}}
    assert _stub(snap, ws).aa_missile_speed("X") is None


def test_zero_rejected_stub(snap: DataSnapshot) -> None:
    ws = {"X": {"missile_speed": 0.0}}
    assert _stub(snap, ws).aa_missile_speed("X") is None


def test_negative_rejected_stub(snap: DataSnapshot) -> None:
    ws = {"X": {"missile_speed": -5.0}}
    assert _stub(snap, ws).aa_missile_speed("X") is None


def test_bool_rejected(snap: DataSnapshot) -> None:
    ws = {"X": {"missile_speed": True}}
    assert _stub(snap, ws).aa_missile_speed("X") is None


def test_non_numeric_rejected(snap: DataSnapshot) -> None:
    ws = {"X": {"missile_speed": "fast"}}
    assert _stub(snap, ws).aa_missile_speed("X") is None


def test_numeric_string_rejected(snap: DataSnapshot) -> None:
    # spell_missile_speed does NOT coerce strings -> sibling matches it: None.
    ws = {"X": {"missile_speed": "2500"}}
    assert _stub(snap, ws).aa_missile_speed("X") is None


def test_int_coerced_to_float(snap: DataSnapshot) -> None:
    ws = {"X": {"missile_speed": 2500}}
    got = _stub(snap, ws).aa_missile_speed("X")
    assert got == 2500.0
    assert isinstance(got, float)


# ---------------------------------------------------------------------------
# byte-identical: wiki_attack_cast_time sibling untouched
# ---------------------------------------------------------------------------


def test_wiki_attack_cast_time_unchanged(snap: DataSnapshot) -> None:
    # The AA missile-speed lift does not perturb the AA-windup sibling accessor.
    for champ in ("Caitlyn", "Jinx", "Ashe"):
        assert snap.wiki_attack_cast_time(champ) == snap.wiki_stats.get(
            champ, {}
        ).get("attack_cast_time")


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only data_loader.py (definition) may reference aa_missile_speed.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "data_loader.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "aa_missile_speed" in text:
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
