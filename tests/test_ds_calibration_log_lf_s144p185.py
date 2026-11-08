"""RM-481 residual (s144, RM-1697): the DS calibration log is appended as LF.

``core/ds_calibration.py`` ``log_ds_run`` appends one JSON line per coaching
tick to ``data/ds_calibration.jsonl`` with a text-mode ``open(..., "a")`` and
no ``newline=``. On Windows the text layer turns every "\\n" into "\\r\\n", so
the appended rows carried CRLF. The same file is REWRITTEN by
``scripts/prune_synthetic_matches.py`` through ``core.polled_json
.atomic_write_text``, which writes LF bytes (tests/
test_prune_ds_calibration_writer_s144p13.py), so a prune followed by more ticks
left one jsonl with LF rows and CRLF rows - the mixed-EOL shape
tests/test_tracked_writer_lf_sweep.py already pins out of
``ops/rc_incident_log.py`` (its append sink and trim rewrite are converted
together). The file is gitignored, so the sweep's "append-mode log sinks are
never tracked" exemption held, but the pair rule is the reason to convert this
sink: an appender whose file a sibling writer rewrites with LF emits LF too.

CI is Linux, where the text layer does not translate, so the assertion would
be vacuous without the harness below; a positive control proves the harness
turns a bare text-mode append into CRLF before the writer is trusted. The
harness is the shared tests/_crlf_text_layer.py (s154 C1b): the private copy
patched ``builtins.open`` only, so a ``Path.open`` writer was never reached.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import ds_calibration
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


def _log(game_id: str) -> None:
    ds_calibration.log_ds_run(
        champion="Ahri", mode="ARAM", level=9, owned_items=[3089],
        ds_picks=[{"item_id": 3089, "delta_dps": 12.5}], game_id=game_id,
        match_key=game_id)


def test_log_ds_run_appends_lf_bytes(crlf_text_layer):
    path = Path(ds_calibration._LOG_PATH)
    _log("synthetic-1")
    _log("synthetic-2")
    raw = path.read_bytes()
    assert b"\r" not in raw
    rows = [json.loads(line) for line in raw.decode("utf-8").split("\n") if line]
    assert [r["game_id"] for r in rows] == ["synthetic-1", "synthetic-2"]


def test_an_append_after_an_lf_rewrite_keeps_the_file_pure_lf(crlf_text_layer):
    """The prune rewrites LF; the next tick must not reintroduce CRLF."""
    path = Path(ds_calibration._LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"game_id": "kept"}\n')
    _log("after-prune")
    raw = path.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2
