"""ROADMAP NOW-3: ASCII hygiene over tracked `.css` and `.html`, enumerated
through `tests/_repo_walk` (ADR-015).

WHAT THE ROW CLAIMED, AND WHAT WAS MEASURED
-------------------------------------------
NOW-3 (filed 2026-09-19, LEDGER 1430/1431) says `.css` and `.html` are
"guarded only by the staged-line precommit hook, not by any test", and that the
lane widget's stylesheet and page are clean "by LUCK OF AUTHORING with nothing
enforcing it".

That half of the row is REFUTED, end to end rather than by reading. A probe
file `lane-widget/src/renderer/_probe_glyph.css` carrying U+2014 and U+2713 was
written and STAGED, and `pytest tests/test_ascii_source_sweep.py
tests/test_smart_quote_hygiene.py tests/test_web_comment_lines_ascii.py
tests/test_mojibake_hygiene.py -q` returned `2 failed, 15 passed`:
`test_ascii_source_sweep.py::test_no_net_new_non_ascii_in_tracked_source` and
`test_smart_quote_hygiene.py::test_no_smart_quotes_in_authored_source` both
named the probe. So a NET-NEW glyph in a `.css` outside `web/` already fails
CI today. The row's premise must not be restored.

WHAT WAS ACTUALLY MISSING, AND IS WHAT THIS MODULE ADDS
-------------------------------------------------------
Three real gaps survive that refutation:

1. ADR-015 says a guard that enumerates the REPO ROOT uses `tests/_repo_walk`.
   Measured the same day, `tests/_repo_walk` had SEVENTEEN consumers and every
   one of them passed `*.py` (or `*.py` plus `*.js`); NOTHING in the repo asked
   the canonical walker for `*.css` or `*.html`. The two guards that do reach
   those extensions each shell out to their own `git ls-files` with their own
   hand-rolled skip logic, which is the shape ADR-015 exists to stop.
2. Neither of those two guards asserts a FLOOR on how many `.css` / `.html`
   they selected. `test_ascii_source_sweep.py::test_the_sweep_selects_something`
   asserts `> 500` files across FOURTEEN patterns, which `*.py` alone satisfies:
   dropping `"*.css"` and `"*.html"` from its `_PATTERNS` would leave that
   anti-vacuity guard GREEN. The floor here is per-extension for exactly that
   reason.
3. The sweep in `test_ascii_source_sweep.py` is a RATCHET with a frozen
   baseline. A ratchet is the right shape for a tree that carries 50 files of
   deliberate UI glyphs, but it is NOT a flat ban, and the CLAUDE.md banned set
   (em-dash, en-dash, smart quotes, NBSP, ellipsis) is a flat ban with no
   legitimate exception in a stylesheet or a page. Measured: zero tracked
   `.css` / `.html` carries any of the eight today, so this lands as a strict
   ban and not as another baseline.

ONE READING, NOT A THIRD
------------------------
`test_the_walk_agrees_with_the_git_ls_files_sweep` pins the canonical walker's
`.css` / `.html` selection against the independent `git ls-files` enumeration
that `tests/test_ascii_source_sweep.py` runs, so the two cannot silently
diverge into two readings of one CLAUDE.md rule - the defect
`tools/precommit_gate.py` `_glyph_hits` was written to close.

EMPTY IS NEVER CLEAN
--------------------
Every assertion below would pass on an EMPTY enumeration, so each one is
anchored: a per-extension non-zero floor plus named anchor files. A
machine-local mis-glob turns this guard RED, never silently green.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tests import _repo_walk

_REPO = _repo_walk.REPO_ROOT

# Basename globs, as `iter_repo_files` requires.
_PATTERNS = ("*.css", "*.html")

# Measured 2026-09-20 on Legion: 70 tracked .css and 13 tracked .html reach the
# walker (71 and 13 in the git index; `docs/_archive/2026-07-07-pengu-stub/
# panel.css` is the one EXCLUDED_DIRS drops). The floors sit below those counts
# so ordinary churn does not churn this guard, and far enough above zero that a
# collapsed walk cannot pass. They are NOT a pin on the current numbers.
_CSS_FLOOR = 55
_HTML_FLOOR = 9

# Long-lived tracked paths, one per tree the walk must reach. `lane-widget/` is
# here deliberately: it is the newest .css/.html pair in the repo and the one
# NOW-3 was filed about, so it is the anchor most likely to catch a future
# enumeration that quietly covers `web/` only.
_ANCHORS = (
    "web/css/dashboard.css",
    "web/index.html",
    "lane-widget/src/renderer/widget.css",
    "lane-widget/src/renderer/index.html",
)

# The CLAUDE.md hard rule, built via chr() so this file stays 7-bit ASCII and
# does not add itself to the ratchet baseline it sits beside. Mirrors
# `tests/test_smart_quote_hygiene.py` `_BANNED` - one set, deliberately, not a
# second reading of the same rule.
_BANNED = {
    0x201C: "LEFT DOUBLE QUOTATION MARK",
    0x201D: "RIGHT DOUBLE QUOTATION MARK",
    0x2018: "LEFT SINGLE QUOTATION MARK",
    0x2019: "RIGHT SINGLE QUOTATION MARK",
    0x2013: "EN DASH",
    0x2014: "EM DASH",
    0x2026: "HORIZONTAL ELLIPSIS",
    0x00A0: "NON-BREAKING SPACE",
}


def _walk() -> list[Path]:
    """Every tracked `.css` / `.html` the canonical walker reaches."""
    return _repo_walk.repo_files(_REPO, patterns=_PATTERNS)


def _banned_hits(text: str) -> list[tuple[int, str, int]]:
    """`(codepoint, name, count)` for each banned glyph present in `text`."""
    return [
        (cp, name, text.count(chr(cp)))
        for cp, name in sorted(_BANNED.items())
        if chr(cp) in text
    ]


def test_the_walk_reaches_css_and_html() -> None:
    """Anti-vacuity anchor. Without this, every other test in this module
    passes on a walk that selected nothing, which is indistinguishable from a
    spotless tree - the exact failure `tests/_repo_walk` was written to stop.
    """
    found = {_repo_walk.relative_posix(p, _REPO) for p in _walk()}
    css = sorted(r for r in found if r.endswith(".css"))
    html = sorted(r for r in found if r.endswith(".html"))

    assert len(css) >= _CSS_FLOOR, (
        f"the .css walk selected {len(css)} files, below the {_CSS_FLOOR} floor. "
        "Either the walk collapsed (check EXCLUDED_DIRS and that `git ls-files` "
        "works here) or the tree genuinely shrank - if the latter, lower the "
        "floor deliberately in the same commit that removed the files."
    )
    assert len(html) >= _HTML_FLOOR, (
        f"the .html walk selected {len(html)} files, below the {_HTML_FLOOR} "
        "floor. Same reasoning as the .css floor above."
    )

    missing = [a for a in _ANCHORS if a not in found]
    assert not missing, (
        f"anchor file(s) {missing} are tracked but did not reach the walk. "
        "EXCLUDED_DIRS grew too broad, the pattern list stopped matching, or "
        "the anchors were renamed - fix the walk, do not delete the anchor."
    )


def test_the_scan_catches_a_planted_glyph(tmp_path: Path) -> None:
    """The NEGATIVE control for the sweep below.

    A clean tree and an inert predicate produce the identical verdict, so the
    predicate is exercised against a file that is known dirty. Written as an
    escape, never as a literal, for the reason
    `tests/test_ascii_source_sweep.py:220` records: a literal here would make
    this file a banned-glyph hit and trip the commit gate it is guarding.
    """
    dirty = tmp_path / "probe.css"
    dirty.write_text(
        "/* em" + chr(0x2014) + "dash */\n.x { color: red; }\n", encoding="utf-8")
    hits = _banned_hits(dirty.read_text(encoding="utf-8"))
    assert [cp for cp, _, _ in hits] == [0x2014], (
        f"the banned-glyph scan missed a planted em-dash; got {hits}")


def test_the_scan_accepts_clean_ascii(tmp_path: Path) -> None:
    """The POSITIVE control, and the one that matters more.

    A predicate that flags EVERYTHING passes the control above while being
    useless, and the broken version is the one that looks safest.
    """
    clean = tmp_path / "probe.css"
    clean.write_text(
        "/* plain ascii - no glyphs */\n.x { color: red; }\n", encoding="utf-8")
    assert _banned_hits(clean.read_text(encoding="utf-8")) == []


def test_no_banned_glyphs_in_tracked_css_or_html() -> None:
    """Flat ban, no baseline. Measured clean across all 83 files 2026-09-20.

    Unlike `tests/test_ascii_source_sweep.py` this is NOT a ratchet: the eight
    codepoints here have no legitimate use in a stylesheet or a page, so a hit
    is a defect rather than debt with a number on it. Decorative UI glyphs
    (arrows, status marks) are a different question and stay with the ratchet.
    """
    paths = _walk()
    assert paths, "the walk selected nothing - see test_the_walk_reaches_css_and_html"

    violations: list[str] = []
    for path in paths:
        rel = _repo_walk.relative_posix(path, _REPO)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for cp, name, count in _banned_hits(text):
            violations.append(f"  {rel}: U+{cp:04X} ({name}) x{count}")

    assert not violations, (
        "Banned glyph(s) in tracked .css / .html. CLAUDE.md is a 7-bit ASCII "
        "hard rule for authored content: use ' - ' for a clause break, a plain "
        "apostrophe, '...' for an ellipsis and a normal space.\n"
        + "\n".join(sorted(violations))
    )


def test_the_walk_agrees_with_the_git_ls_files_sweep() -> None:
    """ONE reading of "which .css / .html are authored source".

    `tests/test_ascii_source_sweep.py` enumerates with its own `git ls-files`
    call rather than through `tests/_repo_walk`. Two enumerations of one rule
    is the shape that let U+00D7 into the repo in 2026-07 (see that module's
    docstring), so pin them against each other: the walker's set must equal the
    index's set minus `_repo_walk.is_excluded`.
    """
    proc = subprocess.run(
        ["git", "ls-files", "--", *_PATTERNS],
        cwd=str(_REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"git ls-files failed: {proc.stderr.strip()}"
    indexed = {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}
    assert indexed, "git ls-files returned no .css / .html at all"

    expected = {
        rel for rel in indexed
        if not _repo_walk.is_excluded(rel) and (_REPO / rel).is_file()
    }
    walked = {_repo_walk.relative_posix(p, _REPO) for p in _walk()}

    only_index = sorted(expected - walked)
    only_walk = sorted(walked - expected)
    assert not only_index and not only_walk, (
        "the canonical walker and the git-index sweep disagree about the "
        "authored .css / .html set - one CLAUDE.md rule must not get two "
        f"readings.\n  in the index but not the walk: {only_index[:5]}\n"
        f"  in the walk but not the index: {only_walk[:5]}"
    )


def test_this_guard_is_ascii() -> None:
    """A hygiene guard that is itself dirty is a guard nobody can trust."""
    raw = Path(__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tests/test_css_html_ascii_hygiene.py has {len(non_ascii)} non-ASCII "
        f"byte(s); first at offset {non_ascii[0][0]}"
    )
