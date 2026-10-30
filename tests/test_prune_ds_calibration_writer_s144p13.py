"""RM-1124: the DS calibration prune goes through core.polled_json.

``scripts/prune_synthetic_matches.py`` ``prune_ds_calibration`` rewrote
``data/ds_calibration.jsonl`` by hand: a destination-derived
``ds_calibration.tmp`` scratch, a text-mode ``Path.write_text`` and a BARE
``Path.replace``. The same file is appended to on every coaching tick by
``core/ds_calibration.py`` ``log_ds_run`` (four live coaches call it), so
an operator who runs the prune while RC is up can meet an appender holding
the destination open. Defects, each pinned below:

  1. The bare rename raised on the first transient ``PermissionError``
     (WinError 5) and left the ``.tmp`` scratch behind. core.polled_json
     retries with a bounded backoff and never leaves its scratch file.
  2. Text mode on Windows rewrote every ``\\n`` as ``\\r\\n``.
  3. ops/audit/P2_FINDINGS.md (W4-hw2 LOW): a dry run printed "would drop N"
     but its summary said ``dropped: 0`` with no would-drop count. The dry
     run now reports ``would_drop`` beside ``dropped: 0``.

The kept lines are unchanged: verbatim, in order, one ``\\n`` each.

scripts/ sits outside the repo-wide guard
``tests/test_atomic_write_guard_rm258_rm261.py`` (one-shot generator tree),
so this module carries its own source pin. Every test is platform-portable:
the transient failure is a monkeypatched ``os.replace``, never a held handle.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import polled_json  # noqa: E402
from scripts import prune_synthetic_matches as psm  # noqa: E402

_REAL = json.dumps({"champion": "Quinn", "mode": "ARENA", "ds_picks": [1]})
_SYNTH = json.dumps({"champion": "", "mode": "SR"})
_TEST = json.dumps({"champion": "TestDummy", "mode": "SR"})
_BAD = "{not json"
_ORIGINAL = "\n".join([_REAL, _SYNTH, _BAD, _TEST]) + "\n"
_EXPECTED = ("\n".join([_REAL, _BAD]) + "\n").encode("utf-8")


@pytest.fixture
def log(tmp_path, monkeypatch):
    target = tmp_path / "ds_calibration.jsonl"
    target.write_bytes(_ORIGINAL.encode("utf-8"))
    monkeypatch.setattr(psm, "DS_JSONL", target)
    return target


def _non_backup_names(directory: pathlib.Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()
                  if ".bak-" not in p.name)


def test_pruned_log_is_lf_and_keeps_the_lines_verbatim(log):
    result = psm.prune_ds_calibration(dry_run=False)
    raw = log.read_bytes()
    assert b"\r" not in raw
    assert raw == _EXPECTED
    assert result == {"in": 4, "dropped": 2, "kept": 2}
    assert _non_backup_names(log.parent) == ["ds_calibration.jsonl"]


def test_a_transient_permission_error_on_replace_is_retried(log, monkeypatch):
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    psm.prune_ds_calibration(dry_run=False)
    assert log.read_bytes() == _EXPECTED
    assert calls["n"] == 2
    assert _non_backup_names(log.parent) == ["ds_calibration.jsonl"]


def test_an_exhausted_replace_leaves_the_log_and_no_scratch(log, monkeypatch):
    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        psm.prune_ds_calibration(dry_run=False)
    assert log.read_bytes() == _ORIGINAL.encode("utf-8")
    assert _non_backup_names(log.parent) == ["ds_calibration.jsonl"]


def test_dry_run_summary_reports_the_would_drop_count(log):
    result = psm.prune_ds_calibration(dry_run=True)
    assert result == {"in": 4, "would_drop": 2, "dropped": 0, "kept": 2}
    assert log.read_bytes() == _ORIGINAL.encode("utf-8")
    assert sorted(p.name for p in log.parent.iterdir()) == ["ds_calibration.jsonl"]


def test_the_prune_does_not_hand_roll_the_rename():
    """Source pin: prune_ds_calibration delegates instead of renaming itself."""
    src = pathlib.Path(psm.__file__).read_text(encoding="utf-8")
    assert '.with_suffix(".tmp")' not in src
    assert "tmp.replace(" not in src
    assert "from core.polled_json import atomic_write_text" in src
