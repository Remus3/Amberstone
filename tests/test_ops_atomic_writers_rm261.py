"""RM-261 - the three stdlib-only ops writers must not share a scratch file.

ops/rc_supervisor.atomic_write_json, ops/rc_dev_runtime._atomic_write_json and
ops/rc_transactional_deploy.atomic_write_json / copy_atomic each built their
scratch name from the DESTINATION alone (`<dest>.tmp`), so two writers of one
file - the supervisor and the app both touch ops/runtime/*.json - opened the
same scratch file and could publish torn bytes (the RM-254 defect, fixed in
core/polled_json but not in these deliberate stdlib-only copies). The
supervisor's restart_trigger.txt clear also renamed with a bare os.replace
while the same file defines a retry helper (RM-258).

These modules stay stdlib-only (see SANCTIONED in
tests/test_atomic_write_guard_rm258_rm261.py), so the contract is asserted on
each copy directly: per-writer scratch name, fsync before the rename, and no
scratch file left behind when the rename fails for good.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ops import rc_dev_runtime as rdr
from ops import rc_supervisor as sup
from ops import rc_transactional_deploy as td


def _json_writers():
    return [
        ("supervisor", sup, lambda p: sup.atomic_write_json(p, {"a": 1})),
        ("dev_runtime", rdr, lambda p: rdr._atomic_write_json(p, {"a": 1})),
        ("deploy", td, lambda p: td.atomic_write_json(p, {"a": 1})),
    ]


@pytest.mark.parametrize("name, mod, write", _json_writers(), ids=lambda x: x if isinstance(x, str) else "")
def test_scratch_name_is_per_writer_and_fsynced(tmp_path, monkeypatch, name, mod, write):
    seen: list[str] = []
    events: list[str] = []
    real_replace = os.replace
    real_fsync = os.fsync

    def rec_replace(src, dst, *a, **kw):
        seen.append(Path(src).name)
        events.append("replace")
        return real_replace(src, dst, *a, **kw)

    def rec_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(mod.os, "replace", rec_replace)
    monkeypatch.setattr(mod.os, "fsync", rec_fsync)
    dest = tmp_path / "health.json"
    write(dest)
    write(dest)
    assert len(seen) == 2
    assert "health.json.tmp" not in seen, f"{name}: destination-derived scratch name {seen}"
    assert seen[0] != seen[1], f"{name}: two writes shared one scratch name {seen}"
    assert str(os.getpid()) in seen[0]
    assert events.index("fsync") < events.index("replace"), events
    assert sorted(p.name for p in tmp_path.iterdir()) == ["health.json"]


def test_copy_atomic_uses_a_per_writer_scratch_name(tmp_path, monkeypatch):
    seen: list[str] = []
    real_replace = os.replace

    def rec_replace(src, dst, *a, **kw):
        seen.append(Path(src).name)
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(td.os, "replace", rec_replace)
    src = tmp_path / "src.py"
    src.write_bytes(b"x = 1\n")
    dst = tmp_path / "out" / "dst.py"
    td.copy_atomic(src, dst)
    assert dst.read_bytes() == b"x = 1\n"
    assert seen and seen[0] != "dst.py.tmp" and str(os.getpid()) in seen[0]


@pytest.mark.parametrize("name, mod, write", _json_writers(), ids=lambda x: x if isinstance(x, str) else "")
def test_exhausted_rename_leaves_no_scratch(tmp_path, monkeypatch, name, mod, write):
    def denied(src, dst, *a, **kw):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(mod.os, "replace", denied)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    with pytest.raises(OSError):
        write(tmp_path / "health.json")
    assert list(tmp_path.iterdir()) == [], f"{name}: scratch file orphaned"


def test_supervisor_trigger_clear_goes_through_the_retry_helper():
    """The loop's restart_trigger.txt clear must not rename bare (RM-258)."""
    import ast
    import inspect

    src = inspect.getsource(sup)
    tree = ast.parse(src)
    loops = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "loop"]
    assert loops
    for fn in loops:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "replace" \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                pytest.fail(f"bare os.replace in Supervisor.loop at line {node.lineno}")
