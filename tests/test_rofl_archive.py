"""Regression tests for core.rofl_archive - the forward-capture .rofl archiver.

WHY THIS EXISTS (measured 2026-07-19): replays are hard-locked to the CURRENT
game patch. `POST /lol-replays/v1/rofls/{gameId}/download` on the live LCU
returned 204 for a patch-16.13 match (ONE patch behind) and for a 14.24 match,
and `GET /lol-replays/v1/metadata/{gameId}` reported `state: "incompatible"` for
both. So a .rofl can only ever be obtained while its own patch is live, and
nothing retroactively downloads history - `data/rewind_history.db` holds 2961
matches and exactly 2 .rofl files exist on disk.

The client also prunes its Replays directory, so the only way an archive
accumulates is to copy files out of it promptly. This module is that copy step:
idempotent, atomic, and it NEVER deletes from the source.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import rofl_archive


# ---------------------------------------------------------------------------
# filename parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("NA1-5592802194.rofl", "NA1_5592802194"),
        ("NA1_5604806601.rofl", "NA1_5604806601"),
        ("EUW1-1234567890.rofl", "EUW1_1234567890"),
        ("not-a-replay.txt", None),
        ("garbage.rofl", None),
        ("NA1-notanumber.rofl", None),
    ],
)
def test_match_id_from_name(name, expected):
    assert rofl_archive.match_id_from_name(name) == expected


def test_match_id_round_trips_the_live_replay_names():
    """The two real files on disk must parse - a parser that cannot read the
    actual client naming is useless regardless of what the unit cases say."""
    assert rofl_archive.match_id_from_name("NA1-5592802194.rofl") == "NA1_5592802194"
    assert rofl_archive.match_id_from_name("NA1-5604806601.rofl") == "NA1_5604806601"


# ---------------------------------------------------------------------------
# archiving
# ---------------------------------------------------------------------------

def _seed(src, name, payload=b"ROFL-payload"):
    p = src / name
    p.write_bytes(payload)
    return p


def test_archives_a_new_replay_and_indexes_it(tmp_path):
    src, arc = tmp_path / "Replays", tmp_path / "archive"
    src.mkdir()
    _seed(src, "NA1-5592802194.rofl")

    res = rofl_archive.archive_replays(src, arc, arc / "index.json")

    assert res.copied == ["NA1_5592802194"]
    assert (arc / "NA1-5592802194.rofl").read_bytes() == b"ROFL-payload"
    idx = json.loads((arc / "index.json").read_text(encoding="utf-8"))
    assert "NA1_5592802194" in idx["replays"]
    assert idx["replays"]["NA1_5592802194"]["size"] == len(b"ROFL-payload")


def test_source_file_is_never_deleted(tmp_path):
    """The client owns that directory; we copy, we do not move."""
    src, arc = tmp_path / "Replays", tmp_path / "archive"
    src.mkdir()
    original = _seed(src, "NA1-5592802194.rofl")

    rofl_archive.archive_replays(src, arc, arc / "index.json")

    assert original.exists(), "archiver deleted the source replay"


def test_second_run_is_idempotent(tmp_path):
    src, arc = tmp_path / "Replays", tmp_path / "archive"
    src.mkdir()
    _seed(src, "NA1-5592802194.rofl")
    idx = arc / "index.json"

    first = rofl_archive.archive_replays(src, arc, idx)
    second = rofl_archive.archive_replays(src, arc, idx)

    assert first.copied == ["NA1_5592802194"]
    assert second.copied == []
    assert second.skipped == ["NA1_5592802194"]


def test_ignores_non_rofl_files(tmp_path):
    src, arc = tmp_path / "Replays", tmp_path / "archive"
    src.mkdir()
    _seed(src, "notes.txt")
    _seed(src, "garbage.rofl")

    res = rofl_archive.archive_replays(src, arc, arc / "index.json")

    assert res.copied == []
    assert not (arc / "notes.txt").exists()


def test_leaves_no_partial_file_behind(tmp_path):
    """Atomic write: a tmp artifact must never survive a successful run."""
    src, arc = tmp_path / "Replays", tmp_path / "archive"
    src.mkdir()
    _seed(src, "NA1-5592802194.rofl")

    rofl_archive.archive_replays(src, arc, arc / "index.json")

    leftovers = [p.name for p in arc.iterdir() if p.suffix == ".tmp" or p.name.endswith(".part")]
    assert not leftovers, f"partial artifacts left behind: {leftovers}"


def test_missing_source_dir_is_not_an_error(tmp_path):
    """The Replays dir may legitimately not exist yet. Degrade, do not raise."""
    res = rofl_archive.archive_replays(
        tmp_path / "nope", tmp_path / "arc", tmp_path / "arc" / "index.json"
    )
    assert res.copied == [] and res.failed == []


def test_corrupt_index_is_reported_not_swallowed(tmp_path, caplog):
    """A corrupt index must not silently reset the archive's memory.

    This is the silent-no-op lesson applied to new code: recovery is fine,
    recovering WITHOUT a record is the defect.
    """
    src, arc = tmp_path / "Replays", tmp_path / "archive"
    src.mkdir()
    arc.mkdir()
    idx = arc / "index.json"
    idx.write_text("{not json", encoding="utf-8")
    _seed(src, "NA1-5592802194.rofl")

    with caplog.at_level(logging.WARNING, logger=rofl_archive.logger.name):
        res = rofl_archive.archive_replays(src, arc, idx)

    assert res.copied == ["NA1_5592802194"], "did not recover from a corrupt index"
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "corrupt index was swallowed with no record"
    )


def test_index_write_is_atomic_across_runs(tmp_path):
    """Index must remain valid JSON after repeated runs (no truncation)."""
    src, arc = tmp_path / "Replays", tmp_path / "archive"
    src.mkdir()
    idx = arc / "index.json"
    for n in ("NA1-1111111111.rofl", "NA1-2222222222.rofl", "NA1-3333333333.rofl"):
        _seed(src, n)
        rofl_archive.archive_replays(src, arc, idx)
    data = json.loads(idx.read_text(encoding="utf-8"))
    assert len(data["replays"]) == 3
