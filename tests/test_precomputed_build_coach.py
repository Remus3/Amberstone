"""HZ-C2 - core.precomputed_build_coach reader characterization tests.

Pins the enemy-comp durability classifier (frontline_count -> variant +
confidence), the BUILD A/B choice shaping from one HZ-B2 variant pair, and the
fail-soft empties. compute_factors is monkeypatched so classification is tested
in isolation from champions.json; the table is a synthetic in-memory payload.
"""
from __future__ import annotations

import pytest

from core.coach_choices import CoachChoice
from core import precomputed_build_coach as pbc


def _factors(n, front):
    return {"n": n, "frontline_count": front, "ad_count": 0, "ap_count": 0}


def _payload():
    return {
        "schema": "build_order_variants/v1",
        "build_orders": {
            "Ahri": {
                "anti_tank": {
                    "variant": "anti_tank",
                    "order": ["3135", "3111", "3089"],
                    "bias": {},
                    "antitank": {"my_antitank_score": 0.0, "lean_in": False,
                                 "recommend_antitank_items": True, "top_kind": ""},
                },
                "anti_squishy": {
                    "variant": "anti_squishy",
                    "order": ["3135", "3157"],
                    "bias": {},
                    "antitank": {},
                },
            },
        },
    }


# --------------------------------------------------------------------------- #
# comp_lean classifier
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n,front,expected", [
    (0, 0, None),
    (5, 3, ("anti_tank", "high")),
    (5, 2, ("anti_tank", "mid")),
    (3, 0, ("anti_squishy", "high")),
    (3, 1, ("anti_squishy", "mid")),
    (2, 0, ("anti_squishy", "mid")),  # n<3 -> not high even with 0 frontline
])
def test_comp_lean(monkeypatch, n, front, expected):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(n, front))
    assert pbc.comp_lean(["x"]) == expected


# --------------------------------------------------------------------------- #
# build_choices
# --------------------------------------------------------------------------- #
def test_anti_tank_lean_shapes_build_ab(monkeypatch):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(5, 3))
    out = pbc.build_choices(
        "Ahri", ["Malphite", "Ornn", "Sion"], payload=_payload(),
        item_costs={"3135": ("Void Staff", 3000)},
    )
    assert len(out) == 2
    assert all(isinstance(c, CoachChoice) for c in out)
    assert out[0].label == "Build anti-tank"
    assert out[1].label == "Build anti-squishy"
    assert out[0].confidence == "high"
    assert all(c.source_tag == pbc.SOURCE_TAG for c in out)
    # next item + the A3 recommend_antitank_items note in the A outcome
    assert "Void Staff (3000g)" in out[0].expected_outcome
    assert "front-load pen" in out[0].expected_outcome


def test_anti_squishy_lean_recommends_squishy_first(monkeypatch):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(3, 0))
    out = pbc.build_choices("Ahri", ["Caitlyn", "Lux", "Ezreal"], payload=_payload())
    assert out[0].label == "Build anti-squishy"
    assert out[1].label == "Build anti-tank"
    assert "raw early power" in out[0].expected_outcome


def test_owned_count_advances_next_item(monkeypatch):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(5, 3))
    out = pbc.build_choices(
        "Ahri", ["Malphite", "Ornn"], payload=_payload(),
        item_costs={"3111": ("Mercury's Treads", 1100)}, owned_count=1,
    )
    assert "Mercury's Treads (1100g)" in out[0].expected_outcome


# --------------------------------------------------------------------------- #
# owned-identity skip (deviation fix) - the live build-chip never recommends an
# item the player already owns even when they built off the canonical order.
# --------------------------------------------------------------------------- #
def test_next_item_str_skips_owned_on_deviation():
    order = ["1001", "2002", "3003", "4004"]
    # Owns order[0] + order[2] (deviation). Legacy order[owned_count=2]=3003 is
    # OWNED; skip-owned must return the first un-owned entry, order[1]=2002.
    nxt = pbc._next_item_str(order, owned_count=2, item_costs=None,
                             owned_ids={"1001", "3003"})
    assert nxt == "item 2002"
    assert "3003" not in (nxt or "")


def test_next_item_str_owned_ids_none_is_legacy_index():
    order = ["1001", "2002", "3003"]
    assert pbc._next_item_str(order, 1, None) == "item 2002"
    assert pbc._next_item_str(order, 1, None, owned_ids=None) == "item 2002"
    assert pbc._next_item_str(order, 1, None, owned_ids=set()) == "item 2002"


def test_next_item_str_all_owned_returns_none():
    order = ["1001", "2002"]
    assert pbc._next_item_str(order, 0, None, owned_ids={"1001", "2002"}) is None


def test_build_choices_owned_ids_skips_owned_item(monkeypatch):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(5, 3))
    # anti_tank order = ["3135", "3111", "3089"]; own 3135 + 3089 (deviation).
    # owned_count=2 -> legacy index order[2]=3089 (OWNED). Must skip to 3111.
    out = pbc.build_choices(
        "Ahri", ["Malphite", "Ornn"], payload=_payload(),
        item_costs={"3111": ("Mercury's Treads", 1100),
                    "3089": ("Rabadon's Deathcap", 3600)},
        owned_count=2, owned_ids={"3135", "3089"},
    )
    assert "Mercury's Treads (1100g)" in out[0].expected_outcome
    assert "Rabadon" not in out[0].expected_outcome


@pytest.mark.parametrize("champ,comp,n,front", [
    ("Yasuo", ["Malphite", "Ornn"], 5, 3),   # champ not in table
    ("", ["Malphite"], 5, 3),                 # empty champ
])
def test_uncovered_or_empty_returns_empty(monkeypatch, champ, comp, n, front):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(n, front))
    assert pbc.build_choices(champ, comp, payload=_payload()) == []


def test_unresolvable_comp_returns_empty(monkeypatch):
    monkeypatch.setattr(pbc, "compute_factors", lambda comp: _factors(0, 0))
    assert pbc.build_choices("Ahri", ["???"], payload=_payload()) == []
