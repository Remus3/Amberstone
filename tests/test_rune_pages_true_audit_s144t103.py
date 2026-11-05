"""coaches/rune_pages.py - s144 true-audit cycle 103 (lane 8).

One test class per finding, each red on the pre-fix module:

  F1  the dedup key was rune PICK order: the user-build editor (web/js/main.js
      _ubRpPick*) appends minor runes in click order, so the same page saved
      twice minted two pageIds and two identical-looking side-panel rows.
  F2  an illegal page entered the model ("a malformed page never enters the
      model" was false): a keystone outside the primary tree, minor runes from
      the wrong tree, two runes from one row, a keystone as a minor rune.
  F3  one malformed user-build record (a non-string id, a non-dict runes, an
      unhashable rune name) raised inside the fold and dropped EVERY later
      user build for that champion.
  F4  an unhashable rune field in a generic variant raised out of
      enumerate_pages, so the route answered 500 and the champ-select panel
      cached an empty model for that champion until reload.
  F5  buildIds were not unique: a build_path with no key took its variant's
      own buildId, a repeated path key or user id appeared twice, and the
      panel's builds.find() silently used the first.
  F6  a user build /api/loadout/list does not offer (format_for_display
      rejects it: no label or no items) still got a buildId and a pushPageId
      that /api/loadout/apply refuses.
  F7  user-build rune fields were read raw instead of the way the resolver
      reads them (format_for_display + str()), so pushPageId could name a page
      the resolver never pushes.

Plus the canonical-order guard that no SHIPPED pageId moved (localStorage
saved defaults are keyed by pageId), and the slot-table fail-open contract.
"""
from __future__ import annotations

import itertools
import json
import logging
from pathlib import Path
from unittest import mock

import pytest

from coaches import rune_pages
from lcu.lcu_rune_writer import _KEYSTONES, _TREES, build_perk_ids

_REPO = Path(__file__).resolve().parent.parent

_CRIT = {"key": "crit", "keystone": "Lethal Tempo", "primary": "Precision",
         "secondary": "Domination", "auto_keystone": "Lethal Tempo",
         "auto_primary": "Precision", "auto_secondary": "Domination",
         "build_paths": []}


def _ub(uid, keystone="Lethal Tempo", primary="Precision", secondary="Domination",
        minor_primary=None, minor_secondary=None, items=("Infinity Edge",),
        label="test build"):
    rec = {"id": uid, "label": label, "items": list(items), "runes": {
        "keystone": keystone, "primary": primary, "secondary": secondary,
        "minor_primary": list(minor_primary or []),
        "minor_secondary": list(minor_secondary or [])}}
    return rec


def _enumerate(variants=(), user_builds=(), champ="Jinx", mode="SR"):
    with mock.patch.object(rune_pages, "list_variants",
                           return_value=[dict(v) for v in variants]), \
         mock.patch.object(rune_pages, "_user_builds_for",
                           return_value=list(user_builds)):
        return rune_pages.enumerate_pages(champ, mode)


def _by_id(out):
    return {b["buildId"]: b for b in out["builds"]}


# -- F1: dedup is order-insensitive within a row group -----------------------

