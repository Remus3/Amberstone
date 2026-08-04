# arch: vision_server package facade + entrypoint | section=vision | frozen=no
"""vision_server - :8889 HTTP server for frame cache + Sonnet vision + OCR.

Phase 2.4 split (2026-05-09): the original ``moon_vision_server.py`` (710
LOC) was decomposed into:
  - ``_config``    - port/auth/model constants + Anthropic client
  - ``_stats``     - call counters + log/latency rings
  - ``_frame``     - latest-frame cache + upload handler
  - ``_relay``     - LCU + Live Client API relays
  - ``_inference`` - Sonnet vision + Haiku coach + Tesseract OCR
  - ``_http``      - BaseHTTPRequestHandler routing

The root ``moon_vision_server.py`` is kept as a thin entrypoint shim because
``dashboard/server.py`` spawns the server by file path (not Python import)
when :8889 is not listening - the sole launcher since the ``RC-VisionServer``
scheduled task was removed (2026-06-11, deep-audit P2).
"""
from __future__ import annotations

import os
import socket
import sys
from http.server import ThreadingHTTPServer

from ._config import PORT, _get_client, api_key_present, log
from ._frame import get_latest_frame, handle_upload_frame
from ._http import Handler
from ._inference import handle_coach, handle_ocr, handle_vision
from ._relay import (get_latest_liveclient, get_latest_lcu,
                     handle_upload_liveclient, handle_upload_lcu,
                     lcu_drain_pending, lcu_queue_command, lcu_record_result)
from ._stats import get_stats

__all__ = [
    "Handler",
    "PORT",
    "get_latest_frame",
    "get_latest_lcu",
    "get_latest_liveclient",
    "get_stats",
    "handle_coach",
    "handle_ocr",
    "handle_upload_frame",
    "handle_upload_lcu",
    "handle_upload_liveclient",
    "handle_vision",
    "lcu_drain_pending",
    "lcu_queue_command",
    "lcu_record_result",
    "main",
]


def _bind_host() -> str:
    """Listener address for :8889. Loopback by default (RM-150).

    This bound ``0.0.0.0`` from the pre-ADR-011 2-PC era, when the frame and
    LCU agents ran on a second machine. Every client is Legion-local now
    (``core/liveclient_cache``, ``dashboard/*``, and the three ``tools/*``
    agents repointed alongside this change), so the wildcard only bought LAN
    and tailnet reachability for a route family gated by one ``X-RC-Token``
    header - the amplifier LEDGER 1177 named on the ``/sync/get/`` traversal.

    Overridable for the same reason ``core/game_host.py`` is: the host is
    config, not code. A blank value is treated as unset, so a scheduled task
    that exports an empty variable cannot silently re-open the wildcard.
    """
    return (os.environ.get("RC_VISION_BIND") or "").strip() or "127.0.0.1"


def main() -> int:
    """Entry point used by the ``moon_vision_server.py`` shim and ``python -m
    vision_server``. Returns process exit code."""
    if not api_key_present():
        log.error("No API key")
        return 1

    # Guard: exit cleanly if another instance is already on this port.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1)
    already = probe.connect_ex(("127.0.0.1", PORT)) == 0
    probe.close()
    if already:
        log.warning("Port %d already in use - another instance is running. Exiting.", PORT)
        return 0   # clean exit, not error - autostart VBS sees success

    # Port did not answer: reap any wedged/orphaned predecessor instances that
    # would otherwise co-bind :8889 via SO_REUSEADDR and jam the port so every
    # connect() is refused (project_liveclient_loopback_regression, 2026-07-05).
    from ._reap import reap_stale_vision_instances
    reaped = reap_stale_vision_instances()
    if reaped:
        log.warning("cleared %d stale vision-server instance(s) before bind: %s",
                    len(reaped), reaped)

    _get_client()
    host = _bind_host()
    log.info("Moon Vision Server on %s:%d  python=%s", host, PORT, sys.executable)
    # ThreadingHTTPServer (S7, 2026-06-10): the plain HTTPServer serialized
    # EVERY request behind the slowest in-flight handler - an in-process
    # self-grab (GDI BitBlt + JPEG encode, 100-400ms) or a Sonnet/OCR
    # inference call would block /latest-lcu, /latest-liveclient and the
    # LCU command queue for its whole duration, which the operator felt as
    # slow champ-select updates + slow build/rune pushes. All shared state
    # in _frame/_relay/_stats was already lock-guarded, so per-request
    # threads are safe.
    s = ThreadingHTTPServer((host, PORT), Handler)
    s.daemon_threads = True
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        s.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
