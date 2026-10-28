# arch: RM-1022 (1) - the :8889 /monitor file is anchored to the repo root, never the CWD
"""RM-1022 part (1) - ``vision_server/_http.py`` read and wrote the
``/monitor`` page relative to the process working directory.

``do_PUT`` wrote every authenticated PUT of ``moon_monitor.html`` (or
``monitor.html``) into ``Path.cwd() / "moon_monitor.html"`` as well as into
``SYNC_DIR``, and ``do_GET /monitor`` probed ``Path.cwd()`` as one of its
candidates. Live, the vision process is spawned with ``cwd=<repo>``
(``dashboard`` -> ``spawn_vision``), so the CWD file WAS the repo-root file -
the same path ``MONITOR_HTML_PATH`` already names. Anywhere else (a test, a
hand-started server) the PUT planted a file in whatever directory the process
stood in, and the GET served one from there. RM-828 (c) anchored ``SYNC_DIR``
the same way; this is its filed residue.

The fix writes the discoverability copy to ``MONITOR_HTML_PATH`` (the repo
root, the first ``/monitor`` candidate) and drops the CWD candidate, so the
live behaviour is unchanged and no path depends on the CWD any more.
"""
from __future__ import annotations

import ast
import contextlib
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from unittest import mock

from vision_server import _http
from vision_server._config import AUTH_HEADER, AUTH_TOKEN

REPO = Path(__file__).resolve().parent.parent
_PAYLOAD = b"<html><body>s144q11 monitor payload</body></html>"


class _Server:
    """A real ``_http.Handler`` on an ephemeral loopback port."""

    def __enter__(self) -> "_Server":
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _http.Handler)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)

    def call(self, method: str, path: str,
             payload: bytes | None = None) -> tuple[int, bytes]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=payload, method=method,
            headers={AUTH_HEADER: AUTH_TOKEN},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class MonitorFileIsNotCwdRelativeTests(unittest.TestCase):
    """The PUT write and the /monitor read never resolve against the CWD."""

    def _isolate(self) -> tuple[Path, Path, Path]:
        """Separate the repo root, the CWD and the inbox into three dirs.

        Returns ``(root, cwd, inbox)``. ``MONITOR_HTML_PATH`` and the module
        ``__file__`` point under ``root``, ``Path.home()`` and ``SYNC_DIR``
        under scratch dirs, and the process CWD is ``cwd`` - so a file that
        lands in or is served from ``cwd`` can only have got there through
        the CWD.
        """
        tmp = Path(tempfile.mkdtemp(prefix="rc_s144q11_")).resolve()
        root, cwd, inbox, home = (tmp / "root", tmp / "cwd",
                                  tmp / "inbox", tmp / "home")
        for d in (root / "pkg", cwd, inbox, home):
            d.mkdir(parents=True)
        # LIFO: unpatch, then leave the dir, then delete it. Windows refuses
        # to remove the process CWD, so the chdir-back runs before the rmtree.
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(cwd)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            mock.patch.object(_http, "MONITOR_HTML_PATH", root / "moon_monitor.html"))
        stack.enter_context(
            mock.patch.object(_http, "__file__", str(root / "pkg" / "_http.py")))
        stack.enter_context(
            mock.patch.object(Path, "home", classmethod(lambda cls: home)))
        stack.enter_context(mock.patch.object(_http, "SYNC_DIR", inbox))
        return root, cwd, inbox

    def test_put_writes_the_monitor_copy_beside_the_server_not_into_the_cwd(self) -> None:
        root, cwd, inbox = self._isolate()
        for name in ("moon_monitor.html", "monitor.html"):
            with self.subTest(name=name):
                (root / "moon_monitor.html").unlink(missing_ok=True)
                with _Server() as s:
                    status, _ = s.call("PUT", f"/sync/put/{name}", _PAYLOAD)
                self.assertEqual(status, 200)
                self.assertFalse(
                    (cwd / "moon_monitor.html").exists(),
                    "the PUT wrote moon_monitor.html into the process CWD")
                self.assertEqual(
                    (root / "moon_monitor.html").read_bytes(), _PAYLOAD,
                    "the PUT did not write the repo-root MONITOR_HTML_PATH copy")
                self.assertEqual((inbox / name).read_bytes(), _PAYLOAD,
                                 "the PUT no longer delivers into SYNC_DIR")

    def test_monitor_get_does_not_serve_a_file_from_the_cwd(self) -> None:
        _root, cwd, _inbox = self._isolate()
        (cwd / "moon_monitor.html").write_bytes(_PAYLOAD)
        with _Server() as s:
            status, body = s.call("GET", "/monitor")
        self.assertEqual(status, 404,
                         "/monitor served a moon_monitor.html found only in the CWD")
        self.assertNotIn(_PAYLOAD, body)

    def test_monitor_get_serves_the_put_copy(self) -> None:
        """The discoverability the CWD write existed for still holds."""
        self._isolate()
        with _Server() as s:
            put_status, _ = s.call("PUT", "/sync/put/moon_monitor.html", _PAYLOAD)
            self.assertEqual(put_status, 200)
            status, body = s.call("GET", "/monitor")
        self.assertEqual(status, 200)
        self.assertEqual(body, _PAYLOAD)


def _is_rooted(text: str) -> bool:
    """Drive-rooted or slash-rooted, on any host (Windows calls ``/x`` relative)."""
    return text.startswith(("/", "\\")) or PureWindowsPath(text).is_absolute()


def _cwd_relative_sites(src: str) -> list[str]:
    """``Path.cwd()`` / ``os.getcwd()`` calls and relative ``Path("x")`` literals."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr in ("cwd", "getcwd")
                and isinstance(f.value, ast.Name) and f.value.id in ("Path", "os")):
            hits.append(f"{node.lineno}: {ast.unparse(node)}")
        elif (isinstance(f, ast.Name) and f.id == "Path" and node.args
              and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and not _is_rooted(node.args[0].value)):
            hits.append(f"{node.lineno}: {ast.unparse(node)}")
    return hits


class NoCwdRelativePathInVisionServerTests(unittest.TestCase):
    """Sibling sweep, pinned: no vision_server module resolves against the CWD."""

    _FILES = sorted((REPO / "vision_server").glob("*.py")) + [REPO / "moon_vision_server.py"]

    def test_the_sweep_sees_the_package(self) -> None:
        self.assertIn(REPO / "vision_server" / "_http.py", self._FILES)
        self.assertTrue(all(p.is_file() for p in self._FILES))

    def test_the_predicate_matches_each_shape(self) -> None:
        src = ("from pathlib import Path\nimport os\n"
               "a = Path.cwd() / 'x'\nb = os.getcwd()\nc = Path('moon_sync_inbox')\n"
               "d = Path('/abs/ok')\ne = Path(__file__).parent\n")
        self.assertEqual(len(_cwd_relative_sites(src)), 3)

    def test_no_vision_server_module_resolves_a_path_against_the_cwd(self) -> None:
        found = {
            str(p.relative_to(REPO)): hits
            for p in self._FILES
            if (hits := _cwd_relative_sites(p.read_text(encoding="utf-8")))
        }
        self.assertEqual(found, {},
                         "CWD-relative path in the vision server; anchor it to "
                         "Path(__file__) as _config._SYNC_DIR does")


if __name__ == "__main__":
    unittest.main()
