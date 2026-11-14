"""ops/loop/lane_model_log.py: MAIN ORDER 2026-11-14 0930 section 3, the model change log.

When a lane's model differs from its previous run, write a line (lane, old model, new
model, reason, date) to the change ledger and the lane status file. The current and the
previous model both come from the kit usage ledger (one row per run, note
lane-s144-<lane>), so "previous run" means the previous recorded run. Paths are tmp."""
from __future__ import annotations

import json
from pathlib import Path

from ops.loop import lane_model_log as ML

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"


def _row(ts, model, note="lane-s144-ds"):
    return {"ts": ts, "note": note, "model": model, "rc": 0}


def _usage(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(json.dumps(r) + "\n" for r in rows).encode("ascii"))
    return path


def _lines(path: Path) -> list:
    return [json.loads(x) for x in path.read_text(encoding="ascii").splitlines() if x]


def test_start_line_models_reads_the_runner_line(tmp_path):
    log = tmp_path / "lane.log"
    log.write_bytes(b"\xef\xbb\xbflane start 2026-11-14T10:00:00 cwd=C:\\wt model=claude-sonnet-5-5 "
                    b"kit_lane_model= effort=high prompt=x route=fleet_route\r\nmore\r\n")
    assert ML.start_line_models(log) == (SONNET, "")
    assert ML.start_line_models(tmp_path / "absent.log") == (None, None)


def test_model_source_names_who_picked_the_model():
    assert ML.model_source(OPUS, OPUS, None).startswith("kit lane_model")
    assert ML.model_source(SONNET, "", SONNET).startswith("RC trial RC_LANE_MODEL")
    assert ML.model_source(OPUS, "", None).startswith("config.json executor_model")


def test_a_changed_model_writes_one_line_with_lane_old_new_reason_date(tmp_path):
    usage = _usage(tmp_path / "u.jsonl", [
        _row("2026-11-13T10:00:00-06:00", SONNET),
        _row("2026-11-13T11:00:00-06:00", SONNET, note="lane-s144-repo"),
        _row("2026-11-14T10:00:00-06:00", OPUS),
    ])
    ledger = tmp_path / "changes.jsonl"
    rec = {"run_id": "s144d500-abc", "model": "config"}
    got = ML.check_cycle(tmp_path, "ds", rec, _row("2026-11-14T10:00:00-06:00", OPUS),
                         usage_path=usage, ledger_path=ledger, source="config.json executor_model")
    assert got is not None
    (line,) = _lines(ledger)
    assert line["lane"] == "ds" and line["old"] == SONNET and line["new"] == OPUS
    assert line["date"] == "2026-11-14" and line["run_id"] == "s144d500-abc"
    assert "config.json executor_model" in line["reason"]
    assert ML.format_line(line) == (
        f"2026-11-14 ds model {SONNET} -> {OPUS} ({line['reason']})")


def test_the_same_model_writes_nothing(tmp_path):
    usage = _usage(tmp_path / "u.jsonl", [_row("2026-11-13T10:00:00-06:00", OPUS),
                                           _row("2026-11-14T10:00:00-06:00", OPUS)])
    ledger = tmp_path / "changes.jsonl"
    assert ML.check_cycle(tmp_path, "ds", {}, _row("2026-11-14T10:00:00-06:00", OPUS),
                          usage_path=usage, ledger_path=ledger) is None
    assert not ledger.exists()


def test_a_first_run_or_a_run_with_no_usage_row_writes_nothing(tmp_path):
    usage = _usage(tmp_path / "u.jsonl", [_row("2026-11-14T10:00:00-06:00", OPUS)])
    ledger = tmp_path / "changes.jsonl"
    assert ML.check_cycle(tmp_path, "ds", {}, _row("2026-11-14T10:00:00-06:00", OPUS),
                          usage_path=usage, ledger_path=ledger) is None
    assert ML.check_cycle(tmp_path, "ds", {}, None, usage_path=usage,
                          ledger_path=ledger) is None
    assert not ledger.exists()


def test_known_history_carries_the_recorded_reason():
    why = ML.known_reason("ds", "2026-11-08", SONNET, OPUS)
    assert "f1954a39d" in why and "RM-1267" in why and "LEDGER 2077" in why
    assert "a30d17b25" in ML.known_reason("research", "2026-11-01", OPUS, SONNET)
    assert ML.known_reason("queue", "2026-11-08", SONNET, OPUS) is None


def test_backfill_writes_the_history_once(tmp_path):
    usage = _usage(tmp_path / "u.jsonl", [
        _row("2026-10-31T10:00:00-06:00", OPUS),
        _row("2026-11-01T15:03:12-06:00", SONNET),
        _row("2026-11-08T11:29:16-06:00", OPUS),
        _row("2026-11-08T12:00:00-06:00", OPUS),
    ])
    ledger = tmp_path / "changes.jsonl"
    assert len(ML.backfill(usage, ledger)) == 2
    assert len(ML.backfill(usage, ledger)) == 0
    rows = _lines(ledger)
    assert [(r["old"], r["new"], r["date"]) for r in rows] == [
        (OPUS, SONNET, "2026-11-01"), (SONNET, OPUS, "2026-11-08")]
    assert "RM-1267" in rows[1]["reason"]


def test_stamp_merges_the_last_lines_into_the_status_file(tmp_path):
    ledger = tmp_path / "changes.jsonl"
    for i in range(15):
        ML.append(ledger, {"ts": f"2026-11-14T10:{i:02d}:00-06:00", "date": "2026-11-14",
                           "lane": "ds", "old": OPUS, "new": SONNET, "reason": f"r{i}"})
    status = tmp_path / "s144-lanes.json"
    status.write_bytes(b'{"task": "s144-lanes", "daily": {}}')
    block = ML.stamp(tmp_path, status_path=status, ledger_path=ledger, last=10)
    doc = json.loads(status.read_text(encoding="ascii"))
    assert doc["task"] == "s144-lanes" and doc["daily"] == {}
    assert doc["model_changes"] == block and len(block["lines"]) == 10
    assert block["lines"][-1].endswith("(r14)")
