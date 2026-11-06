"""Hardening of core.build_planner.champ_kit_data (s144 true-audit cycle 161).

Every test runs against a synthetic DS data dir under tmp_path (``_DS_DIR`` is
monkeypatched and both caches are dropped before and after), so no live patch
data is read and no live state is touched. Synthetic champions only.

Findings pinned here (S144-T-488..S144-T-496):
  * a NaN / inf share or stat read as the MAXIMUM weight (``_clamp`` keeps the
    upper bound when handed NaN), and a bool read as 1.0;
  * one junk share zeroed its sibling shares (one shared try block), and one
    junk stat zeroed its sibling stat / rating;
  * a non-object lolmath / damage_distribution / stats / ratings raised
    AttributeError, and a non-list or nested-list tags / roles raised TypeError;
  * a non-iterable spell array raised TypeError out of the ability-AP sum, an
    inf ratio made an auto-attacker a caster marksman, a NaN ratio erased the
    real ones, and a bool ratio counted as 1 percent;
  * a shape-drifted champions.json / ratios file was cached as a SUCCESS for
    the process lifetime (the RM-439 class);
  * a case variant of a champion name ("ezreal") was unresolved, so the
    coherence re-rank (which resolves the archetype case-insensitively) docked
    Ezreal's spellblade core;
  * a BOM in current.txt hid all champion data, and a path-segment token was
    followed outside the DS data dir;
  * a blank-ish entry name indexed an empty key, so a blank-ish query resolved.

ASCII only - use " - " for a clause break.
"""
from __future__ import annotations

import json
import logging
import math

import pytest

from core.build_planner import champ_kit_data as ckd

_PATCH = "9.9.9"
_NAN = float("nan")
_INF = float("inf")


def _mks(cid="Testmks", name=None, **over):
    """A ranged crit marksman (physical-dominant) with every field present."""
    entry = {
        "id": cid,
        "name": name or cid,
        "tags": ["Marksman"],
        "stats": {"attackrange": 550.0, "attackspeedperlevel": 3.0},
        "lolmath": {
            "damage_distribution": {"physical": 0.8, "magical": 0.1,
                                    "trued": 0.1},
            "roles": ["MARKSMAN"],
            "ratings": {"healing": 0.0, "shielding": 0.0},
        },
    }
    entry.update(over)
    return entry


@pytest.fixture
def ds(tmp_path, monkeypatch):
    """Point the module at a synthetic DS dir; returns a writer."""
    root = tmp_path / "daemon_slayer"
    (root / _PATCH).mkdir(parents=True)
    (root / "current.txt").write_text(_PATCH, encoding="utf-8")
    monkeypatch.setattr(ckd, "_DS_DIR", root)
    ckd.invalidate_cache()

    def write(champs=None, ratios=None, raw_champs=None, raw_ratios=None):
        if raw_champs is not None or champs is not None:
            text = raw_champs if raw_champs is not None else json.dumps(
                {"data": {e["id"]: e for e in champs}})
            (root / _PATCH / "champions.json").write_text(text,
                                                          encoding="utf-8")
        if raw_ratios is not None or ratios is not None:
            text = raw_ratios if raw_ratios is not None else json.dumps(
                {"champions": ratios})
            (root / _PATCH / "cdragon_ability_ratios.json").write_text(
                text, encoding="utf-8")
        ckd.invalidate_cache()
        return root

    yield write
    ckd.invalidate_cache()


def _w(ds, entry, champ=None):
    ds([entry])
    w = ckd.derive_kit_weights(champ or entry["id"])
    assert w is not None
    assert set(w) == set(ckd._AXES)
    assert all(math.isfinite(v) for v in w.values()), w
    return w


# --------------------------------------------------------------------------- #
# Non-finite and bool numbers never read as the maximum weight.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, True])
def test_nonfinite_or_bool_physical_share_reads_as_zero(ds, bad):
    e = _mks()
    e["lolmath"]["damage_distribution"]["physical"] = bad
    assert _w(ds, e)["AD"] == 0.0


@pytest.mark.parametrize("bad", [_NAN, _INF])
def test_nonfinite_magical_share_reads_as_zero(ds, bad):
    e = _mks(tags=["Mage"])
    e["lolmath"]["roles"] = ["MAGE"]
    e["lolmath"]["damage_distribution"]["magical"] = bad
    assert _w(ds, e)["AP"] == 0.0


