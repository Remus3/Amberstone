"""FLEET-KIT conformance: the vendored kit and the CLAUDE.md FLEET-COMMON block.

The kit (ops/fleet_kit/) is vendored byte-for-byte from MAIN and pinned by its
own MANIFEST.json. Its conformance() returns [] only when every kit file matches
the manifest and CLAUDE.md is ASCII, LF, and carries the FLEET-COMMON block
byte-identical between the BEGIN / END markers. Never edit the kit locally; a
new kit version arrives as a MAIN note and replaces all three files at once.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KIT_PATH = REPO_ROOT / "ops" / "fleet_kit" / "fleet_headless.py"


def _load_kit():
    spec = importlib.util.spec_from_file_location("fleet_headless", KIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fleet_kit_conformance():
    assert KIT_PATH.is_file(), f"vendored kit missing: {KIT_PATH}"
    kit = _load_kit()
    assert kit.conformance(REPO_ROOT) == []
