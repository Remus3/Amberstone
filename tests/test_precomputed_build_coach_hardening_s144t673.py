"""S144-T-673 - core.precomputed_build_coach true-audit hardening.

One junk value anywhere in the inputs used to sink the WHOLE BUILD A/B pair
(build_choices' broad except turned an OverflowError / ValueError / TypeError
from one bad item-cost row or one bad count into ``[]``), the A choice's note
was read off the table cell instead of the variant actually looked up, a bare
string comp or owned-id set was iterated character by character, an empty
owned-id iterator silently bypassed the documented legacy index, a caller mode
reached the table loader's file name unchecked, and every swallowed exception
was silent. 40 of the 52 cases below failed on the pre-fix module; the other
12 are positive controls that pin behaviour the fix must keep (a generator
comp, a float cost, a well-formed mode, a bool owned id that must not read as
item 1). A bool ORDER entry is covered by test_blank_order_entries_are_skipped.
"""
from __future__ import annotations

import logging

import pytest

from core import precomputed_build_coach as pbc


def _factors(n, front):
    return {"n": n, "frontline_count": front, "ad_count": 0, "ap_count": 0}


def _payload(*, drop_variant_key=False):
    at = {
        "variant": "anti_tank",
        "order": ["3135", "3111", "3089"],
        "bias": {},
        "antitank": {"lean_in": False, "recommend_antitank_items": True},
    }
    sq = {"variant": "anti_squishy", "order": ["3135", "3157"],
          "bias": {}, "antitank": {}}
    if drop_variant_key:
        at.pop("variant")
        sq.pop("variant")
    return {"build_orders": {"Ahri": {"anti_tank": at, "anti_squishy": sq}}}


@pytest.fixture
def tank_wall(monkeypatch):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(5, 3))


# --------------------------------------------------------------------------- #
# comp_lean input shape
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("comp", ["Malphite", b"Ornn", {"Malphite": 1}])
def test_comp_lean_rejects_a_bare_string_or_mapping(tank_wall, comp):
    # A single name / a dict is not a comp; it must never classify.
    assert pbc.comp_lean(comp) is None


@pytest.mark.parametrize("comp", [5, 2.5, True, object()])
def test_comp_lean_non_iterable_never_raises(tank_wall, comp):
    assert pbc.comp_lean(comp) is None


def test_comp_lean_generator_still_classifies(monkeypatch):
    seen = []

    def _cf(comp):
        seen.append(comp)
        return _factors(5, 3)

    monkeypatch.setattr(pbc, "compute_factors", _cf)
    assert pbc.comp_lean(n for n in ["Malphite", "Ornn"]) == ("anti_tank", "high")
    assert seen == [["Malphite", "Ornn"]]


# --------------------------------------------------------------------------- #
# item-cost rows: one bad row degrades that item's text, never the pair
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("row", [
    ("Void Staff", float("inf")),
    ("Void Staff", float("nan")),
    ("Void Staff", True),
    ("Void Staff", -5),
    ("Void Staff", "lots"),
    ("Void Staff", None),
])
def test_bad_cost_keeps_the_name_and_the_pair(tank_wall, row):
    out = pbc.build_choices("Ahri", ["Malphite"], payload=_payload(),
                            item_costs={"3135": row})
    assert len(out) == 2
    assert "next Void Staff;" in out[0].expected_outcome


@pytest.mark.parametrize("row", ["abc", "ab", ("Void Staff",), None, 7,
                                 ("", 3000), ("   ", 3000), (5, 3000),
                                 ("A", 1, 2)])
def test_malformed_row_falls_back_to_the_item_id(tank_wall, row):
    out = pbc.build_choices("Ahri", ["Malphite"], payload=_payload(),
                            item_costs={"3135": row})
    assert len(out) == 2
    assert "next item 3135;" in out[0].expected_outcome


def test_float_cost_is_rendered_as_whole_gold():
    assert pbc._fmt_item("3135", {"3135": ("Void Staff", 3000.0)}) == "Void Staff (3000g)"


@pytest.mark.parametrize("costs", [["3135"], "3135", 42])
def test_non_mapping_cost_table_falls_back(costs):
    assert pbc._fmt_item("3135", costs) == "item 3135"