def test_nan_true_share_reads_as_zero(ds):
    e = _mks()
    e["lolmath"]["damage_distribution"]["trued"] = _NAN
    assert _w(ds, e)["true"] == pytest.approx(0.2)


def test_nan_attackspeedperlevel_reads_as_zero(ds):
    e = _mks()
    e["stats"]["attackspeedperlevel"] = _NAN
    assert _w(ds, e)["AS"] == pytest.approx(0.6)


def test_nan_attackrange_reads_as_melee(ds):
    e = _mks()
    e["stats"]["attackrange"] = _NAN
    # Not ranged -> not a crit marksman -> the generic marksman crit weight.
    assert _w(ds, e)["crit"] == pytest.approx(0.2)


def test_nan_rating_does_not_mask_the_other_rating(ds):
    e = _mks(tags=["Support"])
    e["lolmath"]["roles"] = ["SUPPORT"]
    e["lolmath"]["ratings"] = {"healing": _NAN, "shielding": 5.0}
    assert _w(ds, e)["AH"] == pytest.approx(0.9)


# --------------------------------------------------------------------------- #
# One junk field never zeroes its siblings.
# --------------------------------------------------------------------------- #
def test_junk_physical_share_keeps_magical_share(ds):
    e = _mks(tags=["Mage"])
    e["lolmath"]["roles"] = ["MAGE"]
    e["lolmath"]["damage_distribution"] = {"physical": "junk",
                                           "magical": 0.6, "trued": 0.0}
    assert _w(ds, e)["AP"] == pytest.approx(0.6 * 1.35)


def test_junk_attackrange_keeps_attackspeedperlevel(ds):
    e = _mks(tags=["Fighter"])
    e["lolmath"]["roles"] = ["FIGHTER"]
    e["stats"] = {"attackrange": "junk", "attackspeedperlevel": 3.0}
    assert _w(ds, e)["AS"] == pytest.approx(0.2 + 3.0 / 18.0)


def test_junk_healing_keeps_shielding(ds):
    e = _mks(tags=["Support"])
    e["lolmath"]["roles"] = ["SUPPORT"]
    e["lolmath"]["ratings"] = {"healing": "junk", "shielding": 5.0}
    assert _w(ds, e)["AH"] == pytest.approx(0.9)


# --------------------------------------------------------------------------- #
# Wrong-typed sections never raise.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", ["x", ["a"], 5])
def test_non_object_lolmath_never_raises(ds, bad):
    e = _mks(lolmath=bad)
    _w(ds, e)


@pytest.mark.parametrize("field", ["damage_distribution", "ratings"])
@pytest.mark.parametrize("bad", ["x", [1], 7])
def test_non_object_lolmath_subsection_never_raises(ds, field, bad):
    e = _mks()
    e["lolmath"][field] = bad
    _w(ds, e)


@pytest.mark.parametrize("bad", ["x", [1], 7])
def test_non_object_stats_never_raises(ds, bad):
    _w(ds, _mks(stats=bad))


@pytest.mark.parametrize("bad", [5, 2.5, {"a": 1}])
def test_non_list_tags_never_raise(ds, bad):
    e = _mks(tags=bad)
    e["lolmath"]["roles"] = bad
    _w(ds, e)
    assert ckd.is_caster_marksman(e["id"]) is False


def test_nested_list_tag_is_dropped_not_raised(ds):
    e = _mks(tags=[["Mage"], "Marksman", {"x": 1}])
    e["lolmath"]["roles"] = [["MAGE"], "MARKSMAN"]
    w = _w(ds, e)
    # "Marksman" still counts: the marksman crit weight is applied.
    assert w["crit"] == pytest.approx(1.1)


def test_bare_string_tags_are_not_read_by_character(ds):
    e = _mks(tags="Marksman")
    e["lolmath"]["roles"] = "MARKSMAN"
    w = _w(ds, e)
    assert w["crit"] == 0.0


# --------------------------------------------------------------------------- #
# The ability-AP sum.
# --------------------------------------------------------------------------- #
def _caster(cid="Testcaster"):
    return _mks(cid=cid, tags=["Marksman", "Mage"])


