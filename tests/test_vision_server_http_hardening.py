"""Lane 8 deep audit of ``vision_server/_http.py`` - the :8889 trust boundary.

The handler is the widest untrusted-input surface the vision pipeline owns.
At the time of this audit ``vision_server/__init__.py`` bound it on
``0.0.0.0``, so every route here was reachable from the LAN and the tailnet,
gated only by the ``X-RC-Token`` header - the amplifier that made the
traversal below a live disclosure rather than a local one. RM-150 has since
narrowed the bind to loopback (``_bind_host``), which shrinks the blast radius
but does NOT close any of the defects pinned in this file: the containment,
body-gate and auth checks are the fix, and the bind is defense in depth.

Measured 2026-08-03 against the real ``Handler`` on an ephemeral port:

    GET /sync/get/../probe_secret.txt          -> 200, file body
    GET /sync/get/C:/some/space-free/path.txt  -> 200, file body

``do_GET`` built the served path as ``SYNC_DIR / self.path[10:]`` with no
containment. Two distinct escapes, both proven live:

1. ``..`` segments walk out of the inbox. This is the form that reaches
   ``API-Key-Claude.txt`` - verified independently, 200 plus the file body.
2. An ABSOLUTE path replaces the base entirely - ``pathlib`` semantics, so
   ``Path("moon_sync_inbox") / "C:/x/y.txt"`` is just ``C:/x/y.txt``. A
   ``".."`` filter alone would not have caught this one.

Escape 2 needs a SPACE-FREE target: the handler never ``unquote``s, and
``BaseHTTPRequestHandler`` splits the request line on whitespace, so a literal
space is a 400 and ``%20`` stays percent-encoded and 404s. That limits which
absolute paths it reaches; it does not make it safe, and escape 1 is
unaffected.

``do_PUT`` on the same file already does the right thing (``Path(...).name``
strips every directory component), which is what made the GET side easy to
miss - the sibling method looks careful.

The fix copies the precedent at ``dashboard/routes_static.py:64-67``: resolve
the root, resolve the candidate, assert ``relative_to``. That comment records
that a prefix check plus a ``".."`` filter was deliberately REPLACED by this,
because both are bypassable.

Also pinned here, same audit pass:
- POST with a NEGATIVE Content-Length. It passed the oversize check and
  reached ``rfile.read(-1)``, which reads to EOF - a client that never closes
  wedges the handler thread for as long as it likes.
- PUT parsed Content-Length OUTSIDE its ``try``, so a malformed value raised
  through the handler and the client got a connection reset instead of a 400.
- PUT had no size cap at all, while POST caps at 10 MiB.
"""
from __future__ import annotations

import shutil
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from vision_server._config import AUTH_HEADER, AUTH_TOKEN, SYNC_DIR
from vision_server._http import Handler

SECRET = "SUPERSECRET-not-a-real-key"


