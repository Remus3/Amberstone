# arch: 7-bit ASCII normalizer for cloud-routine audit reports | section=tools | frozen=no
"""Normalize ``agents/agent6_auditor/reports/`` to 7-bit ASCII.

WHY THIS EXISTS, AND WHY ``strip_smart_quotes.py`` IS NOT ENOUGH.

The files in that directory are authored by CLOUD SCHEDULED ROUTINES that
commit straight to main (author ``weekly-rc-health@anthropic-routines`` /
``weekly-ddragon-audit@anthropic-routines``). Those routines run in a fresh
clone where ``core.hooksPath`` is unset, so ``.githooks/`` and
``tools/precommit_gate.py`` never fire - CI is the only gate that ever sees
them, and by then the commit is already on main.

``tests/test_smart_quote_hygiene.py::test_agent6_reports_are_ascii`` is that
gate, and it has now gone red three times:

  * 2026-07-27 - three reports carrying U+2713, U+2014 and U+00D7 (58
    non-ASCII bytes), found by eye during an audit.
  * 2026-08-04 - one report shipping 24 U+2713 in a status column, which
    turned ``docs-guards`` RED on main.
  * 2026-08-25 - one report shipping 1 U+2014 and 8 U+2713 (27 bytes), which
    turned ``docs-guards`` red on the push and ``nightly-full-suite`` red on
    every scheduled run for the next four days.

The remediation the guard pointed at was ``tools/strip_smart_quotes.py
--apply``. That tool rewrites dashes, smart quotes, the ellipsis and NBSP -
and it does NOT know U+2713, which is the DOMINANT glyph these routines
emit (24 of 24 in the second incident, 8 of 9 distinct in the third). So the
prescribed fix could never actually clear the guard, and each occurrence was
repaired by hand. That is the defect this module closes: a mechanical fix
that covers the glyphs the routines really produce.

Scope is deliberately NARROW. These are generated status reports, not
authored prose, so ANY non-ASCII byte in this directory is a defect and a
mechanical normalisation is always correct here. Do not point this tool at
the wider repo - ``tools/strip_smart_quotes.py`` owns that, and it has the
mojibake context-sensitivity this one does not need.

Replacement happens in three tiers, most specific first:

  1. An explicit map for the decorative glyphs status reports actually use
     (check marks, ballot crosses, arrows, bullets, box drawing, warning
     signs, dashes, quotes). A check mark becomes ``OK`` and a cross becomes
     ``FAIL``, which is what the charter tells the routines to write.
  2. Unicode compatibility decomposition (NFKD) for anything else that has a
     faithful ASCII spelling - this catches accented letters, ligatures and
     the fullwidth forms without needing an entry each.
  3. Anything still non-ASCII is DROPPED, and every drop is reported by
     codepoint so a genuinely new glyph class is visible rather than silent.

This module keeps ITSELF 7-bit ASCII by spelling every glyph as ``chr(...)``
rather than the literal character, so it is not its own exclusion.

Usage:
    python tools/sanitize_agent6_reports.py            # report only
    python tools/sanitize_agent6_reports.py --check    # exit 1 if dirty (CI)
    python tools/sanitize_agent6_reports.py --apply    # rewrite in place
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "agents" / "agent6_auditor" / "reports"

# Tier 1: explicit spellings for the decoratives these routines emit.
# Keyed by codepoint so this file stays 7-bit ASCII.
GLYPH_MAP: dict[str, str] = {
    chr(0x2713): "OK",      # CHECK MARK           - the charter says write OK
    chr(0x2714): "OK",      # HEAVY CHECK MARK
    chr(0x2705): "OK",      # WHITE HEAVY CHECK MARK
    chr(0x2717): "FAIL",    # BALLOT X
    chr(0x2718): "FAIL",    # HEAVY BALLOT X
    chr(0x274C): "FAIL",    # CROSS MARK
    chr(0x26A0): "WARN",    # WARNING SIGN
    chr(0x00D7): "x",       # MULTIPLICATION SIGN  - "3 x 4", not a cross
    chr(0x2014): " - ",     # EM DASH
    chr(0x2013): " - ",     # EN DASH
    chr(0x2212): "-",       # MINUS SIGN
    chr(0x201C): '"',       # LEFT DOUBLE QUOTATION MARK
    chr(0x201D): '"',       # RIGHT DOUBLE QUOTATION MARK
    chr(0x2018): "'",       # LEFT SINGLE QUOTATION MARK
    chr(0x2019): "'",       # RIGHT SINGLE QUOTATION MARK
    chr(0x2026): "...",     # HORIZONTAL ELLIPSIS
    chr(0x00A0): " ",       # NO-BREAK SPACE
    chr(0x2192): "->",      # RIGHTWARDS ARROW
    chr(0x2190): "<-",      # LEFTWARDS ARROW
    chr(0x2194): "<->",     # LEFT RIGHT ARROW
    chr(0x2022): "-",       # BULLET
    chr(0x00B7): "-",       # MIDDLE DOT
    chr(0x2500): "-",       # BOX DRAWINGS LIGHT HORIZONTAL
    chr(0x2502): "|",       # BOX DRAWINGS LIGHT VERTICAL
    chr(0x2264): "<=",      # LESS-THAN OR EQUAL TO
    chr(0x2265): ">=",      # GREATER-THAN OR EQUAL TO
    chr(0x2248): "~=",      # ALMOST EQUAL TO
    chr(0x00B1): "+/-",     # PLUS-MINUS SIGN
}


def sanitize_text(text: str) -> tuple[str, dict[str, int], dict[str, int]]:
    """Return (ascii_text, mapped_counts, dropped_counts).

    ``mapped_counts`` and ``dropped_counts`` are keyed by ``U+XXXX`` so a
    caller can report exactly what moved without re-scanning.
    """
    mapped: dict[str, int] = {}
    dropped: dict[str, int] = {}
    out: list[str] = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
            continue
        key = f"U+{ord(ch):04X}"
        # Tier 1: explicit spelling.
        if ch in GLYPH_MAP:
            out.append(GLYPH_MAP[ch])
            mapped[key] = mapped.get(key, 0) + 1
            continue
        # Tier 2: compatibility decomposition down to ASCII.
        folded = unicodedata.normalize("NFKD", ch)
        ascii_folded = "".join(c for c in folded if ord(c) < 128)
        if ascii_folded:
            out.append(ascii_folded)
            mapped[key] = mapped.get(key, 0) + 1
            continue
        # Tier 3: no faithful ASCII spelling - drop, but never silently.
        dropped[key] = dropped.get(key, 0) + 1
    return "".join(out), mapped, dropped


def _offenders() -> list[Path]:
    if not REPORTS_DIR.is_dir():
        return []
    out = []
    for p in sorted(REPORTS_DIR.rglob("*")):
        if p.is_file() and any(b > 127 for b in p.read_bytes()):
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="rewrite offending files in place (atomic)")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any file carries a non-ASCII byte")
    args = ap.parse_args(argv)

    if not REPORTS_DIR.is_dir():
        print(f"sanitize_agent6_reports: {REPORTS_DIR} missing")
        return 0

    offenders = _offenders()
    if not offenders:
        print("sanitize_agent6_reports: clean - all reports are 7-bit ASCII")
        return 0

    for p in offenders:
        raw = p.read_bytes()
        n_bad = sum(1 for b in raw if b > 127)
        clean, mapped, dropped = sanitize_text(raw.decode("utf-8", errors="replace"))
        try:
            rel = p.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            # REPORTS_DIR can be pointed outside the repo (tests do this);
            # fall back to the absolute path rather than raising.
            rel = p.as_posix()
        detail = ", ".join(f"{k} x{v}" for k, v in sorted(mapped.items()))
        suffix = f" [{detail}]" if detail else ""
        print(f"  {rel}: {n_bad} non-ASCII byte(s){suffix}")
        if dropped:
            print("     DROPPED (no ASCII spelling): "
                  + ", ".join(f"{k} x{v}" for k, v in sorted(dropped.items())))
        if args.apply:
            # Atomic write, per the CLAUDE.md hard rule. Only non-ASCII
            # codepoints are touched, so CRLF line endings survive intact.
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(clean.encode("ascii"))
            tmp.replace(p)
            print("     rewritten -> 7-bit ASCII")

    if args.apply:
        print(f"sanitize_agent6_reports: rewrote {len(offenders)} file(s)")
        return 0

    print(f"sanitize_agent6_reports: {len(offenders)} file(s) carry non-ASCII. "
          "Fix with: python tools/sanitize_agent6_reports.py --apply")
    return 1 if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
