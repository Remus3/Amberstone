"""lib/ingest_receipt.py hardening (s144 true-audit, S144-T-700).

Each test pins one measured weakness of the Y-08 receipt log:

* a torn last line (crash mid-write) was the documented "skip, never
  repair" case, but the NEXT append was glued onto the fragment, so the
  reader dropped the new, complete row too - one crash cost two receipts;
* rows already glued that way are recovered by the reader (backfill): the
  complete row at the end of the line is salvaged, the fragment stays lost;
* ``read_receipts`` is documented "Never raises" but raised on a junk
  ``limit`` (None, "x", inf, NaN) or a non-path ``path``;
* ``build_row`` read a bool / negative / fractional ``attempt`` as a count,
  a bool ``now`` / ``scheduled_at`` as epoch second 1.0, and an overflowing
  ``elapsed_s`` (inf) made ``json.dumps(allow_nan=False)`` raise, so the
  whole receipt was lost; a non-str status whose ``repr`` raised lost the
  receipt too, although an unknown status must be recorded.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lib import ingest_receipt as ir

ROW_A = {"status": "ok", "match_id": "NA1_1000000001"}


def _lines(path: Path) -> list[str]:
    return path.read_bytes().decode("ascii").split("\n")


# --- torn tail -----------------------------------------------------------

def test_append_after_a_torn_tail_starts_a_new_line(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_bytes(b'{"v": 1, "ts": 5.0, "target": "NA1_9", "stat')
    assert ir.append_receipt(ROW_A, attempt=0, now=10.0, path=path)
    rows = ir.read_receipts(path)
    assert [r["target"] for r in rows] == ["NA1_1000000001"]
    lines = _lines(path)
    assert lines[0] == '{"v": 1, "ts": 5.0, "target": "NA1_9", "stat'
    assert json.loads(lines[1])["target"] == "NA1_1000000001"
    assert lines[2] == ""
    assert len(lines) == 3


def test_append_adds_no_blank_line_to_a_clean_file(tmp_path):
    path = tmp_path / "r.jsonl"
    for i in range(3):
        assert ir.append_receipt({"status": "ok", "match_id": f"NA1_{i}"},
                                 attempt=0, now=float(i), path=path)
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\n\n" not in raw
    assert not raw.startswith(b"\n")
    assert raw.count(b"\n") == 3


def test_append_to_an_empty_existing_file_adds_no_leading_newline(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_bytes(b"")
    assert ir.append_receipt(ROW_A, attempt=0, now=1.0, path=path)
    assert not path.read_bytes().startswith(b"\n")


def test_append_writes_lf_bytes_only(tmp_path):
    path = tmp_path / "r.jsonl"
    assert ir.append_receipt(ROW_A, attempt=0, now=1.0, path=path)
    assert b"\r" not in path.read_bytes()


# --- backfill: rows already glued to a fragment --------------------------

def test_reader_salvages_a_row_glued_to_a_torn_fragment(tmp_path):
    path = tmp_path / "r.jsonl"
    good = ir.build_row(ROW_A, scheduled_at=1.0, attempt=0, now=2.0)
    glued = '{"v": 1, "ts": 1.0, "status": "er' + json.dumps(good)
    path.write_text(glued + "\n", encoding="ascii", newline="\n")
    rows = ir.read_receipts(path)
    assert rows == [good]


def test_salvage_takes_only_a_complete_current_schema_row(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text(
        'junk{"v": 1, "status": \n'            # salvage target torn too
        'junk{"v": 2, "status": "ok"}\n'       # not this schema
        'junk{"v": 1, "status": 7}\n'          # status not a name
        '{"x": 1}{"v": 1, "status": "error", "ts": 3.0}\n',
        encoding="ascii", newline="\n")
    rows = ir.read_receipts(path)
    assert [r["status"] for r in rows] == ["error"]


@pytest.mark.parametrize("v", ["true", "1.0", '"1"'])
def test_salvage_wants_an_integer_schema_version(tmp_path, v):
    path = tmp_path / "r.jsonl"
    path.write_text('junk{"v": ' + v + ', "status": "ok"}\n',
                    encoding="ascii", newline="\n")
    assert ir.read_receipts(path) == []


@pytest.mark.parametrize("deep", ["[" * 200000, 'x{"v": ' + "[" * 200000])
def test_a_deeply_nested_line_costs_only_itself(tmp_path, deep):
    path = tmp_path / "r.jsonl"
    path.write_text('{"status": "ok", "ts": 1}\n' + deep + "\n"
                    '{"status": "error", "ts": 2}\n',
                    encoding="ascii", newline="\n")
    rows = ir.read_receipts(path)
    assert [r["status"] for r in rows] == ["ok", "error"]


def test_a_quoted_marker_inside_a_string_is_never_salvaged(tmp_path):
    # json.dumps escapes every quote inside a value, so a cause that
    # mentions the row prefix can never look like a row start.
    row = ir.build_row({"status": "error", "cause": '{"v": 1, "status": "ok"}'},
                       attempt=0, now=1.0)
    text = json.dumps(row)
    assert '{"v": ' not in text[1:]
    path = tmp_path / "r.jsonl"
    path.write_text("x" + text[1:] + "\n", encoding="ascii", newline="\n")
    assert ir.read_receipts(path) == []


# --- read_receipts never raises -----------------------------------------

@pytest.mark.parametrize("limit", [None, "x", "5", float("inf"), float("nan"),
                                   2.5, True, False, object(), [3]])
def test_read_receipts_never_raises_on_a_junk_limit(tmp_path, limit):
    path = tmp_path / "r.jsonl"
    for i in range(3):
        ir.append_receipt({"status": "ok", "match_id": f"NA1_{i}"},
                          attempt=0, now=float(i), path=path)
    rows = ir.read_receipts(path, limit=limit)
    assert [r["target"] for r in rows] == ["NA1_0", "NA1_1", "NA1_2"]


@pytest.mark.parametrize("limit,want", [(1, 1), (2, 2), (0, 1), (-4, 1)])
def test_read_receipts_integer_limit_keeps_the_tail(tmp_path, limit, want):
    path = tmp_path / "r.jsonl"
    for i in range(3):
        ir.append_receipt({"status": "ok", "match_id": f"NA1_{i}"},
                          attempt=0, now=float(i), path=path)
    rows = ir.read_receipts(path, limit=limit)
    assert len(rows) == want
    assert rows[-1]["target"] == "NA1_2"


@pytest.mark.parametrize("path", [123, object(), b"\x00bad", 1.5])
def test_read_receipts_never_raises_on_a_junk_path(path):
    assert ir.read_receipts(path) == []


# --- build_row field hygiene --------------------------------------------

@pytest.mark.parametrize("attempt", [True, False, -1, 2.5, float("nan"),
                                     "3", None])
def test_junk_attempt_is_not_a_count(attempt):
    row = ir.build_row(ROW_A, attempt=attempt, now=1.0)
    assert row["attempts"] is None


@pytest.mark.parametrize("attempt,want", [(0, 1), (4, 5)])
def test_integer_attempt_counts(attempt, want):
    assert ir.build_row(ROW_A, attempt=attempt, now=1.0)["attempts"] == want


def test_bool_now_is_not_an_epoch():
    before = time.time()
    row = ir.build_row(ROW_A, attempt=0, now=True)
    assert row["ts"] >= before


def test_bool_scheduled_at_is_not_a_start():
    row = ir.build_row(ROW_A, scheduled_at=True, attempt=0, now=100.0)
    assert row["elapsed_s"] is None


def test_overflowing_elapsed_never_loses_the_receipt(tmp_path):
    path = tmp_path / "r.jsonl"
    assert ir.append_receipt(ROW_A, scheduled_at=-1e308, attempt=0,
                             now=1e308, path=path)
    rows = ir.read_receipts(path)
    assert len(rows) == 1
    assert rows[0]["elapsed_s"] is None


class _BadRepr:
    def __repr__(self):
        raise RuntimeError("repr exploded")


def test_status_whose_repr_raises_is_still_recorded_as_unknown(tmp_path):
    path = tmp_path / "r.jsonl"
    assert ir.append_receipt({"status": _BadRepr()}, attempt=0, now=1.0,
                             path=path)
    rows = ir.read_receipts(path)
    assert len(rows) == 1
    assert ir.classify(rows[0]["status"]) == ir.CLASS_UNKNOWN
