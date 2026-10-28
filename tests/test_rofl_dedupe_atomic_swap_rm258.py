"""RM-258 residual: the .rofl relink swap goes through core.polled_json.

tools/rofl_dedupe.py runs as the daily RC-RoflDedupe task (`--apply`,
docs/OPERATIONS.md) over the replay archive that RC-RoflArchive writes every
15 minutes. Its relink built a destination-derived `<replay>.rofl.relink`
scratch link and swapped it in with a bare os.replace: no WinError 5 retry
while an indexer or a replay reader holds the target open, and one scratch
name shared by every concurrent run.

The swap now takes its scratch name from `polled_json._scratch_path`
(per-writer pid + token) and renames through `polled_json._replace_with_retry`
- the same two helpers core/rofl_archive.py's `_atomic_copy` uses for the same
archive. Every path lives under tmp_path; the growth sample is redirected so
nothing touches data/.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import rofl_dedupe  # noqa: E402

# Synthetic match id (RM-906): never a real Riot id.
_NAME = "NA1_1000000001.rofl"
_BYTES = b"synthetic-rofl-container\n" * 64


@pytest.fixture
def archive(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    keeper = root / "players" / "MID" / "alpha" / _NAME
    other = root / "players" / "TOP" / "bravo" / _NAME
    for p in (keeper, other):
        p.parent.mkdir(parents=True)
        p.write_bytes(_BYTES)
    sample = tmp_path / "growth.jsonl"

    def append_sample(_root, _stamp):
        sample.write_bytes(b"")
        return sample

    monkeypatch.setattr(rofl_dedupe, "append_sample", append_sample)
    return root, keeper, other


def _leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.rglob("*") if p.is_file() and p.suffix != ".rofl")


def test_apply_swaps_through_the_shared_retry_with_a_per_writer_scratch(archive, monkeypatch):
    root, keeper, other = archive
    calls = []
    real = polled_json._replace_with_retry

    def spy(src, dst):
        calls.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(polled_json, "_replace_with_retry", spy)
    assert rofl_dedupe.main(["--root", str(root), "--apply"]) == 0

    assert len(calls) == 1, calls
    scratch, dst = calls[0]
    assert dst == other
    assert scratch.parent == other.parent
    pattern = re.escape(_NAME) + rf"\.{os.getpid()}\.[0-9a-f]+\.tmp"
    assert re.fullmatch(pattern, scratch.name), scratch.name
    assert os.path.samefile(keeper, other)
    assert other.read_bytes() == _BYTES
    assert _leftovers(root) == []


def test_a_refused_swap_keeps_the_replay_and_leaves_no_scratch(archive, monkeypatch):
    root, keeper, other = archive

    def refuse(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", refuse)
    assert rofl_dedupe.main(["--root", str(root), "--apply"]) == 1

    assert other.read_bytes() == _BYTES
    assert not os.path.samefile(keeper, other)
    assert _leftovers(root) == []


def test_a_rerun_is_a_no_op(archive, monkeypatch):
    root, keeper, other = archive
    assert rofl_dedupe.main(["--root", str(root), "--apply"]) == 0
    calls = []
    monkeypatch.setattr(polled_json, "_replace_with_retry",
                        lambda src, dst: calls.append((src, dst)))
    assert rofl_dedupe.main(["--root", str(root), "--apply"]) == 0
    assert calls == []
    assert os.path.samefile(keeper, other)
