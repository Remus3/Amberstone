"""total auto-attack cycle-time accessor - schema lift item 345 (2026-06-07).

A NEW forward-marker accessor ``DataSnapshot.wiki_attack_total_time`` exposing
the wiki_stats per-champion ``attack_total_time`` datum as a first-class
comparable MAGNITUDE - the FULL basic-attack cycle duration (seconds): windup
PLUS recovery, i.e. ``1 / attackSpeed`` at base. This is a DISTINCT axis from
``wiki_attack_cast_time`` (item 221), which is the WINDUP-only portion (the
point in the cycle the projectile / damage commits). The total time governs how
OFTEN the auto fires; the cast time governs how long each one locks the champ.
They diverge for every champ that carries the datum (Jhin total 1.6 vs cast
0.25). It was loaded into ``DataSnapshot.wiki_stats`` alongside
``attack_cast_time`` (item 221) + ``missile_speed`` (item 344) +
``mode_modifiers`` (item 232) but no accessor ever surfaced it.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/wiki_stats.json`` via
``DataSnapshot.load()`` (ground-truth probed 2026-06-07; the union of wiki_stats
record keys is exactly attack_cast_time / attack_cast_time_src /
attack_total_time / attack_total_time_src / missile_speed / missile_speed_src /
mode_modifiers / wiki_name - the ``*_src`` keys are provenance strings and
``wiki_name`` is a display string, so ``attack_total_time`` is the single
remaining unsurfaced top-level MAGNITUDE; 61 champs carry a numeric value, all
61 positive and all 61 distinct from that champ's ``attack_cast_time``; 110 are
null / absent):

* Jhin AA     attack_total_time=1.6     (cast 0.25)
* Draven AA   attack_total_time=1.473   (cast 0.23)
* Aatrox AA   attack_total_time=1.52    (cast 0.30)
* Belveth AA  attack_total_time=1.01    (cast 0.25)
* Jinx AA     attack_total_time=1.6     (cast 0.27)
* Azir AA     attack_total_time=1.6     (cast 0.25)

None / absent cases (the datum is a 61-champ coverage subset, NOT a melee/ranged
split - Belveth + Aatrox are melee yet carry it):
* Garen / Lux  attack_total_time null -> None
* unknown champ                       -> None

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes
``wiki_attack_total_time`` at ship - it mirrors the item-344 ``aa_missile_speed``
/ item-221 ``wiki_attack_cast_time`` sibling accessors (snapshot-method idiom
reading the already-loaded sidecar; no data duplication, patch-refresh-safe) and
the item-336 / 337 / 338 / 339 / 340 / 341 / 342 / 343 / 344 forward-marker
contract (no consumer -> byte-identical -> ENGINE_VERSION does NOT bump). The
``wiki_attack_cast_time`` / ``mode_modifier`` siblings and every serialized
surface are untouched, so live DS output is byte-identical.

Guard mirrors ``aa_missile_speed`` (item 344) exactly: reject bool / non-numeric
and do NOT coerce a numeric STRING (returns None), PLUS a ``<= 0`` guard so a
non-positive sentinel returns None rather than a nonsensical zero-length attack
cycle. The ``<= 0`` clause is defensive (the live 16.11.1 data carries no
non-positive value) and keeps the guard sibling_consistent with the prior AA
accessor.

Coverage classes:
* value pins - exact total cycle time per seed from 16.11.1.
* shape - the accessor returns a positive float for a seeded champ.
* distinct-axis - the total time differs from the windup-only cast time.
* source - the accessor surfaces exactly wiki_stats[champ]["attack_total_time"].
* absent - None for the no-datum champs and an unknown champ.
* hygiene / fallback - absent-sidecar / missing-key / None / bool / non-numeric
  / numeric-string fall to None; int / float coerce to float; 0.0 / negative
  reject to None (the ``<= 0`` guard).
* byte-identical - ``wiki_attack_cast_time`` is UNCHANGED for the seeds (the
  total-time lift touched neither it nor ``mode_modifier``).
* forward-marker - no production module other than the definition
  (``data_loader.py``) references ``wiki_attack_total_time``.
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

    wiki_attack_total_time touches ONLY self.wiki_stats, so reusing the loaded
    snapshot's other fields and swapping the sidecar dict exercises the guard
    without rebuilding the full constructor.
    """
    return dataclasses.replace(snap, wiki_stats=ws)


# ---------------- expected seed set ----------------

_SEEDS: dict[str, float] = {
    "Jhin": 1.6,
    "Draven": 1.473,
    "Aatrox": 1.52,
    "Belveth": 1.01,
    "Jinx": 1.6,
    "Azir": 1.6,
}


# ---------------------------------------------------------------------------
# value pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("champ", "total"), list(_SEEDS.items()))
def test_seed_total_time(snap: DataSnapshot, champ: str, total: float) -> None:
    assert snap.wiki_attack_total_time(champ) == pytest.approx(total, abs=1e-4)


