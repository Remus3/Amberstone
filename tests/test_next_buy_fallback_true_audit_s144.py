"""S144-T-739 - true-audit of core/next_buy_fallback.py (the live NEXT BUY
fallback behind dashboard/_liveclient.py).

Findings pinned here, each measured before the fix:

1. A table cell that is not an item id still came out of
   ``fallback_build_ids`` as one: ``True`` -> "True", ``0`` -> "0",
   ``-5`` -> "-5", a dict -> its repr, " 3153 " kept its spaces, so a
   real id with stray whitespace never matched items_index.
2. A lean bucket that is a non-empty list of junk (``[None, False, ""]``)
   was served instead of falling back to "balanced": ``False == 0`` passed
   the ``i or i == 0`` filter, the row became ``["False"]`` and the
   champion's NEXT BUY row vanished.
3. ``_id_to_name`` turned ANY truthy items_index value into a display
   name with ``str(v)``, so a dict or list value rendered its Python repr
   (and a whitespace-only value a blank) as an item name in the overlay.
4. ``preferred_bucket`` iterated whatever it was handed, so a dict roster
   classified its KEYS and a bare string its characters, unlike
   ``compute_factors``' own contract (list / tuple / set only).
5. ``fallback_enabled``'s docstring said only "0" / "false" / "off" turn
   the fallback off; the code also honours "no" and an empty value.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from core import next_buy_fallback as nbf

AD_COMP = ["Zed", "Jinx", "Caitlyn", "Tryndamere", "Garen"]


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.delenv(nbf.FALLBACK_ENV, raising=False)
    nbf.reset_cache()
    yield
    nbf.reset_cache()


def _patch_table(table: dict):
    return mock.patch.object(nbf._lsp, "load_build_orders", return_value=table)


def _patch_items(tmp_path, by_id: dict):
    path = tmp_path / "items_index.json"
    path.write_text(json.dumps({"byId": by_id}), encoding="utf-8")
    return mock.patch.object(nbf, "_ITEMS_INDEX_PATH", path)


# --- finding 1: only real item ids leave fallback_build_ids ---------------

def test_junk_cells_are_dropped_not_stringified():
    table = {"Aatrox": {"balanced": [
        True, False, 0, -5, {"id": 1}, [1], None, "abc", "",
        "3111", 3078, "3153",
    ]}}
    with _patch_table(table):
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC") == [
            "3111", "3078", "3153"]


def test_whitespace_padded_id_is_normalised_so_it_resolves(tmp_path):
    table = {"Aatrox": {"balanced": [" 3153 ", "3111"]}}
    with _patch_table(table), _patch_items(
            tmp_path, {"3153": "Black Cleaver", "3111": "Mercury's Treads"}):
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC") == ["3153", "3111"]
        assert nbf.fallback_build("Aatrox", "CLASSIC") == [
            "Black Cleaver", "Mercury's Treads"]


def test_integral_float_id_is_kept_fractional_and_nonfinite_dropped():
    table = {"Aatrox": {"balanced": [
        3143.0, 3143.5, float("nan"), float("inf"), "3111"]}}
    with _patch_table(table):
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC") == ["3143", "3111"]


def test_overlong_digit_string_does_not_cost_the_row():
    # int() of a > 4300-digit string raises ValueError on Python 3.11+; it
    # must cost that one cell, never the whole row via the outer handler.
    table = {"Aatrox": {"balanced": ["9" * 5000, "3111"]}}
    with _patch_table(table):
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC") == ["3111"]


def test_non_ascii_digits_are_not_ids():
    table = {"Aatrox": {"balanced": ["".join(map(chr, (0x663, 0x661, 0x661, 0x661))), "3111"]}}
    with _patch_table(table):
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC") == ["3111"]


# --- finding 2: a junk-only bucket falls back instead of serving junk -----

def test_junk_only_lean_bucket_falls_back_to_balanced():
    table = {"Aatrox": {"ad_heavy": [None, False, ""],
                        "balanced": ["3142", "3071"]}}
    with _patch_table(table):
        assert nbf.preferred_bucket(AD_COMP) == "ad_heavy"
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC", AD_COMP) == [
            "3142", "3071"]


def test_junk_only_balanced_falls_back_to_any_real_bucket():
    table = {"Aatrox": {"balanced": [True, "x"], "ap_heavy": ["3065"]}}
    with _patch_table(table):
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC") == ["3065"]


def test_all_junk_buckets_yield_empty():
    table = {"Aatrox": {"balanced": [False], "ad_heavy": [None]}}
    with _patch_table(table):
        assert nbf.fallback_build_ids("Aatrox", "CLASSIC") == []


# --- finding 3: only real string names become display names --------------

def test_non_string_item_names_are_not_rendered(tmp_path):
    table = {"Aatrox": {"balanced": ["3111", "3153", "3078", "3143"]}}
    by_id = {"3111": {"name": "Mercury's Treads"}, "3153": ["x"],
             "3078": "   ", "3143": "Randuin's Omen"}
    with _patch_table(table), _patch_items(tmp_path, by_id):
        assert nbf.fallback_build("Aatrox", "CLASSIC") == ["Randuin's Omen"]


def test_item_name_is_stripped(tmp_path):
    table = {"Aatrox": {"balanced": ["3143"]}}
    with _patch_table(table), _patch_items(
            tmp_path, {"3143": "  Randuin's Omen \n"}):
        assert nbf.fallback_build("Aatrox", "CLASSIC") == ["Randuin's Omen"]


def test_items_index_with_no_usable_name_is_not_memoised(tmp_path):
    table = {"Aatrox": {"balanced": ["3143"]}}
    with _patch_table(table):
        with _patch_items(tmp_path, {"3143": {"name": "x"}}):
            assert nbf.fallback_build("Aatrox", "CLASSIC") == []
        # The file is repaired: the next call must pick it up, not serve a
        # memoised empty map (RM-443 shape).
        with _patch_items(tmp_path, {"3143": "Randuin's Omen"}):
            assert nbf.fallback_build("Aatrox", "CLASSIC") == [
                "Randuin's Omen"]


# --- finding 4: the roster must be a real collection ---------------------

def test_dict_roster_is_not_classified_by_its_keys():
    roster = {name: {} for name in AD_COMP}
    assert nbf.preferred_bucket(roster) == "balanced"


def test_string_roster_is_not_classified_by_characters():
    assert nbf.preferred_bucket("Zed") == "balanced"


def test_tuple_and_list_rosters_still_classify():
    assert nbf.preferred_bucket(AD_COMP) == "ad_heavy"
    assert nbf.preferred_bucket(tuple(AD_COMP)) == "ad_heavy"


# --- finding 5: the kill-switch docstring matches the code ---------------

@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "  OFF "])
def test_kill_switch_off_values(monkeypatch, raw):
    monkeypatch.setenv(nbf.FALLBACK_ENV, raw)
    assert nbf.fallback_enabled() is False


@pytest.mark.parametrize("raw", ["1", "true", "on", "yes"])
def test_kill_switch_on_values(monkeypatch, raw):
    monkeypatch.setenv(nbf.FALLBACK_ENV, raw)
    assert nbf.fallback_enabled() is True


def test_kill_switch_docstring_names_every_off_value():
    doc = nbf.fallback_enabled.__doc__ or ""
    for word in ('"0"', '"false"', '"no"', '"off"', "empty"):
        assert word in doc, word


# --- the real tables still come through byte-identical -------------------

def test_real_tables_carry_no_cell_the_validator_drops():
    """Backfill check: the shipped flat tables hold only real ids, so the
    hardening changes nothing a live game is served today."""
    for stem in ("sr", "aram", "arena"):
        orders = nbf._lsp.load_build_orders(stem)
        assert isinstance(orders, dict) and orders, stem
        for champ, buckets in orders.items():
            for bucket, order in buckets.items():
                if not isinstance(order, list):
                    continue
                kept = [c for c in (nbf._item_id(x) for x in order) if c]
                assert kept == [str(x) for x in order], (stem, champ, bucket)


def test_real_items_index_names_all_survive():
    by_id = nbf._id_to_name()
    assert len(by_id) > 600
    assert all(isinstance(v, str) and v == v.strip() and v
               for v in by_id.values())
