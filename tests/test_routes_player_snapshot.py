"""Contract tests for /api/player-snapshot and its helpers (player-snapshot card)."""
import json
import sqlite3

from core import player_gpi
from dashboard import routes_player_snapshot as rps
from tests.test_player_gpi_window import _seed, _rows   # reuse the seed helpers


def _gpi(strongest, weakest, versat=70.0, consist=40.0):
    axes = [
        {"key": "aggression", "score": 80.0, "scoring": "relative"},
        {"key": "farming", "score": 30.0, "scoring": "relative"},
        {"key": "vision", "score": 50.0, "scoring": "relative"},
        {"key": "objectives", "score": 55.0, "scoring": "relative"},
        {"key": "survival", "score": 45.0, "scoring": "relative"},
        {"key": "tempo", "score": 60.0, "scoring": "relative"},
        {"key": "versatility", "score": versat, "scoring": "absolute"},
        {"key": "consistency", "score": consist, "scoring": "absolute"},
    ]
    return {"axes": axes, "strongest_axis": strongest, "weakest_axis": weakest}


def test_tags_are_three_with_correct_tones_and_words():
    tags = rps._derive_snapshot_tags(_gpi("aggression", "farming"))
    assert len(tags) == 3
    assert tags[0] == {"label": "Aggressive", "tone": "strong"}
    assert tags[2] == {"label": "Weak Farm", "tone": "weak"}
    # neutral slot is the shape axis (versatility 70 > consistency 40) high word.
    assert tags[1] == {"label": "Generalist", "tone": "neutral"}


def test_neutral_slot_uses_consistency_when_it_dominates():
    tags = rps._derive_snapshot_tags(_gpi("tempo", "vision", versat=20.0, consist=85.0))
    assert tags[1] == {"label": "Consistent", "tone": "neutral"}


class _FakeHandler:
    def __init__(self, path):
        self.path = path
        self.status = None
        self.body = None
    def _send(self, status, body, ctype):
        self.status = status
        self.body = json.loads(body.decode("utf-8"))


def test_build_model_shape_and_bands():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    gpi = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=now - 24 * 3600_000)
    model = rps._build_snapshot_model(gpi, "sr", 24)
    assert set(model) >= {"header", "dial", "minis", "bars", "tags",
                          "profile_ref", "confidence", "sample_n", "empty"}
    assert model["empty"] is False
    assert len(model["tags"]) == 3
    assert {b["key"] for b in model["bars"]} == {"income", "combat", "objectives", "vision"}
    assert {m["key"] for m in model["minis"]} == {"kda", "winrate", "kp"}
    kp = next(m for m in model["minis"] if m["key"] == "kp")
    assert kp["provenance"] == "inferred"
    assert model["dial"]["band"] in {"good", "ok", "poor"}
    assert model["profile_ref"]["mode"] == "sr"
    assert next(m for m in model["minis"] if m["key"] == "kda")["value"] != "-"


def test_empty_window_returns_empty_model_no_error():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    # A window in the far past -> zero games inside it.
    gpi = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=now + 3600_000)
    model = rps._build_snapshot_model(gpi, "sr", 24)
    assert model["empty"] is True
    assert model["confidence"] in {"insufficient", "low"}


def test_route_never_leaks_raw_error():
    h = _FakeHandler("/api/player-snapshot?mode=sr&hours=24")
    rps._serve_player_snapshot(h)          # real DB path; must not raise
    assert h.status == 200
    assert h.body.get("empty") in (True, False)   # a valid model either way


def test_route_registered_with_dispatch():
    from dashboard import _dispatch
    routes = _dispatch._gather_get()       # memoized _GET_CACHE builder
    def _safe(pred):
        try:
            return bool(pred("/api/player-snapshot"))
        except Exception:  # noqa: BLE001
            return False
    assert any(_safe(pred) for pred, _h in routes), \
        "/api/player-snapshot not registered with dispatch"
