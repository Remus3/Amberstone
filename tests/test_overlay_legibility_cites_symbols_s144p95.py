"""RM-1395: the overlay legibility tooling cites overlay.css by selector.

tools/overlay_legibility_preview.py and its spec test carried fifteen
`overlay.css:<line>` / `active_match.css:<line>` anchors. Every one had drifted
(overlay.css:339-344 is a comment block now, :217-224 a first-paint gate, :608
and :627 land inside comments). The prose now names the rule's selector, which
survives an edit above it; this guard keeps it that way and pins that each
cited selector still exists in the stylesheet it names. The dated spec doc
docs/qa/OVERLAY_LEGIBILITY_VARIANTS_2026-09-01.md keeps its line numbers: it
records what was measured on that day.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "tools/overlay_legibility_preview.py",
    "tests/test_overlay_legibility_variants_spec.py",
)

_LINE_CITE = re.compile(r"[A-Za-z0-9_/.]+\.(?:py|js|css|json):\d+")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    assert _LINE_CITE.findall(_read(rel)) == [], "cite a selector, not a line number"


@pytest.mark.parametrize("rel", MODULES)
def test_module_stays_ascii_and_lf(rel):
    raw = (ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        '"rule": "overlay.css:339-344 (rgb(--ovx-text), --fs-ov-call 14px/700)",',
        "# (overlay.css:627) deliberately strip the widget frame",
        "#   web/css/panels/active_match.css:92-100",
        "active_match.css:92-100 (1,1,0) outranks overlay.css:217-223",
    ):
        assert _LINE_CITE.search(old), old
    assert _LINE_CITE.search("served on :8889 by overlay.css") is None


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("web/css/panels/active_match.css", "#view-active-match .am-pane {"),
        ("web/css/overlay.css", 'body[data-shell="overlay"] .ovx-widget .am-pane,'),
        ("web/css/overlay.css", 'body[data-shell="overlay"] .ovx-widget.am-pane {'),
        ("web/css/overlay.css", '.ovx-widget[data-ovx-id="w-trinket"] {'),
        ("web/css/overlay.css", '.ovx-widget[data-ovx-id="w-mmrect"] {'),
        ("web/css/overlay.css", 'div[data-call-line="action"] > span:last-child'),
        ("web/css/overlay.css", 'div[data-call-line="action"][data-call-band] {'),
        ("web/css/overlay.css", 'div[data-call-line="right-now"] > span:last-child {'),
        ("web/css/overlay.css", 'div[data-call-line="objective"] > span:last-child'),
        ("web/css/overlay.css", ".ovx-widget .am-pane-head {"),
        ("web/css/overlay.css", '#rn-lead .rc-lead-line {'),
        ("web/css/overlay.css", '#rn-lead .rc-lead-tag {'),
        ("web/css/overlay.css", 'body[data-shell="overlay"] .rc-co-eta {'),
        ("web/css/overlay.css", 'body[data-shell="overlay"] .rc-co-eta.rc-co-now {'),
        ("web/css/overlay.css", "/* 7. Combat declutter (doctrine section 6)."),
    ],
)
def test_every_selector_the_modules_cite_still_exists(rel, needle):
    assert needle in _read(rel), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "name",
    [
        '`.ovx-widget[data-ovx-id="w-trinket"]` rule in',
        "the `#view-active-match .am-pane` rule in web/css/panels/active_match.css",
        "the `.ovx-widget .am-pane, .ovx-widget.am-pane` rule in web/css/overlay.css",
        "the section 7 combat declutter block of overlay.css",
        "outranks the overlay.css",
    ],
)
def test_prose_still_names_the_selector(name):
    assert name in _read("tools/overlay_legibility_preview.py")
