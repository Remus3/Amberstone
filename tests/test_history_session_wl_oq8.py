"""
tests/test_history_session_wl_oq8.py

OQ8 (QA37, operator-queue 2026-07-01) - History per-session W-L header
rollup. The 2hr-gap session grouping already exists SERVER-side
(dashboard/builders.py _group_sessions, SESSION_GAP_S); each session's
matches carry a per-match `win` field (true/false/null via _lcu_win,
item 77 WIN-CAPTURE). The rollup is therefore pure PRESENTATION:
main.js computes W-L from s.matches at render (works identically for
the live /api/history payload and the ui_mock fixture - neither needed
a schema change), shows it in the session row and the detail head, and
undecided matches (win === null, pre-ingest rows) are excluded rather
than guessed - the same no-guessed-outcome rule builders.py documents.

String-assertion tests per the repo convention (test_ui_polish pattern);
the rendered proof lives in tests/snapshot_panels/test_history_view.py::
test_history_session_wl_rollup.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_JS = ROOT / "web" / "js" / "main.js"
HEADER_CSS = ROOT / "web" / "css" / "panels" / "header.css"


def _js() -> str:
    return MAIN_JS.read_text(encoding="utf-8")


def test_session_wl_helper_counts_strict_booleans():
    """The rollup helper must count ONLY strict true/false wins - a null
    (undecided pre-ingest row) is neither a W nor an L."""
    js = _js()
    assert "function _sessionWL(" in js, "main.js missing the _sessionWL helper"
    body = js.split("function _sessionWL(", 1)[1].split("\n  }", 1)[0]
    assert "=== true" in body, "wins must be counted with win === true (strict)"
    assert "=== false" in body, "losses must be counted with win === false (strict)"


def test_session_row_template_carries_wl_chip():
    js = _js()
    assert "hs-wl" in js, "session row template missing the hs-wl W-L chip"
    # The chip renders wins before losses in the NW-NL shape.
    assert re.search(r"\$\{[^}]*wins[^}]*\}W", js), "chip must render <wins>W"
    assert re.search(r"\$\{[^}]*losses[^}]*\}L", js), "chip must render <losses>L"


def test_detail_head_includes_wl():
    """Both detail-head writers (session click + filter-clear restore)
    append the session W-L after the games count."""
    js = _js()
    heads = re.findall(r"head\.textContent = `MATCHES[^`]*`", js)
    assert heads, "detail-head template writers not found"
    for h in heads:
        assert "_sessionWL" in h or "wlLabel" in h, (
            f"detail head writer missing the W-L rollup: {h}"
        )


def test_header_css_styles_wl_with_tokens():
    css = HEADER_CSS.read_text(encoding="utf-8")
    assert ".hs-wl" in css, "header.css missing .hs-wl rules"
    block = css.split(".hs-wl", 1)[1]
    assert "var(--good" in block[:600], "W count must use the --good token"
    assert "var(--bad" in block[:600], "L count must use the --bad token"
