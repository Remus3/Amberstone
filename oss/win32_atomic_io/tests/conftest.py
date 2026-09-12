"""Put the src-layout package on sys.path for the in-tree test run.

An installed copy (pip install -e .) needs none of this; this exists so the
tests are runnable straight from a checkout without an install step.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
