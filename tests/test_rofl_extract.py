"""Regression tests for .rofl Layer-1 stats extraction (core.rofl_archive).

MEASURED 2026-07-19 against two real archived replays: a .rofl (magic
b"RIOT\\x02\\x00") ends with a plain UNENCRYPTED JSON blob carrying `statsJson`,
which itself is a JSON string holding 10 player dicts at 367 engine-named fields
each (CHAMPIONS_KILLED, GOLD_EARNED, ITEM0..ITEM6, KEYSTONE_ID, ...).

Two traps this encodes, both hit for real:
  1. The blob has TRAILING BYTES past the closing brace, so a plain json.loads
     raises "Extra data: line 1 column 120680". JSONDecoder().raw_decode is
     required.
  2. `statsJson` is a STRING containing JSON, not a nested object - it needs a
     second parse.

Extraction has NO patch gate (unlike playback, which is hard patch-locked), needs
no game client and no third-party tool. That is what makes an archived replay a
permanent stats record - including for event modes such as KIWI, which Match-V5
403s on and which are therefore absent from rewind_history.db entirely.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import rofl_archive as ra


def _fake_rofl(players, game_length=1020541, trailing=b"\x00\x00trailing-garbage"):
    """Build a byte-accurate minimal .rofl: magic, filler, JSON blob, trailing.

    Mirrors the real container closely enough to exercise the two traps above.
    """
    meta = {
        "gameLength": game_length,
        "lastGameChunkId": 37,
        "lastKeyFrameId": 18,
        "statsJson": json.dumps(players),
    }
    return b"RIOT\x02\x00" + b"\x00" * 64 + json.dumps(meta).encode("utf-8") + trailing


_PLAYERS = [
    {"SKIN": "Leona", "CHAMPIONS_KILLED": "17", "NUM_DEATHS": "11",
     "GOLD_EARNED": "17460", "WIN": "Win", "ITEM0": "3084", "ITEM6": "220013"},
    {"SKIN": "Yone", "CHAMPIONS_KILLED": "2", "NUM_DEATHS": "7",
     "GOLD_EARNED": "9001", "WIN": "Fail", "ITEM0": "6672", "ITEM6": "3340"},
]


def test_extracts_meta_and_players(tmp_path):
    p = tmp_path / "NA1-5604806601.rofl"
    p.write_bytes(_fake_rofl(_PLAYERS))

    out = ra.extract_stats(p)

    assert out is not None
    assert out["match_id"] == "NA1_5604806601"
    assert out["game_length_ms"] == 1020541
    assert len(out["players"]) == 2
    assert out["players"][0]["SKIN"] == "Leona"
    assert out["players"][0]["ITEM6"] == "220013"


def test_survives_trailing_bytes_after_the_json_object(tmp_path):
    """The real trap: plain json.loads raises 'Extra data' here."""
    p = tmp_path / "NA1-1.rofl"
    p.write_bytes(_fake_rofl(_PLAYERS, trailing=b"\x00" * 512 + b"junk{}{}"))
    out = ra.extract_stats(p)
    assert out is not None and len(out["players"]) == 2


def test_stats_json_is_a_string_needing_a_second_parse(tmp_path):
    """If statsJson were treated as a nested object, players would come back as
    a str and this would fail."""
    p = tmp_path / "NA1-2.rofl"
    p.write_bytes(_fake_rofl(_PLAYERS))
    out = ra.extract_stats(p)
    assert isinstance(out["players"], list)
    assert isinstance(out["players"][0], dict)


def test_missing_file_returns_none_with_a_record(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=ra.logger.name):
        out = ra.extract_stats(tmp_path / "absent.rofl")
    assert out is None
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_file_without_a_blob_returns_none_with_a_record(tmp_path, caplog):
    p = tmp_path / "NA1-3.rofl"
    p.write_bytes(b"RIOT\x02\x00" + b"\x00" * 4096)
    with caplog.at_level(logging.WARNING, logger=ra.logger.name):
        out = ra.extract_stats(p)
    assert out is None
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_corrupt_blob_returns_none_with_a_record(tmp_path, caplog):
    p = tmp_path / "NA1-4.rofl"
    p.write_bytes(b"RIOT\x02\x00" + b'{"gameLength":not-json')
    with caplog.at_level(logging.WARNING, logger=ra.logger.name):
        out = ra.extract_stats(p)
    assert out is None
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_stats_json_list_of_non_dicts_returns_none_not_a_crash(tmp_path, caplog):
    """A statsJson that is valid JSON but the WRONG shape - a list whose entries
    are not player objects - must be rejected like any other corrupt blob, never
    crash. field_count derives len(players[0]); on a non-dict first entry that
    raised an uncaught TypeError which propagated out of extract_stats and aborted
    the whole extract_archive loop, dropping every later replay in the pass.

    Covers both observed variants: a non-sized entry (int/None/bool) that RAISED,
    and a string entry that silently produced a garbage dict (field_count read the
    string length while downstream sidecar consumers index each player as a dict).
    """
    for payload in ([1, 2, 3], [None], [True], ["not-a-player"]):
        p = tmp_path / "NA1-7.rofl"
        p.write_bytes(_fake_rofl(payload))
        with caplog.at_level(logging.WARNING, logger=ra.logger.name):
            out = ra.extract_stats(p)
        assert out is None, f"expected None for statsJson={payload!r}, got {out!r}"
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# bulk extraction over an archive dir
# ---------------------------------------------------------------------------

def test_extract_archive_writes_one_sidecar_per_replay(tmp_path):
    arc = tmp_path / "arc"
    arc.mkdir()
    (arc / "NA1-111.rofl").write_bytes(_fake_rofl(_PLAYERS))
    (arc / "NA1-222.rofl").write_bytes(_fake_rofl(_PLAYERS))

    res = ra.extract_archive(arc)

    assert sorted(res.extracted) == ["NA1_111", "NA1_222"]
    written = json.loads((arc / "stats" / "NA1_111.json").read_text(encoding="utf-8"))
    assert written["match_id"] == "NA1_111"
    assert len(written["players"]) == 2


def test_extract_archive_is_idempotent(tmp_path):
    arc = tmp_path / "arc"
    arc.mkdir()
    (arc / "NA1-111.rofl").write_bytes(_fake_rofl(_PLAYERS))

    first = ra.extract_archive(arc)
    second = ra.extract_archive(arc)

    assert first.extracted == ["NA1_111"]
    assert second.extracted == []
    assert second.skipped == ["NA1_111"]


def test_extract_archive_force_reextracts(tmp_path):
    arc = tmp_path / "arc"
    arc.mkdir()
    (arc / "NA1-111.rofl").write_bytes(_fake_rofl(_PLAYERS))
    ra.extract_archive(arc)
    res = ra.extract_archive(arc, force=True)
    assert res.extracted == ["NA1_111"]


def test_extract_archive_counts_failures_rather_than_dropping_them(tmp_path):
    arc = tmp_path / "arc"
    arc.mkdir()
    (arc / "NA1-111.rofl").write_bytes(_fake_rofl(_PLAYERS))
    (arc / "NA1-999.rofl").write_bytes(b"RIOT\x02\x00" + b"\x00" * 100)

    res = ra.extract_archive(arc)

    assert res.extracted == ["NA1_111"]
    assert res.failed == ["NA1_999"]


def test_extract_archive_survives_a_non_dict_statsjson_replay(tmp_path):
    """One replay whose statsJson is a list of non-dicts must be COUNTED as
    failed, not crash the pass. Before the fix extract_stats raised TypeError on
    the bad file and extract_archive had no guard, so the good sibling that sorted
    after it (NA1-999) was never extracted - one corrupt .rofl dropped the rest."""
    arc = tmp_path / "arc"
    arc.mkdir()
    # NA1-111 sorts before NA1-999; the bad file must not prevent the good one.
    (arc / "NA1-111.rofl").write_bytes(_fake_rofl([1, 2, 3]))
    (arc / "NA1-999.rofl").write_bytes(_fake_rofl(_PLAYERS))

    res = ra.extract_archive(arc)

    assert res.extracted == ["NA1_999"]
    assert res.failed == ["NA1_111"]


def test_extract_archive_on_missing_dir_is_not_an_error(tmp_path):
    res = ra.extract_archive(tmp_path / "nope")
    assert res.extracted == [] and res.failed == []


def test_extract_archive_leaves_no_partial_sidecar(tmp_path):
    arc = tmp_path / "arc"
    arc.mkdir()
    (arc / "NA1-111.rofl").write_bytes(_fake_rofl(_PLAYERS))
    ra.extract_archive(arc)
    leftovers = [p.name for p in (arc / "stats").iterdir() if p.name.endswith(".tmp")]
    assert not leftovers
