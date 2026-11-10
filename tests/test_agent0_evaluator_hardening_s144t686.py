"""S144-T-686 true-audit of ``agents/agent0_gatekeeper/evaluator.py``.

The evaluator is the last path check on a task filed through the supervisor
(``POST`` file-task -> ``scheduler._agent0_review``), so ``remote_path``,
``payload_ext``, ``tag`` and ``signature`` are filer-controlled. Each block
below pins one weakness measured at the audit's base:

* the payload type was self-declared: ``web\\evil.exe`` with
  ``payload_ext=".html"`` was ACCEPTED;
* an NTFS stream (``x.html:evil.exe``), a NUL / control byte, a Windows
  reserved device name and a trailing dot / space were ACCEPTED;
* the traversal guard missed partial and double percent-encoding, encoded
  separators and dot-only segments (its own comment promised the latter);
* a non-string field raised ``AttributeError`` / ``TypeError`` out of the
  gate instead of a dead-letter rejection;
* a bare-string config list was iterated per CHARACTER (``"25"`` authorised
  agents ``"2"`` and ``"5"``; ``".html"`` allowed ext ``"."``), and an empty
  prefix allowed every path;
* a raising game-state probe let a forwarder restart through (fail-open);
* the repeat window kept one bucket per signature forever.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agents.agent0_gatekeeper import Evaluator, Task
from agents.agent0_gatekeeper.evaluator import _RepeatWindow

BS = "\\"
SHARE = BS + BS + "192.0.2.237" + BS + "RCClient"
WEB = SHARE + BS + "web" + BS
FWD = SHARE + BS + "forwarder" + BS


def _task(**overrides) -> Task:
    base = dict(op="push-web-ui", originating_agent="5",
                remote_path=WEB + "index.html", payload_ext=".html", tag="ui")
    base.update(overrides)
    return Task(**base)


def _label(decision) -> str | None:
    return None if decision.rejection is None else decision.rejection.reason_label


# --- characterisation: the legitimate shapes still pass ----------------------

@pytest.mark.parametrize("path,ext", [
    (WEB + "index.html", ".html"),
    (WEB + "INDEX.HTML", ".html"),
    (WEB + "js" + BS + "app.min.js", ".js"),
    (WEB + "console.html", ".html"),
    (WEB + "conx.css", ".css"),
    (WEB + "com10.js", ".js"),
    (WEB + "a%41.html", ".html"),
])
def test_legitimate_web_paths_are_accepted(path, ext):
    d = Evaluator().evaluate(_task(remote_path=path, payload_ext=ext))
    assert d.accepted, _label(d)
    assert d.criteria_passed == [1, 2, 3, 4, 5, 6]


def test_restart_trigger_between_matches_is_accepted():
    e = Evaluator(game_state_probe=lambda: "NONE")
    d = e.evaluate(Task(op="trigger-forwarder-restart", originating_agent="2",
                        remote_path=FWD + "restart_trigger.txt",
                        payload_ext=".txt", tag="restart-forwarder"))
    assert d.accepted, _label(d)


# --- F1: the declared payload type must match the path's own suffix ----------

@pytest.mark.parametrize("path", [
    WEB + "evil.exe",
    WEB + "evil.html.exe",
    WEB + "evil",
    WEB + "sub" + BS,
])
def test_declared_payload_ext_must_match_the_path_suffix(path):
    d = Evaluator().evaluate(_task(remote_path=path, payload_ext=".html"))
    assert d.accepted is False
    assert d.rejection.reason_code == 2
    assert d.rejection.reason_label == "payload_suffix_mismatch"
    assert d.rejection.disposition == "dead_letter"


# --- F2a: names Windows rewrites or routes elsewhere --------------------------

@pytest.mark.parametrize("name", [
    "x.html:evil.exe",          # NTFS alternate data stream
    "x.html" + chr(0) + ".exe",  # NUL truncation
    "x" + chr(10) + ".html",     # control byte (log forging)
    "x" + chr(0x7F) + ".html",
    "x<.html", "x>.html", "x|.html", "x*.html", "x?.html", 'x".html',
    "x.html.",                  # trailing dot: Windows strips it
    "x.html ",                  # trailing space: Windows strips it
    "CON.html", "con.html", "nul.js", "AUX.css", "prn.html",
    "COM1.js", "lpt9.css", "COM1",
    "CONIN$.html", "conout$.js", "COM0.html", "lpt0.css",
    "COM\u00b9.html", "lpt\u00b3.css",
])
def test_unsafe_windows_names_are_rejected(name):
    d = Evaluator().evaluate(_task(remote_path=WEB + name, payload_ext=".html"))
    assert d.accepted is False
    assert d.rejection.reason_code == 3
    assert d.rejection.reason_label == "destination_unsafe_name"


def test_unsafe_name_in_a_directory_segment_is_rejected():
    d = Evaluator().evaluate(_task(remote_path=WEB + "aux" + BS + "x.html"))
    assert d.rejection is not None
    assert d.rejection.reason_label == "destination_unsafe_name"


def test_percent_encoded_nul_is_rejected():
    d = Evaluator().evaluate(_task(remote_path=WEB + "x.html%00.exe"))
    assert d.accepted is False
    assert d.rejection.reason_code == 3


# --- F2b: traversal the old guard missed ---------------------------------------

@pytest.mark.parametrize("seg", [
    "%2e.", ".%2E", "%2E%2e",
    "%252e%252e",               # double-encoded
    "%25252e%25252e",           # triple-encoded
    "..%5c..", "..%2f..",       # encoded separators
    "%5c..%5c",
    ".. ", "...", ".", ". ",    # dot / space only segments
])
def test_traversal_variants_are_rejected(seg):
    d = Evaluator().evaluate(_task(remote_path=WEB + seg + BS + "x.html"))
    assert d.accepted is False
    assert d.rejection.reason_code == 3
    assert d.rejection.reason_label == "destination_traversal"


def test_runaway_percent_nesting_is_rejected_not_looped():
    nested = "%" + "25" * 40 + "2e"
    d = Evaluator().evaluate(_task(remote_path=WEB + nested + nested + BS + "x.html"))
    assert d.accepted is False
    assert d.rejection.reason_code == 3


# --- F3: a junk field is a dead-letter rejection, never an exception -----------

@pytest.mark.parametrize("field,value", [
    ("remote_path", None), ("remote_path", 7), ("remote_path", b"\\\\x"),
    ("remote_path", WEB + "a" * 1100 + ".html"),
    ("op", "x" * 300), ("payload_ext", "." + "h" * 300), ("tag", "t" * 300),
    ("signature", "s" * 300), ("originating_agent", "5" * 300),
    ("payload_ext", None), ("payload_ext", 3),
    ("op", None), ("op", ["push-web-ui"]),
    ("tag", 5), ("tag", ["restart-forwarder"]),
    ("signature", ["s"]), ("signature", {"s": 1}),
    ("originating_agent", ["5"]), ("originating_agent", None), ("originating_agent", True),
])
def test_malformed_task_fields_are_rejected_not_raised(field, value):
    d = Evaluator().evaluate(_task(**{field: value}))
    assert d.accepted is False
    assert d.rejection.reason_code == 2
    assert d.rejection.reason_label == "malformed_task"
    assert d.rejection.disposition == "dead_letter"


def test_int_originating_agent_still_authorises():
    d = Evaluator().evaluate(_task(originating_agent=5))
    assert d.accepted, _label(d)


# --- F4: config junk fails CLOSED, never per-character -------------------------

def _write(tmp_path: Path, ops, allow) -> Evaluator:
    (tmp_path / "ops.json").write_text(json.dumps(ops), encoding="utf-8")
    (tmp_path / "al.json").write_text(json.dumps(allow), encoding="utf-8")
    return Evaluator(tmp_path / "ops.json", tmp_path / "al.json")


_GOOD_ALLOW = {"share_unc": SHARE, "allowed_prefixes": [WEB]}


def _ops(**spec):
    base = {"authorized_agents": ["2", "5"], "target_subdir": "web",
            "payload_extensions": [".html"]}
    base.update(spec)
    return {"operations": {"push-web-ui": base}}


def test_bare_string_authorized_agents_drops_the_op(tmp_path):
    e = _write(tmp_path, _ops(authorized_agents="25"), _GOOD_ALLOW)
    d = e.evaluate(_task())
    assert d.rejection.reason_label == "unknown_operation"


def test_bare_string_payload_extensions_drops_the_op(tmp_path):
    e = _write(tmp_path, _ops(payload_extensions=".html"), _GOOD_ALLOW)
    for path, ext in ((WEB + "x.", "."), (WEB + "x.h", "h"), (WEB + "x.html", ".html")):
        d = e.evaluate(_task(remote_path=path, payload_ext=ext))
        assert d.accepted is False


def test_dotless_or_junk_extension_entries_are_dropped(tmp_path):
    e = _write(tmp_path, _ops(payload_extensions=["html", ".", 5, "..", ".a/b", ".JS"]), _GOOD_ALLOW)
    assert e._ops["push-web-ui"]["payload_extensions"] == [".js"]
    assert e.evaluate(_task(remote_path=WEB + "x.js", payload_ext=".js")).accepted
    d = e.evaluate(_task(remote_path=WEB + "x.", payload_ext="."))
    assert d.accepted is False


def test_int_agent_ids_in_config_still_authorise(tmp_path):
    e = _write(tmp_path, _ops(authorized_agents=[5]), _GOOD_ALLOW)
    assert e.evaluate(_task()).accepted


def test_non_mapping_operations_rejects_every_op(tmp_path):
    e = _write(tmp_path, {"operations": ["push-web-ui"]}, _GOOD_ALLOW)
    assert e.evaluate(_task()).rejection.reason_label == "unknown_operation"


def test_non_mapping_op_spec_drops_the_op(tmp_path):
    e = _write(tmp_path, {"operations": {"push-web-ui": "web"}}, _GOOD_ALLOW)
    assert e.evaluate(_task()).rejection.reason_label == "unknown_operation"


@pytest.mark.parametrize("prefixes", [
    [""],                                   # empty prefix matched everything
    WEB,                                    # bare string iterated per char
    [BS + BS],                              # not under the share
    [BS + BS + "evil" + BS + "RCClient" + BS + "web" + BS],
    [SHARE + BS + "web"],                   # no trailing separator
    [7],
])
def test_junk_allowed_prefixes_fail_closed(tmp_path, prefixes):
    e = _write(tmp_path, _ops(), {"share_unc": SHARE, "allowed_prefixes": prefixes})
    d = e.evaluate(_task())
    assert d.accepted is False
    assert d.rejection.reason_code == 3


def test_share_match_needs_a_separator_after_the_share_root():
    e = Evaluator()
    assert e._target_machine_ok(SHARE + BS + "web" + BS + "x.html")
    assert not e._target_machine_ok(SHARE + "X" + BS + "web" + BS + "x.html")


@pytest.mark.parametrize("share", ["", 7, None, "RCClient"])
def test_junk_share_unc_fails_closed(tmp_path, share):
    e = _write(tmp_path, _ops(), {"share_unc": share, "allowed_prefixes": [WEB]})
    d = e.evaluate(_task())
    assert d.accepted is False


# --- F5: an unreadable game state blocks a forwarder restart ------------------

def test_raising_game_state_probe_blocks_a_restart():
    def _boom():
        raise RuntimeError("lcu down")

    e = Evaluator(game_state_probe=_boom)
    d = e.evaluate(Task(op="trigger-forwarder-restart", originating_agent="2",
                        remote_path=FWD + "restart_trigger.txt",
                        payload_ext=".txt", tag="restart-forwarder"))
    assert d.accepted is False
    assert d.rejection.reason_label == "active_match_protected"
    assert d.rejection.disposition == "retry_once"


def test_raising_probe_does_not_touch_untagged_tasks():
    def _boom():
        raise RuntimeError("lcu down")

    assert Evaluator(game_state_probe=_boom).evaluate(_task()).accepted


# --- F6: the repeat window forgets stale signatures --------------------------

def test_repeat_window_prunes_stale_signatures():
    w = _RepeatWindow(window_sec=60.0, max_in_window=3)
    for i in range(1000):
        w.observe_and_check(f"s{i}", now=float(i))
    w.observe_and_check("z", now=10_000.0)
    assert len(w._events) <= 2


def test_repeat_window_still_trips_inside_the_window():
    w = _RepeatWindow(window_sec=60.0, max_in_window=3)
    assert w.observe_and_check("a", now=0.0) is False
    assert w.observe_and_check("a", now=1.0) is False
    assert w.observe_and_check("a", now=2.0) is True
    assert w.observe_and_check("a", now=200.0) is False


# --- log line cannot be forged by a filer-controlled path ----------------------

def test_reject_log_line_carries_no_raw_newline(caplog):
    caplog.set_level(logging.WARNING, logger="agent0.evaluator")
    Evaluator().evaluate(_task(remote_path=WEB + "x" + chr(10) + "FORGED.html"))
    assert caplog.records
    for rec in caplog.records:
        assert chr(10) not in rec.getMessage()
