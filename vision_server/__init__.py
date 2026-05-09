# arch: vision_server package facade + entrypoint | section=vision | frozen=no
"""vision_server — :8889 HTTP server for frame cache + Sonnet vision + OCR.

Phase 2.4 split (2026-05-09): the original ``moon_vision_server.py`` (710
LOC) was decomposed into:
  - ``_config``    — port/auth/model constants + Anthropic client
  - ``_stats``     — call counters + log/latency rings
  - ``_frame``     — latest-frame cache + upload handler
  - ``_relay``     — LCU + Live Client API relays
  - ``_inference`` — Sonnet vision + Haiku coach + Tesseract OCR
  - ``_http``      — BaseHTTPRequestHandler routing

The root ``moon_vision_server.py`` is kept as a thin entrypoint shim because
``RC-VisionServer`` scheduled task and ``dashboard/server.py`` both spawn the
server by file path (not Python import).
"""
from __future__ import annotations

import socket
import sys
from http.server import HTTPServer

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
        log.warning("Port %d already in use — another instance is running. Exiting.", PORT)
        return 0   # clean exit, not error — autostart VBS sees success

    _get_client()
    log.info("Moon Vision Server on 0.0.0.0:%d  python=%s", PORT, sys.executable)
    s = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        s.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
