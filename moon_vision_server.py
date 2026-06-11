# arch: vision server entrypoint shim - delegates to vision_server.main | section=vision | frozen=no
"""moon_vision_server.py - thin entrypoint shim for the :8889 vision server.

The real implementation lives in the ``vision_server/`` package (Phase 2.4
split, 2026-05-09). This file is preserved as a top-level entry point because
``dashboard/server.py`` spawns it by file path
(``subprocess.Popen([sys.executable, "moon_vision_server.py"])``) whenever
:8889 is not already listening - that self-heal is the ONLY launcher since the
vestigial ``RC-VisionServer`` scheduled task was removed (2026-06-11, deep-audit
P2; XML archived in ``docs/_archive/``).

New code should ``from vision_server import ...`` instead of importing this file.
"""
from __future__ import annotations

import sys

from vision_server import main

if __name__ == "__main__":
    sys.exit(main())
