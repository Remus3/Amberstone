"""RM-718 (a): the two unrotated writers that held 87 MB of a 100 MiB logs/ dir.

Measured 2026-10-24 on the main checkout: top-level `logs/*.log*` = 94.3 MiB
against `core/log_retention.py`'s 100 MiB cap (`_DEFAULT_MAX_TOTAL_MB`).
`logs/replay_roster.log` was 59.5 MB (tools/replay_roster_pull.py opened its
`--log-file` in plain append mode, ~40 KB per hourly run, ~1 MB/day) and
`logs/lcu_agent.log` 27.3 MB (tools/lcu_agent.py built a plain FileHandler,
~0.34 MB/day since 2026-08-05). Neither ever rotated, so the dir would have
crossed the cap in about a week and the size pass would have deleted RC's dated
daily logs first while the two offenders kept growing.

Every test here works in tmp_path; none touches the live logs/ dir.
"""
import ast
import logging
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import log_retention  # noqa: E402
from core import log_rotation  # noqa: E402
from tests._replace_faults import scoped_fs_fault  # noqa: E402


def _fill(path: Path, size: int, byte: bytes = b"x") -> Path:
    path.write_bytes(byte * size)
    return path


# -- core/log_rotation.rotate_if_oversize ----------------------------------

def test_under_cap_is_left_alone(tmp_path):
    log = _fill(tmp_path / "w.log", 99)
    assert log_rotation.rotate_if_oversize(log, max_bytes=100, backup_count=2) is False
    assert log.read_bytes() == b"x" * 99
    assert not (tmp_path / "w.log.1").exists()


def test_missing_file_is_a_noop(tmp_path):
    assert log_rotation.rotate_if_oversize(
        tmp_path / "absent.log", max_bytes=100, backup_count=2) is False


def test_oversize_file_shifts_into_numbered_backups(tmp_path):
    log = _fill(tmp_path / "w.log", 100, b"c")
    _fill(tmp_path / "w.log.1", 10, b"b")

    assert log_rotation.rotate_if_oversize(log, max_bytes=100, backup_count=2) is True

    assert not log.exists(), "the base file must be free for a fresh open"
    assert (tmp_path / "w.log.1").read_bytes() == b"c" * 100
    assert (tmp_path / "w.log.2").read_bytes() == b"b" * 10


def test_backups_beyond_the_count_are_dropped(tmp_path):
    """The bound is (1 + backup_count) files; a third generation must not
    survive a rotation with backup_count=2."""
    log = _fill(tmp_path / "w.log", 100, b"c")
    _fill(tmp_path / "w.log.1", 10, b"b")
    _fill(tmp_path / "w.log.2", 10, b"a")

    assert log_rotation.rotate_if_oversize(log, max_bytes=100, backup_count=2) is True

    assert (tmp_path / "w.log.1").read_bytes() == b"c" * 100
    assert (tmp_path / "w.log.2").read_bytes() == b"b" * 10
    assert not (tmp_path / "w.log.3").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["w.log.1", "w.log.2"]


def test_a_refused_rename_keeps_the_base_file_and_does_not_raise(tmp_path):
    """Windows refuses to rename a file another process holds open. The writer
    must keep appending to the oversize file rather than crash or lose it."""
    log = _fill(tmp_path / "w.log", 100)

    def _deny(real, src, dst, *a, **kw):
        raise PermissionError("held open by another process")

    with scoped_fs_fault("replace", tmp_path, _deny, expect_fire=False) as rep, \
            scoped_fs_fault("rename", tmp_path, _deny, expect_fire=False) as ren:
        rotated = log_rotation.rotate_if_oversize(log, max_bytes=100, backup_count=2)

    assert rep.attempts + ren.attempts >= 1, "no rename was attempted"

    assert rotated is False
    assert log.read_bytes() == b"x" * 100


_WIN_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="only Windows refuses to rename a file another handle holds open")


@_WIN_ONLY
def test_a_refused_rotation_leaves_every_backup_intact(tmp_path):
    """Verifier repro (2): the old order shifted `.1 -> .2` (dropping the old
    `.2`) BEFORE the base rename that a holder refuses, so one refused attempt
    destroyed a generation. A refused rotation must change nothing."""
    log = _fill(tmp_path / "w.log", 100, b"c")
    _fill(tmp_path / "w.log.1", 10, b"b")
    _fill(tmp_path / "w.log.2", 10, b"a")

    with open(log, "ab"):  # a second handle holds the base file open
        rotated = log_rotation.rotate(log, backup_count=2)

    assert rotated is False
    assert log.read_bytes() == b"c" * 100
    assert (tmp_path / "w.log.1").read_bytes() == b"b" * 10
    assert (tmp_path / "w.log.2").read_bytes() == b"a" * 10
    assert sorted(p.name for p in tmp_path.iterdir()) == ["w.log", "w.log.1", "w.log.2"]