def test_all_seeds_present_and_positive(snap: DataSnapshot) -> None:
    for champ, expected in _SEEDS.items():
        got = snap.wiki_attack_total_time(champ)
        assert got is not None, f"{champ}: unexpectedly None"
        assert got == pytest.approx(expected, abs=1e-4), f"{champ}: {got!r}"
        assert isinstance(got, float)
        assert got > 0.0


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


def test_returns_float(snap: DataSnapshot) -> None:
    t = snap.wiki_attack_total_time("Jhin")
    assert isinstance(t, float)
    assert t > 0.0


# ---------------------------------------------------------------------------
# distinct axis: total cycle time != windup-only cast time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("champ", list(_SEEDS))
def test_distinct_from_cast_time(snap: DataSnapshot, champ: str) -> None:
    total = snap.wiki_attack_total_time(champ)
    cast = snap.wiki_attack_cast_time(champ)
    assert total is not None and cast is not None
    assert abs(total - cast) > 1e-6


# ---------------------------------------------------------------------------
# source: surfaces exactly wiki_stats[champ]["attack_total_time"]
# ---------------------------------------------------------------------------


def test_reads_wiki_stats_source(snap: DataSnapshot) -> None:
    for champ in ("Jhin", "Draven", "Belveth"):
        raw = snap.wiki_stats.get(champ, {}).get("attack_total_time")
        assert snap.wiki_attack_total_time(champ) == raw


def test_champ_keyed(snap: DataSnapshot) -> None:
    # wiki_attack_total_time takes only a champ (no slot) - it is the basic
    # attack cycle, a per-champ axis.
    assert snap.wiki_attack_total_time("Belveth") == pytest.approx(1.01, abs=1e-4)


# ---------------------------------------------------------------------------
# absent (real data)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("champ", ["Garen", "Lux"])
def test_no_datum_is_none(snap: DataSnapshot, champ: str) -> None:
    # 110 champs carry no attack_total_time datum -> None (a coverage subset,
    # not a melee/ranged split).
    assert snap.wiki_stats.get(champ, {}).get("attack_total_time") is None
    assert snap.wiki_attack_total_time(champ) is None


def test_none_for_unknown_champ(snap: DataSnapshot) -> None:
    assert snap.wiki_attack_total_time("NotAChampion") is None


# ---------------------------------------------------------------------------
# hygiene / fallback (crafted sidecar)
# ---------------------------------------------------------------------------


def test_absent_sidecar(snap: DataSnapshot) -> None:
    assert _stub(snap, {}).wiki_attack_total_time("Jhin") is None


def test_missing_key(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_cast_time": 0.3}}
    assert _stub(snap, ws).wiki_attack_total_time("X") is None


def test_none_value(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_total_time": None}}
    assert _stub(snap, ws).wiki_attack_total_time("X") is None


def test_zero_rejected_stub(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_total_time": 0.0}}
    assert _stub(snap, ws).wiki_attack_total_time("X") is None


def test_negative_rejected_stub(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_total_time": -1.5}}
    assert _stub(snap, ws).wiki_attack_total_time("X") is None


def test_bool_rejected(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_total_time": True}}
    assert _stub(snap, ws).wiki_attack_total_time("X") is None


def test_non_numeric_rejected(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_total_time": "slow"}}
    assert _stub(snap, ws).wiki_attack_total_time("X") is None


def test_numeric_string_rejected(snap: DataSnapshot) -> None:
    # aa_missile_speed does NOT coerce strings -> sibling matches it: None.
    ws = {"X": {"attack_total_time": "1.6"}}
    assert _stub(snap, ws).wiki_attack_total_time("X") is None


def test_int_coerced_to_float(snap: DataSnapshot) -> None:
    ws = {"X": {"attack_total_time": 2}}
    got = _stub(snap, ws).wiki_attack_total_time("X")
    assert got == 2.0
    assert isinstance(got, float)


# ---------------------------------------------------------------------------
# byte-identical: wiki_attack_cast_time sibling untouched
# ---------------------------------------------------------------------------


def test_wiki_attack_cast_time_unchanged(snap: DataSnapshot) -> None:
    # The total-time lift does not perturb the AA-windup sibling accessor.
    for champ in ("Jhin", "Draven", "Belveth"):
        assert snap.wiki_attack_cast_time(champ) == snap.wiki_stats.get(
            champ, {}
        ).get("attack_cast_time")


# ---------------------------------------------------------------------------
# forward-marker: no production consumer
# ---------------------------------------------------------------------------


def test_no_production_consumer() -> None:
    """Only data_loader.py (definition) may reference wiki_attack_total_time.

    Scans the daemon_slayer engine package's non-test .py files; a true
    forward-marker has no consumer beyond its own definition module.
    """
    pkg = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in pkg.glob("*.py"):
        if path.name == "data_loader.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "wiki_attack_total_time" in text:
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
