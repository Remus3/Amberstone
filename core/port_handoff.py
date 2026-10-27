# arch: launcher port hand-off - wait out a dying holder before skipping a start | section=core | frozen=no
"""Wait out a dying predecessor before a server launcher gives up its port.

Measured 2026-10-23 (session 129): after ``schtasks /End /TN
RC-DS-MatchDB-MCP`` the old process lingered for a moment. An immediate
``schtasks /Run`` found :8861 still bound, logged "port 8861 already bound -
skipping (exit 0)" and exited; then the old pid died, and nothing listened on
:8861 until a second ``/Run``. The launchers treated "the port is held right
now" as "a live instance will keep serving it" - one point-in-time check. The
same check sat in ``tools/start_daemon_slayer.py`` (:8860), in
``tools/ds_matchdb_mcp_server.serve_forever`` and in the vision server's own
start guard (:8889).

``await_port`` retries a PLAIN bind for ``window_s`` seconds:

* FREE  - the bind succeeded inside the window: start the server.
* LIVE  - still held when the window ends AND ``holder_live()`` says the
  holder answers as a real instance of this server: skip (exit 0), it serves.
* STUCK - still held and the holder does not answer as this server: the
  caller cannot bind and must not report success.

The holder is trusted only AFTER the whole window, never on the first
answer: a process that is being ended can still answer for a moment, so an
early "it answers, skip" would re-open exactly this race.

The probe bind sets no SO_REUSEADDR. The servers themselves bind WITH it
(``http.server.HTTPServer.allow_reuse_address``), and on Windows that option
lets a second socket co-bind a port another socket holds; a plain bind fails
while any socket holds the port, which is what "still held" has to mean here.
Every side effect is injectable for tests. Stdlib only, so a launcher can
import it before its server's heavy imports.

Residuals (RM-834, measured 2026-10-27; tests/test_port_handoff_residuals_rm834.py):

* (b) FIXED. The liveness probe waited 2 s, so a live server whose
  ``/health`` was slower (a loaded box) read STUCK and its launcher logged
  "not started (exit 1)" beside a serving instance. It now waits
  ``HEALTH_TIMEOUT_S`` (10 s, read at call time). Reverses if: a live holder
  is measured taking longer than that to answer ``/health``.
* (c) The probe sends the caller's headers (the match-DB bearer) only to a
  loopback host: ``health_answers`` refuses any other host before it
  connects. ACCEPTED: the loopback holder is not identified before the
  bearer goes to it, because every MCP client already sends the same bearer
  to the same port on every call, so the probe adds no exposure. Reverses
  if: the clients gain a holder-identity check (then the probe gets the same
  one), or the probe's bearer stops being the one the clients already send.
* (a) RECORDED, not fixed. A holder that keeps answering ``/health`` for the
  whole window while it is being ended reads LIVE (exit 0), and the port can
  go down after it exits. No outside probe can tell it from a live holder,
  and none of these servers serves ``/health`` while it shuts down (an ended
  task's process is terminated, with no thread left to answer). Reverses
  if: a server gains a graceful shutdown that keeps serving ``/health``
  (then ``/health`` must say it is stopping and the probe must reject that),
  or a log shows a LIVE skip followed by the port down with no new start.
* (d) NOT MEASURED. Linux refuses a plain bind while a TIME_WAIT socket
  holds the port, so a holder that closed live connections could read held
  for the whole window there. RC runs on Windows only (ADR-011); CI's Linux
  runner never creates a TIME_WAIT on these ports. Reverses if: a launcher
  runs on Linux or WSL (then measure it there first).
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import time
from typing import Callable, Mapping, NamedTuple, Optional

FREE, LIVE, STUCK = "free", "live", "stuck"

# A process being ended releases its socket in well under a second on a quiet
# box; 30 s covers a loaded one. The cost lands only on a start that finds a
# genuinely live holder (a manual run beside the task: the task itself is
# IgnoreNew, so the scheduler never starts a second copy), and that start
# merely exits 30 s later.
WINDOW_S = 30.0
POLL_S = 0.25
# The liveness probe runs once, after the whole window, so a few seconds more
# to tell a slow live holder from a mute one is cheap (RM-834 b: 2.0 read a
# loaded live server as STUCK). Read at call time so a test can shorten it.
HEALTH_TIMEOUT_S = 10.0


class Handoff(NamedTuple):
    state: str          # FREE / LIVE / STUCK
    waited_s: float     # seconds spent before the verdict


def require_loopback(host: str) -> str:
    """Return ``host`` when it is a loopback address, else raise ValueError.

    Every RC server is local-only (ADR-011); a ``--host ''`` or ``0.0.0.0``
    reaching a bind would expose it on every interface (CodeQL
    py/bind-socket-all-network-interfaces, alert 66, MAIN FIX 2026-10-25 1935).
    """
    h = (host or "").strip()
    if h.lower() == "localhost":
        return host
    try:
        ok = ipaddress.ip_address(h.strip("[]")).is_loopback
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(f"refusing non-loopback bind host {host!r}")
    return host


def can_bind(host: str, port: int) -> bool:
    """True when a plain (no SO_REUSEADDR) bind of ``host:port`` succeeds.

    Raises ValueError for a non-loopback ``host`` (see ``require_loopback``).
    """
    host = require_loopback(host)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def health_answers(host: str, port: int, *, path: str = "/health",
                   headers: Optional[Mapping[str, str]] = None,
                   timeout_s: Optional[float] = None,
                   check: Optional[Callable[[bytes], bool]] = None) -> bool:
    """True when ``GET path`` answers 200 (and ``check(body)`` holds).

    ``timeout_s`` defaults to ``HEALTH_TIMEOUT_S``. A non-loopback ``host``
    is refused before any connection opens, so ``headers`` (a bearer) never
    leave the box (RM-834 c).

    Never raises: a refused, reset, timed-out or malformed answer, a
    non-loopback host, or a ``check`` that raises, is simply "does not
    answer as this server".
    """
    try:
        require_loopback(host)
    except ValueError:
        return False
    if timeout_s is None:
        timeout_s = HEALTH_TIMEOUT_S
    conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
    try:
        conn.request("GET", path, headers=dict(headers or {}))
        resp = conn.getresponse()
        body = resp.read(65536)
        if resp.status != 200:
            return False
        return True if check is None else bool(check(body))
    except Exception:  # noqa: BLE001 - any failure means "not a live instance"
        return False
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def json_check(predicate: Callable[[dict], bool]) -> Callable[[bytes], bool]:
    """A ``health_answers`` check: the body is a JSON object and ``predicate`` holds."""
    def _check(body: bytes) -> bool:
        doc = json.loads(body.decode("utf-8"))
        return isinstance(doc, dict) and bool(predicate(doc))
    return _check


def await_port(host: str, port: int, *, holder_live: Callable[[], bool],
               window_s: float = WINDOW_S, poll_s: float = POLL_S,
               bind_ok: Callable[[str, int], bool] = can_bind,
               clock: Callable[[], float] = time.monotonic,
               sleep: Callable[[float], None] = time.sleep) -> Handoff:
    """Wait up to ``window_s`` for ``host:port`` to come free; see the module doc."""
    require_loopback(host)
    start = clock()
    deadline = start + max(0.0, float(window_s))
    while True:
        if bind_ok(host, port):
            return Handoff(FREE, clock() - start)
        now = clock()
        if now >= deadline:
            break
        sleep(max(0.0, min(float(poll_s), deadline - now)))
    try:
        live = bool(holder_live())
    except Exception:  # noqa: BLE001 - a probe that raises proves nothing
        live = False
    if live:
        return Handoff(LIVE, clock() - start)
    # The liveness probe took time; a holder that died meanwhile has freed it.
    if bind_ok(host, port):
        return Handoff(FREE, clock() - start)
    return Handoff(STUCK, clock() - start)