class TestF1CanonicalOrder:
    def test_primary_minor_pick_order_does_not_mint_a_second_page(self):
        row_order = ["Absorb Life", "Legend: Haste", "Cut Down"]
        out = _enumerate(user_builds=[
            _ub("u1", minor_primary=row_order),
            _ub("u2", minor_primary=list(reversed(row_order)))])
        b = _by_id(out)
        assert b["userbuild_u1"]["pushPageId"] is not None
        assert b["userbuild_u1"]["pushPageId"] == b["userbuild_u2"]["pushPageId"]
        assert len(out["pages"]) == 1

    def test_secondary_minor_pick_order_does_not_mint_a_second_page(self):
        out = _enumerate(user_builds=[
            _ub("u1", minor_secondary=["Taste of Blood", "Ultimate Hunter"]),
            _ub("u2", minor_secondary=["Ultimate Hunter", "Taste of Blood"])])
        b = _by_id(out)
        assert b["userbuild_u1"]["pushPageId"] is not None
        assert b["userbuild_u1"]["pushPageId"] == b["userbuild_u2"]["pushPageId"]

    def test_served_perk_ids_are_in_row_order(self):
        pg = rune_pages.resolve_page(
            "Lethal Tempo", "Precision", "Domination",
            minor_primary=["Cut Down", "Absorb Life", "Legend: Haste"],
            minor_secondary=["Ultimate Hunter", "Taste of Blood"])
        assert pg is not None
        # keystone, primary rows 1-3, secondary by row, shards untouched.
        assert pg["perk_ids"][:6] == [8008, 9101, 9105, 8017, 8139, 8106]
        assert pg["perk_ids"][6:] == [5005, 5008, 5001]

    def test_a_real_subrune_delta_still_mints_a_distinct_page(self):
        out = _enumerate(user_builds=[
            _ub("u1", minor_primary=["Absorb Life", "Legend: Haste", "Cut Down"]),
            _ub("u2", minor_primary=["Absorb Life", "Legend: Haste", "Last Stand"])])
        b = _by_id(out)
        assert b["userbuild_u1"]["pushPageId"] != b["userbuild_u2"]["pushPageId"]
        assert len(out["pages"]) == 2

    def test_no_default_page_id_moved(self):
        # Saved defaults live in browser localStorage keyed by pageId, so a
        # canonicalisation that re-keyed any DEFAULT page would orphan them.
        # Every legal default combination must hash exactly as before.
        checked = 0
        for ks, pri, sec in itertools.product(_KEYSTONES, _TREES, _TREES):
            if pri == sec:
                continue
            pg = rune_pages.resolve_page(ks, pri, sec)
            if pg is None:
                continue
            raw = build_perk_ids(ks, pri, sec)
            assert pg["pageId"] == rune_pages.page_id(raw), (ks, pri, sec)
            assert pg["perk_ids"] == raw
            checked += 1
        assert checked >= len(_KEYSTONES) * 4


# -- F2: an illegal page never enters the model ------------------------------

class TestF2Legality:
    @pytest.mark.parametrize("kwargs", [
        # keystone outside the primary tree
        dict(keystone="Conqueror", primary="Sorcery", secondary="Precision"),
        dict(keystone="Electrocute", primary="Precision", secondary="Domination"),
        # primary minors from another tree
        dict(keystone="Lethal Tempo", primary="Precision", secondary="Domination",
             minor_primary=["Manaflow Band", "Transcendence", "Gathering Storm"]),
        # two primary minors from one row
        dict(keystone="Lethal Tempo", primary="Precision", secondary="Domination",
             minor_primary=["Absorb Life", "Triumph", "Cut Down"]),
        # a keystone as a primary minor
        dict(keystone="Lethal Tempo", primary="Precision", secondary="Domination",
             minor_primary=["Conqueror", "Legend: Haste", "Cut Down"]),
        # secondary minors from the primary tree
        dict(keystone="Lethal Tempo", primary="Precision", secondary="Domination",
             minor_secondary=["Triumph", "Cut Down"]),
        # two secondary minors from one row
        dict(keystone="Lethal Tempo", primary="Precision", secondary="Domination",
             minor_secondary=["Cheap Shot", "Taste of Blood"]),
        # the same secondary minor twice
        dict(keystone="Lethal Tempo", primary="Precision", secondary="Domination",
             minor_secondary=["Taste of Blood", "Taste of Blood"]),
        # a keystone of the secondary tree as a secondary minor
        dict(keystone="Lethal Tempo", primary="Precision", secondary="Domination",
             minor_secondary=["Electrocute", "Taste of Blood"]),
    ])
    def test_illegal_page_is_none(self, kwargs):
        assert rune_pages.resolve_page(**kwargs) is None

    def test_illegal_user_build_gets_no_push_page(self):
        out = _enumerate(variants=[_CRIT], user_builds=[
            _ub("bad", keystone="Conqueror", primary="Sorcery", secondary="Precision")])
        b = _by_id(out)
        assert b["userbuild_bad"]["pushPageId"] is None
        assert b["userbuild_bad"]["recommendedPageId"] is None
        assert len(out["pages"]) == 1

    def test_legal_pages_still_resolve(self):
        for args in (("Conqueror", "Precision", "Resolve"),
                     ("Phase Rush", "Sorcery", "Inspiration"),
                     ("Hail of Blades", "Domination", "Precision"),
                     ("Glacial Augment", "Inspiration", "Sorcery"),
                     ("Grasp of the Undying", "Resolve", "Precision")):
            assert rune_pages.resolve_page(*args) is not None, args

    def test_served_names_come_from_the_canonical_tables(self):
        # The side panel interpolates keystone / primary / secondary into
        # HTML attributes unescaped, so the model must only ever serve names
        # it validated against the writer's own tables.
        out = _enumerate(variants=[_CRIT], user_builds=[
            _ub("x", keystone='Lethal Tempo"><img src=x>'),
            _ub("y", primary="<b>Precision</b>")])
        for pg in out["pages"]:
            assert pg["keystone"] in _KEYSTONES
            assert pg["primary"] in _TREES
            assert pg["secondary"] in _TREES


