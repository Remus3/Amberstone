"""RM-258 residual: tools/timeline_ingest.py writes each corpus file through
core.polled_json.

The ingest is a detached, hours-long job (its docstring: "long by
construction and is meant to run detached"). While it runs, the 15-minute
RC-ReplayChainWatch task counts `<corpus>/timelines/*.json`
(tools/replay_chain_watch.py timelines_count) and tools/mine_event_patterns.py
reads the same directory. Each match file was written to a destination-derived
`<match_id>.tmp` scratch and swapped in with a bare Path.replace: no fsync, no
WinError 5 retry while a reader holds the target open, one scratch name per
match for every concurrent run, and a refused rename left the scratch file
behind.

The write now goes through `polled_json.atomic_write_bytes` (per-writer
scratch name, fsync, bounded retry, scratch removed on failure). Every network
seam and the pacing sleep are stubbed; every path lives under tmp_path.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from core import riot_api as RA  # noqa: E402
from tools import timeline_ingest as ti  # noqa: E402

# Synthetic match id (RM-906): never a real Riot id.
_MID = "NA1_1000000002"
_MATCH = {"info": {"gameDuration": 1800}}
_TIMELINE = {"info": {"frames": [{"timestamp": 0}]}}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(ti, "_pace", lambda: None)
    monkeypatch.setattr(RA, "get_match", lambda mid: dict(_MATCH))
    monkeypatch.setattr(RA, "get_match_timeline", lambda mid: dict(_TIMELINE))


def _spy_replace(monkeypatch):
    seen = []
    real = polled_json._replace_with_retry

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(polled_json, "_replace_with_retry", spy)
    return seen


def test_the_match_file_is_renamed_through_polled_json(tmp_path, monkeypatch):
    seen = _spy_replace(monkeypatch)
    assert ti.ingest_match(_MID, tmp_path) == "ok"
    dest = tmp_path / f"{_MID}.json"
    assert len(seen) == 1, seen
    src, dst = seen[0]
    assert dst == dest
    # Per-writer scratch (pid + token) beside the target, never `<id>.tmp`.
    assert src.parent == tmp_path
    assert re.fullmatch(
        re.escape(f"{_MID}.json.{os.getpid()}.") + r"[0-9a-f]{8}\.tmp", src.name
    ), src.name
    # Same compact bytes the old writer produced, no scratch left behind.
    expected = json.dumps({"match": _MATCH, "timeline": _TIMELINE},
                          separators=(",", ":")).encode("utf-8")
    assert dest.read_bytes() == expected
    assert [p.name for p in tmp_path.iterdir()] == [dest.name]


def test_a_refused_rename_leaves_no_scratch_file(tmp_path, monkeypatch):
    def refused(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", refused)
    with pytest.raises(PermissionError):
        ti.ingest_match(_MID, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_retry_partial_replaces_the_stored_partial_atomically(tmp_path, monkeypatch):
    dest = tmp_path / f"{_MID}.json"
    dest.write_bytes(json.dumps({"match": _MATCH, "timeline": None}).encode())
    monkeypatch.setattr(RA, "get_match",
                        lambda mid: pytest.fail("match half must be reused"))
    seen = _spy_replace(monkeypatch)
    assert ti.ingest_match(_MID, tmp_path, retry_partial=True) == "ok"
    assert [dst for _src, dst in seen] == [dest]
    assert json.loads(dest.read_bytes()) == {"match": _MATCH,
                                             "timeline": _TIMELINE}
    assert [p.name for p in tmp_path.iterdir()] == [dest.name]
