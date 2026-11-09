"""RC-5 - the repin tool's "unknown" control is a DESIGNED NEGATIVE, expected rc 1.

tools/repin_subagent_cli.py runs `--definitely-not-a-flag` and requires it to
exit 1. The kit logs the child's real rc in the usage row, and the kit owns the
row's shape, so the only room RC has is the note label. These tests pin: the
label the control now spawns under, the predicate RC's own failure count uses
(new label + the historical labels, measured in headless_usage.jsonl), that a
designed negative which did NOT behave as designed still counts as failed, and
that a control timeout leaves its cause in the evidence dir.
"""
from __future__ import annotations

import json
import subprocess
from subprocess import CompletedProcess

import pytest

from ops.loop import fleet_route
from tools import repin_subagent_cli as repin

UNKNOWN_ERR = "error: unknown option '--definitely-not-a-flag'"


def _row(note, rc=1, **over):
    row = {"note": note, "rc": rc, "error": None, "is_error": None, "limit": None,
           "kind": "build"}
    row.update(over)
    return row


def _unknown_spawn(notes):
    def spawn(prompt, *, note, extra, log_path):
        notes.append(note)
        open(log_path, "w", encoding="utf-8").close()
        return ({"rc": 1, "result": None, "error": None},
                CompletedProcess(args=[], returncode=1, stdout=None, stderr=UNKNOWN_ERR + "\n"))
    return spawn


# ---- the label ---------------------------------------------------------------

def test_the_unknown_control_spawns_under_the_designed_negative_label(tmp_path):
    notes = []
    m = repin.measure(tmp_path / "ev", controls=("unknown",), spawn_fn=_unknown_spawn(notes))
    assert m.results[0].passed, m.results[0].reasons
    assert notes == ["repin-subagent-cli-unknown-designed-negative-rc1"]


@pytest.mark.parametrize("name", ["canary", "neg", "leak"])
def test_the_model_controls_keep_their_plain_labels(name):
    assert repin.control_note(name) == f"repin-subagent-cli-{name}"


def test_the_tool_and_the_counter_agree_on_the_label():
    assert fleet_route.is_designed_negative(_row(repin.control_note("unknown"), 1))
    assert not fleet_route.is_designed_negative(_row(repin.control_note("canary"), 1))


# ---- the expected rc is exactly 1 --------------------------------------------

@pytest.mark.parametrize("rc,ok", [(1, True), (0, False), (2, False), (None, False)])
def test_the_unknown_control_expects_exactly_rc_1(tmp_path, rc, ok):
    log = tmp_path / "unknown.stream.jsonl"
    log.write_text("", encoding="ascii")
    assert repin.grade("unknown", "QX", rc, UNKNOWN_ERR + "\n", log).passed is ok


# ---- the failure count -------------------------------------------------------

@pytest.mark.parametrize("note", [
    "repin-subagent-cli-unknown-designed-negative-rc1",
    # every historical label, measured in headless_usage.jsonl
    "repin-subagent-cli-unknown",
    "rm684-canary-unknown",
    "f1s124-canary-unknown",
    "s125clipin-canary-unknown",
    "w2fclipin-canary-unknown",
])
def test_a_designed_negative_row_is_not_a_failure(note):
    assert fleet_route.is_designed_negative(_row(note))
    assert not fleet_route.row_failed(_row(note))
    # kit v27 puts the stderr tail in "error"
    assert not fleet_route.row_failed(_row(note, error=UNKNOWN_ERR))


@pytest.mark.parametrize("row", [
    _row("repin-subagent-cli-unknown-designed-negative-rc1", 0),  # the CLI accepted it
    _row("repin-subagent-cli-unknown-designed-negative-rc1", 2),
    _row("repin-subagent-cli-unknown-designed-negative-rc1", None, error="timeout"),
    _row("repin-subagent-cli-unknown-designed-negative-rc1", 1, error="spawn ENOENT"),
    _row("repin-subagent-cli-unknown-designed-negative-rc1", 1, error="rc 1"),
    _row("repin-subagent-cli-unknown-designed-negative-rc1", 1, is_error=True),
    _row("repin-subagent-cli-unknown-designed-negative-rc1", 1, limit="7d"),
    _row("repin-subagent-cli-unknown", 2),
])
def test_a_designed_negative_that_misbehaved_still_counts_failed(row):
    assert not fleet_route.is_designed_negative(row)
    assert fleet_route.row_failed(row)


