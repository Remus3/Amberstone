"""RM-1039 true-audit: the DS-data loaders in dashboard/_deterministic_coaching.py.

Scope: ``_load_build_orders``, ``_load_item_costs`` and ``_legendary_catalog``
(the completed-legendary catalog that drives item-spike callouts here and RM-604
``item_completed`` in core/live_event_deriver.py). Findings pinned:

  F1  ``_legendary_catalog`` and ``_load_build_orders`` memoised a FAILED or
      EMPTY load (no patch in current.txt yet, an unreadable items.json) for
      the whole process lifetime, so item spikes, item_completed and the recall
      callout stayed dark until an RC restart even after the data appeared.
      Contract now (core/failed_load_gate.py, RM-439 shape): a failed / empty
      load is not cached, the disk is not touched again inside the backoff
      window, the next attempt after it heals, a success is cached, and the
      failure warns once per streak.
  F2  A wrong-shaped file (top level or ``data`` / ``build_orders`` not an
      object) raised AttributeError out of the loader, which voided the WHOLE
      deterministic resolver (choices, callouts and lead all empty), not just
      the one item surface. Now: fail-soft empty.
  F3  A non-finite gold total (NaN / Infinity, which json.loads accepts) made
      ``_load_item_costs`` abort mid-loop (ValueError) or raise (OverflowError),
      and the half-filled table was served from then on; NaN also cleared the
      legendary gold floor. Now: that one item is skipped.
  F4  A non-list ``tags`` field holding unhashable values raised TypeError out
      of ``_legendary_catalog``. Now: only string tags are read.

The clock is advanced by patching ``time.monotonic`` (the gate looks it up per
call). Hermetic: every case points ``_DS_DATA`` at tmp_path.
"""
from __future__ import annotations

import json
import logging
import time

import pytest

import dashboard._deterministic_coaching as dc
from core.failed_load_gate import FailedLoadGate

_PATCH = "99.1.1"
_LOGGER = "dashboard._deterministic_coaching"


def _item(name, total, *, tags=None, into=None, purchasable=True):
    it = {"name": name, "gold": {"total": total, "purchasable": purchasable},
          "tags": ["Damage"] if tags is None else tags}
    if into is not None:
        it["into"] = into
    return it


_GOOD_ITEMS = {
    "3078": _item("Trinity Force", 3333),
    "3006": _item("Berserker's Greaves", 1100, tags=["Boots"]),
    "1036": _item("Long Sword", 350, into=["3078"]),
}


@pytest.fixture
def ds(tmp_path, monkeypatch):
    """Point the loaders at an empty DS data dir with fresh caches and gates."""
    saved_orders = dict(dc._BUILD_ORDERS_CACHE)
    saved_costs = dict(dc._ITEM_COST_CACHE)
    dc._BUILD_ORDERS_CACHE.clear()
    dc._ITEM_COST_CACHE.clear()
    monkeypatch.setattr(dc, "_DS_DATA", tmp_path)
    monkeypatch.setattr(dc, "_LEGENDARY_CATALOG_CACHE", None)
    for name in ("_ITEM_COST_GATE", "_LEGENDARY_CATALOG_GATE"):
        if hasattr(dc, name):
            monkeypatch.setattr(dc, name, FailedLoadGate())
    if hasattr(dc, "_BUILD_ORDERS_GATES"):
        monkeypatch.setattr(dc, "_BUILD_ORDERS_GATES", {})
    yield tmp_path
    dc._BUILD_ORDERS_CACHE.clear()
    dc._BUILD_ORDERS_CACHE.update(saved_orders)
    dc._ITEM_COST_CACHE.clear()
    dc._ITEM_COST_CACHE.update(saved_costs)


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


def _write_patch(root, patch=_PATCH):
    (root / "current.txt").write_text(patch + "\n", encoding="utf-8")
    (root / patch).mkdir(exist_ok=True)


def _write_items(root, data, patch=_PATCH):
    _write_patch(root, patch)
    (root / patch / "items.json").write_text(json.dumps(data), encoding="utf-8")


def _write_raw(root, name, text, patch=_PATCH):
    _write_patch(root, patch)
    (root / patch / name).write_text(text, encoding="utf-8")


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == _LOGGER and r.levelno >= logging.WARNING]


# ---------------------------------------------------------------- F1 catalog