# -- F3: one bad user record never drops the others --------------------------

class TestF3RecordIsolation:
    @pytest.mark.parametrize("bad", [
        {"id": 5, "label": "x", "items": ["Infinity Edge"], "runes": {}},
        {"id": "r1", "label": "x", "items": ["Infinity Edge"], "runes": ["nope"]},
        {"id": "r2", "label": "x", "items": ["Infinity Edge"],
         "runes": {"keystone": ["Lethal Tempo"], "primary": "Precision",
                   "secondary": "Domination"}},
        {"id": "r3", "label": "x", "items": ["Infinity Edge"],
         "runes": {"keystone": "Lethal Tempo", "primary": "Precision",
                   "secondary": "Domination", "minor_primary": [["nested"]]}},
        {"id": "r4", "label": "x", "items": 7, "runes": {}},
        "not a dict",
    ])
    def test_a_bad_record_does_not_drop_later_builds(self, bad):
        good = _ub("good", keystone="Electrocute", primary="Domination",
                   secondary="Precision")
        out = _enumerate(variants=[_CRIT], user_builds=[bad, good])
        b = _by_id(out)
        assert "userbuild_good" in b
        assert b["userbuild_good"]["pushPageId"] is not None
        assert "crit" in b

    def test_a_non_string_id_is_skipped(self):
        out = _enumerate(user_builds=[
            {"id": 5, "label": "x", "items": ["Infinity Edge"],
             "runes": {"keystone": "Lethal Tempo", "primary": "Precision",
                       "secondary": "Domination"}}])
        assert out["builds"] == []

    def test_store_failure_still_isolated_and_logged(self, caplog):
        def _boom(champ):
            raise OSError("store gone")
        with mock.patch.object(rune_pages, "list_variants", return_value=[_CRIT]), \
             mock.patch.object(rune_pages, "_user_builds_for", side_effect=_boom), \
             caplog.at_level(logging.WARNING, logger="rc.rune_pages"):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        assert [b["buildId"] for b in out["builds"]] == ["crit"]
        assert any("OSError" in r.getMessage() for r in caplog.records)

    def test_a_non_list_store_result_is_ignored(self):
        with mock.patch.object(rune_pages, "list_variants", return_value=[_CRIT]), \
             mock.patch.object(rune_pages, "_user_builds_for", return_value=5):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        assert [b["buildId"] for b in out["builds"]] == ["crit"]


# -- F4: a malformed generic variant cannot 500 the route --------------------

class TestF4GenericVariantIsolation:
    def test_unhashable_keystone_does_not_raise(self):
        bad = {**_CRIT, "key": "bad", "keystone": ["Lethal Tempo"],
               "auto_keystone": ["Lethal Tempo"]}
        out = _enumerate(variants=[bad, _CRIT])
        b = _by_id(out)
        assert b["bad"]["pushPageId"] is None
        assert b["bad"]["recommendedPageId"] is None
        assert b["crit"]["pushPageId"] is not None

    def test_unhashable_path_rune_does_not_raise(self):
        v = {**_CRIT, "build_paths": [
            {"key": "p1", "keystone": {"x": 1}, "primary": "Precision",
             "secondary": "Domination"},
            {"key": "p2", "keystone": "Electrocute", "primary": "Domination",
             "secondary": "Precision"}]}
        b = _by_id(_enumerate(variants=[v]))
        assert b["crit:p1"]["pushPageId"] is None
        assert b["crit:p2"]["pushPageId"] is not None

    def test_resolve_page_never_raises_on_unhashable_input(self):
        assert rune_pages.resolve_page(["x"], "Precision", "Domination") is None
        assert rune_pages.resolve_page("Lethal Tempo", {}, "Domination") is None
        assert rune_pages.resolve_page(
            "Lethal Tempo", "Precision", "Domination",
            minor_primary=[["a"], ["b"], ["c"]]) is None