def test_non_iterable_spell_array_never_raises(ds):
    e = _caster()
    ds([e], ratios={e["id"]: {"Q": 5, "W": [{"ap_pct": [300.0]}]}})
    assert ckd.is_caster_marksman(e["id"]) is True


def test_inf_ratio_does_not_make_a_caster(ds):
    e = _caster()
    ds([e], ratios={e["id"]: {"Q": [{"ap_pct": [_INF]}]}})
    assert ckd.is_caster_marksman(e["id"]) is False


def test_nan_ratio_does_not_erase_the_real_ones(ds):
    e = _caster()
    ds([e], ratios={e["id"]: {"Q": [{"ap_pct": [_NAN]}],
                              "W": [{"ap_pct": [300.0]}]}})
    assert ckd.is_caster_marksman(e["id"]) is True


def test_nan_scalar_ratio_does_not_erase_the_real_ones(ds):
    e = _caster()
    ds([e], ratios={e["id"]: {"Q": [{"ap_pct": _NAN}],
                              "W": [{"ap_pct": 300.0}]}})
    assert ckd.is_caster_marksman(e["id"]) is True


def test_bool_ratio_is_not_one_percent(ds):
    e = _caster()
    blocks = {f"S{i}": [{"ap_pct": True}] for i in range(250)}
    ds([e], ratios={e["id"]: blocks})
    assert ckd.is_caster_marksman(e["id"]) is False


def test_well_formed_ratios_still_sum(ds):
    e = _caster()
    ds([e], ratios={e["id"]: {"Q": [{"ap_pct": [10.0, 150.0]}],
                              "W": [{"ap_pct": 60.0, "total_ad_pct": [40.0]}]}})
    agg = ckd._ability_agg(ckd._resolve_champ(e["id"]))
    assert agg == pytest.approx({"ap": 2.1, "total_ad": 0.4})
    assert ckd.is_caster_marksman(e["id"]) is True


# --------------------------------------------------------------------------- #
# A shape-drifted file is a failure, never a cached success.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", ['{"data": []}', '{"data": {}}',
                                 '{"data": {"A": 5, "B": "x"}}', "[]", "5"])
