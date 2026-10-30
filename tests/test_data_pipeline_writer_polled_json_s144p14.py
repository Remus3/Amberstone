"""RM-1125: scripts/data_pipeline.py writes through core.polled_json.

RC-PatchRefresh (weekly, ``pythonw scripts/data_pipeline.py all``) rewrites
data/meta/ddragon_*.json, web/data/*_index.json, the rank-tier live artifact
and the icon PNGs while RC is up and its routes read those files. The
pipeline's own ``_atomic_write_bytes`` hand-rolled the swap:

  1. a fixed ``<name>.tmp`` scratch derived from the destination alone, so two
     writers of one file (a manual run beside the scheduled one) share it
     (ops/audit/P2_FINDINGS.md W4-hw2 LOW, the tmp-suffix collision);
  2. a BARE ``Path.replace`` with no WinError 5 retry, so a reader holding the
     destination for a millisecond failed the whole refresh step (W4-hw2 LOW,
     the no-retry replace);
  3. no fsync before the rename.

It now delegates to ``core.polled_json.atomic_write_bytes``. The bytes it
writes are unchanged (tests/test_data_pipeline_lf_writes.py pins LF and the
exact text). scripts/ sits outside the repo-wide guard
tests/test_atomic_write_guard_rm258_rm261.py (one-shot generator tree), so
this module carries its own source pin. Every test is platform-portable: the
transient failure is a monkeypatched ``os.replace``, never a held handle.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import polled_json  # noqa: E402
from scripts import data_pipeline as dp  # noqa: E402

_ORIGINAL = b'{"previous": true}\n'
_NEW = '{\n  "new": 1\n}\n'


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "ddragon_items.json"
    path.write_bytes(_ORIGINAL)
    return path


def test_a_transient_permission_error_on_replace_is_retried(target, monkeypatch):
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    dp._atomic_write_text(target, _NEW)
    assert target.read_bytes() == _NEW.encode("utf-8")
    assert calls["n"] == 2
    assert sorted(p.name for p in target.parent.iterdir()) == ["ddragon_items.json"]


def test_an_exhausted_replace_keeps_the_target_and_no_scratch(target, monkeypatch):
    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        dp._write_bytes(target, b"\x89PNG" * 16)
    assert target.read_bytes() == _ORIGINAL
    assert sorted(p.name for p in target.parent.iterdir()) == ["ddragon_items.json"]


def test_two_writes_of_one_file_use_distinct_per_writer_scratch_names(
        target, monkeypatch):
    seen: list[str] = []
    real_replace = polled_json.os.replace

    def spy(src, dst):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", spy)
    dp._atomic_write_text(target, _NEW)
    dp._atomic_write_text(target, _NEW)
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(n.startswith("ddragon_items.json.") and n.endswith(".tmp")
               and n != "ddragon_items.json.tmp" for n in seen)


def test_the_pipeline_does_not_hand_roll_the_rename():
    """Source pin: the pipeline delegates instead of renaming itself."""
    src = pathlib.Path(dp.__file__).read_text(encoding="utf-8")
    assert 'path.name + ".tmp"' not in src
    assert "tmp.replace(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
