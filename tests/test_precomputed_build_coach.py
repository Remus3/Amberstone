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
