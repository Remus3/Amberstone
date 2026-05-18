"""Regression guard for the canonical champion-alias unification (s173 #3).

The JSON at ``web/data/champion_aliases.json`` is the single source of truth
for display-name → DDragon-id rename overrides. It is consumed by:
  - ``web/js/lib/items_index.js`` (runtime, async fetch)
  - ``web/js/dashboard.js`` (runtime, async fetch - dead-code mirror)
  - ``tools/daemon_slayer_extract.py`` (build-time, sync read)

If any consumer hardcodes the map again or the JSON drops an entry, this
test fails - preserving the audit-finding #3 invariant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIASES_PATH = ROOT / "web" / "data" / "champion_aliases.json"

EXPECTED_ALIASES = {
    "wukong": "MonkeyKing",
    "renataglasc": "Renata",
    "nunuwillump": "Nunu",
}


def test_canonical_aliases_file_exists():
    assert ALIASES_PATH.is_file(), f"missing canonical file: {ALIASES_PATH}"


def test_canonical_aliases_content():
    """The JSON must be a flat dict matching the expected key→value map.

    Keys MUST be lowercase-ASCII alphanumeric so JS and Python normalizers
    both produce identical lookup keys.
    """
    data = json.loads(ALIASES_PATH.read_text("utf-8"))
    assert isinstance(data, dict), "champion_aliases.json must be a flat dict"
    assert data == EXPECTED_ALIASES, (
        f"alias map drift detected: got {data!r}, expected {EXPECTED_ALIASES!r}. "
        "If you intentionally added/removed an alias, update EXPECTED_ALIASES."
    )
    for key in data:
        assert key.islower(), f"key {key!r} must be lowercase"
        assert key.isalnum(), f"key {key!r} must be alphanumeric (no spaces/punct)"


def test_python_resolver_uses_canonical_map():
    """``tools/daemon_slayer_extract.py`` must read the canonical JSON
    at import time (not a hardcoded dict)."""
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from daemon_slayer_extract import (
        _LOLMATH_TO_DDRAGON_ALIAS,
        _championkey_to_ddragon_id,
    )

    assert _LOLMATH_TO_DDRAGON_ALIAS == EXPECTED_ALIASES, (
        "Python resolver's loaded map diverges from canonical JSON - "
        "likely a hardcoded fallback was reintroduced."
    )

    # lolmath emits camelCase keys; resolver must normalize before lookup.
    ddragon_ids = {"MonkeyKing", "Nunu", "Renata", "Aatrox", "Leblanc"}
    assert _championkey_to_ddragon_id("wukong", ddragon_ids) == "MonkeyKing"
    assert _championkey_to_ddragon_id("nunuWillump", ddragon_ids) == "Nunu"
    assert _championkey_to_ddragon_id("renataGlasc", ddragon_ids) == "Renata"
    # Non-aliased path still works via existing case-insensitive fallback.
    assert _championkey_to_ddragon_id("leBlanc", ddragon_ids) == "Leblanc"
    # Unknown key returns None.
    assert _championkey_to_ddragon_id("notachampion", ddragon_ids) is None


def test_js_consumers_reference_canonical_file():
    """Sanity check: both JS consumers must fetch ``/data/champion_aliases.json``
    rather than carrying a hardcoded dict.

    This is a string-grep, not a runtime check - but it's enough to catch
    a regression where someone re-hardcodes the map inline.
    """
    for js_path in [
        ROOT / "web" / "js" / "lib" / "items_index.js",
        ROOT / "web" / "js" / "dashboard.js",
    ]:
        src = js_path.read_text("utf-8")
        assert "/data/champion_aliases.json" in src, (
            f"{js_path.name} does not fetch the canonical alias JSON"
        )
        # The hardcoded triple should NOT be present as object-literal entries
        # (we use a substring that would appear only in a hardcoded map).
        assert '"wukong": "MonkeyKing"' not in src, (
            f"{js_path.name} appears to have re-hardcoded the alias map"
        )