def test_legendary_catalog_failed_load_is_not_memoised(ds, clock):
    # Cold start: no current.txt yet -> nothing completed.
    assert dc._legendary_catalog() == (frozenset(), frozenset())
    _write_items(ds, {"data": _GOOD_ITEMS})
    clock[0] += 60.0
    ids, names = dc._legendary_catalog()
    assert ids == frozenset({"3078"})
    assert names == frozenset({"trinity force"})


def test_legendary_catalog_empty_catalog_is_not_memoised(ds, clock):
    # A readable items.json that yields NO completed legendary is not a catalog.
    _write_items(ds, {"data": {"3006": _GOOD_ITEMS["3006"]}})
    assert dc._legendary_catalog() == (frozenset(), frozenset())
    _write_items(ds, {"data": _GOOD_ITEMS})
    clock[0] += 60.0
    assert dc._legendary_catalog()[0] == frozenset({"3078"})


def test_legendary_catalog_backs_off_inside_the_window(ds, clock):
    assert dc._legendary_catalog()[0] == frozenset()
    _write_items(ds, {"data": _GOOD_ITEMS})
    # Still inside the backoff window: the disk is not re-read yet.
    assert dc._legendary_catalog()[0] == frozenset()
    clock[0] += 60.0
    assert dc._legendary_catalog()[0] == frozenset({"3078"})


def test_legendary_catalog_success_is_cached(ds, clock):
    _write_items(ds, {"data": _GOOD_ITEMS})
    assert dc._legendary_catalog()[0] == frozenset({"3078"})
    (ds / _PATCH / "items.json").unlink()
    clock[0] += 60.0
    assert dc._legendary_catalog()[0] == frozenset({"3078"})


def test_legendary_catalog_failure_warns_once_per_streak(ds, clock, caplog):
    caplog.set_level(logging.DEBUG)
    dc._legendary_catalog()
    clock[0] += 60.0
    dc._legendary_catalog()
    assert len(_warnings(caplog)) == 1, [r.getMessage() for r in _warnings(caplog)]


def test_blank_patch_never_reads_a_root_level_file(ds):
    # current.txt present but blank: the loaders must not fall through to
    # <ds>/items.json or <ds>/build_orders_sr.json (an empty patch segment).
    (ds / "current.txt").write_text("\n", encoding="utf-8")
    (ds / "items.json").write_text(json.dumps({"data": _GOOD_ITEMS}), encoding="utf-8")
    (ds / "build_orders_sr.json").write_text(
        json.dumps({"build_orders": {"Aatrox": {"balanced": ["3078"]}}}), encoding="utf-8")
    assert dc._legendary_catalog() == (frozenset(), frozenset())
    assert dc._load_item_costs() == {}
    assert dc._load_build_orders("sr") == {}


# ---------------------------------------------------------------- F2 shapes

@pytest.mark.parametrize("text", ['[1, 2]', '{"data": [1, 2]}', '"x"', '{"data": 7}'])
def test_legendary_catalog_wrong_shape_is_fail_soft(ds, text):
    _write_raw(ds, "items.json", text)
    assert dc._legendary_catalog() == (frozenset(), frozenset())


@pytest.mark.parametrize("text", ['[1, 2]', '{"data": [1, 2]}', '"x"'])
def test_item_costs_wrong_shape_is_fail_soft(ds, text):
    _write_raw(ds, "items.json", text)
    assert dc._load_item_costs() == {}


@pytest.mark.parametrize("text", ['[1, 2]', '{"build_orders": [1, 2]}', '"x"',
                                  '{"build_orders": {}}'])
def test_build_orders_wrong_shape_is_fail_soft(ds, text):
    _write_raw(ds, "build_orders_sr.json", text)
    assert dc._load_build_orders("sr") == {}


def test_owned_legendary_count_survives_a_wrong_shaped_catalog(ds):
    _write_raw(ds, "items.json", '{"data": [1, 2]}')
    assert dc._owned_legendary_count(["3078"], None) == 0


def test_next_build_item_survives_a_list_build_orders(ds):
    _write_items(ds, {"data": _GOOD_ITEMS})
    _write_raw(ds, "build_orders_sr.json", '{"build_orders": ["Aatrox"]}')
    assert dc._next_build_item("Aatrox", "sr", 0) is None


# ---------------------------------------------------------------- F1 orders

def test_build_orders_failed_load_is_not_memoised(ds, clock):
    assert dc._load_build_orders("sr") == {}
    _write_raw(ds, "build_orders_sr.json",
               json.dumps({"build_orders": {"Aatrox": {"balanced": ["3078"]}}}))
    clock[0] += 60.0
    assert dc._load_build_orders("sr") == {"Aatrox": {"balanced": ["3078"]}}


