# RC2 P7.1 - ASCII-violation full sweep: verification + close

Stage 7.1 deliverable: prove the authored tree is swept clean of banned
non-ASCII, lock the clean state machine-side (including frozen files), and
document what remains by design. "Kill the startup warning" = no banned glyph
can lurk un-guarded, so no ASCII-violation warning can fire.

ASCII only. No em-dashes, en-dashes, or smart quotes.

## Banned set (the hard rule)

Per CLAUDE.md (2026-05-18) + tools/precommit_gate.py + the hygiene guards, the
banned codepoints in authored source are:

    U+2014 EM DASH        U+2013 EN DASH
    U+201C/U+201D smart double quotes
    U+2018/U+2019 smart single quotes
    U+2026 HORIZONTAL ELLIPSIS    U+00A0 NON-BREAKING SPACE

These are parse-hazard / operator-style violations. They are distinct from
FUNCTIONAL non-ASCII (see "Retained by design" below), which is operator
approved and load-bearing.

## Verified state (2026-06-20)

1. Banned set: ZERO occurrences across every tracked authored file EXCEPT the
   immutable root `_archive/2026-05-01-audit/` quarantine (CLAUDE.md: "NOT
   swept - immutable history / non-source"; the hygiene guards skip it).
   - Live tree incl. frozen files: clean (per-frozen scan, 0 banned bytes).
2. Safe glyph sweep residual = 0: `tools/p3_ascii_sweep.py --dry-run` (comments)
   and `--doc-dry` (docstrings) over core/dashboard/modes/app/lcu/tools +
   DS-engine + composition_advisor.py report 0 substitutions across 546 .py
   files. Prior DEEP-AUDIT P2/P3 cycles already swept every comment/docstring/
   log-string glyph; nothing sweepable remains.
3. Hygiene suite green: tests/test_smart_quote_hygiene.py +
   test_mojibake_hygiene.py + test_u2500_hygiene.py + test_ps1_encoding_hygiene.py
   = 15 passed.

## Enforcement tightened (P7.1)

tests/test_smart_quote_hygiene.py previously SKIPPED the frozen-file list in its
tree-wide banned-set walk. Operator greenlit "frozen INCLUDED" (2026-06-20,
TOP-10 #10). The skip is removed: the tree-wide walk now asserts on every
tracked authored file including frozen, and a new explicit regression lock
`test_frozen_files_clean_of_banned_glyphs` asserts each frozen file is clean.
Result: a banned glyph in a frozen file now fails CI/local pytest (the "startup
warning" cannot lurk un-guarded). Frozen files are clean today, so the change is
a green tightening, no sweep edit to any frozen file.

## Retained by design (NOT swept)

- Functional / load-bearing glyphs: DS-engine arrows (U+2192) and math (U+00D7,
  U+2212) inside emitted/regex-matched STRINGS; web/* UI render glyphs
  (box-drawing U+2500/U+2550, arrows, status emoji) in CSS/JS shown to the user.
  Sweeping these would change rendered output / engine behavior. Their own
  guards (test_u2500_hygiene.py) pin the intended set.
- Protective encodings: UTF-8 BOM on .ps1 (PS5.1 ANSI-mojibake guard);
  UTF-16 Task XML (canonical scheduled-task format).
- External data: DDragon / Meraki JSON mirrors (data/daemon_slayer/**,
  Share/src/data/**, data/meta/*) carry Riot punctuation verbatim; allowlisted.
- Immutable history: root `_archive/`, agents/agent6_auditor/reports/, logs,
  jsonl ledgers. Em-dash + mojibake there is operator-gated (E10 git-history
  rewrite), not authored-source drift.

## Scope vs E10

E10 (ASCII retro sweep across ALL files + git HISTORY rewrite + force-push) is a
separate operator-played stage. P7.1 closes the authored-source sweep + the
enforcement gap; E10 owns the history rewrite.
