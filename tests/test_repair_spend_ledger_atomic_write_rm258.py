"""RM-258 residual: the spend-ledger repair writes go through core.polled_json.

`_atomic_write_json` in tools/repair_spend_ledger.py hand-rolled a
destination-derived `<file>.json.tmp` plus a bare `os.replace`: no fsync, no
WinError 5 retry, and a failed rename left the scratch file behind. The
running app's cost tracker (core/cost_tracker.py) and the cost-health
watchdog poll the same data/spend/ files, so a torn or failed swap is
reader-visible. It also wrote through `Path.write_text`, which turns every LF
into CRLF on Windows (RM-481), while the live writer writes LF only.

Each test spies on `core.polled_json.atomic_write_bytes`, then checks the
exact on-disk bytes (`json.dumps(..., indent=1)` UTF-8, LF only) and that no
scratch file is left beside the ledger.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import repair_spend_ledger as rsl  # noqa: E402

_SYNTH_USD = 0.000088   # one 10-in / 20-out Haiku 4.5 call


def _mixed_day() -> dict:
    """One real lane plus one synthetic lane (the shape the repair targets)."""
    real = {"calls": 930, "usd": 3.807435, "tokens": 2965954}
    synth = {"calls": 39, "usd": round(39 * _SYNTH_USD, 6), "tokens": 39 * 30}
    return {
        "date": "2026-07-28",
        "total_usd": round(real["usd"] + synth["usd"], 6),
        "calls": 930 + 39,
        "tokens_in": 2_000_000 + 39 * 10,
        "tokens_out": 965_954 + 39 * 20,
        "cache_in": 0,
        "cache_write": 0,
        "by_model": {rsl.SYNTH_MODEL: {
            "calls": 930 + 39, "usd": round(real["usd"] + synth["usd"], 6),
            "tokens_in": 2_000_000 + 39 * 10,
            "tokens_out": 965_954 + 39 * 20,
            "cache_in": 0, "cache_write": 0,
        }},
        "by_purpose": {"sr_coach": real, "aram_coach": synth},
    }


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _scratch(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def test_day_file_write_routes_through_polled_json(tmp_path, spy):
    day = tmp_path / "2026-06-21.json"
    day.write_bytes(json.dumps(_mixed_day(), indent=1).encode("utf-8"))

    rep = rsl.repair_dir(tmp_path, dry_run=False)

    assert rep["dropped_calls"] == 39
    assert [p for p, _ in spy] == [day]
    on_disk = day.read_bytes()
    assert on_disk == spy[0][1]
    assert b"\r" not in on_disk
    doc = json.loads(on_disk)
    assert on_disk == json.dumps(doc, indent=1).encode("utf-8")
    assert set(doc["by_purpose"]) == {"sr_coach"}
    assert _scratch(tmp_path) == []


def test_sidecar_writes_route_through_polled_json(tmp_path, spy):
    open_path = tmp_path / "_match_open.json"
    open_path.write_text(json.dumps({
        "by_purpose": {"aram_coach": {"calls": 3, "usd": 0.000264}},
        "ts": 1.5}), encoding="utf-8")
    recent = tmp_path / "recent_matches.json"
    zero = {"aram": {"usd": 0.0, "tokens": 0}}
    real = {"aram": {"usd": 0.41, "tokens": 90000}}
    recent.write_text(json.dumps({"matches": [
        {"ts": 1.0, "by_gate": zero}, {"ts": 2.0, "by_gate": real}]}),
        encoding="utf-8")

    rep = rsl.repair_match_sidecars(tmp_path, dry_run=False)

    assert rep["match_open_reset"] is True
    assert rep["match_records_dropped"] == 1
    assert sorted(p.name for p, _ in spy) == [
        "_match_open.json", "recent_matches.json"]
    assert open_path.read_bytes() == b"{}"
    recent_bytes = recent.read_bytes()
    assert b"\r" not in recent_bytes
    assert json.loads(recent_bytes) == {"matches": [{"ts": 2.0, "by_gate": real}]}
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_ledger_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    day = tmp_path / "2026-06-21.json"
    before = json.dumps(_mixed_day(), indent=1).encode("utf-8")
    day.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)

    with pytest.raises(PermissionError):
        rsl.repair_dir(tmp_path, dry_run=False)

    assert day.read_bytes() == before
    assert _scratch(tmp_path) == []
