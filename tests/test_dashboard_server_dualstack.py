"""Regression guard for the 2026-06-02 dual-stack dashboard bind.

`legion-rc` resolves IPv6-first on clients (Tailscale AAAA fd7a:... + link-local
fe80::). A v4-only 0.0.0.0 listener left the browser's IPv6 connects - including
the long-lived /api/state-stream EventSource that carries live data - hitting no
listener, so the hostname "loaded the page but showed no live data" (page
survived via IPv4 fallback) while typed IPv4 URLs worked fully. These pins lock
the dual-stack bind (`::` + IPV6_V6ONLY=0) so a refactor can't silently regress
it back to an IPv4-only listener.
"""
from __future__ import annotations

import socket
import unittest
from http.server import BaseHTTPRequestHandler

from dashboard import server as srv


class _Noop(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence per-request stderr noise
        pass


class DualStackBindTests(unittest.TestCase):
    def test_host_is_v6_wildcard(self) -> None:
        self.assertEqual(srv.HOST, "::")

    def test_dual_protocol_server_is_v6(self) -> None:
        self.assertEqual(
            srv._DualProtocolHTTPServer.address_family, socket.AF_INET6
        )

    def test_dual_stack_fallback_is_v6(self) -> None:
        self.assertEqual(
            srv._DualStackHTTPServer.address_family, socket.AF_INET6
        )

    def test_mixin_clears_v6only_on_real_bind(self) -> None:
        # Binding the no-TLS fallback exercises _DualStackMixin.server_bind on a
        # real socket. Assert the family is v6 AND IPV6_V6ONLY is cleared so the
        # single listener accepts IPv4 (v4-mapped) connections too - the exact
        # property that lets an IPv6-first hostname reach the dashboard.
        s = srv._DualStackHTTPServer(("::", 0), _Noop)
        try:
            self.assertEqual(s.socket.family, socket.AF_INET6)
            self.assertEqual(
                s.socket.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY), 0
            )
        finally:
            s.server_close()


if __name__ == "__main__":
    unittest.main()
