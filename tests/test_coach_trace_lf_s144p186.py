"""RM-481 residual (s144, RM-1698): the coach trace ring buffer is appended as LF.

``core/coach_trace.py`` ``append`` writes one JSON line per coach call to
``data/coach_trace.jsonl`` with a text-mode ``open(..., "a")`` and no
``newline=``. On Windows the text layer turns every "\\n" into "\\r\\n", so the
appended rows carried CRLF. The same file is REWRITTEN by ``_trim`` (the
200-line ring buffer) through ``core.polled_json.atomic_write_text``, which
writes LF bytes, so the first trim followed by more calls left one jsonl with
LF rows and CRLF rows - the mixed-EOL pair shape pinned for
``core/ds_calibration.py`` (tests/test_ds_calibration_log_lf_s144p185.py).
The appender of a file a sibling writer rewrites with LF emits LF too.

CI is Linux, where the text layer does not translate, so the assertions would be
vacuous without the harness below; positive controls prove the harness turns a
bare ``open`` and a bare ``Path.open`` append into CRLF before the writer is
trusted (``Path.open`` goes through ``io.open`` with ``newline`` passed
POSITIONALLY, so the shared harness in tests/_crlf_text_layer.py patches both
names and reads ``newline`` from either place; s154 C1b). Each control also
asserts the harness recorded a forced write for its own file, so it cannot pass
on the strength of the host's own text layer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import coach_trace
from tests._crlf_text_layer import install_crlf_text_layer


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS."""
    return install_crlf_text_layer(monkeypatch)


def test_positive_control_a_bare_text_append_produces_crlf(tmp_path,
                                                           crlf_text_layer):
    target = tmp_path / "control.jsonl"
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert crlf_text_layer.forced_for(target), "harness missed open"
    assert target.read_bytes() == b"a\r\nb\r\n", "harness failed to force CRLF"


def test_positive_control_a_bare_path_open_append_produces_crlf(tmp_path,
                                                                crlf_text_layer):
    target = tmp_path / "control_path.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert crlf_text_layer.forced_for(target), "harness missed Path.open"
    assert target.read_bytes() == b"a\r\nb\r\n", "harness missed Path.open"


def _record(tag: str) -> None:
    coach_trace.append(mode="ARAM", model="synthetic-model", response=tag)


def test_append_writes_lf_bytes(crlf_text_layer):
    path = Path(coach_trace._TRACE_FILE)
    _record("synthetic-1")
    _record("synthetic-2")
    raw = path.read_bytes()
    assert b"\r" not in raw
    rows = [json.loads(line) for line in raw.decode("utf-8").split("\n") if line]
    assert [r["response"] for r in rows] == ["synthetic-1", "synthetic-2"]


def test_an_append_after_an_lf_trim_keeps_the_file_pure_lf(crlf_text_layer):
    """The ring-buffer trim rewrites LF; the next call must not add CRLF."""
    path = Path(coach_trace._TRACE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"response": "kept"}\n')
    _record("after-trim")
    raw = path.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2
