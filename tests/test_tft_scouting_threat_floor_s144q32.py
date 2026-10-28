"""RM-1101: the scouting threat score's recent-games floor is one named constant.

tft_scouting.compute_threat compared an opponent's recent-sample size against a
bare literal 3 in two places (the "unknown" verdict and the placement term of
the score) and read the size as ``sample.get("n") or 0``, which lets a digit
string (a TypeError at the comparison), a float (3.0 passes the floor and
prints "(last 3.0)") and a bool (True reads as 1 game) through.

The floor is NOT comps.MIN_GAMES: that one is the lobby-wide aggregate row's
floor in tft/engine, a different population (one opponent's last DEFAULT_N
matches here), and tft_scouting does not import the engine. A retune of the
engine floor must not move the scouting verdict, so the scouting module names
its own constant, MIN_THREAT_GAMES.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from tft import tft_scouting as TS
from tft.engine import comps

GOLD = {"ranked": True, "tier": "GOLD", "division": "II", "lp": 10, "wins": 0,
        "losses": 0, "games": 0, "display": "GOLD II 10 LP"}


def _sample(n, avg=2.0, top4=0.8):
    return {"n": n, "avg_placement": avg, "top4_rate": top4}


def _threat(rank, n, **kw):
    return TS.compute_threat(rank, _sample(n, **kw), {"kind": "none", "length": 0}, [], [])


def test_floor_is_a_named_int_constant():
    assert isinstance(TS.MIN_THREAT_GAMES, int) and not isinstance(TS.MIN_THREAT_GAMES, bool)
    assert TS.MIN_THREAT_GAMES == 3


def test_compute_threat_compares_no_bare_int_literal():
    """AST guard: no Compare on the sample size `n` in compute_threat has an int literal
    operand above 1 (0 / 1 stay legal: `n != 1` is the plural check, not a floor). The
    score / streak thresholds compare other names and are not this floor."""
    tree = ast.parse(inspect.getsource(TS.compute_threat))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            ops = [node.left, *node.comparators]
            if not any(isinstance(op, ast.Name) and op.id == "n" for op in ops):
                continue
            for op in ops:
                if (isinstance(op, ast.Constant) and type(op.value) is int
                        and op.value > 1):
                    bad.append((node.lineno, op.value))
    assert bad == []
    sites = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)
             and any(isinstance(op, ast.Name) and op.id == "MIN_THREAT_GAMES"
                     for op in [node.left, *node.comparators])]
    assert len(sites) == 2  # the "unknown" verdict and the placement term


def test_unranked_boundary():
    below = _threat(None, TS.MIN_THREAT_GAMES - 1)
    assert below["level"] == "unknown" and below["score"] is None
    at = _threat(None, TS.MIN_THREAT_GAMES)
    assert at["level"] != "unknown" and isinstance(at["score"], int)


def test_ranked_below_floor_ignores_the_placement_term():
    """Ranked with too few games: scored from the rank alone, the avg term is off."""
    good = _threat(GOLD, TS.MIN_THREAT_GAMES - 1, avg=1.0, top4=1.0)
    bad = _threat(GOLD, TS.MIN_THREAT_GAMES - 1, avg=8.0, top4=0.0)
    assert good["score"] == bad["score"]
    good_at = _threat(GOLD, TS.MIN_THREAT_GAMES, avg=1.0, top4=1.0)
    bad_at = _threat(GOLD, TS.MIN_THREAT_GAMES, avg=8.0, top4=0.0)
    assert good_at["score"] > bad_at["score"]


def test_both_sites_read_the_constant(monkeypatch):
    monkeypatch.setattr(TS, "MIN_THREAT_GAMES", 5)
    assert _threat(None, 4)["level"] == "unknown"
    a = _threat(GOLD, 4, avg=1.0, top4=1.0)
    b = _threat(GOLD, 4, avg=8.0, top4=0.0)
    assert a["score"] == b["score"]
    assert _threat(None, 5)["level"] != "unknown"


def test_engine_floor_retune_does_not_move_scouting(monkeypatch):
    before = _threat(None, 3)
    monkeypatch.setattr(comps, "MIN_GAMES", 7)
    assert _threat(None, 3) == before
    assert before["level"] != "unknown"


@pytest.mark.parametrize("junk", ["3", "10", 3.0, 10.0, True, -4, None, [3], float("nan")])
def test_non_int_sample_size_is_no_evidence(junk):
    """Only a plain positive int is a game count; anything else reads as 0 games."""
    t = _threat(None, junk)
    assert t == {"level": "unknown", "score": None,
                 "summary": "Rank unknown - no recent TFT games"}


@pytest.mark.parametrize("junk", ["3", 3.0, True])
def test_ranked_junk_size_keeps_the_placement_term_off(junk):
    good = _threat(GOLD, junk, avg=1.0, top4=1.0)
    bad = _threat(GOLD, junk, avg=8.0, top4=0.0)
    assert good["score"] == bad["score"]
    assert good["summary"] == "GOLD II 10 LP"  # no "avg ... (last 3.0)" from a junk count


def test_build_digest_still_counts_real_rows():
    """The producer writes n as an int, so the real path is unchanged."""
    row = {"placement": 2, "ts_s": 1, "game_type": "standard", "set": 18,
           "traits": [], "units": []}
    rows = [dict(row, ts_s=i, placement=p) for i, p in enumerate([1, 2, 3], start=1)]
    d = TS.build_digest(TS.Identity("Opp", "TST"), None, rows)
    assert d["sample"]["n"] == 3
    assert d["threat"]["level"] != "unknown"
    assert "(last 3)" in d["threat"]["summary"]
