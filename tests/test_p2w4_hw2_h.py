"""P2-W4 half-wave 2, SLICE H (repo-root deep) regression tests.

Cycle 15 audit. Covers FIX-NOW defects in repo-root surface files:

1. performance_tracker._atomic_write_json must reject non-finite floats
   instead of emitting the bare ``Infinity`` / ``NaN`` JSON tokens that a
   strict reader (the dashboard rating-panel parser) rejects. The rating
   dicts carry score-derived floats (cs_per_min etc.) straight from the
   live game_state, so an upstream inf/nan would otherwise poison the
   on-disk per-mode rating file with a bare token.  Fix = allow_nan=False
   so the write raises BEFORE the tmp file lands, leaving the prior valid
   file intact (the caller already wraps the write in try/except + log).

2. riot-commander.spec must NOT pass a ``.svg`` path as the PyInstaller
   EXE icon - Windows PyInstaller only accepts ``.ico`` and hard-fails the
   build on an SVG. With no bundled ``.ico`` the correct value is None.

All tests exercise pure helpers / static source only - no live server,
no RC process, no DS restart.
"""
import json
import math
from pathlib import Path

import pytest

import performance_tracker as pt

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. Non-finite JSON token guard (friction class #1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_atomic_write_json_rejects_nonfinite(tmp_path, bad):
    """A non-finite value must NOT be serialized to a bare Infinity/NaN
    token. The writer should raise (ValueError) so the caller's try/except
    drops the update and the target file is never written with bad tokens."""
    target = tmp_path / "last_sr.json"
    with pytest.raises(ValueError):
        pt._atomic_write_json(target, {"rating": "S", "stats": {"cs_per_min": bad}})
    # Nothing torn or poisoned left behind.
    assert not target.exists()
    assert not (tmp_path / "last_sr.json.tmp").exists()


def test_atomic_write_json_finite_roundtrips(tmp_path):
    """Finite payloads still write + parse cleanly (no regression)."""
    target = tmp_path / "last_aram.json"
    payload = {"rating": "A", "stats": {"cs_per_min": 7.4, "kp": 63}, "notes": ["ok"]}
    pt._atomic_write_json(target, payload)
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_atomic_write_json_no_bare_token_on_disk(tmp_path):
    """Belt-and-suspenders: even if the guard changed, assert the produced
    file (for finite data) never contains the bare Infinity/NaN tokens a
    strict reader rejects."""
    target = tmp_path / "last_arena.json"
    pt._atomic_write_json(target, {"rating": "B", "stats": {"kda": "1/2/3"}})
    raw = target.read_text(encoding="utf-8")
    assert "Infinity" not in raw
    assert "NaN" not in raw


# ---------------------------------------------------------------------------
# 2. PyInstaller spec icon must not be an .svg (build-breaker, friction #7)
# ---------------------------------------------------------------------------

def test_spec_does_not_use_svg_icon():
    """riot-commander.spec must not feed a .svg path to EXE(icon=...);
    PyInstaller on Windows requires .ico and errors on svg."""
    spec = (REPO_ROOT / "riot-commander.spec").read_text(encoding="utf-8")
    # No icon= line may reference an .svg file.
    for line in spec.splitlines():
        stripped = line.strip()
        if stripped.startswith("icon=") or stripped.startswith("icon ="):
            assert ".svg" not in stripped, f"spec feeds svg icon to PyInstaller: {stripped!r}"


def test_calculate_rating_finite_for_zero_game(tmp_path):
    """Sanity: the score helpers never emit a non-finite grade/score even
    on a degenerate all-zero stats dict (denominators are max()-guarded)."""
    grade, notes = pt.calculate_rating(
        {"cs_per_min": 0, "deaths": 0, "kills": 0, "assists": 0,
         "game_mins": 0, "ally_kills_total": 0, "gold_per_min": 0}
    )
    assert grade in ("S", "A", "B", "C", "D", "F")
    assert isinstance(notes, list)
    # The aram/arena/brawl variants too.
    for fn in (pt.calculate_aram_rating, pt.calculate_arena_rating,
               pt.calculate_brawl_rating):
        g, n = fn({"deaths": 0, "kills": 0, "assists": 0, "game_mins": 0,
                   "ally_kills_total": 0})
        assert g in ("S", "A", "B", "C", "D", "F")


def test_enemy_damage_profile_finite_empty():
    """composition_advisor.enemy_damage_profile on an empty team must not
    divide by zero (total is max(1, ...))."""
    from composition_advisor import enemy_damage_profile
    prof = enemy_damage_profile([])
    for k in ("ad", "ap"):
        assert math.isfinite(prof[k])
