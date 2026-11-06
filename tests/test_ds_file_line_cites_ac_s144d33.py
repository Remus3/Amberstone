"""Guard: the wave 21 and changelog-tracking tests cite by symbol and text (ac).

Measured 2026-10-30 at ENGINE 1.290.0, re-deriving the RM-1053 "DS test
lines" residue over agents/daemon_slayer/tests. Two prose cites had drifted:

- ``test_cc_conditional_wave21.py`` said the COND_NTH_HIT "docstring" in
  ``cc_conditional.py`` sat at "line 190". The text it means is the comment
  directly under the ``COND_NTH_HIT = "nth_hit"`` constant (a comment, not a
  docstring), which had moved down to line 193;
- ``test_changelog_tracks_engine_version.py`` put its two mid-paragraph
  over-match examples at ``CHANGELOG.md:1691`` and ``:6979``. The CHANGELOG
  is prepended on every bump, so both had moved by well over a thousand
  lines. The quoted text is enough to find them.

The tests below pin the rewritten prose and the source facts it restates.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
WAVE21 = TESTS / "test_cc_conditional_wave21.py"
TRACKS = TESTS / "test_changelog_tracks_engine_version.py"
CC_MODULE = REPO / "agents" / "daemon_slayer" / "cc_conditional.py"
CHANGELOG = REPO / "agents" / "daemon_slayer" / "CHANGELOG.md"
TARGETS = (WAVE21, TRACKS)

_LINE_CITE = re.compile(r"(?<![\w.])\w+\.(?:py|md):\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%|-lines? (?=\d)")

WAVE21_PHRASE = (
    "The comment under the COND_NTH_HIT constant in cc_conditional.py "
    'EXPLICITLY names "Xin Zhao Q 3rd-attack knockup"'
)
TRACKS_PHRASES = (
    "over-matches TWICE on the live file: the prose "
    "\"16.13.1 (items['3040'] passive ...\" wraps onto its own line, and so "
    'does "1.25.0 (item 122). Engine-side math ...".',
)
CONTINUATIONS = (
    "16.13.1 (items['3040'] passive",
    "1.25.0 (item 122). Engine-side math",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _flat_comments(text: str) -> str:
    return _flat("\n".join(re.sub(r"^\s*# ?", "", line) for line in text.splitlines()))


def _hits(path: Path) -> list[str]:
    return [
        f"{path.name}:{n}: {line.strip()}"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]


def test_pattern_matches_the_old_shapes():
    for sample in (
        '      (line 190) EXPLICITLY named "Xin Zhao Q 3rd-attack knockup"',
        "# live file: CHANGELOG.md:1691 wraps the prose",
        '# onto its own line, and :6979 wraps "1.25.0 (item 122).',
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for sample in (WAVE21_PHRASE, *TRACKS_PHRASES):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    hits = [h for path in TARGETS for h in _hits(path)]
    assert not hits, "cite by symbol or quoted text, not line:\n" + "\n".join(hits)


def test_names_the_symbol_and_text():
    wave21 = _flat(WAVE21.read_text(encoding="utf-8"))
    assert WAVE21_PHRASE in wave21
    assert "tag's own docstring" not in wave21
    tracks = _flat_comments(TRACKS.read_text(encoding="utf-8"))
    for phrase in TRACKS_PHRASES:
        assert phrase in tracks, phrase


def test_comment_under_the_constant_names_xin_zhao_q():
    lines = CC_MODULE.read_text(encoding="utf-8").splitlines()
    start = lines.index('COND_NTH_HIT = "nth_hit"')
    comment = []
    for line in lines[start + 1:]:
        if not line.startswith("#"):
            break
        comment.append(line)
    assert "Xin Zhao Q 3rd-attack knockup" in _flat(" ".join(comment))


def test_quoted_continuations_are_mid_paragraph():
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    for prefix in CONTINUATIONS:
        found = [i for i, line in enumerate(lines) if line.startswith(prefix)]
        assert len(found) == 1, (prefix, found)
        assert lines[found[0] - 1].strip(), prefix
