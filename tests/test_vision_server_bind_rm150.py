# arch: RM-150 guards for the :8889 bind narrowing + error-body redaction
"""RM-150 - the two leftovers from the lane-8 ``vision_server/_http.py`` audit.

Filed by LEDGER 1177 as MACHINE-ENV and ERROR-HANDLING findings that were
deliberately NOT fixed on the way past, so they arrive here with their
reasoning already recorded. Two halves, guarded separately.

HALF A - the ``0.0.0.0`` bind.
``vision_server/__init__.py`` bound ``ThreadingHTTPServer(("0.0.0.0", PORT))``,
which is legacy from the pre-ADR-011 2-PC era when the frame/LCU agents lived
on a second machine. Every client is Legion-local now, so the only thing the
wide bind bought was LAN + tailnet reachability for a route family gated by a
single ``X-RC-Token`` header - the amplifier LEDGER 1177 named on the
``/sync/get/`` traversal.

Narrowing it is a MULTI-FILE change and that is the whole reason the row was
filed instead of fixed inline:

1. ``tests/test_vision_server_threading_s7.py`` PINS the literal
   ``("0.0.0.0", PORT)`` by regex, so the S7 guard has to move in the same
   commit or the narrowing goes red against its own repo.
2. Three served agents hardcoded ``http://192.168.8.230:8889`` - a LAN IP that
   still resolves on this box, so they work today ONLY because of the wide
   bind. ``tools/lcu_agent.py`` is live as ``RC-LCUAgent``;
   ``tools/screen_agent.py`` and ``tools/phase_watcher.py`` are served and
   installable but not currently scheduled. Narrowing the bind without
   repointing them is how you take the LCU snapshot offline silently, since
   all three run under ``pythonw`` (LEDGER 1183 family).

The repoint follows the in-tree precedent ``tools/liveclient_relay._upload_url``
(LEDGER 1183), which already made exactly this move for the fourth agent and
recorded the reasoning: both ends are the same machine, so the token crossed
the LAN interface in cleartext for nothing, and a DHCP change would have
killed the agent silently. Host stays config, not code - same principle as
``core/game_host.py``.

HALF B - raw exception text in 5xx bodies.
``self._j(500, {"error": str(e)})`` at four sites, plus a ``/monitor`` 404 that
returned its whole candidate list including ``Path.home()``. LEDGER 1177
classed this as hardening rather than an Error-Handling breach - :8889 is a
machine-local JSON API, not a coach UI or a dashboard panel, so the CLAUDE.md
rule about user-facing error strings does not bind it. It is still a free
disclosure of module paths, home directory and exception internals to anything
that can reach the port, so it is closed here rather than carried.
"""
from __future__ import annotations

import ast
import json
import os
import re
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import vision_server
from vision_server import _http
from vision_server._config import AUTH_HEADER, AUTH_TOKEN

REPO = Path(__file__).resolve().parent.parent
LAN_PIN = re.compile(r"192\.168\.8\.230:8889")


class _Server:
    """Real Handler on an ephemeral loopback port - no mocks in the path."""

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