def test_shape_drifted_champions_file_is_not_cached(ds, raw, caplog):
    ds(raw_champs=raw)
    with caplog.at_level(logging.WARNING, logger="rc.build_planner.champ_kit_data"):
        assert ckd._load_champions() == {}
    assert ckd._CHAMP_CACHE is None
    assert ckd._CHAMP_GATE.should_attempt() is False
    assert any("champ_kit_data" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("raw", ['{"champions": []}', "{}", "[]",
                                 '{"champions": 5}'])
def test_shape_drifted_ratios_file_is_not_cached(ds, raw):
    ds(raw_ratios=raw)
    assert ckd._load_ability_ratios() == {}
    assert ckd._RATIO_CACHE is None
    assert ckd._RATIO_GATE.should_attempt() is False


def test_empty_ratio_map_is_a_legitimate_cached_empty(ds):
    ds(raw_ratios='{"champions": {}}')
    assert ckd._load_ability_ratios() == {}
    assert ckd._RATIO_CACHE == {}


def test_well_formed_champions_file_is_cached(ds):
    ds([_mks()])
    assert "Testmks" in ckd._load_champions()
    assert ckd._CHAMP_CACHE is not None


# --------------------------------------------------------------------------- #
# Name resolution.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("query", ["ezreal", "EZREAL", "eZrEaL", " Ezreal "])
def test_case_variant_resolves_like_the_canonical_name(ds, query):
    e = _caster(cid="Ezreal")
    ds([e], ratios={"Ezreal": {"Q": [{"ap_pct": [300.0]}]}})
    assert ckd.derive_kit_weights(query) == ckd.derive_kit_weights("Ezreal")
    assert ckd.is_caster_marksman(query) is True


def test_case_variant_of_a_display_name_resolves(ds):
    e = _mks(cid="KogMaw", name="Kog'Maw")
    ds([e])
    assert ckd.derive_kit_weights("kog'maw") == ckd.derive_kit_weights("KogMaw")


def test_exact_match_still_wins_over_a_case_fold(ds):
    a = _mks(cid="Aa", name="Aa")
    b = _mks(cid="AA", name="AA", tags=["Tank"])
    b["lolmath"]["roles"] = ["TANK"]
    ds([a, b])
    assert ckd.derive_kit_weights("AA")["HP-scaling"] == pytest.approx(1.1)
    assert ckd.derive_kit_weights("Aa")["HP-scaling"] == 0.0


@pytest.mark.parametrize("query", [" ", "'", "' '", "   "])
def test_blankish_query_never_resolves(ds, query):
    junk = _mks(cid="Junk", name=" ")
    junk2 = _mks(cid="Junk2", name="'")
    ds([junk, junk2])
    assert ckd.derive_kit_weights(query) is None
    # The index layer: no key without an alphanumeric is ever indexed.
    assert all(ckd._norm(k) for k in ckd._load_champions())


@pytest.mark.parametrize("query", [" ", "'", ""])
def test_blankish_query_refused_even_if_the_index_held_a_blank_key(
        ds, monkeypatch, query):
    # The query layer on its own: a blank-ish name never resolves, even
    # against an index that (somehow) carries blank keys.
    e = _mks()
    monkeypatch.setattr(ckd, "_load_champions",
                        lambda: {"": e, " ": e, "'": e, "Testmks": e})
    assert ckd._resolve_champ(query) == {}


def test_case_fold_follows_a_swapped_index(ds, monkeypatch):
    # The fold is tied to ONE index object: a reload (patch refresh) that
    # yields a new index must never be answered from the old fold.
    old = _mks(cid="Swapme")
    new = _mks(cid="Swapme", tags=["Tank"])
    new["lolmath"]["roles"] = ["TANK"]
    current = {"idx": {"Swapme": old}}
    monkeypatch.setattr(ckd, "_load_champions", lambda: current["idx"])
    assert ckd._resolve_champ("swapme") is old
    current["idx"] = {"Swapme": new}
    assert ckd._resolve_champ("swapme") is new


@pytest.mark.parametrize("value, expected", [
    ("Marksman", frozenset()),
    ("ab", frozenset()),
    (["Marksman", 5, ["Mage"], "Mage"], frozenset({"Marksman", "Mage"})),
    (("Tank",), frozenset({"Tank"})),
    (None, frozenset()),
    ({"Mage": 1}, frozenset()),
])
def test_str_set_reads_only_str_list_members(value, expected):
    assert ckd._str_set(value) == expected


def test_non_str_entry_name_is_not_indexed(ds):
    e = _mks(cid="Realid", name=12345)
    ds([e])
    assert ckd.derive_kit_weights("12345") is None
    assert ckd.derive_kit_weights("Realid") is not None


# --------------------------------------------------------------------------- #
# current.txt.
# --------------------------------------------------------------------------- #
def test_bom_current_txt_still_resolves(ds):
    root = ds([_mks()])
    (root / "current.txt").write_bytes(b"\xef\xbb\xbf" + _PATCH.encode() + b"\r\n")
    ckd.invalidate_cache()
    assert ckd.derive_kit_weights("Testmks") is not None


@pytest.mark.parametrize("token", ["../evil", "..", "evil/x", "evil\\x", "C:evil"])
def test_path_segment_patch_token_is_refused(ds, token):
    root = ds()
    outside = root.parent / "evil"
    outside.mkdir(exist_ok=True)
    (outside / "champions.json").write_text(
        json.dumps({"data": {"Testmks": _mks()}}), encoding="utf-8")
    (outside / "x").mkdir(exist_ok=True)
    (outside / "x" / "champions.json").write_text(
        json.dumps({"data": {"Testmks": _mks()}}), encoding="utf-8")
    (root / "current.txt").write_text(token, encoding="utf-8")
    ckd.invalidate_cache()
    assert ckd._resolve_ds_patch() is None
    assert ckd.derive_kit_weights("Testmks") is None


def test_unreadable_current_txt_is_no_data_not_a_raise(ds):
    root = ds([_mks()])
    (root / "current.txt").write_bytes(b"\xff\xfe\x00bad")
    ckd.invalidate_cache()
    assert ckd._resolve_ds_patch() is None
