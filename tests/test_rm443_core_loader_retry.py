"""RM-443 - census follow-on to RM-439: more core/ loaders cached a failed load.

BACKLOG row RM-443 (filed 2026-09-16, LEDGER 1420). RM-439 fixed 12 loaders and
shipped ``core/failed_load_gate.py``; its AST census found further candidates.
The candidate list was RE-DERIVED for this row (the filed count is a
hypothesis) and each hit classified. This file pins the DEFECT sites.

Two shapes are pinned:

1. ``is None`` / keyed-permanent caches (``SITES``). Contract, identical to
   RM-439: a failed load returns the fail-soft value and is NOT cached; inside
   the gate's backoff window the loader does not touch the disk again; once the
   backoff has elapsed and the data is readable the next call returns real
   data; a successful load IS cached; the failure warns once per streak.

2. mtime-keyed caches (``MTIME_SITES``). These already re-read when the file
   changes, so a MALFORMED file heals when it is rewritten, and that stays as
   is (same mtime, same bytes, same parse result). The defect is the transient
   read error: a Windows sharing violation during an atomic replace lands the
   empty payload under the NEW mtime, and the file never changes again. Contract:
   an OSError on read is not cached; malformed content at an unchanged mtime
   still is; a success is cached.

The clock is advanced by patching ``time.monotonic``. No network, no live ports.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

import core.arena_augment_playline as aap
import core.build_order_precompute as bop
import core.build_order_variants as bov
import core.build_planner.fed_threat as ft
import core.build_planner.replan as rp
import core.build_planner.situational as sit
import core.champion_movespeed as cms
import core.daemon_slayer_client as dsc
import core.defensive_picks as dp
import core.enemy_aware_stats as eas
import core.laning_scenario_precompute as lsp
import core.minimap_identity as mmi
import core.next_buy_fallback as nbf
import core.personal_build_wr as pbw
import core.pickban_targets as pbt
import core.vision_profiles as vprof
import core.vision_tesseract as vt

_PATCH = "9.9.9"
_BAD = "{ this is not json"
_PAST_BACKOFF = 3600.0

_CHAMPS = json.dumps({"data": {
    "MonkeyKing": {
        "id": "MonkeyKing", "key": "62", "name": "Wukong",
        "tags": ["Fighter", "Tank"],
        "info": {"attack": 8, "magic": 2, "defense": 5, "difficulty": 3},
        "stats": {"movespeed": 340, "armor": 31, "armorperlevel": 4.7,
                  "spellblock": 32, "spellblockperlevel": 2.05,
                  "hp": 610, "hpperlevel": 99},
    },
}})

_ITEMS = json.dumps({"data": {
    "3075": {"name": "Thornmail", "tags": ["Armor"], "from": ["1029", "3076"],
             "gold": {"total": 2450},
             "stats": {"FlatArmorMod": 75, "FlatHPPoolMod": 150}},
    "3009": {"name": "Boots of Swiftness", "tags": ["Boots"],
             "gold": {"total": 1000}, "stats": {"FlatMovementSpeedMod": 60}},
}})

_BUILD_ORDERS = json.dumps({"build_orders": {"Lux": {"core": ["3089"]}}})


@dataclass(frozen=True)
class Site:
    id: str
    logger_name: str
    point: Callable[[Path, pytest.MonkeyPatch], Path]  # returns the file to write
    call: Callable[[], Any]
    good_text: str
    is_good: Callable[[Any], bool]
    is_fallback: Callable[[Any], bool]
    is_uncached: Callable[[], bool]


def _point_attr(module, attr, name="data.json"):
    def _p(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
        target = tmp_path / name
        mp.setattr(module, attr, target)
        return target
    return _p


def _point_ds_dir(module, filename, attr="_DS_DIR"):
    def _p(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
        ds = tmp_path / "daemon_slayer"
        (ds / _PATCH).mkdir(parents=True)
        (ds / "current.txt").write_text(_PATCH, encoding="utf-8")
        mp.setattr(module, attr, ds)
        return ds / _PATCH / filename
    return _p


def _point_pbw(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "dd"
    (root / _PATCH).mkdir(parents=True)
    mp.setattr(pbw, "_DDRAGON_ROOT", root)
    return root / _PATCH / "items.json"


def _point_mmi(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "MonkeyKing.png").write_bytes(b"")
    mp.setattr(mmi, "_ICON_DIR", icons)
    target = tmp_path / "ddragon_champions.json"
    mp.setattr(mmi, "_CHAMPS_PATH", target)
    return target


def _point_vt(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    # No per-HUD profile: _regions() falls through to the legacy file.
    mp.setattr(vprof, "load_profile", lambda *a, **k: {})
    target = tmp_path / "vision_regions.json"
    mp.setattr(vt, "_REGIONS_FILE", target)
    return target


def _point_lsp(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    ds = tmp_path / "daemon_slayer"
    (ds / _PATCH).mkdir(parents=True)
    (ds / "current.txt").write_text(_PATCH, encoding="utf-8")
    mp.setattr(lsp, "_DS_DIR", ds)
    mp.setattr(lsp, "_CURRENT_TXT", ds / "current.txt")
    return ds / _PATCH / "build_orders_sr.json"


def _none(module, attr):
    return lambda: getattr(module, attr) is None


_LSP_LOG = "rc.laning_scenario_precompute"

SITES = [
    Site("daemon_slayer_client.champion_attackrange", dsc.logger.name,
         _point_ds_dir(dsc, "champions.json", "_DS_DATA_DIR"),
         lambda: dsc.champion_attackrange("Lux"),
         json.dumps({"data": {"Lux": {"name": "Lux", "stats": {"attackrange": 550}}}}),
         lambda r: r == 550.0, lambda r: r == 0.0,
         _none(dsc, "_champ_attackrange_index")),
    Site("daemon_slayer_client.champion_has_ability_data", dsc.logger.name,
         _point_ds_dir(dsc, "champion_abilities.json", "_DS_DATA_DIR"),
         lambda: dsc.champion_has_ability_data("Nobody"),
         json.dumps({"Lux": {"q": {}}}),
         lambda r: r is False, lambda r: r is True,
         _none(dsc, "_champ_ability_index")),
    Site("daemon_slayer_client._champion_is_stale", dsc.logger.name,
         _point_ds_dir(dsc, "ability_staleness.json", "_DS_DATA_DIR"),
         lambda: dsc._champion_is_stale("Lux"),
         json.dumps({"stale_champions": ["Lux"]}),
         lambda r: r is True, lambda r: r is False,
         _none(dsc, "_champ_stale_index")),
    Site("champion_movespeed._champ_index", cms._log.name,
         _point_attr(cms, "_CHAMPS_PATH"), cms._champ_index, _CHAMPS,
         lambda r: r.get("wukong") == 340.0, lambda r: r == {},
         _none(cms, "_CHAMP_MS")),
    Site("champion_movespeed._item_index", cms._log.name,
         _point_attr(cms, "_ITEMS_PATH"), cms._item_index, _ITEMS,
         lambda r: r.get("3009") == (60.0, 0.0), lambda r: r == {},
         _none(cms, "_ITEM_MS")),
    Site("enemy_aware_stats._load_champ_index", eas._log.name,
         _point_attr(eas, "_CHAMPS_PATH"), eas._load_champ_index, _CHAMPS,
         lambda r: r.get("MonkeyKing", {}).get("armor") == 31.0,
         lambda r: r == {}, _none(eas, "_CHAMP_INDEX")),
    Site("enemy_aware_stats._load_stat_index", eas._log.name,
         _point_attr(eas, "_ITEMS_PATH"), eas._load_stat_index, _ITEMS,
         lambda r: r.get("3075") == {"armor": 75.0, "mr": 0.0, "hp": 150.0},
         lambda r: r == {}, _none(eas, "_STAT_INDEX")),
    Site("defensive_picks._load_champ_info", dp._log.name,
         _point_attr(dp, "_CHAMPS_PATH"), dp._load_champ_info, _CHAMPS,
         lambda r: r.get("Wukong", {}).get("attack") == 8,
         lambda r: r == {}, _none(dp, "_CHAMP_INFO")),
    Site("fed_threat._load_gold_map", ft._log.name,
         _point_attr(ft, "_ITEMS_PATH"), ft._load_gold_map, _ITEMS,
         lambda r: r.get("3075") == 2450.0, lambda r: r == {},
         _none(ft, "_GOLD_MAP")),
    Site("replan._load_recipe", rp.__name__,
         _point_attr(rp, "_ITEMS_PATH"), rp._load_recipe, _ITEMS,
         lambda r: r.get("3075", {}).get("from") == ("1029", "3076"),
         lambda r: r == {}, _none(rp, "_RECIPE")),
    Site("situational._load_catalog", sit.__name__,
         _point_attr(sit, "_ITEMS_PATH"), sit._load_catalog, _ITEMS,
         lambda r: r.get("3075", {}).get("name") == "Thornmail",
         lambda r: r == {}, _none(sit, "_CATALOG")),
    Site("arena_augment_playline._rows", aap.__name__,
         _point_ds_dir(aap, "arena_augments.json"), aap._rows,
         json.dumps({"augments": [{"name": "Tank Engine"}]}),
         lambda r: r == [{"name": "Tank Engine"}], lambda r: r == [],
         _none(aap, "_ROWS_CACHE")),
    # Derived index over _rows(): it must not freeze an empty projection of a
    # failed (and therefore uncached) row load.
    Site("arena_augment_playline._load_index", aap.__name__,
         _point_ds_dir(aap, "arena_augments.json"), aap._load_index,
         json.dumps({"augments": [{"name": "Tank Engine"}]}),
         lambda r: r.get("tankengine") == {"name": "Tank Engine"},
         lambda r: r == {}, _none(aap, "_INDEX_CACHE")),
    Site("personal_build_wr._item_meta", pbw.__name__, _point_pbw,
         pbw._item_meta, _ITEMS,
         lambda r: r.get("3075") == {"name": "Thornmail", "gold": 2450},
         lambda r: r == {}, _none(pbw, "_META_CACHE")),
    Site("minimap_identity._icon_index", mmi._log.name, _point_mmi,
         mmi._icon_index, _CHAMPS,
         lambda r: "wukong" in r,
         lambda r: "wukong" not in r and "monkeyking" in r,
         _none(mmi, "_ICON_INDEX")),
    Site("vision_tesseract._regions", vt._log.name, _point_vt, vt._regions,
         json.dumps({"_base": [1920, 1080], "gold": [1, 2, 3, 4]}),
         lambda r: r.get("gold") == [1, 2, 3, 4],
         lambda r: r == vt._DEFAULT_REGIONS, _none(vt, "_REGIONS_CACHE")),
    Site("laning_scenario_precompute.load_build_orders", _LSP_LOG, _point_lsp,
         lambda: lsp.load_build_orders("sr"), _BUILD_ORDERS,
         lambda r: r == {"Lux": {"core": ["3089"]}}, lambda r: r == {},
         lambda: "sr" not in lsp._BUILD_ORDERS_CACHE),
    Site("next_buy_fallback._canon_table", _LSP_LOG, _point_lsp,
         lambda: nbf._canon_table("sr"), _BUILD_ORDERS,
         lambda r: r.get("Lux") == {"core": ["3089"]}, lambda r: r == {},
         lambda: "sr" not in nbf._CANON_CACHE),
]
_IDS = [s.id for s in SITES]


def _reset_all() -> None:
    """Drop every cache under test plus any failure gate. Gates are found by
    duck type so this helper also runs against the pre-fix tree."""
    dsc._champ_attackrange_index = None
    dsc._champ_ability_index = None
    dsc._champ_stale_index = None
    cms._reset_caches()
    eas._CHAMP_INDEX = None
    eas._STAT_INDEX = None
    dp._CHAMP_INFO = None
    ft._GOLD_MAP = None
    rp._RECIPE = None
    sit._CATALOG = None
    aap.reset_cache()
    pbw.reset_cache()
    mmi._reset_caches()
    vt.reload_regions()
    lsp._BUILD_ORDERS_CACHE.clear()
    lsp._CACHE.clear()
    nbf.reset_cache()
    bop._CACHE.clear()
    bov._CACHE.clear()
    pbt._CACHE.clear()
    for mod in (dsc, cms, eas, dp, ft, rp, sit, aap, pbw, mmi, vt, lsp, nbf,
                bop, bov, pbt):
        for name in dir(mod):
            obj = getattr(mod, name)
            if name.endswith("_GATE") and callable(getattr(obj, "reset", None)):
                obj.reset()
            elif name.endswith("_GATES") and isinstance(obj, dict):
                obj.clear()


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


@pytest.mark.parametrize("site", SITES, ids=_IDS)
def test_failed_load_is_not_cached_and_a_later_call_recovers(
    site, tmp_path, monkeypatch, clock,
):
    target = site.point(tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")

    first = site.call()
    assert site.is_fallback(first), f"failed load returned {first!r}"
    assert site.is_uncached(), "a failed load must not be written into the cache"

    target.write_text(site.good_text, encoding="utf-8")
    clock.advance(_PAST_BACKOFF)
    second = site.call()
    assert site.is_good(second), f"recovered load returned {second!r}"


@pytest.mark.parametrize("site", SITES, ids=_IDS)
def test_successful_load_is_cached(site, tmp_path, monkeypatch, clock, reads):
    target = site.point(tmp_path, monkeypatch)
    target.write_text(site.good_text, encoding="utf-8")

    assert site.is_good(site.call())
    assert reads.get(str(target), 0) == 1

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
    site.call()  # inside the backoff window: no second disk read
    assert reads.get(str(target), 0) == 1

    clock.advance(_PAST_BACKOFF)
    site.call()
    assert reads.get(str(target), 0) == 2, "the failed load was not retried"

    assert len(_warnings(caplog, site.logger_name)) == 1, [
        r.getMessage() for r in _warnings(caplog, site.logger_name)
    ]


def test_invalidate_clears_a_backoff(tmp_path, monkeypatch, clock):
    """An existing reset helper must also end a backoff window."""
    target = _point_attr(cms, "_CHAMPS_PATH")(tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")
    assert cms._champ_index() == {}
    target.write_text(_CHAMPS, encoding="utf-8")
    cms._reset_caches()
    assert cms._champ_index().get("wukong") == 340.0


def test_missing_staleness_report_is_a_cached_legitimate_empty(
    tmp_path, monkeypatch, clock,
):
    """ability_staleness.json is the optional output of a separate wiki check:
    ABSENCE is a normal state (not evidence of staleness), so it stays cached.
    Only an unreadable / malformed report, or a missing patch pointer, is a
    failure."""
    target = _point_ds_dir(dsc, "ability_staleness.json", "_DS_DATA_DIR")(
        tmp_path, monkeypatch)
    assert not target.exists()
    assert dsc._champion_is_stale("Lux") is False
    assert dsc._champ_stale_index == {}


def test_ds_snapshot_reset_clears_a_backoff(tmp_path, monkeypatch, clock):
    """The snapshot-index reset seam drops the indexes AND their gates, so a
    reset issued inside a backoff window reloads at once."""
    target = _point_ds_dir(dsc, "champions.json", "_DS_DATA_DIR")(
        tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")
    assert dsc.champion_attackrange("Lux") == 0.0
    target.write_text(
        json.dumps({"data": {"Lux": {"name": "Lux", "stats": {"attackrange": 550}}}}),
        encoding="utf-8")
    dsc.reset_snapshot_indexes()
    assert dsc.champion_attackrange("Lux") == 550.0


def test_missing_regions_file_still_caches_and_seeds_defaults(
    tmp_path, monkeypatch, clock,
):
    """An ABSENT vision_regions.json is the fresh-install state, not a failure:
    the defaults are cached and written out, exactly as before."""
    target = _point_vt(tmp_path, monkeypatch)
    assert vt._regions() == vt._DEFAULT_REGIONS
    assert vt._REGIONS_CACHE == vt._DEFAULT_REGIONS
    assert target.exists()


# -- mtime-keyed loaders ------------------------------------------------------

@dataclass(frozen=True)
class MtimeSite:
    id: str
    module: Any
    target: Callable[[], Path]
    call: Callable[[], Any]


MTIME_SITES = [
    MtimeSite("build_order_precompute.load_build_order_precompute", bop,
              lambda: bop._db_path("sr", _PATCH),
              lambda: bop.load_build_order_precompute("sr", _PATCH)),
    MtimeSite("build_order_variants.load_build_order_variants", bov,
              lambda: bov._db_path("sr", _PATCH),
              lambda: bov.load_build_order_variants("sr", _PATCH)),
    MtimeSite("laning_scenario_precompute.load_laning_scenarios", lsp,
              lambda: lsp._db_path("sr", _PATCH),
              lambda: lsp.load_laning_scenarios("sr", _PATCH)),
    MtimeSite("pickban_targets.load_pickban_targets", pbt,
              lambda: pbt._db_path(_PATCH),
              lambda: pbt.load_pickban_targets("sr", _PATCH)),
]
_MTIME_IDS = [s.id for s in MTIME_SITES]
_PAYLOAD = {"schema": 1, "rows": {"Lux": ["3089"]}}


def _mtime_target(site: MtimeSite, tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    mp.setattr(site.module, "_DS_DIR", tmp_path / "daemon_slayer")
    target = site.target()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@pytest.mark.parametrize("site", MTIME_SITES, ids=_MTIME_IDS)
def test_mtime_transient_read_error_is_not_cached(site, tmp_path, monkeypatch):
    target = _mtime_target(site, tmp_path, monkeypatch)
    target.write_text(json.dumps(_PAYLOAD), encoding="utf-8")

    real = Path.read_text
    state = {"fail": True}

    def flaky(self, *a, **kw):
        if str(self) == str(target) and state["fail"]:
            state["fail"] = False
            raise PermissionError(32, "sharing violation", str(self))
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert site.call() == {}
    # The file did NOT change: only a non-cached failure can recover here.
    assert site.call() == _PAYLOAD


@pytest.mark.parametrize("site", MTIME_SITES, ids=_MTIME_IDS)
def test_mtime_malformed_file_stays_cached_at_unchanged_mtime(
    site, tmp_path, monkeypatch, reads,
):
    target = _mtime_target(site, tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")
    assert site.call() == {}
    assert site.call() == {}
    assert reads.get(str(target), 0) == 1


@pytest.mark.parametrize("site", MTIME_SITES, ids=_MTIME_IDS)
def test_mtime_success_is_cached(site, tmp_path, monkeypatch, reads):
    target = _mtime_target(site, tmp_path, monkeypatch)
    target.write_text(json.dumps(_PAYLOAD), encoding="utf-8")
    assert site.call() == _PAYLOAD
    assert site.call() == _PAYLOAD
    assert reads.get(str(target), 0) == 1
