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

CENSUS (re-derived 2026-09-16 against base 6c42caf48; line = the ``def`` line
there, EXCEPT the rows in the five modules RM-450 edited - augment_external_source,
augment_recommender, minimap_identity, replay_history, vision_template_match -
whose lines were re-derived after RM-450). Instrument: an AST scan over core/ for functions that write a
module-level cache name either (A) inside / after a try-except whose handler
does not exit, or (B) from the return value of a same-module function that
holds a non-raising handler. One row per function; A-or-B hits = 57, plus
three rows the scan cannot see (riot_api, cited by the filed row;
log_retention.start and vision_routing.read_or_escalate, raised by review) =
60 rows. An empty scan is a claim about the pattern: pass B was added after a
verifier found three sites pass A missed (load_grid, load_own_history's scan,
_atlas), and a re-verifier then showed a pass B hit (match_detail) had been
mis-classed BENIGN - the helper swallowing the failure was one call away.

  file:line | function | class | reason
  core/anvil_shadow.py:94 | log_anvil_advice | NOT-A-LOADER | dedupe signature
  core/aram_item_interaction_context.py:235 | _get_index | BENIGN | gated by RM-439
  core/archetype_picks.py:628 | save_archetype_pick | FIXED-ELSEWHERE | re-read failure wrote {}+entry over the file; fixed by RM-444
  core/archetype_picks.py:754 | clear_archetype_pick | BENIGN | re-read failure returns False, nothing cached or written
  core/arena_augment_playline.py:106 | _rows | DEFECT-FIXED | gate (+ _load_index projection)
  core/augment_external_source.py:429 | get_priors | DEFECT-FIXED | RM-450: network failure served degraded, retried once per 300 s window (vs 15 s HTTP timeout)
  core/augment_external_source.py:713 | get_augment_meta | DEFECT-FIXED | RM-450: same shape and window as get_priors
  core/augment_recommender.py:248 | load_own_history | DEFECT-FIXED | locked-db scan cached under an unchanged key; per-mode gate; RM-450 row-count memo refuted twice and removed (per-call count cost is a follow-up)
  core/augment_shadow.py:99 | log_augment_advice | NOT-A-LOADER | dedupe signature
  core/build_order_precompute.py:732 | load_build_order_precompute | DEFECT-FIXED | OSError under unchanged mtime no longer cached
  core/build_order_variants.py:464 | load_build_order_variants | DEFECT-FIXED | OSError under unchanged mtime no longer cached
  core/build_planner/fed_threat.py:70 | _load_gold_map | DEFECT-FIXED | gate
  core/build_planner/kit_synergy.py:399 | _alias_index | BENIGN | projection of the cached catalog (RM-439 reviewed)
  core/build_planner/replan.py:76 | _load_recipe | DEFECT-FIXED | gate (was silent)
  core/build_planner/situational.py:92 | _load_catalog | DEFECT-FIXED | gate (was silent)
  core/champ_select_shadow.py:54 | log_champ_select_advice | NOT-A-LOADER | dedupe signature
  core/champion_movespeed.py:103 | _champ_index | DEFECT-FIXED | gate
  core/champion_movespeed.py:130 | _item_index | DEFECT-FIXED | gate
  core/coaching_data_lock.py:216 | _note_file_lock_failure | NOT-A-LOADER | lock-episode bookkeeping
  core/daemon_slayer_client.py:2165 | champion_attackrange | DEFECT-FIXED | gate
  core/daemon_slayer_client.py:2200 | champion_has_ability_data | DEFECT-FIXED | gate
  core/daemon_slayer_client.py:2250 | _champion_is_stale | DEFECT-FIXED | gate; absent report stays cached
  core/daemon_slayer_resolver.py:267 | _load_hp_if_stale | BENIGN | failure returns before the cache write; mtime reload
  core/defensive_picks.py:61 | _load_champ_info | DEFECT-FIXED | gate
  core/det_coach_shadow.py:35 | log_det_coaching | NOT-A-LOADER | dedupe signature
  core/ds_onhit_ap_roster.py:67 | load_onhit_ap_roster | BENIGN | gated by RM-439
  core/enemy_aware_stats.py:84 | _load_champ_index | DEFECT-FIXED | gate
  core/enemy_aware_stats.py:144 | _load_stat_index | DEFECT-FIXED | gate
  core/hz_build_shadow.py:38 | log_precomputed_build | NOT-A-LOADER | dedupe signature
  core/hz_choice_shadow.py:119 | log_precomputed_choices | NOT-A-LOADER | dedupe signature
  core/laning_scenario_precompute.py:352 | load_build_orders | DEFECT-FIXED | per-mode gate
  core/laning_scenario_precompute.py:1004 | load_laning_scenarios | DEFECT-FIXED | OSError under unchanged mtime no longer cached
  core/live_benchmark_band_shadow.py:50 | log_live_bands | NOT-A-LOADER | dedupe signature
  core/live_metrics.py:63 | _resolve_streamer | BENIGN | import failure is deterministic in-process
  core/liveclient_cache.py:229 | _loop | NOT-A-LOADER | poll loop snapshot
  core/liveclient_cache.py:301 | start | NOT-A-LOADER | task handle
  core/liveclient_cache.py:331 | stop | NOT-A-LOADER | task handle
  core/log_retention.py:305 | start | NOT-A-LOADER | worker/task handle (not a scan hit)
  core/log_retention.py:354 | stop | NOT-A-LOADER | task handle
  core/log_setup.py:110 | setup | NOT-A-LOADER | configured flag (frozen file)
  core/macro_response_shadow.py:40 | log_macro_response | NOT-A-LOADER | dedupe signature
  core/minimap_blob_detect.py:394 | _compute_and_cache_dots | NOT-A-LOADER | per-frame compute cache
  core/minimap_districts.py:225 | load_grid | DEFECT-FIXED | existing-file read error cached the embedded grid; per-key gate
  core/minimap_identity.py:129 | _icon_index | DEFECT-FIXED | partial build not cached; no rescan inside backoff; RM-450 per-icon gate on _masked_template
  core/next_buy_fallback.py:138 | _canon_table | DEFECT-FIXED | caches only a non-empty table
  core/objective_playbook_shadow.py:39 | log_objective_playbook | NOT-A-LOADER | dedupe signature
  core/obs_frame_source.py:54 | _get_obs_cfg | BENIGN | 5 s TTL retry
  core/personal_build_wr.py:60 | _item_meta | DEFECT-FIXED | gate (was silent)
  core/pickban_targets.py:73 | load_pickban_targets | DEFECT-FIXED | OSError under unchanged mtime no longer cached
  core/rank_tier_bench.py:200 | _refresh_now | BENIGN | keeps the prior grid; TTL retry
  core/rank_tier_source.py:345 | fetch_rows | BENIGN | negative cache expires
  core/replay_history.py:284 | match_detail | DEFECT-FIXED | cached a result built after _load_champ_index swallowed a read failure; per-path gate; RM-450 non-object / empty index is a failure
  core/replay_narrative_shadow.py:37 | log_replay_narrative | NOT-A-LOADER | dedupe signature
  core/riot_api.py:73 | _get_api_key | BENIGN | failures return uncached (not a scan hit)
  core/vision_routing.py:50 | read_or_escalate | NOT-A-LOADER | warn-once dropped-key signature set (not a scan hit)
  core/vision_template_match.py:137 | _atlas | DEFECT-FIXED | folder-scan failure per-category gate; absent opencv stays cached; RM-450 missing / empty folder is a failure
  core/vision_template_match.py:188 | _index | DEFECT-FIXED | caches only a projection of a loaded atlas
  core/vision_tesseract.py:69 | _regions | DEFECT-FIXED | legacy-file read error; absent file still cached
  core/vision_tesseract.py:627 | read_fast_fields | NOT-A-LOADER | per-tick OCR slow-field cache
  core/ward_producer.py:243 | tick | NOT-A-LOADER | per-tick diff state

  TOTALS: DEFECT-FIXED 28 | DEFECT-UNFIXED 0 | FIXED-ELSEWHERE 1 | BENIGN 10 | NOT-A-LOADER 21 | rows 60

