"""Tests for tools/slice_orchestrator.py - the resumable run manifest.

Covers init (with force-guard), add (dup-guard), set (status validation),
next (work-priority order), resume (non-committed set), summary (counts), and
the atomic-write round-trip. Every test injects a tmp --manifest so the real
ops/runtime/slice_manifest.json is never touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import slice_orchestrator as so  # noqa: E402


def _mf(tmp_path: Path) -> str:
    return str(tmp_path / "slice_manifest.json")


def _init(mf: str, run_id: str = "run-x") -> int:
    return so.main(["--manifest", mf, "init", "--run-id", run_id, "--head", "abc123"])


def test_init_creates_manifest(tmp_path):
    mf = _mf(tmp_path)
    assert _init(mf) == 0
    data = json.loads(Path(mf).read_text(encoding="utf-8"))
    assert data["run_id"] == "run-x"
    assert data["head_sha"] == "abc123"
    assert data["slices"] == []


def test_init_refuses_overwrite_without_force(tmp_path):
    mf = _mf(tmp_path)
    assert _init(mf) == 0
    assert _init(mf, run_id="run-y") == 2  # exists, no --force
    # original survives
    assert json.loads(Path(mf).read_text(encoding="utf-8"))["run_id"] == "run-x"


def test_init_force_overwrites(tmp_path):
    mf = _mf(tmp_path)
    assert _init(mf) == 0
    rc = so.main(["--manifest", mf, "init", "--run-id", "run-z", "--force"])
    assert rc == 0
    assert json.loads(Path(mf).read_text(encoding="utf-8"))["run_id"] == "run-z"


def test_add_appends_pending_slice(tmp_path):
    mf = _mf(tmp_path)
    _init(mf)
    assert so.main(["--manifest", mf, "add", "--id", "A", "--title", "engine", "--files", "a.py,b.py"]) == 0
    data = json.loads(Path(mf).read_text(encoding="utf-8"))
    assert len(data["slices"]) == 1
    s = data["slices"][0]
    assert s["id"] == "A"
    assert s["status"] == "pending"
    assert s["files"] == ["a.py", "b.py"]
    assert s["commit"] is None


def test_add_rejects_duplicate_id(tmp_path):
    mf = _mf(tmp_path)
    _init(mf)
    so.main(["--manifest", mf, "add", "--id", "A", "--title", "first"])
    assert so.main(["--manifest", mf, "add", "--id", "A", "--title", "again"]) == 2
    data = json.loads(Path(mf).read_text(encoding="utf-8"))
    assert len(data["slices"]) == 1


def test_add_without_manifest_errors(tmp_path):
    mf = _mf(tmp_path)
    assert so.main(["--manifest", mf, "add", "--id", "A", "--title", "x"]) == 2


def test_set_status_and_commit(tmp_path):
    mf = _mf(tmp_path)
    _init(mf)
    so.main(["--manifest", mf, "add", "--id", "A", "--title", "x"])
    assert so.main(["--manifest", mf, "set", "--id", "A", "--status", "committed", "--commit", "deadbee"]) == 0
    s = json.loads(Path(mf).read_text(encoding="utf-8"))["slices"][0]
    assert s["status"] == "committed"
    assert s["commit"] == "deadbee"


def test_set_rejects_bad_status(tmp_path):
    mf = _mf(tmp_path)
    _init(mf)
    so.main(["--manifest", mf, "add", "--id", "A", "--title", "x"])
    assert so.main(["--manifest", mf, "set", "--id", "A", "--status", "bogus"]) == 2
    s = json.loads(Path(mf).read_text(encoding="utf-8"))["slices"][0]
    assert s["status"] == "pending"  # unchanged


def test_set_unknown_slice_errors(tmp_path):
    mf = _mf(tmp_path)
    _init(mf)
    assert so.main(["--manifest", mf, "set", "--id", "Z", "--status", "verified"]) == 2


def test_next_prefers_pending_then_failed_then_in_progress(tmp_path, capsys):
    mf = _mf(tmp_path)
    _init(mf)
    for sid in ("A", "B", "C"):
        so.main(["--manifest", mf, "add", "--id", sid, "--title", sid])
    so.main(["--manifest", mf, "set", "--id", "A", "--status", "committed"])
    so.main(["--manifest", mf, "set", "--id", "B", "--status", "in_progress"])
    so.main(["--manifest", mf, "set", "--id", "C", "--status", "failed"])
    capsys.readouterr()
    so.main(["--manifest", mf, "next"])
    # failed (C) outranks in_progress (B); committed (A) is done
    assert capsys.readouterr().out.strip() == "C"


def test_next_empty_when_all_committed(tmp_path, capsys):
    mf = _mf(tmp_path)
    _init(mf)
    so.main(["--manifest", mf, "add", "--id", "A", "--title", "x"])
    so.main(["--manifest", mf, "set", "--id", "A", "--status", "committed"])
    capsys.readouterr()
    so.main(["--manifest", mf, "next"])
    assert capsys.readouterr().out.strip() == ""


def test_resume_lists_all_non_committed(tmp_path, capsys):
    mf = _mf(tmp_path)
    _init(mf)
    for sid in ("A", "B", "C", "D"):
        so.main(["--manifest", mf, "add", "--id", sid, "--title", sid])
    so.main(["--manifest", mf, "set", "--id", "A", "--status", "committed"])
    so.main(["--manifest", mf, "set", "--id", "B", "--status", "verified"])
    so.main(["--manifest", mf, "set", "--id", "C", "--status", "in_progress"])
    # D stays pending
    capsys.readouterr()
    so.main(["--manifest", mf, "resume"])
    out = capsys.readouterr().out.split()
    assert out == ["B", "C", "D"]  # A (committed) excluded


def test_summary_counts(tmp_path, capsys):
    mf = _mf(tmp_path)
    _init(mf)
    for sid in ("A", "B", "C"):
        so.main(["--manifest", mf, "add", "--id", sid, "--title", sid])
    so.main(["--manifest", mf, "set", "--id", "A", "--status", "committed"])
    capsys.readouterr()
    so.main(["--manifest", mf, "summary"])
    counts = json.loads(capsys.readouterr().out)
    assert counts["total"] == 3
    assert counts["committed"] == 1
    assert counts["pending"] == 2


def test_save_is_atomic_round_trip(tmp_path):
    mf = Path(_mf(tmp_path))
    data = {"run_id": "r", "created_at": "t", "head_sha": "h", "slices": []}
    so.save_manifest(mf, data)
    assert not mf.with_suffix(mf.suffix + ".tmp").exists()  # temp cleaned by os.replace
    assert so.load_manifest(mf) == data


def test_load_missing_returns_empty(tmp_path):
    assert so.load_manifest(Path(_mf(tmp_path))) == {}


def test_manifest_is_ascii(tmp_path):
    mf = _mf(tmp_path)
    _init(mf)
    so.main(["--manifest", mf, "add", "--id", "A", "--title", "engine slice"])
    raw = Path(mf).read_bytes()
    assert raw.decode("ascii")  # raises if any non-ASCII byte slipped in


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