# -- F5: buildIds are unique and every one is resolvable ---------------------

class TestF5UniqueBuildIds:
    def test_keyless_path_does_not_shadow_its_variant(self):
        v = {**_CRIT, "build_paths": [
            {"key": "", "keystone": "Electrocute", "primary": "Domination",
             "secondary": "Precision"}]}
        out = _enumerate(variants=[v])
        ids = [b["buildId"] for b in out["builds"]]
        assert ids == ["crit"]
        # and the variant's own entry is the one that survives
        assert _by_id(out)["crit"]["pushPageId"] == rune_pages.resolve_page(
            "Lethal Tempo", "Precision", "Domination")["pageId"]

    def test_repeated_path_key_first_wins(self):
        v = {**_CRIT, "build_paths": [
            {"key": "p", "keystone": "Electrocute", "primary": "Domination",
             "secondary": "Precision"},
            {"key": "p", "keystone": "Conqueror", "primary": "Precision",
             "secondary": "Resolve"}]}
        out = _enumerate(variants=[v])
        ids = [b["buildId"] for b in out["builds"]]
        assert ids.count("crit:p") == 1
        # loadout_resolver.resolve takes the FIRST matching path key.
        assert _by_id(out)["crit:p"]["pushPageId"] == rune_pages.resolve_page(
            "Electrocute", "Domination", "Precision")["pageId"]

    def test_repeated_user_id_first_wins(self):
        out = _enumerate(user_builds=[
            _ub("same", keystone="Electrocute", primary="Domination",
                secondary="Precision"),
            _ub("same")])
        ids = [b["buildId"] for b in out["builds"]]
        assert ids == ["userbuild_same"]
        assert out["builds"][0]["pushPageId"] == rune_pages.resolve_page(
            "Electrocute", "Domination", "Precision")["pageId"]

    def test_non_string_path_key_is_skipped(self):
        v = {**_CRIT, "build_paths": [
            {"key": 7, "keystone": "Electrocute", "primary": "Domination",
             "secondary": "Precision"}]}
        assert [b["buildId"] for b in _enumerate(variants=[v])["builds"]] == ["crit"]

    @pytest.mark.parametrize("vkey", ["a:b", " crit", "crit "])
    def test_unresolvable_variant_key_is_skipped(self, vkey):
        # loadout_resolver.resolve splits on the first colon and does not
        # strip a colon-free key, so neither form can ever be pushed.
        v = {**_CRIT, "key": vkey}
        assert [b["buildId"] for b in _enumerate(variants=[v, _CRIT])["builds"]] \
            == ["crit"]

    def test_padded_path_key_is_skipped(self):
        v = {**_CRIT, "build_paths": [
            {"key": " p ", "keystone": "Electrocute", "primary": "Domination",
             "secondary": "Precision"}]}
        assert [b["buildId"] for b in _enumerate(variants=[v])["builds"]] == ["crit"]

    def test_empty_variant_key_is_skipped(self):
        v = {**_CRIT, "key": ""}
        assert _enumerate(variants=[v, _CRIT])["builds"][0]["buildId"] == "crit"
        assert len(_enumerate(variants=[v, _CRIT])["builds"]) == 1


# -- F6 / F7: user-build parity with /api/loadout/list and /apply ------------

