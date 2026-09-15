# arch: once-per-session inbox surfacing guards | section=tests | frozen=no
"""Guards for the per-session reported record in tools/rc_facts.py.

WHY THIS EXISTS. The cross-repo inbox watcher had exactly two failure
directions and shipped with a guard against neither:

  * TOO QUIET. Three states printed NOTHING and were indistinguishable from a
    clean inbox - an absent moon_sync_inbox/ returned 0 in silence, an
    unreadable seen store was coerced to an empty set (which prints everything
    as unread, the opposite of silent, but for a reason nobody could see), and
    an AttributeError from a valid-JSON non-dict store escaped an
    `except OSError` and exited 1, which drops the hook's stdout entirely.
  * TOO LOUD. The same full block re-printed on every operator prompt for the
    whole life of a session, which trains the reader to skip the one section
    that carries a sibling's correction or retraction.

The fix is a per-session-id record of what has already been SHOWN, which is not
the same thing as what has been ACKNOWLEDGED - the seen store stays the only
ack, and nothing here ever writes it. Every assertion below is derived from a
specific way the answer "was this shown, and did the watcher actually look"
has already been unavailable.

THE ORDER IS THE LOAD-BEARING PART. A record written before the block reaches
stdout marks the block shown; a hook killed at its 8 s SessionStart timeout has
its stdout dropped, so the whole session would then print nothing. Hence:
report file first (it records nothing, so a kill after it suppresses nothing,
and the pointer never names an absent file), then stdout and flush, then the
record, and only inside a wall-clock budget below the hook timeout.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.rc_facts as rc_facts  # noqa: E402

_PY = sys.executable
_REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------- fixtures


def _digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _key(name: str, body: str) -> str:
    return f"{name} [{_digest(body)}]"


def _repo(tmp_path: Path, monkeypatch, *, inbox: bool = True) -> Path:
    """A tmp _ROOT with the two runtime paths the watcher writes under.

    `_T0` is re-stamped deliberately: it is captured at MODULE scope, so in a
    suite that has been running for more than the record budget every record
    assertion would fail for a reason that has nothing to do with the code
    under test.
    """
    root = tmp_path / "repo"
    (root / "ops" / "runtime").mkdir(parents=True)
    if inbox:
        (root / "moon_sync_inbox").mkdir(parents=True)
    monkeypatch.setattr(rc_facts, "_ROOT", root)
    monkeypatch.setattr(rc_facts, "_T0", time.monotonic())
    return root


def _note(root: Path, name: str, body: str) -> str:
    (root / "moon_sync_inbox" / name).write_text(body, encoding="utf-8")
    return _key(name, body)


def _quiet_probes(monkeypatch, root: Path) -> None:
    """Neutralise main()'s live probes so a unit test does not hit the network.

    _HEALTH is monkeypatched too: it derives from a SECOND module global
    (_APP), so patching _ROOT alone leaves main() reading the live health file.
    """
    monkeypatch.setattr(rc_facts, "_HEALTH", root / "ops" / "runtime" / "health.json")
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: [])
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: False)


def _capture(monkeypatch) -> io.StringIO:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    return buf


def _reported_file(root: Path) -> Path:
    return root / "ops" / "runtime" / "sync_inbox_reported.json"


def _report_file(root: Path) -> Path:
    return root / "ops" / "runtime" / "sync_inbox_report.txt"


# ----------------------------------------------------- the factored section


def test_inbox_section_golden_lines_three_notes_session_none(tmp_path, monkeypatch):
    """The exact block, written out literally rather than described.

    A test that only asserts "some header appears" passes against a watcher
    that lost the entries under it, which is the direction that costs
    something here.
    """
    root = _repo(tmp_path, monkeypatch)
    ka = _note(root, "a.md", "one")
    kb = _note(root, "b.md", "two")
    kc = _note(root, "c.md", "three")

    lines, anomalies, keys = rc_facts._inbox_section(root, None)

    assert lines == [
        "## Cross-repo inbox - 3 UNREAD",
        f"- {ka}",
        f"- {kb}",
        f"- {kc}",
        "Read them, then record them as seen:",
        "  python tools/rc_facts.py --mark-inbox-seen",
    ]
    assert anomalies == ["moon_sync_inbox: 3 unread note(s) from sibling repos"]
    assert keys == {ka, kb, kc}


def test_importing_a_copy_of_rc_facts_creates_no_file(tmp_path):
    """Nothing may execute at import.

    tools/moon_sync_poller.py and tools/inbox_responder_runner.py both import
    this module, so an import-time write (or an import-time fault) reaches a
    long-lived poller restart loop, not just a hook fire.
    """
    (tmp_path / "tools").mkdir()
    copied = tmp_path / "tools" / "rc_facts.py"
    copied.write_bytes((_REPO_ROOT / "tools" / "rc_facts.py").read_bytes())

    prog = (
        "import importlib.util, sys;"
        f"spec = importlib.util.spec_from_file_location('probe_rc_facts', r'{copied}');"
        "m = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(m);"
        "print('IMPORT-OK')"
    )
    r = subprocess.run(
        [_PY, "-c", prog], capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )

    assert r.returncode == 0, r.stderr
    assert "IMPORT-OK" in r.stdout, "the import did not complete, so the absence proves nothing"
    assert not (tmp_path / "ops").exists(), "importing the module created ops/"


def test_session_id_is_validated_before_use():
    assert rc_facts._session_id({"session_id": "abc/..\\x"}) is None
    assert rc_facts._session_id({"session_id": 12}) is None
    assert rc_facts._session_id({"session_id": None}) is None
    assert rc_facts._session_id({"session_id": ""}) is None
    assert rc_facts._session_id({"session_id": "a0f2a498-1b03-4d80-9c12-298bb6317777"}) == (
        "a0f2a498-1b03-4d80-9c12-298bb6317777"
    )


# ------------------------------------------------- once per session id


def test_inbox_only_prints_each_unread_key_once_per_session(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    buf = _capture(monkeypatch)
    assert rc_facts.report_inbox_only(session="s") == 0
    assert "a.md" in buf.getvalue(), "the first fire must actually show the note"

    buf2 = _capture(monkeypatch)
    assert rc_facts.report_inbox_only(session="s") == 0
    assert buf2.getvalue() == ""


def test_new_arrival_mid_session_prints_once(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")

    _note(root, "b.md", "two")
    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    shown = buf.getvalue()
    assert "b.md" in shown
    assert "a.md" not in shown, "an already-shown note re-printed beside the new one"

    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert buf2.getvalue() == ""


def test_edited_note_new_digest_prints_once(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")

    _note(root, "a.md", "one CORRECTION two")
    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    shown = buf.getvalue()
    assert _digest("one CORRECTION two") in shown
    assert _digest("one") not in shown

    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert buf2.getvalue() == ""


def test_withdrawal_prints_once_per_session(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    key = _note(root, "a.md", "one")
    (root / "ops" / "runtime" / "sync_inbox_seen.json").write_text(
        json.dumps({"seen": [key]}), encoding="utf-8")
    (root / "moon_sync_inbox" / "a.md").unlink()

    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert "WITHDRAWN" in buf.getvalue()

    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert "WITHDRAWN" not in buf2.getvalue()


def test_second_session_id_prints_again(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")

    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="t")
    assert "a.md" in buf.getvalue(), "a second live session id was suppressed by the first"


def test_no_session_id_prints_every_time_and_writes_no_record(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    for i in range(12):
        _note(root, f"n{i:02d}.md", f"body {i}")

    for _ in range(2):
        buf = _capture(monkeypatch)
        assert rc_facts.report_inbox_only() == 0
        shown = buf.getvalue()
        assert "12 UNREAD" in shown
        assert "- ... and 2 more" in shown
        assert "sync_inbox_report.txt" not in shown, (
            "a sid-less run named a report file it is not allowed to write")

    assert not _reported_file(root).exists()
    assert not _report_file(root).exists()


def test_session_start_marks_its_block_reported_for_that_session(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _quiet_probes(monkeypatch, root)
    _note(root, "a.md", "one")

    _capture(monkeypatch)
    assert rc_facts.main(session="s") == 0

    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert buf.getvalue() == "", "SessionStart's block did not count as shown for its own sid"

    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="t")
    assert "a.md" in buf2.getvalue(), "the record is global, not per session id"


def test_session_start_always_prints_even_when_already_reported(tmp_path, monkeypatch):
    """main() never subtracts. A resume that keeps the sid re-prints ONCE.

    The opposite - a SessionStart that subtracts its own record - delivers an
    empty block into a fresh context, which is the failure direction the whole
    design forbids.
    """
    root = _repo(tmp_path, monkeypatch)
    _quiet_probes(monkeypatch, root)
    _note(root, "a.md", "one")

    buf = _capture(monkeypatch)
    rc_facts.main(session="s")
    assert "a.md" in buf.getvalue()
    assert _reported_file(root).exists()

    buf2 = _capture(monkeypatch)
    rc_facts.main(session="s")
    assert "a.md" in buf2.getvalue(), "SessionStart printed an empty block on a resume"


# ---------------------------------------------------- UNMEASURED states


def test_missing_inbox_prints_unmeasured_not_silence(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch, inbox=False)
    _quiet_probes(monkeypatch, root)
    token = "UNMEASURED: moon_sync_inbox/ absent"

    buf = _capture(monkeypatch)
    assert rc_facts.report_inbox_only(session="s") == 0
    assert token in buf.getvalue()

    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert buf2.getvalue() == "", "an absent inbox re-printed under the same sid"

    buf3 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="u")
    assert token in buf3.getvalue(), "a new sid must see the fault"

    for _ in range(2):
        buf4 = _capture(monkeypatch)
        rc_facts.report_inbox_only()
        assert token in buf4.getvalue(), "a sid-less run must fail open"

    recorded = json.loads(_reported_file(root).read_text(encoding="utf-8"))
    assert recorded["sessions"]["s"]["keys"] == ["UNMEASURED:inbox-absent"]

    buf5 = _capture(monkeypatch)
    assert rc_facts.main(session="s") == 0
    assert token in buf5.getvalue(), "SessionStart must always print the fault"


def test_absent_seen_store_lists_everything_unread_not_unmeasured(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    for i in range(5):
        _note(root, f"n{i}.md", f"body {i}")

    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    shown = buf.getvalue()
    assert "5 UNREAD" in shown
    assert "UNMEASURED" not in shown, "a store that never existed is not a failure to look"


def test_unreadable_seen_store_prints_one_unmeasured_line_not_everything_unread(
        tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    for i in range(50):
        _note(root, f"n{i:02d}.md", f"body {i}")
    (root / "ops" / "runtime" / "sync_inbox_seen.json").write_text("garbage", encoding="utf-8")

    buf = _capture(monkeypatch)
    assert rc_facts.report_inbox_only(session="s") == 0
    shown = buf.getvalue()
    assert len([ln for ln in shown.splitlines() if "UNMEASURED" in ln]) == 1
    assert "50 UNREAD" not in shown

    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert "UNMEASURED" in buf2.getvalue(), (
        "a transient blind state went quiet, which reads as a clean inbox")


@pytest.mark.parametrize("body", ["[]", '"x"'])
def test_seen_store_that_is_a_json_list_prints_one_unmeasured_line(
        tmp_path, monkeypatch, body):
    root = _repo(tmp_path, monkeypatch)
    for i in range(5):
        _note(root, f"n{i}.md", f"body {i}")
    (root / "ops" / "runtime" / "sync_inbox_seen.json").write_text(body, encoding="utf-8")

    buf = _capture(monkeypatch)
    assert rc_facts.report_inbox_only(session="s") == 0
    shown = buf.getvalue()
    assert len([ln for ln in shown.splitlines() if "UNMEASURED" in ln]) == 1
    assert "5 UNREAD" not in shown


def test_unexpected_exception_exits_zero_with_unmeasured_line(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    def boom(_inbox):
        raise RuntimeError("probe")

    monkeypatch.setattr(rc_facts, "_inbox_entries", boom)

    assert rc_facts.report_inbox_only(session="s") == 0
    cap = capsys.readouterr()
    lines = [ln for ln in cap.out.splitlines() if ln.strip()]
    assert lines == ["## Cross-repo inbox - UNMEASURED: watcher failed (RuntimeError)"]
    assert cap.err == "", "a traceback reached stderr"


def test_non_ascii_name_does_not_raise(tmp_path, monkeypatch):
    """The name is built from an escape on purpose - a literal trips the
    repo's ASCII source sweep."""
    root = _repo(tmp_path, monkeypatch)
    _note(root, "note-" + chr(0x4E2D) + ".md", "one")

    raw = io.BytesIO()
    strict = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="")
    monkeypatch.setattr(sys, "stdout", strict)
    assert rc_facts.report_inbox_only(session="s") == 0
    strict.flush()

    assert "\\u4e2d" in raw.getvalue().decode("ascii")


