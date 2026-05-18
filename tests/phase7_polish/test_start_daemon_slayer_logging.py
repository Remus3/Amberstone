"""
tests/phase7_polish/test_start_daemon_slayer_logging.py
ROADMAP medium-priority #3 - RC-DaemonSlayer startup traceability.

The RC-DaemonSlayer scheduled task runs as SYSTEM; writes under the project
root can fail there and pythonw.exe has no console, so the old
`_log_startup` (single target + `except OSError: pass`) lost every startup
line on a boot-time failure. These tests pin the resilient contract:
canonical path → ProgramData fallback → stderr echo, never raising.
"""
import importlib.util
import io
import os
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _load_module():
    """Load tools/start_daemon_slayer.py in isolation.

    The module does `os.chdir(_PROJECT_ROOT)` at import time; save/restore
    cwd so importing it for a unit test doesn't pollute sibling tests.
    """
    cwd = os.getcwd()
    try:
        spec = importlib.util.spec_from_file_location(
            "start_daemon_slayer",
            _PROJECT_ROOT / "tools" / "start_daemon_slayer.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(cwd)


SDS = _load_module()


class _CaptureStderr:
    """Context manager swapping sys.stderr for a StringIO."""

    def __enter__(self):
        self._orig = sys.stderr
        self.buf = io.StringIO()
        sys.stderr = self.buf
        return self.buf

    def __exit__(self, *exc):
        sys.stderr = self._orig
        return False


class TestLogStartup(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_sds_log_"))
        self._orig_log = SDS._LOG_FILE
        self._orig_fallback = SDS._FALLBACK_LOG_FILE
        self._orig_write = SDS._write_log_line
        SDS._LOG_FILE = self.tmp / "logs" / "daemon_slayer_startup.log"
        SDS._FALLBACK_LOG_FILE = self.tmp / "pd" / "daemon_slayer_startup.log"

    def tearDown(self):
        SDS._LOG_FILE = self._orig_log
        SDS._FALLBACK_LOG_FILE = self._orig_fallback
        SDS._write_log_line = self._orig_write
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── canonical path ───────────────────────────────────────────────────
    def test_writes_to_canonical_when_writable(self):
        with _CaptureStderr():
            written = SDS._log_startup("hello world")
        self.assertEqual(written, SDS._LOG_FILE)
        content = SDS._LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("hello world", content)
        self.assertFalse(SDS._FALLBACK_LOG_FILE.exists())

    def test_line_format_preserved(self):
        # Exact legacy shape: "YYYY-MM-DD HH:MM:SS  msg\n" (two spaces).
        import re
        with _CaptureStderr():
            SDS._log_startup("boot msg")
        line = SDS._LOG_FILE.read_text(encoding="utf-8")
        self.assertRegex(
            line, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  boot msg\n$")

    # ── fallback path ────────────────────────────────────────────────────
    def test_falls_back_to_programdata_when_canonical_unwritable(self):
        calls: list[Path] = []

        def fake_write(target: Path, line: str) -> bool:
            calls.append(target)
            if target == SDS._LOG_FILE:
                return False  # simulate SYSTEM-context write failure
            return self._orig_write(target, line)

        SDS._write_log_line = fake_write
        with _CaptureStderr():
            written = SDS._log_startup("fallback msg")
        self.assertEqual(written, SDS._FALLBACK_LOG_FILE)
        self.assertEqual(calls, [SDS._LOG_FILE, SDS._FALLBACK_LOG_FILE])
        self.assertIn(
            "fallback msg",
            SDS._FALLBACK_LOG_FILE.read_text(encoding="utf-8"))

    # ── never silent / never raises ──────────────────────────────────────
    def test_returns_none_when_all_targets_fail_and_does_not_raise(self):
        SDS._write_log_line = lambda *a, **k: False
        with _CaptureStderr() as buf:
            written = SDS._log_startup("nowhere")
        self.assertIsNone(written)
        # Even with no file target, stderr still carries the trace.
        self.assertIn("nowhere", buf.getvalue())

    def test_always_echoes_to_stderr_even_on_file_success(self):
        with _CaptureStderr() as buf:
            SDS._log_startup("echo me")
        self.assertIn("echo me", buf.getvalue())

    def test_stderr_write_failure_is_swallowed(self):
        # pythonw.exe (detached SYSTEM task) can leave sys.stderr unusable.
        class Boom:
            def write(self, _):
                raise ValueError("stderr closed")

            def flush(self):
                raise ValueError("stderr closed")

        orig = sys.stderr
        sys.stderr = Boom()
        try:
            written = SDS._log_startup("still logged")
        finally:
            sys.stderr = orig
        # File write still succeeded; the stderr failure did not propagate.
        self.assertEqual(written, SDS._LOG_FILE)
        self.assertIn(
            "still logged", SDS._LOG_FILE.read_text(encoding="utf-8"))


class TestWriteLogLineHelper(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_sds_wll_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_parents_and_appends(self):
        target = self.tmp / "a" / "b" / "log.txt"
        self.assertTrue(SDS._write_log_line(target, "line1\n"))
        self.assertTrue(SDS._write_log_line(target, "line2\n"))
        self.assertEqual(
            target.read_text(encoding="utf-8"), "line1\nline2\n")

    def test_returns_false_on_oserror(self):
        # Put a file where a parent directory needs to be → mkdir raises.
        blocker = self.tmp / "blocker"
        blocker.write_text("x", encoding="utf-8")
        target = blocker / "nested" / "log.txt"
        self.assertFalse(SDS._write_log_line(target, "nope\n"))


if __name__ == "__main__":
    unittest.main()
