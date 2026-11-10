"""S144-Q-139 - one shared compare-and-remove primitive for the lock breakers.

RM-691 (ops/loop/inbox_tick.py ``_remove_if``), S144-Q-132
(agents/_supervisor_common.py ``_remove_if_holds``) and S144-Q-131
(ops/loop/drain_waves_2_3.py ``_remove_if``) each carried a hand-copied body of
the same mechanism: rename the file to a unique side name, compare the bytes
moved with the bytes the caller read, delete them on a match, put them back
with a no-overwrite hard link on a mismatch. S144-Q-138 made
ops/loop/loop_controller.py a fourth caller (of inbox_tick's copy). Three
copies drift: a fix to one (the no-hard-link fallback, the side name) would
reach one caller in three.

These pin the primitive's contract once (``core.polled_json.remove_if_holds``)
and that every caller routes through it: no copy of the rename / link body is
left in any of the three modules. Every path is under tmp_path.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from core import polled_json

ROOT = Path(__file__).resolve().parents[1]
CALLER_FILES = (
    "ops/loop/inbox_tick.py",
    "ops/loop/drain_waves_2_3.py",
    "agents/_supervisor_common.py",
)


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _siblings(path: Path) -> list[str]:
    return sorted(p.name for p in path.parent.iterdir() if p.name != path.name)


# --- the primitive's contract -------------------------------------------------


def test_removes_a_file_that_still_holds_the_bytes(tmp_path: Path) -> None:
    lock = tmp_path / "x.lock"
    lock.write_bytes(b"123")
    assert polled_json.remove_if_holds(lock, b"123") is True
    assert not lock.exists()
    assert _siblings(lock) == []


def test_keeps_a_changed_file_byte_identical(tmp_path: Path) -> None:
    lock = tmp_path / "x.lock"
    lock.write_bytes(b"new owner")
    assert polled_json.remove_if_holds(lock, b"old owner") is False
    assert lock.read_bytes() == b"new owner"
    assert _siblings(lock) == []


def test_an_absent_file_counts_as_gone(tmp_path: Path) -> None:
    assert polled_json.remove_if_holds(tmp_path / "never.lock", b"1") is True


def test_side_name_keeps_the_suffix_by_default(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "inbox_tick.lock"
    lock.write_bytes(b"1")
    seen: list[str] = []
    real = os.rename

    def spy(src, dst):
        seen.append(Path(dst).name)
        return real(src, dst)

    monkeypatch.setattr(polled_json.os, "rename", spy)
    polled_json.remove_if_holds(lock, b"1")
    assert seen and seen[0].startswith("inbox_tick.break-") and seen[0].endswith(".lock")


def test_side_name_appends_when_suffix_is_not_kept(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "supervisor.lock"
    lock.write_bytes(b"1")
    seen: list[str] = []
    real = os.rename

    def spy(src, dst):
        seen.append(Path(dst).name)
        return real(src, dst)

    monkeypatch.setattr(polled_json.os, "rename", spy)
    polled_json.remove_if_holds(lock, b"1", keep_suffix=False)
    assert seen and seen[0].startswith("supervisor.lock.break-")
    assert not seen[0].endswith(".lock")


def test_a_file_created_during_the_break_wins(tmp_path: Path, monkeypatch) -> None:
    """A newer lock made between the rename and the put-back stays; the moved
    bytes are dropped (the residual every caller documents)."""
    lock = tmp_path / "x.lock"
    lock.write_bytes(b"A fresh")
    real_read = Path.read_bytes
    raced: list[str] = []

    def read_then_race(self):
        data = real_read(self)
        if ".break-" in self.name:
            raced.append(self.name)
            lock.write_bytes(b"C newer")
        return data

    monkeypatch.setattr(Path, "read_bytes", read_then_race)
    assert polled_json.remove_if_holds(lock, b"stale") is False
    assert raced, "the race seam never ran, so this proves nothing"
    assert real_read(lock) == b"C newer"
    assert _siblings(lock) == []


def test_without_hard_links_a_mismatch_is_renamed_back(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "x.lock"
    lock.write_bytes(b"live")

    def no_links(src, dst):
        raise OSError("no hard links on this volume")

    monkeypatch.setattr(polled_json.os, "link", no_links)
    assert polled_json.remove_if_holds(lock, b"stale") is False
    assert lock.read_bytes() == b"live"
    assert _siblings(lock) == []


def test_an_unmovable_file_is_left_in_place(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "x.lock"
    lock.write_bytes(b"held open")

    def refuse(src, dst):
        raise PermissionError("held open by its creator")

    monkeypatch.setattr(polled_json.os, "rename", refuse)
    assert polled_json.remove_if_holds(lock, b"held open") is False
    assert lock.read_bytes() == b"held open"


# --- every caller routes through it --------------------------------------------


def test_inbox_tick_routes_through_the_primitive() -> None:
    tick = _load("rc_inbox_tick_s144q139_test", "ops/loop/inbox_tick.py")
    assert tick._remove_if is polled_json.remove_if_holds


def test_drain_waves_routes_through_the_primitive() -> None:
    dw = _load("rc_drain_waves_s144q139_test", "ops/loop/drain_waves_2_3.py")
    assert dw._remove_if is polled_json.remove_if_holds


def test_supervisor_routes_through_the_primitive(tmp_path: Path, monkeypatch) -> None:
    from agents import _supervisor_common as common

    calls: list[tuple] = []

    def spy(path, expected, *, keep_suffix=True):
        calls.append((path, expected, keep_suffix))
        return True

    monkeypatch.setattr(common, "remove_if_holds", spy)
    target = tmp_path / "sentinel"
    assert common._remove_if_holds(target, b"9") is True
    # The supervisor's side name stays <name>.break-<pid>-<hex>, which its
    # orphan-tmp reaper (lockfile.*.tmp) never matches.
    assert calls == [(target, b"9", False)]


@pytest.mark.parametrize("rel", CALLER_FILES)
def test_no_caller_keeps_a_copy_of_the_body(rel: str) -> None:
    """The rename-aside / link-back body lives only in core/polled_json.py."""
    tree = ast.parse((ROOT / rel).read_bytes().decode("utf-8"))
    hits = [
        f"{node.lineno}: os.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"rename", "link"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
    ]
    assert hits == [], f"{rel} still calls {hits}"


def test_the_body_scan_matches_something() -> None:
    """Positive control: the same scan finds the body in the primitive's home."""
    tree = ast.parse((ROOT / "core/polled_json.py").read_bytes().decode("utf-8"))
    attrs = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
    }
    assert {"rename", "link"} <= attrs
