"""RM-258: tools/rc_facts.py's four writers route through core.polled_json.

The module hand-rolled four tmp + rename writes: the operator's seen store
(--mark-inbox-seen), the per-session REPORTED record (read back on every
SessionStart / UserPromptSubmit fire), the unread-inbox report file and the
hook-invocation log trim. Each built its scratch name from the destination
(shared by every writer of that file) and finished with a bare Path.replace -
no fsync and no WinError 5 retry. Two of them also went through text-mode
write_text, so their JSON landed as CRLF on Windows.

Each now calls core.polled_json.atomic_write_bytes (per-writer scratch name,
fsync, bounded PermissionError retry, the scratch removed on failure, LF
bytes). The module stays stdlib-only at import (it is a hook, run as a script
with tools/ as sys.path[0]); the helper imports core lazily.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.rc_facts as rc_facts  # noqa: E402
from tests._replace_faults import scoped_fs_fault  # noqa: E402


def _root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    (root / "ops" / "runtime").mkdir(parents=True)
    (root / "moon_sync_inbox").mkdir(parents=True)
    monkeypatch.setattr(rc_facts, "_ROOT", root)
    monkeypatch.setattr(rc_facts, "_T0", time.monotonic())
    return root


def _record_writes(monkeypatch) -> list[tuple[str, bytes]]:
    import core.polled_json as pj
    seen: list[tuple[str, bytes]] = []
    real = pj._write_then_replace

    def rec(path, data):
        seen.append((Path(path).name, bytes(data)))
        return real(path, data)

    monkeypatch.setattr(pj, "_write_then_replace", rec)
    return seen


def _no_scratch(d: Path, keep: set[str]) -> None:
    assert sorted(p.name for p in d.iterdir()) == sorted(keep)


def test_mark_inbox_seen_routes_through_polled_json(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path, monkeypatch)
    for name in ("b.md", "a.md"):
        (root / "moon_sync_inbox" / name).write_text(name, encoding="utf-8")
    seen = _record_writes(monkeypatch)

    assert rc_facts.mark_inbox_seen() == 0

    names = sorted(rc_facts._inbox_entries(root / "moon_sync_inbox"))
    expected = json.dumps({"seen": names}, indent=2).encode("utf-8")
    dest = root / "ops" / "runtime" / "sync_inbox_seen.json"
    assert seen == [(dest.name, expected)]
    assert dest.read_bytes() == expected
    assert b"\r" not in dest.read_bytes()
    _no_scratch(dest.parent, {dest.name})


def test_save_reported_routes_through_polled_json(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    seen = _record_writes(monkeypatch)

    rc_facts._save_reported("sid-1", {"k2", "k1"})

    dest = root / "ops" / "runtime" / "sync_inbox_reported.json"
    assert [name for name, _ in seen] == [dest.name]
    raw = dest.read_bytes()
    assert seen[0][1] == raw
    assert b"\r" not in raw
    assert json.loads(raw)["sessions"]["sid-1"]["keys"] == ["k1", "k2"]
    _no_scratch(dest.parent, {dest.name})


def test_save_reported_survives_two_transient_permission_errors(tmp_path, monkeypatch):
    """The reported record is rewritten while other fires read it; a WinError 5
    on the rename used to drop the write (the OSError is swallowed), so the
    block printed again. The shared retry clears a transient share-lock."""
    root = _root(tmp_path, monkeypatch)
    left = [2]

    def flaky(real, src, dst, *a, **kw):
        if left[0]:
            left[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst, *a, **kw)

    with scoped_fs_fault("replace", tmp_path, flaky) as rec:
        rc_facts._save_reported("sid-1", {"k1"})

    assert rec.attempts == 3
    dest = root / "ops" / "runtime" / "sync_inbox_reported.json"
    assert json.loads(dest.read_bytes())["sessions"]["sid-1"]["keys"] == ["k1"]
    _no_scratch(dest.parent, {dest.name})


def test_inbox_report_routes_through_polled_json(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    seen = _record_writes(monkeypatch)

    assert rc_facts._write_inbox_report(["a.md", "b.md"], ["gone.md"]) is True

    dest = root / "ops" / "runtime" / "sync_inbox_report.txt"
    expected = b"a.md\nb.md\nWITHDRAWN:gone.md\n"
    assert seen == [(dest.name, expected)]
    assert dest.read_bytes() == expected
    _no_scratch(dest.parent, {dest.name})

    # Unchanged bytes still short-circuit: no second write.
    assert rc_facts._write_inbox_report(["a.md", "b.md"], ["gone.md"]) is True
    assert len(seen) == 1


def test_invocation_log_trim_routes_through_polled_json(tmp_path, monkeypatch):
    monkeypatch.setattr(rc_facts, "_LOG_TRIM_BYTES", 16)
    monkeypatch.setattr(rc_facts, "_LOG_KEEP", 3)
    log = tmp_path / "hook_invocations.jsonl"
    rows = [json.dumps({"n": i}) for i in range(6)]
    log.write_bytes(("\n".join(rows) + "\n").encode("utf-8"))
    seen = _record_writes(monkeypatch)

    rc_facts._trim_invocation_log(log)

    expected = ("\n".join(rows[-3:]) + "\n").encode("utf-8")
    assert seen == [(log.name, expected)]
    assert log.read_bytes() == expected
    _no_scratch(tmp_path, {log.name})
