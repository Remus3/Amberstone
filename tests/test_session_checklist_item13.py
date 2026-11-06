"""FLEET-KIT v7 item 13 - RC's session counter and checklist block.

Covers tools/session_checklist.py (counter read / stamp, the session-start
block, the progress write) and the two consumers: tools/rc_facts.py (the
SessionStart hook prints the block FIRST) and the tracked hand-off, which must
carry a `SESSION: <n>` line so the counter is never unseeded.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import session_checklist as sc  # noqa: E402

BOX = chr(0x2610)  # U+2610 ballot box; ASCII source

HANDOFF = (
    "NEXT SESSION\n"
    "------------\n"
    "SESSION: 41\n"
    "Next action: re-probe live state after the reboot.\n"
    "Open items:\n- a thing\n"
)


def _write(tmp_path, text):
    p = tmp_path / "RC-NEXT-SESSION.txt"
    p.write_bytes(text.encode("ascii"))
    return p


def test_read_session_parses_the_line(tmp_path):
    assert sc.read_session(_write(tmp_path, HANDOFF)) == 41


def test_read_session_absent_is_none(tmp_path):
    assert sc.read_session(_write(tmp_path, "NEXT SESSION\n----\nNext action: x\n")) is None
    assert sc.read_session(tmp_path / "missing.txt") is None


def test_stamp_replaces_existing_line_and_keeps_lf(tmp_path):
    p = _write(tmp_path, HANDOFF)
    sc.stamp_session(42, p)
    data = p.read_bytes()
    assert b"\r" not in data
    assert data.count(b"SESSION: ") == 1
    assert sc.read_session(p) == 42
    assert data.decode("ascii").replace("SESSION: 42", "SESSION: 41") == HANDOFF


def test_stamp_inserts_after_underline_when_absent(tmp_path):
    p = _write(tmp_path, "NEXT SESSION\n------------\nNext action: x\n")
    sc.stamp_session(7, p)
    assert p.read_text(encoding="ascii").splitlines()[:3] == [
        "NEXT SESSION", "------------", "SESSION: 7"]


def test_stamp_rejects_nonpositive(tmp_path):
    with pytest.raises(ValueError):
        sc.stamp_session(0, _write(tmp_path, HANDOFF))


def test_start_block_shape(tmp_path):
    block = sc.session_start_block(_write(tmp_path, HANDOFF))
    lines = block.splitlines()
    assert lines[0] == "Session 41 checklist"
    assert lines[1] == f"{BOX} C1: re-probe live state after the reboot."
    assert lines[2] == f"{BOX} /done"
    assert lines[3] == sc.DIRECTIVE
    assert len(lines) == 4


def test_start_block_flags_a_missing_counter(tmp_path):
    block = sc.session_start_block(_write(tmp_path, "Next action: x\n"))
    assert block.splitlines()[0] == "Session 0 checklist"
    assert f"{BOX} C0: Seed SESSION" in block


def test_start_block_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(sc, "read_session", boom)
    assert "unavailable: RuntimeError" in sc.session_start_block(tmp_path / "x")


def test_long_next_action_is_one_capped_line(tmp_path):
    block = sc.session_start_block(_write(tmp_path, "SESSION: 3\nNext action: " + "w " * 200 + "\n"))
    c1 = block.splitlines()[1]
    assert len(c1) <= len(f"{BOX} C1: ") + sc.TASK_MAX


def test_local_renderer_matches_kit():
    # The kit file is vendored and tracked (kit v8): absence must FAIL, not skip.
    kit = sc.kit_checklist()
    assert kit is not None, "ops/fleet_kit/fleet_checklist.py missing or unloadable"
    rows = [{"id": "C1", "task": "Do a thing"}, {"id": "C2", "task": "Do another"}]
    assert sc._local_render(5, rows, "note x") == kit.render(5, rows, "note x")


def test_source_is_ascii():
    for rel in ("tools/session_checklist.py", "tests/test_session_checklist_item13.py"):
        assert (ROOT / rel).read_bytes().isascii(), rel


def test_write_progress_carries_checklist(tmp_path):
    rows = [{"id": "R1", "task": "Pick the note", "state": None, "eta_s": None}]
    sc.write_progress(tmp_path, "inbox-responder", 10, "fire start", 60, "running", checklist=rows)
    doc = json.loads((tmp_path / "ops/loop/control/progress/inbox-responder.json").read_text())
    assert doc["status"] == "running"
    assert [r["id"] for r in doc["checklist"]] == ["R1"]
    assert {"task", "pct", "step", "eta_s", "status", "updated", "checklist"} <= set(doc)


# RM-258: both writers go through core.polled_json (per-writer scratch name,
# fsync, bounded WinError 5 retry), not a shared `<name>.tmp` plus a bare
# rename. The hand-off is read by the SessionStart hook and the progress file
# by the lane widget and the board, so a torn read loses the counter or a row.

def _record_writes(monkeypatch):
    import core.polled_json as pj
    seen = []
    real = pj._write_then_replace

    def rec(path, data):
        seen.append((Path(path).name, bytes(data)))
        return real(path, data)

    monkeypatch.setattr(pj, "_write_then_replace", rec)
    return seen


def test_rm258_stamp_routes_through_polled_json(tmp_path, monkeypatch):
    seen = _record_writes(monkeypatch)
    p = _write(tmp_path, HANDOFF)
    sc.stamp_session(42, p)
    expected = HANDOFF.replace("SESSION: 41", "SESSION: 42").encode("ascii")
    assert seen == [("RC-NEXT-SESSION.txt", expected)]
    assert p.read_bytes() == expected
    assert [x.name for x in tmp_path.iterdir()] == ["RC-NEXT-SESSION.txt"]


def test_rm258_stamp_survives_a_transient_rename_refusal(tmp_path, monkeypatch):
    import core.polled_json as pj
    real = pj.os.replace
    refusals = [2]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pj.os, "replace", flaky)
    monkeypatch.setattr(pj.time, "sleep", lambda _s: None)
    p = _write(tmp_path, HANDOFF)
    sc.stamp_session(43, p)
    assert refusals == [0]
    assert sc.read_session(p) == 43


def test_rm258_local_progress_fallback_routes_through_polled_json(tmp_path, monkeypatch):
    seen = _record_writes(monkeypatch)
    monkeypatch.setattr(sc, "KIT_HEADLESS", tmp_path / "no_kit.py")
    rows = [{"id": "R1", "task": "Pick the note", "state": None, "eta_s": None}]
    doc = sc.write_progress(tmp_path, "inbox-responder", 10, "fire start", 60, "running",
                            checklist=rows)
    target = tmp_path / "ops/loop/control/progress/inbox-responder.json"
    assert seen == [("inbox-responder.json", json.dumps(doc).encode("ascii"))]
    assert target.read_bytes() == json.dumps(doc).encode("ascii")
    assert [x.name for x in target.parent.iterdir()] == ["inbox-responder.json"]


def test_rm258_stamp_works_when_run_as_a_script(tmp_path):
    """`python tools/session_checklist.py --stamp` (tools/done.md section 10)
    puts tools/, not the repo root, on sys.path; the writer must still find
    core.polled_json."""
    import os
    import subprocess
    p = _write(tmp_path, HANDOFF)
    tools = str(ROOT / "tools")
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        f"root = Path({str(ROOT)!r}).resolve()\n"
        f"sys.path[:] = [{tools!r}] + [x for x in sys.path[1:] if Path(x or '.').resolve() != root]\n"
        "import session_checklist as sc\n"
        f"sc.stamp_session(9, {str(p)!r})\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env,
                       capture_output=True, text=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert r.returncode == 0, r.stderr
    assert sc.read_session(p) == 9


def test_cli_next_and_stamp(tmp_path, capsys):
    p = _write(tmp_path, HANDOFF)
    assert sc.main(["--next"], path=p) == 0
    assert capsys.readouterr().out.strip() == "42"
    assert sc.main(["--stamp", "42"], path=p) == 0
    assert sc.main(["--current"], path=p) == 0
    assert capsys.readouterr().out.split()[-1] == "42"


def test_cli_next_without_counter_fails_loud(tmp_path, capsys):
    assert sc.main(["--next"], path=_write(tmp_path, "Next action: x\n")) == 1


# Kit v10 (MAIN 2026-10-08 0839 ORDER step 5): checklist printing uses
# fleet_checklist.emit(), never print(). A cp1252 stream gets "[ ]" for the box
# (the SessionStart harness sets PYTHONUTF8, so the hook keeps U+2610) and a
# pythonw process (no stdout) prints nothing; neither raises.

def test_emit_survives_a_cp1252_stdout(monkeypatch):
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", wrapper)
    assert sc.emit(f"{BOX} /done") == "[ ] /done"
    wrapper.flush()
    assert raw.getvalue() == b"[ ] /done\n"


def test_emit_keeps_the_box_on_a_utf8_stdout(monkeypatch):
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
    monkeypatch.setattr(sys, "stdout", wrapper)
    assert sc.emit(f"{BOX} /done") == f"{BOX} /done"
    assert raw.getvalue() == f"{BOX} /done\n".encode()


def test_emit_under_pythonw_prints_nothing_and_never_raises(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    assert sc.emit(f"{BOX} /done") is None
    assert sc.main(["--show"], path=ROOT / "missing-handoff.txt") == 0


def test_emit_is_the_kits_emit(monkeypatch):
    kit = sc.kit_checklist()
    assert kit is not None and callable(getattr(kit, "emit", None)), "kit v10 emit()"
    calls = []
    monkeypatch.setattr(kit, "emit", lambda text, stream=None: calls.append(text) or text)
    sc.emit("x")
    assert calls == ["x"]


def test_cli_prints_through_emit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sc, "emit", lambda text, stream=None: calls.append(text) or text)
    assert sc.main(["--show"], path=_write(tmp_path, HANDOFF)) == 0
    assert calls and calls[0].startswith("Session 41 checklist")


def test_tracked_handoff_carries_the_counter():
    """The counter must be seeded in the tracked hand-off (item 13 a)."""
    assert sc.read_session(ROOT / "RC-NEXT-SESSION.txt") is not None


def test_rc_facts_prints_the_block_first(tmp_path, monkeypatch):
    from tools import rc_facts

    health = tmp_path / "health.json"
    health.write_text('{"pid": 1, "alive": true, "last_reload_ok": true}', encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_APP", tmp_path)
    monkeypatch.setattr(rc_facts, "_HANDOFF", _write(tmp_path, HANDOFF))
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: True)
    monkeypatch.setattr(rc_facts, "_health_all", dict)
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: None)
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    assert rc_facts.main(session=None) == 0
    text = buf.getvalue()
    assert text.startswith("Session 41 checklist\n"), text[:200]
    assert f"{BOX} /done" in text
    assert text.index(f"{BOX} /done") < text.index("# RC live state")


def _rc_facts_world(tmp_path, monkeypatch):
    from tools import rc_facts

    health = tmp_path / "health.json"
    health.write_text('{"pid": 1, "alive": true, "last_reload_ok": true}', encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_APP", tmp_path)
    monkeypatch.setattr(rc_facts, "_HANDOFF", _write(tmp_path, HANDOFF))
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: True)
    monkeypatch.setattr(rc_facts, "_health_all", dict)
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: None)
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    return rc_facts


def test_rc_facts_prints_the_block_through_emit(tmp_path, monkeypatch):
    rc_facts = _rc_facts_world(tmp_path, monkeypatch)
    calls = []
    real = sc.emit
    monkeypatch.setattr(sc, "emit", lambda text, stream=None: calls.append(text) or real(text, stream))
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    assert rc_facts.main(session=None) == 0
    assert len(calls) == 1 and calls[0].startswith("Session 41 checklist")
    assert buf.getvalue().startswith(calls[0] + "\n")


def test_rc_facts_on_a_cp1252_stdout_keeps_the_block_and_the_probe(tmp_path, monkeypatch):
    rc_facts = _rc_facts_world(tmp_path, monkeypatch)
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", wrapper)
    assert rc_facts.main(session=None) == 0
    wrapper.flush()
    text = raw.getvalue().decode("cp1252")
    assert text.startswith("Session 41 checklist\n")
    assert "[ ] /done" in text and text.index("[ ] /done") < text.index("# RC live state")


def test_rc_facts_under_pythonw_does_not_raise(tmp_path, monkeypatch):
    rc_facts = _rc_facts_world(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "stdout", None)
    assert rc_facts.main(session=None) == 0