def test_a_rotation_refused_mid_shift_is_rolled_back(tmp_path):
    """A backup that refuses its shift (a reader holding `.1`) must not cost
    the oldest generation either: every applied rename is undone."""
    log = _fill(tmp_path / "w.log", 100, b"c")
    _fill(tmp_path / "w.log.1", 10, b"b")
    _fill(tmp_path / "w.log.2", 10, b"a")

    def _deny_shift_of_backup_1(real, src, dst, *a, **kw):
        if Path(src).name == "w.log.1":
            raise PermissionError("held open by a reader")
        return real(src, dst, *a, **kw)

    with scoped_fs_fault("replace", tmp_path, _deny_shift_of_backup_1):
        rotated = log_rotation.rotate(log, backup_count=2)

    assert rotated is False
    assert log.read_bytes() == b"c" * 100
    assert (tmp_path / "w.log.1").read_bytes() == b"b" * 10
    assert (tmp_path / "w.log.2").read_bytes() == b"a" * 10
    assert sorted(p.name for p in tmp_path.iterdir()) == ["w.log", "w.log.1", "w.log.2"]


# -- crash mid-rotation: orphaned scratch files are recovered, never overwritten

def _contents(d: Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


@pytest.mark.parametrize("tag", ["", ".4242.deadbeef"])
def test_crash_after_staging_loses_nothing(tmp_path, tag):
    """Verifier probe C: the process died right after staging the base aside,
    the writer restarted and wrote a new base, then the next rotation ran. The
    old shared `.rotating` name was overwritten by that rotation and BASE was
    lost. Both the legacy bare name and the per-writer form must survive."""
    log = tmp_path / "a.log"
    log.write_bytes(b"NEWBASE")
    (tmp_path / "a.log.1").write_bytes(b"ONE")
    (tmp_path / "a.log.2").write_bytes(b"TWO")
    (tmp_path / f"a.log.rotating{tag}").write_bytes(b"BASE")

    assert log_rotation.rotate(log, backup_count=2) is True

    after = _contents(tmp_path)
    assert sorted(after.values()) == [b"BASE", b"NEWBASE", b"ONE", b"TWO"], after
    assert after["a.log.1"] == b"NEWBASE" and after["a.log.2"] == b"ONE"
    assert not [n for n in after if ".rotating" in n or ".dropping" in n], after


def test_crash_mid_shift_loses_nothing(tmp_path):
    """Verifier probe D: died after staging, after moving the oldest to the drop
    name, and after shifting `.1 -> .2`. The old code then lost BASE and the
    old `.1` (ONE), leaving only NEWBASE. Every generation must survive."""
    log = tmp_path / "a.log"
    log.write_bytes(b"NEWBASE")
    (tmp_path / "a.log.2").write_bytes(b"ONE")
    (tmp_path / "a.log.dropping.4242.deadbeef").write_bytes(b"TWO")
    (tmp_path / "a.log.rotating.4242.deadbeef").write_bytes(b"BASE")

    assert log_rotation.rotate(log, backup_count=2) is True

    after = _contents(tmp_path)
    assert sorted(after.values()) == [b"BASE", b"NEWBASE", b"ONE", b"TWO"], after
    # The interrupted rotation is completed (BASE back in the chain), then the
    # new one runs on top of it.
    assert after["a.log.1"] == b"NEWBASE" and after["a.log.2"] == b"BASE"
    assert not [n for n in after if ".rotating" in n or ".dropping" in n], after


def test_handler_open_recovers_an_orphan(tmp_path):
    log = tmp_path / "agent.log"
    log.write_bytes(b"NEWBASE\n")
    (tmp_path / "agent.log.rotating.4242.deadbeef").write_bytes(b"BASE\n")

    handler = log_rotation.rotating_file_handler(log, max_bytes=10_000, backup_count=2)
    handler.close()

    after = _contents(tmp_path)
    assert after.get("agent.log.1") == b"BASE\n", after
    assert after["agent.log"] == b"NEWBASE\n"


def test_recovery_never_overwrites_an_existing_file(tmp_path, monkeypatch):
    """When the preserved name is somehow taken, the orphan stays where it is
    (under its own unique name, which no rotation reuses)."""
    log = tmp_path / "a.log"
    log.write_bytes(b"NEWBASE")
    (tmp_path / "a.log.1").write_bytes(b"ONE")
    orphan = tmp_path / "a.log.rotating.4242.deadbeef"
    orphan.write_bytes(b"BASE")
    monkeypatch.setattr(log_rotation, "_token", lambda: "fixed")
    taken = tmp_path / log_rotation._recovered_name(log, "rotating").name
    taken.write_bytes(b"SQUATTER")

    log_rotation.recover_orphans(log)

    assert orphan.read_bytes() == b"BASE"
    assert taken.read_bytes() == b"SQUATTER"


def test_scratch_names_are_per_writer(tmp_path):
    """Two writers must never share a scratch name: each carries the pid and a
    fresh random token, unlike the old shared `.rotating` / `.dropping`."""
    seen: list = []

    def _spy(real, src, dst, *a, **kw):
        seen.append(Path(dst).name)
        return real(src, dst, *a, **kw)

    log = tmp_path / "w.log"
    with scoped_fs_fault("replace", tmp_path, _spy):
        for _ in range(2):
            _fill(log, 100)
            _fill(tmp_path / "w.log.1", 10)
            _fill(tmp_path / "w.log.2", 10)
            assert log_rotation.rotate(log, backup_count=2) is True

    staged = [n for n in seen if ".rotating." in n]
    dropped = [n for n in seen if ".dropping." in n]
    assert len(staged) == 2 and len(dropped) == 2, seen
    assert staged[0] != staged[1] and dropped[0] != dropped[1]
    assert all(f".{os.getpid()}." in n for n in staged + dropped), seen


def test_rotation_never_logs(tmp_path, caplog):
    """A refusal must not be reported through logging: when the handler that
    is rotating sits on the root logger, that record re-enters it."""
    log = _fill(tmp_path / "w.log", 100)

    def _deny(real, src, dst, *a, **kw):
        raise PermissionError("held open by another process")

    with caplog.at_level(logging.DEBUG), \
            scoped_fs_fault("replace", tmp_path, _deny, expect_fire=False), \
            scoped_fs_fault("rename", tmp_path, _deny, expect_fire=False):
        log_rotation.rotate(log, backup_count=2)

    assert [r for r in caplog.records if r.name.startswith("rc.log_rotation")] == []


@pytest.mark.parametrize("bad", [0, -1])
def test_nonpositive_max_bytes_is_rejected(tmp_path, bad):
    log = _fill(tmp_path / "w.log", 10)
    with pytest.raises(ValueError):
        log_rotation.rotate_if_oversize(log, max_bytes=bad, backup_count=2)
    assert log.exists()


@pytest.mark.parametrize("bad", [0, -1])
def test_backup_count_below_one_is_rejected(tmp_path, bad):
    """backup_count=0 would turn a rotation into an unrecoverable truncation."""
    log = _fill(tmp_path / "w.log", 10)
    with pytest.raises(ValueError):
        log_rotation.rotate_if_oversize(log, max_bytes=5, backup_count=bad)
    assert log.exists()


# -- core/log_rotation.SafeRotatingFileHandler -----------------------------

def _emit_lines(handler, n: int) -> None:
    """Feed records straight to the handler: no logger state is touched."""
    for i in range(n):
        handler.handle(logging.LogRecord(
            "rm718a", logging.INFO, __file__, 0, "line %03d %s",
            (i, "y" * 20), None))


def test_handler_rolls_over_at_the_size_cap(tmp_path):
    path = tmp_path / "agent.log"
    handler = log_rotation.rotating_file_handler(path, max_bytes=200, backup_count=2)
    try:
        _emit_lines(handler, 40)
    finally:
        handler.close()

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["agent.log", "agent.log.1", "agent.log.2"], names
    for p in tmp_path.iterdir():
        assert p.stat().st_size <= 200
    assert "line 039" in path.read_text(encoding="utf-8")


def test_handler_keeps_records_when_the_rollover_is_refused(tmp_path):
    """The stdlib RotatingFileHandler loses the record when the rename raises,
    and leaves its stream None so every later record retries and is lost too.
    A refused rollover must degrade to appending, never to silence."""
    path = tmp_path / "agent.log"
    handler = log_rotation.rotating_file_handler(path, max_bytes=200, backup_count=2)

    def _deny(real, src, dst, *a, **kw):
        raise PermissionError("held open by another process")

    # Deny BOTH rename primitives: the stdlib handler renames with os.rename,
    # this module with os.replace. Denying only one would let a regression to
    # the stdlib rollover pass by never hitting the fault.
    try:
        with scoped_fs_fault("replace", tmp_path, _deny, expect_fire=False) as rep, \
                scoped_fs_fault("rename", tmp_path, _deny, expect_fire=False) as ren:
            _emit_lines(handler, 40)
    finally:
        handler.close()

    assert rep.attempts + ren.attempts >= 1, "no rollover was attempted"
    text = path.read_text(encoding="utf-8")
    missing = [i for i in range(40) if f"line {i:03d}" not in text]
    assert missing == [], f"records lost on a refused rollover: {missing}"
    assert not (tmp_path / "agent.log.1").exists()


@_WIN_ONLY
def test_root_logger_handler_with_a_held_file_does_not_recurse(tmp_path, capsys):
    """Verifier repro (1), the lcu_agent wiring: basicConfig puts the handler on
    the ROOT logger. The old rotate() logged its refusal before the retry
    deadline was set; that record propagated to root, re-entered this handler,
    retried the refused rollover, and recursed - measured 121 refusal lines,
    3 RecursionErrors and dropped records, recurring once a minute.

    Real wiring, real refusal: a second handle holds the file open, so the
    rename fails the way it does when another process holds the log."""
    path = tmp_path / "agent.log"
    path.write_text("x" * 300 + "\n", encoding="utf-8")  # already over cap
    handler = log_rotation.rotating_file_handler(path, max_bytes=200, backup_count=2)
    handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    lg = logging.getLogger("lcu_agent")
    holder = open(path, "a", encoding="utf-8")
    root.addHandler(handler)
    try:
        for i in range(5):
            lg.warning("REC %03d", i)
    finally:
        root.removeHandler(handler)
        handler.close()
        holder.close()

    err = capsys.readouterr().err
    text = path.read_text(encoding="utf-8")
    assert "RecursionError" not in err and "Logging error" not in err, err[-2000:]
    assert [i for i in range(5) if f"REC {i:03d}" not in text] == []
    assert text.count("log rotation refused") == 1, text.count("log rotation refused")
    assert handler.refused_rollovers == 1
    assert not list(tmp_path.glob("agent.log.*"))


def test_a_refused_streak_is_noted_once_and_reset_by_a_success(tmp_path, monkeypatch):
    """The refusal note goes straight into the file (pythonw has no stderr),
    once per streak of refusals, never once per retry."""
    path = tmp_path / "agent.log"
    handler = log_rotation.rotating_file_handler(path, max_bytes=200, backup_count=2)
    monkeypatch.setattr(log_rotation, "_RETRY_AFTER_S", 0.0)

    def _deny(real, src, dst, *a, **kw):
        raise PermissionError("held open by another process")

    try:
        with scoped_fs_fault("replace", tmp_path, _deny):
            _emit_lines(handler, 30)
        refused = handler.refused_rollovers
        notes_while_refused = path.read_text(encoding="utf-8").count("log rotation refused")
        _emit_lines(handler, 30)
    finally:
        handler.close()

    assert refused >= 2, "the retry never re-attempted"
    assert notes_while_refused == 1
    assert handler.refused_rollovers == 0, "a successful rollover must end the streak"
    assert (tmp_path / "agent.log.1").exists()


def test_rotating_file_handler_validates_its_bounds(tmp_path):
    with pytest.raises(ValueError):
        log_rotation.rotating_file_handler(tmp_path / "a.log", max_bytes=0)
    with pytest.raises(ValueError):
        log_rotation.rotating_file_handler(tmp_path / "a.log", backup_count=0)


# -- the two writers -------------------------------------------------------

def test_replay_roster_sink_rotates_an_oversize_log_before_opening(tmp_path, monkeypatch):
    from tools import replay_roster_pull as rpp

    monkeypatch.setattr(rpp, "_LOG_SINK_MAX_BYTES", 100)
    sink = _fill(tmp_path / "replay_roster.log", 150, b"o")

    stream = rpp._open_log_sink(sink)
    try:
        stream.write("fresh run\n")
    finally:
        stream.close()

    assert sink.read_text(encoding="utf-8") == "fresh run\n"
    assert (tmp_path / "replay_roster.log.1").read_bytes() == b"o" * 150


def test_replay_roster_sink_notes_a_refused_rotation_and_keeps_the_log(tmp_path, monkeypatch):
    from tools import replay_roster_pull as rpp

    monkeypatch.setattr(rpp, "_LOG_SINK_MAX_BYTES", 100)
    sink = _fill(tmp_path / "replay_roster.log", 150, b"o")
    _fill(tmp_path / "replay_roster.log.1", 10, b"p")

    def _deny(real, src, dst, *a, **kw):
        raise PermissionError("held open by another process")

    with scoped_fs_fault("replace", tmp_path, _deny):
        stream = rpp._open_log_sink(sink)
    try:
        stream.write("run\n")
    finally:
        stream.close()

    text = sink.read_text(encoding="utf-8")
    assert text.startswith("o" * 150)
    assert "log rotation refused" in text and text.endswith("run\n")
    assert (tmp_path / "replay_roster.log.1").read_bytes() == b"p" * 10
    assert not (tmp_path / "replay_roster.log.2").exists()


def test_replay_roster_sink_recovers_an_orphan_even_under_the_cap(tmp_path):
    from tools import replay_roster_pull as rpp

    sink = tmp_path / "replay_roster.log"
    sink.write_text("new run\n", encoding="utf-8")
    (tmp_path / "replay_roster.log.rotating.4242.deadbeef").write_text(
        "crashed run\n", encoding="utf-8")

    rpp._open_log_sink(sink).close()

    assert (tmp_path / "replay_roster.log.1").read_text(encoding="utf-8") == "crashed run\n"
    assert not list(tmp_path.glob("replay_roster.log.rotating*"))


def test_replay_roster_sink_appends_under_the_cap(tmp_path):
    from tools import replay_roster_pull as rpp

    sink = tmp_path / "nested" / "replay_roster.log"
    sink.parent.mkdir()
    sink.write_text("earlier run\n", encoding="utf-8")

    stream = rpp._open_log_sink(sink)
    try:
        stream.write("next run\n")
    finally:
        stream.close()

    assert sink.read_text(encoding="utf-8") == "earlier run\nnext run\n"
    assert not (sink.parent / "replay_roster.log.1").exists()


def test_replay_roster_main_opens_the_sink_through_the_rotating_helper():
    """main() must not open --log-file directly again (the unbounded append
    this row exists to remove)."""
    src = (_ROOT / "tools" / "replay_roster_pull.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    opens = [n for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "open"]
    calls = {n.func.id for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert opens == [], "main() opens a file directly; use _open_log_sink"
    assert "_open_log_sink" in calls


def test_lcu_agent_builds_no_unbounded_file_handler():
    src = (_ROOT / "tools" / "lcu_agent.py").read_text(encoding="utf-8")
    def _label(call):
        f = call.func
        return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")

    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)]
    plain = [n.lineno for n in calls if _label(n) == "FileHandler"]
    assert plain == [], f"plain FileHandler at line(s) {plain}"
    assert any(_label(n) == "SafeRotatingFileHandler" for n in calls)


def test_lcu_agent_file_handler_is_size_bounded():
    import tools.lcu_agent as agent

    h = agent._FILE_HANDLER
    assert isinstance(h, log_rotation.SafeRotatingFileHandler)
    assert 0 < h.maxBytes <= log_rotation.DEFAULT_MAX_BYTES
    assert h.backupCount >= 1


def test_rotated_writers_fit_well_inside_the_retention_cap():
    """Worst case on disk for the two rotated writers, (1 + backups) files of
    max_bytes each, must leave at least half of log_retention's cap for RC's
    dated daily logs and everything else."""
    from tools import replay_roster_pull as rpp
    import tools.lcu_agent as agent

    worst = ((1 + rpp._LOG_SINK_BACKUPS) * rpp._LOG_SINK_MAX_BYTES
             + (1 + agent._FILE_HANDLER.backupCount) * agent._FILE_HANDLER.maxBytes)
    cap = log_retention._DEFAULT_MAX_TOTAL_MB * 1024 * 1024
    assert worst <= cap // 2, (worst, cap)


def test_no_live_log_was_touched_by_this_module():
    """Sanity anchor: the conftest redirect keeps the lcu_agent handler off the
    operator's live logs/ dir."""
    import tools.lcu_agent as agent

    live = (_ROOT / "logs").resolve()
    base = Path(agent._FILE_HANDLER.baseFilename).resolve()
    assert live not in base.parents, base
    assert os.path.basename(base) == "lcu_agent.log"