RM-450 (2026-09-16) closed the two DEFECT-UNFIXED rows and three residuals on
DEFECT-FIXED rows; its pins live in tests/test_rm450_core_residuals.py.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

import sqlite3
import sys

import core.arena_augment_playline as aap
import core.augment_recommender as ar
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
import core.minimap_districts as md
import core.minimap_identity as mmi
import core.next_buy_fallback as nbf
import core.personal_build_wr as pbw
import core.pickban_targets as pbt
import core.replay_history as rh
import core.vision_profiles as vprof
import core.vision_template_match as vtm
import core.vision_tesseract as vt
from core.failed_load_gate import FailedLoadGate

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


_SR_GRID_TEXT = (Path(md.__file__).resolve().parent.parent / "config"
                 / "minimap_grids" / "sr.json").read_text(encoding="utf-8")


def _point_md(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    grids = tmp_path / "minimap_grids"
    grids.mkdir()
    mp.setattr(md, "_CONFIG_DIR", grids)
    return grids / "sr.json"


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
    Site("minimap_districts.load_grid", "rc.minimap_districts",
         _point_md, lambda: md.load_grid("sr"),
         _SR_GRID_TEXT,
         lambda r: r is not None and len(r.districts) == 13,
         lambda r: r is not None and [d.id for d in r.districts] == ["sr_map"],
         lambda: not md._CACHE),
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


_ALL_MODULES = (dsc, cms, eas, dp, ft, rp, sit, aap, pbw, mmi, vt, lsp, nbf,
                bop, bov, pbt, md, vtm, ar, rh)


def _drop_caches_keep_gates() -> None:
    """Drop every cache under test by BARE assignment, leaving any failure gate
    exactly as it is (the streak-reset test needs that distinction)."""
    dsc._champ_attackrange_index = None
    dsc._champ_ability_index = None
    dsc._champ_stale_index = None
    cms._CHAMP_MS = None
    cms._ITEM_MS = None
    eas._CHAMP_INDEX = None
    eas._STAT_INDEX = None
    dp._CHAMP_INFO = None
    ft._GOLD_MAP = None
    rp._RECIPE = None
    sit._CATALOG = None
    aap._ROWS_CACHE = None
    aap._INDEX_CACHE = None
    pbw._META_CACHE = None
    mmi._ICON_INDEX = None
    mmi._PARTIAL_ICON_INDEX = {}
    mmi._TPL_CACHE.clear()
    vt._REGIONS_CACHE = None
    vt._BASE_CACHE = (vt.BASE_W, vt.BASE_H)
    lsp._BUILD_ORDERS_CACHE.clear()
    lsp._CACHE.clear()
    nbf._CANON_CACHE.clear()
    nbf._ID_TO_NAME_CACHE.clear()
    bop._CACHE.clear()
    bov._CACHE.clear()
    pbt._CACHE.clear()
    md._CACHE.clear()
    vtm._ATLAS_CACHE.clear()
    vtm._INDEX_CACHE.clear()
    vtm._TPL_CACHE.clear()
    ar._own_cache.clear()
    ar._own_cache_key.clear()
    rh._MATCH_DETAIL_CACHE.clear()
    rh._id_to_champ.clear()


def _reset_all() -> None:
    """Drop every cache under test plus EVERY failure gate. Gates are found by
    TYPE, not by a name suffix (a suffix rule missed ``_own_gates`` and let a
    backoff leak between tests): a module-level FailedLoadGate is reset and a
    module-level dict holding gates is cleared."""
    _drop_caches_keep_gates()
    for mod in _ALL_MODULES:
        for obj in list(vars(mod).values()):
            if isinstance(obj, FailedLoadGate):
                obj.reset()
            elif isinstance(obj, dict) and any(
                isinstance(v, FailedLoadGate) for v in list(obj.values())
            ):
                obj.clear()


def test_reset_all_finds_every_gate():
    """Guard for the reset itself: after _reset_all no module under test holds
    a gate in a failure streak or a non-empty gate dict."""
    for mod in _ALL_MODULES:
        for obj in list(vars(mod).values()):
            if isinstance(obj, FailedLoadGate):
                obj.record_failure()
    ar._own_gates["probe"] = FailedLoadGate()
    ar._own_gates["probe"].record_failure()
    _reset_all()
    for mod in _ALL_MODULES:
        for name, obj in vars(mod).items():
            if isinstance(obj, FailedLoadGate):
                assert obj.should_attempt(), f"{mod.__name__}.{name}"
            elif isinstance(obj, dict):
                assert not any(isinstance(v, FailedLoadGate)
                               for v in obj.values()), f"{mod.__name__}.{name}"


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


@pytest.mark.parametrize("site", SITES, ids=_IDS)
def test_success_ends_the_failure_streak(
    site, tmp_path, monkeypatch, clock, caplog,
):
    """A success must END the streak (record_success): after the cache is
    dropped by bare assignment, a NEW failure is attempted at once (no stale
    backoff) and warns again."""
    target = site.point(tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")
    caplog.set_level(logging.DEBUG)

    site.call()
    clock.advance(_PAST_BACKOFF)
    target.write_text(site.good_text, encoding="utf-8")
    assert site.is_good(site.call())

    _drop_caches_keep_gates()
    target.write_text(_BAD, encoding="utf-8")
    assert site.is_fallback(site.call())  # no clock advance
    assert len(_warnings(caplog, site.logger_name)) == 2, [
        r.getMessage() for r in _warnings(caplog, site.logger_name)
    ]


def test_icon_dir_scan_waits_out_the_backoff(tmp_path, monkeypatch, clock):
    """minimap_identity: inside the backoff after a failed DDragon read the
    icon folder is NOT rescanned per call; the partial index still serves."""
    target = _point_mmi(tmp_path, monkeypatch)
    target.write_text(_BAD, encoding="utf-8")
    icons = str(mmi._ICON_DIR)
    globs = {"n": 0}
    real_glob = Path.glob

    def counting_glob(self, *a, **kw):
        if str(self) == icons:
            globs["n"] += 1
        return real_glob(self, *a, **kw)

    monkeypatch.setattr(Path, "glob", counting_glob)
    assert "monkeyking" in mmi._icon_index()
    assert "monkeyking" in mmi._icon_index()
    assert globs["n"] == 1
    clock.advance(_PAST_BACKOFF)
    mmi._icon_index()
    assert globs["n"] == 2


def test_missing_grid_file_is_a_cached_embedded_fallback(tmp_path, monkeypatch):
    """No grid file is the documented degrade-to-embedded state - cached."""
    _point_md(tmp_path, monkeypatch)
    grid = md.load_grid("sr")
    assert [d.id for d in grid.districts] == ["sr_map"]
    assert ("sr", str(md._CONFIG_DIR)) in md._CACHE


# -- vision_template_match atlas ---------------------------------------------

class _FakeCv2:
    IMREAD_COLOR = 1
    COLOR_BGR2RGB = 4

    @staticmethod
    def imread(path, flag):
        return "img:" + Path(path).stem

    @staticmethod
    def cvtColor(img, code):
        return img


class _FlakyDir:
    """A category dir whose glob raises while ``fail`` is set."""

    def __init__(self, real: Path) -> None:
        self.real = real
        self.fail = True
        self.calls = 0

    def is_dir(self):
        return self.real.is_dir()

    def glob(self, pattern):
        self.calls += 1
        if self.fail:
            raise OSError("icon folder unavailable")
        return self.real.glob(pattern)


def _flaky_items_dir(tmp_path, monkeypatch) -> _FlakyDir:
    real = tmp_path / "items"
    real.mkdir()
    (real / "Thornmail.png").write_bytes(b"")
    flaky = _FlakyDir(real)
    monkeypatch.setitem(sys.modules, "cv2", _FakeCv2)
    monkeypatch.setitem(vtm._CATEGORY_DIRS, "items", flaky)
    return flaky


def test_atlas_scan_failure_is_not_cached_and_recovers(
    tmp_path, monkeypatch, clock, caplog,
):
    flaky = _flaky_items_dir(tmp_path, monkeypatch)
    caplog.set_level(logging.DEBUG)

    assert vtm._atlas("items") == {}
    assert "items" not in vtm._ATLAS_CACHE
    assert vtm._index("items") == {}
    assert "items" not in vtm._INDEX_CACHE
    assert flaky.calls == 1, "inside the backoff the folder is not rescanned"

    flaky.fail = False
    clock.advance(_PAST_BACKOFF)
    assert vtm._atlas("items") == {"Thornmail": "img:Thornmail"}
    assert "thornmail" in vtm._index("items")
    assert "items" in vtm._ATLAS_CACHE and "items" in vtm._INDEX_CACHE
    assert len(_warnings(caplog, vtm._log.name)) == 1


def test_atlas_without_opencv_stays_a_cached_empty(monkeypatch):
    """opencv is an optional dependency: its absence is permanent, cached."""
    monkeypatch.setitem(sys.modules, "cv2", None)
    assert vtm._atlas("items") == {}
    assert vtm._ATLAS_CACHE.get("items") == {}


# -- augment_recommender own history -------------------------------------------

def _history_db(tmp_path: Path) -> Path:
    db = tmp_path / "match_history.db"
    raw = json.dumps({"tracked_puuid": "P", "lcu_match_detail": {
        "gameMode": "KIWI", "queueId": 2400,
        "participantIdentities": [{"participantId": 1, "player": {"puuid": "P"}}],
        "participants": [{"participantId": 1,
                          "stats": {"playerAugment1": 101, "win": True}}],
    }})
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE matches (raw_data TEXT)")
    conn.execute("INSERT INTO matches VALUES (?)", (raw,))
    conn.commit()
    conn.close()
    return db


class _FlakyConn:
    def __init__(self, real, state) -> None:
        self._real = real
        self._state = state

    def execute(self, sql, *a):
        if sql.startswith("SELECT raw_data") and self._state["fail"]:
            self._state["calls"] += 1
            raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, *a)

    def close(self) -> None:
        self._real.close()


def _flaky_connect(monkeypatch) -> dict:
    state = {"fail": True, "calls": 0}
    real_connect = sqlite3.connect

    def connect(*a, **kw):
        return _FlakyConn(real_connect(*a, **kw), state)

    monkeypatch.setattr(sqlite3, "connect", connect)
    return state


def test_own_history_query_failure_is_not_cached(
    tmp_path, monkeypatch, clock, caplog,
):
    """The DB does not change between calls, so its (mtime, size, row count)
    cache key does not either: a cached failure would stand until the next
    game is ingested."""
    db = _history_db(tmp_path)
    state = _flaky_connect(monkeypatch)
    caplog.set_level(logging.DEBUG)

    assert ar.load_own_history("mayhem", db_path=db).n_matches == 0
    assert "mayhem" not in ar._own_cache
    ar.load_own_history("mayhem", db_path=db)
    assert state["calls"] == 1, "inside the backoff the query is not retried"

    state["fail"] = False
    clock.advance(_PAST_BACKOFF)
    hist = ar.load_own_history("mayhem", db_path=db)
    assert hist.n_matches == 1 and hist.games == {101: 1}
    assert len(_warnings(caplog, ar._log.name)) == 1


def test_own_history_success_and_absent_db_are_cached(tmp_path, monkeypatch):
    db = _history_db(tmp_path)
    assert ar.load_own_history("mayhem", db_path=db).n_matches == 1
    assert "mayhem" in ar._own_cache
    ar.reset_cache()
    assert ar.load_own_history("mayhem", db_path=tmp_path / "absent.db").n_matches == 0
    assert "mayhem" in ar._own_cache


def test_own_history_success_ends_the_failure_streak(
    tmp_path, monkeypatch, clock, caplog,
):
    db = _history_db(tmp_path)
    state = _flaky_connect(monkeypatch)
    caplog.set_level(logging.DEBUG)
    ar.load_own_history("mayhem", db_path=db)
    state["fail"] = False
    clock.advance(_PAST_BACKOFF)
    assert ar.load_own_history("mayhem", db_path=db).n_matches == 1
    _drop_caches_keep_gates()
    state["fail"] = True
    assert ar.load_own_history("mayhem", db_path=db).n_matches == 0  # no advance
    assert len(_warnings(caplog, ar._log.name)) == 2


def test_atlas_success_ends_the_failure_streak(
    tmp_path, monkeypatch, clock, caplog,
):
    flaky = _flaky_items_dir(tmp_path, monkeypatch)
    caplog.set_level(logging.DEBUG)
    vtm._atlas("items")
    flaky.fail = False
    clock.advance(_PAST_BACKOFF)
    assert vtm._atlas("items")
    _drop_caches_keep_gates()
    flaky.fail = True
    assert vtm._atlas("items") == {}  # no advance
    assert len(_warnings(caplog, vtm._log.name)) == 2


@pytest.mark.parametrize("text, why", [
    ("[1, 2]", "not a JSON object"),
    (json.dumps({"districts": [{"bogus": 1}]}), "no usable districts"),
], ids=["not-an-object", "no-usable-districts"])
def test_grid_content_failures_are_not_cached(
    text, why, tmp_path, monkeypatch, clock, caplog,
):
    target = _point_md(tmp_path, monkeypatch)
    target.write_text(text, encoding="utf-8")
    caplog.set_level(logging.DEBUG)
    grid = md.load_grid("sr")
    assert [d.id for d in grid.districts] == ["sr_map"]
    assert not md._CACHE
    msgs = [r.getMessage() for r in _warnings(caplog, "rc.minimap_districts")]
    assert len(msgs) == 1 and why in msgs[0], msgs
    target.write_text(_SR_GRID_TEXT, encoding="utf-8")
    clock.advance(_PAST_BACKOFF)
    assert len(md.load_grid("sr").districts) == 13


def test_grid_no_grid_declaration_stays_cached(tmp_path, monkeypatch):
    target = _point_md(tmp_path, monkeypatch)
    target.write_text(json.dumps({"districts": []}), encoding="utf-8")
    assert md.load_grid("sr") is None
    assert md._CACHE == {("sr", str(md._CONFIG_DIR)): None}


# -- replay_history match_detail ------------------------------------------------

_REWIND_SCHEMA = """
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY, queue_id INTEGER, game_mode TEXT,
    game_duration_s INTEGER, game_creation_ts INTEGER, patch TEXT,
    tracked_champion_id INTEGER);
CREATE TABLE participants (
    match_id TEXT, participant_id INTEGER, team_id INTEGER,
    champion_id INTEGER, champion_name TEXT, riot_id_game_name TEXT,
    summoner_name TEXT, summoner_level INTEGER);
CREATE TABLE teams (match_id TEXT, team_id INTEGER, win INTEGER);
CREATE TABLE timeline_frames (
    match_id TEXT, timestamp_ms INTEGER, participant_id INTEGER,
    level INTEGER, total_gold INTEGER, minions_killed INTEGER,
    jungle_minions INTEGER, pos_x INTEGER, pos_y INTEGER,
    total_dmg_done INTEGER, total_dmg_taken INTEGER);
CREATE TABLE timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
    timestamp_ms INTEGER, event_type TEXT, participant_id INTEGER,
    item_id INTEGER, killer_id INTEGER, victim_id INTEGER,
    assisting_ids_json TEXT, kill_pos_x INTEGER, kill_pos_y INTEGER,
    raw_json TEXT);
"""
_AHRI = json.dumps({"data": {"Ahri": {"key": "103", "name": "Ahri"}}})


def _point_rewind(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "rewind_history.db"
    c = sqlite3.connect(str(db))
    c.executescript(_REWIND_SCHEMA)
    c.execute("INSERT INTO matches VALUES ('M1', 2400, 'KIWI', 1200, 0, "
              "'16.15', 103)")
    c.commit()
    c.close()
    mp.setattr(rh, "_REWIND_DB", db)
    champs = tmp_path / "ddragon_champions.json"
    mp.setattr(rh, "_DDR_CHAMPS", champs)
    return champs


def _tracked_name(detail):
    return (detail or {}).get("tracked", {}).get("champion_name")


def test_match_detail_not_cached_when_champion_index_failed(
    tmp_path, monkeypatch, clock, reads, caplog,
):
    champs = _point_rewind(tmp_path, monkeypatch)
    champs.write_text(_BAD, encoding="utf-8")
    caplog.set_level(logging.DEBUG)

    first = rh.match_detail("M1")
    assert first is not None and _tracked_name(first) is None
    assert not rh._MATCH_DETAIL_CACHE, "a result built from a failed index was cached"
    rh.match_detail("M1")
    assert reads.get(str(champs), 0) == 1, "inside the backoff: no re-read"

    champs.write_text(_AHRI, encoding="utf-8")
    clock.advance(_PAST_BACKOFF)
    assert _tracked_name(rh.match_detail("M1")) == "Ahri"
    assert len(rh._MATCH_DETAIL_CACHE) == 1
    assert len(_warnings(caplog, rh._log.name)) == 1


def test_match_detail_success_is_cached(tmp_path, monkeypatch, clock, reads):
    champs = _point_rewind(tmp_path, monkeypatch)
    champs.write_text(_AHRI, encoding="utf-8")
    assert _tracked_name(rh.match_detail("M1")) == "Ahri"
    assert len(rh._MATCH_DETAIL_CACHE) == 1
    assert _tracked_name(rh.match_detail("M1")) == "Ahri"
    assert reads.get(str(champs), 0) == 1


def test_census_totals_match_its_rows():
    """The census in this module's docstring: the per-class row counts must be
    EXACTLY the recorded ones (not merely self-consistent), the TOTALS line
    must say the same, and every cited file must still exist."""
    import re

    expected = {"DEFECT-FIXED": 28, "DEFECT-UNFIXED": 0, "FIXED-ELSEWHERE": 1,
                "BENIGN": 10, "NOT-A-LOADER": 21}
    rows = [ln.strip() for ln in __doc__.splitlines()
            if re.match(r"\s+core/\S+:\d+ \| ", ln)]
    classes = [r.split(" | ")[2] for r in rows]
    # A zero-count class (DEFECT-UNFIXED since RM-450) has no row, so the
    # vocabulary check is a subset check; the exact counts below still pin it.
    assert set(classes) <= set(expected), set(classes) - set(expected)
    assert {c: classes.count(c) for c in expected} == expected
    totals = dict(re.findall(r"([A-Za-z-]+) (\d+)",
                             __doc__.split("TOTALS:")[1].splitlines()[0]))
    assert {c: int(totals[c]) for c in expected} == expected
    assert len(rows) == int(totals["rows"]) == sum(expected.values()) == 60
    assert len({r.split(" | ")[0] for r in rows}) == len(rows), "duplicate row"
    root = Path(__file__).resolve().parent.parent
    for r in rows:
        assert (root / r.split(":")[0]).is_file(), r


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
