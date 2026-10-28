"""Guard: P2-W1-dash-D cites the DS dashboard routes by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``tests/test_p2w1_dash_d.py`` (f2887158a, 2026-06-12) listed the API surfaces
it was written against as ``dashboard/<route>.py:<n>`` cites. Of the 21 line
numbers only ``stats.py:126`` points at its symbol at HEAD. About ten were
already off at f2887158a itself (statcheck, knobs, damage_mix, the archetype
import); the rest drifted since, ``data_loader.py:67`` (``DataSnapshot.load``,
now near 156) by about 90 lines. Every named symbol still exists, so the list
now names module and symbol only.

``dashboard/routes_ds_combo.py`` uppercases ``mode`` with a comment saying the
engine compares ``mode == "ARAM"`` case-sensitively. True when written; false
since RM-325 (c9bea8b07): ``compute_combo`` hands ``mode`` to
``burst.compute_burst_damage``, which folds it through
``data_loader.canonical_mode`` before any ARAM gate. The uppercase still keeps
the cache key and the echoed ``mode`` field to one spelling, so it stays and
the comment now says why.

The tests below pin each claim to the code, so a moved or renamed seam fails
here instead of leaving prose that lies.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import burst, combo, stats
from agents.daemon_slayer.data_loader import DataSnapshot
from core import archetype_picks
from dashboard import (
    routes_archetype,
    routes_damage_mix,
    routes_ds_combo,
    routes_ds_knobs,
    routes_ds_matchup,
    routes_ds_profile,
    routes_ds_relscore,
    routes_ds_statcheck,
    routes_spike_curve,
)

REPO = Path(__file__).resolve().parent.parent
P2W1 = REPO / "tests" / "test_p2w1_dash_d.py"
COMBO = REPO / "dashboard" / "routes_ds_combo.py"

_LINE_CITE = re.compile(r"\w\.py:\d")

_SURFACES = {
    routes_ds_statcheck: ("_serve_ds_statcheck", "_reset_caches", "_load_engine"),
    routes_ds_combo: ("_serve_ds_combo", "_parse_float", "_parse_level"),
    routes_ds_knobs: ("_serve_ds_knobs", "_parse_float", "_parse_budget"),
    routes_ds_relscore: ("_serve_ds_relscore",),
    routes_ds_matchup: ("_serve_ds_matchup", "_compute"),
    routes_ds_profile: ("_serve_ds_profile", "_compute"),
    routes_spike_curve: ("_serve_spike_curve", "_load_snapshot"),
    routes_damage_mix: ("_serve_damage_mix",),
    routes_archetype: ("_serve_archetype_post",),
}


def _p2w1_docstring() -> str:
    text = P2W1.read_text(encoding="utf-8")
    start = text.index('"""')
    return text[start:text.index('"""', start + 3)]


def test_citing_files_exist() -> None:
    assert P2W1.is_file(), P2W1
    assert COMBO.is_file(), COMBO


def test_p2w1_has_no_line_cites_left() -> None:
    hits = _LINE_CITE.findall(P2W1.read_text(encoding="utf-8"))
    assert not hits, f"{P2W1.name}: line cites {hits}"


def test_every_listed_surface_exists_and_is_named() -> None:
    doc = _p2w1_docstring()
    for module, names in _SURFACES.items():
        short = module.__name__.rsplit(".", 1)[-1]
        assert f"dashboard/{short}.py" in doc, short
        for name in names:
            assert callable(getattr(module, name, None)), f"{short}.{name}"
            assert f"{short}.{name}" in doc or name in doc, f"{short}.{name}"


def test_data_snapshot_load_is_a_classmethod() -> None:
    assert isinstance(inspect.getattr_static(DataSnapshot, "load"), classmethod)
    assert "DataSnapshot.load (agents/daemon_slayer/data_loader.py)" in (
        " ".join(_p2w1_docstring().split())
    )


def test_archetype_route_imports_save_at_module_level() -> None:
    assert routes_archetype.save_archetype_pick is archetype_picks.save_archetype_pick


@pytest.mark.parametrize("level", [0, 19, -1])
def test_clamp_level_raises_out_of_range(level: int) -> None:
    with pytest.raises(ValueError):
        stats.clamp_level(level)
    assert "stats.clamp_level RAISES" in _p2w1_docstring()


def test_combo_comment_no_longer_claims_case_sensitive_engine() -> None:
    text = COMBO.read_text(encoding="utf-8")
    assert "case-sensitively (burst.py / dps.py)" not in text
    assert "data_loader.canonical_mode" in text
    assert "RM-325" in text


def test_combo_route_still_uppercases_mode() -> None:
    src = inspect.getsource(routes_ds_combo._serve_ds_combo)
    assert '(qs.get("mode") or ["SR"])[0].strip().upper() or "SR"' in src


def test_combo_hands_mode_to_burst_which_folds_it_first() -> None:
    src = inspect.getsource(combo.compute_combo)
    call = src.index("compute_burst_damage(")
    assert "mode=mode" in src[call:call + 300]
    bsrc = inspect.getsource(burst.compute_burst_damage)
    assert bsrc.index("mode = canonical_mode(mode)") < bsrc.index(
        'if mode == "ARAM":'
    )


def test_combo_result_echoes_the_route_spelling() -> None:
    src = inspect.getsource(combo.compute_combo)
    ret = src.rindex("return ComboResult(")
    assert "mode=mode," in src[ret:ret + 300]
