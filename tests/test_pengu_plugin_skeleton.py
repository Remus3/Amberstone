"""OVL2: structural contract for the Pengu Loader plugin stub.

No live client is needed (CODE-ONLY STUB; live validation OWED). These pins
guard the skeleton's shape + ASCII hygiene so a later in-client wire-up has a
stable contract to build on.

RM-119 class B4, 2026-08-06: this module used to carry a module-level
`pytestmark = pytest.mark.skipif(not PENGU.is_dir(), ...)` aimed at a repo-root
`pengu/` that was relocated to `docs/_archive/2026-07-07-pengu-stub/` on
2026-07-07. Every one of its six tests had skipped silently ever since, so the
structural contract it exists to pin was asserted NOWHERE - the classic B4
shape, where the tree contradicts the module's premise and the suite reports
green by not running.

The premise was SATISFIABLE the whole time: the three stub files are TRACKED at
the archive path, so they are present in every checkout. The fix is to resolve
the stub ROOT rather than to assume one location - repo-root `pengu/` when the
stub is live there again, the tracked archive otherwise - and to assert, never
skip. Whichever copy is authoritative on this checkout is the one held to the
contract, and the BACKLOG question (was the archival intended, or should the
stub return to `pengu/`?) is left exactly where it was: unanswered, but no
longer able to silence the guard.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_LIVE = _ROOT / "pengu"
_ARCHIVED = _ROOT / "docs" / "_archive" / "2026-07-07-pengu-stub"

# Prefer a revived repo-root stub; fall back to the tracked archived copy.
PENGU = _LIVE if _LIVE.is_dir() else _ARCHIVED
INDEX = PENGU / "index.js"
PANEL = PENGU / "panel.css"
README = PENGU / "README.md"


def test_the_stub_is_reachable_on_every_checkout():
    """No skip may stand in for this: one of the two locations MUST hold it.

    `docs/_archive/2026-07-07-pengu-stub/` is tracked in git, so its absence is
    a broken checkout rather than an absent environment capability - which is
    exactly the moment the tests below have to fail instead of skip.
    """
    assert PENGU.is_dir(), (
        f"neither the live stub at {_LIVE} nor the tracked archived copy at "
        f"{_ARCHIVED} is present - the archived copy is committed, so this is "
        "a broken checkout, not a relocated stub"
    )


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
    # decode("ascii") raises on ANY non-ASCII byte - that alone bans em/en
    # dashes + smart quotes (all > U+007F) repo-wide. Codepoints are spelled
    # as escapes, never literal glyphs, so this test file stays pure ASCII.
    text = raw.decode("ascii")
    for cp in (0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D):
        assert chr(cp) not in text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