# --------------------------------------------------------------------------- #
# owned_count / owned_ids
# --------------------------------------------------------------------------- #
def test_infinite_owned_count_does_not_sink_the_pair(tank_wall):
    out = pbc.build_choices("Ahri", ["Malphite"], payload=_payload(),
                            owned_count=float("inf"))
    assert len(out) == 2


@pytest.mark.parametrize("oc", [True, float("nan"), float("inf"), "x", None])
def test_junk_owned_count_reads_as_zero(oc):
    assert pbc._next_item_str(["1001", "2002"], oc, None) == "item 1001"


def test_empty_owned_iterator_uses_the_legacy_index():
    order = ["1001", "2002", "3003"]
    assert pbc._next_item_str(order, 1, None, owned_ids=iter([])) == "item 2002"
    assert pbc._next_item_str(order, 1, None, owned_ids=(x for x in [])) == "item 2002"


@pytest.mark.parametrize("owned", ["1001", b"1001", 5, {"1001": 1}])
def test_junk_owned_ids_use_the_legacy_index(owned):
    order = ["1001", "2002", "3003"]
    assert pbc._next_item_str(order, 1, None, owned_ids=owned) == "item 2002"


def test_numeric_owned_ids_match_string_order_entries():
    order = ["1001", "2002", "3003"]
    assert pbc._next_item_str(order, 0, None, owned_ids=[1001, 2002.0]) == "item 3003"


def test_bool_owned_id_is_not_item_one():
    assert pbc._next_item_str(["1", "2"], 0, None, owned_ids=[True]) == "item 1"


def test_blank_order_entries_are_skipped():
    assert pbc._next_item_str(["", None, "3135"], 0, None) == "item 3135"
    assert pbc._next_item_str([None, True, "  "], 0, None) is None


# --------------------------------------------------------------------------- #
# the A note follows the variant LOOKED UP, not the cell's own label
# --------------------------------------------------------------------------- #
def test_anti_tank_note_does_not_depend_on_the_cell_variant_key(tank_wall):
    out = pbc.build_choices("Ahri", ["Malphite"],
                            payload=_payload(drop_variant_key=True))
    assert out[0].label == "Build anti-tank"
    assert "raw early power" not in out[0].expected_outcome
    assert "front-load pen" in out[0].expected_outcome
    assert out[1].label == "Build anti-squishy"
    assert "raw early power" in out[1].expected_outcome


# --------------------------------------------------------------------------- #
# mode is validated before it reaches the table loader's file name
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["../../secrets", "sr/../x", "tft", "", None, 3])
def test_unknown_mode_never_reaches_the_loader(tank_wall, monkeypatch, mode):
    calls = []
    monkeypatch.setattr(pbc, "load_build_order_variants",
                        lambda m="sr", patch=None: calls.append(m) or _payload())
    assert pbc.build_choices("Ahri", ["Malphite"], mode) == []
    assert calls == []


@pytest.mark.parametrize("mode,expected", [("SR", "sr"), (" aram ", "aram"),
                                           ("arena", "arena")])
def test_known_mode_is_normalised_for_the_loader(tank_wall, monkeypatch, mode,
                                                 expected):
    calls = []
    monkeypatch.setattr(pbc, "load_build_order_variants",
                        lambda m="sr", patch=None: calls.append(m) or _payload())
    assert len(pbc.build_choices("Ahri", ["Malphite"], mode)) == 2
    assert calls == [expected]


# --------------------------------------------------------------------------- #
# a swallowed failure is logged (once per exception type), not silent
# --------------------------------------------------------------------------- #
def test_unexpected_failure_is_logged_once(tank_wall, monkeypatch, caplog):
    def _boom(_name):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(pbc, "canonical_champion_id", _boom)
    monkeypatch.setattr(pbc, "_LOGGED_FAILURES", set())
    caplog.set_level(logging.WARNING, logger=pbc.__name__)
    assert pbc.build_choices("Ahri", ["Malphite"], payload=_payload()) == []
    assert pbc.build_choices("Ahri", ["Malphite"], payload=_payload()) == []
    recs = [r for r in caplog.records if r.name == pbc.__name__]
    assert len(recs) == 1
    assert "RuntimeError" in recs[0].getMessage()