class TestF6F7ResolverParity:
    def test_a_build_the_chooser_does_not_list_gets_no_entry(self):
        out = _enumerate(user_builds=[
            _ub("noitems", items=()), _ub("nolabel", label="")])
        assert out["builds"] == []
        assert out["pages"] == []

    @pytest.mark.parametrize("rec", [
        _ub("a"),
        _ub("b", keystone="Electrocute", primary="Domination", secondary="Precision"),
        _ub("c", minor_primary=["Cut Down", "Absorb Life", "Legend: Haste"]),
        _ub("d", minor_secondary=["Ultimate Hunter", "Taste of Blood"]),
        # non-string minors: the resolver str()s them, misses, keeps defaults
        {"id": "e", "label": "x", "items": ["Infinity Edge"],
         "runes": {"keystone": "Lethal Tempo", "primary": "Precision",
                   "secondary": "Domination", "minor_primary": [1, 2, 3]}},
        # an unhashable minor: the resolver str()s it too, so defaults again
        {"id": "g", "label": "x", "items": ["Infinity Edge"],
         "runes": {"keystone": "Lethal Tempo", "primary": "Precision",
                   "secondary": "Domination",
                   "minor_primary": [["nested"], "Cut Down"]}},
        # a same-tree request: the substituted tree is what both report
        _ub("f", primary="Precision", secondary="Precision"),
    ])
    def test_push_page_is_what_the_resolver_pushes(self, rec):
        from dashboard import routes_loadout
        with mock.patch("coaches.sr_user_builds.list_for", return_value=[rec]):
            res = routes_loadout._resolve_user_build(
                "Jinx", "userbuild_" + rec["id"], "sr", None)
        out = _enumerate(user_builds=[rec])
        push = _by_id(out)["userbuild_" + rec["id"]]["pushPageId"]
        rune_cmd = res.get("rune_cmd")
        assert rune_cmd is not None
        page = next(p for p in out["pages"] if p["pageId"] == push)
        assert sorted(page["perk_ids"]) == sorted(rune_cmd["perk_ids"])
        assert rune_pages._TREES[page["primary"]] == rune_cmd["primary_id"]
        assert rune_pages._TREES[page["secondary"]] == rune_cmd["sub_id"]


# -- verifier round 1: the two gaps it found in the first draft --------------

def _js_push_build(builds, selected_page_id):
    """champ_select.js _csvPushFollowedRune's lookup, transcribed."""
    return next((b for b in builds
                 if str(b.get("pushPageId") or b.get("recommendedPageId") or "")
                 == str(selected_page_id)), None)


class TestVerifierRound1:
    @pytest.mark.parametrize("own", [
        # resolves through build_perk_ids, illegal by the slot table
        dict(keystone="Conqueror", primary="Sorcery", secondary="Precision"),
        # does not resolve at all
        dict(keystone="Not A Keystone", primary="Precision", secondary="Domination"),
    ])
    def test_variant_with_no_own_page_is_never_the_push_target(self, own):
        v = {**_CRIT, "key": "bad", **own}
        out = _enumerate(variants=[v, _CRIT])
        auto = rune_pages.resolve_page("Lethal Tempo", "Precision", "Domination")
        b = _by_id(out)["bad"]
        assert b["pushPageId"] is None
        assert b["recommendedPageId"] is None
        # the auto page is the default selection; it must reach a build whose
        # own runes ARE that page, never the bad variant listed first
        target = _js_push_build(out["builds"], auto["pageId"])
        assert target is not None and target["buildId"] == "crit"

    def test_duplicate_user_id_behind_a_malformed_first_is_unpushable(self):
        # _resolve_user_build stops at the first record with the id and
        # answers "malformed", so the model must not offer the second one.
        bad = {"id": "same", "label": "x", "items": ["Infinity Edge"],
               "runes": ["nope"]}
        out = _enumerate(user_builds=[bad, _ub("same")])
        assert out["builds"] == []


# -- slot table: fail-open, not cached on failure, shape-checked -------------

