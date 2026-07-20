"""Tests for core.aram_item_interaction_context (RM-111 consumer loader).

The loader reads an OFFLINE-precomputed snapshot
(``data/coaching/aram_item_interaction.json``, written by
``tools/aram_item_interaction_precompute.py``) and renders one short cue per
item on the build path. These tests point the module at a tmp_path fixture via
the ``_load_index(path=...)`` seam, so nothing here touches the gitignored
``data/rewind_history.db`` or a real ``data/coaching/`` file.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from core import aram_item_interaction_context as ctx
from core.aram_item_interaction import champion_names_by_id, comp_shape

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import aram_item_interaction_precompute as precompute  # noqa: E402

# The shape an EMPTY enemy list resolves to: compute_factors([]) yields zero
# ad/ap/frontline counts, so shape_from_factors returns mixed + fl_none.
SHAPE = "mixed/fl_none"


def _cell(**over) -> dict:
    base = {
        "shape": SHAPE,
        "item_id": 3153,
        "name": "Blade of the Ruined King",
        "timing": "mid",
        "n": 27,
        "winrate": 0.6296,
        "winrate_smoothed": 0.5812,
        "expected_winrate": 0.5,
        "wpa": 0.1296,
        "wpa_shrunk": 0.05,
        "gold_swing": 310.4,
        "n_gold_swing": 20,
        "avg_purchase_time_s": 700.0,
    }
    base.update(over)
    return base


def _write(tmp_path, cells, **envelope) -> "object":
    payload = {
        "schema": "aram_item_interaction/v1",
        "patch": "16.14.1",
        "matches": 2049,
        "generated_note": "offline precompute",
        "cells": cells,
    }
    payload.update(envelope)
    path = tmp_path / "aram_item_interaction.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _reset_index():
    ctx._INDEX = None
    yield
    ctx._INDEX = None


def _point_at(path):
    ctx._INDEX = ctx._load_index(path)


# ---------------------------------------------------------------- hit / miss

def test_hit_cell_renders_expected_cue(tmp_path):
    _point_at(_write(tmp_path, [_cell()]))
    out = ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    )
    assert out == {"Blade of the Ruined King": "58% n=27 +310g"}


def test_missing_cell_renders_sentinel_and_keeps_key(tmp_path):
    _point_at(_write(tmp_path, [_cell()]))
    out = ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King", "Nashor's Tooth"], game_mode="ARAM"
    )
    assert set(out) == {"Blade of the Ruined King", "Nashor's Tooth"}
    assert out["Nashor's Tooth"] == ctx.CUE_SENTINEL
    assert ctx.CUE_SENTINEL == "-"


def test_gold_swing_none_omits_gold_clause(tmp_path):
    _point_at(_write(tmp_path, [_cell(gold_swing=None, n_gold_swing=0)]))
    out = ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    )
    assert out == {"Blade of the Ruined King": "58% n=27"}


def test_negative_gold_swing_is_signed(tmp_path):
    _point_at(_write(tmp_path, [_cell(gold_swing=-210.6)]))
    out = ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    )
    assert out == {"Blade of the Ruined King": "58% n=27 -211g"}


def test_case_insensitive_name_fallback(tmp_path):
    _point_at(_write(tmp_path, [_cell()]))
    out = ctx.item_interaction_cues(
        [], 600.0, ["blade of the ruined king"], game_mode="ARAM"
    )
    assert out["blade of the ruined king"] == "58% n=27 +310g"


def test_cue_length_budget(tmp_path):
    _point_at(_write(tmp_path, [_cell()]))
    out = ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    )
    assert len(out["Blade of the Ruined King"]) <= 18


# ---------------------------------------------------------------- empty dict

@pytest.mark.parametrize("mode", ["CLASSIC", "CHERRY", "TFT", None, ""])
def test_non_aram_mode_returns_empty(tmp_path, mode):
    _point_at(_write(tmp_path, [_cell()]))
    assert ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode=mode
    ) == {}


def test_aram_mode_aliases_are_accepted(tmp_path):
    _point_at(_write(tmp_path, [_cell()]))
    for mode in ("ARAM", "aram", "KIWI", "ARAM_MAYHEM"):
        out = ctx.item_interaction_cues(
            [], 600.0, ["Blade of the Ruined King"], game_mode=mode
        )
        assert out, mode


def test_absent_snapshot_returns_empty(tmp_path):
    ctx._INDEX = ctx._load_index(tmp_path / "nope.json")
    assert ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    ) == {}


def test_unparseable_snapshot_returns_empty(tmp_path):
    bad = tmp_path / "aram_item_interaction.json"
    bad.write_text("{not json", encoding="utf-8")
    ctx._INDEX = ctx._load_index(bad)
    assert ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    ) == {}


def test_empty_item_names_returns_empty(tmp_path):
    _point_at(_write(tmp_path, [_cell()]))
    assert ctx.item_interaction_cues([], 600.0, [], game_mode="ARAM") == {}


# ------------------------------------------------------------ timing buckets

def test_timing_bucket_boundaries(tmp_path):
    cells = [
        _cell(timing="early", n=11, winrate_smoothed=0.41, gold_swing=None),
        _cell(timing="mid", n=27, winrate_smoothed=0.5812, gold_swing=310.4),
        _cell(timing="late", n=33, winrate_smoothed=0.62, gold_swing=None),
    ]
    _point_at(_write(tmp_path, cells))
    name = "Blade of the Ruined King"

    def cue(t):
        return ctx.item_interaction_cues([], t, [name], game_mode="ARAM")[name]

    assert cue(479.0) == "41% n=11"       # early upper edge
    assert cue(480.0) == "58% n=27 +310g"  # mid lower edge (inclusive)
    assert cue(899.0) == "58% n=27 +310g"  # mid upper edge
    assert cue(900.0) == "62% n=33"       # late lower edge (inclusive)


# --------------------------------------------------------- shape resolution

def _sample_ids() -> list[int]:
    names = champion_names_by_id()
    assert names, "champion catalog unavailable"
    return sorted(names)[:5]


def test_shape_resolves_from_numeric_ids(tmp_path):
    ids = _sample_ids()
    shape = comp_shape(ids)
    _point_at(_write(tmp_path, [_cell(shape=shape)]))
    out = ctx.item_interaction_cues(
        ids, 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    )
    assert out["Blade of the Ruined King"] == "58% n=27 +310g"


def test_shape_resolves_from_display_names(tmp_path):
    ids = _sample_ids()
    names = champion_names_by_id()
    display = [names[i] for i in ids]
    shape = comp_shape(ids)
    _point_at(_write(tmp_path, [_cell(shape=shape)]))
    out = ctx.item_interaction_cues(
        display, 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    )
    assert out["Blade of the Ruined King"] == "58% n=27 +310g"


def test_shape_mismatch_yields_sentinel(tmp_path):
    other = "ad_heavy/fl_heavy" if SHAPE != "ad_heavy/fl_heavy" else "ap_heavy/fl_none"
    _point_at(_write(tmp_path, [_cell(shape=other)]))
    out = ctx.item_interaction_cues(
        [], 600.0, ["Blade of the Ruined King"], game_mode="ARAM"
    )
    assert out == {"Blade of the Ruined King": ctx.CUE_SENTINEL}


# ------------------------------------------------------------- provenance

def test_cue_provenance_renders(tmp_path):
    _point_at(_write(tmp_path, [_cell()]))
    prov = ctx.cue_provenance()
    assert prov == "own ARAM corpus n=2049 patch=16.14.1"
    assert prov.isascii()


def test_cue_provenance_empty_without_snapshot(tmp_path):
    ctx._INDEX = ctx._load_index(tmp_path / "nope.json")
    assert ctx.cue_provenance() == ""


def test_cue_provenance_renders_patch_range(tmp_path):
    _point_at(_write(tmp_path, [_cell()],
                     patch=None, patch_min="13.16", patch_max="15.17"))
    prov = ctx.cue_provenance()
    assert prov == "own ARAM corpus n=2049 patches 13.16-15.17"
    assert prov.isascii()
    # ASCII hyphen only - an en/em-dash here would violate the repo hard rule.
    assert chr(0x2013) not in prov and chr(0x2014) not in prov
    assert "13.16-15.17" in prov


def test_cue_provenance_collapses_pinned_patch(tmp_path):
    _point_at(_write(tmp_path, [_cell()],
                     patch="15.17", patch_min="15.17", patch_max="15.17"))
    assert ctx.cue_provenance() == "own ARAM corpus n=2049 patch=15.17"


def test_cue_provenance_range_wins_over_legacy_patch_field(tmp_path):
    _point_at(_write(tmp_path, [_cell()],
                     patch="16.14.1", patch_min="13.16", patch_max="15.17"))
    assert ctx.cue_provenance() == "own ARAM corpus n=2049 patches 13.16-15.17"


def test_cue_provenance_falls_back_to_legacy_patch_when_range_absent(tmp_path):
    # No patch_min/patch_max at all: the pre-range payload shape still renders.
    _point_at(_write(tmp_path, [_cell()]))
    assert ctx.cue_provenance() == "own ARAM corpus n=2049 patch=16.14.1"


def test_cue_provenance_omits_clause_when_no_patch_info(tmp_path):
    _point_at(_write(tmp_path, [_cell()],
                     patch=None, patch_min=None, patch_max=""))
    assert ctx.cue_provenance() == "own ARAM corpus n=2049"


# ------------------------------------------------------- numeric patch sort

def test_patch_sort_key_is_numeric_not_lexical():
    # THE bug a lexical sort introduces: "15.9" > "15.13" as text, but 15.9
    # is the OLDER patch and must sort first.
    assert precompute._patch_sort_key("15.9") < precompute._patch_sort_key("15.13")
    assert "15.9" > "15.13"  # the lexical comparison this guards against
    assert precompute._patch_sort_key("13.16") < precompute._patch_sort_key("15.17")
    assert precompute._patch_sort_key("9.24") < precompute._patch_sort_key("10.1")


def test_patch_sort_orders_full_corpus_range():
    patches = ["15.13", "13.16", "15.9", "14.2", "15.17", "13.9"]
    ordered = sorted(patches, key=precompute._patch_sort_key)
    assert ordered[0] == "13.9"
    assert ordered[-1] == "15.17"
    assert ordered == ["13.9", "13.16", "14.2", "15.9", "15.13", "15.17"]


def test_patch_sort_key_tolerates_malformed():
    assert precompute._patch_sort_key("") == (-1, -1)
    assert precompute._patch_sort_key("abc.def") == (-1, -1)
    assert precompute._patch_sort_key("15") == (15, -1)


def test_patch_range_pinned_patch_short_circuits(tmp_path):
    # A pinned --patch never touches the db; both ends are that patch.
    assert precompute.patch_range(tmp_path / "absent.db", "15.17") == ("15.17", "15.17")


def test_patch_range_missing_db_is_fail_soft(tmp_path):
    assert precompute.patch_range(tmp_path / "absent.db") == (None, None)


def test_patch_range_reads_numeric_min_max(tmp_path):
    db = tmp_path / "mini.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, map_id INT, "
        "has_timeline INT, patch TEXT)"
    )
    rows = [
        ("a", 12, 1, "15.13"),
        ("b", 12, 1, "15.9"),
        ("c", 12, 1, "13.16"),
        ("d", 12, 1, "15.17"),
        ("e", 12, 1, None),
        ("f", 12, 1, ""),
        ("g", 11, 1, "16.14"),   # wrong map - excluded
        ("h", 12, 0, "16.14"),   # no timeline - excluded
    ]
    conn.executemany("INSERT INTO matches VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()
    assert precompute.patch_range(db) == ("13.16", "15.17")


def test_build_payload_carries_patch_range():
    payload = precompute.build_payload(
        {"patch": None, "matches": 2049, "cells": []},
        patch_min="13.16", patch_max="15.17",
    )
    assert payload["patch_min"] == "13.16"
    assert payload["patch_max"] == "15.17"
    assert payload["matches"] == 2049


def test_build_payload_defaults_range_to_none():
    payload = precompute.build_payload({"matches": 1, "cells": []})
    assert payload["patch_min"] is None
    assert payload["patch_max"] is None


# ------------------------------------------------------------- fail-soft

def test_malformed_cells_never_raise(tmp_path):
    _point_at(_write(tmp_path, ["not a dict", {"shape": SHAPE}, _cell()]))
    out = ctx.item_interaction_cues(
        [None, "Nonexistent Champ", 999999], 600.0,
        ["Blade of the Ruined King"], game_mode="ARAM",
    )
    assert set(out) == {"Blade of the Ruined King"}
