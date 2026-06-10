"""HZ-C2 - dashboard._deterministic_coaching.shadow_log_precomputed_build
wiring tests. Pins that the state-builder build-shadow hook reads coach + lc,
classifies the enemy comp, records a covered hit / coverage miss / nothing on a
lobby tick, and never raises. Monkeypatches the table loader + classifier so it
is data-independent; writes to a tmp path.
"""
from __future__ import annotations

import json

from dashboard import _deterministic_coaching as dc


def _payload():
    return {
        "schema": "build_order_variants/v1",
        "build_orders": {
            "Ahri": {
                "anti_tank": {"variant": "anti_tank", "order": ["3135"],
                              "bias": {}, "antitank": {"recommend_antitank_items": True}},
                "anti_squishy": {"variant": "anti_squishy", "order": ["3157"],
                                 "bias": {}, "antitank": {}},
            },
        },
    }


def _patch(monkeypatch, n=5, front=3):
    import core.build_order_variants as bov
    import core.precomputed_build_coach as pbc
    monkeypatch.setattr(bov, "load_build_order_variants",
                        lambda mode="sr", patch=None: _payload())
    monkeypatch.setattr(pbc, "compute_factors",
                        lambda comp: {"n": n, "frontline_count": front})


def _read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_wiring_covered_hit(tmp_path, monkeypatch):
    _patch(monkeypatch, n=5, front=3)
    p = tmp_path / "b.jsonl"
    coach = {"champion": "Ahri", "game_time_s": 600.0}
    # lc carries champion: the HZ-D4 gate requires a LIVE liveclient tick.
    lc = {"champion": "Ahri", "enemy_team": ["Malphite", "Ornn", "Sion"],
          "owned_items": ["x"]}
    dc.shadow_log_precomputed_build(coach, lc, "sr", path=p)
    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["my_champion"] == "Ahri"
    assert r["lean"] == "anti_tank"
    assert r["covered"] is True
    assert len(r["choices"]) == 2
    assert r["choices"][0]["source_tag"] == "ds-precompute-build"


def test_wiring_coverage_miss_recorded(tmp_path, monkeypatch):
    _patch(monkeypatch, n=5, front=3)
    p = tmp_path / "b.jsonl"
    # Yasuo not in the synthetic table -> lean resolves but champ uncovered.
    coach = {"champion": "Yasuo"}
    lc = {"champion": "Yasuo", "enemy_team": ["Malphite", "Ornn"]}
    dc.shadow_log_precomputed_build(coach, lc, "sr", path=p)
    rows = _read(p)
    assert len(rows) == 1
    assert rows[0]["covered"] is False
    assert rows[0]["choices"] == []


def test_wiring_no_champion_no_record(tmp_path, monkeypatch):
    _patch(monkeypatch)
    p = tmp_path / "b.jsonl"
    dc.shadow_log_precomputed_build({}, {"enemy_team": ["Malphite"]}, "sr", path=p)
    assert not p.exists()


def test_wiring_never_raises(tmp_path, monkeypatch):
    import core.build_order_variants as bov
    import core.precomputed_build_coach as pbc

    # Non-None lean so the flow reaches the raising loader (not the early
    # coverage-miss log path).
    monkeypatch.setattr(pbc, "compute_factors",
                        lambda comp: {"n": 5, "frontline_count": 3})

    def _boom(mode="sr", patch=None):
        raise RuntimeError("variants table read blew up")

    monkeypatch.setattr(bov, "load_build_order_variants", _boom)
    p = tmp_path / "b.jsonl"
    dc.shadow_log_precomputed_build(
        {"champion": "Ahri"},
        {"champion": "Ahri", "enemy_team": ["Malphite"]}, "sr", path=p)
    assert not p.exists()