class TestSlotTable:
    def _reset(self, monkeypatch, path):
        monkeypatch.setattr(rune_pages, "_DDRAGON_RUNES", path)
        monkeypatch.setattr(rune_pages, "_SLOT_TABLE", None)
        monkeypatch.setattr(rune_pages, "_SLOT_TABLE_FAIL_LOGGED", False)

    def test_missing_file_fails_open_and_logs_once(self, monkeypatch, tmp_path, caplog):
        self._reset(monkeypatch, tmp_path / "absent.json")
        with caplog.at_level(logging.WARNING, logger="rc.rune_pages"):
            a = rune_pages.resolve_page("Lethal Tempo", "Precision", "Domination")
            b = rune_pages.resolve_page("Conqueror", "Sorcery", "Precision")
        assert a is not None
        # unvalidated: the pre-audit behaviour, never a crash or an empty model
        assert b is not None
        assert len([r for r in caplog.records if "slot table" in r.getMessage()]) == 1

    def test_failure_is_not_cached(self, monkeypatch, tmp_path):
        self._reset(monkeypatch, tmp_path / "absent.json")
        assert rune_pages._slot_table() is None
        monkeypatch.setattr(rune_pages, "_DDRAGON_RUNES",
                            _REPO / "data" / "meta" / "ddragon_runes.json")
        assert rune_pages._slot_table()
        assert rune_pages.resolve_page("Conqueror", "Sorcery", "Precision") is None

    @pytest.mark.parametrize("doc", [
        {"not": "a list"}, [], [{"id": "8000", "slots": []}],
        [{"id": 8000, "slots": [{"runes": [{"id": True}]}]}],
        [{"id": 8000, "slots": "x"}],
        [{"id": 8000, "slots": []}],
        # four slots, but a bool where a rune id belongs
        [{"id": 8000, "slots": [{"runes": [{"id": 1}]}, {"runes": [{"id": 2}]},
                                {"runes": [{"id": 3}]}, {"runes": [{"id": False}]}]}],
        # four slots, but one rune id twice
        [{"id": 8000, "slots": [{"runes": [{"id": 1}]}, {"runes": [{"id": 2}]},
                                {"runes": [{"id": 3}]}, {"runes": [{"id": 1}]}]}],
        # four slots, one of them empty (a partial table would reject legal
        # pages that use the missing row)
        [{"id": 8000, "slots": [{"runes": []}, {"runes": [{"id": 2}]},
                                {"runes": [{"id": 3}]}, {"runes": [{"id": 4}]}]}],
        # a bool tree id
        [{"id": True, "slots": [{"runes": [{"id": 1}]}, {"runes": [{"id": 2}]},
                                {"runes": [{"id": 3}]}, {"runes": [{"id": 4}]}]}],
    ])
    def test_malformed_table_is_unavailable(self, monkeypatch, tmp_path, doc):
        p = tmp_path / "runes.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        self._reset(monkeypatch, p)
        assert rune_pages._slot_table() is None

    def test_unparseable_file_is_unavailable(self, monkeypatch, tmp_path):
        p = tmp_path / "runes.json"
        p.write_bytes(b"\xff\xfe not json")
        self._reset(monkeypatch, p)
        assert rune_pages._slot_table() is None


# -- the shipped data: every champion and mode still enumerates --------------

@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_shipped_loadouts_enumerate_cleanly(mode):
    doc = json.loads((_REPO / "data" / "champion_loadouts.json")
                     .read_text(encoding="utf-8"))
    champs = sorted(doc.get("champions") or {})
    assert len(champs) > 100
    total = 0
    with mock.patch.object(rune_pages, "_user_builds_for", return_value=[]):
        for champ in champs:
            out = rune_pages.enumerate_pages(champ, mode)
            ids = [b["buildId"] for b in out["builds"]]
            assert len(ids) == len(set(ids)), champ
            # The new skips (bad key, repeat) and the legality check drop
            # nothing the shipped data carries.
            served = rune_pages.list_variants(champ, mode)
            assert len(ids) == sum(1 + len(v["build_paths"]) for v in served), champ
            assert all(b["pushPageId"] and b["recommendedPageId"]
                       for b in out["builds"]), champ
            page_ids = {p["pageId"] for p in out["pages"]}
            for b in out["builds"]:
                if b["pushPageId"] is not None:
                    assert b["pushPageId"] in page_ids
            total += len(out["pages"])
    assert total > 0


def test_module_and_test_are_ascii_lf():
    for p in (Path(rune_pages.__file__), Path(__file__)):
        raw = p.read_bytes()
        assert not [b for b in raw if b > 0x7F], p.name
        assert b"\r" not in raw, p.name