# ------------------------------------------------- the cap and the report file


def _many(root: Path, n: int) -> list[str]:
    keys = []
    for i in range(n):
        name = f"n{i:03d}-" + "x" * 110 + ".md"
        keys.append(_note(root, name[:120], f"body {i}"))
    return keys


def test_cap_is_asserted_not_commented(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _many(root, 250)

    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    lines = buf.getvalue().splitlines()

    names = [ln for ln in lines if ln.startswith("- ") and not ln.startswith("- ... ")]
    pointer = [ln for ln in lines if ln.startswith("- ... ")]
    assert len(names) == 10
    assert pointer == ["- ... and 240 more - ops/runtime/sync_inbox_report.txt"]
    assert len(_report_file(root).read_text(encoding="utf-8").splitlines()) == 250


def test_full_report_file_lists_every_unread_beyond_the_cap(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    keys = _many(root, 250)

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")

    listed = set(_report_file(root).read_text(encoding="utf-8").splitlines())
    assert listed == set(keys)


def test_report_file_is_rewritten_not_appended(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _many(root, 250)

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    size1 = _report_file(root).stat().st_size

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="t")
    assert _report_file(root).stat().st_size == size1


def test_report_file_untouched_when_unchanged(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _many(root, 12)

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    before = _report_file(root).stat().st_mtime_ns

    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="t")
    assert _report_file(root).stat().st_mtime_ns == before


def test_report_file_is_written_before_stdout(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    keys = _many(root, 250)
    saw: list[int] = []

    class _Checker(io.StringIO):
        def write(self, s):  # noqa: D102
            if _report_file(root).exists():
                saw.append(len(_report_file(root).read_text(encoding="utf-8").splitlines()))
            else:
                saw.append(-1)
            return super().write(s)

    monkeypatch.setattr(sys, "stdout", _Checker())
    rc_facts.report_inbox_only(session="s")

    assert saw, "nothing was written to stdout at all"
    assert saw[0] == len(keys), (
        "the pointer named a report file that did not exist yet at the moment "
        "the block was written")


def test_unwritable_report_file_prints_unmeasured_pointer_and_records_nothing_beyond_the_cap(
        tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _many(root, 250)

    def boom(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(rc_facts, "_write_inbox_report", boom)

    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    lines = buf.getvalue().splitlines()
    assert [ln for ln in lines if ln.startswith("- ... ")] == [
        "- ... and 240 more - UNMEASURED: report file unwritable (PermissionError)"
    ]

    recorded = json.loads(_reported_file(root).read_text(encoding="utf-8"))
    assert len(recorded["sessions"]["s"]["keys"]) == 10

    # The 10 that WERE shown are recorded; the 240 the pointer could not point
    # at are not, so they come back on the next fire behind the same
    # UNMEASURED pointer - which is the whole point of not recording them.
    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    lines2 = buf2.getvalue().splitlines()
    assert "## Cross-repo inbox - 240 UNREAD" in lines2
    assert [ln for ln in lines2 if ln.startswith("- ... ")] == [
        "- ... and 230 more - UNMEASURED: report file unwritable (PermissionError)"
    ]


# ------------------------------------------------------------- the ordering


def test_record_is_not_written_when_stdout_write_fails(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    class _Boom:
        def write(self, _s):
            raise OSError("stdout is gone")

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", _Boom())
    assert rc_facts.report_inbox_only(session="s") == 0
    assert not _reported_file(root).exists()

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert rc_facts.report_inbox_only(session="s") == 0
    assert _reported_file(root).exists(), (
        "the control arm proves the absence above was caused by the failure")


def test_record_written_after_output(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")
    buf = _capture(monkeypatch)
    seen_at_record: list[str] = []

    real = rc_facts._save_reported

    def wrapper(sid, keys):
        seen_at_record.append(buf.getvalue())
        return real(sid, keys)

    monkeypatch.setattr(rc_facts, "_save_reported", wrapper)
    rc_facts.report_inbox_only(session="s")

    assert seen_at_record, "_save_reported was never called"
    assert "a.md" in seen_at_record[0], "the record was written before the block was delivered"


def test_record_is_skipped_past_the_sessionstart_budget(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")
    t0 = rc_facts._T0

    monkeypatch.setattr(rc_facts.time, "monotonic", lambda: t0 + 7.0)
    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert "a.md" in buf.getvalue()
    assert not _reported_file(root).exists(), (
        "a hook the harness is about to kill marked its block reported")

    monkeypatch.setattr(rc_facts.time, "monotonic", lambda: t0 + 1.0)
    _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert _reported_file(root).exists()


# --------------------------------------------------------- the record itself


def test_reported_record_is_keyed_per_session_id(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    rc_facts._save_reported("s", {"a.md [aaa]"})
    rc_facts._save_reported("t", {"b.md [bbb]"})

    assert rc_facts._reported_keys("s") == {"a.md [aaa]"}
    assert rc_facts._reported_keys("t") == {"b.md [bbb]"}


def test_reported_record_is_bounded_to_64_sessions_and_eviction_only_reprints(
        tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    for i in range(65):
        rc_facts._save_reported(f"sid{i:03d}", {f"k{i}"})

    data = json.loads(_reported_file(root).read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert len(data["sessions"]) == 64
    assert "sid000" not in data["sessions"], "the oldest sid was not evicted"

    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="sid000")
    assert "a.md" in buf.getvalue(), "eviction must cause a RE-PRINT, never a suppression"


def test_reported_write_failure_falls_open(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _note(root, "a.md", "one")

    def boom(self, _target):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "replace", boom)
    buf = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert "a.md" in buf.getvalue()
    monkeypatch.undo()
    monkeypatch.setattr(rc_facts, "_ROOT", root)
    monkeypatch.setattr(rc_facts, "_T0", time.monotonic())

    buf2 = _capture(monkeypatch)
    rc_facts.report_inbox_only(session="s")
    assert "a.md" in buf2.getvalue(), "a failed record write suppressed the next fire"


def test_reported_record_never_touches_seen_file(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    key = _note(root, "a.md", "one")
    seen = root / "ops" / "runtime" / "sync_inbox_seen.json"
    seen.write_text(json.dumps({"seen": [key]}), encoding="utf-8")
    _note(root, "b.md", "two")

    before_bytes = seen.read_bytes()
    before_mtime = seen.stat().st_mtime_ns

    for i in range(10):
        _capture(monkeypatch)
        rc_facts.report_inbox_only(session=f"s{i}")

    assert seen.read_bytes() == before_bytes
    assert seen.stat().st_mtime_ns == before_mtime, "showing acknowledged something"


# ------------------------------------------------------------ _payload_key


def test_payload_key_unchanged_for_a_plain_drop(tmp_path):
    drop = tmp_path / "from-XX-verbatim"
    (drop / "sub").mkdir(parents=True)
    (drop / "a.txt").write_bytes(b"alpha")
    (drop / "sub" / "b.txt").write_bytes(b"beta")
    (drop / "sub" / "c.txt").write_bytes(b"gamma")

    files = sorted((f for f in drop.rglob("*") if f.is_file()), key=lambda f: f.as_posix())
    lines = [
        f"{f.relative_to(drop).as_posix()}\0{hashlib.sha256(f.read_bytes()).hexdigest()}".encode()
        for f in files
    ]
    expected = hashlib.sha256(b"\n".join(lines)).hexdigest()[:12]

    assert rc_facts._payload_key(drop) == f"[3 files, content {expected}]"


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows reparse point")
def test_payload_key_refuses_a_junction_and_moves_the_digest(tmp_path):
    drop = tmp_path / "from-XX-verbatim"
    drop.mkdir()
    (drop / "a.txt").write_bytes(b"alpha")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"not ours")

    baseline = rc_facts._payload_key(drop)

    r = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(drop / "link"), str(outside)],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if r.returncode != 0:
        pytest.skip(f"mklink unavailable: {r.stdout} {r.stderr}")

    after = rc_facts._payload_key(drop)
    assert after != baseline, "a reparse point appeared and the key did not move"
    assert after.startswith("[1 files, "), (
        "the walk descended through the junction instead of refusing it")


def test_payload_key_budget_5000_entries_moves_the_digest(tmp_path):
    big = tmp_path / "big"
    big.mkdir()
    for i in range(5001):
        (big / f"f{i:05d}").write_bytes(b"")
    key = rc_facts._payload_key(big)
    assert "BUDGET-EXCEEDED" in key
    assert "5000+" in key

    small = tmp_path / "small"
    small.mkdir()
    for i in range(4999):
        (small / f"f{i:05d}").write_bytes(b"")
    key2 = rc_facts._payload_key(small)
    assert "BUDGET-EXCEEDED" not in key2
    assert "5000+" not in key2


# --------------------------------------------------------- the CLI control


def test_cli_with_a_session_id_creates_both_files(tmp_path):
    """The control arm for test_cli_does_not_hang_without_stdin.

    That test asserts a stdin-less run writes NEITHER file. On its own that is
    a claim about a writer nobody proved works, so this arm runs the same CLI
    with a validated session id and asserts both files appear.
    """
    (tmp_path / "tools").mkdir()
    copied = tmp_path / "tools" / "rc_facts.py"
    copied.write_bytes((_REPO_ROOT / "tools" / "rc_facts.py").read_bytes())
    inbox = tmp_path / "moon_sync_inbox"
    inbox.mkdir()
    for i in range(12):
        (inbox / f"n{i:02d}.md").write_text(f"body {i}", encoding="utf-8")

    env = dict(os.environ, RC_HOOK_LOG=str(tmp_path / "redirected.jsonl"))
    r = subprocess.run(
        [_PY, str(copied), "--inbox-only"],
        input=json.dumps({"session_id": "t", "hook_event_name": "UserPromptSubmit"}),
        capture_output=True, text=True, timeout=60, env=env,
    )

    assert r.returncode == 0, r.stderr
    assert "12 UNREAD" in r.stdout
    assert (tmp_path / "ops" / "runtime" / "sync_inbox_reported.json").is_file()
    assert (tmp_path / "ops" / "runtime" / "sync_inbox_report.txt").is_file()
