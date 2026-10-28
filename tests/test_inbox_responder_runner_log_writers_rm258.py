"""RM-258: the runner's invocation-log trimmer and metrics rotator are atomic.

tools/inbox_responder_runner.py `_trim` rewrites the invocation log down to its
last INVOCATION_LOG_KEEP rows, and `_rotate_metrics` replaces the metrics
ledger with its carried rows once it passes METRICS_ROTATE_BYTES. Each
hand-rolled a destination-derived scratch name (`<log>.jsonl.tmp`,
`<ledger>.jsonl.rotate`) plus a bare Path.replace: no fsync, no WinError 5
retry, and one scratch file shared by every writer of that log. Both swallow
OSError, so a single refused rename skipped the trim or the rotation silently
and the file kept growing.

They now route through core.polled_json. On-disk bytes are unchanged (UTF-8,
no newline translation), and the rotation still appends the archive before it
replaces the live file, so a failure leaves the ledger complete.

tmp roots only: no process, no live inbox, no git.
"""
from __future__ import annotations

import json
from pathlib import Path

import core.polled_json as pj
from tools import inbox_responder_runner as runner


def _record_writes(monkeypatch):
    seen = []
    real = pj._write_then_replace

    def rec(path, data):
        seen.append((Path(path).name, bytes(data)))
        return real(path, data)

    monkeypatch.setattr(pj, "_write_then_replace", rec)
    return seen


def _flaky_rename(monkeypatch, count: int):
    real = pj.os.replace
    refusals = [count]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pj.os, "replace", flaky)
    monkeypatch.setattr(pj.time, "sleep", lambda _s: None)
    return refusals


def _seed_log(path: Path, count: int) -> list[str]:
    lines = [json.dumps({"ts": f"2026-10-27T00:00:{i:02d}", "row": i,
                         "note": "caf\u00e9"}, ensure_ascii=False) + "\n"
             for i in range(count)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(lines).encode("utf-8"))
    return lines


def _seed_metrics(path: Path, count: int) -> list[str]:
    lines = [json.dumps({"cycle_id": f"c{i}", "agreement_id": "old",
                         "ts": f"2026-09-0{1 + i % 9}T00:00:0{i % 10}",
                         "pad": "x" * 200}, ensure_ascii=True) + "\n"
             for i in range(count)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(lines).encode("ascii"))
    return lines


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()
                  if p.name.endswith((".tmp", ".rotate")))


# ---------------------------------------------------------------------------
# _trim
# ---------------------------------------------------------------------------


def test_rm258_trim_routes_through_polled_json_with_exact_bytes(tmp_path, monkeypatch):
    path = runner.invocations_path(tmp_path)
    lines = _seed_log(path, 12)
    seen = _record_writes(monkeypatch)

    runner._trim(path, keep=5)

    want = "".join(lines[-5:]).encode("utf-8")
    assert seen == [(path.name, want)]
    assert path.read_bytes() == want
    assert b"\r" not in path.read_bytes()
    assert _leftovers(path.parent) == []


def test_rm258_trim_survives_transient_rename_refusals(tmp_path, monkeypatch):
    path = runner.invocations_path(tmp_path)
    lines = _seed_log(path, 12)
    refusals = _flaky_rename(monkeypatch, 2)

    runner._trim(path, keep=5)

    assert refusals == [0]
    assert path.read_bytes() == "".join(lines[-5:]).encode("utf-8")
    assert _leftovers(path.parent) == []


def test_rm258_a_stale_shared_scratch_name_cannot_block_the_trim(tmp_path):
    """The old fixed scratch name, taken by a directory, made every trim fail."""
    path = runner.invocations_path(tmp_path)
    lines = _seed_log(path, 12)
    path.with_suffix(".jsonl.tmp").mkdir()

    runner._trim(path, keep=5)

    assert path.read_bytes() == "".join(lines[-5:]).encode("utf-8")


def test_trim_is_inert_at_or_below_keep(tmp_path, monkeypatch):
    path = runner.invocations_path(tmp_path)
    _seed_log(path, 5)
    before = path.read_bytes()
    seen = _record_writes(monkeypatch)

    runner._trim(path, keep=5)

    assert seen == []
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# _rotate_metrics
# ---------------------------------------------------------------------------


def _small_rotation(monkeypatch):
    monkeypatch.setattr(runner, "METRICS_ROTATE_BYTES", 2000)
    monkeypatch.setattr(runner, "METRICS_CARRY_ROWS", 10)


def test_rm258_rotation_replaces_the_ledger_through_polled_json(tmp_path, monkeypatch):
    _small_rotation(monkeypatch)
    path = runner.metrics_path(tmp_path)
    lines = _seed_metrics(path, 60)
    seen = _record_writes(monkeypatch)

    runner._rotate_metrics(path)

    want = "".join(lines[-10:]).encode("ascii")
    assert seen == [(path.name, want)]
    assert path.read_bytes() == want
    archives = sorted(path.parent.glob(f"{path.stem}.*{path.suffix}"))
    assert len(archives) == 1
    assert archives[0].read_bytes() + want == "".join(lines).encode("ascii")
    assert _leftovers(path.parent) == []


def test_rm258_rotation_survives_transient_rename_refusals(tmp_path, monkeypatch):
    _small_rotation(monkeypatch)
    path = runner.metrics_path(tmp_path)
    lines = _seed_metrics(path, 60)
    refusals = _flaky_rename(monkeypatch, 2)

    runner._rotate_metrics(path)

    assert refusals == [0]
    assert path.read_bytes() == "".join(lines[-10:]).encode("ascii")
    assert _leftovers(path.parent) == []


def test_rm258_a_rotation_whose_replace_fails_leaves_the_ledger_complete(tmp_path, monkeypatch):
    """Every rename refused: the live file is untouched and no scratch is left.

    The archive was already appended, so its rows are duplicated rather than
    lost - the disclosed cost in `_rotate_metrics`' docstring."""
    _small_rotation(monkeypatch)
    path = runner.metrics_path(tmp_path)
    _seed_metrics(path, 60)
    before = path.read_bytes()
    _flaky_rename(monkeypatch, 99)

    runner._rotate_metrics(path)

    assert path.read_bytes() == before
    assert _leftovers(path.parent) == []


def test_rm258_a_carry_write_that_cannot_land_keeps_the_ledger_and_the_archive(tmp_path, monkeypatch):
    """The archive is appended BEFORE the live file is replaced (ORDER in the
    docstring), so a carry write that fails leaves the ledger complete and its
    archived rows duplicated, never lost, and raises nothing at the caller."""
    _small_rotation(monkeypatch)
    path = runner.metrics_path(tmp_path)
    lines = _seed_metrics(path, 60)
    before = path.read_bytes()

    def refuse(_path, _data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pj, "_write_then_replace", refuse)

    runner._rotate_metrics(path)

    assert path.read_bytes() == before
    archives = sorted(path.parent.glob(f"{path.stem}.*{path.suffix}"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == "".join(lines[:-10]).encode("ascii")
