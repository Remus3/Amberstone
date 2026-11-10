# arch: lane 8 true-audit s144 cycle 169 regressions for ops/loop/intents.py | section=tests | frozen=no
"""Lane 8 (true-audit) s144 cycle 169 - ops/loop/intents.py hardening.

Each test names one weakness measured in the consumer half of the Mission
Control intent seam. Every test is isolated: the control dir and the hand-off
base are tmp_path, never the live ops/loop/control or the repo root.

1. consume() wrote the TRACKED hand-off without the pre-write gate that
   write_prompt() runs, so the intent path published a banned glyph the other
   path refuses.
2. tools/session_intent.py reported a gate refusal as "empty_prompt".
3. _read_doc() read a UTF-8 BOM intent file (PowerShell 5.1 Set-Content
   -Encoding UTF8 writes one) as absent, and let RecursionError on a deeply
   nested file escape pending().
4. consume() wrote the consumed marker to whatever `_path` the caller's doc
   named - an unrelated file, or the OTHER intent's file.
5. consume() raised AttributeError / TypeError on a non-dict doc or an
   unhashable intent instead of returning its documented refusal.
6. resolve_next_session_path() accepted Windows-normalised segments (a
   trailing space or dot), reserved characters and a non-dict doc, and never
   checked that the resolved target stays under the base.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ops.loop import intents

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT = "NEXT SESSION\nTask: keep going.\n"
EM_DASH = chr(0x2014)


@pytest.fixture
def ctl(tmp_path):
    d = tmp_path / "control"
    d.mkdir()
    return d


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def _queue(ctl, intent, **extra):
    doc = {"intent": intent, "key": "k-" + intent, "ts": 1.0,
           "consumed": False, "next_session_path": "RC-NEXT-SESSION.txt"}
    doc.update(extra)
    path = ctl / intents.INTENT_FILES[intent]
    path.write_bytes((json.dumps(doc) + "\n").encode("utf-8"))
    return path


# 1 ------------------------------------------------------------------------

def test_consume_runs_the_same_pre_write_gate_as_write_prompt(ctl, home):
    marker = _queue(ctl, "done_continue")
    bad = "hand-off " + EM_DASH + " with a banned glyph\n"
    with pytest.raises(intents.HandoffRefused):
        intents.consume(prompt=bad, root=ctl, base=home)
    assert not (home / "RC-NEXT-SESSION.txt").exists()
    # Nothing was marked: the operator's intent survives for the fixed retry.
    assert json.loads(marker.read_text(encoding="utf-8"))["consumed"] is False
    assert intents.consume(prompt=PROMPT, root=ctl, base=home)["ok"] is True


def test_a_replay_with_a_gated_prompt_still_answers_already_consumed(ctl,
                                                                     home):
    _queue(ctl, "halt_save")
    assert intents.consume(prompt=PROMPT, root=ctl, base=home)["ok"] is True
    again = intents.consume(prompt="x " + EM_DASH + "\n", root=ctl, base=home)
    assert again["reason"] == "already_consumed"


# 2 ------------------------------------------------------------------------

def _cli(*args, ctl, home):
    env = dict(os.environ)
    env["RC_INTENT_CONTROL_DIR"] = str(ctl)
    env["RC_INTENT_BASE"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "session_intent.py"),
         *args], capture_output=True, text=True, env=env,
        cwd=str(REPO_ROOT), timeout=120, check=False, **kw)


@pytest.mark.parametrize("mode", ["--consume", "--write-prompt"])
def test_cli_names_a_gate_refusal_as_such(ctl, home, tmp_path, mode):
    _queue(ctl, "done_continue")
    pf = tmp_path / "prompt.txt"
    pf.write_bytes(("bad " + EM_DASH + "\n").encode("utf-8"))
    proc = _cli(mode, "--prompt-file", str(pf), ctl=ctl, home=home)
    assert proc.returncode == 2, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is False
    assert out["reason"] == "handoff_refused"
    assert not (home / "RC-NEXT-SESSION.txt").exists()


def test_cli_empty_prompt_is_still_named_empty_prompt(ctl, home, tmp_path):
    _queue(ctl, "done_continue")
    pf = tmp_path / "prompt.txt"
    pf.write_bytes(b"   \n")
    proc = _cli("--consume", "--prompt-file", str(pf), ctl=ctl, home=home)
    assert proc.returncode == 2, proc.stderr
    assert json.loads(proc.stdout)["reason"] == "empty_prompt"


# 3 ------------------------------------------------------------------------

def test_a_bom_intent_file_is_pending_not_invisible(ctl, home):
    doc = {"intent": "halt_save", "key": "k1", "consumed": False}
    (ctl / intents.INTENT_FILES["halt_save"]).write_bytes(
        b"\xef\xbb\xbf" + json.dumps(doc).encode("utf-8"))
    found = intents.pending(root=ctl)
    assert found is not None and found["intent"] == "halt_save"
    assert intents.consume(prompt=PROMPT, root=ctl, base=home)["ok"] is True


def test_a_deeply_nested_intent_file_degrades_to_absent(ctl):
    (ctl / intents.INTENT_FILES["halt_save"]).write_bytes(
        b"[" * 200000 + b"]" * 200000)
    assert intents.pending(root=ctl) is None


# 4 ------------------------------------------------------------------------

def test_consume_never_overwrites_an_unrelated_path_named_by_the_doc(
        ctl, home, tmp_path):
    real = _queue(ctl, "done_continue")
    victim = tmp_path / "unrelated.json"
    victim.write_bytes(b'{"precious": 1}\n')
    doc = {"intent": "done_continue", "_path": str(victim)}
    result = intents.consume(doc, prompt=PROMPT, root=ctl, base=home)
    assert victim.read_bytes() == b'{"precious": 1}\n'
    assert result["ok"] is True
    assert json.loads(real.read_text(encoding="utf-8"))["consumed"] is True


def test_consume_never_marks_the_other_intents_file(ctl, home):
    _queue(ctl, "done_continue")
    halt = _queue(ctl, "halt_save")
    doc = {"intent": "done_continue", "_path": str(halt)}
    intents.consume(doc, prompt=PROMPT, root=ctl, base=home)
    assert json.loads(halt.read_text(encoding="utf-8"))["consumed"] is False


def test_consume_accepts_the_peeked_path_from_pending(ctl, home, tmp_path):
    """The honoured case: pending() under one dir, consume() names another."""
    other = tmp_path / "other"
    other.mkdir()
    marker = _queue(other, "halt_save")
    peeked = intents.pending(root=other)
    result = intents.consume(peeked, prompt=PROMPT, root=ctl, base=home)
    assert result["ok"] is True
    assert json.loads(marker.read_text(encoding="utf-8"))["consumed"] is True


@pytest.mark.parametrize("bad_path", [5, ["x"], {"a": 1}])
def test_consume_ignores_a_non_string_path(ctl, home, bad_path):
    real = _queue(ctl, "halt_save")
    doc = {"intent": "halt_save", "_path": bad_path}
    assert intents.consume(doc, prompt=PROMPT, root=ctl, base=home)["ok"]
    assert json.loads(real.read_text(encoding="utf-8"))["consumed"] is True


# 5 ------------------------------------------------------------------------

@pytest.mark.parametrize("doc", ["halt_save", ["halt_save"], 7,
                                 {"intent": ["halt_save"]},
                                 {"intent": {"x": 1}}])
def test_consume_refuses_a_junk_doc_instead_of_raising(ctl, home, doc):
    _queue(ctl, "halt_save")
    result = intents.consume(doc, prompt=PROMPT, root=ctl, base=home)
    assert result == {"ok": False, "reason": "no_pending_intent"}
    assert not (home / "RC-NEXT-SESSION.txt").exists()


# 6 ------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "sub/.. /RC-x.txt",
    "sub/... /RC-x.txt",
    "sub/RC-x.txt.",
    "sub /RC-x.txt",
    "sub./RC-x.txt",
    "su<b/RC-x.txt",
    "RC-x?.txt",
    'RC-"x".txt',
    "RC-x|y.txt",
    "RC-x*.txt",
    "sub\x00/RC-x.txt",
    "sub/\tRC-x.txt\t",
])
def test_windows_normalised_or_reserved_segments_fall_back(home, raw):
    got = intents.resolve_next_session_path({"next_session_path": raw},
                                            base=home)
    assert got == home / "RC-NEXT-SESSION.txt"


@pytest.mark.parametrize("doc", [["x"], "RC-x.txt", 3])
def test_a_non_dict_doc_falls_back_instead_of_raising(home, doc):
    assert intents.resolve_next_session_path(doc, base=home) == \
        home / "RC-NEXT-SESSION.txt"


def test_a_junction_out_of_the_base_falls_back(home, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = home / "linked"
    try:
        Path(link).symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        if sys.platform != "win32":
            pytest.skip("cannot create a directory link here")
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True, text=True, timeout=60, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if made.returncode != 0:
            pytest.skip("cannot create a junction here")
    got = intents.resolve_next_session_path(
        {"next_session_path": "linked/RC-x.txt"}, base=home)
    assert got == home / "RC-NEXT-SESSION.txt"


def test_a_plain_owned_subpath_is_still_honoured(home):
    got = intents.resolve_next_session_path(
        {"next_session_path": "sub/dir/RC-NEXT-SESSION.txt"}, base=home)
    assert got == home / "sub" / "dir" / "RC-NEXT-SESSION.txt"
