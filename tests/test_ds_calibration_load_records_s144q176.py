"""S144-Q-176: pin load_records' non-dict skip and its two warnings.

``core/ds_calibration_agreement.py`` ``load_records`` documents three
fail-soft behaviours. Before this file only the malformed-JSON skip was
tested; the S144-Q-123 round-2 verifier showed two mutants surviving every
ds_calibration test file:

  * M5: append a JSON line that parses to a non-dict (list, scalar, string,
    null) instead of skipping it. Every consumer indexes the rows as dicts
    (``rec.get(...)``), so one such row would raise downstream.
  * M9: drop the warning logged when a generation cannot be read. The load
    then returns ``[]`` with no trace of why the calibration report is empty.

These tests pin the skip, the skip COUNT in the summary warning (malformed
JSON and non-dict lines together, summed across rotation generations), the
silence on a clean file, and the read-failure warning. A private handler
is attached to the module's own logger, so the assertions do not depend on
how a sibling test configured propagation on the "rc" logger tree.

Every file lives in tmp_path.
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import ds_calibration_agreement as dca  # noqa: E402


def _row(game_id: str) -> str:
    return json.dumps({"game_id": game_id, "ts": 1.0, "ds_picks": []})


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def records():
    """Yield a handler on ``dca.log`` itself that keeps WARNING+ records.

    A private handler rather than caplog: caplog's root handler would see a
    record a second time through propagation.
    """
    handler = _ListHandler()
    old_level = dca.log.level
    dca.log.setLevel(logging.WARNING)
    dca.log.addHandler(handler)
    try:
        yield handler
    finally:
        dca.log.removeHandler(handler)
        dca.log.setLevel(old_level)


def _warnings(handler: _ListHandler) -> list[str]:
    return [r.getMessage() for r in handler.records
            if r.name == dca.log.name and r.levelno == logging.WARNING]


def test_non_dict_lines_are_skipped_and_dict_rows_keep_their_order(
        tmp_path, records):
    p = tmp_path / "cal.jsonl"
    lines = [
        _row("g1"),
        "[1, 2, 3]",
        "42",
        '"a string"',
        "null",
        "true",
        _row("g2"),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = dca.load_records(p)
    assert [r["game_id"] for r in out] == ["g1", "g2"]
    assert all(isinstance(r, dict) for r in out)


def test_skip_warning_counts_malformed_and_non_dict_lines_together(
        tmp_path, records):
    p = tmp_path / "cal.jsonl"
    p.write_text(
        "\n".join([_row("g1"), "{ not json", "[1]", "", "7", _row("g2")]) + "\n",
        encoding="utf-8")
    assert [r["game_id"] for r in dca.load_records(p)] == ["g1", "g2"]
    msgs = _warnings(records)
    assert msgs == [f"load_records {p}: skipped 3 malformed lines"]


def test_skip_count_is_summed_across_rotation_generations(tmp_path, records):
    base = tmp_path / "ds_calibration.jsonl"
    base.with_name(base.name + ".1").write_text(
        _row("g-old") + "\n[\"rotated\"]\n", encoding="utf-8")
    base.write_text("{ broken\n" + _row("g-new") + "\nnull\n", encoding="utf-8")
    assert [r["game_id"] for r in dca.load_records(base)] == ["g-old", "g-new"]
    assert _warnings(records) == [
        f"load_records {base}: skipped 3 malformed lines"]


def test_a_clean_file_logs_no_warning(tmp_path, records):
    p = tmp_path / "cal.jsonl"
    p.write_text(_row("g1") + "\n\n" + _row("g2") + "\n", encoding="utf-8")
    assert len(dca.load_records(p)) == 2
    assert _warnings(records) == []


def test_a_failed_read_returns_empty_and_logs_why(tmp_path, monkeypatch,
                                                  records):
    p = tmp_path / "cal.jsonl"
    p.write_text(_row("g1") + "\n", encoding="utf-8")
    real_open = open

    def denied(path, *args, **kwargs):
        if pathlib.Path(path) == p:
            raise PermissionError(13, "Permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", denied)
    assert dca.load_records(p) == []
    msgs = _warnings(records)
    assert len(msgs) == 1
    assert msgs[0].startswith(f"load_records {p}: ")
    assert "Permission denied" in msgs[0]


def test_a_single_skipped_line_is_still_reported(tmp_path, records):
    p = tmp_path / "cal.jsonl"
    p.write_text(_row("g1") + "\n[]\n", encoding="utf-8")
    assert [r["game_id"] for r in dca.load_records(p)] == ["g1"]
    assert _warnings(records) == [f"load_records {p}: skipped 1 malformed lines"]


def test_a_failed_read_drops_rows_already_read_from_older_generations(
        tmp_path, monkeypatch, records):
    # All or nothing: a readable `.1` read first does not leak a partial list
    # when the base then fails with a non-FileNotFoundError OSError.
    base = tmp_path / "ds_calibration.jsonl"
    base.with_name(base.name + ".1").write_text(_row("g-old") + "\n",
                                                encoding="utf-8")
    base.write_text(_row("g-new") + "\n", encoding="utf-8")
    real_open = open

    def denied(path, *args, **kwargs):
        if pathlib.Path(path) == base:
            raise PermissionError(13, "Permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", denied)
    assert dca.load_records(base) == []
    assert len(_warnings(records)) == 1
