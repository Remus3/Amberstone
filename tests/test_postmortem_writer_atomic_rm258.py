"""RM-258 family: the postmortem writer goes through core.polled_json.

``scripts/postmortem_analyze.py`` ``write_atomic`` hand-rolled the atomic
write: ``tempfile.mkstemp`` + a text-mode ``os.fdopen`` + a BARE
``os.replace``. Its output ``data/coaching/death_patterns.json`` is read at
runtime while the analyzer runs - ``dashboard/routes_personal_context.py``
serves it on request (mtime-keyed cache) and the four mode coaches read it
through ``core/death_patterns_loader.py`` - and the scheduled wrapper
``ops/run_postmortem_with_restart.ps1`` bounces RC only AFTER the write. So a
reader holding the file open met a rename with no retry. Two defects, each
pinned below:

  1. A bare ``os.replace`` raised on the first transient ``PermissionError``
     (WinError 5, a reader holding the destination open) and failed the run.
     core.polled_json retries with a bounded backoff and never leaves its
     scratch file.
  2. Text mode on Windows rewrites every ``\\n`` as ``\\r\\n``, so the report
     landed on disk CRLF while the serialized payload was LF.

The payload shape is unchanged: ``indent=2``, ASCII-escaped (json's default
``ensure_ascii``), one trailing newline.

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
from scripts import postmortem_analyze  # noqa: E402

_PAYLOAD = {
    "total_deaths": 3,
    "top3": ["solo_pickoff"],
    "patterns": {"solo_pickoff": {"label": "Solo pick " + chr(0xE9), "count": 2}},
}


def _expected_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def test_report_bytes_are_lf_ascii_with_one_trailing_newline(tmp_path):
    target = tmp_path / "death_patterns.json"
    postmortem_analyze.write_atomic(target, _PAYLOAD)
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw == _expected_bytes(_PAYLOAD)
    assert json.loads(raw.decode("ascii")) == _PAYLOAD


def test_a_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    target = tmp_path / "death_patterns.json"
    target.write_bytes(b"{}\n")
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    postmortem_analyze.write_atomic(target, _PAYLOAD)
    assert target.read_bytes() == _expected_bytes(_PAYLOAD)
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["death_patterns.json"]


def test_an_exhausted_replace_leaves_the_old_report_and_no_scratch(tmp_path, monkeypatch):
    target = tmp_path / "death_patterns.json"
    target.write_bytes(b"{}\n")

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        postmortem_analyze.write_atomic(target, _PAYLOAD)
    assert target.read_bytes() == b"{}\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["death_patterns.json"]


def test_the_writer_does_not_hand_roll_the_rename():
    """Source pin: write_atomic delegates instead of renaming itself."""
    src = pathlib.Path(postmortem_analyze.__file__).read_text(encoding="utf-8")
    assert "os.replace(" not in src
    assert "mkstemp(" not in src
    assert "from core.polled_json import atomic_write_text" in src
