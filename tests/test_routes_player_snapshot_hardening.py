"""Hardening tests for /api/player-snapshot (s144 true-audit cycle 110, RM-1445).

Each test pins one audited weakness of dashboard/routes_player_snapshot.py:

- a flat profile (strongest axis == weakest axis) must not tag the SAME axis
  both "Aggressive" and "Passive";
- an unknown or missing axis key must neither crash the whole card into the
  degraded model nor fabricate a tag for an axis the profile never named;
- the model's ``confidence`` must describe the requested time window, not the
  full-history window compute_gpi judged it on;
- ``hours`` is validated (ASCII digits only) and clamped to a sane maximum;
- the degraded model is flagged, friendly, logged WITH a traceback and never
  carries the raw error text;
- a client that hangs up mid-response is not mistaken for a route failure and
  is not written to a second time.

compute_gpi is monkeypatched in every route-level test, so nothing here
reads the live rewind DB.
"""
from __future__ import annotations

import json
import logging
import sqlite3

import pytest

from core import player_gpi
from dashboard import routes_player_snapshot as rps

_RAW = "database is locked: <repo>/secret/rewind_history.db token=abc123"


def _axes(scores: dict[str, float] | None = None) -> list[dict]:
    base = {
        "aggression": 80.0, "farming": 30.0, "vision": 50.0,
        "objectives": 55.0, "survival": 45.0, "tempo": 60.0,
        "versatility": 70.0, "consistency": 40.0,
    }
    base.update(scores or {})
    return [{"key": k, "score": v} for k, v in base.items()]


def _gpi(**over) -> dict:
    gpi = {
        "axes": _axes(),
        "strongest_axis": "aggression",
        "weakest_axis": "farming",
        "window_n": 12,
        "confidence": "high",
        "overall": 54.0,
        "win_rate": 0.5,
        "kp_pct": 48.0,
        "kda_mean": 2.5,
        "win_streak": {"kind": "win", "n": 2},
        "this_match": {"champion_id": 222},
    }
    gpi.update(over)
    return gpi


class _Handler:
    def __init__(self, path: str, fail_send: BaseException | None = None):
        self.path = path
        self.calls: list[tuple[int, bytes, str]] = []
        self._fail = fail_send

    def _send(self, status, body, ctype):
        self.calls.append((status, body, ctype))
        if self._fail is not None:
            raise self._fail

    @property
    def body(self) -> dict:
        return json.loads(self.calls[-1][1].decode("utf-8"))


def _patch_gpi(monkeypatch, result=None, exc=None):
    seen: dict = {}

    def fake(mode="sr", since_ts=None, **_kw):
        seen["mode"] = mode
        seen["since_ts"] = since_ts
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(rps.player_gpi, "compute_gpi", fake)
    return seen


# ---- tags -----------------------------------------------------------------

def test_flat_profile_never_tags_one_axis_strong_and_weak():
    flat = dict.fromkeys(("aggression", "farming", "vision", "objectives", "survival", "tempo"), 50.0)
    # compute_gpi's max()/min() both pick the FIRST axis on a full tie.
    gpi = _gpi(axes=_axes(flat), strongest_axis="aggression",
               weakest_axis="aggression")
    labels = [t["label"] for t in rps._derive_snapshot_tags(gpi)]
    assert not ("Aggressive" in labels and "Passive" in labels), labels
    # A flat profile has no strongest axis either: the first-in-order pick
    # is arbitrary, so both skill slots drop and the shape tag remains.
    assert [t["tone"] for t in rps._derive_snapshot_tags(gpi)] == ["neutral"]


def test_whole_history_window_is_flat_on_real_compute_gpi():
    # The flat profile is not synthetic: when the window holds the whole
    # history, every relative axis is the mean midrank percentile of the full
    # set, exactly 50, and compute_gpi names one axis strongest AND weakest.
    from tests.test_player_gpi_window import _rows, _seed
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    try:
        _seed(conn, _rows(20, now))
        gpi = player_gpi.compute_gpi(mode="sr", conn=conn,
                                     since_ts=now - 24 * 3600_000)
    finally:
        conn.close()
    assert gpi["strongest_axis"] == gpi["weakest_axis"]
    model = rps._build_snapshot_model(gpi, "sr", 24)
    assert [t["tone"] for t in model["tags"]] == ["neutral"]


def test_unknown_axis_key_does_not_raise_or_fabricate():
    gpi = _gpi(strongest_axis="mechanics", weakest_axis="macro")
    tags = rps._derive_snapshot_tags(gpi)
    tones = [t["tone"] for t in tags]
    assert "strong" not in tones and "weak" not in tones
    assert tones == ["neutral"]


def test_missing_axis_keys_do_not_fabricate_default_tags():
    gpi = _gpi(strongest_axis=None, weakest_axis=None)
    labels = [t["label"] for t in rps._derive_snapshot_tags(gpi)]
    assert "Aggressive" not in labels
    assert "Weak Farm" not in labels


def test_shape_axis_is_never_a_strong_or_weak_tag():
    # Spec 4.6: shape axes are barred from the red slot (and are not skill
    # strengths either); a shape key in those slots is dropped, not rendered.
    gpi = _gpi(strongest_axis="versatility", weakest_axis="consistency")
    tags = rps._derive_snapshot_tags(gpi)
    assert [t["tone"] for t in tags] == ["neutral"]