class _Server:
    """Real Handler on an ephemeral loopback port - no mocks in the path."""

    def __enter__(self) -> "_Server":
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)

    def get(self, path: str) -> tuple[int, bytes]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            headers={AUTH_HEADER: AUTH_TOKEN},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def raw(self, request_bytes: bytes, timeout: float = 6.0) -> bytes:
        """Send a hand-built request so malformed headers survive the client."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        try:
            s.sendall(request_bytes)
            s.settimeout(timeout)
            return s.recv(256)
        except socket.timeout:
            return b""
        finally:
            s.close()


class SyncGetPathTraversal(unittest.TestCase):
    """GET /sync/get/ must never serve a file outside the sync inbox."""

    def setUp(self) -> None:
        self.secret = (SYNC_DIR.resolve().parent / "rc_audit_probe_secret.txt")
        self.secret.write_text(SECRET, encoding="utf-8")
        self.addCleanup(lambda: self.secret.unlink(missing_ok=True))

    def test_absolute_path_injection_is_refused(self) -> None:
        # The probe target CANNOT live beside SYNC_DIR: the repo root is
        # `C:\Riot Commander`, and a literal space in the request line is
        # rejected by http.client before it is ever sent (and would be a 400
        # server-side anyway - see the module docstring). The lane worktree
        # path happened to be space-free, which is why this passed there and
        # only failed once merged. A temp dir is space-free on Windows and
        # POSIX alike; assert it rather than skipping, so a machine that
        # breaks the assumption fails loudly instead of quietly passing.
        probe_dir = Path(tempfile.mkdtemp(prefix="rc_audit_"))
        self.addCleanup(lambda: shutil.rmtree(probe_dir, ignore_errors=True))
        self.assertNotIn(" ", str(probe_dir),
                         "probe path must be space-free to reach the handler")
        probe = probe_dir / "rc_audit_probe_secret.txt"
        probe.write_text(SECRET, encoding="utf-8")
        with _Server() as srv:
            code, body = srv.get("/sync/get/" + str(probe).replace("\\", "/"))
        self.assertNotIn(SECRET.encode(), body,
                         "absolute-path injection served a file outside SYNC_DIR")
        self.assertEqual(code, 404)

    def test_dotdot_traversal_is_refused(self) -> None:
        with _Server() as srv:
            code, body = srv.get("/sync/get/../rc_audit_probe_secret.txt")
        self.assertNotIn(SECRET.encode(), body,
                         "'..' traversal served a file outside SYNC_DIR")
        self.assertEqual(code, 404)

    def test_encoded_dotdot_traversal_is_refused(self) -> None:
        """Percent-encoded separators must not reconstitute a traversal."""
        with _Server() as srv:
            code, body = srv.get("/sync/get/..%2Frc_audit_probe_secret.txt")
        self.assertNotIn(SECRET.encode(), body)
        self.assertEqual(code, 404)

    def test_a_file_inside_the_inbox_is_still_served(self) -> None:
        """Positive control - the fix must not break the feature."""
        inside = SYNC_DIR / "rc_audit_probe_inside.txt"
        inside.write_text("inbox-payload", encoding="utf-8")
        self.addCleanup(lambda: inside.unlink(missing_ok=True))
        with _Server() as srv:
            code, body = srv.get("/sync/get/rc_audit_probe_inside.txt")
        self.assertEqual(code, 200)
        self.assertEqual(body, b"inbox-payload")

    def test_missing_file_inside_the_inbox_is_404(self) -> None:
        with _Server() as srv:
            code, _ = srv.get("/sync/get/rc_audit_probe_absent.txt")
        self.assertEqual(code, 404)


class ContentLengthHandling(unittest.TestCase):
    """A Content-Length is attacker-controlled input, on POST and on PUT."""

    def test_negative_content_length_does_not_wedge_the_handler(self) -> None:
        with _Server() as srv:
            resp = srv.raw(
                b"POST /upload-frame HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                + AUTH_HEADER.encode() + b": " + AUTH_TOKEN.encode() + b"\r\n"
                b"Content-Length: -1\r\n\r\n"
            )
        self.assertTrue(resp, "negative Content-Length hung the handler thread "
                              "(rfile.read(-1) reads to EOF)")
        self.assertIn(b"400", resp.split(b"\r\n", 1)[0])

    def test_put_malformed_content_length_returns_400(self) -> None:
        with _Server() as srv:
            resp = srv.raw(
                b"PUT /sync/put/x.txt HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                + AUTH_HEADER.encode() + b": " + AUTH_TOKEN.encode() + b"\r\n"
                b"Content-Length: not-a-number\r\n\r\n"
            )
        self.assertTrue(resp, "malformed PUT Content-Length produced no response")
        self.assertIn(b"400", resp.split(b"\r\n", 1)[0])

    def test_put_oversize_is_refused(self) -> None:
        with _Server() as srv:
            resp = srv.raw(
                b"PUT /sync/put/x.txt HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                + AUTH_HEADER.encode() + b": " + AUTH_TOKEN.encode() + b"\r\n"
                b"Content-Length: 999999999\r\n\r\n"
            )
        self.assertTrue(resp, "oversize PUT produced no response")
        self.assertIn(b"413", resp.split(b"\r\n", 1)[0])


class AuthGate(unittest.TestCase):
    """Constant-time comparison must not change who gets in."""

    def test_wrong_token_is_401(self) -> None:
        with _Server() as srv:
            req = urllib.request.Request(
                f"http://127.0.0.1:{srv.port}/sync/list",
                headers={AUTH_HEADER: "wrong-token"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 401)

    def test_missing_token_is_401(self) -> None:
        with _Server() as srv:
            req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/sync/list")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 401)

    def test_correct_token_is_accepted(self) -> None:
        with _Server() as srv:
            code, _ = srv.get("/sync/list")
        self.assertEqual(code, 200)


class PublicRoutesLeakNoSecrets(unittest.TestCase):
    """/health is the one unauthenticated route - it must stay a bool."""

    def test_health_reports_key_presence_not_the_key(self) -> None:
        with _Server() as srv:
            req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/health")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
        self.assertIn(b"api_key_ok", body)
        self.assertNotIn(b"sk-ant-", body)


if __name__ == "__main__":
    unittest.main()
