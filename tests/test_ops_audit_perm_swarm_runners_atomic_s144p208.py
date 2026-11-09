"""The last three ops/audit/ds_perm_swarm runners write through core.polled_json.

RM-258 residual (RM-1716): live_flip_eyeball.py, run_consolidate.py and
run_harness.py each carried a private `_atomic_write` that wrote
`<name>.<ext>.tmp` and os.replace'd it: a scratch name derived from the
destination alone, shared by two concurrent runs. They now call
core.polled_json.atomic_write_bytes with the same UTF-8 bytes. That empties the
ops/audit baseline, so the guard's `audit_unclassified` area is retired.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ops.audit.ds_perm_swarm import live_flip_eyeball, run_consolidate, run_harness

MODS = [live_flip_eyeball, run_consolidate, run_harness]
IDS = ["live_flip_eyeball", "run_consolidate", "run_harness"]
TEXT = "line one\nsecond caf" + chr(0xE9) + "\n"


@pytest.mark.parametrize("mod", MODS, ids=IDS)
def test_writes_exact_utf8_lf_bytes_and_leaves_no_scratch(mod, tmp_path):
    dest = tmp_path / "nested" / "report.json"
    mod._atomic_write(dest, TEXT)
    assert dest.read_bytes() == TEXT.encode("utf-8")
    assert b"\r" not in dest.read_bytes()
    assert sorted(p.name for p in dest.parent.iterdir()) == ["report.json"]


@pytest.mark.parametrize("mod", MODS, ids=IDS)
def test_replaces_an_existing_file_in_place(mod, tmp_path):
    dest = tmp_path / "report.md"
    dest.write_bytes(b"old")
    mod._atomic_write(dest, "new\n")
    assert dest.read_bytes() == b"new\n"
    assert [p.name for p in tmp_path.iterdir()] == ["report.md"]


@pytest.mark.parametrize("mod", MODS, ids=IDS)
def test_goes_through_polled_json(mod, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(mod, "atomic_write_bytes",
                        lambda p, b: seen.append((p, b)))
    mod._atomic_write(tmp_path / "r.json", "x\n")
    assert seen == [(tmp_path / "r.json", b"x\n")]


@pytest.mark.parametrize("mod", MODS, ids=IDS)
def test_no_destination_derived_scratch_is_left_in_the_module(mod):
    src = Path(mod.__file__).read_bytes().decode("utf-8")
    assert ".tmp" not in src and "os.replace" not in src