def test_malformed_axis_entries_are_skipped_not_fatal():
    gpi = _gpi(axes=[None, {"score": 9.0}, {"key": 7}] + _axes())
    model = rps._build_snapshot_model(gpi, "sr", 24)
    assert model["empty"] is False
    assert {b["key"]: b["score"] for b in model["bars"]}["combat"] == 80.0


def test_route_with_unknown_axis_still_serves_the_real_model(monkeypatch):
    _patch_gpi(monkeypatch, result=_gpi(strongest_axis="mechanics"))
    h = _Handler("/api/player-snapshot?mode=sr&hours=24")
    rps._serve_player_snapshot(h)
    assert h.body["empty"] is False
    assert h.body.get("degraded") is not True
    assert h.body["dial"]["value"] == 54


# ---- confidence -----------------------------------------------------------

def test_confidence_reflects_the_requested_window(monkeypatch):
    # compute_gpi judges "high" on the full-history window; a 24 h window
    # holding 2 games is a low-confidence snapshot.
    model = rps._build_snapshot_model(_gpi(window_n=2, confidence="high"),
                                      "sr", 24)
    assert model["confidence"] == "low"
    full = rps._build_snapshot_model(
        _gpi(window_n=player_gpi.MIN_GAMES, confidence="high"), "sr", 24)
    assert full["confidence"] == "high"


# ---- hours validation -----------------------------------------------------

@pytest.mark.parametrize("raw", ["9" * 40, "99999", str(rps.MAX_HOURS + 1)])
def test_hours_is_clamped_to_a_maximum(monkeypatch, raw):
    seen = _patch_gpi(monkeypatch, result=_gpi())
    h = _Handler("/api/player-snapshot?mode=sr&hours=" + raw)
    rps._serve_player_snapshot(h)
    cap = rps.MAX_HOURS
    assert h.body["dial"]["label"] == f"SR last {cap}h"
    assert h.body["profile_ref"]["window"] == f"{cap}h"
    assert seen["since_ts"] > 0


@pytest.mark.parametrize("raw", ["1_2", "\u0661\u0662", "-5", "abc", "", "1e3"])
def test_non_ascii_digit_hours_fall_back_to_default(monkeypatch, raw):
    _patch_gpi(monkeypatch, result=_gpi())
    h = _Handler("/api/player-snapshot?mode=sr&hours=" + raw)
    rps._serve_player_snapshot(h)
    assert h.body["profile_ref"]["window"] == "24h", raw


def test_zero_hours_clamps_to_one(monkeypatch):
    _patch_gpi(monkeypatch, result=_gpi())
    h = _Handler("/api/player-snapshot?mode=aram&hours=0")
    rps._serve_player_snapshot(h)
    assert h.body["profile_ref"]["window"] == "1h"
    assert h.body["profile_ref"]["mode"] == "aram"


# ---- degraded path --------------------------------------------------------

def test_degraded_model_is_flagged_friendly_and_logged(monkeypatch, caplog):
    _patch_gpi(monkeypatch, exc=sqlite3.OperationalError(_RAW))
    h = _Handler("/api/player-snapshot?mode=arena&hours=48")
    with caplog.at_level(logging.WARNING, logger=rps.__name__):
        rps._serve_player_snapshot(h)
    assert len(h.calls) == 1
    status, raw_body, _ctype = h.calls[0]
    assert status == 200
    body = h.body
    assert body["empty"] is True
    assert body["degraded"] is True
    assert body["dial"]["label"] == rps.DEGRADED_LABEL
    assert body["profile_ref"] == {"mode": "arena", "window": "48h",
                                   "match_id": None}
    assert "locked" not in raw_body.decode("utf-8")
    assert "abc123" not in raw_body.decode("utf-8")
    recs = [r for r in caplog.records if r.name == rps.__name__]
    assert recs and recs[-1].exc_info is not None


def test_normal_model_is_not_flagged_degraded(monkeypatch):
    _patch_gpi(monkeypatch, result=_gpi())
    h = _Handler("/api/player-snapshot?mode=sr&hours=24")
    rps._serve_player_snapshot(h)
    assert h.body.get("degraded", False) is False


# ---- client disconnect ----------------------------------------------------

def test_client_disconnect_is_not_a_route_failure(monkeypatch, caplog):
    _patch_gpi(monkeypatch, result=_gpi())
    h = _Handler("/api/player-snapshot?mode=sr&hours=24",
                 fail_send=ConnectionAbortedError(10053, "aborted"))
    with caplog.at_level(logging.WARNING, logger=rps.__name__):
        rps._serve_player_snapshot(h)          # must not raise
    assert len(h.calls) == 1, "a hung-up client was written to twice"
    assert not [r for r in caplog.records
                if r.name == rps.__name__ and r.levelno >= logging.WARNING]


def test_degraded_send_disconnect_is_swallowed(monkeypatch):
    _patch_gpi(monkeypatch, exc=sqlite3.OperationalError("x"))
    h = _Handler("/api/player-snapshot", fail_send=BrokenPipeError())
    rps._serve_player_snapshot(h)              # must not raise
    assert len(h.calls) == 1


def test_programming_error_in_send_is_not_swallowed(monkeypatch):
    _patch_gpi(monkeypatch, exc=sqlite3.OperationalError("x"))
    h = _Handler("/api/player-snapshot", fail_send=TypeError("bad sig"))
    with pytest.raises(TypeError):
        rps._serve_player_snapshot(h)