@pytest.mark.parametrize("row,failed", [
    (_row("repin-subagent-cli-canary", 1), True),   # a real API failure, measured
    (_row("lane-s144-queue", 1), True),
    (_row("kit-rollout v26", None, error="timeout"), True),
    (_row("x", 0, is_error=True), True),
    (_row("unknown", 1), True),                     # a bare word is not the label
    (_row("some-unknown", 1), True),
    (_row("x", 0), False),
    (_row("x", None), False),
])
def test_every_other_row_is_judged_as_before(row, failed):
    assert fleet_route.row_failed(row) is failed


def _ledger(root, rows, tail=""):
    path = root / fleet_route.kit().USAGE_REL
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail, encoding="ascii")


def test_usage_failures_counts_a_window_of_the_ledger(tmp_path):
    _ledger(tmp_path, [_row("old", 1), _row("repin-subagent-cli-unknown"),
                       _row("repin-subagent-cli-canary"), _row("ok", 0)], tail="not json\n[]\n")
    got = fleet_route.usage_failures(root=tmp_path, last=3)
    assert got == {"rows": 3, "failed": 1, "designed_negative": 1,
                   "failed_notes": {"repin-subagent-cli-canary": 1}}


def test_usage_failures_of_a_missing_ledger_is_zero(tmp_path):
    assert fleet_route.usage_failures(root=tmp_path) == {
        "rows": 0, "failed": 0, "designed_negative": 0, "failed_notes": {}}


def test_the_cli_prints_the_count_and_starts_nothing(tmp_path, capsys, monkeypatch):
    def no_spawn(*a, **k):
        raise AssertionError("the count must not start a run")

    monkeypatch.setattr(fleet_route, "spawn", no_spawn)
    _ledger(tmp_path, [_row("repin-subagent-cli-unknown"), _row("lane", 1)])
    rc = fleet_route.main(["--usage-failures", "--root", str(tmp_path), "--last", "5"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["failed_notes"] == {"lane": 1}


# ---- the timeout cause -------------------------------------------------------

def test_a_control_timeout_logs_its_cause_in_the_evidence_dir(tmp_path):
    rows = ['{"type": "system", "subtype": "init"}', '{"type": "assistant", "x": "last"}']

    def slow(prompt, *, note, extra, log_path):
        if note == repin.control_note("unknown"):
            return _unknown_spawn([])(prompt, note=note, extra=extra, log_path=log_path)
        log_path.write_text("\n".join(rows) + "\n", encoding="ascii")
        raise subprocess.TimeoutExpired(["x"], 240)

    m = repin.measure(tmp_path / "ev", spawn_fn=slow)
    assert [r.name for r in m.results] == ["unknown", "canary"]
    assert m.results[-1].reasons == ["timeout"]
    doc = json.loads((tmp_path / "ev" / "summary.json").read_text(encoding="ascii"))
    cause = doc["results"][-1]["facts"]["timeout_cause"]
    assert cause["control"] == "canary" and cause["timeout_s"] == 240
    assert cause["elapsed_s"] >= 0 and cause["stream_rows"] == 2
    assert cause["last_stream_line"] == rows[-1]


def test_a_timeout_with_no_stream_says_so(tmp_path):
    def slow(prompt, *, note, extra, log_path):
        raise subprocess.TimeoutExpired(["x"], 240)

    m = repin.measure(tmp_path / "ev", spawn_fn=slow)
    cause = m.results[0].facts["timeout_cause"]
    assert cause["control"] == "unknown"
    assert cause["stream_rows"] == 0 and cause["last_stream_line"] is None


def test_the_logged_last_stream_line_is_capped(tmp_path):
    def slow(prompt, *, note, extra, log_path):
        log_path.write_text("x" * 5000 + "\n", encoding="ascii")
        raise subprocess.TimeoutExpired(["x"], 240)

    m = repin.measure(tmp_path / "ev", spawn_fn=slow)
    assert len(m.results[0].facts["timeout_cause"]["last_stream_line"]) <= repin.LAST_LINE_CAP
