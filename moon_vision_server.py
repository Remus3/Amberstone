# arch: vision server entrypoint shim - delegates to vision_server.main | section=vision | frozen=no
"""moon_vision_server.py - thin entrypoint shim for the :8889 vision server.

The real implementation lives in the ``vision_server/`` package (Phase 2.4
split, 2026-05-09). This file is preserved as a top-level entry point because
two external callers spawn it by file path:

  1. ``RC-VisionServer`` scheduled task: ``python.exe "C:\\Riot Commander\\moon_vision_server.py"``
  2. ``dashboard/server.py``: ``subprocess.Popen([sys.executable, "moon_vision_server.py"])``

Both keep working unchanged. New code should ``from vision_server import ...``
instead of importing this file.
"""
from __future__ import annotations

import sys

from vision_server import main

if __name__ == "__main__":
    sys.exit(main())
