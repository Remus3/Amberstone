"""MAIN FIX 2026-10-25 1930 section 1: RC-CostHealthWatchdog exited 1 on every
15-minute run from 2026-10-24 23:15.

Two causes, both pinned here:

1. `PURPOSE_MAP` is a hand copy of the docs/COST_TRACE.md matrix and had
   fallen behind the live call sites, so the hot purpose of a TFT day
   (`tft_coach`) classified as "unmapped" and the proposal sent the reader to
   trace a call that is already wired. The guard below sweeps every
   `purpose="..."` literal in production code, so the next new purpose fails
   here instead of in the cron.
2. The baseline was the median of prior days with ANY spend, and on this box
   most days only a background warm session spends (about $0.002). Every play
   day then read as a breach (measured: 1.80 against a 0.002088 baseline) and
   latched exit 1 until local midnight. The idle floor already defines an idle
   day for TODAY; the baseline now applies the same floor to the PRIOR days.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from tests import _repo_walk

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "chw_purposes", str(_ROOT / "tools" / "cost_health_watchdog.py"))
chw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(chw)

_PURPOSE_LITERAL = re.compile(r"""purpose\s*=\s*["']([a-z0-9_]+)["']""")


def _write(p: Path, total_usd, by_purpose=None) -> None:
    p.write_text(json.dumps({"total_usd": total_usd,
                             "by_purpose": by_purpose or {}}),
                 encoding="utf-8")


def _production_purpose_literals() -> set[str]:
    found: set[str] = set()
    for path in _repo_walk.iter_repo_files(_ROOT, ("*.py",)):
        rel = _repo_walk.relative_posix(path, _ROOT)
        if rel.startswith("tests/") or "/tests/" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found.update(_PURPOSE_LITERAL.findall(text))
    return found


# ---------------------------------------------------------------- mapping

def test_tft_coach_classifies_as_haiku_not_unmapped():
    r = chw.classify({"tft_coach": {"usd": 1.191},
                      "vision_relay": {"usd": 0.382}})
    assert r["hot_purpose"] == "tft_coach"
    assert r["tier"] == "HAIKU"
    assert r["file"].startswith("tft/tft_coach_engine.py")
    assert "unmapped" not in r["proposal"]


def test_every_production_purpose_literal_is_mapped():
    literals = _production_purpose_literals()
    # Anchor: an empty or broken sweep must not pass as "all mapped".
    assert "tft_coach" in literals
    assert len(literals) >= 15, sorted(literals)
    missing = sorted(literals - set(chw.PURPOSE_MAP))
    assert missing == [], missing


@pytest.mark.parametrize("name", sorted(
    ("sr_coach", "aram_coach", "arena_coach", "brawl_coach", "coach_relay",
     "vision_relay", "vision_direct", "tft_coach", "tft_live_analysis",
     "tft_live_aug_select", "tft_vision", "agent7_warm")))
def test_every_mapped_tier_is_a_known_tier(name):
    tier, fil = chw.PURPOSE_MAP[name]
    assert tier in ("HAIKU", "SONNET")
    assert re.fullmatch(r"[A-Za-z0-9_/]+\.py:[0-9]+", fil), fil
    assert (_ROOT / fil.split(":", 1)[0]).is_file(), fil


# --------------------------------------------------------------- baseline

def test_idle_days_do_not_form_the_baseline_live_shape(tmp_path):
    """The measured 2026-10-25 ledgers: one ARAM play day, five idle days."""
    for stem, usd in (("2026-08-02", 3.018484), ("2026-08-03", 0.00055),
                      ("2026-08-06", 0.004176), ("2026-09-11", 0.002088),
                      ("2026-09-29", 0.002088), ("2026-10-04", 0.002088)):
        _write(tmp_path / f"{stem}.json", usd)
    _write(tmp_path / "2026-10-25.json", 1.800651)
    r = chw.spend_baseline(tmp_path, "2026-10-25")
    assert r["baseline_usd"] == 3.018484
    assert r["samples"] == 1
    assert r["breach"] is False


def test_a_real_spike_over_active_days_still_breaches(tmp_path):
    _write(tmp_path / "2026-05-01.json", 1.0)
    _write(tmp_path / "2026-05-02.json", 0.002)
    _write(tmp_path / "2026-05-03.json", 1.0)
    _write(tmp_path / "2026-05-04.json", 0.002)
    _write(tmp_path / "2026-05-09.json", 1.51)
    r = chw.spend_baseline(tmp_path, "2026-05-09")
    assert r["baseline_usd"] == 1.0
    assert r["breach"] is True


def test_only_idle_history_has_no_baseline(tmp_path):
    """Same rule as test_no_prior_no_breach: no comparable day, no verdict."""
    _write(tmp_path / "2026-05-01.json", 0.002)
    _write(tmp_path / "2026-05-02.json", 0.002)
    _write(tmp_path / "2026-05-09.json", 5.0)
    r = chw.spend_baseline(tmp_path, "2026-05-09")
    assert r["baseline_usd"] == 0.0
    assert r["breach"] is False


def test_live_shape_cron_run_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(chw, "probe_health", lambda *a, **k: {
        "ok": True, "pid": 1, "alive": True, "last_reload_ok": True,
        "mode": None, "age_s": 1.0})
    today = chw.date.today().isoformat()
    _write(tmp_path / "2026-08-02.json", 3.018484,
           {"aram_coach": {"usd": 1.5357, "calls": 613}})
    for stem in ("2026-09-11", "2026-09-29", "2026-10-04"):
        _write(tmp_path / f"{stem}.json", 0.002088,
               {"agent7_warm": {"usd": 0.002088, "calls": 70}})
    _write(tmp_path / f"{today}.json", 1.800651,
           {"tft_coach": {"usd": 1.191, "calls": 548},
            "vision_relay": {"usd": 0.382, "calls": 167}})
    rc = chw.main(["--spend-dir", str(tmp_path),
                   "--state", str(tmp_path / "state.json")])
    assert rc == 0
