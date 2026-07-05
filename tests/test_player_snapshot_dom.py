"""DOM-string assertions on web/js/panels/player_snapshot.js.

No browser - asserts the source exports the render fn, uses only tokens.css
custom properties (no hardcoded hex), and branches on model.empty.
"""
from pathlib import Path

SRC = Path("web/js/panels/player_snapshot.js").read_text(encoding="utf-8")


def test_exports_render_and_is_idempotent():
    assert "export function renderPlayerSnapshot(" in SRC
    assert "dataset.sig" in SRC          # idempotent signature stash


def test_no_hardcoded_hex_colors():
    import re
    # Card composes tokens; a raw #rrggbb is a token-sprawl regression.
    assert not re.search(r"#[0-9a-fA-F]{6}", SRC)


def test_handles_empty_and_ascii_only():
    assert "model.empty" in SRC
    assert all(ord(c) < 128 for c in SRC)   # ASCII-only (no em-dash/smart quote)
