"""P3 A3b-2 / item 426 - adaptation_hint coach-emit ASCII guard.

The champion-hint substrate (`format_hint_line`, `insight_card`) and the
diagnostic CLI used to emit U+2191/U+2193 trend arrows, a U+00B7 middot
separator (which `insight_card` also rsplit on to trim the clipboard card),
and U+2192 HOT/COLD arrows. Those were converted to ASCII (^/v/- and a
" | " separator) under the no-em-dash / ASCII-only repo rule, and the
middot separator was deliberately NOT mapped to "*" because the card is a
copy-to-clipboard / Discord-paste surface where "*text*" renders as italic.

This locks the two coach-emit modules ASCII so a future edit cannot
re-introduce a glyph that ships into a Haiku prompt, the dashboard, or a
pasted card. Scoped to these files on purpose - the wider P3 glyph sweep is
still in flight, so a repo-wide assertion would false-fail on un-swept files.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_FILES = [
    _ROOT / "coaches" / "adaptation_hint_champion.py",
    _ROOT / "coaches" / "adaptation_hint_cli.py",
]
_MIDDOT = chr(0x00B7)


def test_adaptation_hint_sources_are_pure_ascii():
    for f in _FILES:
        text = f.read_text(encoding="utf-8")
        bad = [
            (i + 1, ch)
            for i, line in enumerate(text.splitlines())
            for ch in line
            if ord(ch) > 0x7F
        ]
        assert not bad, f"{f.name} has non-ASCII glyphs: {bad[:10]}"


def test_insight_card_separator_is_discord_safe():
    # The trim boundary the card rsplits on must stay the " | " separator,
    # never "*" (italic in Discord) or the old U+00B7 middot.
    src = _FILES[0].read_text(encoding="utf-8")
    assert 'rsplit(" | ", 1)' in src
    assert '" | ".join(segs)' in src
    assert _MIDDOT not in src  # no middot anywhere
    assert 'rsplit(" * "' not in src  # never the markdown-italic char
