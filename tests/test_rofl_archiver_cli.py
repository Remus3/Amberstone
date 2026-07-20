"""CLI-level regression: a closed League client must not abort the archive pass.

The archiver runs on a 15-minute schedule, and the client is CLOSED for most of
that duty cycle. `--pull` is the ONLY step that needs the LCU; archiving,
highlight capture and stats extraction are pure file work.

Shipped defect (caught by the scheduled task reporting LastTaskResult=1): when
the lockfile was absent, main() printed an error and returned 1 BEFORE reaching
the archive/extract/highlights steps - so every run with the game closed did
nothing at all and reported failure. Same coupling shape as the supervisor A3
fix: one step's expected, benign failure taking unrelated work down with it.

A missing lockfile is a SKIP, not a failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import rofl_archiver  # noqa: E402


def _seed_replay(d: Path, name: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(b"RIOT\x02\x00" + b"\x00" * 32)
    return p


def test_pull_with_no_client_still_archives_and_exits_zero(tmp_path, monkeypatch, capsys):
    """RED before the fix: returns 1 and copies nothing."""
    src = tmp_path / "Replays"
    arc = tmp_path / "arc"
    _seed_replay(src, "NA1-5592802194.rofl")

    class _NoClient:
        def __init__(self, *a, **kw):
            raise OSError("lockfile absent")

    monkeypatch.setattr(rofl_archiver, "LcuReplayClient", _NoClient)

    rc = rofl_archiver.main([
        "--pull", "--source", str(src), "--archive", str(arc),
    ])

    out = capsys.readouterr().out
    assert rc == 0, f"a closed client must not be a failure exit; got {rc}\n{out}"
    assert (arc / "NA1-5592802194.rofl").exists(), (
        "archive step was skipped because --pull could not reach the client"
    )


def test_pull_with_no_client_reports_the_skip(tmp_path, monkeypatch, capsys):
    """The skip must be visible - silently doing nothing is the defect this
    whole program exists to remove."""
    src = tmp_path / "Replays"
    arc = tmp_path / "arc"
    _seed_replay(src, "NA1-1.rofl")

    class _NoClient:
        def __init__(self, *a, **kw):
            raise OSError("lockfile absent")

    monkeypatch.setattr(rofl_archiver, "LcuReplayClient", _NoClient)
    rofl_archiver.main(["--pull", "--source", str(src), "--archive", str(arc)])

    out = capsys.readouterr().out.lower()
    assert "skip" in out or "not running" in out, (
        "the pull skip was not reported to the caller"
    )


def test_archive_only_run_needs_no_client(tmp_path):
    """The common scheduled case: no --pull at all, client irrelevant."""
    src = tmp_path / "Replays"
    arc = tmp_path / "arc"
    _seed_replay(src, "NA1-2.rofl")

    rc = rofl_archiver.main(["--source", str(src), "--archive", str(arc)])

    assert rc == 0
    assert (arc / "NA1-2.rofl").exists()
