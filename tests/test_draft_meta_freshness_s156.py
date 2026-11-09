"""s156 S3: staleness signal for the hand-curated draft meta files.

champion_counters.json and global_top_bans.json have no sound first-party
refresh source, so the draft routes now report how stale they are instead of
presenting a 16.10.1 list as current.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from core import draft_meta_freshness as f

_REPO = Path(__file__).resolve().parent.parent
_TODAY = dt.date(2026, 11, 8)


def test_stale_doc_reports_patch_gap_and_age():
    out = f.meta_freshness({"patch": "16.10.1", "updated": "2026-05-15"},
                           current_patch="16.22.1", today=_TODAY)
    assert out == {
        "source_patch": "16.10.1", "source_updated": "2026-05-15",
        "current_patch": "16.22.1", "patches_behind": 12, "age_days": 177,
        "stale": True,
    }


def test_current_doc_is_not_stale():
    out = f.meta_freshness({"patch": "16.22.1", "updated": "2026-11-05"},
                           current_patch="16.22.1", today=_TODAY)
    assert out["stale"] is False
    assert out["patches_behind"] == 0
    assert out["age_days"] == 3


@pytest.mark.parametrize("doc", [
    None, [], "x", {}, {"patch": 16.1}, {"patch": "latest"},
    {"patch": "16.10.1", "updated": "May 15"}, {"updated": "2026-13-40"},
])
def test_malformed_docs_degrade_to_unknown_and_stale(doc):
    out = f.meta_freshness(doc, current_patch="16.22.1", today=_TODAY)
    assert out["stale"] is True
    assert set(out) == {"source_patch", "source_updated", "current_patch",
                        "patches_behind", "age_days", "stale"}


def test_major_version_change_has_no_patch_count_but_is_stale():
    out = f.meta_freshness({"patch": "15.24.1"}, current_patch="16.1.1",
                           today=_TODAY)
    assert out["patches_behind"] is None
    assert out["stale"] is True


def test_unknown_current_patch_is_stale(tmp_path):
    assert f.current_ddragon_patch(tmp_path / "absent.json") is None
    out = f.meta_freshness({"patch": "16.22.1"}, current_patch="garbage",
                           today=_TODAY)
    assert out["current_patch"] is None
    assert out["stale"] is True


def test_current_patch_reads_the_tracked_ddragon_version():
    want = json.loads((_REPO / "data" / "meta" / "ddragon_version.json")
                      .read_text(encoding="utf-8"))["version"]
    assert f.current_ddragon_patch() == want


@pytest.mark.parametrize("name", ["champion_counters.json", "global_top_bans.json"])
def test_tracked_meta_files_carry_a_readable_stamp(name):
    # The signal is only honest if the curated files keep their stamp.
    doc = json.loads((_REPO / "data" / "meta" / name).read_text(encoding="utf-8"))
    out = f.meta_freshness(doc, current_patch="16.22.1", today=_TODAY)
    assert out["source_patch"] is not None
    assert out["source_updated"] is not None