class BindHostTests(unittest.TestCase):
    """HALF A - the listener address is loopback, and it is config not code."""

    def test_default_bind_is_loopback(self) -> None:
        self.assertEqual(vision_server._bind_host(), "127.0.0.1")

    def test_bind_host_is_env_overridable(self) -> None:
        prev = os.environ.get("RC_VISION_BIND")
        os.environ["RC_VISION_BIND"] = "0.0.0.0"
        try:
            self.assertEqual(vision_server._bind_host(), "0.0.0.0")
        finally:
            if prev is None:
                os.environ.pop("RC_VISION_BIND", None)
            else:
                os.environ["RC_VISION_BIND"] = prev

    def test_blank_env_falls_back_to_loopback(self) -> None:
        """An empty env var is an unset one - never a wildcard bind."""
        prev = os.environ.get("RC_VISION_BIND")
        os.environ["RC_VISION_BIND"] = "   "
        try:
            self.assertEqual(vision_server._bind_host(), "127.0.0.1")
        finally:
            if prev is None:
                os.environ.pop("RC_VISION_BIND", None)
            else:
                os.environ["RC_VISION_BIND"] = prev

    def test_no_wildcard_literal_left_in_the_bind_call(self) -> None:
        """The S7 pin moved here; it must not have moved back."""
        src = (REPO / "vision_server" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotRegex(
            src, re.compile(r"ThreadingHTTPServer\(\(\s*[\"']0\.0\.0\.0[\"']"),
            "wildcard bind reintroduced - :8889 is Legion-local (ADR-011) and "
            "its routes are gated by one X-RC-Token header (LEDGER 1177)")


class AgentUploadTargetTests(unittest.TestCase):
    """HALF A - no served agent may depend on the wide bind to reach :8889."""

    @staticmethod
    def _agent_allowlist() -> set[str]:
        """Read the served-file allowlist off disk, not from a restatement."""
        src = (REPO / "dashboard" / "routes_static.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", "") == "_AGENT_ALLOWED"
                            for t in node.targets)):
                return {e.value for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        raise AssertionError("_AGENT_ALLOWED not found in routes_static.py")

    def test_allowlist_is_non_empty(self) -> None:
        """Guard the guard - an empty allowlist makes the sweep vacuous."""
        self.assertGreater(len(self._agent_allowlist()), 3)

    def test_the_three_repointed_agents_are_still_served(self) -> None:
        """If one leaves the allowlist the sweep below stops covering it."""
        served = self._agent_allowlist()
        for name in ("lcu_agent.py", "screen_agent.py", "phase_watcher.py"):
            self.assertIn(name, served)

    def test_no_served_agent_hardcodes_the_lan_ip_for_8889(self) -> None:
        checked = 0
        for name in sorted(self._agent_allowlist()):
            if not name.endswith(".py"):
                continue
            path = REPO / "tools" / name
            if not path.exists():
                continue
            checked += 1
            src = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                src, LAN_PIN,
                f"{name} reaches :8889 over the LAN IP - it works only while "
                "the server binds a wildcard, and a DHCP change kills it "
                "silently under pythonw (precedent: liveclient_relay)")
        self.assertGreaterEqual(checked, 3, "sweep read too few agent files")

    def test_repointed_agents_expose_an_env_override(self) -> None:
        """Host is config, not code - same rule as core/game_host.py."""
        for name, var in (("lcu_agent.py", "RC_VISION_BASE"),
                          ("screen_agent.py", "RC_VISION_UPLOAD_URL"),
                          ("phase_watcher.py", "RC_VISION_BASE")):
            src = (REPO / "tools" / name).read_text(encoding="utf-8")
            self.assertIn(var, src, f"{name} has no host override")
            self.assertIn("127.0.0.1:8889", src, f"{name} default is not loopback")


class ErrorBodyRedactionTests(unittest.TestCase):
    """HALF B - a 5xx says something went wrong, not what or where."""

    def test_500_body_carries_no_exception_text(self) -> None:
        sentinel = "SENTINEL-LEAK-RM150"
        original = _http.get_stats

        def boom() -> dict:
            raise ValueError(sentinel)

        _http.get_stats = boom
        try:
            with _Server() as s:
                status, body = s.get("/stats")
        finally:
            _http.get_stats = original
        self.assertEqual(status, 500)
        self.assertNotIn(sentinel, body.decode("utf-8", "replace"))
        self.assertEqual(json.loads(body).get("error"), "internal error")

    def test_monitor_404_does_not_list_filesystem_paths(self) -> None:
        with _Server() as s:
            status, body = s.get("/monitor")
        if status == 200:
            self.skipTest("moon_monitor.html is present on this box")
        self.assertEqual(status, 404)
        text = body.decode("utf-8", "replace")
        self.assertNotIn("searched", text)
        self.assertNotIn(str(Path.home()), text)
        self.assertNotIn("Desktop", text)

    def test_no_500_site_still_formats_the_exception(self) -> None:
        """Source pin - the four str(e) bodies LEDGER 1177 named."""
        src = (REPO / "vision_server" / "_http.py").read_text(encoding="utf-8")
        self.assertNotRegex(
            src, re.compile(r"_j\(5\d\d,\s*\{\"error\":\s*str\(e\)"),
            "a 5xx body is formatting the exception again")

    def test_every_500_site_logs_the_raw_cause(self) -> None:
        """Redaction must not become suppression - the log keeps the detail."""
        src = (REPO / "vision_server" / "_http.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("self._err500("), 4)
        body = src.split("def _err500")[1].split("\n    def ")[0]
        self.assertIn("log.error", body)


if __name__ == "__main__":
    unittest.main()