def test_build_orders_empty_table_is_not_memoised(ds, clock):
    _write_raw(ds, "build_orders_sr.json", '{"build_orders": {}}')
    assert dc._load_build_orders("sr") == {}
    _write_raw(ds, "build_orders_sr.json",
               json.dumps({"build_orders": {"Aatrox": {"balanced": ["3078"]}}}))
    clock[0] += 60.0
    assert dc._load_build_orders("sr") == {"Aatrox": {"balanced": ["3078"]}}


def test_build_orders_backs_off_inside_the_window(ds, clock):
    assert dc._load_build_orders("sr") == {}
    _write_raw(ds, "build_orders_sr.json",
               json.dumps({"build_orders": {"Aatrox": {"balanced": ["3078"]}}}))
    assert dc._load_build_orders("sr") == {}
    clock[0] += 60.0
    assert dc._load_build_orders("sr") == {"Aatrox": {"balanced": ["3078"]}}


def test_build_orders_gate_is_per_mode(ds, clock):
    _write_raw(ds, "build_orders_sr.json",
               json.dumps({"build_orders": {"Aatrox": {"balanced": ["3078"]}}}))
    assert dc._load_build_orders("arena") == {}
    # A failing arena table never backs off the SR one.
    assert dc._load_build_orders("sr") == {"Aatrox": {"balanced": ["3078"]}}


def test_build_orders_success_is_cached(ds, clock):
    _write_raw(ds, "build_orders_sr.json",
               json.dumps({"build_orders": {"Aatrox": {"balanced": ["3078"]}}}))
    assert dc._load_build_orders("sr")
    (ds / _PATCH / "build_orders_sr.json").unlink()
    clock[0] += 60.0
    assert dc._load_build_orders("sr") == {"Aatrox": {"balanced": ["3078"]}}


# ---------------------------------------------------------------- costs

def test_item_costs_failed_load_heals_after_backoff(ds, clock):
    assert dc._load_item_costs() == {}
    _write_items(ds, {"data": _GOOD_ITEMS})
    clock[0] += 60.0
    assert dc._load_item_costs()["3078"] == ("Trinity Force", 3333)


def test_item_costs_backs_off_inside_the_window(ds, clock):
    assert dc._load_item_costs() == {}
    _write_items(ds, {"data": _GOOD_ITEMS})
    assert dc._load_item_costs() == {}
    clock[0] += 60.0
    assert "3078" in dc._load_item_costs()


def test_item_costs_empty_table_backs_off(ds, clock):
    # A readable items.json with no priced item is a failed load: backed off.
    _write_items(ds, {"data": {"1": {"name": "No Gold"}}})
    assert dc._load_item_costs() == {}
    _write_items(ds, {"data": _GOOD_ITEMS})
    assert dc._load_item_costs() == {}
    clock[0] += 60.0
    assert "3078" in dc._load_item_costs()


# ---------------------------------------------------------------- F3 non-finite

@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_item_costs_skip_only_a_non_finite_total(ds, bad):
    text = ('{"data": {"1001": {"name": "Boots", "gold": {"total": 300}}, '
            '"6666": {"name": "Bad", "gold": {"total": ' + bad + '}}, '
            '"3078": {"name": "Trinity Force", "gold": {"total": 3333}}}}')
    _write_raw(ds, "items.json", text)
    costs = dc._load_item_costs()
    assert "6666" not in costs
    assert costs["1001"] == ("Boots", 300)
    assert costs["3078"] == ("Trinity Force", 3333)


def test_legendary_catalog_rejects_a_nan_total(ds):
    text = ('{"data": {"6666": {"name": "Bad", "tags": [], '
            '"gold": {"total": NaN, "purchasable": true}}, '
            '"3078": {"name": "Trinity Force", "tags": [], '
            '"gold": {"total": 3333, "purchasable": true}}}}')
    _write_raw(ds, "items.json", text)
    assert dc._legendary_catalog()[0] == frozenset({"3078"})


# ---------------------------------------------------------------- F4 tags

def test_legendary_catalog_unhashable_tags_do_not_raise(ds):
    data = dict(_GOOD_ITEMS)
    data["4444"] = _item("Odd Tags", 3000, tags=[{"x": 1}, ["y"]])
    data["5555"] = _item("Scalar Tags", 3000, tags=7)
    _write_items(ds, {"data": data})
    ids = dc._legendary_catalog()[0]
    assert {"3078", "4444", "5555"} <= ids
    assert "3006" not in ids  # Boots still excluded by its string tag
