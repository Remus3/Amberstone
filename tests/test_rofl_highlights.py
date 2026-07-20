"""Regression tests for highlight-clip archiving (core.rofl_archive).

The client writes highlight clips to
`Documents/League of Legends/Highlights/` using a filename that embeds BOTH the
patch and the match id:

    16-13_NA1-5592802194_01.webm
    ^^^^^ patch 16.13
          ^^^^^^^^^^^^^^ match NA1_5592802194
                         ^^ clip index

That makes the filename a direct join key onto `matches.match_id` in
rewind_history.db, and onto the archived `.rofl` for the same game. Measured on
the real file: `16-13_NA1-5592802194_01.webm`, 4613480 bytes, whose match is
already in the replay archive.

Clips live in a client-managed directory, so the same reasoning as replays
applies: copy them out, never move or delete, and key on the clip id so
re-running is free.
"""
from __future__ import annotations

import json

import pytest

from core import rofl_archive as ra


@pytest.mark.parametrize(
    "name,expected",
    [
        ("16-13_NA1-5592802194_01.webm", ("NA1_5592802194", "16.13", "01")),
        ("16-14_NA1-5604806601_02.webm", ("NA1_5604806601", "16.14", "02")),
        ("9-4_EUW1-1234567890_10.webm", ("EUW1_1234567890", "9.4", "10")),
        ("16-13_NA1-5592802194_01.mp4", ("NA1_5592802194", "16.13", "01")),
        ("notaclip.webm", None),
        ("16-13_NA1-5592802194.webm", None),      # missing clip index
        ("16-13_NA1-notanumber_01.webm", None),
        ("16-13_NA1-5592802194_01.txt", None),    # not a video
    ],
)
def test_highlight_key_from_name(name, expected):
    assert ra.highlight_key_from_name(name) == expected


def _seed(d, name, payload=b"webm-bytes"):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(payload)
    return d / name


def test_archives_a_clip_and_indexes_it(tmp_path):
    src, arc = tmp_path / "Highlights", tmp_path / "arc"
    _seed(src, "16-13_NA1-5592802194_01.webm")

    res = ra.archive_highlights(src, arc, arc / "clips.json")

    assert res.copied == ["NA1_5592802194_01"]
    assert (arc / "highlights" / "16-13_NA1-5592802194_01.webm").exists()
    idx = json.loads((arc / "clips.json").read_text(encoding="utf-8"))
    entry = idx["clips"]["NA1_5592802194_01"]
    assert entry["match_id"] == "NA1_5592802194"
    assert entry["patch"] == "16.13"
    assert entry["size"] == len(b"webm-bytes")


def test_source_clip_is_never_deleted(tmp_path):
    src, arc = tmp_path / "Highlights", tmp_path / "arc"
    original = _seed(src, "16-13_NA1-5592802194_01.webm")
    ra.archive_highlights(src, arc, arc / "clips.json")
    assert original.exists(), "archiver deleted the source clip"


def test_second_run_is_idempotent(tmp_path):
    src, arc = tmp_path / "Highlights", tmp_path / "arc"
    _seed(src, "16-13_NA1-5592802194_01.webm")
    idx = arc / "clips.json"

    first = ra.archive_highlights(src, arc, idx)
    second = ra.archive_highlights(src, arc, idx)

    assert first.copied == ["NA1_5592802194_01"]
    assert second.copied == []
    assert second.skipped == ["NA1_5592802194_01"]


def test_multiple_clips_for_one_match_are_distinct(tmp_path):
    """Clip index is part of the key - two clips of the same game must not
    collide and silently drop one."""
    src, arc = tmp_path / "Highlights", tmp_path / "arc"
    _seed(src, "16-13_NA1-5592802194_01.webm")
    _seed(src, "16-13_NA1-5592802194_02.webm")

    res = ra.archive_highlights(src, arc, arc / "clips.json")

    assert sorted(res.copied) == ["NA1_5592802194_01", "NA1_5592802194_02"]


def test_ignores_non_clip_files(tmp_path):
    src, arc = tmp_path / "Highlights", tmp_path / "arc"
    _seed(src, "readme.txt")
    _seed(src, "random.webm")

    res = ra.archive_highlights(src, arc, arc / "clips.json")

    assert res.copied == []


def test_missing_source_dir_is_not_an_error(tmp_path):
    res = ra.archive_highlights(tmp_path / "nope", tmp_path / "arc",
                                tmp_path / "arc" / "clips.json")
    assert res.copied == [] and res.failed == []


def test_leaves_no_partial_file_behind(tmp_path):
    src, arc = tmp_path / "Highlights", tmp_path / "arc"
    _seed(src, "16-13_NA1-5592802194_01.webm")
    ra.archive_highlights(src, arc, arc / "clips.json")
    leftovers = [p.name for p in (arc / "highlights").iterdir() if p.name.endswith(".tmp")]
    assert not leftovers


def test_index_stays_valid_across_runs(tmp_path):
    src, arc = tmp_path / "Highlights", tmp_path / "arc"
    idx = arc / "clips.json"
    for n in ("16-13_NA1-111_01.webm", "16-13_NA1-222_01.webm", "16-14_NA1-333_01.webm"):
        _seed(src, n)
        ra.archive_highlights(src, arc, idx)
    data = json.loads(idx.read_text(encoding="utf-8"))
    assert len(data["clips"]) == 3
