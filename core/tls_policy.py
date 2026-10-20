"""One TLS protocol floor for every ssl.SSLContext RC builds itself (RM-752).

Every server or client context RC constructs comes from a factory here, so
the floor is one constant instead of a per-site default.

Why TLSv1_2 and not TLSv1_3-only (measured 2026-10-20, session 125; decision
recorded in docs/OPERATIONS.md "TLS protocol floor (RM-752)"):

* Python 3.14.4 / OpenSSL 3.0.19 already gives a bare
  ``ssl.SSLContext(PROTOCOL_TLS_SERVER | PROTOCOL_TLS_CLIENT)`` a TLSv1_2
  floor, so pinning TLSv1_2 changes no handshake; it makes the floor explicit
  (CodeQL py/insecure-protocol reads an unset floor as "any version") and
  independent of the interpreter.
* A TLSv1_3-only :8888 / :8895 refuses this box's own tools: both curl.exe
  builds and PowerShell 5.1 use Schannel, which has no TLS 1.3 client on
  Windows 10 (curl rc=35 against a 1.3-only loopback server).
* The LCU peer is Riot's; RC's default-context LCU readers prove it speaks
  TLS 1.2, nothing here proves it speaks 1.3.

The floor is read at CALL time, so a test can move it and see every routed
site follow (tests/test_tls_floor_rm752.py).
"""
from __future__ import annotations

import ssl

TLS_MIN_VERSION = ssl.TLSVersion.TLSv1_2


def server_context() -> ssl.SSLContext:
    """A TLS server context at the RC floor; the caller loads its cert."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = TLS_MIN_VERSION
    return ctx


def client_context_noverify() -> ssl.SSLContext:
    """A client context at the RC floor with verification OFF.

    For loopback peers that present a self-signed certificate (the :8888
    dashboard's mkcert cert, the LCU's Riot cert). Hostname and chain checks
    are off; the protocol floor still applies.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = TLS_MIN_VERSION
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx
