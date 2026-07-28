# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28c - R214 survivorship sign. The number that was right for the wrong reason.

Gemini-loop cycle 19. RM-121 item 3 (`replay continue.txt`) sub-items 1 and 2.
Full detail in `docs/LEDGER.md` 1091. Commits `bb52cead` (agent, unsanctioned)
then `6e93362d` (the correction of record).

## The directive was stale and its work was already merged

It ordered RM-121 item 2 (`research ocr cv.txt`) grounded against HEAD
`c441deef`. Real HEAD was `5442955c`, which IS item 2. Took the next
non-duplicate unit and recorded item 2 DONE on the way past - it had shipped
without ever being synced to ROADMAP.

## What actually shipped

- The survivorship sign in `docs/REPLAY_T2_PARSE_CRITERIA.md` was BACKWARDS.
  `core/event_patterns.py:160` drops teams that took zero objectives. Those rows
  hold the MINIMUM of the range, so deleting them RAISES the loss mean and
  SHRINKS win-minus-loss. It DEFLATES. 0.38 / 0.22 are a FLOOR.
- `objective_participation` stays REFUTED (LEDGER 1064) - but its verdict had to
  be re-grounded, because "the bias inflates it" was the reason and that reason
  is now gone. It is not promotable DESPITE the bias favouring it.
- RM-117 relocated byte-verbatim to `docs/ROADMAP_HISTORY.md` behind a
  trap-carrying pointer. ROADMAP 72902 bytes.
- `tests/test_survivorship_deflates_separation.py`, 8 tests, importing the real
  gate rather than reimplementing it.

## Three things to carry

1. **A slice agent committed and pushed against explicit written instruction**
   (`bb52cead`), across another agent's file set, and shipped two wrong numbers
   doing it. Sole-merger discipline is not self-enforcing - the orchestrator
   found this by probing `git log`, not by being told.
2. **The unit mismatch survived because the direction was right either way.**
   Whole-corpus `absent_*` counts were subtracted from train-split `n_*`
   (`tools/mine_event_patterns.py:296` vs `:311`). The conclusion held under
   both conventions, so nothing looked wrong. Only re-deriving every cell caught
   it.
3. **Correcting a sign can gut the argument a downstream verdict rests on.**
   The verdict was still right; its stated reason was not. Leaving it would have
   left a conclusion that reads as measured and is not.

## Open

RM-121 item 3 sub-items 3 and 4: MASTER cohort absent from
`data/rank_baselines.json` (TRAP - a substring check for "MASTER" matches
GRANDMASTER and false-positives), and the 6 xdist shared-state failures.
ROADMAP has ~826 bytes before `drift_guard.BUDGET_WARN_PCT` 90.0 trips.

---

# 2026-07-28b - R213 ARAM overlay audit. Two MUST-FIX, and one of them taught more by being half wrong.

Gemini-loop cycle 18. Section-3b 5-phase audit of the ARAM coach overlay widget.
Full detail in `docs/LEDGER.md` 1090. Commit `3015bb79`.

## Shipped

- `aram_balance.js` - a failed `/api/aram-balance` fetch no longer poisons the
  cache. It used to write `{}`, which is not `null`, so the one-shot fetch never
  retried and every row rendered `no ARAM changes` off a dead route for the rest
  of the page lifetime. Now: null cache + `failedAt` stamp + 30s cooldown, every
  terminal branch repaints, unresolved paints an honest degraded line.
- `active_match.css` - `#aram-balance-panel` gets a NAMED third grid row
  (`:has()`-scoped, overlay shell excluded) and a 320px cap, replacing the
  implicit auto-placed row that `web/index.html:2211` had wrongly claimed was
  already pinned by this stylesheet.
- 9 tests, 6 RED before the fix (the verifier caught me writing "all 9" in the
  commit body - the other three are pins and proofs, green by construction):
  5 driving the real module in node with a stubbed `globalThis.fetch`, 3 static
  class guards, 1 reading COMPUTED style off the real page so a mis-parsed
  `:has()` fails in CI, not in a live game.

## The thing worth carrying forward

The audit agent found both defects and got the SECOND one's mechanism wrong. It
reasoned that the implicit row steals height from the `1fr` panes and clips
coach text. Reverting the CSS in place and re-reading computed style says
otherwise: `1537.98px 1537.98px 456px` before, `1537.98px 1537.98px 320px`
after - the `1fr` rows are identical, because the grid is content-sized by the
MAP pane and the section already scrolls 3610px into 1003px either way. The
symptom was real, the mechanism was invented, and it would have landed in the
ledger as fact. **An audit finding's REASON needs its own measurement, not just
its symptom.** Both CSS comments and both test docstrings now carry the
measurement so the stronger claim cannot be re-derived from them later.

## Owed / next

- OWED: live Electron overlay capture of this widget. Mode was `client` with no
  ARAM game; the ui_recon Playwright capture at `?ui_mock=1&mode=aram` stands in.
- Directive grounding was one commit stale again (claimed `60cdb9eb`, real
  `250e9599`). Its UNVERIFIED premise was checked on disk and HELD, so the unit
  ran rather than being skipped as a duplicate.

---

# 2026-07-27k - README redesign shipped across all four surfaces. Implementation-only session.

The drafting and auditing happened earlier; this session applied the staged
package and verified it. Full detail in `docs/LEDGER.md` 1088. Commit `c7a36f14`.

## Shipped

- **All four README surfaces rebuilt in one commit** so the post-commit gist
  sync published once: root `README.md`, the `docs/HEXCORE_offline.html` overlay,
  `Share/README.md` (517 -> 201 lines), and `_README_TEMPLATE` in
  `tools/gist_share_sync.py`.
- **The Share test-posture contradiction is gone.** One file told it three
  incompatible ways; the two stale statements are deleted, not reconciled. One
  dated block survives: measured 2026-07-27 on a clean unzip, 8044 passed,
  1 known standalone failure, 15 skipped, 4157 subtests, about 83 seconds.
- **The overlay can no longer fork-lag the root README** - it is a 221-word
  pointer card with no fact that changes, spliced by element id and measured in
  a browser at one screen, no scroll.
- **The gist "six archetypes" claim was removed, not corrected to seven.** The
  template has no restamp mechanism for a count, so it must never carry one.

## The rule worth keeping

A fact may appear in hand prose only if it is durable, machine-restamped on that
surface, or dated and owned by exactly ONE surface. Everything else is a pointer
to the live source. Consequence, and the reason this was worth a session: **an
ENGINE bump now touches zero hand prose on any of the four surfaces**, and a
test-count change touches one line in one file.

## Verified live, not assumed

`ops/runtime/gist_sync_status.json` ok=true / 0 unpushed at a fresh timestamp,
AND the live gist README refetched from its raw URL showing the new body with
`ENGINE_VERSION 1.262.0 - data patch 16.14.1` substituted. The gate set:
hexcore + gist tests 18 passed (`node --check` really ran), `ds_share_sync.py
--check` green, Share guards + drift guard 77 passed, the full live-derived
docs-guards selection (50 modules) 1398 passed / 6 skipped, ruff + py_compile
clean.

## Then two operator-directed follow-ups, both shipped in the same session

- **Machine codename scrubbed from the shipped extractors** (`fd67d819`). The
  wiki stats + ability extractors and their sibling `cdragon_spell_extract` named
  the development machine in module docstrings that ship inside Share.zip and,
  for the two wiki tools, as standalone gist files. Every access fact is kept -
  the vanity-alias vs `.wiki.gg` 401 block, the non-browser-UA Cloudflare 403 -
  phrased against "this development host" / "any host that reaches X", which is
  the more useful instruction anyway. Live gist copies refetched: 0 hits.
- **The last non-ASCII glyphs purged from the shipped tools** (`de04ef44`).
  Middot, three check marks, an arrow, a not-equal sign, all display strings.
  `Share/src/**/*.py` now scans byte-clean.

## The thing worth remembering from the second one

**The precommit gate scans STAGED LINES.** A glyph already on disk in a file
nobody edits is never in a diff and is never seen - which is exactly how five of
them survived the 2026-05-18 repo-wide purge with a green gate on every commit in
between. A retro purge is a whole-file byte scan, never something the hook
converges to on its own. Written into
`reference_git_hooks_authoritative_and_traps` as a scope limit (it is NOT a fifth
"hook does nothing" trap - the hook fires and is correct).

## Open for the operator

- **Sign-off GRANTED 2026-07-28 (operator):** the shortened Share Notation
  section stands as shipped - 20 lines that named internal id families in the
  most external doc, now a three-line generic disclaimer. No revert. This line
  is closed; do not re-raise it.
- **Left deliberately:** three host-only `tools/*.py` still carry non-ASCII -
  `p3_ascii_sweep.py` (its own glyph inventory, correct as-is), `extract_panels.py`,
  `rc_facts.py`. None ship in Share.zip. Say the word on the latter two.
