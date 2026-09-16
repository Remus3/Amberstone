"""RM-439 - a failed data load in core/ must not be cached for the process lifetime.

BACKLOG row RM-439 (filed 2026-09-16, LEDGER 1419), the sibling sweep of the
item_advisor residuals fix ``1371e7b5e``. Every loader below used an ``is None``
cache sentinel and wrote its empty fallback into the cache when the load failed,
so ONE transient failure at first call (AV scan / editor lock on Windows, a patch
refresh that flips ``current.txt`` before the patch files land, a half-written
hand edit) degraded the process until restart. Two sites logged nothing at all.

Contract pinned per site:

  * a failed load returns the empty value and is NOT cached - once the data is
    readable again (and the retry backoff has elapsed) the next call returns
    the real data;
  * inside the backoff window a failed loader does not touch the disk again
    (bounded hot-path cost: ``canonical_champion_id`` / ``canonical_item_id``
    are called per champion / per item, and a broken 845 KB items.json parses
    in ~3.5 ms);
  * a successful load IS cached (a second call does not re-read);
  * the failure warns ONCE per failure streak, not once per call.

The clock is advanced by patching ``time.monotonic`` so the retry arm needs no
real sleep. No network, no live ports.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

import core.aram_item_interaction_context as aic
import core.archetype_picks as ap
import core.build_planner.champ_kit_data as ckd
import core.build_planner.kit_synergy as ks
import core.ds_onhit_ap_roster as onhit
import core.ds_support_route_overrides as sro

_PATCH = "9.9.9"
_BAD = "{ this is not json"


@dataclass(frozen=True)
class Site:
    id: str
    module: Any
    cache_attr: str
    logger_name: str
    point: Callable[[Path, pytest.MonkeyPatch], Path]  # returns the file to write
    call: Callable[[], Any]
    good_text: str
    is_good: Callable[[Any], bool]


def _point_attr(module, attr):
    def _p(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
        target = tmp_path / "data.json"
        mp.setattr(module, attr, target)
        return target
    return _p


def _point_ds_dir(module, filename):
    def _p(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
        ds = tmp_path / "daemon_slayer"
        (ds / _PATCH).mkdir(parents=True)
        (ds / "current.txt").write_text(_PATCH, encoding="utf-8")
        mp.setattr(module, "_DS_DIR", ds)
        return ds / _PATCH / filename
    return _p


_DDRAGON = json.dumps({"data": {
    "MonkeyKing": {"id": "MonkeyKing", "key": "62", "name": "Wukong",
                   "tags": ["Fighter", "Tank"]},
}})

_DS_CHAMPS = json.dumps({"data": {
    "Lux": {"id": "Lux", "key": "99", "name": "Lux", "tags": ["Mage"],
            "lolmath": {"damage_distribution": {"magical": 0.9, "physical": 0.1}}},
}})

SITES = [
    Site(
        "aram_item_interaction_context._get_index", aic, "_INDEX",
        aic.__name__, _point_attr(aic, "_DEFAULT_PATH"), aic._get_index,
        json.dumps({"cells": [{"shape": "poke", "timing": "early",
                               "name": "Thornmail", "item_id": 3075,
                               "winrate_smoothed": 0.58, "n": 27}]}),
        lambda r: bool(r) and ("poke", "early", 3075) in r["by_id"],
    ),
    Site(
        "ds_onhit_ap_roster.load_onhit_ap_roster", onhit, "_ROSTER_CACHE",
        onhit.__name__, _point_attr(onhit, "_ROSTER_PATH"),
        onhit.load_onhit_ap_roster,
        json.dumps({"champions": {"Kayle": {"coherence": 0.7}}}),
        lambda r: r == {"Kayle": 0.7},
    ),
    Site(
        "archetype_picks._load_damage_axes", ap, "_DAMAGE_AXIS_CACHE",
        "rc.archetype_picks", _point_ds_dir(ap, "champions.json"),
        ap._load_damage_axes, _DS_CHAMPS, lambda r: r.get("Lux") == "ap",
    ),
    Site(
        "archetype_picks._load_aram_overrides", ap, "_ARAM_OVERRIDE_CACHE",
        "rc.archetype_picks", _point_attr(ap, "_ARAM_OVERRIDE_PATH"),
        ap._load_aram_overrides,
        json.dumps({"champions": {"Kayle": {"override": "mage"}}}),
        lambda r: r == {"Kayle": "mage"},
    ),
    Site(
        "archetype_picks._load_champion_tags", ap, "_TAGS_CACHE",
        "rc.archetype_picks", _point_attr(ap, "_CHAMPS_PATH"),
        ap._load_champion_tags, _DDRAGON,
        lambda r: r.get("Wukong") == ["Fighter", "Tank"],
    ),
    Site(
        "archetype_picks.champion_name_by_key", ap, "_KEY_NAME_CACHE",
        "rc.archetype_picks", _point_attr(ap, "_CHAMPS_PATH"),
        lambda: ap.champion_name_by_key("62"), _DDRAGON,
        lambda r: r == "Wukong",
    ),
    Site(
        "archetype_picks.canonical_champion_id", ap, "_ID_CACHE",
        "rc.archetype_picks", _point_attr(ap, "_CHAMPS_PATH"),
        lambda: ap.canonical_champion_id("Wukong"), _DDRAGON,
        lambda r: r == "MonkeyKing",
    ),
    Site(
        "archetype_picks._load_picks", ap, "_PICKS_CACHE",
        "rc.archetype_picks", _point_attr(ap, "_PICKS_PATH"),
        ap._load_picks,
        json.dumps({"Garen": {"primary": "tank", "secondary": "bruiser"}}),
        lambda r: r.get("Garen", {}).get("primary") == "tank",
    ),
    Site(
        "champ_kit_data._load_champions", ckd, "_CHAMP_CACHE",
        "rc.build_planner.champ_kit_data", _point_ds_dir(ckd, "champions.json"),
        ckd._load_champions, _DS_CHAMPS, lambda r: r.get("Lux", {}).get("key") == "99",
    ),
    Site(
        "champ_kit_data._load_ability_ratios", ckd, "_RATIO_CACHE",
        "rc.build_planner.champ_kit_data",
        _point_ds_dir(ckd, "cdragon_ability_ratios.json"),
        ckd._load_ability_ratios,
        json.dumps({"champions": {"Lux": {"q": {"ap": 0.65}}}}),
        lambda r: r == {"Lux": {"q": {"ap": 0.65}}},
    ),
    Site(
        "kit_synergy._load_items", ks, "_ITEM_CACHE",
        "rc.build_planner.kit_synergy", _point_ds_dir(ks, "items.json"),
        ks._load_items,
        json.dumps({"data": {"3075": {"name": "Thornmail", "tags": ["Armor"]}}}),
        lambda r: r.get("3075", {}).get("name") == "Thornmail",
    ),
    Site(
        "ds_support_route_overrides.load_support_route_overrides", sro,
        "_ROSTER_CACHE", sro.__name__, _point_attr(sro, "_ROSTER_PATH"),
        sro.load_support_route_overrides,
        json.dumps({"champions": {"Lulu": {"primary": "mage"}}}),
        lambda r: r == {"Lulu": ("mage", "enchanter")},
    ),
]

_IDS = [s.id for s in SITES]
_MODULES = (aic, onhit, ap, ckd, ks, sro)
_CACHE_ATTRS = {
    aic: ("_INDEX",),
    onhit: ("_ROSTER_CACHE",),
    ap: ("_DAMAGE_AXIS_CACHE", "_ARAM_OVERRIDE_CACHE", "_TAGS_CACHE",
         "_KEY_NAME_CACHE", "_ID_CACHE", "_PICKS_CACHE"),
    ckd: ("_CHAMP_CACHE", "_RATIO_CACHE"),
    ks: ("_ITEM_CACHE", "_ALIAS_INDEX"),
    sro: ("_ROSTER_CACHE",),
}


def _reset_all() -> None:
    """Drop every cache under test plus any failure gate, so no state leaks
    into (or out of) this file. Gates are found by duck type so this helper
    also runs against the pre-fix tree."""
    for mod in _MODULES:
        for attr in _CACHE_ATTRS[mod]:
            setattr(mod, attr, None)
        for name in dir(mod):
            if name.endswith("_GATE"):
                reset = getattr(getattr(mod, name), "reset", None)
                if callable(reset):
                    reset()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_all()
    yield
    _reset_all()


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(time, "monotonic", c)
    return c


@pytest.fixture
def reads(monkeypatch):
    """Count Path.read_text calls per resolved path."""
    counts: dict[str, int] = {}
    real = Path.read_text

    def counting(self, *a, **kw):
        key = str(self)
        counts[key] = counts.get(key, 0) + 1
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", counting)
    return counts


def _warnings(caplog, logger_name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.name == logger_name and r.levelno >= logging.WARNING]


def _empty_for(site: Site) -> Any:
    if site.id.endswith("champion_name_by_key"):
        return ""
    if site.id.endswith("canonical_champion_id"):
        return "Wukong"  # unresolved name passes through unchanged
    return {}


# Retry after the backoff: 5 s by default; advance well past any small TTL.
_PAST_BACKOFF = 3600.0


@pytest.mark.parametrize("site", SITES, ids=_IDS)
def test_failed_load_is_not_cached_and_a_later_call_recovers(
    site, tmp_path, monkeypatch, clock,
):
    target = site.point(tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")

    first = site.call()
    assert first == _empty_for(site)
    assert getattr(site.module, site.cache_attr) is None, (
        "a failed load must not be written into the cache"
    )

    target.write_text(site.good_text, encoding="utf-8")
    clock.advance(_PAST_BACKOFF)
    second = site.call()
    assert site.is_good(second), f"recovered load returned {second!r}"


@pytest.mark.parametrize("site", SITES, ids=_IDS)
def test_successful_load_is_cached(site, tmp_path, monkeypatch, clock, reads):
    target = site.point(tmp_path, monkeypatch)
    target.write_text(site.good_text, encoding="utf-8")

    assert site.is_good(site.call())
    n = reads.get(str(target), 0)
    assert n == 1

    target.write_text(_BAD, encoding="utf-8")  # a cached success ignores disk
    clock.advance(_PAST_BACKOFF)
    assert site.is_good(site.call())
    assert reads.get(str(target), 0) == 1


@pytest.mark.parametrize("site", SITES, ids=_IDS)
def test_failure_warns_once_per_streak_and_backs_off(
    site, tmp_path, monkeypatch, clock, reads, caplog,
):
    target = site.point(tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")
    caplog.set_level(logging.DEBUG)

    site.call()
    assert reads.get(str(target), 0) == 1
    # Inside the backoff window: no second disk read.
    site.call()
    assert reads.get(str(target), 0) == 1

    clock.advance(_PAST_BACKOFF)
    site.call()
    assert reads.get(str(target), 0) == 2, "the failed load was not retried"

    assert len(_warnings(caplog, site.logger_name)) == 1, [
        r.getMessage() for r in _warnings(caplog, site.logger_name)
    ]


def test_gate_streak_semantics(clock):
    """First failure of a streak reports True; a success ends the streak so the
    next failure reports True again; the backoff window is honoured."""
    from core.failed_load_gate import FailedLoadGate

    gate = FailedLoadGate(retry_after_s=5.0)
    assert gate.should_attempt()
    assert gate.record_failure() is True
    assert gate.should_attempt() is False
    clock.advance(4.9)
    assert gate.should_attempt() is False
    clock.advance(0.2)
    assert gate.should_attempt() is True
    assert gate.record_failure() is False  # same streak - no second warning
    gate.record_success()
    assert gate.should_attempt() is True
    assert gate.record_failure() is True   # new streak warns again


def test_picks_missing_file_is_a_cached_legitimate_empty(tmp_path, monkeypatch):
    """data/cs_archetype_picks.json is gitignored and absent in a fresh clone:
    absence is the NORMAL no-picks state, not a failure, so it stays cached."""
    monkeypatch.setattr(ap, "_PICKS_PATH", tmp_path / "absent.json")
    assert ap._load_picks() == {}
    assert ap._PICKS_CACHE == {}


def test_ds_patch_pointer_failure_is_not_cached(tmp_path, monkeypatch, clock):
    """A missing current.txt (patch refresh mid-flight) is a failure too."""
    ds = tmp_path / "daemon_slayer"
    ds.mkdir()
    monkeypatch.setattr(ks, "_DS_DIR", ds)
    assert ks._load_items() == {}
    assert ks._ITEM_CACHE is None
    (ds / _PATCH).mkdir()
    (ds / _PATCH / "items.json").write_text(
        json.dumps({"data": {"1001": {"name": "Boots"}}}), encoding="utf-8")
    (ds / "current.txt").write_text(_PATCH, encoding="utf-8")
    clock.advance(_PAST_BACKOFF)
    assert ks._load_items()["1001"]["name"] == "Boots"


def test_invalidate_clears_a_backoff(tmp_path, monkeypatch, clock):
    """The existing invalidate helpers must also end a backoff window, or a
    test (or patch refresh) that invalidates right after a failure is served
    the stale empty value."""
    target = _point_attr(sro, "_ROSTER_PATH")(tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")
    assert sro.load_support_route_overrides() == {}
    target.write_text(json.dumps({"champions": {"Lulu": {"primary": "mage"}}}),
                      encoding="utf-8")
    sro.reset_support_route_override_cache()
    assert sro.load_support_route_overrides() == {"Lulu": ("mage", "enchanter")}
