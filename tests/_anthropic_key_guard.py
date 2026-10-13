"""Point the shared Anthropic key lookup away from the real key file (ENV-APIKEY).

Why: ``core/anthropic_key.py`` resolves ``<repo>/API-Key-Claude.txt`` when a
caller passes no root, and ``vision_server/_config.py`` resolves the key at
IMPORT time. About ten test modules import ``vision_server`` at module top, so
that read runs during COLLECTION - before any function-scoped fixture - and
the ``tests/conftest.py`` per-test redirect cannot reach it. Once the real key
file exists in the main checkout, collection would read the live key.

Rule: ``install()`` rebinds ``core.anthropic_key._KEY_ROOT`` to a fixed
directory outside the repo that is never created, so no key file can be there
and nothing is left behind in %TEMP% (MAIN FIX TEMP-1). The rootdir
``conftest.py`` calls it at import, which pytest does before collecting either
suite root (``tests`` and ``agents/daemon_slayer``), in the controller and in
every xdist worker. The per-test redirect in ``tests/conftest.py`` stays and
restores to this value after each test.

Pinned by ``tests/test_api_key_single_lookup_env_apikey.py`` (a subprocess
``--collect-only`` with a spy on ``key_file_path``).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

NO_KEY_ROOT = Path(tempfile.gettempdir()) / "rc-pytest-no-anthropic-key"


def install() -> Path:
    """Redirect the shared key root; return the root now in force."""
    from core import anthropic_key

    anthropic_key._KEY_ROOT = NO_KEY_ROOT
    return NO_KEY_ROOT
