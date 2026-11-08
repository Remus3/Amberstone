"""RM-718 (b): tools/cost_health_watchdog.py's log has a size cap.

Filed 2026-10-09 by the repo review (B26-05) and re-probed by the s134
research lane cycle 16: `_log_line` opened `logs/cost_health_watchdog.log` in
plain append mode on every BREACH and never rotated it (5,631,999 B measured
2026-10-26). The watchdog is a ONE-SHOT writer (one process per fire), so it
takes the rotate-at-open shape RM-718 (a) gave tools/replay_roster_pull.py:
recover a crashed rotation's scratch, rotate when at or over the cap, append.
A refused rotation (another process holds the file) keeps appending and says
so in the file; nothing raises into the watchdog.

Every test redirects `_LOG` into tmp_path; none touches the live logs/ dir.
"""
import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import log_retention  # noqa: E402
from core import log_rotation  # noqa: E402
from tests._replace_faults import scoped_fs_fault  # noqa: E402
from tools import cost_health_watchdog as chw  # noqa: E402

_SRC = _ROOT / "tools" / "cost_health_watchdog.py"


def _fill(path: Path, size: int, byte: bytes = b"x") -> Path:
    path.write_bytes(byte * size)
    return path


def _redirect(monkeypatch, log: Path, cap: int = 100) -> None:
    # raising=False: on the unfixed module the cap constant does not exist, so
    # the base fails on BEHAVIOUR (no rotation), not on a missing attribute.
    monkeypatch.setattr(chw, "_LOG", log)
    monkeypatch.setattr(chw, "_LOG_MAX_BYTES", cap, raising=False)


def test_an_oversize_log_is_rotated_before_the_line_is_appended(tmp_path, monkeypatch):
    log = _fill(tmp_path / "cost_health_watchdog.log", 150, b"o")
    _redirect(monkeypatch, log)

    chw._log_line("BREACH {}")

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].endswith(" BREACH {}"), lines
    assert (tmp_path / "cost_health_watchdog.log.1").read_bytes() == b"o" * 150


def test_a_log_exactly_at_the_cap_is_rotated(tmp_path, monkeypatch):
    """At or over, as core/log_rotation.rotate_if_oversize defines it."""
    log = _fill(tmp_path / "cost_health_watchdog.log", 100, b"o")
    _redirect(monkeypatch, log)

    chw._log_line("BREACH {}")

    assert (tmp_path / "cost_health_watchdog.log.1").read_bytes() == b"o" * 100


def test_the_oldest_generation_is_dropped_so_the_bound_holds(tmp_path, monkeypatch):
    log = _fill(tmp_path / "cost_health_watchdog.log", 150, b"a")
    _fill(tmp_path / "cost_health_watchdog.log.1", 150, b"b")
    _fill(tmp_path / "cost_health_watchdog.log.2", 150, b"c")
    _redirect(monkeypatch, log)

    chw._log_line("BREACH {}")

    assert (tmp_path / "cost_health_watchdog.log.1").read_bytes() == b"a" * 150
    assert (tmp_path / "cost_health_watchdog.log.2").read_bytes() == b"b" * 150
    assert not (tmp_path / "cost_health_watchdog.log.3").exists()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["cost_health_watchdog.log", "cost_health_watchdog.log.1",
                     "cost_health_watchdog.log.2"], names


def test_a_log_under_the_cap_is_appended_to_in_place(tmp_path, monkeypatch):
    log = tmp_path / "cost_health_watchdog.log"
    log.write_text("earlier run\n", encoding="utf-8")
    _redirect(monkeypatch, log)

    chw._log_line("BREACH {}")

    text = log.read_text(encoding="utf-8")
    assert text.startswith("earlier run\n") and text.endswith(" BREACH {}\n"), text
    assert not (tmp_path / "cost_health_watchdog.log.1").exists()


def test_a_missing_log_is_created_without_a_rotation(tmp_path, monkeypatch):
    log = tmp_path / "logs" / "cost_health_watchdog.log"
    _redirect(monkeypatch, log)

    chw._log_line("BREACH {}")

    text = log.read_text(encoding="utf-8")
    assert text.count("\n") == 1 and text.endswith(" BREACH {}\n"), text
    assert "log rotation refused" not in text
    assert sorted(p.name for p in log.parent.iterdir()) == ["cost_health_watchdog.log"]


def test_a_refused_rotation_keeps_the_line_notes_it_and_does_not_raise(tmp_path, monkeypatch):
    log = _fill(tmp_path / "cost_health_watchdog.log", 150, b"o")
    _fill(tmp_path / "cost_health_watchdog.log.1", 10, b"p")
    _redirect(monkeypatch, log)

    def _deny(real, src, dst, *a, **kw):
        raise PermissionError("held open by another process")

    with scoped_fs_fault("replace", tmp_path, _deny):
        chw._log_line("BREACH {}")

    text = log.read_text(encoding="utf-8")
    assert text.startswith("o" * 150)
    assert "log rotation refused" in text and text.endswith(" BREACH {}\n"), text
    assert (tmp_path / "cost_health_watchdog.log.1").read_bytes() == b"p" * 10
    assert not (tmp_path / "cost_health_watchdog.log.2").exists()


def test_a_crashed_rotation_is_recovered_even_under_the_cap(tmp_path, monkeypatch):
    log = tmp_path / "cost_health_watchdog.log"
    log.write_text("new run\n", encoding="utf-8")
    (tmp_path / "cost_health_watchdog.log.rotating.4242.deadbeef").write_text(
        "crashed run\n", encoding="utf-8")
    _redirect(monkeypatch, log)

    chw._log_line("BREACH {}")

    assert (tmp_path / "cost_health_watchdog.log.1").read_text(
        encoding="utf-8") == "crashed run\n"
    assert not list(tmp_path.glob("cost_health_watchdog.log.rotating*"))


def test_an_unwritable_log_location_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("a file where the log dir should be\n", encoding="utf-8")
    _redirect(monkeypatch, blocker / "cost_health_watchdog.log")

    chw._log_line("BREACH {}")  # must not raise

    assert blocker.read_text(encoding="utf-8") == "a file where the log dir should be\n"


def test_the_cap_is_the_shared_default_and_valid():
    assert chw._LOG_MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert chw._LOG_BACKUPS == log_rotation.DEFAULT_BACKUP_COUNT
    log_rotation._validate(chw._LOG_MAX_BYTES, chw._LOG_BACKUPS)


def test_only_the_rotating_helper_opens_the_log():
    """No other function may append to `_LOG` directly again (the unbounded
    append this row removes)."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "open"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "_LOG"
                    and fn.name != "_log_line"):
                offenders.append((fn.name, node.lineno))
    assert offenders == [], offenders


def test_three_one_shot_and_rotating_writers_fit_inside_half_the_retention_cap():
    """RM-718 (a) budgeted its two rotated writers to half of log_retention's
    cap; the watchdog joins that budget, so the three together still leave
    half of logs/ for RC's dated daily logs."""
    import tools.lcu_agent as agent
    from tools import replay_roster_pull as rpp

    worst = ((1 + rpp._LOG_SINK_BACKUPS) * rpp._LOG_SINK_MAX_BYTES
             + (1 + agent._FILE_HANDLER.backupCount) * agent._FILE_HANDLER.maxBytes
             + (1 + chw._LOG_BACKUPS) * chw._LOG_MAX_BYTES)
    cap = log_retention._DEFAULT_MAX_TOTAL_MB * 1024 * 1024
    assert worst <= cap // 2, (worst, cap)
