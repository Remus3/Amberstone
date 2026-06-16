"""OVL2: structural contract for the pengu/ Pengu Loader plugin stub.

No live client is needed (CODE-ONLY STUB; live validation OWED). These pins
guard the skeleton's shape + ASCII hygiene so a later in-client wire-up has a
stable contract to build on.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PENGU = Path(__file__).resolve().parent.parent / "pengu"
INDEX = PENGU / "index.js"
PANEL = PENGU / "panel.css"
README = PENGU / "README.md"


def test_plugin_files_exist():
    assert INDEX.is_file()
    assert PANEL.is_file()
    assert README.is_file()


def test_index_fetches_state_with_configurable_origin():
    src = INDEX.read_text(encoding="utf-8")
    assert "/api/state" in src
    assert "rc_origin" in src           # localStorage override key
    assert "https://127.0.0.1:8888" in src  # default RC_ORIGIN
    assert "import.meta.url" in src      # sibling panel.css resolution
    assert "panel.css" in src
    assert "tokens.css" in src           # consumes the dashboard design tokens
    assert "export default" in src       # Pengu Loader entry


def test_panel_css_uses_design_tokens():
    css = PANEL.read_text(encoding="utf-8")
    assert "var(--" in css               # references the token layer
    assert "--fs-" in css                # v2.1 font scale
    assert "rc-pengu" in css


@pytest.mark.parametrize("path", [INDEX, PANEL, README])
def test_plugin_files_are_ascii_clean(path):
    raw = path.read_bytes()
    # No non-ASCII bytes (bans em/en dashes + smart quotes repo-wide).
    assert raw.decode("ascii")
    for bad in ("—", "–", "‘", "’", "“", "”"):
        assert bad not in raw.decode("utf-8")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
