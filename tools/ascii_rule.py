"""One reading of CLAUDE.md's 7-bit ASCII rule, shared by two hooks.

MAIN FIX 2026-10-21 1254 item #13. The rule had two readings: the PostToolUse
edit hook (tools/edit_lint_check.py) checked six glyphs, the commit gate
(tools/precommit_gate.py) every codepoint > 127. Two rules enforcing one
CLAUDE.md hard rule disagreed, and the looser one ran first. Both hooks now
import THIS module, so they cannot drift into two readings again.

The rule: authored text is 7-bit ASCII. Any codepoint > 127 is a hit; the six
historical glyphs keep their names (the commonest offenders, named so a hit
is actionable), every other one is reported as `U+XXXX (escape)`.

Population is the caller's business. The commit gate reads ADDED diff lines;
the edit hook reads the text the tool wrote. Neither re-flags a pre-existing
line nobody touched.

HOOK DEPENDENCY. Both hooks need this file beside them in tools/. The strip
helpers named by `fix_hint()` are NOT dependencies: the hint names them only
when they exist on disk (MAIN FIX 1254 #14).
"""

from __future__ import annotations

from pathlib import Path

# The six glyphs with a name. Spelled as chr() so this file stays ASCII.
NAMED = {
    chr(0x2014): "em-dash",
    chr(0x2013): "en-dash",
    chr(0x201C): "smart-dquote-open",
    chr(0x201D): "smart-dquote-close",
    chr(0x2018): "smart-quote-open",
    chr(0x2019): "smart-quote-close",
}

# ---------------------------------------------------------------------------
# REPO CONFIG - the surfaces the rule does not reach. Repo-relative, POSIX.
#
# Surfaces CLAUDE.md's retroactive purge deliberately did NOT sweep (immutable
# history / non-source), plus upstream DATA mirrors. DDragon and Meraki ship
# champion and item names RC does not author and cannot fix - gating them would
# block correct commits, and a gate that blocks correct work is one people
# learn to bypass.
EXEMPT_PARTS = ("logs/", "docs/_archive/", "__pycache__/", ".git/")
EXEMPT_SUFFIXES = (".jsonl", ".log", ".pyc", ".png", ".jpg", ".ico", ".zip")
# "data/" carries the DDragon / Meraki snapshots verbatim. They genuinely hold
# em-dashes and bullets from upstream, so gating them would apply an
# authored-content rule to content nobody here authored.
EXEMPT_PREFIXES = ("data/",)
# The two APPEND-ONLY RECORDS. Same class as docs/_archive/ above - they only
# live one directory up. Measured 2026-09-07: 3255 pre-existing non-ASCII
# characters between them, almost all status markers and arrows accumulated
# over months of appends. They never tripped the gate before because nobody
# EDITS those lines; the pre-public name scrub touched hundreds at once and the
# gate then blocked a commit whose every flagged glyph predated it. New
# authored prose anywhere else still gets the catch-all.
EXEMPT_FILES = ("docs/history_notes.md", "docs/LEDGER.md")

# Optional cleanup helpers, looked up beside this file (a test points it at an
# empty dir to prove an absent helper is never named).
_HELPER_DIR = Path(__file__).resolve().parent
_HELPERS = ("strip_em_dashes.py", "strip_smart_quotes.py")


def is_exempt(path: str) -> bool:
    """True when `path` (repo-relative) is a surface the rule does not reach."""
    p = (path or "").replace("\\", "/")
    if any(part in p for part in EXEMPT_PARTS):
        return True
    if p.endswith(EXEMPT_SUFFIXES):
        return True
    if p in EXEMPT_FILES:
        return True
    return p.startswith(EXEMPT_PREFIXES)


def hits(text: str, path: str = "") -> list[str]:
    """Sorted, de-duplicated names of every codepoint > 127 in `text`.

    The six NAMED glyphs report by name; anything else as
    `non-ascii U+XXXX (escape)`. An exempt `path` reports nothing - the six
    included: a DDragon champion name like Cho'Gath carries U+2019 upstream.

    History (the commit gate, WIDENED 2026-07-28): the six-glyph set let
    U+00D7 reach a committed agent6 health report and turned the suite red
    through a gate working exactly as written. The catch-all closed that.
    """
    if is_exempt(path):
        return []
    found = {NAMED[c] for c in text if c in NAMED}
    found |= {
        f"non-ascii U+{ord(c):04X} ({c.encode('unicode_escape').decode()})"
        for c in text
        if ord(c) > 127 and c not in NAMED
    }
    return sorted(found)


def line_hits(text: str, path: str = "") -> list[tuple[int, list[str]]]:
    """(1-based line number, hits) for every line of `text` with a hit."""
    if is_exempt(path):
        return []
    out: list[tuple[int, list[str]]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.isascii():
            out.append((lineno, hits(line)))
    return out


def fix_hint() -> str:
    """One-line repair advice. Helpers are named only when present, and only
    as OPTIONAL: neither hook runs or needs them (MAIN FIX 1254 #14)."""
    hint = ("Fix by hand in 7-bit ASCII: ' - ' for a clause break, '->' for an "
            "arrow, a word for a status glyph")
    present = [h for h in _HELPERS if (_HELPER_DIR / h).is_file()]
    if present:
        hint += "; optional helpers (not hook dependencies): " + ", ".join(
            "tools/" + h for h in present)
    return hint
